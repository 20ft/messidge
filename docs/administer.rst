============================
Administration and Demo Apps
============================

In the `quickstart <quickstart.html>`_ we briefly passed through creating user and node accounts. The authentication facilities are pluggable - ie open to be reimplemented for your particular case - but the existing facilities are *there* and good enough for simple cases. Let's see how we go about creating credentials for nodes and users to authenticate with.

Nodes
^^^^^

Credentials for nodes are not stored on disk. This is primarily so nodes can start from a fixed disk image. In the demo applications the credentials are passed directly from the command line but in a practical application you may wish to store these params either in the AWS parameter store or a similar locally hosted facility (see `AWS or not <https://github.com/RantyDave/awsornot>`_).

Programmatically all you need to do is create a new key pair then register it with the Identity object. The demonstration code also fetches the (local) server pair in order to provide the node with the server public key::

    from messidge import KeyPair
    from messidge.broker.identity import Identity

    identity = Identity()
    try:
        keys = KeyPair.new()
        identity.register_node(keys.public.decode(), '{}')
        skeys = KeyPair("localhost_broker")
        print("Start node with...\npython3 node.py localhost %s %s %s" %
              (keys.public.decode(), keys.secret.decode(), skeys.public.decode()))
    finally:
        identity.stop()

Perhaps obviously, this code produces a command line that the demo node.py can be started with.

Users
^^^^^

Users are slightly more complicated in that they specifically need inviting; have to obtain the server public key from somewhere; and need to create their own public/secret key pair. In Messidge this is done as a two stage process. First, the administrator invites the user to use the service - programmatically this is just a call to 'create_pending_user' with the user's email address::

    import sys
    from messidge.broker.identity import Identity

    identity = Identity()
    try:
        token = identity.create_pending_user(sys.argv[1])
        print("The user will need this token: " + token)
    finally:
        identity.stop()

No emails are sent (the address is just used as an identifier for administrative purposes), and transport of the token to the user is left as an exercise for the reader. It is worth noting, however, that the token transport does not need to be particularly well secured - and that once a token has been used it cannot be used again.

On the client side the token is used to confirm the account::

    import sys
    from messidge import create_account

    create_account("localhost", sys.argv[1])

The create_account call takes the token and forwards it to the account confirmation server running (by default) on TCP port 2021. If the token matches one of our pending users the server calls 'confirm_user' on the identity object then returns the server's public key. The client then creates four files in a hidden directory (by default '~/.messidge' unless changed as a 'prefix' parameter to one of the calls).

* ``default_location`` stores the fqdn or ip of the server we just authenticated against.
* ``location_name.pub`` and ``location_name`` are the public and secret keys used to access the server. This is very much the same as how (most) ssh clients store their keys.
* ``location_name.spub`` is the public key for the server.

Because of this architecture we can back up a series of client keys by merely backing up the directory; keys can be stored for multiple locations; and the default location can be set by merely editing the file.
