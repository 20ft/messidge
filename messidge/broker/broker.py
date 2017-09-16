# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/

# This is the top level object and message broker

# Note that commands that get called and raise a ValueError have the exception passed back to the caller


import logging
import random
from base64 import b64encode
from lru import LRU
import os

import zmq
import cbor
from zmq.utils.monitor import recv_monitor_message
from .identity import AccountConfirmationServer
from .agent import Agent
from .auth import Authenticate

from ..loop import Loop
from .message import BrokerMessage


class Broker:
    def __init__(self, keys, identity, model, node_type, session_type, controller, commands, *,
                 base_port=2020, pre_run_callback=None, session_recovered_callback=None, session_destroy_callback=None):
        """Initialise with location and the private/secret key pair"""
        # Basic structure
        self.keys = keys
        self.model = model
        self.controller = controller
        self.commands = commands
        self.node_type = node_type
        self.session_type = session_type
        self.session_recovered_callback = session_recovered_callback
        self.session_destroy_callback = session_destroy_callback
        self.pre_run_callback = pre_run_callback
        self.base_port = base_port
        self.skt = None  # initialised when run
        self.skt_monitor = None
        self.fd_rid = {}  # map from file descriptor to remote id so we know who has disconnected
        self.fd_pipe = {}
        self.rid_agent = {}
        self.node_rid_pk = {}
        self.node_pk_rid = {}
        self.local_replies = {}  # map from uuid to function call
        self.forward_replies = LRU(1024)  # map from msg.uuid to rid so we can forward replies
        self.identity = identity
        self.authenticator = Authenticate(identity, self.keys)
        self.account_confirm = AccountConfirmationServer(identity, self.keys, base_port + 1)
        self.loop = None
        self.next_connection_rid = None

        # Threading
        zmq.Context.instance().set(zmq.IO_THREADS, os.cpu_count())

    def run(self):
        """Call on the main thread, creates the 'background' thread that actually does all the work."""
        # the server socket
        self.skt = zmq.Context.instance().socket(zmq.ROUTER)
        self.skt.set_hwm(0)  # infinite, don't drop or block because that would be bad
        self.skt.setsockopt(zmq.LINGER, 0)  # drop waiting packets if a client disconnects
        try:
            self.skt.bind("tcp://*:" + str(self.base_port))
        except zmq.error.ZMQError:
            raise RuntimeError("Cannot bind zmq listen socket, exiting")
        self.set_next_rid()

        # Set up the message loop
        self.loop = Loop(self.skt, message_type=BrokerMessage)
        self.loop.register_exclusive(self.skt, self._event_socket, "Events")
        self.loop.register_exclusive(self.skt.get_monitor_socket(), self._monitor, "Socket monitor for events")

        # Client hookups...
        if self.pre_run_callback is not None:
            self.pre_run_callback()

        # Go
        logging.info("Started broker: 0.0.0.0:" + str(self.base_port))
        self.loop.run()

    def stop(self):
        self.identity.stop()  # confirmation server just bins out when we exit (a daemon thread)
        self.loop.stop()

    # sending a fresh command
    def send_cmd(self, rid, cmd, params=None, bulk=b'', uuid=b'', local_reply=None):
        if local_reply is not None and uuid is not b'':
            self.local_replies[uuid] = local_reply
        try:
            agent = self.rid_agent[rid]
        except KeyError:
            logging.warning("Failed sending command, no agent for rid: " + str(rid))
            return
        if agent is None:
            BrokerMessage.send_socket(self.skt, rid, cmd, uuid, params, bulk)
        else:
            BrokerMessage.send_pipe(agent.encrypt_pipe[0], rid, cmd, uuid, params, bulk)

    # give the next connection a unique (but known) routing id
    def set_next_rid(self):
        """Set the routing id for the next socket that connects"""
        self.next_connection_rid = bytes([random.randint(0, 255) for _ in range(0, 4)])
        logging.debug("Set next rid to: " + str(self.next_connection_rid))
        self.skt.set(zmq.CONNECT_RID, self.next_connection_rid)

    def disconnect_for_rid(self, rid, is_definitely_user=False):
        # Remove the crypto agent
        agent = None
        try:
            agent = self.rid_agent[rid]
            del self.rid_agent[rid]  # both users and nodes have rid_agent mappings (nodes are just None)
            if agent is not None:  # a user
                agent.stop()
                agent.join()
                self.loop.unregister_exclusive(agent.encrypt_pipe[0].fileno())
                self.loop.unregister_exclusive(agent.decrypt_pipe[0].fileno())
                del self.fd_pipe[agent.encrypt_pipe[0].fileno()]
                del self.fd_pipe[agent.decrypt_pipe[0].fileno()]
        except KeyError:
            logging.debug("While disconnecting rid could not find agent or None: " + str(rid))

        # Remove the right objects
        if agent is None and not is_definitely_user:
            self._disconnect_node(rid)
        else:
            self._disconnect_user(rid)

    def _handshake(self, msg, skt):
        # gets called via the event loop just like everything else
        # because this is the handshake message it's not actually encrypted
        # NOTE that if this falls over the client may/will become jammed and unable to reconnect
        if msg.command != b'auth':
            logging.debug("Not a handshake message, dropped: " + str(msg.command))
            return False, None
        try:
            msg.params = cbor.loads(msg.params)
        except BaseException:
            logging.debug("Handshake message failed to unpack params: " + str(msg.command))
            return False, None

        # authenticate
        # msg = self.persistent.resolve_alias(msg)  # TODO
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
        if msg.params['rid'] in self.model.sessions:  # pre-existing session
            # Update rids so the session now has the new rid
            session = self.model.sessions[msg.params['rid']]
            logging.info("Recovering session: " + str(msg.params['rid']))
            del self.model.sessions[msg.params['rid']]
            session.rid = msg.rid  # so now the session "belongs" to the new rid
            for fd, old_rid in self.fd_rid.items():
                if old_rid == msg.params['rid']:
                    self.fd_rid = msg.rid
            if self.session_recovered_callback is not None:
                self.session_recovered_callback(session, msg.params['rid'])
        else:
            # if an alias is connecting then it will need the original pk to be used because encryption
            session = self.session_type(msg.rid, pk, msg.params['nonce'])
            self.model.sessions[msg.rid] = session
            resources = self.model.resources(pk)

        self.model.sessions[msg.rid] = session
        self.model.create_session_record(session)
        logging.info("Connected session: " + str(msg.rid))

        # create the encryption agent
        # we register the filenumber because zmq.poll won't poll a pipe object (but it will for a descriptor)
        agent = Agent(msg.rid, pk, msg.params['nonce'])
        self.loop.register_exclusive(agent.encrypt_pipe[0].fileno(),
                                     self._emit_encrypted, "Encryption pipe, agent=" + str(msg.rid))
        self.loop.register_exclusive(agent.decrypt_pipe[0].fileno(),
                                     self._event_pipe, "Decryption pipe, agent=" + str(msg.rid))
        self.fd_pipe[agent.encrypt_pipe[0].fileno()] = agent.encrypt_pipe[0]
        self.fd_pipe[agent.decrypt_pipe[0].fileno()] = agent.decrypt_pipe[0]
        logging.debug("Encrypt pipe for rid: %s -> %s" % (str(msg.rid), agent.encrypt_pipe[0].fileno()))
        logging.debug("Decrypt pipe for rid: %s -> %s" % (str(msg.rid), agent.decrypt_pipe[0].fileno()))
        self.rid_agent[msg.rid] = agent

        # send the session key to the other end
        parts = [msg.rid, agent.encrypted_session_key(self.keys.secret_binary()), msg.rid]
        skt.send_multipart(parts)

        # maybe create a resource offer
        if resources is not None:
            BrokerMessage.send_pipe(agent.encrypt_pipe[0], msg.rid, b'resource_offer', b'', resources)

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
        parts = [msg.rid, b'', msg.rid]
        skt.send_multipart(parts)
        return None

    def _monitor(self, skt):
        """Catches the file descriptor opening and closing"""
        evt = recv_monitor_message(skt)
        descriptor = evt['value']
        if evt['event'] == zmq.EVENT_ACCEPTED:  # the handshake will sort itself out
            logging.debug("Received a connection: %s -> %s" % (descriptor, str(self.next_connection_rid)))
            self.fd_rid[descriptor] = self.next_connection_rid

        # disconnection
        if evt['event'] == zmq.EVENT_DISCONNECTED:
            if descriptor not in self.fd_rid:
                logging.warning("Caught disconnection from a fd that has no connection to a rid: " + str(descriptor))
                return
            else:
                logging.debug("Caught disconnection: " + str(descriptor))

            rid = self.fd_rid[descriptor]
            del self.fd_rid[descriptor]
            self.disconnect_for_rid(rid)

    def _disconnect_node(self, rid):
        # removing a node
        try:
            pk = self.node_rid_pk[rid]
        except KeyError:
            logging.debug("Can't disconnect node, gone already: " + str(rid))
            return

        del self.node_rid_pk[rid]
        del self.node_pk_rid[pk]
        del self.model.nodes[pk]
        logging.info("Node disconnected: " + b64encode(pk).decode())

    def _disconnect_user(self, rid):
        """Disconnect a single session - fires a callback"""
        try:
            sess = self.model.sessions[rid]
        except KeyError:
            logging.debug("Closing session not held in the model, ignoring: " + str(rid))
            return
        sess.close(self)
        logging.info("Session disconnected: " + str(rid))

        if self.session_destroy_callback is not None:
            self.session_destroy_callback(sess)
        del self.model.sessions[rid]

    # Entrypoint for events that have come in over zmq
    def _event_socket(self, skt):
        # receive from the socket
        try:
            msg = BrokerMessage.receive_socket(skt)
        except RuntimeError as e:
            logging.info("Something bad happened with a message coming over a socket: " + str(e))
            return

        # since it came in from "outside" it will be plaintext if it came from a node
        try:
            agent = self.rid_agent[msg.rid]  # may be None, but still a valid (node) connection
            if agent is None:  # a node
                msg.params = cbor.loads(msg.params)
                msg.emit_socket = skt
            else:  # a user
                # send to be decrypted
                msg.forward_pipe(agent.decrypt_pipe[0])
                return

        # If a new connection.....
        except KeyError:
            success, agent = self._handshake(msg, skt)
            if not success:  # authentication failed
                msg.params = dict()
                msg.forward_socket(skt)
                return
            self.set_next_rid()
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
            logging.error("Encryption agent could not decrypt: " + str(agent))
            self.disconnect_for_rid(msg.rid)
            return

        # all good
        msg.emit_pipe = agent.encrypt_pipe[0]
        self._event(msg)

    def _event(self, msg):
        """Top level handler for incoming events"""
        # at this point we know the message is plaintext and will have either emit_pipe or emit_socket set
        # ensure we have all the necessary parameters then forward, call the handler, validate, whatever
        try:
            # is this a reply we're supposed to be forwarding?
            if msg.uuid in self.forward_replies:
                msg.rid = self.forward_replies[msg.uuid]
                # socket to forward to a node in plaintext, else send via a pipe to be encrypted
                if msg.rid in self.node_rid_pk:
                    msg.emit_socket = self.skt
                else:
                    try:
                        msg.emit_pipe = self.rid_agent[msg.rid].encrypt_pipe[0]
                        msg.forward()
                    except KeyError:
                        logging.debug("Wanted to send a message reply to a disconnected session (dropped).")
                return

            # are we supposed to  be forwarding it locally?
            if msg.uuid in self.local_replies:
                self.local_replies[msg.uuid](msg)
                return

            # validate data if it hasn't come from a node
            if msg.rid not in self.node_rid_pk:

                # if there is a claim to be a certain user it needs validating
                if 'user' in msg.params:
                    if not isinstance(msg.params['user'], bytes):
                        raise ValueError("Send user pk in binary")
                    user = b64encode(msg.params['user']).decode()
                    if msg.rid not in self.rid_agent:
                        raise ValueError("Claimed user not initialised: " + user)
                    if self.rid_agent[msg.rid].pk != msg.params['user']:
                        raise ValueError("Claimed user pk is wrong: " + user)
                    logging.debug("Validated claim to be user: " + user)

                # if there is a claim to be a certain session it needs validating
                if 'session' in msg.params:
                    if msg.params['session'] != msg.rid:
                        raise ValueError("Claimed session value is wrong: " + str(msg.command))
                    logging.debug("Validated claim to be session: " + str(msg.params['session']))

            # if this is a message that laksa can deal with, call the controller
            if msg.command in self.commands:
                self._check_basic_properties(msg)
                getattr(self.controller, '_' + msg.command.decode())(msg)
                return

            # forwarding to the node
            try:
                node_pk = msg.params['node']
                del msg.params['node']  # don't need to send this to the node itself
                # record the source rid to reply the message to
                if msg.replyable():
                    self.forward_replies[msg.uuid] = msg.rid
                # set the rid to the node and forward
                msg.rid = self.node_pk_rid[node_pk]
                msg.forward_socket(self.skt)
            except KeyError:
                raise ValueError("No node address or invalid: " + str(msg.command))

        except ValueError as e:
            logging.warning("Client %s called %s and threw a ValueError: %s" %
                            (str(msg.rid), str(msg.command), str(e)))
            try:
                msg.reply({"exception": str(e)})
            except BaseException as e:
                logging.error("Failed while attempting to forward a value error - str(e) failed.")
                raise e

    def _check_basic_properties(self, msg):
        """Helper utility to bounce missing/clearly-wrong properties before they do a bad thing"""

        # is this a broker command, is it expecting a reply and can we send it?
        try:
            command = msg.command
            if self.commands[command][1]:  # Needs reply
                msg.raise_if_cant_reply()
            if self.commands[command][2]:  # Needs to have come from a node
                if msg.rid not in self.node_rid_pk:
                    raise ValueError("This call is for nodes only")
        except KeyError:
            # not a broker command, assume passing through (node value has already been checked)
            return  # no need to check params, we know message is not for the broker

        # have all the parameters for the command been sent?
        necessary_params = self.commands[msg.command][0]
        for necessary in necessary_params:
            if necessary not in msg.params:
                raise ValueError("Necessary parameter was not passed: " + necessary)

    def _emit_encrypted(self, fd):  # called when pipe 'fd' has an encrypted message ready to send
        try:
            pipe = self.fd_pipe[fd]
            parts = pipe.recv()
        except EOFError:
            logging.error("EOF while receiving in _emit_encrypted: " + str(fd))
            return
        self.skt.send_multipart(parts)

    def __repr__(self):
        return "<messidge.broker.Broker object at %x>" % id(self)


class ModelMinimal:
    def __init__(self):
        self.nodes = {}
        self.sessions = {}

    # overload if you want to make a resource offer to the client
    def resources(self, pk):
        return None

    # overload these if you want to make persistent sessions
    def create_session_record(self, sess):
        pass

    def update_session_record(self, sess):
        pass

    def delete_session_record(self, sess):
        pass


class NodeMinimal:
    def __init__(self, pk):
        self.pk = pk


class SessionMinimal:
    def __init__(self, rid, pk, nonce):
        self.rid = rid
        self.pk = pk
        self.nonce = nonce
        self.old_rid = rid  # for use with reconnection

    # overload to free resources - can use passed broker to send commands to nodes
    def close(self, broker):
        pass

