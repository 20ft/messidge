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

import os
from sys import stderr
from _thread import allocate_lock
from http.client import HTTPConnection
from base64 import b64decode, b64encode
from libnacl.public import SecretKey


class KeyPair:
    """Holds a public/secret key pair as base 64 - bytes not strings"""

    def __init__(self, name=None, prefix='~/.messidge', public=None, secret=None):
        # initialised the 'usual' way?
        self.public = public
        self.secret = secret
        if public is not None and secret is not None:
            return
        if name is None:
            return
        if prefix is None:
            raise RuntimeError("Prefix cannot be None")

        # we are fetching the keys
        expand = os.path.expanduser(prefix)
        try:
            with open(expand + '/' + name + ".pub", 'rb') as f:
                self.public = f.read()
        except FileNotFoundError:
            raise RuntimeError("No public key found, halting")
        try:
            with open(expand + '/' + name, 'rb') as f:
                self.secret = f.read()
        except FileNotFoundError:
            raise RuntimeError("No private key found, halting")

    def public_binary(self):
        return b64decode(self.public)

    def secret_binary(self):
        return b64decode(self.secret)

    @staticmethod
    def new(name=None, prefix='~/.messidge'):
        """Create a new random key pair"""
        keys = SecretKey()
        rtn = KeyPair()
        rtn.public = b64encode(keys.pk)
        rtn.secret = b64encode(keys.sk)

        # are we persisting them?
        if name is not None and prefix is not None:
            expand = os.path.expanduser(prefix)
            os.makedirs(expand, exist_ok=True)
            with open(expand + '/' + name + ".pub", 'w+b') as f:
                f.write(rtn.public)
            with open(expand + '/' + name, 'w+b') as f:
                f.write(rtn.secret)

        return rtn

    def __repr__(self):
        return "<messidge.Keys object at %x (pk=%s)>" % (id(self), self.public)


def default_location(prefix='~/.messidge'):
    try:
        with open(os.path.expanduser(prefix + '/default_location'), 'r') as f:
            return f.read().strip('\n')
    except FileNotFoundError:
        raise RuntimeError("""There is no default_location file so cannot choose default location.""")


def create_account(location, token, prefix='~/.messidge'):
    # The new key pair (will be written to disk)
    keys = KeyPair.new(name=location, prefix=prefix)

    # Let the server know
    conn = HTTPConnection(location, 2021)
    try:
        conn.request('POST', '/', token + " " + keys.public.decode())
    except ConnectionRefusedError:
        print("Server refused connection - please ensure the location address is correct", file=stderr)
        exit(1)
    reply = conn.getresponse().read().decode()

    # failed?
    if reply[:5] == 'Fail:':
        print(reply, file=stderr)
        exit(1)

    # write out the default location and server public key
    directory = os.path.expanduser(prefix) + '/'
    os.makedirs(directory, exist_ok=True)
    with open(directory + 'default_location', 'w') as f:
        f.write(location)
    with open(directory + location + '.spub', 'w') as f:
        f.write(reply)


class Waitable:
    def __init__(self, locked=True):
        self.wait_lock = allocate_lock()
        self.exception = None
        if locked:
            self.wait_lock.acquire()

    def __del__(self):
        if self.wait_lock.locked():
            self.wait_lock.release()

    def wait_until_ready(self, timeout=120):
        """Blocks waiting for a (normally asynchronous) update indicating the object is ready.

        Note this also causes exceptions that would previously have been raised on the background thread
        to be raise on the calling (i.e. main) thread."""
        # this lock is used for waiting on while uploading layers, needs to be long
        self.wait_lock.acquire(timeout=timeout)
        self.wait_lock.release()
        if self.exception:
            raise self.exception
        return self

    def mark_as_ready(self):
        if self.wait_lock.locked():
            self.wait_lock.release()

    def unblock_and_raise(self, exception):
        # releases the lock but causes the thread in 'wait_until_ready' to raise an exception
        self.exception = exception
        self.mark_as_ready()
