# A quick runthrough of writing a client for Messidge
# (c) 2017 David Preece, this work is in the public domain
import logging
import time
from messidge.client.connection import Connection, cmd
from messidge import default_location


class Controller:
    def __init__(self):
        self.nodes = []

    def _resource_offer(self, msg):
        self.nodes = msg.params['nodes']

    commands = {b'resource_offer': cmd(['nodes'])}


logging.basicConfig(level=logging.INFO)

# takes it's server address, pk and sk from the configuration in (default) ~/.messidge
conn = Connection(default_location())  # I do not like blocking the c'tor
controller = Controller()
conn.register_commands(controller, Controller.commands)
conn.start().wait_until_ready()


# an asynchronous command
conn.send_cmd(b'write_note', {'note': time.ctime(time.time())})

# synchronous, but guaranteed to not be called before 'write_note' has been processed by the broker
reply = conn.send_blocking_cmd(b'fetch_notes')
print("Here are the notes: " + str(reply.params['notes']))

# asynchronous via callback
# note that the callback is called by the background (loop) thread
def async_callback(msg):
    print("Async callback: " + str(msg.params['notes']))
conn.send_cmd(b'fetch_notes', reply_callback=async_callback)
print("This will print before the async callback is triggered...")

# an exception is raised from a blocking call
try:
    conn.send_blocking_cmd(b'raise_exception')
except ValueError as e:
    print("ValueError raised because: " + str(e))

# get the nodes to do something for us by passing their public key
for node_pk in controller.nodes:
    reply = conn.send_blocking_cmd(b'divide', {'node': node_pk, 'dividend': 10.0, 'devisor': 5.0})
    print("10.0/5.0=" + str(reply.params['quotient']))

    try:
        conn.send_blocking_cmd(b'divide', {'node': node_pk, 'dividend': 10.0, 'devisor': 0.0})
    except ValueError as e:
        print("ValueError raised because: " + str(e))

conn.disconnect()
