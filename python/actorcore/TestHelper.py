"""
Help for writing test cases that need a Cmdr, Model, Actor, etc.
"""
import sys
import os
import re
import time
import imp
import inspect
import logging

from actorcore import Actor

import opscore.protocols.validation as validation
from opscore.utility.qstr import qstr
from opscore.actor import keyvar
from opscore.protocols import keys,types,parser,messages

# To allow fake-setting/handling of the various actor models.
global globalModels
globalModels = {}

def merge_dicts(*args):
    """Merge many dicts and return the result."""
    return {k:v for d in args for k,v in d.iteritems()}

# MCP state setup
ffsClosed = {'ffsStatus':['01']*8}
ffsOpen = {'ffsStatus':['10']*8}
arcOn = {'hgCdLamp':[1]*4, 'neLamp':[1]*4}
arcOff = {'hgCdLamp':[0]*4, 'neLamp':[0]*4}
flatOn = {'ffLamp':[1]*4}
flatOff = {'ffLamp':[0]*4}
othersOff = {'whtLampCommandedOn':[0],'uvLampCommandedOn':[0],}
semaphoreGood = {'semaphoreOwner':['None']}
semaphoreBad = {'semaphoreOwner':['SomeEvilGuy']}
gangBad = {'apogeeGang':[1]}
gangCart = {'apogeeGang':[2]}
gangPodium = {'apogeeGang':[4]}
gang1m = {'apogeeGang':[36]}
mcpState = {}
mcpState['flats'] = merge_dicts(ffsClosed,arcOff,flatOn,gangPodium)
mcpState['arcs'] = merge_dicts(ffsClosed,arcOn,flatOff,gangPodium)
mcpState['boss_science'] = merge_dicts(ffsOpen,arcOff,flatOff,gangPodium)
mcpState['apogee_science'] = merge_dicts(ffsOpen,arcOff,flatOff,gangCart)
mcpState['all_off'] = merge_dicts(ffsClosed,arcOff,flatOff,gangPodium)
mcpState['apogee_parked'] = merge_dicts(ffsClosed,arcOff,flatOff,gangCart)
# these lamps should always be off, so set them as such...
for n in mcpState:
    mcpState[n].update(othersOff)
    mcpState[n].update(semaphoreGood)


# APOGEE state setup
ditherA = {'ditherPosition':[0,'A']}
ditherB = {'ditherPosition':[0.5,'B']}
ditherUnknown = {'ditherPosition':['NaN','?']}
shutterClosed = {'shutterLimitSwitch':['false','true']}
shutterOpen = {'shutterLimitSwitch':['true','false']}
shutterUnknown = {'shutterLimitSwitch':['false','false']}
notReading = {'utrReadState':['','Done',0,0]}
reading = {'utrReadState':['object','Reading',1,2]}
apogeeState = {}
apogeeState['A_closed'] = merge_dicts(ditherA, shutterClosed, notReading)
apogeeState['B_open'] = merge_dicts(ditherB, shutterOpen, notReading)
apogeeState['unknown'] = merge_dicts(ditherUnknown, shutterUnknown, notReading)


#BOSS state setup
exposureIdle = {'exposureState':['IDLE',0,0]}
exposureIntegrating = {'exposureState':['INTEGRATING',900,100]}
exposureReading = {'exposureState':['READING',60,10]}
exposureAborted = {'exposureState':['ABORTED',0,0]}
bossState = {}
bossState['idle'] = merge_dicts(exposureIdle)
bossState['integrating'] = merge_dicts(exposureIntegrating)
bossState['reading'] = merge_dicts(exposureReading)
bossState['aborted'] = merge_dicts(exposureAborted)


# TCC state setup
tccBase = {'axisBadStatusMask':['0x00057800'], 'utc_TAI':[-35.0],
           'moveItems':[''], 'inst':['guider'], 'objName':[''],
           'slewEnd':'', 'tccStatus':['',''],
           'objNetPos':[121.0, 0.0, 4908683470.64, 30.0, 0.0, 4908683470.64]}
