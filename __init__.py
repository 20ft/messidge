"""
Copyright (c) 2017 David Preece, All rights reserved.

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

import os
from sys import stderr
from http.client import HTTPConnection
from base64 import b64decode, b64encode
from libnacl.public import SecretKey


class KeyPair:
    """Holds a public/secret key pair as base 64 - bytes not strings"""

    def __init__(self, name=None, prefix='~/.20ft', public=None, secret=None):
        self.public = public
        self.secret = secret
        if name is None:
            return

        # we are also fetching the keys
        expand = os.path.expanduser(prefix)
        try:
            with open(expand + '/' + name + ".pub", 'rb') as f:
                self.public = f.read()[:-1]
        except FileNotFoundError:
            raise RuntimeError("No public key found, halting")
        try:
            with open(expand + '/' + name, 'rb') as f:
                self.secret = f.read()[:-1]
        except FileNotFoundError:
            raise RuntimeError("No private key found, halting")

    def public_binary(self):
        return b64decode(self.public)

    def secret_binary(self):
        return b64decode(self.secret)

    @staticmethod
    def new():
        """Create a new random key pair"""
        keys = SecretKey()
        rtn = KeyPair()
        rtn.public = b64encode(keys.pk)
        rtn.secret = b64encode(keys.sk)
        return rtn

    def __repr__(self):
        return "<messidge.Keys object at %x (pk=%s)>" % (id(self), self.public)


def default_location():
    try:
        with open(os.path.expanduser('~/.20ft/default_location'), 'r') as f:
            return f.read().strip('\n')
    except FileNotFoundError:
        raise RuntimeError("""There is no ~/.20ft/default_location so cannot choose default location.""")


def create_account(location, token):
    # The new key pair
    keys = KeyPair.new()

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

    # write out the appropriate files
    directory = os.path.expanduser('~/.20ft/')
    os.makedirs(directory, exist_ok=True)
    with open(directory + 'default_location', 'w') as f:
        f.write(location + "\n")
    with open(directory + location + '.spub', 'w') as f:
        f.write(reply + "\n")
    with open(directory + location + '.pub', 'w') as f:
        f.write(keys.public.decode() + "\n")
    with open(directory + location, 'w') as f:
        f.write(keys.secret.decode() + "\n")

