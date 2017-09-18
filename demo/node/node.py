# A sample node using the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
from messidge.client.connection import Connection
from .controller import Controller


class Node:
    # The node is effectively just another client
    def __init__(self, location, server_pk, keys):
        # set up some objects
        self.connection = Connection(location=location, server_pk=server_pk, keys=keys)
        self.controller = Controller()
        self.connection.register_commands(self.controller, Controller.commands)

    def run(self):
        self.connection.wait_until_finished()

    def disconnect(self):
        self.connection.disconnect()
