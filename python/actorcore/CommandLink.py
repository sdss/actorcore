from __future__ import with_statement

__all__ = ['CommandLink']

import logging
iccLogger = logging.getLogger('icc')
cmdLogger = logging.getLogger('cmds')

import os
import re
import sys
import threading
from twisted.internet import reactor

from opscore.utility.qstr import qstr
from opscore.protocols.parser import CommandParser
from twisted.protocols.basic import LineReceiver

from Command import Command

class CommandLink(LineReceiver):

    # How we match a command...
    #     1. optional cmdrName
    #     2. optional MID
    #     3. command string 
    cmdRe = re.compile(r"""
    ^\s*
    (?:(?P<cmdrName>(?:[a-z][a-z0-9_]*)?(?:\.(?:[a-z][a-z0-9_]*))+)\s+)?
    (?:(?P<mid>[0-9]+)\s+)?
    (?P<cmdString>.+)""",
                       re.IGNORECASE | re.VERBOSE)

    def __init__(self, brains, connID, eol='\n'):
        """ Receives what should be atomic commands, parses them, and passes them on.
        """
        # LineReceiver.__init__(self) # How can they live without?
        
        self.brains = brains
        self.connID = connID
        self.delimiter = eol
        self.parser = CommandParser()
        self.delimiterChecked = False
        self.outputQueue = []
        self.outputQueueLock = threading.Lock()
        
        self.mid = 1                    # In case we need to self-assign MIDs
        
    def connectionMade(self):
        """ Called when our connection has been established. """

        iccLogger.debug('new CommandNub')
        self.brains.bcast.respond('yourUserNum=%d' % self.connID)
        
    def lineReceived(self, cmdString):
        """ Called when a complete line has been read from the hub. """
        
        # Telnet connections send back '\r\n'. Or worse, I fear. Try to make
        # those connections work just like properly formatted ones.
        if not self.delimiterChecked:
            while len(cmdString) > 0 and cmdString[-1] < ' ':
                self.delimiter = cmdString[-1]+self.delimiter
                cmdString = cmdString[:-1]
            self.delimiterChecked = True
            
        # Parse the header...
        m = self.cmdRe.match(cmdString)
        if not m:
            self.brains.bcast.warn('text=%s' % (qstr("cannot parse header for %s" % (cmdString))))
            cmdLogger.critical('cannot parse header for: %s' % (cmdString))
            return
        cmdDict = m.groupdict()

        # Look for, or create, an integer MID.
        rawMid = cmdDict['mid']
        if rawMid == '' or rawMid == None: # Possibly self-assign a MID
            mid = self.mid
            self.mid += 1
        else:    
            try:
                mid = int(rawMid)
            except Exception, e:
                self.brains.bcast.warn('text=%s' % (qstr("command ignored: MID is not an integer in %s" % cmdString)))
                cmdLogger.critical('MID must be an integer: %s' % (rawMid))
                return
        if mid >= self.mid:
            self.mid += 1
        
        cmdrName = cmdDict['cmdrName']
        if cmdrName == '' or cmdrName == None:
            cmdrName = 'self.%d' % (self.connID) # Fabricate a connection ID.

        # Finally, use the standard opscore parser.
        try:
            parsedCmd = self.parser.parse(cmdDict['cmdString'])
        except:
            cmdLogger.critical('cannot parse command string: %s' % (cmdDict['cmdString']))
            cmd = Command(self.factory, cmdrName, self.connID, mid, None)
            self.brains.bcast.fail('text=%s' % (qstr("cannot parse command: %s" % (cmdDict['cmdString']))))
            return
        
        cmdLogger.debug('new command from %s:%d: %s' % (cmdrName, mid, parsedCmd))
        cmd = Command(self.factory, cmdrName, self.connID, mid, parsedCmd)

        # And hand it upstairs.
        try:
            self.brains.newCmd(cmd)
        except:
            self.brains.bcast.fail('text=%s' % (qstr("cannot process parsed command: %s" % 
                                                     (cmdDict['cmdString']))))

    def sendQueuedResponses(self):
        """ method for the twisted reactor to call when we tell it there is output from this thread. """
        
        with self.outputQueueLock:
            while len(self.outputQueue) > 0:
                e = self.outputQueue.pop(0)
                self.transport.write(e)
                
    def sendResponse(self, cmd, flag, response):
        """ Ship a command off to the hub. """

        e = "%d %d %s %s\n" % (self.connID, cmd.mid, flag, response)
        with self.outputQueueLock:
            self.outputQueue.append(e)
        reactor.callFromThread(self.sendQueuedResponses)
            
    def shutdown(self, why="cuz"):
        """ Called from above when we want to drop the connection. """
        
        self.brains.bcast.respond('text=%s' % (qstr("shutting connection %d down" % (self.connID))))
        iccLogger.info("CommandLink.shutdown because %s", why)
        self.transport.loseConnection()
        
    def connectionLost(self, reason="cuz"):
        """ Called from below when the connection is dropped. """
        
        iccLogger.info("connectionLost of %s because %s", self, reason)
        self.factory.loseConnection(self)
