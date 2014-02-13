"""
Help for writing test cases that need a Cmdr, Model, Actor, etc.
"""

from actorcore import Actor
from opscore.actor import keyvar
from opscore.protocols import keys,types,parser

# To allow fake-setting/handling of the various actor models.
global globalModels
globalModels = {}

# MCP state setup
ffsClosed = {'ffsStatus':['01']*8}
ffsOpen = {'ffsStatus':['10']*8}
arcOn = {'hgCdLamp':[1]*4, 'neLamp':[1]*4}
arcOff = {'hgCdLamp':[0]*4, 'neLamp':[0]*4}
flatOn = {'ffLamp':[1]*4}
flatOff = {'ffLamp':[0]*4}
othersOff = {'whtLampCommandedOn':[False],'uvLampCommandedOn':[False],}

mcpState = {}
# TBD: there's gotta be a better way to combine dicts than this!
mcpState['flats'] = dict(ffsClosed.items() + arcOff.items() + flatOn.items())
mcpState['arcs'] = dict(ffsClosed.items() + arcOn.items() + flatOff.items())
mcpState['science'] = dict(ffsOpen.items() + arcOff.items() + flatOff.items())
mcpState['all_off'] = dict(ffsClosed.items() + arcOff.items() + flatOff.items())
# these lamps should always be off, so set them as such...
for n in mcpState:
    mcpState[n].update(othersOff)


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
# TBD: there's gotta be a better way to combine dicts than this!
apogeeState['A_closed'] = dict(ditherA.items() + shutterClosed.items() + notReading.items())
apogeeState['B_open'] = dict(ditherB.items() + shutterOpen.items() + notReading.items())
apogeeState['unknown'] = dict(ditherUnknown.items() + shutterUnknown.items() + notReading.items())


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
            print level,txt
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
        self._checkFinished(self)
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
        actor = kwargs.get('actor',None)
        try:
            cmdStr = kwargs.get('cmdStr')
            cmd = self.cParser.parse(cmdStr)
            cmdTxt = ' '.join((actor,cmd.name,cmd.keywords.canonical(' ')))
            caller = kwargs.get('forUserCmd',None)
            timeLim = kwargs.get('timeLim',-1)
            other = '<<caller=%s timeLim=%.1f>>'%(caller,timeLim)
            text = ' '.join((cmdTxt,other))
        except parser.ParseError:
            text = str(*args)
            for k,v in sorted(kwargs.items()):
                text = ' '.join((text,'%s=%s'%(k,v)))
        self._msg(text,'c')
        
        # Handle commands where we have to set a new state.
        if actor == 'apogee':
            self.apogee_succeed(*args,**kwargs)
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
            raise ValueError('Unknown shuter position: %s'%keywords)
        return key,newVal
    
    def _get_expose(self,keywords):
        """Return the key/value pair for a requested exposure."""
        key = 'utrReadState'
        time = keywords['time'].values[0]
        nReads = float(time)/10.
        name = keywords['object'].values[0]
        newVal = {key:(name,'Reading',1,nReads)}
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
    
