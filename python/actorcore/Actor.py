"""
An actor is a threaded program that communicates with the hub. It accepts
commands (defined in its Commands/*Cmd.py files), sends keywords (defined in its
actorkeys file), and may also send commands to other actors and/or listen for
keywords from other actors.

Prepare an actor by initializing its class. It will read the hub connection and logging
info from a config file and build its command set. If an actor has multiple
individual threads and message queues, you will have to start them separately.

Start an actor by calling its run() method. This will either start a Thread or
a twisted reactor, depending on the value of runInReactorThread.
"""

import abc
import imp
import importlib
import inspect
import logging
import os
import queue
import re
import socket
import sys
import threading
import traceback

from twisted.internet import reactor

import opscore
import opscore.protocols.keys as keys
import opscore.protocols.validation as validation
from opscore.protocols.parser import CommandParser
from opscore.utility.qstr import qstr
from opscore.utility.sdss3logging import setConsoleLevel, setupRootLogger
from opscore.utility.tback import tback
from sdsstools import read_yaml_file

from . import CmdrConnection
from . import Command as actorCmd
from . import CommandLinkManager as cmdLinkManager


class Msg(object):
    """
    Messages that an actor can pass to its threads.
    Subclass it and add more command types for your actor.
    """

    # Priorities
    CRITICAL = 0
    HIGH = 2
    MEDIUM = 4
    NORMAL = 6

    # Command types; use classes so that the unique IDs are automatically generated
    class EXIT:
        pass

    class DONE:
        pass

    class REPLY:
        pass

    def __init__(self, type, cmd, **data):
        self.type = type
        self.cmd = cmd
        self.priority = Msg.NORMAL

        # how long this command is expected to take (may be overridden by data)
        self.duration = 0

        # convert data[] into attributes
        for k, v in list(data.items()):
            self.__setattr__(k, v)
        self.__data = list(data.keys())

    def __repr__(self):
        values = []
        for k in self.__data:
            values.append("{} : {}".format(k, self.__getattribute__(k)))

        return "{}, {}: {{{}}}".format(self.type.__name__, self.cmd, ", ".join(values))

    def __cmp__(self, rhs):
        """Used when sorting the messages in a priority queue"""
        return self.priority - rhs.priority


class ModLoader(object):
    def load_module(self, fullpath, name):
        """Try to load a named module in the given path.

        The imp.find_module() docs give the following boring prescription:

          'This function does not handle hierarchical module names
          (names containing dots). In order to find P.M, that is,
          submodule M of package P, use find_module() and
          load_module() to find and load package P, and then use
          find_module() with the path argument set to P.__path__. When
          P itself has a dotted name, apply this recipe recursively.'
        """

        self.icclog.info("trying to load module path=%s name=%s", fullpath, name)

        parts = fullpath.split(".")
        path = None
        while len(parts) > 1:
            pname = parts[0]
            try:
                self.icclog.debug("pre-loading path=%s pname=%s", path, pname)
                file, filename, description = imp.find_module(pname, path)

                self.icclog.debug(
                    "pre-loading package file=%s filename=%s description=%s",
                    file,
                    filename,
                    description,
                )
                mod = imp.load_module(pname, file, filename, description)
                path = mod.__path__
                parts = parts[1:]
            except ImportError:
                raise
            finally:
                file.close()

        try:
            self.icclog.debug("trying to find path=%s class=%s", path, name)
            file, filename, description = imp.find_module(name, path)

            self.icclog.debug(
                "trying to attach file=%s filename=%s description=%s",
                file,
                filename,
                description,
            )
            mod = imp.load_module(name, file, filename, description)
            return mod
        except ImportError as e:
            raise e
        finally:
            file.close()


class ActorState(object):
    """An object to hold globally useful state for an actor"""

    def __init__(self, actor, models=None):
        self.actor = actor
        # NOTE: getattr is for running unittests;
        # we don't create the Cmdr connection, so can't get its dispatcher.
        self.dispatcher = getattr(self.actor.cmdr, "dispatcher", None)
        if models is None:
            models = {}
        self.models = models
        self.restartCmd = None
        self.aborting = False
        self.ignoreAborting = False
        self.timeout = 10

    def __str__(self):
        msg = "{} {}".format(self.actor, self.actor.cmdr.dispatcher)
        return msg


