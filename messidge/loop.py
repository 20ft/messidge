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

import logging
import time
import traceback
from _thread import get_ident

import zmq

from .client.message import Message


class Loop:

    def __init__(self, skt=None, message_type=Message, *, exit_on_exception=False):
        """Initialise (but not start) a message loop.

        :param skt: the (actually optional) ZMQ socket that connects to the location.
        :param message_type: optionally set to use a non-default message class.
        :param exit_on_exception: the message loop will exit if an exception makes it to the BaseException handler."""
        super().__init__()
        self.exclusive_handlers = {}
        self.reply_callbacks = {}
        self.command_handlers = {}
        self.idle = set()
        self.skt = skt  # the main trunk socket
        self.session_key = None
        self.message_type = message_type
        self.exit_on_exception = exit_on_exception
        self.value_error_handler = None
        self.running_thread = None
        self.caught_exception = None
        self.main_thread = get_ident()
        self.p = zmq.Poller()
        if skt is not None:
            self.p.register(skt, zmq.POLLIN)  # so register_reply will work even if we don't register anything else
            logging.debug("Message loop has registered trunk socket")

    def run(self):
        """Message loop. Runs single threaded (usually but not necessarily a background thread)."""
        self.running_thread = get_ident()
        last_idle = time.time()
        logging.debug("Message loop started")
        while self.running_thread is not None:
            try:
                # fetch the events
                events = self.p.poll(timeout=500)

                # idle? or every five seconds at worst
                tme = time.time()
                if len(events) == 0 or tme - last_idle > 5:
                    last_idle = tme
                    # should be be quitting?
                    if self.running_thread is None:  # yes, leave loop
                        break
                    # otherwise do our idle tasks
                    for idle_task in set(self.idle):
                        idle_task()
                    continue

                # Deal with all the events
                for event in events:

                    # on an exclusive socket? (the actual process of collecting the message is owned by the callback)
                    socket = event[0]
                    if socket in self.exclusive_handlers:
                        self.exclusive_handlers[socket](socket)
                        continue

                    # maybe an fd socket hasn't disappeared yet?
                    if isinstance(socket, int):
                        logging.debug("Message arrived for an fd socket that was unregistered: " + str(socket))
                        continue

                    # an ordinary message
                    msg = self.message_type.receive(socket, self.session_key)

                    try:
                        # is this a hooked reply? - these may well deal with (or raise) exceptions...
                        try:
                            self.reply_callbacks[msg.uuid](msg)
                            continue
                        except KeyError:
                            pass

                        # non-main thread exceptions just bin out and don't take the app down
                        # so the message loop catches them and waits for the main thread to deal with it.
                        try:
                            logging.debug("Message loop caught an exception: " + msg.params["exception"])
                            raise ValueError(msg.params["exception"])
                        except KeyError:
                            pass

                        # hopefully, then, a vanilla command
                        try:
                            obj, handlers = self.command_handlers[socket]  # don't replace with single value
                        except KeyError:
                            logging.debug("Socket had left command handlers with a message still to process")
                            continue
                        try:
                            handler = handlers[msg.command]
                        except KeyError:
                            # logging.warning("No handler was found for: %s (uuid=%s)" % (msg.command, msg.uuid))
                            continue

                        # logging.debug("Handling command: " + str(msg.command))
                        Loop.check_basic_properties(msg, handler)
                        getattr(obj, '_' + msg.command.decode())(msg)

                    except ValueError as e:
                        if self.value_error_handler:
                            self.value_error_handler(e, msg)
                        else:
                            raise e

            except KeyboardInterrupt:
                self.stop()

            except BaseException as e:
                logging.warning(traceback.format_exc())
                self.caught_exception = e
                if self.exit_on_exception:
                    self.stop()

        logging.debug("Message loop has finished")

    def stop(self):
        """Causes the thread in 'run' to exit cleanly."""
        if self.running_thread is None:
            return
        self.running_thread = None

    def set_crypto_params(self, session_key: bytes):
        """Sets the cryptographic parameters for this connection.

        :param session_key: The session key for this connection.
        """
        self.session_key = session_key

    def register_exclusive(self, obj, handler, *, comment: str=""):
        """Registers an object and handler called to receive all events received on a ZMQ socket or file descriptor.

        :param obj: the object that will receive events.
        :param handler: the handler that will be called - passed the zmq socket or file handler (int).
        :param comment: an optional comment for clarifying debug logs."""
        # function signature: def callback(self, socket)
        # object can be a zmq socket or a file descriptor
        if obj in self.exclusive_handlers:
            raise RuntimeError("Tried to register a socket exclusively twice: %s (%s)" % (str(obj), comment))
        if obj in self.command_handlers:
            raise RuntimeError("Socket is already registered with commands: %s (%s)" % (str(obj), comment))

        self.exclusive_handlers[obj] = handler
        self.p.register(obj, zmq.POLLIN)
        logging.debug("Message loop has registered exclusive: %s (%s)" % (str(obj), comment))

    def unregister_exclusive(self, obj):
        """Unregister an object as an exclusive handler.

        :param obj: The object to unregister."""
        try:
            del self.exclusive_handlers[obj]
            self.p.unregister(obj)
            logging.debug("Message loop has unregistered exclusive: " + str(obj))
        except KeyError:
            pass

    def register_commands(self, skt, obj, commands, *, comment: str=""):
        """Register command callbacks.

        :param skt: ZMQ socket that will receive the events.
        :param obj: The object that will handle the events.
        :param commands: A dictionary of {b'command': handler, ...}.
        :param comment: A string to help clarify debug logs."""
        if skt in self.exclusive_handlers:
            raise RuntimeError("Socket is already registered as exclusive: " + comment)
        if skt in self.command_handlers:
            raise RuntimeError("Tried to register a series of commands twice for the same socket: " + comment)
        for command in commands.keys():
            if not isinstance(command, bytes):
                raise RuntimeError("Pass commands as bytes, not strings")
        self.command_handlers[skt] = (obj, commands)
        if skt is not self.skt:  # OK to reclassify the existing socket but no OK to re-register it
            self.p.register(skt, zmq.POLLIN)

    def register_reply(self, command_uuid: bytes, callback):
        """Hooking the reply to a command. Note that this will not override an exclusive socket.

        :param command_uuid: the uuid of the command message from which we are expecting a reply.
        :param callback: the callback that gets sent the reply message when it arrives."""
        if callback is not None:
            self.reply_callbacks[command_uuid] = callback
        else:
            raise RuntimeError("Tried to register a reply for a command but passed None for the callback")

    def unregister_reply(self, command_uuid: bytes):
        """Removing the hook for a command reply.

        :param command_uuid: the uuid of the command message from which we are no longer expecting a reply."""
        try:
            del self.reply_callbacks[command_uuid]
        except KeyError:
            logging.debug("Called unregister_reply for a uuid that isn't hooked")

    def register_on_idle(self, obj):
        """Register an object.method to be called whenever the message loop has idle time.

        :param obj: The object.method to be called - no additional parameters are passed."""
        # Idles get invoked every time the poll on the message loop times out (ie has nothing to do)
        if obj not in self.idle:
            self.idle.add(obj)

    def unregister_on_idle(self, obj):
        """Unregister an object.method from the message loop's idle time.

        :param obj: The object.method to be unregistered."""
        try:
            self.idle.remove(obj)
        except KeyError:
            pass

    def on_value_error(self, callback):
        """Register an alternative to raising exceptions for ValueError exceptions coming over the wire.

        :param callback: the callback to be fired, gets passed the exception and message that caused the exception."""
        self.value_error_handler = callback

    @staticmethod
    def check_basic_properties(msg, handler):
        """Helper utility to ensure messages fulfill certain basic criteria before they are passed to their handlers.

        :param msg: the message to be tested.
        :param handler: the handler (a return from client.connection.cmd) to be tested for."""
        necessary_params, needs_reply = handler
        for necessary in necessary_params:
            if necessary not in msg.params:
                raise ValueError("Necessary parameter was not passed: " + necessary)
        if needs_reply and not msg.replyable():
            raise ValueError("This command needs to be replyable but the message was not: " + str(msg))

    def __repr__(self):
        return "<messidge.loop.Loop object at %x (exclusive=%d commands=%d replies_callbacks=%d)>" % \
               (id(self), len(self.exclusive_handlers), len(self.command_handlers), len(self.reply_callbacks))