axisStat = {'azStat':[0]*4, 'altStat':[0]*4, 'rotStat':[0]*4}
atStow = {'axePos':[121,15,0]}
atGangChange = {'axePos':[121,45,0]}
atInstChange = {'axePos':[0,90,0]}
tccState = {}
tccState['stopped'] = merge_dicts(tccBase, axisStat, atStow)


# guider state setup
bossLoaded = {'cartridgeLoaded':[11,1000,'A',54321,1], 'survey':['BOSS','BOSS']}
apogeeLoaded = {'cartridgeLoaded':[1,2000,'A',54321,2], 'survey':['APOGEE','APOGEE']}
mangaLoaded = {'cartridgeLoaded':[2,3000,'A',54321,3], 'survey':['MaNGA','MaNGA Dither']}
apogeemangaLoaded = {'cartridgeLoaded':[3,4000,'A',54321,4], 'survey':['APOGEE-2;MaNGA','MaNGA Dither']}
noDecenter = {'decenter':[0,'disabled',0,0,0,0,0]}
yesDecenter = {'decenter':[0,'enabled',0,0,0,0,0]}
guiderOn = {'guideState':['on']}
guiderOff = {'guideState':['off']}
# The below was stolen from guiderActor.Commands.GuiderCommand
mangaDithers = {'N':(-0.417, +0.721, 0.0),
                'S':(-0.417, -0.721, 0.0),
                'E':(+0.833, 0.000, 0.0),
                'C':(0.0,0.0,0.0)}
mangaN = {'mangaDither':['N'],'decenter':[0,'enabled',-0.417,+0.721,0,0,0]}
mangaS = {'mangaDither':['S'],'decenter':[0,'enabled',-0.417,-0.721,0,0,0]}
mangaE = {'mangaDither':['E'],'decenter':[0,'enabled',+0.833,0,0,0,0]}
mangaC = {'mangaDither':['C'],'decenter':[0,'disabled',0,0,0,0,0]}
guiderState = {}
guiderState['cartLoaded'] = merge_dicts(guiderOff,bossLoaded,mangaC)
guiderState['bossLoaded'] = merge_dicts(guiderOff,bossLoaded,mangaC)
guiderState['apogeeLoaded'] = merge_dicts(guiderOff,apogeeLoaded,mangaC)
guiderState['mangaLoaded'] = merge_dicts(guiderOff,mangaLoaded,mangaC)
guiderState['apogeemangaLoaded'] = merge_dicts(guiderOff,apogeemangaLoaded,mangaC)
guiderState['guiderOn'] = merge_dicts(guiderOn,bossLoaded,mangaC)
guiderState['guiderOnDecenter'] = merge_dicts(guiderOn,mangaLoaded,mangaN)


# platedb state setup
bossPointing = {'pointingInfo':[1000,11,'A',10.,20.,1.,0.,5500,'BOSS','BOSS']}
apogeePointing = {'pointingInfo':[2000,1,'A',20.,30.,2.,1.,10500,'APOGEE','APOGEE']}
mangaPointing = {'pointingInfo':[3000,2,'A',30.,40.,3.,2.,5500,'MaNGA','MaNGA dither']}
apogeemangaPointing = {'pointingInfo':[4000,3,'A',40.,50.,4.,3.,10500,'APOGEE-MANGA','APOGEE lead']}
mangaapogeePointing = {'pointingInfo':[5000,4,'A',50.,60.,5.,4.,5500,'APOGEE-MaNGA','MaNGA dither']}
platedbState = {}
platedbState['boss'] = merge_dicts(bossPointing)
platedbState['apogee'] = merge_dicts(apogeePointing)
platedbState['manga'] = merge_dicts(mangaPointing)
platedbState['apogee_manga'] = merge_dicts(mangaapogeePointing)
platedbState['manga_apogee'] = merge_dicts(apogeemangaPointing)

# gcamera state setup
gcameraTempOk = {'cooler':[-40,-40,-40,80,1,'Correcting']}
gcameraState = {}
gcameraState['ok'] = merge_dicts(gcameraTempOk)

# sop state setup
bypasses = ["ffs", "ff_lamp", "hgcd_lamp", "ne_lamp", "axes",
            "brightPlate", "darkPlate", "gangCart", "gangPodium",
            "slewToField","guiderDark"]
sopNoBypass = {'bypassNames':bypasses,'bypassed':[0,]*len(bypasses)}
sopEmptyCommands = {"surveyCommands":('gotoStow', 'gotoInstrumentChange')}
sopBossCommands = {"surveyCommands":('gotoField','hartmann', 'doBossCalibs',
                                      'doBossScience','gotoInstrumentChange')}
sopMangaCommands = {"surveyCommands":('gotoField', 'hartmann', 'doBossCalibs',
                                      'doMangaDither', 'doMangaSequence',
                                      'gotoInstrumentChange')}
sopApogeeCommands = {"surveyCommands":('gotoField', 'doApogeeScience',
                                       'doApogeeSkyFlats', 'gotoGangChange',
                                       'gotoInstrumentChange', 'doApogeeDomeFlat')}
sopApogeeMangaCommands = {"surveyCommands":('gotoField',
                                            'hartmann', 'doBossCalibs',
                                            'doApogeeMangaDither', 'doApogeeMangaSequence',
                                            'doApogeeSkyFlats', 'gotoGangChange',
                                            'gotoInstrumentChange', 'doApogeeDomeFlat')}


sopState = {}
sopState['ok'] = merge_dicts(sopNoBypass,sopEmptyCommands)


class Cmd(object):
    """
    Fake commander object, keeps the message level and message for
    all messages sent through it.
    """
    def __init__(self,verbose=False):
        """Save the level of any messages that pass through."""
        self.verbose = verbose
        self.finished = False
        self.nFinished = 0
        self.didFail = False
        self.cParser = parser.CommandParser()
        self.clear_msgs()
        self.cmdr = None # to make an Actor happy
        self.mid = 0 # to make an Actor happy

        # Always fail when failOn is called as a command.
        self.failOn = None
        # Increase failOnCount to fail on the Nth call of failOn.
        self.failOnCount = 1

        # to keep track of whether BOSS hasn't been readout.
        self.bossNeedsReadout = False
        
    def __repr__(self):
        return 'TestHelperCmdr-%s'%('finished' if self.finished else 'running')
    
    # Copied from opscore.actor.keyvar.py:CmdVar
    @property
    def lastReply(self):
        """Return the last reply object, or None if no replies seen"""
        if not self.replyList:
            return None
        return self.replyList[-1]

    def _msg(self,txt,level):
        if self.verbose:
            # because "print" isn't threadsafe in py27
            sys.stderr.write('%s %s\n'%(level,txt))
            sys.stderr.flush()
        self.levels += level
        self.messages.append(txt)
    def _checkFinished(self):
        if self.finished:
            badTxt="!!!!!This cmd already finished %d times!"%self.nFinished
            self._msg(badTxt,'w')
        self.nFinished += 1
    
    def clear_msgs(self):
        """Clear all message text, levels, and calls."""
        self.levels = ''
        self.messages = []
        self.calls = []
        self.replyList = []

    def inform(self,txt):
        self._msg(txt,'i')
        # fake-set the model, if needs-be
        self.use_keywords(txt)
    def respond(self,txt):
        self._msg(txt,'i')
    def diag(self,txt):
        self._msg(txt,'d')
    def warn(self,txt):
        self._msg(txt,'w')
    def error(self,txt):
        self._msg(txt,'e')
    def fail(self,txt):
        self._checkFinished()
        self._msg(txt,'f')
        self.finished = True
        self.didFail = True
    
    def finish(self,txt=''):
        self._checkFinished()
        self._msg(txt,'F')
        self.finished = True
    def isAlive(self):
        return not self.finished
    
    def use_keywords(self,txt):
        """Update a model keyword, given an inform-level output."""
        key = 'surveyCommands'
        if key in txt:
            val = txt.split('=')[-1].split(', ')
            global globalModels
            globalModels['sop'].keyVarDict[key].set(val)

    def call(self,*args,**kwargs):
        """Pretend to complete command successfully."""
        
        # for handling FakeThread stuff.
        if args:
            text = str(*args).strip()
            self._msg(text,'c')
            if self.failOn is not None and command == self.failOn:
                if self.failOnCount == 1:
                    self.didFail = True
                else:
                    self.failOnCount -= 1
                    self.didFail = False
            else:
                self.didFail = False
            return self
        
        # for handling "real" commands
        cmdStr = kwargs.get('cmdStr')
        timeLim = kwargs.get('timeLim',-1)
        actor = kwargs.get('actor',None)
        caller = kwargs.get('forUserCmd',None)
        baseText = ' '.join((str(actor), cmdStr, '<<timeLim=%s>>'%(timeLim)))
        if caller is not None and not isinstance(caller,Cmd):
            raise TypeError("You can't call %s with forUserCmd=%s."%(baseText,caller))
        try:
            cmd = self.cParser.parse(cmdStr)
            cmdTxt = ' '.join((actor,cmd.string))
            other = '<<timeLim=%.1f>>'%(timeLim)
            text = ' '.join((cmdTxt,other))
        except (parser.ParseError, AttributeError) as e:
            text = baseText
        self._msg(text,'c')
        command = text.split('<<')[0].strip()
        self.calls.append(command)
        if self.failOn is not None and command == self.failOn:
            if self.failOnCount == 1:
                self.didFail = True
                return self
            else:
                self.failOnCount -= 1
        
        # Handle commands where we have to set a new state.
        if actor == 'apogee':
            self.apogee_succeed(*args,**kwargs)
        elif actor == 'boss':
            self.boss_succeed(*args,**kwargs)
        elif actor == 'mcp':
            self.mcp_succeed(*args,**kwargs)
        elif actor == 'guider':
            self.guider_succeed(*args,**kwargs)
        else:
            self.didFail = False
        return self
    
    def apogee_succeed(self,*args,**kwargs):
        """Handle apogee commands as successes, and update appropriate keywords."""
        cmdStr = kwargs.get('cmdStr')
        try:
            cmd = self.cParser.parse(cmdStr)
            if cmd.name == 'dither':
                key,newVal = self._get_dither(cmd.keywords)
            elif cmd.name == 'shutter':
                key,newVal = self._get_shutter(cmd.keywords)
            elif cmd.name == 'expose':
                key,newVal = self._get_expose(cmd.keywords)
            else:
                raise ValueError("I don't know what to do with this: %s"%cmdStr)
        except ValueError as e:
            print 'ValueError in apogee_succeed:',e
            self.didFail = True
        else:
            self.didFail = False
            global globalModels
            globalModels['apogee'].keyVarDict[key].set(newVal[key])

    def _get_dither(self,keywords):
        """Return the key/value pair for a requested new dither position."""
        cmdVal = keywords['namedpos'].values[0]
        key = 'ditherPosition'
        if cmdVal == 'A':
            newVal = ditherA
        elif cmdVal == 'B':
            newVal = ditherB
        else:
            raise ValueError('Unknown dither position: %s'%cmdVal)
        return key,newVal
    
    def _get_shutter(self,keywords):
        """Return the key/value pair for a requested new shutter position."""
        key = 'shutterLimitSwitch'
        if 'open' in keywords:
            newVal = shutterOpen
        elif 'close' in keywords:
            newVal = shutterClosed
        else:
            raise ValueError('Unknown shutter position: %s'%keywords)
        return key,newVal
    
    def _get_expose(self,keywords):
        """Return the key/value pair for a requested exposure."""
        key = 'utrReadState'
        time = keywords['time'].values[0]
        nReads = float(time)/10.
        name = keywords['object'].values[0]
        newVal = {key:(name,'Reading',1,nReads)}
        return key,newVal
    
    def boss_succeed(self,*args,**kwargs):
        """Handle boss commands as successes, and remember if we need to readout."""
        cmdStr = kwargs.get('cmdStr')
        cmd = self.cParser.parse(cmdStr)
        if cmd.name == 'exposure':
            readout = 'readout' in cmd.keywords
            noreadout = 'noreadout' in cmd.keywords
            if readout and self.bossNeedsReadout:
                self.bossNeedsReadout = False
                self.didFail = False
                time.sleep(1) # waiting a short bit helps with lamp timings.
            elif readout and not self.bossNeedsReadout:
                self.didFail = True
                print "Error! boss says: No exposure to act on."
            elif not readout and self.bossNeedsReadout:
                self.didFail = True
                print "Error! Cannot take BOSS exposure: need to readout previous one!"
            elif noreadout:
                self.bossNeedsReadout = True
                self.didFail = False
                time.sleep(1) # waiting a short bit helps with lamp timings.
            else:
                self.bossNeedsReadout = False
                self.didFail = False
                time.sleep(1) # waiting a short bit helps with lamp timings.
        else:
            # any other boss commands just succeed.
            self.didFail = False
    
    def mcp_succeed(self,*args,**kwargs):
        """Handle mcp commands as successes, and update appropriate keywords."""
        try:
            cmdStr = kwargs.get('cmdStr')
            if 'ff.' in cmdStr:
                result = self._do_lamp('ff',cmdStr.split('.')[-1])
            elif 'ne.' in cmdStr:
                result = self._do_lamp('ne',cmdStr.split('.')[-1])
            elif 'hgcd.' in cmdStr:
                result = self._do_lamp('hgCd',cmdStr.split('.')[-1])
            elif 'wht.' in cmdStr:
                # these two lamps are always off. So do nothing.
                self.didFail = False
                return
            elif 'uv.' in cmdStr:
                self.didFail = False
                return
            elif 'ffs.' in cmdStr:
                result = self._do_ffs(cmdStr.split('.')[-1])
            else:
                raise ValueError('Unknown mcp command: %s'%cmdStr)
        except ValueError as e:
            print 'ValueError in mcp_succeed:',e
            self.didFail = True
        else:
            if result is None:
                # key was already newVal, so do nothing.
                return
            else:
                key,newVal = result
            self.didFail = False
            global globalModels
            globalModels['mcp'].keyVarDict[key].set(newVal)
                
    def _do_lamp(self,lamp,state):
        """
        Change lamp to new state.

        Return the new key/value pair, or None if nothing is to be changed.
        """
        key = lamp+'Lamp'
        val = globalModels['mcp'].keyVarDict[key].getValue()

        if (state == 'on' and sum(val) == 4) or (state == 'off' and val == 0):
            return None
        if state == 'on':
            newVal = [1]*4
        elif state == 'off':
            newVal = [0]*4
        else:
            raise ValueError('Unknown %sLamp state: %s'%(lamp,state))
        return key,newVal
    
    def _do_ffs(self,state):
        """Change ffs screens to new state"""
        key = 'ffsStatus'
        if state == 'close':
            newVal = ffsClosed['ffsStatus']
        elif state == 'open':
            newVal = ffsOpen['ffsStatus']
        else:
            raise ValueError('Unknown ffs state: %s'%state)
        return key,newVal
    
    def guider_succeed(self,*args,**kwargs):
        """Handle mcp commands as successes, and update appropriate keywords."""
        cmdStr = kwargs.get('cmdStr')
        try:
            cmd = self.cParser.parse(cmdStr)
            if cmd.name == 'mangaDither':
                key,newVal = self._get_mangaDither(cmd.keywords)
            elif cmd.name == 'decenter':
                key,newVal = self._get_decenter(cmd.keywords)
            elif cmd.name == 'on':
                # This keeps guiderThread happy:
                self.replyList.append(messages.Reply('',[messages.Keyword('Timeout')]))
                key,newVal = 'guideState',guiderOn
            elif cmd.name == 'off':
                key,newVal = 'guideState',guiderOff
            elif cmd.name == 'flat':
                time.sleep(1) # waiting a short bit helps with lamp timings.
                self.didFail = False
                return
            elif cmd.name in ("axes", "scale", "focus"):
                # just succeed on axes clear.
                self.didFail = False
                return
            else:
                raise ValueError("I don't know what to do with this: %s"%cmdStr)
        except ValueError as e:
            print 'ValueError in guider_succeed:',e
            self.didFail = True
        else:
            self.didFail = False
            global globalModels
            globalModels['guider'].keyVarDict[key].set(newVal[key])
        
    def _get_mangaDither(self,keywords):
        """Set a new mangaDither position."""
        key = 'decenter'
        pos = keywords['ditherPos'].values[0]
        if pos == 'N':
            newVal = mangaN
        elif pos == 'S':
            newVal = mangaS
        elif pos == 'E':
            newVal = mangaE
        else:
            raise ValueError("I don't know what to do with this mangaDither: %s"%keywords)
        global globalModels
        globalModels['guider'].keyVarDict['mangaDither'].set(newVal['mangaDither'])
        return key,newVal
        
    def _get_decenter(self,keywords):
        """Change decenter to new state"""
        key = 'decenter'
        if 'on' in keywords:
            newVal = yesDecenter
        elif 'off' in keywords:
            newVal = noDecenter
        else:
            raise ValueError('Unknown decenter state: %s'%(state))
        return key,newVal