class Actor(object):
    def __init__(
        self,
        name,
        productName=None,
        productDir=None,
        configFile=None,
        makeCmdrConnection=True,
    ):
        """
        Create an Actor.

        Args:
            name (str): the name we are advertised as to the hub.

        Kwargs:
            productName (str): the name of the product; defaults to name
            configFile (str): the full path of the configuration file; defaults
                to etc/$name.cfg
            makeCmdrConnection (bool): establish self.cmdr as a command connection
                to the hub.
        """
        # Define/save the actor name, the product name, the product_DIR, and the
        # configuration file.
        self.name = name
        self.productName = productName or self.name

        mod = importlib.import_module(self.productName)
        class_path = os.path.dirname(mod.__file__)
        product_dir_name = productDir or class_path
        self.product_dir = product_dir_name

        if not self.product_dir:
            raise RuntimeError(
                "environment variable %s must be defined" % (product_dir_name)
            )

        self.configFile = configFile or os.path.join(
            self.product_dir, f"etc/{self.name}.yaml"
        )

        self.read_config_files()

        self.configureLogs()

        self.logger.info("%s starting up...." % (name))
        self.parser = CommandParser()

        # The list of all connected sources.
        tronInterface = self.config["tron"]["interface"] or ""
        tronPort = self.config["tron"]["port"]
        self.commandSources = cmdLinkManager.listen(
            self, port=tronPort, interface=tronInterface
        )
        # The Command which we send uncommanded output to.
        self.bcast = actorCmd.Command(
            self.commandSources, "self.0", 0, 0, None, immortal=True
        )

        # IDs to send commands to ourself.
        self.selfCID = self.commandSources.fetchCid()
        self.synthMID = 1

        # commandSets are the command handler packages. Each handles
        # a vocabulary, which it registers when loaded.
        # We gather them in one place mainly so that "meta-commands" (init, status)
        # can find the others.
        self.commandSets = {}

        self.logger.info("Creating validation handler...")
        self.handler = validation.CommandHandler()

        self.logger.info("Attaching actor command sets...")
        self.attachAllCmdSets()
        self.logger.info("All command sets attached...")

        self.commandQueue = queue.Queue()
        self.shuttingDown = False

        if makeCmdrConnection:
            self.cmdr = CmdrConnection.Cmdr(name, self)
            self.cmdr.connectionMade = self._connectionMade
            self.cmdr.connect()
        else:
            self.cmdr = None

    def read_config_files(self):
        """Read the config file(s) in etc/"""

        # Missing config bits should make us blow up.
        self.configFile = os.path.expandvars(self.configFile)
        logging.warn("reading config file %s", self.configFile)

        self.config = read_yaml_file(self.configFile)

    def configureLogs(self, cmd=None):
        """(re-)configure our logs."""

        self.logDir = os.path.expandvars(self.config["logging"]["logdir"])
        assert self.logDir, "logdir must be set!"

        # Make the root logger go to a rotating file. All others derive from this.
        setupRootLogger(self.logDir)

        # The real stderr/console filtering is actually done through the
        # console Handler.
        try:
            consoleLevel = int(self.config["logging"]["consoleLevel"])
        except BaseException:
            consoleLevel = int(self.config["logging"]["baseLevel"])
        setConsoleLevel(consoleLevel)

        # self.console needs to be renamed ore deleted, I think.
        self.console = logging.getLogger("")
        self.console.setLevel(int(self.config["logging"]["baseLevel"]))

        self.logger = logging.getLogger("actor")
        self.logger.setLevel(int(self.config["logging"]["baseLevel"]))
        self.logger.propagate = True
        self.logger.info("(re-)configured root and actor logs")

        self.cmdLog = logging.getLogger("cmds")
        self.cmdLog.setLevel(int(self.config["logging"]["cmdLevel"]))
        self.cmdLog.propagate = True
        self.cmdLog.info("(re-)configured cmds log")

        if cmd:
            cmd.inform('text="reconfigured logs"')

    def versionString(self, cmd):
        """Return the version key value.

        If you simply want to generate the keyword, call .sendVersionKey().

        """

        if hasattr(self, "version"):
            version = self.version
        else:
            version = "unknown"

        if version == "unknown" or version == "":
            cmd.warn("text='pathetic version string: %s'" % (version))

        return version

    def sendVersionKey(self, cmd):
        """Generate the version keyword in response to cmd."""

        version = self.versionString(cmd)
        cmd.inform("version=%s" % (qstr(version)))

    def triggerHubConnection(self):
        """Send the hub a command to connect back to us."""

        if not self.cmdr:
            self.bcast.warn(
                'text="CANNOT ask hub to connect to us, '
                'since we do not have a connection to it yet!"'
            )
            return

        self.bcast.warn("%s is asking the hub to connect back to us" % (self.name))
        self.cmdr.dispatcher.executeCmd(
            opscore.actor.keyvar.CmdVar(
                actor="hub", cmdStr="startNubs %s" % (self.name), timeLim=5.0
            )
        )

    def _connectionMade(self):
        """twisted arranges to call this when self.cmdr has been established."""

        self.bcast.warn("%s is connected to the hub." % (self.name))

        #
        # Request that tron connect to us.
        #
        self.triggerHubConnection()
        self.connectionMade()

    def connectionMade(self):
        """For overriding."""
        pass

    def attachCmdSet(self, cname, path=None):
        """(Re-)load and attach a named set of commands."""

        if path is None:
            path = [os.path.join(self.product_dir, "Commands")]

        self.logger.info("attaching command set %s from path %s", cname, path)

        file = None
        try:
            file, filename, description = imp.find_module(cname, path)
            self.logger.debug(
                "command set file=%s filename=%s from path %s", file, filename, path
            )
            mod = imp.load_module(cname, file, filename, description)
        except ImportError as e:
            raise RuntimeError("Import of %s failed: %s" % (cname, e))
        finally:
            if file:
                file.close()

        # Instantiate and save a new command handler.
        cmdSet = getattr(mod, cname)(self)

        # Check any new commands before finishing with the load. This
        # is a bit messy, as the commands might depend on a valid
        # keyword dictionary, which also comes from the module
        # file.
        #
        # BAD problem here: the Keys define a single namespace. We need
        # to check for conflicts and allow unloading. Right now we unilaterally
        # load the Keys and do not unload them if the validation fails.
        if hasattr(cmdSet, "keys") and cmdSet.keys:
            keys.CmdKey.addKeys(cmdSet.keys)
        valCmds = []
        for v in cmdSet.vocab:
            try:
                verb, args, func = v
            except ValueError:
                raise RuntimeError("vocabulary word needs three parts: %s" % (v))

            # Check that the function exists and get its help.
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

        self.logger.debug("handler verbs: %s" % (list(self.handler.consumers.keys())))

    def attachAllCmdSets(self, path=None):
        """(Re-)load all command classes -- files in ./Command which end with Cmd.py."""

        if path is None:
            self.attachAllCmdSets(
                path=os.path.join(os.path.dirname(__file__), "Commands")
            )
            self.attachAllCmdSets(path=os.path.join(self.product_dir, "Commands"))
            return

        dirlist = sorted(os.listdir(path))
        self.logger.info("loading %s" % (dirlist))

        for f in dirlist:
            if os.path.isdir(f) and not f.startswith("."):
                self.attachAllCmdSets(path=f)
            if re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*Cmd\.py$", f):
                self.attachCmdSet(f[:-3], [path])

    def cmdTraceback(self, e):
        eType, eValue, eTraceback = sys.exc_info()
        tbList = traceback.extract_tb(eTraceback)
        where = tbList[-1]

        return "%r at %s:%d" % (eValue, where[0], where[1])

    def runActorCmd(self, cmd):
        try:
            cmdStr = cmd.rawCmd
            self.cmdLog.debug("raw cmd: %s" % (cmdStr))

            try:
                validatedCmd, cmdFuncs = self.handler.match(cmdStr)
            except Exception as e:
                cmd.fail(
                    "text=%s"
                    % (qstr("Unmatched command: %s (exception: %s)" % (cmdStr, e)))
                )
                # tback('actor_loop', e)
                return

            if not validatedCmd:
                cmd.fail("text=%s" % (qstr("Unrecognized command: %s" % (cmdStr))))
                return

            self.cmdLog.info("< %s:%d %s" % (cmd.cmdr, cmd.mid, validatedCmd))
            if len(cmdFuncs) > 1:
                cmd.warn(
                    "text=%s"
                    % (
                        qstr(
                            "command has more than one callback (%s): %s"
                            % (cmdFuncs, validatedCmd)
                        )
                    )
                )
            try:
                cmd.cmd = validatedCmd
                for func in cmdFuncs:
                    func(cmd)
            except Exception as e:
                oneLiner = self.cmdTraceback(e)
                cmd.fail("text=%s" % (qstr("command failed: %s" % (oneLiner))))
                # tback('newCmd', e)
                return

        except Exception as e:
            cmd.fail(
                "text=%s"
                % (
                    qstr(
                        "completely unexpected exception when "
                        "processing a new command: %s" % (e)
                    )
                )
            )
            try:
                tback("newCmdFail", e)
            except BaseException:
                pass

    def actor_loop(self):
        """Check the command queue and dispatch commands."""

        while True:
            try:
                cmd = self.commandQueue.get(block=True, timeout=3)
            except queue.Empty:
                if self.shuttingDown:
                    return
                else:
                    continue
            self.runActorCmd(cmd)

    def commandFailed(self, cmd):
        """Gets called when a command has failed."""
        pass

    def newCmd(self, cmd):
        """Dispatch a newly received command."""

        self.cmdLog.info("new cmd: %s" % (cmd))

        # Empty cmds are OK; send an empty response...
        if len(cmd.rawCmd) == 0:
            cmd.finish("")
            return None

        if self.runInReactorThread:
            self.runActorCmd(cmd)
        else:
            self.commandQueue.put(cmd)

        return self

    def callCommand(self, cmdStr):
        """Send ourselves a command."""

        cmd = actorCmd.Command(
            self.commandSources,
            "self.%d" % (self.selfCID),
            cid=self.selfCID,
            mid=self.synthMID,
            rawCmd=cmdStr,
        )
        self.synthMID += 1
        self.newCmd(cmd)

    def _shutdown(self):
        self.shuttingDown = True

    def run(self, doReactor=True):
        """Actually run the twisted reactor."""
        try:
            self.runInReactorThread = self.config[self.name]["runInReactorThread"]
        except BaseException:
            self.runInReactorThread = False

        self.logger.info(
            "starting reactor (in own thread=%s)...." % (not self.runInReactorThread)
        )
        try:
            if not self.runInReactorThread:
                threading.Thread(target=self.actor_loop).start()
            if doReactor:
                reactor.run()
        except Exception as e:
            tback("run", e)

        if doReactor:
            self.logger.info("reactor dead, cleaning up...")
            self._shutdown()


