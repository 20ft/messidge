# A sample model using the Messidge python library
# (c) 2017 David Preece, this work is in the public domain
import logging

from messidge.broker.bases import ModelMinimal, NodeMinimal, SessionMinimal


class MyModel(ModelMinimal):
    def __init__(self):
        super().__init__()
        self.pk_notes = {}  # maps user pk onto the list of notes they made

    def add_note(self, pk, note):
        if pk not in self.pk_notes:
            self.pk_notes[pk] = []
        self.pk_notes[pk].append(note)

    def notes_for(self, pk):
        try:
            return self.pk_notes[pk]
        except KeyError:  # no notes for this pk
            return []

    def resources(self, pk):
        return {'nodes': list(self.nodes.keys())}  # materialise the generator (keys)


class MySession(SessionMinimal):
    def __init__(self, rid, pk):
        super().__init__(rid, pk)
        logging.debug("I am the right kind of session object.")


class MyNode(NodeMinimal):
    def __init__(self, pk, msg, config):
        super().__init__(pk, msg, config)
        logging.debug("I am the right kind of node object.")
