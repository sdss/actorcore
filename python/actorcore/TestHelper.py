"""
Help for writing test cases that need a Cmdr, Model, Actor, etc.
"""

from actorcore import Actor
from opscore.actor import keyvar
from opscore.protocols import keys,types
 
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
    def _msg(self,txt,level):
        if self.verbose:
            print level,txt
        self.levels += level
        self.messages.append(txt)
    def inform(self,txt):
        self._msg(txt,'i')
    def respond(self,txt):
        self._msg(txt,'i')
    def diag(self,txt):
        self._msg(txt,'d')
    def warn(self,txt):
        self._msg(txt,'w')
    def fail(self,txt):
        self._msg(txt,'f')
    def error(self,txt):
        self._msg(txt,'e')
    
    def finish(self,txt):
        if self.finished:
            print "!!!!!!!!!!!!!!!!"
            print "This Cmd already finished!"
            return False
        self._msg(txt,'F')
        self.finished = True
        
    def call(self,*args,**kwargs):
        """Pretend to complete command successfully."""
        text = str(*args)
        for k,v in sorted(kwargs.items()):
            text = ' '.join((text,'%s=%s'%(k,v)))
        self._msg(text,'c')
        self.didFail = False            
        return self

class Model(object):
    """quick replacement for Model in opscore/actorcore."""
    def __init__(self,actor,keyDict={}):
        self.actor = actor
        self.myKeys = keys.KeysDictionary.load(actor)
        self.keyVarDict = {}
        for k,v in keyDict.items():
            keyType = keys.Key(k,self.get_TypedValue(k))
            self.keyVarDict[k] = keyvar.KeyVar(actor,self.myKeys[k])#,doPrint=True)
            self.keyVarDict[k].set(v)
        
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
