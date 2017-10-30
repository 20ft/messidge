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

import libnacl
import libnacl.utils
import logging
from base64 import b64encode
from multiprocessing import Process, Pipe
from multiprocessing.connection import wait
from .message import BrokerMessage


class Agent(Process):
    """Multiprocess async encryption"""

    def __init__(self, rid, pk):
        super().__init__(target=self.run, name=b64encode(pk).decode())
        # basics
        self.rid = rid
        self.pk = pk
        self.session_key = libnacl.utils.salsa_key()

        # create the sockets to send work up here
        self.encrypt_pipe = Pipe()
        self.decrypt_pipe = Pipe()
        self.stop_pipe = Pipe()

        # go
        self.running = False
        self.start()

    def encrypted_session_key(self, nonce, secret_binary):
        return libnacl.crypto_box(self.session_key, nonce, self.pk, secret_binary)

    def stop(self):
        self.stop_pipe[0].send(b'')

    def run(self):
        self.running = True
        while self.running:
            try:
                ready_list = wait([self.encrypt_pipe[1], self.decrypt_pipe[1], self.stop_pipe[1]])
            except (KeyboardInterrupt, OSError):
                self._inner_stop()
                return

            for skt in ready_list:
                if skt == self.decrypt_pipe[1]:
                    msg = BrokerMessage.receive_pipe(self.decrypt_pipe[1], True)
                    msg.decrypt(self.session_key)
                    msg.forward_pipe(self.decrypt_pipe[1])
                    continue

                if skt == self.encrypt_pipe[1]:
                    msg = BrokerMessage.receive_pipe(self.encrypt_pipe[1], False)
                    msg.encrypt(self.session_key)
                    msg.forward_pipe(self.encrypt_pipe[1])
                    continue

                if skt == self.stop_pipe[1]:
                    self._inner_stop()

    def _inner_stop(self):
        if not self.running:
            return
        self.decrypt_pipe[0].close()
        self.decrypt_pipe[1].close()
        self.encrypt_pipe[0].close()
        self.encrypt_pipe[1].close()
        self.stop_pipe[0].close()
        self.stop_pipe[1].close()
        logging.debug("Stopped agent for rid: " + str(self.rid))
        self.running = False

    def state(self):
        return {'pk': b64encode(self.pk).decode()}

    def __repr__(self):
        return "<messidge.broker.Agent object at %x (rid=%s)>" % (id(self), self.rid)

