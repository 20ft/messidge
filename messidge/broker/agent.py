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
import os
from multiprocessing import Process, Pipe
from multiprocessing.connection import wait
from .message import BrokerMessage


class Agent(Process):
    """Subprocess async encryption"""

    def __init__(self):
        super().__init__(target=self.run)
        # create the sockets to send work up here
        self.encrypt_pipe = Pipe()
        self.decrypt_pipe = Pipe()
        self.stop_pipe = Pipe()

        # go
        self.running = False
        self.start()

    def encrypted_session_key(self, session_key, nonce, pk, secret_binary):
        return

    def stop(self):
        self.stop_pipe[0].send(b'')

    def run(self):
        # raise my priority
        os.setpriority(os.PRIO_PROCESS, 0, -15)

        # run a message loop
        self.running = True
        while self.running:
            try:
                ready_list = wait([self.encrypt_pipe[1], self.decrypt_pipe[1], self.stop_pipe[1]])
            except (KeyboardInterrupt, OSError):
                self._inner_stop()
                return

            for skt in ready_list:
                try:
                    if skt == self.decrypt_pipe[1]:
                        msg = BrokerMessage.receive_pipe(self.decrypt_pipe[1], True)
                        msg.decrypt()
                        msg.forward_pipe(self.decrypt_pipe[1])
                        continue
                except OSError:  # the pipe gets closed at an inappropriate moment
                    continue

                try:
                    if skt == self.encrypt_pipe[1]:
                        msg = BrokerMessage.receive_pipe(self.encrypt_pipe[1], False)
                        msg.encrypt()
                        msg.forward_pipe(self.encrypt_pipe[1])
                        continue
                except OSError:
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
        self.running = False