class SDSSActor(Actor, metaclass=abc.ABCMeta):
    """
    An actor that communicates with the hub, handles commands, knows its own location.

    After subclassing it and replacing newActor(), create and start a new actor via:
        someActor = someActor.newActor()
        someActor.run(someActor.Msg)

    """

    @abc.abstractmethod
    def newActor():
        """Subclasses must implement this as a @staticmethod.

        Return the version of the actor based on our location.
        """
        pass

    @staticmethod
    def determine_location(location=None):
        """Returns location based on the domain name or ``$OBSERVATORY``."""

        location = location or os.environ.get("OBSERVATORY", None)

        if location is None:
            fqdn = socket.getfqdn().split(".")
        else:
            location = location.upper()
            assert location in ["APO", "LCO", "LOCAL"], "invalid location"
            return location

        if "apo" in fqdn:
            return "APO"
        elif "lco" in fqdn:
            return "LCO"
        elif "ACTORCORE_LOCAL" in os.environ and os.environ["ACTORCORE_LOCAL"] == "1":
            return "LOCAL"
        else:
            return None

    def attachAllCmdSets(self, path=None):
        """
        (Re-)load all command classes -- files in ./Command which end with Cmd.py.
        Also loads everything that ends with Cmd_'location'.py
        """

        super(SDSSActor, self).attachAllCmdSets(path)

        if path is not None:
            dirlist = sorted(os.listdir(path))
            self.logger.info("loading %s" % (dirlist))

            for f in dirlist:
                if re.match(
                    r"^[a-zA-Z][a-zA-Z0-9_-]*Cmd_{}\.py$".format(self.location), f
                ):
                    self.attachCmdSet(f[:-3], [path])

    def run(self, Msg=None, startThreads=True, doReactor=True, queueClass=None):
        """
        Start any pre-definted threads and the twisted reactor.

        Kwargs:
            Msg (subclass of actorstate.Msg): if defined, use this to start the
            actor's threads.
            doReactor (bool): call twisted's reactor.run(), and cleanup when finished.
            queueClass (class): The Queue class to use. If None, uses Queue.Queue.
                This is mostly intended for sopActor, which uses its own subclass
                of Queue.

        """

        if not queueClass:
            queueClass = queue.Queue

        if Msg is not None:
            self.startThreads(
                Msg, restartQueues=True, restart=False, queueClass=queueClass
            )

        try:
            self.runInReactorThread = self.config[self.name]["runInReactorThread"]
        except BaseException:
            self.runInReactorThread = False

        self.logger.info(
            "starting reactor (in own thread=%s)...." % (not self.runInReactorThread)
        )
        try:
            if not self.runInReactorThread:
                threading.Thread(target=self.actor_loop).start()
            if doReactor:
                reactor.run()
        except Exception as e:
            tback("run", e)

        if doReactor:
            self.logger.info("reactor dead, cleaning up...")
            self._shutdown()

    def startThreads(
        self, Msg, cmd=None, restart=False, restartQueues=False, queueClass=None
    ):
        """
        Start or restart the worker threads (from self.threadList) and queues.

        Args:
            actorState (ActorState): container for the current state of the
                class, to pass messages between threads, etc.
            Msg: static class defining messages that can be sent to this actor's queues.

        Kwargs:
            cmd (actorstate.Command): to send messages on.
            restart (bool): restart all running threads and clear all queues.
                Implies restartQueues=True.
            restartQueues (bool): Create new empty queues for each thread.
            queueClass (class): The Queue class to use. If None, uses Queue.Queue.
                This is mostly intended for sopActor, which uses its own subclass
                of Queue.
        """
        actorState = self.actorState

        if getattr(actorState, "threads", None) is None:
            restart = False  # nothing to restart!

        if not restart:
            actorState.queues = {}
            actorState.threads = {}

            restartQueues = True

        def updateName(g):
            """re.sub callback to convert master -> master-1; master-3 -> master-4"""
            try:
                n = int(g.group(2))
            except TypeError:
                n = 0
            return "%s-%d" % (g.group(1), n + 1)

        newQueues = {}
        threadsToStart = []
        for tname, tid, thread in self.threadList:

            if queueClass is None or queueClass is queue.Queue:
                newQueues[tid] = (
                    queue.Queue(0) if restartQueues else actorState.queues[tid]
                )
            else:
                # If queueClass is custom, we assume it comes from SOP,
                # whose queue require to pass the tname as the first argument.
                # TODO: this is ugly and has already caused problems. We should find
                # a better solution.
                newQueues[tid] = (
                    queueClass(tname, 0) if restartQueues else actorState.queues[tid]
                )

            if inspect.ismodule(thread):
                threadTarget = thread.main
                threadModule = thread
            else:
                threadTarget = thread
                threadModule = sys.modules[thread.__module__]

            if restart:
                importlib.reload(threadModule)

                for t in threading.enumerate():
                    if re.search(
                        r"^%s(-\d+)?$" % tname, t.name
                    ):  # a thread of the proper type
                        actorState.queues[tid].flush()
                        actorState.queues[tid].put(Msg(Msg.EXIT, cmd=cmd))

                        t.join(1.0)
                        if t.isAlive():
                            if cmd:
                                cmd.inform('text="Failed to kill %s"' % tname)

                tname = re.sub(
                    r"^([^\d]*)(?:-(\d*))?$", updateName, actorState.threads[tid].name
                )

            actorState.threads[tid] = threading.Thread(
                target=threadTarget, name=tname, args=[actorState.actor, newQueues]
            )
            actorState.threads[tid].daemon = True

            threadsToStart.append(actorState.threads[tid])

        # Switch to the new queues now that we've sent EXIT to the old ones
        for tid, q in list(newQueues.items()):
            actorState.queues[tid] = q

        for t in threadsToStart:
            t.start()
