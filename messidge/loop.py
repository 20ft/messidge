"""Copyright (c) 2017 David Preece, All rights reserved.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""

import logging
import sys
import time
import traceback
from _thread import get_ident

import zmq

from .client.message import Message


class Loop:

    def __init__(self, skt, message_type=Message):
        """Initialise (but not start) a message loop.

        skt is the zeromq socket that connects to the location.
        message_type can be set to customise the Message class."""
        super().__init__()
        self.exclusive_handlers = {}
        self.reply_callbacks = {}
        self.command_handlers = {}
        self.idle = set()
        self.skt = skt  # the main trunk socket
        self.nonce = None
        self.session_key = None
        self.message_type = message_type
        self.value_error_handler = None
        self.running_thread = None
        self.caught_exception = None
        self.main_thread = get_ident()
        self.p = zmq.Poller()
        if skt is not None:
            self.p.register(skt, zmq.POLLIN)  # so register_reply will work even if we don't register anything else
            logging.debug("Message loop has registered trunk socket")

    def set_crypto_params(self, nonce, session_key):
        self.nonce = nonce
        self.session_key = session_key

    def register_exclusive(self, obj, handler, comment=""):
        """Registers an object and an object.handler that gets called to receive all events."""
        # function signature: def callback(self, socket)
        # object can be a zmq socket or a file descriptor
        if obj in self.exclusive_handlers:
            raise RuntimeError("Tried to register a socket exclusively twice")
        if obj in self.command_handlers:
            raise RuntimeError("Socket is already registered with commands")

        self.exclusive_handlers[obj] = handler
        self.p.register(obj, zmq.POLLIN)
        logging.debug("Message loop has registered exclusive: " + comment)

    def unregister_exclusive(self, obj):
        try:
            del self.exclusive_handlers[obj]
            self.p.unregister(obj)
            logging.debug("Message loop has unregistered exclusive: " + str(obj))
        except KeyError:
            logging.warning("Tried to unregister a socket that was not registered (exclusive): " + str(obj))

    def register_commands(self, skt, obj, commands, comment=""):
        """Register command callbacks directly."""
        # A single shot per socket. Pass commands as {'name': _callback, ... }
        if skt in self.exclusive_handlers:
            raise RuntimeError("Socket is already registered as exclusive")
        if skt in self.command_handlers:
            raise RuntimeError("Tried to register a series of commands twice for the same socket")
        self.command_handlers[skt] = (obj, commands)
        if skt is not self.skt:  # OK to reclassify the existing socket but no OK to re-register it
            self.p.register(skt, zmq.POLLIN)
            logging.debug("Message loop has registered for commands: " + str(skt) + " " + comment)
        else:
            logging.debug("Not registering with poll twice (commands): " + str(skt))

    def register_reply(self, command_uuid, callback):
        """Hooking the reply to a command. Note that this will not override an exclusive socket."""
        if callback is not None:
            self.reply_callbacks[command_uuid] = callback
        else:
            raise RuntimeError("Tried to register a reply for a command but passed None for the callback")

    def unregister_reply(self, command_uuid):
        """Removing the reply hook"""
        try:
            del self.reply_callbacks[command_uuid]
        except KeyError:
            logging.debug("Called unregister_reply for a uuid that isn't hooked")

    def register_on_idle(self, obj):
        """Idles get invoked every time the poll on the message loop times out (ie has nothing to do)"""
        if obj not in self.idle:
            self.idle.add(obj)

    def unregister_on_idle(self, obj):
        if obj in self.idle:
            self.idle.remove(obj)

    def on_value_error(self, callback):
        """Register an alternative to raising exceptions for ValueError exceptions coming over the wire"""
        self.value_error_handler = callback

    def stop(self):
        """Stops the message loop."""
        if self.running_thread is None:
            return
        self.running_thread = None

    @staticmethod
    def check_basic_properties(msg, handler):
        """Helper utility to bounce messages that are missing properties before they do a bad thing"""
        necessary_params = handler[0]
        for necessary in necessary_params:
            if necessary not in msg.params:
                raise ValueError("Necessary parameter was not passed: " + necessary)
        if handler[1] and not msg.replyable():
            raise ValueError("This command needs to be replyable but the message was not: " + str(msg))

    def run(self):
        """Message loop. Runs single threaded (usually but not necessarily a background thread)."""
        self.running_thread = get_ident()
        tmr = time.time()
        msg = None
        socket = None
        logging.debug("Message loop started")
        while self.running_thread is not None:
            try:
                # warning if the loop stalls
                latency = ((time.time()-tmr)*1000)
                if latency > 10:
                    if latency < 1000:
                        logging.debug("Event loop stalled for (ms): " + str(latency))
                    else:
                        logging.warning("Event loop stalled for (ms): " + str(latency))

                # fetch the events
                events = self.p.poll(timeout=500)
                tmr = time.time()
                msg = None

                # idle?
                if len(events) == 0:
                    for idle_task in set(self.idle):
                        idle_task()
                    continue

                # Deal with all the events
                for event in events:

                    # did one of the previous events in the same group request the loop stop?
                    # in which case we stop any retries
                    if self.running_thread is None:
                        self.idle.clear()
                        break

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
                    msg = self.message_type.receive(socket, self.nonce, self.session_key)

                    try:
                        # non-main thread exceptions just bin out and don't take the app down
                        # so the message loop catches them and waits for the main thread to deal with it.
                        if 'exception' in msg.params:
                            logging.debug("Message loop caught an exception: " + msg.params["exception"])
                            self.caught_exception = ValueError(msg.params["exception"])

                        # is this a hooked reply? - these may well deal with (or raise) exceptions...
                        if msg.uuid in self.reply_callbacks:
                            self.reply_callbacks[msg.uuid](msg)
                            continue

                        # hopefully, then, a vanilla command
                        try:
                            obj, handlers = self.command_handlers[socket]  # don't replace with single value
                        except KeyError:
                            logging.debug("Socket had left command handlers with a message still to process")
                            continue
                        try:
                            handler = handlers[msg.command]
                            logging.debug("Handling command: " + str(msg.command))
                            Loop.check_basic_properties(msg, handler)
                            getattr(obj, '_' + msg.command.decode())(msg)
                        except KeyError:
                            logging.warning("No handler was found for: %s (uuid=%s)" % (msg.command, msg.uuid))

                    except ValueError as e:
                        if self.value_error_handler:
                            self.value_error_handler(e, msg)
                        else:
                            raise e

            except KeyboardInterrupt:
                self.stop()

        logging.debug("Message loop has finished")

    def __repr__(self):
        return "<messidge.loop.Loop object at %x (exclusive=%d commands=%d replies_callbacks=%d)>" % \
               (id(self), len(self.exclusive_handlers), len(self.command_handlers), len(self.reply_callbacks))
