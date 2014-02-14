"""
Help for writing test cases that need a Cmdr, Model, Actor, etc.
"""
import sys

from actorcore import Actor
from opscore.actor import keyvar
from opscore.protocols import keys,types,parser

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
othersOff = {'whtLampCommandedOn':[False],'uvLampCommandedOn':[False],}
semaphoreGood = {'semaphoreOwner':['None']}
semaphoreBad = {'semaphoreOwner':['SomeEvilGuy']}
mcpState = {}
mcpState['flats'] = merge_dicts(ffsClosed,arcOff,flatOn)
mcpState['arcs'] = merge_dicts(ffsClosed,arcOn,flatOff)
mcpState['science'] = merge_dicts(ffsOpen,arcOff,flatOff)
mcpState['all_off'] = merge_dicts(ffsClosed,arcOff,flatOff)
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


# TCC state setup
tccBase = {'axisBadStatusMask':['0x00057800'], 
           'moveItems':[''], 'inst':['guider'], 
           'slewEnd':'', 'tccStatus':['','']}
axisStat = {'azStat':[0]*4, 'altStat':[0]*4, 'rotStat':[0]*4}
tccState = {}
# TBD: there's gotta be a better way to combine dicts than this!
tccState['stopped'] = merge_dicts(tccBase, axisStat)


# guider state setup
cartLoaded = {'cartridgeLoaded':[1,1000,'A',54321,0]}
noDecenter = {'decenter':[0,'disabled',0,0,0,0,0]}
yesDecenter = {'decenter':[0,'enabled',0,0,0,0,0]}
# The below is stolen from guiderActor.Commands.GuiderCommand
mangaDithers = {'N':(-0.417, +0.721, 0.0),
                'S':(-0.417, -0.721, 0.0),
                'E':(+0.833, 0.000, 0.0),
                'C':(0.0,0.0,0.0)}
mangaNDecenter = {'decenter':[0,'enabled',-0.417,+0.721,0,0,0]}
mangaSDecenter = {'decenter':[0,'enabled',-0.417,-0.721,0,0,0]}
mangaEDecenter = {'decenter':[0,'enabled',+0.833,0,0,0,0]}
guiderState = {}
guiderState['cartLoaded'] = merge_dicts(cartLoaded,noDecenter)

class Cmd(object):
    """
    Fake commander object, keeps the message level and message for
    all messages sent through it. 
    """
    def __init__(self,verbose=False):
        """Save the level of any messages that pass through."""
        self.verbose = verbose
        self.levels = ''
        self.messages = []
        self.finished = False
        self.nFinished = 0
        self.cParser = parser.CommandParser()
    def __repr__(self):
        return 'TestHelperCmdr-%s'%('finished' if self.finished else 'running')
        
    def _msg(self,txt,level):
        if self.verbose:
            # because "print" isn't threadsafe in py27
            sys.stderr.write('%s %s\n'%(level,txt))
            sys.stderr.flush()
        self.levels += level
        self.messages.append(txt)
    def _checkFinished(self):
        if self.finished:
            print "!!!!!This cmd already finished %d times!"%self.nFinished
            self.nFinished += 1
    def inform(self,txt):
        self._msg(txt,'i')
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
    
    def finish(self,txt):
        self._checkFinished()
        self._msg(txt,'F')
        self.finished = True
    def isAlive(self):
        return not self.finished
    
    def call(self,*args,**kwargs):
        """Pretend to complete command successfully."""
        if args:
            # for handling FakeThread stuff.
            text = str(*args)
            self._msg(text,'c')
            self.didFail = False
            return
        cmdStr = kwargs.get('cmdStr')
        timeLim = kwargs.get('timeLim',-1)
        actor = kwargs.get('actor',None)
        caller = kwargs.get('forUserCmd',None)
        baseText = ' '.join((str(actor), '%s [%s]'%(cmdStr,timeLim)))
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
        
        # Handle commands where we have to set a new state.
        if actor == 'apogee':
            self.apogee_succeed(*args,**kwargs)
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
            print "!!Error: %s"%e
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
    
    def mcp_succeed(self,*args,**kwargs):
        """Handle mcp commands as successes, and update appropriate keywords."""
        try:
            cmdStr = kwargs.get('cmdStr')
            if 'ff.' in cmdStr:
                key,newVal = self._do_lamp('ff',cmdStr.split('.')[-1])
            elif 'ffs.' in cmdStr:
                key,newVal = self._do_ffs(cmdStr.split('.')[-1])
            else:
                raise ValueError('Unknown mcp command: %s'%cmdStr)
        except ValueError:
            self.didFail = True
        else:
            self.didFail = False
            global globalModels
            globalModels['mcp'].keyVarDict[key].set(newVal)
                
    def _do_lamp(self,lamp,state):
        """Change lamp to new state"""
        key = lamp.lower()+'Lamp'
        if state == 'on':
            newVal = [1]*4
        elif state == 'off':
            newVal = [1]*4
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
            #elif cmd.name == 'expose':
            #    key,newVal = self._get_expose(cmd.keywords)
            else:
                raise ValueError("I don't know what to do with this: %s"%cmdStr)
        except ValueError as e:
            print "!!Error: %s"%e
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
            newVal = mangaNDecenter
        elif pos == 'S':
            newVal = mangaSDecenter
        elif pos == 'E':
            newVal = mangaEDecenter
        else:
            raise ValueError("I don't know what to do with this mangaDither: %s"%keywords)
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
    def __init__(self,name):
        self.name = name

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
            self.actor = FakeActor(actor)
            self.actor.bcast = cmd
            self.actor.cmdr = cmd
        for m,p in zip(models,modelParams):
            self.models[m] = Model(m,p)
        global globalModels
        globalModels = self.models
    
