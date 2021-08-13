import logging
import queue
import sys
import threading

import opscore.actor.cmdkeydispatcher as opsDispatcher
import opscore.actor.keyvar as opsKeyvar
import opscore.actor.model as opsModel
from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver


def encode(cmdStr):
    """To encode unicode strings as something Twisted will take."""
    return cmdStr.encode(sys.getdefaultencoding())


class CmdrConnection(LineReceiver):
    def __init__(self, readCallback, brains, logger=None, **argv):
        """The Commander twisted Protocol: sends command lines and passes on replies."""

        self.delimiter = "\n"
        self.readCallback = readCallback
        self.brains = brains
        self.lock = threading.Lock()
        self.logger = logger if logger else logging.getLogger("cmdr")

        self.logger.info("starting new CmdrConnection")

    def connectionMade(self):
        self.brains.connectionMade()

    def write(self, cmdStr):
        """Main entry point for sending a command.

        Args:
           cmdstr (str): a Command to send
        """

        with self.lock:
            # encode, incase we received a unicode string.
            self.logger.debug("transporting command %s" % (encode(cmdStr)))
            self.transport.write(encode(cmdStr))

    def lineReceived(self, replyStr):
        """Incorporate an entire reply line.

        Args:
           replyStr   - the new reply line.
        """

        self.logger.debug("read: " + replyStr)
        self.readCallback(self.transport, replyStr)


class CmdrConnector(ReconnectingClientFactory):
    def __init__(self, name, brains, logger=None):
        self.name = name
        self.cmdr = name
        self.brains = brains
        self.readCallback = None
        self.stateCallback = None

        self.maxDelay = 60
        self.initialDelay = 0.5
        self.factor = 2

        # We can only have one connection...
        self.activeConnection = None

        self.logger = logger if logger else logging.getlogger("cmdr")

    def doStart(self):
        self.logger.warn("in doStart")

    def buildProtocol(self, addr):
        """A new connection has been established. Create a new Protocol."""

        self.logger.warn("launching new CmdrConnection")

        assert self.activeConnection is None, "connection already active!"
        assert self.readCallback is not None, "readCallback has not yet been set!"

        self.resetDelay()
        proto = CmdrConnection(
            self.readCallback, brains=self.brains, logger=self.logger
        )
        proto.factory = self
        self.activeConnection = proto
        self.stateCallback(self)

        return proto

    def clientConnectionLost(self, connector, reason):
        """We are called when our connection is lost.
        Start trying to create a new connection.
        """

        self.logger.warn("CmdrConnection lost: %s " % reason)

        self.activeConnection = None
        self.stateCallback(self)
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):

        self.logger.warn("CmdrConnection failed: %s " % (reason))

        self.activeConnection = None
        self.stateCallback(self)
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)

    def isConnected(self):
        """Called by the dispatcher to find out if we are connected."""
        return self.activeConnection is not None

    def addReadCallback(self, readCallback):
        self.readCallback = readCallback

    def addStateCallback(self, stateCallback):
        self.stateCallback = stateCallback

    def writeLine(self, cmdStr):
        """Called by the dispatcher to send a command."""
        # encode, incase we received a unicode string.
        self.logger.info(">> %s" % (encode(cmdStr)))
        if not self.activeConnection:
            raise RuntimeError("not connected.")

        self.activeConnection.write(encode(cmdStr) + "\n")


class Cmdr(object):
    def __init__(self, name, actor, loggerName="cmdr"):
        self.actor = actor

        logger = logging.getLogger(loggerName)
        self.logger = logger

        self.connector = CmdrConnector(name, self, logger=logger)
        self.factory = self.connector

        # Start a dispatcher, connected to our logger. Wire the dispatcher
        # in to the Model "singleton"
        logger = logging.getLogger("dispatch")
        try:
            dispatchLevel = self.actor.config["logging"]["dispatchLevel"]
        except BaseException:
            dispatchLevel = logging.WARN
        logger.setLevel(dispatchLevel)

        def logFunc(msgStr, severity, actor, cmdr, keywords, cmdID=0, logger=logger):
            logger.info("%s %s.%s %s %s" % (cmdr, actor, cmdID, severity, msgStr))

        self.dispatcher = opsDispatcher.CmdKeyVarDispatcher(
            name, self.connector, logFunc, includeName=True
        )
        opsModel.Model.setDispatcher(self.dispatcher)

    def connectionMade(self):
        pass

    def connect(self):
        tronHost = self.actor.config["tron"]["tronHost"]
        tronPort = int(self.actor.config["tron"]["tronCmdrPort"])

        reactor.connectTCP(tronHost, tronPort, self.connector)

    def call(self, **argv):
        """Send a command and generate all its output.

        The arguments are passed right through to the keyvar.CmdVar. If the callCodes is
        set to keyvar.AllCodes, this function generates all the individual response lines,
        otherwise it returns all the linesa at once.
        """

        q = self.cmdq(**argv)
        ret = q.get()
        self.logger.info("command %s returned " % (ret))
        return ret

    def cmdq(self, **argv):
        """Send a command and return a Queue on which the command output will be put."""
        self.logger.info("queueing command %s" % (argv))

        q = queue.Queue()
        argv["callFunc"] = q.put
        cmdvar = opsKeyvar.CmdVar(**argv)
        reactor.callFromThread(self.dispatcher.executeCmd, cmdvar)

        return q

    def waitForKey(self, **argv):
        self.logger.info("sending command %s" % (argv))

        q = queue.Queue()
        argv["callFunc"] = q.put
        keyvar = opsKeyvar.KeyVar(**argv)
        reactor.callFromThread(self.dispatcher.executeCmd, keyvar)
        ret = q.get()

        self.logger.info("waitForKey %s returned %s " % (argv, ret))
        return ret


def liveTest():
    """Connect to a running hub and print out all tcc traffic."""
    import opscore.actor.keyvar as keyvar

    logger = logging.getLogger("test")

    def showVal(keyVar, logger=logger):
        logger.info(
            "keyVar %s.%s = %r, isCurrent = %s"
            % (keyVar.actor, keyVar.name, keyVar.valueList, keyVar.isCurrent)
        )

    cmdr = Cmdr("test.me")
    cmdr.connect()

    # Register all tcc keywords to be printed.
    tccModel = opsModel.Model("tcc")
    for o in list(tccModel.__dict__.values()):
        if isinstance(o, keyvar.KeyVar):
            o.addCallback(showVal)

    reactor.run()


def main():
    liveTest()


if __name__ == "__main__":
    main()
