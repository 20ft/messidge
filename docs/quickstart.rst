==========
Quickstart
==========

A quick demonstration:

* You are going to need `libsodium <https://download.libsodium.org/doc/>`_ and `ZeroMQ <https://zeromq.org/>`_ installed so ``brew install libsodium zeromq`` on a mac, ``apt install python3-zmq python3-libnacl`` on ubuntu or *whatever* on your platform.
* Python requirements are ``pip3 install pyzmq libnacl shortuuid psutil lru-dict cbor bottle litecache``.
* From your home directory clone the Messidge repository from GitHub ``git clone https://github.com/rantydave/messidge``.

Run the Broker
^^^^^^^^^^^^^^

* Open a new terminal, cd to ~/messidge/demo and ``export PYTHONPATH=".."``.
* Run ``python3 broker.py``

You should see something like... ::

    ~/m/demo> python3 broker.py
    INFO:root:Started account confirmation server: 0.0.0.0:2021
    INFO:root:Started broker: 0.0.0.0:2020

Add a Node
^^^^^^^^^^

* Open a new terminal, cd to ~/messidge/demo and ``export PYTHONPATH=".."``.
* Create a node account with ``python3 gen_node_account.py``.
* Start a node with the provided command line.

You should see something like... ::

    ~/m/demo> python3 gen_node_account.py
    Start node with...
    python3 node.py localhost zmtfztCypF/1zaEyhIXV6WsSITXq574ysMyI+aNYylA= AXj5unW+OK8+j/IwNrA7lWYhnUUB9y0r8tMeiNyg1Yw= WeAmNmDOiBuMAK3ecVwRu0yyvVIhGNXdUii7GCYCORw=
    ~/m/demo> python3 node.py localhost zmtfztCypF/1zaEyhIXV6WsSITXq574ysMyI+aNYylA= AXj5unW+OK8+j/IwNrA7lWYhnUUB9y0r8tMeiNyg1Yw= WeAmNmDOiBuMAK3ecVwRu0yyvVIhGNXdUii7GCYCORw=
    INFO:root:Connecting to: localhost:2020
    INFO:root:Message queue connected
    INFO:root:Handshake completed

Run a Client
^^^^^^^^^^^^

* Open a new terminal, cd to ~/messidge/demo and ``export PYTHONPATH=".."``.
* Create a new client invitation with ``python3 gen_user_account.py your@email``. This will create a confirmation token.
* Confirm the account with ``python3 confirm_user_account.py --the-token--``.
* Run ``python3 client.py``

You should see... ::

    ~/m/demo> export PYTHONPATH=".."
    ~/m/demo> python3 gen_user_account.py davep@zedkep.com
    The user will need this token: 2UUDwtG9EevqQiVkdaEzHn
    ~/m/demo> python3 confirm_user_account.py 2UUDwtG9EevqQiVkdaEzHn
    ~/m/demo> python3 client.py
    INFO:root:Connecting to: localhost:2020
    INFO:root:Message queue connected
    INFO:root:Handshake completed
    Here are the notes: ['Tue Sep 19 21:54:02 2017']
    This will print before the async callback is triggered...
    Async callback: ['Tue Sep 19 21:54:02 2017']
    Expected! ValueError raised because: raise_exception was called
    10.0/5.0=2.0
    Expected! ValueError raised because: Devisor cannot be zero

