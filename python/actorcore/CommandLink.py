__all__ = ["CommandLink"]

import logging
import re
import sys
import threading

from opscore.utility.qstr import qstr
from opscore.utility.tback import tback
from twisted.internet import reactor
from twisted.protocols.basic import LineReceiver

from .Command import Command


actorLogger = logging.getLogger("actor")
cmdLogger = logging.getLogger("cmds")


class CommandLink(LineReceiver):

    # How we match a command...
    #     1. optional cmdrName
    #     2. optional MID
    #     3. command string
    cmdRe = re.compile(
        r"""
    ^\s*
    (?:(?P<cmdrName>(?:[a-z][a-z0-9_]*)?(?:\.(?:[a-z][a-z0-9_]*))+)\s+)?
    (?:(?P<mid>[0-9]+)\s+)?
    (?P<cmdString>.+)""",
        re.IGNORECASE | re.VERBOSE,
    )

    def __init__(self, brains, connID, eol="\n"):
        """Receives what should be atomic commands, parses them, and passes them on."""
        # LineReceiver.__init__(self) # How can they live without?

        self.brains = brains
        self.connID = connID
        self.delimiter = eol
        self.delimiterChecked = False
        self.outputQueue = []
        self.outputQueueLock = threading.Lock()

        self.mid = 1  # In case we need to self-assign MIDs

    def connectionMade(self):
        """Called when our connection has been established."""

        actorLogger.debug("new CommandNub")
        cmdrName = "self.%d" % self.connID
        cmd = Command(self.factory, cmdrName, self.connID, 0, "")
        cmd.finish("yourUserNum=%d" % self.connID)

    def dataReceived(self, cmdString):
        """Called when a complete line has been read from the hub.

        This used to be lineReceived but something changed in Twisted ...
        Also, dealing with Unicode vs bytes.

        """

        # Deal with unicode
        cmdString = cmdString.decode().strip()

        # NOTE: JSG - I'm commenting this since I'm not sure what's the point.
        # It doesn't seem to deal with the delimiters for each message received;
        # maybe something has happened with Twisted. It seems just stripping
        # does work fine ...

        # Telnet connections send back '\r\n'. Or worse, I fear. Try to make
        # those connections work just like properly formatted ones.
        # if not self.delimiterChecked:
        #     while len(cmdString) > 0 and cmdString[-1] < ' ':
        #         self.delimiter = cmdString[-1] + self.delimiter
        #         cmdString = cmdString[:-1]
        #     self.delimiterChecked = True

        # Parse the header...
        m = self.cmdRe.match(cmdString)
        if not m:
            self.brains.bcast.warn(
                "text=%s" % (qstr("cannot parse header for %s" % (cmdString)))
            )
            cmdLogger.critical("cannot parse header for: %s" % (cmdString))
            return
        cmdDict = m.groupdict()

        # Look for, or create, an integer MID.
        rawMid = cmdDict["mid"]
        if rawMid == "" or rawMid is None:  # Possibly self-assign a MID
            mid = self.mid
            self.mid += 1
        else:
            try:
                mid = int(rawMid)
            except Exception:
                self.brains.bcast.warn(
                    "text=%s"
                    % (qstr("command ignored: MID is not an integer in %s" % cmdString))
                )
                cmdLogger.critical("MID must be an integer: %s" % (rawMid))
                return
        if mid >= self.mid:
            self.mid += 1

        cmdrName = cmdDict["cmdrName"]
        if cmdrName == "" or cmdrName is None:
            cmdrName = "self.%d" % (self.connID)  # Fabricate a connection ID.

        # And hand it upstairs.
        try:
            cmd = Command(
                self.factory, cmdrName, self.connID, mid, cmdDict["cmdString"]
            )
            self.brains.newCmd(cmd)
        except Exception as e:
            self.brains.bcast.fail(
                "text=%s"
                % (
                    qstr(
                        "cannot process command: %s (exception=%s)"
                        % (cmdDict["cmdString"], e)
                    )
                )
            )
            cmdLogger.warn(tback("lineReceived", e))

    def sendQueuedResponses(self):
        """Method for the twisted reactor to call when we tell
        it there is output from this thread."""

        cmdLogger.debug("flushing queue to all outputs...")
        with self.outputQueueLock:
            while len(self.outputQueue) > 0:
                e = self.outputQueue.pop(0).encode(sys.getdefaultencoding())
                cmdLogger.debug("flushing queue line: %s" % (e[:-1]))
                self.transport.write(e)

    def sendResponse(self, cmd, flag, response):
        """Ship a command off to the hub."""

        e = "%d %d %s %s\n" % (cmd.cid, cmd.mid, flag, response)
        cmdLogger.info("> %s" % (e[:-1]))
        with self.outputQueueLock:
            self.outputQueue.append(e)
        reactor.callFromThread(self.sendQueuedResponses)

    def shutdown(self, why="cuz"):
        """Called from above when we want to drop the connection."""

        self.brains.bcast.respond(
            "text=%s" % (qstr("shutting connection %d down" % (self.connID)))
        )
        actorLogger.info("CommandLink.shutdown because %s", why)
        self.transport.loseConnection()

    def connectionLost(self, reason="cuz"):
        """Called from below when the connection is dropped."""

        actorLogger.info("connectionLost of %s because %s", self, reason)
        self.factory.loseConnection(self)