class ActorTester(object):
    """
    Helper class for actor-related tests. Sets up a reasonable initial model state.

    Expects that self.name be set to the name of this actor before setUp().
    test suites should subclass this and unittest, in that order.
    """
    
    def setUp(self):
        """Set some defaults and initialize self.actorState."""
        self.timeout = 5
        # Set this to True to fail if there is no cmd_calls defined for that test.
        self.fail_on_no_cmd_calls = False
        if not getattr(self,'test_calls',None):
            self.test_calls = []
        
        try:
            if self.verbose:
                print "\n" # newline after unittest's docstring printing.
        except NameError:
            self.verbose = False
        
        self.cmd = Cmd(verbose=self.verbose)
        
        # default status for some actors
        models = ['mcp','apogee','tcc','guider','platedb','gcamera','sop','boss']
        modelParams = [mcpState['all_off'],
                       apogeeState['A_closed'],
                       tccState['stopped'],
                       guiderState['bossLoaded'],
                       platedbState['boss'],
                       gcameraState['ok'],
                       sopState['ok'],
                       bossState['idle']
                      ]
        self.actorState = ActorState(cmd=self.cmd,actor=self.name,models=models,modelParams=modelParams)
    
    def _run_cmd(self,cmdStr,queue):
        """Run the command in cmdStr on the current actor, and return the resutling msg."""
        self.cmd.rawCmd = cmdStr
        self.actor.runActorCmd(self.cmd)
        if queue is not None:
            return self._queue_get(queue)
        else:
            return None
    
    def _queue_get(self,queue):
        """Get a message off the queue, and fail with a message if there isn't one."""
        try:
            return queue.get(timeout=self.timeout)
        except queue.Empty:
            self.cmd.fail('No message on the queue!')
            return None

    def _check_cmd(self, nCall, nInfo, nWarn, nErr, finish, didFail=False, **kwargs):
        """Check cmd levels, whether it finished, and the cmd.call stack."""
        if self.test_calls is not None:
            self._check_calls(self.test_calls,self.cmd.calls)
        else:
            errMsg = "%s doesn't have a cmd_calls definition!"%self.id()
            print("WARNING: %s"%errMsg)
            self.assertFalse(self.fail_on_no_cmd_calls,errMsg)
        self._check_levels(nCall, nInfo, nWarn, nErr)
        self.assertEqual(self.cmd.finished, finish)
        
        if didFail and finish:
            self.assertEqual(self.cmd.didFail, didFail)
            # if we really "fail"ed, there should be exactly one fail message.
            self.assertEqual(self.cmd.levels.count('f'),1)
        elif not didFail and finish:
            # if we "finish"ed, there should be exactly one finish message, and no fails.
            self.assertEqual(self.cmd.levels.count('F'),1)
            self.assertEqual(self.cmd.levels.count('f'),0)
        else:
            # if we didn't "fail", there should be exactly 0 fail messages.
            self.assertEqual(self.cmd.levels.count('f'),0)
    
    def _check_levels(self, nCall, nInfo, nWarn, nErr):
        """Check that the cmd levels match the expected result."""
        l = self.cmd.levels
        counts = (l.count('c'),l.count('i'),l.count('w'),l.count('e'))
        self.assertEqual(counts,(nCall,nInfo,nWarn,nErr))
    
    def _check_calls(self,test_calls,calls):
        """
        Check that the actual cmd calls match the expected result.
        Have to compare one "block" at a time, because of threading.
        """
        n = 0
        actual,expected = [],[]
        for sublist in test_calls:
            i = len(sublist)
            actual.extend(sorted(calls[n:n+i]))
            expected.extend(sorted(sublist))
            n = n+i
        # tack on anything else that we missed.
        actual.extend(calls[n:])
        self.assertEqual(actual,expected)


