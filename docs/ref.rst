=========
Reference
=========

Broker
======

Broker
^^^^^^

..  autoclass:: messidge.broker.broker.Broker
    :members:

..  autofunction:: messidge.broker.broker.cmd

Identity
^^^^^^^^

..  autoclass:: messidge.broker.identity.Identity
    :members:

Loop
====

The same message loop is used by both the broker and the client (although the broker specialises command handling).

..  autoclass:: messidge.loop.Loop
    :members:

Client
======

Connection
^^^^^^^^^^

..  autoclass:: messidge.client.connection.Connection
    :members:

..  autofunction:: messidge.client.connection.cmd

Message
^^^^^^^

..  autoclass:: messidge.client.message.Message
    :members:
