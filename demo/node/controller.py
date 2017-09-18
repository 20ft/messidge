# A sample node controller using the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
from messidge.bases import ControllerMinimal
from messidge.client.connection import cmd


class Controller(ControllerMinimal):
    def _divide(self, msg):
        # some additional validation
        if not isinstance(msg.params['dividend'], float) or not isinstance(msg.params['devisor'], float):
            raise ValueError("Divide only takes two floats.")
        if msg.params['devisor'] == 0:
            raise ValueError("Devisor cannot be zero")

        # go
        msg.reply({'quotient': msg.params['divident'] / msg.params['devisor']})

    commands = {'divide': cmd(['dividend', 'devisor'], needs_reply=True)}
