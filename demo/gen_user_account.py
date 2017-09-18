# Creating user accounts for the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
import sys
from messidge.broker.identity import Identity

if len(sys.argv) != 2:
    print("Run: python3 gen_user_account.py user@email", file=sys.stderr)
    exit(1)

identity = Identity()
try:
    token = identity.create_pending_user(sys.argv[1])
    print("The user will need this token: " + token)
finally:
    identity.stop()  # because identity runs a background thread

