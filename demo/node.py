# Sample node for the messidge framework
# (c) 2017 David Preece, this work is in the public domain
import sys
from messidge import KeyPair
from demo.node.node import Node

if len(sys.argv) != 5:
    print("Usage: node.py location.fqdn pk sk spk", file=sys.stderr)
    exit(1)

app, location, pk, sk, spk = sys.argv
node = Node(location, spk, KeyPair(public=pk, secret=sk))
try:
    node.run()
finally:
    node.disconnect()
