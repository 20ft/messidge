# A sample controller using the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
from messidge.bases import ControllerMinimal
from messidge.broker.broker import cmd


class MyController(ControllerMinimal):
    def __init__(self, model):
        self.model = model

    def _write_note(self, msg):
        self.model.add_note(msg.params['user'], msg.params['note'])

    def _fetch_notes(self, msg):
        msg.reply({'notes': self.model.notes_for(msg.params['user'])})

    def _raise_exception(self, msg):
        raise ValueError("raise_exception was called")

    # commands are: {b'command': cmd(['necessary', 'params'], needs_reply=False, node_only=False), ....}
    commands = {
        b'write_note': cmd(['note']),
        b'fetch_notes': cmd([], needs_reply=True),
        b'raise_exception': cmd([], needs_reply=True)
    }
