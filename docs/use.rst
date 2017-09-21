==============
Using Messidge
==============

Messidge is primarily for intermediating between a number of users ... who may be on the public Internet and who communicate over an authenticated and encrypted channel; and a number of nodes which are assumed to lie on a LAN or similar private network.

In the architecture diagram below, green are those components provided by Messidge, and blue are those that need to be implemented to use the library.

..  image:: architecture.svg

All objects are named by their public key (pk), and each connection onto the broker has a routing id (a rid, that you won't need to touch). A user can connect more than one instance, each of these being called a session; and nodes are assumed to have single instance per pk.

There are no network addresses - as far as a client (or a node) is concerned it is part of a traditional client/server setup and is only talking to the one server. It's all asynchronous but can be made to look synchronous if you need to; and it's simple to set up a long term 'channel' through which message replies can be streamed. It guarantees to deliver messages in order and only once. Best of all, it's designed to make all these things dead easy.

To prepare, either follow the initial steps of the `quickstart <quickstart.html>`_ to have the demo code on your machine, or ``pip3 install messidge`` to just install the module.

Let's go through the steps required to build a Messidge based application (the one in the `demo directory <https://github.com/RantyDave/messidge/tree/master/demo>`_)...

A Basic Server/Broker
^^^^^^^^^^^^^^^^^^^^^

Let's build a sample server that: Centrally stores a series of notes provided by the client, and provides stateless nodes for dividing two numbers.

The majority of the work is to create model and controller objects (where the model has to derive from ModelMinimal), and classes for user and node sessions (SessionMinimal and NodeMinimal respectively). So, first off, let's create the model class::

    from messidge.broker.bases import ModelMinimal

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

Note that the notes are namespaced by the user public key (pk). There are no usernames, and everything that authenticates does so with a public/secret key pair. The controller looks like this::

    from messidge.broker.broker import cmd

    class MyController:
        def __init__(self, model):
            self.model = model

        def _write_note(self, msg):
            self.model.add_note(msg.params['user'], msg.params['note'])

        def _fetch_notes(self, msg):
            msg.reply({'notes': self.model.notes_for(msg.params['user'])})

        commands = {
            b'write_note': cmd(['note']),
            b'fetch_notes': cmd([], needs_reply=True)
        }

A few things to note are:

* The controller needs a static commands dict (actually called 'commands') which describes the available commands and any validations to be applied before the message is passed to its handler.
* Validations are created with messidge.broker.broker.cmd. This takes a list of parameters whose existence (but not type) are checked for, whether or not the command needs to use replyable messages, and whether or not the command is only valid if it has come from a node.
* Handlers are always named as an underscore plus the command name. They are always passed 'self' for the controller and the message itself. Return values will be ignored, but the message can have 'reply' called on it.
* The message has the parameters 'user' (being the user pk) and 'session' (being an opaque id - the rid) added to it and these are guaranteed to be correct. Messages from nodes have 'node' (being the node pk) but no session.

The sample model also includes specialisations of the user and node session objects. These are not necessary for an application as simple as the demo code, but become useful really quickly in real world scenarios::

    from messidge.broker.bases import SessionMinimal, NodeMinimal

    class MySession(SessionMinimal):
        def __init__(self, rid, pk, nonce):
            super().__init__(rid, pk, nonce)
            logging.debug("I am the right kind of session object.")


    class MyNode(NodeMinimal):
        def __init__(self, pk, msg, config):
            super().__init__(pk, msg, config)
            logging.debug("I am the right kind of node object.")

The broker also needs a way of creating and authenticating identities. Since this is likely to vary from one application to another we can define the classes at construction time, or the default is to use some simple implementations that are built in (see Identity, Authenticate, and AccountConfirmationServer). This documentation assumes you are using the default classes and does not cover the creation of custom implementations.

We can now construct these into the broker itself. Jobs here are to:

* Establish the public/secret key pair the broker will use for encryption.
* Create the model and controller objects.
* Create the broker with the keys, model, controller, and types for user and node sessions.
* Tell it to run ... then tell it to stop. ::

    # fetch/create the server keys
    try:
        keys = KeyPair('localhost_broker')
    except RuntimeError:  # assume it can't find the keys, let's generate more
        keys = KeyPair.new('localhost_broker')

    # create the objects
    model = MyModel()
    controller = MyController(model)
    broker = Broker(keys, model, MyNode, MySession, controller)

    # run the broker, ensuring it gets stopped if there's an uncaught exception
    try:
        broker.run()
    except KeyboardInterrupt:
        pass
    finally:
        broker.stop()

At at the most basic level at least, that's it.

Adding a Node
^^^^^^^^^^^^^

A node has no concept of identity or sessions (unless you add them) and hence is considerably simpler than the broker. It does, however, handle commands and hence needs a controller. These are implemented *very* much like the broker controller::

    from messidge.client.connection import cmd


    class Controller:
        def __init__(self, socket_factory):
            self.socket_factory = socket_factory

        def _divide(self, msg):
            # some additional validation
            if not isinstance(msg.params['dividend'], float) or not isinstance(msg.params['devisor'], float):
                raise ValueError("Divide only takes two floats.")
            if msg.params['devisor'] == 0:
                raise ValueError("Devisor cannot be zero")

            # go
            msg.reply(self.socket_factory(), results={'quotient': msg.params['dividend'] / msg.params['devisor']})

        commands = {b'divide': cmd(['dividend', 'devisor'], needs_reply=True)}

The major differences are:

* The 'cmd' function comes from messidge.client.connection and doesn't have a concept of messages only being valid if they come from a node. Otherwise the implementations are identical.
* Client messages cannot just have 'reply' called on them and need to be passed a socket through which they can be forwarded. In the example above this is passed through the 'socket_factory' function.

Note that in this example we apply additional checks to the incoming parameters and raise a ValueError if they fail. This error is caught by the message loop and transported to the client where it is raised as part of the original rpc call.

Since there is no model (in the bare-bones case) we can implement a single object representing the node thus::

    from messidge.client.connection import Connection

    class Node:
        # The node is effectively just another client
        def __init__(self, location, server_pk, keys):
            # set up some objects
            self.connection = Connection(location, server_pk=server_pk, keys=keys, reflect_value_errors=True)
            self.controller = Controller(self.connection.send_skt)
            self.connection.register_commands(self.controller, Controller.commands)
            self.connection.start()

        def run(self):
            self.connection.wait_until_complete()

        def disconnect(self):
            self.connection.disconnect()

Some things to note:

* A node uses the same connection object as the client. Location is the fqdn (or ip address) of the broker to connect to; server_pk is the expected public key from the server (thus thwarting mitm attacks); the keys are a client public/secret pair and use exactly the same class as for the broker; and 'reflect_value_errors' indicates that value errors raised as part of handling a command are to be reflected back to the calling user - the alternative being to allow them to filter through to the underlying try/except (if there is one).
* The controller is passed send_skt from the connection object in the role of a socket factory. Connection.send_skt either creates a new ZMQ socket for this thread (if necessary) or provides one that exists already.
* One must call 'register_commands' on a connection before calling 'start'.
* After start, 'wait_until_complete' will run the message loop and controller on a background thread and will return when this thread exits. And similarly to the broker, it is polite to call disconnect when finished.

We can use this object to construct an 'application' in a very similar manner to that used for the broker::

    node = Node(location, spk, KeyPair(public=pk, secret=sk))
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.disconnect()

Implementing a Client
^^^^^^^^^^^^^^^^^^^^^

Basic client implementation is, effectively, half a node. To start off with we need only concern ourselves with one object and two method calls - creating a connection, using it to make an asynchronous call, and making a synchronous call::

    from messidge.client.connection import Connection
    from messidge import default_location

    conn = Connection(default_location())
    conn.start().wait_until_ready()

    # an asynchronous command
    conn.send_cmd(b'write_note', {'note': time.ctime(time.time())})

    # synchronous, but guaranteed to not be called before 'write_note' has been processed by the broker
    reply = conn.send_blocking_cmd(b'fetch_notes')
    print("Here are the notes: " + str(reply.params['notes']))

OK, so there's quite a lot here...

* Unlike the node, the connection is constructed with *just* the name of the location and the remainder happens "automagically".
* The call 'default_location' looks in a per-application hidden directory (by default, ~/.messidge/) for a file called 'default_location'. If it exists, the contents of the file is read and returned.
* The Connection then uses this location to look in the hidden directory for the client's secret key, public key, and and the server's public key. These will be named after the location so if the location is called "localhost" we will be expecting to see "localhost" (the secret key), "localhost.pub" (the public key), and "localhost.spub" (the server's public key). Note that by setting the directory up like this a single application can hold credentials for more than one location. The same technique can be used for a node but the need for a persistent disk image proves to be less than ideal in practice.
* We call 'wait_until_ready' on the connection. There's no specific need to do this - the node doesn't need to, for example - but doing so ensures that the connection is entirely ready if you need to send a command down it straight away.
* We send an asynchronous command. The command itself is a binary string, a dictionary of parameters are passed, and additionally there is a single field for bulk data. Obviously there is no return from the command but the message queue assures us that commands are processed in the order in which they are sent.
* We send a synchronous command. Again, the command is a binary string - and parameters and bulk data can also be passed. When the message receives a reply, the call returns the reply message. Most likely (but depending on the implementation of the broker and/or node) the results you want are contained in the params dictionary of the returned message.

Looking further into the demo code we can see some other patterns::

    # asynchronous via callback
    # note that the callback is called by the background (loop) thread
    def async_callback(msg):
        print("Async callback: " + str(msg.params['notes']))
    conn.send_cmd(b'fetch_notes', reply_callback=async_callback)
    print("This will print before the async callback is triggered...")

Here we define a reply callback and pass it to the asynchronous 'send_cmd' call. In this case the callback is a simple function, but a method on an object can be called just by specifying object.method. The call gets passed the reply message in exactly the same way as the blocking call returns a message and the results are extracted identically. It is worth noting, however, that in the synchronous case the main thread receives the message and in the asynchronous case the call is made by a background thread.

One more::

    # an exception is raised from a blocking call
    try:
        conn.send_blocking_cmd(b'raise_exception')
    except ValueError as e:
        print("Expected! ValueError raised because: " + str(e))

ValueError exceptions raised in the server as the result of a synchronous call are transported back to the client and raise as if the call itself had raised it.

Resource offers and Calling Nodes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Calling nodes is tricky because you need to somehow know they are there, live and available for you to use. This is achieved through a "resource offer" - a message sent from the broker to a user at the start of a session. To implement a resource offer...

Implement ``resource_offer`` on the broker's model::

    def resources(self, pk):
        return {'nodes': list(self.nodes.keys())}  # materialise the generator (keys)

Implement a controller for the client (so it is able to receive incoming commands)::

    class Controller:
        def __init__(self):
            self.nodes = []

        def _resource_offer(self, msg):
            self.nodes = msg.params['nodes']

        commands = {b'resource_offer': cmd(['nodes'])}

And register the controller before bringing the connection live::

    conn = Connection(default_location())
    controller = Controller()
    conn.register_commands(controller, Controller.commands)
    conn.start().wait_until_ready()

Note that the resource offer will not have arrived before 'wait_until_ready' returns - nor is there a guarantee it ever will (after all, the broker may not have implemented it). If this is going to be a problem, you'll have to poll for it (remembering that the offer is delivered on a background thread).

The exact form that the resource offer takes is (obviously) defined by the broker itself, but in the above case the broker returns a list of public keys for nodes. To send an instruction to a node we merely include this public key as one of the parameters::

    # get the nodes to do something for us by passing their public key
    for node_pk in controller.nodes:
        reply = conn.send_blocking_cmd(b'divide', {'node': node_pk, 'dividend': 10.0, 'devisor': 5.0})
        print("10.0/5.0=" + str(reply.params['quotient']))

The broker can advertise any resources you want, in any form you want. Note that the user's pk is passed to the 'resources' method and this can be used to ensure only the correct resources are advertised for a particular user.
