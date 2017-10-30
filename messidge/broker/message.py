# Copyright (c) 2017 David Preece, All rights reserved.
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


import cbor
import libnacl
import libnacl.utils
import logging


class BrokerMessage:
    """The server side message, markedly different to it's client side equivalent"""
    # For instance, it actually has a destination

    def __init__(self):
        self.is_encrypted = None
        self.emit_pipe = None
        self.emit_socket = None
        self.bulk = None
        self.params = None
        self.rid = None
        self.nonce = None  # needed for decryption, a new one gets made when encrypting
        self.command = None
        self.uuid = None

    @staticmethod
    def receive_socket(socket):
        # Receive a message from the socket.
        parts = socket.recv_multipart(copy=False)

        if len(parts) != 6:
            raise RuntimeError("Wrong number of parts in receive_socket")

        rtn = BrokerMessage()
        rtn.rid = bytes(parts[0].buffer)
        rtn.nonce = bytes(parts[1].buffer)
        rtn.command = bytes(parts[2].buffer)
        rtn.uuid = bytes(parts[3].buffer)
        rtn.params = bytes(parts[4].buffer)
        rtn.bulk = bytes(parts[5].buffer)
        rtn.is_encrypted = True  # unless it's an auth message, but auth deals with that
        rtn.emit_pipe = None
        rtn.emit_socket = None

        return rtn

    @staticmethod
    def receive_pipe(pipe, encrypted=False):
        # Receive a message from a multiprocessing pipe
        parts = pipe.recv()

        if len(parts) != 6:
            return None
        rtn = BrokerMessage()
        rtn.rid = parts[0]
        rtn.nonce = parts[1]
        rtn.command = parts[2]
        rtn.uuid = parts[3]
        rtn.params = parts[4]
        rtn.bulk = parts[5]
        rtn.is_encrypted = encrypted
        rtn.emit_pipe = None
        rtn.emit_socket = None

        return rtn

    def replyable(self):
        # Returns true if this message can be replied to (has a uuid)
        return self.uuid != b''

    def reply(self, results=None, bulk=None):
        # Called on an existing message, presumably a command to provide the results
        # You can store a message and call reply more than once
        if results is None:
            results = {}
        if bulk is not None:
            self.bulk = bulk

        if self.emit_pipe is not None:
            BrokerMessage.send_pipe(self.emit_pipe, self.rid, b'', b'', self.uuid, results, bulk=self.bulk)
            return

        if self.emit_socket is not None:
            BrokerMessage.send_socket(self.emit_socket, self.rid, b'', b'', self.uuid, results, bulk=self.bulk)
            return

        raise RuntimeError("Attempted to reply to a message without setting either emit pipe or socket")

    def forward(self):
        if self.emit_pipe is not None:
            self.forward_pipe(self.emit_pipe)
            return

        if self.emit_socket is not None:
            self.forward_socket(self.emit_socket)
            return

        raise RuntimeError("Attempted to forward a message without setting either emit pipe or socket")

    def encrypt(self, session_key):
        if self.is_encrypted:
            return
        self.nonce = libnacl.utils.rand_nonce()
        params_binary = cbor.dumps(self.params)
        self.params = libnacl.crypto_secretbox(params_binary, self.nonce, session_key)
        if self.bulk != b'':
            self.bulk = libnacl.crypto_secretbox(self.bulk, self.nonce, session_key)
        self.is_encrypted = True

    def decrypt(self, session_key):
        if not self.is_encrypted:
            return
        try:
            params_string = libnacl.crypto_secretbox_open(self.params, self.nonce, session_key)
            self.params = cbor.loads(params_string)
            if self.bulk != b'':
                self.bulk = libnacl.crypto_secretbox_open(self.bulk, self.nonce, session_key)
            self.is_encrypted = False
        except ValueError:
            logging.warning("Asked to decrypt a message but could not, session: " + str(self.rid))
            self.params = None
            self.bulk = b''

    def forward_socket(self, skt):
        BrokerMessage.send_socket(skt, self.rid, self.nonce, self.command, self.uuid, self.params, bulk=self.bulk)

    def forward_pipe(self, pipe):
        BrokerMessage.send_pipe(pipe, self.rid, self.nonce, self.command, self.uuid, self.params, bulk=self.bulk)

    @staticmethod
    def send_socket(socket, rid, nonce, command, uuid, params, bulk=b''):
        # Send a message to a client - easier to call send_cmd on the broker
        parts = BrokerMessage._parts_to_send(rid, nonce, command, uuid, cbor.dumps(params), bulk)
        socket.send_multipart(parts)

    @staticmethod
    def send_pipe(pipe, rid, nonce, command, uuid, params, bulk=b''):
        parts = BrokerMessage._parts_to_send(rid, nonce, command, uuid, params, bulk)
        pipe.send(parts)

    @staticmethod
    def _parts_to_send(rid, nonce, command, uuid, params, bulk):
        return [rid,
                nonce,
                command,
                uuid,
                params if params is not None else {},
                bulk]

    def __repr__(self):
        return "<broker.message.BrokerMessage object at %x (command=%s uuid=%s)>" % (id(self), self.command, self.uuid)
