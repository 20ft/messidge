# Copyright (c) 2017 David Preece - davep@polymath.tech, All rights reserved.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# This is the top level object and message broker

# Note that commands that get called and raise a ValueError have the exception passed back to the caller


import logging
import random
import libnacl.utils
from base64 import b64encode
from binascii import hexlify
import os

import zmq
import cbor
from zmq.utils.monitor import recv_monitor_message
from .identity import Identity, AccountConfirmationServer
from .agent import Agent
from .auth import Authenticate

from .. import KeyPair
from ..loop import Loop
from .message import BrokerMessage


class Broker:
    """The broker is the top level object for creating a server/broker."""

    def __init__(self, keys: KeyPair, model, node_type, session_type, controller, *, base_port: int=2020,
                 identity_type=Identity, auth_type=Authenticate, account_confirm_type=AccountConfirmationServer,
                 pre_run_callback=None, node_destroy_callback=None,
                 session_recovered_callback=None, session_destroy_callback=None,
                 forwarding_insert_callback=None, forwarding_evict_callback=None):
        """:param keys: Server public/secret keys.
        :param model: Model object (derived from ModelMinimal).
        :param node_type: Class to construct node objects with (derived from NodeMinimal).
        :param session_type: Class to construct session objects with (derived from SessionMinimal).
        :param controller: Controller object (derived from ControllerMinimal).
        :param base_port: TCP port to use plus the next one (so default is 2020 and 2021).
        :param identity_type: Potentially custom class to construct an identity server (see identity.py).
        :param auth_type: Class to authenticate with.
        :param account_confirm_type: Class to use for confirming client accounts.
        :param pre_run_callback: Fired last thing before the message loop starts.
                                 ...signature ()
        :param node_destroy_callback: Fired last thing before a node is destroyed (was disconnected, say).
                                      ...signature (rid)
        :param session_recovered_callback: Fired with the new rid when a session reconnects.
                                           ...signature (session, old_rid, new_rid)
        :param session_destroy_callback: Fired last thing before a session is destroyed.
                                         ...signature (rid)
        :param forwarding_insert_callback: Called when a new entry is made into the forwarding map.
                                           ...signature (key, value)
        :param forwarding_evict_callback: Called when an entry is removed from the forwarding map.
                                          ...signature (key, value)

        The eviction of an entry from the map is not to be used as an indication that an object has been destroyed,
        it may be considerably after destruction or not at all.
        """
        # Basic structure
        self.keys = keys
        self.model = model
        self.controller = controller
        self.commands = controller.commands
        self.node_type = node_type
        self.session_type = session_type
        self.session_recovered_callback = session_recovered_callback
        self.session_destroy_callback = session_destroy_callback
        self.node_destroy_callback = node_destroy_callback
        self.pre_run_callback = pre_run_callback
        self.base_port = base_port
        self.skt = None  # initialised when run
        self.skt_monitor = None
        self.fd_rid = {}  # map from file descriptor to remote id so we know who has disconnected
        self.fd_pipe = {}
        self.rid_agent = {}
        self.node_rid_pk = {}
        self.node_pk_rid = {}
        self.short_term_forwards = {}
        self.forwarding_insert_callback = forwarding_insert_callback
        if forwarding_evict_callback:
            model.long_term_forwards.set_callback(forwarding_evict_callback)
        self.identity = identity_type()
        self.authenticator = auth_type(self.identity, self.keys)
        self.account_confirm = account_confirm_type(self.identity, self.keys, base_port + 1)
        self.loop = None
        self.next_connection_rid = None

        # Threading
        zmq.Context.instance().set(zmq.IO_THREADS, os.cpu_count())
        logging.debug("ZeroMQ context IO threads: " + str(zmq.Context.instance().get(zmq.IO_THREADS)))

    def run(self):
        """Call on the main thread, creates the background thread that actually does all the work."""
        # the server socket
        self.skt = zmq.Context.instance().socket(zmq.ROUTER)
        self.skt.set_hwm(0)  # infinite, don't drop or block because that would be bad
        self.skt.setsockopt(zmq.LINGER, 0)  # drop waiting packets if a client disconnects
        try:
            self.skt.bind("tcp://*:" + str(self.base_port))
        except zmq.error.ZMQError:
            logging.error("Cannot bind socket - is there an instance of the broker running already?")
            raise RuntimeError("Cannot bind zmq listen socket, exiting")
        self.set_next_rid()

        # Set up the message loop
        self.loop = Loop(self.skt, message_type=BrokerMessage, exit_on_exception=True)
        self.loop.register_exclusive(self.skt, self._event_socket, comment="Events")
        self.loop.register_exclusive(self.skt.get_monitor_socket(), self._monitor, comment="Socket monitor for events")

        # Client hookups...
        if self.pre_run_callback is not None:
            self.pre_run_callback()

        # Go
        logging.info("Started broker: 0.0.0.0:" + str(self.base_port))
        self.loop.run()

    def stop(self):
        """Stop background threads. Must be called to allow garbage collection and for a clean exit."""
        # DO NOT explicitly disconnect user sessions
        # for rid in list(self.fd_rid.values()):
        #     self.disconnect_for_rid(rid, is_definitely_user=True)

        # Disconnect nodes
        for rid in list(self.node_pk_rid.values()):
            self.disconnect_for_rid(rid)
        if self.loop is not None:  # if can't bind socket, bins out before loop is constructed
            self.loop.stop()

    def send_cmd(self, rid, command: bytes, params: dict, *, bulk: bytes=b'', uuid: bytes= b''):
        """Send command to either a node or user

        :param rid: the routing identifier to send the message to.
        :param command: a byte string of the command to send.
        :param params: A {'key': 'value'} dictionary of parameters to send.
        :param bulk: An optional piece of bulk data to transport.
        :param uuid: A uuid to attach to this command (so it can reply).
        """
        try:
            agent = self.rid_agent[rid]
        except KeyError:
            logging.debug("Failed sending command, no agent for rid: " + hexlify(rid).decode())
            self.disconnect_for_rid(rid)
            return

        # agent is None implies unencrypted
        if agent is None:
            BrokerMessage.send_socket(self.skt, rid, b'', command, uuid, params, bulk)
        else:
            BrokerMessage.send_pipe(agent.encrypt_pipe[0], rid, b'', command, uuid, params, bulk)

    def set_next_rid(self):
        """Set the routing id for the next socket that connects."""
        # gives the next connection a unique (but known) routing id
        self.next_connection_rid = bytes([random.randint(0, 255) for _ in range(0, 4)])
        logging.debug("Set next rid to: " + hexlify(self.next_connection_rid).decode())
        self.skt.set(zmq.CONNECT_RID, self.next_connection_rid)

    def disconnect_for_rid(self, rid):
        """Disconnect a client.

        :param rid: routing id for the client to disconnect."""
        # Remove the crypto agent
        agent = None
        try:
            agent = self.rid_agent[rid]
            del self.rid_agent[rid]  # both users and nodes have rid_agent mappings (nodes map to None)
            if agent is not None:  # a user
                agent.stop()
                agent.join()
                self.loop.unregister_exclusive(agent.encrypt_pipe[0].fileno())
                self.loop.unregister_exclusive(agent.decrypt_pipe[0].fileno())
                del self.fd_pipe[agent.encrypt_pipe[0].fileno()]
                del self.fd_pipe[agent.decrypt_pipe[0].fileno()]
        except KeyError:
            logging.debug("While disconnecting rid could not find agent or None: " + hexlify(rid).decode())
            self._disconnect_session(rid)

        # Remove the right objects
        if agent is not None:
            self._disconnect_session(rid)
        else:
            self._disconnect_node(rid)
        del agent

    def _handshake(self, msg, skt):
        # gets called via the event loop just like everything else
        # because this is the handshake message it's not actually encrypted
        # NOTE that if this falls over the client may/will become jammed and unable to reconnect
        if msg.command != b'auth':
            logging.debug("Not a handshake message, dropped: " + str(msg.command))
            return False, None

        # authenticate
        success, user, config = self.authenticator.auth(msg)
        if not success:
            logging.warning("There was a protocol-correct failure to authenticate: " +
                            b64encode(msg.params['user']).decode())
            return False, None

        # create the session - the 'create session' calls reply to the handshake message
        agent = None
        if user:
            return True, self._create_user_session(msg, skt, config)
        else:
            return True, self._create_node_session(msg, skt, config)

    def _create_user_session(self, msg, skt, config):
        # are we reconnecting to a persisted session? params['rid'] refers to the rid it *used* to be
        # tag words: recover, rewrite, map
        pk = msg.params['user']
        resources = None
        session = None
        if msg.params['rid'] in self.model.sessions:  # pre-existing session
            # Update rids so the session now has the new rid
            session = self.model.sessions[msg.params['rid']]
            logging.info("Recovering session: %s -> %s" %
                         (hexlify(msg.params['rid']).decode(), hexlify(msg.rid).decode()))
            del self.model.sessions[msg.params['rid']]
            self.model.delete_session_record(msg.params['rid'])
            session.rid = msg.rid  # so now the session "belongs" to the new rid
            for fd, old_rid in self.fd_rid.items():
                if old_rid == msg.params['rid']:
                    self.fd_rid[fd] = msg.rid
            self.model.sessions[msg.rid] = session
            self.model.create_session_record(session)  # don't factor out, the callback needs to be called AFTER
            if self.session_recovered_callback is not None:
                self.session_recovered_callback(session, msg.params['rid'], msg.rid)
        else:
            # if an alias is connecting then it will need the original pk to be used because encryption
            session = self.session_type(msg.rid, pk)
            self.model.sessions[msg.rid] = session
            self.model.create_session_record(session)

        resources = self.model.resources(pk)
        logging.info("Connected session: " + hexlify(msg.rid).decode())

        # create the encryption agent
        # we register the filenumber because zmq.poll won't poll a pipe object (but it will for a descriptor)
        agent = Agent(msg.rid, pk)
        self.loop.register_exclusive(agent.encrypt_pipe[0].fileno(),
                                     self._emit_encrypted, comment="Encryption, agent=" + hexlify(msg.rid).decode())
        self.loop.register_exclusive(agent.decrypt_pipe[0].fileno(),
                                     self._event_pipe, comment="Decryption, agent=" + hexlify(msg.rid).decode())
        self.fd_pipe[agent.encrypt_pipe[0].fileno()] = agent.encrypt_pipe[0]
        self.fd_pipe[agent.decrypt_pipe[0].fileno()] = agent.decrypt_pipe[0]
        logging.debug("Encrypt pipe for rid: %s -> %s" % (hexlify(msg.rid).decode(), agent.encrypt_pipe[0].fileno()))
        logging.debug("Decrypt pipe for rid: %s -> %s" % (hexlify(msg.rid).decode(), agent.decrypt_pipe[0].fileno()))
        self.rid_agent[msg.rid] = agent

        # send the session key to the other end
        nonce = libnacl.utils.rand_nonce()
        parts = [nonce, agent.encrypted_session_key(nonce, self.keys.secret_binary()), msg.rid]
        binary = cbor.dumps(parts)
        skt.send_multipart((msg.rid, binary))

        # maybe create a resource offer
        if resources is not None:
            BrokerMessage.send_pipe(agent.encrypt_pipe[0], msg.rid, b'', b'resource_offer', b'', resources)

        return agent

    def _create_node_session(self, msg, skt, config):
        pk = msg.params['user']
        # this might be a node reconnecting
        try:
            old_rid = self.node_pk_rid[pk]  # will throw a key error if this is a fresh connection
            del self.node_rid_pk[old_rid]  # pk_rid gets overwritten so doesn't need deleting
            self.node_rid_pk[msg.rid] = pk
            self.node_pk_rid[pk] = msg.rid
            logging.info("Reconnected node: " + b64encode(pk).decode())

        except KeyError:
            # a node connecting for the first time
            node = self.node_type(pk, msg, config)
            self.model.nodes[pk] = node
            self.node_rid_pk[msg.rid] = pk
            self.node_pk_rid[pk] = msg.rid
            logging.info("Connected node pk: " + b64encode(pk).decode())

        # send a blank session key so the connection knows it's not encrypted
        parts = [b'', b'', msg.rid]
        binary = cbor.dumps(parts)
        skt.send_multipart((msg.rid, binary))
        return None

    def _monitor(self, skt):
        # Catches the file descriptor opening and closing
        evt = recv_monitor_message(skt)
        descriptor = evt['value']
        if evt['event'] == zmq.EVENT_ACCEPTED:  # the handshake will sort itself out
            logging.debug("Received a connection: %s -> %s" % (descriptor, hexlify(self.next_connection_rid).decode()))
            self.fd_rid[descriptor] = self.next_connection_rid

        # disconnection
        if evt['event'] == zmq.EVENT_DISCONNECTED:
            if descriptor not in self.fd_rid:
                logging.warning("Caught disconnection from a fd that has no connection to a rid")
                return
            else:
                logging.debug("Caught disconnection: " + str(descriptor))

            rid = self.fd_rid[descriptor]
            del self.fd_rid[descriptor]
            self.disconnect_for_rid(rid)

    def _disconnect_node(self, rid):
        # removing a node
        pk = b''
        try:
            pk = self.node_rid_pk[rid]
            del self.node_rid_pk[rid]
            del self.node_pk_rid[pk]
            del self.model.nodes[pk]
        except KeyError:
            logging.debug("Closing node not held in the model: " + hexlify(rid).decode())

        if self.node_destroy_callback is not None:
            self.node_destroy_callback(rid)
        logging.info("Node disconnected: " + b64encode(pk).decode())

    def _disconnect_session(self, rid):
        # Disconnect a single session - fires a callback
        try:
            sess = self.model.sessions[rid]
            sess.close(self)
            del self.model.sessions[rid]
        except KeyError:
            logging.debug("Closing session not held in the model: " + hexlify(rid).decode())

        if self.session_destroy_callback is not None:
            self.session_destroy_callback(rid)
        logging.info("Session disconnected: " + hexlify(rid).decode())

    # Entrypoint for events that have come in over zmq
    def _event_socket(self, skt):
        # receive from the socket
        try:
            msg = BrokerMessage.receive_socket(skt)
        except BaseException as e:
            logging.info("Something bad happened with a message coming over a socket: " + str(e))
            return

        # since it came in from "outside" it will be plaintext if it came from a node
        try:
            agent = self.rid_agent[msg.rid]  # may be None, but still a valid (node) connection
            if agent is None:  # a node
                msg.emit_socket = skt
            else:  # a user
                # send to be decrypted
                msg.forward_pipe(agent.decrypt_pipe[0])
                return

        # If a new connection.....
        except KeyError:
            self.set_next_rid()
            success, agent = self._handshake(msg, skt)
            if not success:  # authentication failed
                msg.params = dict()
                msg.forward_socket(skt)
                return
            self.rid_agent[msg.rid] = agent  # may be None but marks the rid as being valid anyway
            return

        self._event(msg)

    def _event_pipe(self, fd):  # called when pipe 'fd' has a message it wants to inject into the event loop (decrypted)
        # receive from the pipe
        pipe = self.fd_pipe[fd]
        try:
            msg = BrokerMessage.receive_pipe(pipe)
        except BaseException:
            logging.info("Something bad happened with a message coming over a pipe: " + str(pipe))
            return

        # this may be a cry for help from the encryption agent
        agent = self.rid_agent[msg.rid]
        if msg.params is None and msg.bulk is None:
            logging.error("Encryption agent could not decrypt: " + hexlify(agent).decode())
            self.disconnect_for_rid(msg.rid)
            return

        # all good
        msg.emit_pipe = agent.encrypt_pipe[0]
        self._event(msg)

    def _event(self, msg):
        # at this point we know the message is plaintext and will have either emit_pipe or emit_socket set
        # ensure we have all the necessary parameters then forward, call the handler, validate, whatever
        try:
            # we can only have params be a dict at this point
            if not isinstance(msg.params, dict):
                raise ValueError("Message parameters must be a dictionary.")

            # is this a reply we're supposed to be forwarding?
            if msg.uuid in self.short_term_forwards or msg.uuid in self.model.long_term_forwards:
                try:
                    msg.rid = self.short_term_forwards[msg.uuid]
                    del self.short_term_forwards[msg.uuid]
                    logging.debug("Short term forwarded: " + msg.uuid.decode())
                except KeyError:
                    pass  # must be in the long term reply map

                # does this message want to be part of a long term reply?
                if msg.command == b'ka':  # i.e. keep-alive
                    msg.command = b''
                    if msg.rid in self.rid_agent:
                        if msg.uuid not in self.model.long_term_forwards:
                            logging.debug("Long term forwarding: %s -> %s" % (msg.uuid.decode(), hexlify(msg.rid).decode()))
                            self.model.long_term_forwards[msg.uuid] = msg.rid
                            self.forwarding_insert_callback(msg.uuid, msg.rid)  # persists
                        else:
                            logging.debug("Long term forwarded: " + msg.uuid.decode())
                            msg.rid = self.model.long_term_forwards[msg.uuid]
                    else:
                        logging.debug("Message wanted long term forwarding but session has gone: " +
                                      hexlify(msg.rid).decode())
                        return

                # if forwarding to a session, try to do so now
                if msg.rid not in self.node_rid_pk:
                    try:
                        msg.emit_pipe = self.rid_agent[msg.rid].encrypt_pipe[0]
                        msg.forward()
                    except KeyError:
                        logging.debug("Wanted to send a message reply to a disconnected session: " + msg.uuid.decode())
                    return

                # message will be forwarded to a node in plaintext
                msg.emit_socket = self.skt
                msg.forward()
                return

            # now we're either dealing with a command or forwarding it to the node so let's add some context
            logging.debug('Event: ' + msg.command.decode())
            if msg.rid in self.node_rid_pk:
                msg.params['node'] = self.node_rid_pk[msg.rid]
                logging.debug("...apparently came from node: " + b64encode(msg.params['node']).decode())
            elif msg.rid in self.rid_agent and self.rid_agent[msg.rid] is not None:
                msg.params['user'] = self.rid_agent[msg.rid].pk
                msg.params['session'] = msg.rid
                logging.debug("...apparently came from session: " + hexlify(msg.rid).decode())

            # if this is a message that laksa can deal with, call the controller
            if msg.command in self.commands:
                self._check_basic_properties(msg)
                getattr(self.controller, '_' + msg.command.decode())(msg)
                return

            # forwarding to the node
            try:
                # cache node_pk (don't need to send this to the node itself)
                node_pk = msg.params['node']
                del msg.params['node']

                # record the source rid so we can forward replies
                if msg.replyable():
                    logging.debug("Short term forwarding: %s -> %s" %
                                  (msg.uuid.decode(), hexlify(msg.rid).decode()))
                    self.short_term_forwards[msg.uuid] = msg.rid

                # set the rid to the node and forward
                msg.rid = self.node_pk_rid[node_pk]
                msg.forward_socket(self.skt)

            except KeyError:
                raise ValueError("No node address or invalid: " + str(msg.command))

        except ValueError as e:
            logging.info("Client %s called %s and raised a ValueError: %s" %
                         (hexlify(msg.rid).decode(), msg.command.decode(), str(e)))
            try:
                msg.reply({"exception": str(e)})
            except BaseException as e:
                logging.error("Failed while attempting to forward a value error - str(e) failed.")
                raise e

    def _check_basic_properties(self, msg):
        # Helper utility to bounce missing/clearly-wrong properties before they do a bad thing

        # is it expecting a reply and can we send it?
        try:
            try:
                necessary_params, needs_reply, node_only = self.commands[msg.command]
            except ValueError as e:
                raise RuntimeError("Problem unpacking the command structure - you have all three values?: " + str(e))
            if needs_reply and not msg.replyable():
                raise ValueError("Message needs to be replyable for: " + str(msg.command))
            if node_only and msg.rid not in self.node_rid_pk:
                raise ValueError("This call is for nodes only")
        except KeyError:
            # not a broker command, assume passing through (node value has already been checked)
            return  # no need to check params, we know message is not for the broker

        # have all the parameters for the command been sent?
        for necessary in necessary_params:
            if necessary not in msg.params:
                raise ValueError("Necessary parameter was not passed: " + necessary)

    def _emit_encrypted(self, fd):
        # called when pipe 'fd' has an encrypted message ready to send
        try:
            pipe = self.fd_pipe[fd]
            rid, parts = pipe.recv()
        except EOFError:
            logging.error("EOF while receiving in _emit_encrypted: " + str(fd))
            return
        binary = cbor.dumps(parts)
        self.skt.send_multipart((rid, binary))

    def __repr__(self):
        return "<messidge.broker.Broker object at %x>" % id(self)


def cmd(required_params, *, needs_reply=False, node_only=False):
    """Create the internal structure describing a command

    :param required_params: A list of parameters that must be included with the command.
    :param needs_reply: The message needs to be replied to (and must have a uuid).
    :param node_only: The message can only have originated from a node."""
    if 'user' in required_params or 'session' in required_params:
        raise RuntimeError('"user" and "session" are reserved parameter names')
    return required_params, needs_reply, node_only
