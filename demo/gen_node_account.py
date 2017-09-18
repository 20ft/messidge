# Creating node accounts for the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
from messidge import KeyPair
from messidge.broker.identity import Identity

identity = Identity()
try:
    keys = KeyPair.new()
    skeys = KeyPair("localhost")
    identity.register_node(keys.public.decode(), '{}')
    print("Start node with...\npython3 node.py localhost %s %s %s" %
          (keys.public.decode(), keys.secret.decode(), skeys.public.decode()))
finally:
    identity.stop()
