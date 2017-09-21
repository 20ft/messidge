# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
# Base classes for models and controllers


class NodeMinimal:
    def __init__(self, pk, msg, config):
        self.pk = pk
        self.msg = msg
        self.config = config


class SessionMinimal:
    def __init__(self, rid, pk, nonce):
        self.rid = rid
        self.pk = pk
        self.nonce = nonce
        self.old_rid = rid  # for use with reconnection

    # overload to free resources - can use passed broker to send commands to nodes
    def close(self, broker):
        pass


class ModelMinimal:
    """Stores the nodes and user sessions attached to this broker."""

    def __init__(self):
        self.nodes = {}
        self.sessions = {}

    def resources(self, pk):
        """Overload this method to return a resource offer to a newly connected client.

        :param pk: the public key of the connecting user. """
        return None

    # overload these if you want to make persistent sessions
    def create_session_record(self, sess):
        pass

    def update_session_record(self, sess):
        pass

    def delete_session_record(self, sess):
        pass
