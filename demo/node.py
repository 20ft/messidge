# Sample node for the messidge framework
# (c) 2017 David Preece, this work is in the public domain
import sys
import logging
from messidge import KeyPair
from messidge.client.connection import Connection
from node.controller import Controller


if len(sys.argv) != 5:
    print("Usage: node.py location.fqdn pk sk spk", file=sys.stderr)
    exit(1)


class Node:
    # The node is effectively just another client
    def __init__(self, location, server_pk, keys):
        # set up some objects
        self.connection = Connection(location=location, server_pk=server_pk, keys=keys, reflect_value_errors=True)
        self.controller = Controller(self.connection.send_skt)
        self.connection.register_commands(self.controller, Controller.commands)
        self.connection.start()

    def run(self):
        self.connection.wait_until_complete()

    def disconnect(self):
        self.connection.disconnect()


logging.basicConfig(level=logging.INFO)

app, location, pk, sk, spk = sys.argv
node = Node(location, spk, KeyPair(public=pk, secret=sk))
try:
    node.run()
except KeyboardInterrupt:
    pass
finally:
    node.disconnect()
