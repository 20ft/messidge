# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/

import logging
from multiprocessing import Process
from bottle import route, run, request
from litecache.cache import SqlCache


ident_init = """
CREATE TABLE nodes (pk TEXT NOT NULL UNIQUE, json BLOB);
CREATE TABLE users (pk TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE, json BLOB);
CREATE TABLE pending (token TEXT NOT NULL UNIQUE, email TEXT NOT NULL);
"""


class Identity:
    def __init__(self, directory):
        self.db = SqlCache(directory, 'identity', ident_init)

    def user_config_from_db(self, pk_b64):  # is used to check for presence in the db, too
        """Returns the json for pk (if there)"""
        return self.db.query_one("SELECT email, json FROM users WHERE pk=?", (pk_b64,), "Unknown user")

    def register_node(self, keys, params):
        """Writes a node's parameters into the config database"""
        self.db.async("INSERT OR REPLACE INTO nodes (pk, json) VALUES (?, ?);", (keys.public.decode(), params))

    def node_params_from_db(self, pk_b64):
        """Returns json of the node's parameters"""
        return self.db.query_one("SELECT json FROM nodes WHERE pk=?", (pk_b64,), "Unknown node")[0]


class AccountConfirmationServer(Process):
    """A simple HTTP server for confirming accounts"""
    # has single use tokens so no real need to SSL
    db = None
    pk = None
    port = None

    def __init__(self, db, keys, port):
        super().__init__(target=self.serve, name=str("Account Confirmation Server"))
        AccountConfirmationServer.db = db
        AccountConfirmationServer.pk = keys.public
        AccountConfirmationServer.port = port
        self.start()

    @staticmethod
    @route('/', method='POST')
    def account():
        # de-HTTP the request
        try:
            token, user_pk = request.body.read().decode().split()
        except:
            logging.warning("Off-spec request to account creation server: " + request.body.read().decode())
            return None

        # valid token?
        cursor = AccountConfirmationServer.db.underlying().execute("SELECT email FROM pending WHERE token=?", (token,))
        pending_records = cursor.fetchall()
        if len(pending_records) == 0:
            logging.warning("An attempt was made to confirm an account with an incorrect token: " + token)
            return "Fail: this token is either incorrect or has been used once already."
        user_email = pending_records[0][0]

        # check for existing user
        cursor = AccountConfirmationServer.db.underlying().execute("SELECT * FROM users WHERE email=?", (user_email,))
        if len(cursor.fetchall()) != 0:
            logging.warning("An attempt was made to re-confirm for user: " + user_email)
            return "Fail: You have already confirmed your account."

        # all good
        AccountConfirmationServer.db.async("INSERT INTO users (pk, email) VALUES (?, ?);", (user_pk, user_email))
        AccountConfirmationServer.db.async("DELETE FROM pending WHERE token=?", (token,))
        logging.info("Confirmed an account for: " + user_email)
        return AccountConfirmationServer.pk

    @staticmethod
    def serve():
        try:
            logging.info("Started account confirmation server: 0.0.0.0:" + str(AccountConfirmationServer.port))
            run(host='0.0.0.0', port=AccountConfirmationServer.port, quiet=True)
        except OSError:
            logging.critical("Could not bind account confirmation server, exiting")
            exit(1)

