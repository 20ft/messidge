# Copyright (c) 2017 David Preece - davep@polymath.tech, All rights reserved.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# Base classes for models and controllers

from lru import LRU


class NodeMinimal:
    def __init__(self, pk, msg, config):
        self.pk = pk
        self.msg = msg
        self.config = config


class SessionMinimal:
    def __init__(self, rid, pk):
        self.rid = rid
        self.pk = pk
        self.old_rid = rid  # for use with reconnection

    # overload to free resources - can use passed broker to send commands to nodes
    def close(self, broker):
        pass


class ModelMinimal:
    """Stores the nodes and user sessions attached to this broker."""

    def __init__(self):
        self.nodes = {}
        self.sessions = {}
        self.long_term_forwards = LRU(2048)

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
