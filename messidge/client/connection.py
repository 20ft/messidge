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

import logging
import os
import libnacl
import libnacl.utils
import cbor
import psutil
import time
from threading import Thread
from _thread import allocate_lock, get_ident
from base64 import b64decode
import shortuuid
import zmq
from zmq.utils.monitor import recv_monitor_message
from .message import Message
from messidge import KeyPair, Waitable
from messidge.loop import Loop


class Connection(Waitable):
    """Connection onto Messidge broker."""

    # Is expecting ~/.messidge/ to contain keys named after the location to connect to (eg)
    # -rw-r--r--  1 dpreece  staff   45B Jul  8 16:36 localhost
    # -r--------  1 dpreece  staff   45B Jul  8 16:36 localhost.pub

    # skt is the main tcp socket from here to the location and belongs to the background thread
    # x_thread_socket is the "pickup" end of the per-thread sending sockets forwards to skt
    # Note that messages received are exclusively dealt with on the background thread

    def __init__(self, location: str=None, *, prefix='~/.messidge',
                 exit_on_exception=False, reflect_value_errors=False,
                 location_ip: str=None, keys: KeyPair=None, server_pk: str=None):
        """Instantiate a connection.

        :param location: The FQDN of the location to connect to.
        :param prefix: Directory for the client keys and server public keys.
        :param exit_on_exception: Causes the message loop to exit if there's an uncaught exception.
        :param reflect_value_errors: If True, raised ValueErrors will have their source messages replied to.
        :param location_ip: An override for the DNS resolution of 'location'. Useful for LAN and/or test connections.
        :param keys: An override for the key pair in the 'prefix' directory.
        :param server_pk: An override for the server public key in the 'prefix' directory."""
        super().__init__()
        self.connect_ip = location_ip if location_ip is not None else location
        self.location = location if location is not None else self.connect_ip
        self.keys = keys if keys is not None else KeyPair(location, prefix=prefix)
        self.inproc_name = "inproc://x_thread/" + str(id(self))
        self.session_key = None
        self.connect_callbacks = set()
        self.reflect_value_errors = reflect_value_errors
        self.exit_on_exception = exit_on_exception
        self.thread_skt = {}  # map from thread to the socket used to send messages on it's behalf
        self.rid = b''
        self.loop = None
        self.loop_block = allocate_lock()
        self.uuid_blockreply = {}
        self.uuid_blockresults = {}
        self.connected = False
        self.loop_thread = None

        # fetch the server's public key
        if server_pk is None:
            try:
                filename = os.path.expanduser(prefix + '/%s.spub' % location)
                with open(filename, 'r') as f:
                    server_pk = f.read().strip('\n')
            except FileNotFoundError:
                raise RuntimeError("There is no server public key in %s so cannot connect" % filename)
        self.server_public_binary = b64decode(server_pk)
        if len(self.server_public_binary) != 32:
            raise RuntimeError("The server public key record is broken.")

        # Threading
        zmq.Context.instance().set(zmq.IO_THREADS, psutil.cpu_count())
        logging.debug("ZeroMQ context IO threads: " + str(zmq.Context.instance().get(zmq.IO_THREADS)))

        # Prevent queued messages being sent instead of a handshake when reconnecting
        zmq.Context.instance().setsockopt(zmq.LINGER, 0)

        # Should be able to connect, then.
        self.loop_block.acquire()  # allows the thread to start and prepare but not actually run, yet.
        self.thread = Thread(target=self._start, name="Messidge background loop")
        self.thread.start()

    def start(self):
        """Start message loop - separate from __init__ so we get a chance to register_exclusive/register_commands"""
        self.loop_block.release()  # causes the block in _start to clear
        return self

    def wait_until_complete(self):
        """Blocks until the message loop exits"""
        self.thread.join()

        # re-raises (on the main thread) if the loop caught an exception
        if self.exception is not None:
            raise self.exception

    def disconnect(self):
        """Stop the message loop and disconnect - without this object cannot be garbage collected"""
        for thread_id in list(self.thread_skt.keys()):
            self.destroy_send_skt_for(thread_id)
        self.loop.stop()
        self.thread_skt.clear()
        self.connect_callbacks.clear()
        self.uuid_blockreply.clear()
        self.uuid_blockresults.clear()

    def _start(self):
        """The message loop runs on a background thread"""
        self.loop_thread = get_ident()

        # create the trunk socket - remember sockets must be created on the thread they are used on
        logging.info("Connecting to: %s:2020" % self.location)
        working = False
        while not working:
            try:
                self.skt = zmq.Context.instance().socket(zmq.DEALER)
                self.skt.setsockopt(zmq.LINGER, 0)
                self.skt.connect("tcp://%s:2020" % self.connect_ip)
                self.skt_monitor = self.skt.get_monitor_socket()
                working = True
            except zmq.error.ZMQError:
                del self.skt
                self.skt = None
                logging.info("Retrying ZMQ socket")
                time.sleep(1)
        logging.debug("Trunk socket is: %x" % id(self.skt))

        # create the cross thread socket for forwarding
        # since there can be more than one connection in the same process we need to give it a unique id
        self.x_thread_receive = zmq.Context.instance().socket(zmq.DEALER)
        self.x_thread_receive.bind(self.inproc_name)
        logging.debug("Cross-thread socket is: %x" % id(self.x_thread_receive))

        # kick off a message loop - has to be constructed on background thread
        self.loop = Loop(self.skt, exit_on_exception=self.exit_on_exception)
        self.loop.register_exclusive(self.skt_monitor, self._socket_event, comment="Socket events")
        self.loop.register_exclusive(self.x_thread_receive, self._fast_forward, comment="Cross thread socket")
        if self.reflect_value_errors:
            self.loop.on_value_error(self._background_thread_exception)

        # block until allowed to go by start()
        self.loop_block.acquire()
        self.mark_as_ready()
        self.loop.run()  # blocks until loop.stop is called or the loop catches a wayward exception
        self.exception = self.loop.caught_exception

        # Maybe the main thread was in wait_until_ready
        if self.exception is not None:
            self.unblock_and_raise(self.exception)

        # Maybe the main thread was in send_blocking_cmd
        for block in self.uuid_blockreply.values():
            block.release()

    def _socket_event(self, monitor_socket):
        # is this a connection event?
        event = recv_monitor_message(monitor_socket)
        if event['event'] == zmq.EVENT_DISCONNECTED:
            if len(self.uuid_blockreply) != 0:
                raise RuntimeError("Was disconnected from location with a blocking call still pending")
            logging.info("Have been disconnected from location. Wait...")
            self.connected = False
            return
        if event['event'] != zmq.EVENT_CONNECTED:
            return

        logging.info("Message queue connected")
        self.connected = True

        # send the encryption session request
        # the rid is used to show which session we *were* if reconnecting
        params = {'user': self.keys.public_binary(), 'rid': self.rid}
        parts = [b'', b'auth', b'', params, b'']
        binary = cbor.dumps(parts)
        self.skt.send(binary)
        try:
            in_binary = self.skt.recv()
            in_parts = cbor.loads(in_binary)
            if len(in_parts) != 3:
                raise ValueError("Authentication failed.")
            recv_nonce, enc_session_key, rid = in_parts
        except ValueError as e:
            self.unblock_and_raise(e)  # raises within a blocked wait_until_ready
            return

        # unwrap and set the session key
        try:
            if enc_session_key != b'':
                self.session_key = libnacl.crypto_box_open(enc_session_key, recv_nonce,
                                                           self.server_public_binary, self.keys.secret_binary())
                self.loop.set_crypto_params(self.session_key)
        except libnacl.CryptError:
            raise ValueError("Handshake failed.")
        self.rid = rid
        logging.info("Handshake completed")
        for callback in self.connect_callbacks:
            callback(self.rid)
        self.mark_as_ready()

    def send_skt(self):
        """Allocates (if necessary) a socket for the calling thread to send messages with."""
        thread = get_ident()

        # if this is the loop thread then we can use the main thread socket to send
        if thread is self.loop_thread:
            return self.skt

        try:
            return self.thread_skt[thread]
        except KeyError:
            # need a new socket
            new_skt = zmq.Context.instance().socket(zmq.DEALER)
            new_skt.connect(self.inproc_name)
            self.thread_skt[thread] = new_skt
            # logging.debug("Created a per-thread socket for: " + str(thread))
            return new_skt

    def destroy_send_skt(self):
        """Closes and removes the send_skt for the calling thread."""
        self.destroy_send_skt_for(get_ident())

    def destroy_send_skt_for(self, thread):
        try:
            self.thread_skt[thread].close()
            del self.thread_skt[thread]
            # logging.debug("Destroyed per-thread socket for: " + str(thread))
        except KeyError:
            pass

    def send_cmd(self, cmd: bytes, params=None, bulk: bytes=b'', uuid=b'', reply_callback=None):
        """Sends a command to the location, can route replies.

        :param cmd: the command.
        :param params: A {'key': 'value'} dictionary of parameters or ['list'].
        :param bulk: An optional piece of bulk data to transport.
        :param uuid: A uuid to attach to this command (so it can reply).
        :param reply_callback: Callback to fire when the command receives a reply - gets passed the message.
        """
        # BS check
        if self.loop is None:
            raise RuntimeError("The connection has no message loop - _start has not been called.")
        if cmd is None:
            raise RuntimeError("Need to pass a command to send_cmd.")

        # send
        if reply_callback is not None:
            # important that we register the expectation of a reply before asking the question
            if uuid is b'':
                uuid = shortuuid.uuid().encode()  # as bytes
            self.loop.register_reply(uuid, reply_callback)

        Message.send(self.send_skt(), cmd, self.session_key, params, uuid=uuid, bulk=bulk)

    def send_blocking_cmd(self, cmd: bytes, params=None, bulk: bytes=b'', timeout: float=120) -> Message:
        """Sends a command to the location and blocks waiting for a reply (which is returned).
        May raise ValueError exceptions.

        :param cmd: the command.
        :param params: A {'key': 'value'} dictionary of parameters or ['list'].
        :param bulk: An optional piece of bulk data to transport.
        :param timeout: In seconds.
        :return: The reply message.
        """
        thread = get_ident()
        if thread == self.loop_thread:
            raise RuntimeError("Cannot send a blocking command on the loop thread")

        # acquire a lock, wait for the reply
        uuid = shortuuid.uuid().encode()
        self.uuid_blockreply[uuid] = allocate_lock()
        self.uuid_blockreply[uuid].acquire()
        self.send_cmd(cmd, params, uuid=uuid, reply_callback=self._unblock, bulk=bulk)

        # when the background thread has an answer, the lock will release and we can continue
        if not self.uuid_blockreply[uuid].acquire(timeout=timeout):
            raise ValueError("Blocking call timed out: %s(%s)" % (cmd.decode(), str(params)))
        msg = self.uuid_blockresults[uuid]

        # clean up
        self.uuid_blockreply[uuid].release()
        del self.uuid_blockreply[uuid]
        del self.uuid_blockresults[uuid]

        # raise exceptions if either in the message or caught on a background thread
        if 'exception' in msg.params:
            raise ValueError(msg.params['exception'])
        if self.exception:
            raise self.exception
        return msg

    def register_commands(self, obj, commands):
        """Register a list of commands to be handled by the loop.

        :param obj: The object that will handle the commands.
        :param commands: A dict of the form {b'command': handler, ...}."""
        while self.loop is None:
            os.sched_yield()  # loop creation has not yet had a timeslice
        self.loop.register_commands(self.skt, obj, commands)

    def register_connect_callback(self, callback):
        """Register a callback to be fired once the connection is complete.

        :param callback: the object.method to call - is passed the connection rid."""
        self.connect_callbacks.add(callback)

    def unregister_connect_callback(self, callback):
        """Unregister a callback to be fired once the connection is complete.

        :param callback: the object.method to cancel."""
        try:  # may have already been disconnected as part of object shutting down
            self.connect_callbacks.remove(callback)
        except KeyError:
            pass

    def location_name(self) -> str:
        """Outside access to the name/address of this location.

        :return: The FQDN of the location as a string."""
        return self.location

    def _fast_forward(self, skt):
        binary = skt.recv()
        self.skt.send(binary)

    def _unblock(self, msg: Message):
        try:
            self.uuid_blockresults[msg.uuid] = msg  # msg is stored first
            self.uuid_blockreply[msg.uuid].release()
            self.loop.unregister_reply(msg.uuid)
        except KeyError:
            logging.error("Message from a blocking call arrived late (ignored): " + str(msg))

    def _background_thread_exception(self, e, msg):
        """Call from non-main threads to return a value error to the client"""
        if msg.replyable():
            msg.reply(self.send_skt(), {"exception": str(e)})
            logging.info("Client called %s and raised a ValueError: %s" % (msg.command.decode(), str(e)))
        else:
            logging.warning("Unable to return ValueError to client: " + str(e))

    def __repr__(self):
        return "<messidge.client.connection.Connection object at %s (location=%s)>" % (id(self), self.location)


def cmd(required_params, *, needs_reply=False):
    """Create the internal structure describing a command

    :param required_params: A list of parameters that must be included with the command.
    :param needs_reply: The message needs to be replied to (and must have a uuid)."""
    return required_params, needs_reply
