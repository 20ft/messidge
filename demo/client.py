# A quick test/demo of messidge
# (c) 2017 David Preece, this work is in the public domain
import logging
import time
from messidge.client.connection import Connection
from messidge import default_location

# logging.basicConfig(level=logging.DEBUG)

# takes it's server address, pk and sk from the configuration in (default) ~/.messidge
conn = Connection(default_location()).wait_until_ready()  # I do not like blocking the c'tor

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

# an exception (missing params) is produced by an async call
# nothing will happen until we try to use the connection for something else
# the trick here is to log at level=DEBUG or use a blocking call in the first place
print("Deliberately sending error and waiting")
conn.send_cmd(b'write_note')  # missing the 'note' parameter
time.sleep(0.5)
print("Using the connection again (even correctly) causes the exception to be thrown...")
try:
    conn.send_cmd(b'write_note', {'note': 'I will not be sent'})
except ValueError as e:
    print("ValueError because: " + str(e))

conn.disconnect()
