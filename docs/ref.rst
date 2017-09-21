=========
Reference
=========

Broker
======

Classes in this section are the API for building server/broker applications...

Broker
^^^^^^

..  autoclass:: messidge.broker.broker.Broker
    :members:

..  autofunction:: messidge.broker.broker.cmd

Model
^^^^^

..  autoclass:: messidge.broker.bases.ModelMinimal
    :members:

Identity
^^^^^^^^

..  autoclass:: messidge.broker.identity.Identity
    :members:

----

Loop
====

The same message loop is used by both the broker and the client.

..  autoclass:: messidge.loop.Loop
    :members:

----

Client
======

Classes in this section are the API for building client applications...

Connection
^^^^^^^^^^

..  autoclass:: messidge.client.connection.Connection
    :members:

..  autofunction:: messidge.client.connection.cmd
