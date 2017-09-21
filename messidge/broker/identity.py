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

import logging
import os
import shortuuid
from threading import Thread
from bottle import Bottle, run, request
from litecache.cache import SqlCache


ident_init = """
CREATE TABLE nodes (pk TEXT NOT NULL UNIQUE, json BLOB);
CREATE TABLE users (pk TEXT NOT NULL UNIQUE, email TEXT NOT NULL, json BLOB);
CREATE TABLE pending (token TEXT NOT NULL UNIQUE, email TEXT NOT NULL);
"""


class Identity:
    """A default provider of identity and configuration"""

    def __init__(self, directory="~"):
        """Construct the identity database if it's not there.

        :param directory: The directory in which to place the database (identity.sqlite3)"""
        self.db = SqlCache(os.path.expanduser(directory), 'identity', ident_init)

    def stop(self):
        self.db.close()

    def create_pending_user(self, email) -> str:
        """Registers the intention for someone to become a registered user

        :param email: email address of the user.
        :return: confirmation token to give to the user."""
        token = shortuuid.uuid()
        self.db.async("INSERT INTO pending (token, email) VALUES (?, ?)", (token, email))
        return token

    def pending_users_for_token(self, token) -> []:
        """Return the pending users for the given token (may well be zero).

        :param token: the token a user was given in order to be able to confirm their account.
        :return: The list of pending users for that token."""
        return self.db.query("SELECT email FROM pending WHERE token=?", (token,))

    def register_user(self, pk_b64: str, email: str, config: str):
        """Registers a user as being valid.

        :param pk_b64: The user's primary key - base64 encoded string.
        :param email: The user's email address.
        :param config: A json description of any configuration to be associated with the user."""
        self.db.async("DELETE FROM pending WHERE email=?", (email,))
        self.db.async("INSERT INTO users (pk, email, json) VALUES (?, ?, ?)", (pk_b64, email, config))

    def user_config_from_db(self, pk_b64: str) -> (str, str):  # is used to check for presence in the db, too
        """Returns the json configuration for a user.

        :param pk_b64: The user's primary key - base64 encoded string.
        :return: A tuple of email address and the json configuration."""
        return self.db.query_one("SELECT email, json FROM users WHERE pk=?", (pk_b64,), "Unknown user")

    def raise_for_no_user(self, email: str):
        """Raises an error if this email address does not have an account.

        :param email: email address of the user."""
        self.db.query_one("SELECT * FROM users WHERE email=?", (email,), "no validated account")

    def register_node(self, pk_b64: str, config: str):
        """Writes a node's configuration into the database.

        :param pk_b64: The node's primary key - base64 encoded string.
        :param config: A json description of any configuration to be associated with the node."""
        self.db.async("INSERT INTO nodes (pk, json) VALUES (?, ?)", (pk_b64, config))

    def node_config_from_db(self, pk_b64: str) -> str:
        """Returns the json configuration of a node.

        :param pk_b64: The node's primary key - base64 encoded string.
        :return: The json configuration for the node."""
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
