"""Copyright (c) 2017 David Preece, All rights reserved.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""

# uuid is used to identify replies to commands including long running replies (with more than one reply)
# identifiers for everything else are to be passed explicitly in the params (as strings, because of json)

import cbor
import libnacl
import logging


class Message:
    def __init__(self):
        self.command = None
        self.uuid = None
        self.params = None
        self.bulk = None
        self.nonce = None
        self.session_key = None

    @staticmethod
    def receive(socket, nonce, session_key):
        """Pulls one message off the socket, decrypts and returns"""
        # parts are command, uuid, params, bulk
        rtn = Message()
        parts = socket.recv_multipart(copy=False)
        rtn.command = bytes(parts[0].buffer)
        rtn.uuid = bytes(parts[1].buffer)
        rtn.params, rtn.bulk = Message.decrypted_params(bytes(parts[2].buffer),
                                                        bytes(parts[3].buffer),
                                                        nonce,
                                                        session_key)
        rtn.nonce = nonce
        rtn.session_key = session_key
        logging.debug("Message.receive (%s:%s:%s)" %
                      (rtn.uuid.decode(),
                       rtn.command.decode(),
                       list(rtn.params.keys()) if isinstance(rtn.params, dict) else "--"))
        return rtn

    @staticmethod
    def from_persist(parts):
        """Creates a message previously stored as a list of 6"""
        rtn = Message()
        rtn.command = parts[0]
        rtn.uuid = parts[1]
        rtn.params = parts[2]
        rtn.bulk = parts[3]
        rtn.nonce = parts[4]
        rtn.session_key = parts[5]
        return rtn

    def for_persist(self):
        """Create a list of 6 objects that can be used to recreate this message"""
        return [self.command, self.uuid, self.params, self.bulk, self.nonce, self.session_key]

    def replyable(self):
        """Can this message be replied to?"""
        return self.uuid != b''

    def reply(self, socket, results=None, bulk=b''):
        """Reply to a previously received message."""
        if not self.replyable():
            logging.warning("Tried to reply to a non-replyable message: " + str(self))
            return

        logging.debug("Message.reply: (%s:%s:%s)" %
                      (self.uuid.decode(),
                       self.command.decode(),
                       list(results.keys()) if isinstance(results, dict) else "--"))
        if results is None:
            results = {}
        Message.send(socket, b'', self.nonce, self.session_key, results, uuid=self.uuid, bulk=bulk, trace=False)

    def forward(self, socket):
        """Forward a message unchanged down another socket"""
        Message.send(socket, self.command, self.nonce, self.session_key, self.params, uuid=self.uuid, bulk=self.bulk)

    @staticmethod
    def send(socket, command, nonce, session_key, params=None, uuid=b'', bulk=b'', trace=True):
        """Send a command to the location."""
        # Can be called directly but much better to use Connection.send_cmd
        if trace:
            logging.debug("Message.send: (%s:%s:%s)" %
                          (uuid.decode(),
                           command.decode(),
                           list(params.keys()) if isinstance(params, dict) else "--"))
            # str(traceback.extract_stack(None, 3)[0])[14:-1]))
        if params is None:
            params = {}
        params_encrypted, bulk_encrypted = Message.encrypted_params(params, bulk, nonce, session_key)
        parts = [command,
                 uuid,
                 params_encrypted,
                 bulk_encrypted]
        socket.send_multipart(parts)

    @staticmethod
    def encrypted_params(params, bulk, nonce, session_key):
        if session_key is not b'':
            params_encrypted = libnacl.crypto_secretbox(cbor.dumps(params), nonce, session_key)
            bulk_encrypted = libnacl.crypto_secretbox(bulk, nonce, session_key) if bulk != b'' else b''
            return params_encrypted, bulk_encrypted
        else:
            return cbor.dumps(params), bulk

    @staticmethod
    def decrypted_params(params, bulk, nonce, session_key):
        if session_key is not b'':
            params_plaintext = libnacl.crypto_secretbox_open(params, nonce, session_key)
            bulk_plaintext = libnacl.crypto_secretbox_open(bulk, nonce, session_key) if bulk != b'' else b''
            return cbor.loads(params_plaintext), bulk_plaintext
        else:
            return cbor.loads(params), bulk

    def __repr__(self):
        return "<messidge.message.Message object at %x (command=%s uuid=%s params=%s)>" % \
               (id(self), self.command, str(self.uuid), self.params)