#
# Stuff to fake actors/models/etc.
#

class Model(object):
    """quick replacement for Model in opscore/actorcore."""
    def __init__(self,actor,keyDict={}):
        self.actor = actor
        self.myKeys = keys.KeysDictionary.load(actor)
        self.keyVarDict = {}
        for k,v in keyDict.items():
            self.keyVarDict[k] = keyvar.KeyVar(actor,self.myKeys[k])#,doPrint=True)
            self.keyVarDict[k].set(v)
    
    def setKey(self,key,value):
        """Set keyVarDict[key] = value, with appropriate type conversion."""
        self.keyVarDict[key].set(value)
    
    def get_TypedValue(self,name):
        """Returns the TypedValue of the actorkey actor[name]."""
        return self.myKeys[name].typedValues.vtypes[0]
#...

class FakeActor(object):
    """A massively stripped-down version of actorcore.Actor."""
    def __init__(self,name,productName=None):
        self.name = name
        self.commandSets = {}
        self.productName = productName if productName else self.name
        product_dir_name = '$%s_DIR' % (self.productName.upper())
        self.product_dir = os.path.expandvars(product_dir_name)
        self.handler = validation.CommandHandler()
        self.attachAllCmdSets()
        self.cmdLog = logging.getLogger('cmds')
    
    def sendVersionKey(self,cmd):
        cmd.inform("version=FAKE!")
    
    #
    # the cmdSets stuff was lifted from actorcore/Actor.py
    #
    def runActorCmd(self, cmd):
        try:
            cmdStr = cmd.rawCmd
            self.cmdLog.debug('raw cmd: %s' % (cmdStr))
            
            try:
                validatedCmd, cmdFuncs = self.handler.match(cmdStr)
            except Exception, e:
                cmd.fail('text=%s' % (qstr("Unmatched command: %s (exception: %s)" %
                                           (cmdStr, e))))
                    #tback('actor_loop', e)
                return
            
            if not validatedCmd:
                cmd.fail('text=%s' % (qstr("Unrecognized command: %s" % (cmdStr))))
                return
            
            self.cmdLog.info('< %s:%d %s' % (cmd.cmdr, cmd.mid, validatedCmd))
            if len(cmdFuncs) > 1:
                cmd.warn('text=%s' % (qstr("command has more than one callback (%s): %s" %
                                           (cmdFuncs, validatedCmd))))
            try:
                cmd.cmd = validatedCmd
                for func in cmdFuncs:
                    func(cmd)
            except Exception, e:
                cmd.fail('text=%s' % (qstr("command failed: %s" % (e))))
                #tback('newCmd', e)
                return
                
        except Exception, e:
            cmd.fail('text=%s' % (qstr("completely unexpected exception when processing a new command: %s" %
                                       (e))))
            try:
                tback('newCmdFail', e)
            except:
                pass

    def attachCmdSet(self, cname, path=None):
        """ (Re-)load and attach a named set of commands. """

        if path == None:
            path = [os.path.join(self.product_dir, 'python', self.productName, 'Commands')]
               
        file = None
        try:
            file, filename, description = imp.find_module(cname, path)
            mod = imp.load_module(cname, file, filename, description)
        except ImportError, e:
            raise RuntimeError('Import of %s failed: %s' % (cname, e))
        finally:
            if file:
                file.close()

        # Instantiate and save a new command handler.
        exec('cmdSet = mod.%s(self)' % (cname))

        # Check any new commands before finishing with the load. This
        # is a bit messy, as the commands might depend on a valid
        # keyword dictionary, which also comes from the module
        # file.
        #
        # BAD problem here: the Keys define a single namespace. We need
        # to check for conflicts and allow unloading. Right now we unilaterally
        # load the Keys and do not unload them if the validation fails.
        if hasattr(cmdSet, 'keys') and cmdSet.keys:
            keys.CmdKey.addKeys(cmdSet.keys)
        valCmds = []
        for v in cmdSet.vocab:
            try:
                verb, args, func = v
            except ValueError, e:
                raise RuntimeError("vocabulary word needs three parts: %s" % (v))

            # Check that the function exists and get its help.
            #
            funcDoc = inspect.getdoc(func)
            valCmd = validation.Cmd(verb, args, help=funcDoc) >> func
            valCmds.append(valCmd)

        # Got this far? Commit. Save the Cmds so that we can delete them later.
        oldCmdSet = self.commandSets.get(cname, None)
        cmdSet.validatedCmds = valCmds
        self.commandSets[cname] = cmdSet

        # Delete previous set of consumers for this named CmdSet, add new ones.
        if oldCmdSet:
            self.handler.removeConsumers(*oldCmdSet.validatedCmds)
        self.handler.addConsumers(*cmdSet.validatedCmds)
        
    def attachAllCmdSets(self, path=None):
        """ (Re-)load all command classes -- files in ./Command which end with Cmd.py."""

        if path == None:
            self.attachAllCmdSets(path=os.path.join(os.path.expandvars('$ACTORCORE_DIR'), 'python','actorcore','Commands'))
            self.attachAllCmdSets(path=os.path.join(self.product_dir, 'python', self.productName, 'Commands'))
            return

        dirlist = os.listdir(path)
        dirlist.sort()

        for f in dirlist:
            if os.path.isdir(f) and not f.startswith('.'):
                self.attachAllCmdSets(path=f)
            if re.match('^[a-zA-Z][a-zA-Z0-9_-]*Cmd\.py$', f):
                self.attachCmdSet(f[:-3], [path])
                

class ActorState(object):
    """
    A fake version of ActorState, as used in guiderActor and sopActor.
    Holds models and other actors, to facilitate fake global communication.
    """
    dispatcherSet = False
    def __init__(self, cmd=None, actor=None, models=[], modelParams=[]):
        """
        Pass a list of models to create, and modelParams as a list
        of dicts to associate with each model a fake keyVarDict.
        """
        if cmd is None: cmd = Cmd()
        self.models = {}
        if self.dispatcherSet:
            Model.setDispatcher(cmd)
            self.dispatcherSet = True
        if actor is not None:
            productName = ''
            if actor not in ('mcp','tcc'):
                productName = actor+'Actor'
            self.actor = FakeActor(actor,productName=productName)
            self.actor.bcast = cmd
            self.actor.cmdr = cmd
        for m,p in zip(models,modelParams):
            self.models[m] = Model(m,p)
        global globalModels
        globalModels = self.models
    
