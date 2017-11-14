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

""""Abstracting out authentication - this is basically a minimal implementation."""

import logging
from base64 import b64encode


class Authenticate:

    def __init__(self, identity, keys):
        # Create an authentication object when passed location and (our) keys
        self.identity = identity
        self.keys = keys

    def auth(self, msg):
        # Authenticate against config
        # Returns success, user, config
        try:
            pk = b64encode(msg.params['user']).decode()  # the database holds base64 encoded strings for sanity
        except TypeError:
            return False, False, None

        # A user?
        try:
            email, json = self.identity.user_config_from_db(pk)
            logging.info("Authentication succeeded as user: " + email)
            return True, True, json
        except ValueError as e:  # throws if not a user (perhaps a node)
            pass

        # A node, then?
        try:
            json = self.identity.node_config_from_db(pk)
            logging.info("Authentication succeeded as node: " + str(pk))
            return True, False, json
        except ValueError as e:  # oh, we failed then
            pass

        # bugger
        logging.warning("Authentication failed - user not in database (and is not a node): " + str(pk))
        return False, False, None

    def __repr__(self):
        return "<messidge.broker.auth.Auth object at %x (pk=%s)>" % (id(self), self.keys.public)
