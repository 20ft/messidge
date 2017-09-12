# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
""""Abstracting out authentication - this is basically a minimal implementation."""

import logging
from base64 import b64encode


class Authenticate:

    def __init__(self, identity, keys):
        """Create an authentication object when passed location and (our) keys"""
        self.identity = identity
        self.keys = keys

    def __del__(self):
        logging.debug("Authenticator closed")

    def auth(self, msg):
        """Authenticate against config"""
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
            json = self.identity.node_params_from_db(pk)
            logging.info("Authentication succeeded as node: " + str(pk))
            return True, False, json
        except ValueError as e:  # oh, we failed then
            pass

        # bugger
        logging.warning("Authentication failed - user not in database (and is not a node): " + str(pk))
        return False, False, None

    def __repr__(self):
        return "<messidge.broker.auth.Auth object at %x (pk=%s)>" % (id(self), self.keys.public)
