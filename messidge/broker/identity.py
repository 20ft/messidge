# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/

import logging
import os
import shortuuid
from threading import Thread
from bottle import Bottle, run, request
from litecache.cache import SqlCache


ident_init = """
CREATE TABLE nodes (pk TEXT NOT NULL UNIQUE, json BLOB);
CREATE TABLE users (pk TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE, json BLOB);
CREATE TABLE pending (token TEXT NOT NULL UNIQUE, email TEXT NOT NULL);
"""


class Identity:
    def __init__(self, directory="~"):
        self.db = SqlCache(os.path.expanduser(directory), 'identity', ident_init)

    def stop(self):
        self.db.close()

    def raise_for_no_user(self, email):
        """Raises an error if this email address does not have an account"""
        self.db.query_one("SELECT * FROM users WHERE email=?", (email,), "no validated account")

    def create_pending_user(self, email):
        """Registers the intention for someone to become a registered user"""
        token = shortuuid.uuid()
        self.db.async("INSERT INTO pending (token, email) VALUES (?, ?);", (token, email))
        return token

    def pending_users_for_token(self, token):
        """Return the pending users for the given token (may well be zero)"""
        return self.db.query("SELECT email FROM pending WHERE token=?", (token,))

    def register_user(self, pk_b64, email, params):
        """Registers a user as being valid"""
        self.db.async("DELETE FROM pending WHERE email=?", (email,))
        self.db.async("INSERT INTO users (pk, email, json) VALUES (?, ?, ?);", (pk_b64, email, params))
    def user_config_from_db(self, pk_b64):  # is used to check for presence in the db, too
        """Returns the json for pk (if there)"""
        return self.db.query_one("SELECT email, json FROM users WHERE pk=?", (pk_b64,), "Unknown user")

    def register_node(self, pk_b64, params):
        """Writes a node's parameters into the config database"""
        self.db.async("INSERT OR REPLACE INTO nodes (pk, json) VALUES (?, ?);", (pk_b64, params))

    def node_config_from_db(self, pk_b64):
        """Returns json of the node's parameters"""
        return self.db.query_one("SELECT json FROM nodes WHERE pk=?", (pk_b64,), "Unknown node")[0]


confirmation_server = Bottle()


class AccountConfirmationServer(Thread):
    """A simple HTTP server for confirming accounts"""
    # has single use tokens so no real need to SSL
    identity = None
    db = None
    pk = None
    port = None

    def __init__(self, identity, keys, port):
        super().__init__(name=str("Account Confirmation Server"), daemon=True)
        AccountConfirmationServer.identity = identity
        AccountConfirmationServer.db = identity.db.underlying()
        AccountConfirmationServer.pk = keys.public
        AccountConfirmationServer.port = port
        self.start()

    @staticmethod
    @confirmation_server.route('/', method='POST')
    def account():
        # de-HTTP the request
        try:
            token, user_pk = request.body.read().decode().split()
        except:
            logging.warning("Off-spec request to account creation server: " + request.body.read().decode())
            return None

        # valid token?
        pending_records = AccountConfirmationServer.identity.pending_users_for_token(token)
        if len(pending_records) == 0:
            logging.warning("An attempt was made to confirm an account with an incorrect token: " + token)
            return "Fail: this token is either incorrect or has been used already."
        user_email = pending_records[0][0]

        # all good
        AccountConfirmationServer.identity.register_user(user_pk, user_email, "{}")
        logging.info("Confirmed an account for: " + user_email)
        return AccountConfirmationServer.pk

    def run(self):
        try:
            logging.info("Started account confirmation server: 0.0.0.0:" + str(AccountConfirmationServer.port))
            run(app=confirmation_server, host='0.0.0.0', port=AccountConfirmationServer.port, quiet=True)
        except OSError:
            logging.critical("Could not bind account confirmation server, exiting")
            exit(1)
