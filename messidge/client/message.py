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

# uuid is used to identify replies to commands including long running replies (with more than one reply)
# identifiers for everything else are to be passed explicitly in the params (as strings, because of json)

import cbor
import libnacl
import libnacl.utils
import logging


class Message:
    def __init__(self, session_key=None):
        self.command = None
        self.uuid = None
        self.params = None
        self.bulk = None
        self.session_key = session_key  # here so we can reply to a message without knowledge of the session itself

    @staticmethod
    def receive(socket, session_key):
        """Pulls one message off the socket, decrypts and returns it.

        :param socket: The ZMQ socket to receive from.
        :param session_key: The session key for this connection.
        :return: The received and decrypted message."""
        # parts are command, uuid, params, bulk
        rtn = Message(session_key)
        binary = socket.recv()
        parts = cbor.loads(binary)
        nonce = bytes(parts[0])
        rtn.command = bytes(parts[1])
        rtn.uuid = bytes(parts[2])
        try:
            rtn.params, rtn.bulk = Message.decrypted_params(parts[3],
                                                            parts[4],
                                                            nonce,
                                                            session_key)
        except TypeError:
            pass
        
        # logging.debug("Message.receive (%s:%s:%s)" %
        #               (rtn.uuid.decode(),
        #                rtn.command.decode(),
        #                list(rtn.params.keys()) if isinstance(rtn.params, dict) else "--"))
        return rtn

    @staticmethod
    def from_persist(parts):
        """Creates a message from four previously persisted parts.

        :param parts: The four parts.
        :return: The constructed message."""
        rtn = Message()
        rtn.command = parts[0]
        rtn.uuid = parts[1]
        rtn.params = parts[2]
        rtn.bulk = parts[3]
        return rtn

    def for_persist(self) -> []:
        """Create a list of four parts that can be used to recreate this message.

        :return: A four element list that can be used to persist the message."""
        return [self.command, self.uuid, self.params, self.bulk]

    def replyable(self) -> bool:
        """Can this message be replied to?

        :return: True/False"""
        return self.uuid != b''

    def reply(self, socket, results=None, bulk=b'', *, long_term=False):
        """Reply to a previously received message.

        :param socket: the socket to use to send the message.
        :param results: an optional dictionary of results to include as part of the reply.
        :param bulk: an optional bulk data blob.
        :param long_term: optionally keep this channel open for more replies."""
        if not self.replyable():
            logging.warning("Tried to reply to a non-replyable message: " + str(self))
            return

        # logging.debug("Message.reply: (%s:%s:%s)" %
        #               (self.uuid.decode(),
        #                self.command.decode(),
        #                list(results.keys()) if isinstance(results, dict) else "--"))
        if results is None:
            results = {}
        Message.send(socket, b'ka' if long_term else b'',
                     self.session_key, results, uuid=self.uuid, bulk=bulk, trace=False)

    def forward(self, socket):
        """Forward a message unchanged through another socket.

        :param socket: the socket to use to forward the message."""
        Message.send(socket, self.command, self.session_key, self.params, uuid=self.uuid, bulk=self.bulk)

    @staticmethod
    def send(socket, command, session_key, params=None, *, uuid=b'', bulk=b'', trace=True):
        """Send a command to the location. Can be called directly but much better to use Connection.send_cmd.

        :param socket: socket to use to send the message.
        :param command: the command as a binary string.
        :param session_key: The session key for this connection.
        :param params: An optional {'key': 'value'} dictionary of parameters or ['list'].
        :param uuid: An optional uuid to attach to the message. This is what makes messages replyable.
        :param bulk: An optional piece of bulk data to transport.
        :param trace: Set to false to disable debug logging on this occasion.
        """
        # if trace:
        #     logging.debug("Message.send: (%s:%s:%s)" %
        #                   (uuid.decode(),
        #                    command.decode(),
        #                    list(params.keys()) if isinstance(params, dict) else "--"))
        if params is None:
            params = {}
        nonce = libnacl.utils.rand_nonce()
        params_encrypted, bulk_encrypted = Message.encrypted_params(params, bulk, nonce, session_key)
        parts = [nonce,
                 command,
                 uuid,
                 params_encrypted,
                 bulk_encrypted]
        binary = cbor.dumps(parts)
        socket.send(binary)

    @staticmethod
    def encrypted_params(params, bulk, nonce, session_key) -> (bytes, bytes):
        """Returns the encrypted form of the passed parameter dictionary and bulk data.

        :param params: The parameter dictionary.
        :param bulk: The bulk data.
        :param nonce: The n-once for this message.
        :param session_key: The session key for this connection.
        :return: A (bytes, bytes) tuple for the encrypted params and bulk data.
        """
        if session_key is not None:
            params_encrypted = libnacl.crypto_secretbox(cbor.dumps(params), nonce, session_key)
            bulk_encrypted = libnacl.crypto_secretbox(bulk, nonce, session_key) if bulk != b'' else b''
            return params_encrypted, bulk_encrypted
        else:
            return params, bulk

    @staticmethod
    def decrypted_params(params, bulk, nonce, session_key):
        """Returns the decrypted form of the passed parameter dictionary and bulk data.

        :param params: The parameter dictionary.
        :param bulk: The bulk data.
        :param nonce: The n-once for this message.
        :param session_key: The session key for this connection.
        :return: A (bytes, bytes) tuple for the decrypted params and bulk data.
        """
        if session_key is not None:
            try:
                params_plaintext = libnacl.crypto_secretbox_open(params, nonce, session_key)
                bulk_plaintext = libnacl.crypto_secretbox_open(bulk, nonce, session_key) if bulk != b'' else b''
                return cbor.loads(params_plaintext), bulk_plaintext
            except TypeError as e:
                print("decrypted_params fail: %s, %X, %X" % (params, nonce, session_key))
                exit(1)
        else:
            return params, bulk

    def __repr__(self):
        return "<messidge.message.Message object at %x (command=%s uuid=%s params=%s)>" % \
               (id(self), self.command, str(self.uuid), self.params)
