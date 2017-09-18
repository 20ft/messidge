# Confirming user accounts for the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
import sys
from messidge import create_account

if len(sys.argv) != 2:
    print("Run: python3 confirm_user_account.py token", file=sys.stderr)
    exit(1)

create_account("localhost", sys.argv[1])
