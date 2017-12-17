# A sample broker using the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
import logging
from messidge import KeyPair
from messidge.broker.broker import Broker
from demo.broker.model import MyModel, MySession, MyNode
from demo.broker.controller import MyController

logging.basicConfig(level=logging.DEBUG)


# fetch/create the server keys
try:
    keys = KeyPair('localhost_broker')
except RuntimeError:  # assume it can't find the keys, let's generate more
    keys = KeyPair.new('localhost_broker')

# create the objects
model = MyModel()
controller = MyController(model)
broker = Broker(keys, model, MyNode, MySession, controller)

# run the broker, ensuring it gets stopped if there's an uncaught exception
try:
    broker.run()
except KeyboardInterrupt:
    pass
finally:
    broker.stop()
