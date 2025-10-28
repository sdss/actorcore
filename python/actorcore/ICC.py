"""
Instrument Control Computer

An ICC is a specialized actor with a controller that interfaces with a given
instrument.
"""

import importlib.util
import logging
import os
import sys

from opscore.utility.qstr import qstr
from opscore.utility.sdss3logging import makeOpsFileLogger

import actorcore.Actor


class ICC(actorcore.Actor.Actor):
    def __init__(
        self,
        name,
        productName=None,
        configFile=None,
        productDir=None,
        makeCmdrConnection=True,
    ):
        """
        Create an ICC to communicate with an instrument.

        Args:
            name (str): the name we are advertised as to the hub.

        Kwargs:
            productName (str): the name of the product; defaults to name
            configFile (str): the full path of the configuration file; defaults
                to $PRODUCTNAME_DIR/etc/$name.cfg
            makeCmdrConnection (bool): establish self.cmdr as a command connection
                to the hub.

        """

        actorcore.Actor.Actor.__init__(
            self,
            name,
            configFile=configFile,
            productName=productName,
            productDir=productDir,
            makeCmdrConnection=makeCmdrConnection,
        )

        # Create a separate logger for controller io
        makeOpsFileLogger(os.path.join(self.logDir, "io"), "io")
        self.iolog = logging.getLogger("io")
        self.iolog.setLevel(int(self.config["logging"]["ioLevel"]))
        self.iolog.propagate = False

    def attachController(self, name, path=None, cmd=None):
        """(Re-)load and attach a named set of commands."""

        if path is None:
            path = [os.path.join(self.product_dir, "Controllers")]

        # import pdb; pdb.set_trace()
        self.logger.info("attaching controller %s from path %s", name, path)
        try:
            # Search for the module in the given path
            spec = None
            for p in path:
                module_file = os.path.join(p, name + ".py")
                if os.path.exists(module_file):
                    spec = importlib.util.spec_from_file_location(name, module_file)
                    break

            if spec is None:
                raise ImportError(f"No module named '{name}' in path {path}")

            self.logger.debug(
                "controller spec.name=%s spec.origin=%s from path %s",
                spec.name,
                spec.origin,
                path,
            )

            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)

            self.logger.debug(
                "load_module(%s) = %08x",
                name,
                id(mod),
            )
        except ImportError as e:
            raise RuntimeError("Import of %s failed: %s" % (name, e))

        # Instantiate and save a new controller.
        self.logger.info("creating new %s (%08x)", name, id(mod))
        conn = getattr(mod, name)(self, name)

        # If we loaded the module and the controller is already running,
        #   cleanly stop the old one.
        if name in self.controllers:
            self.logger.info("stopping %s controller", name)
            self.controllers[name].stop()
            del self.controllers[name]

        self.logger.info("starting %s controller", name)
        try:
            conn.start()
        except Exception:
            print(sys.exc_info())
            self.logger.error("Could not connect to %s", name)
            return False
        self.controllers[name] = conn
        return True

    def attachAllControllers(self, path=None):
        """(Re-)load and (re-)connect to the hardware controllers listed in
        config:"icc".controllers.
        """

        clist = self.config[self.name]["controllers"]
        self.logger.info("All controllers = %s", clist)
        for c in clist:
            if c not in self.allControllers:
                self.bcast.warn(
                    "text=%s" % (qstr("cannot attach unknown controller %s" % (c)))
                )
                continue
            if not self.attachController(c, path):
                self.bcast.warn('text="Could not connect to controller %s."' % (c))

    def stopAllControllers(self):
        for c in list(self.controllers.keys()):
            controller = self.controllers[c]
            controller.stop()

    def shutdown(self):
        actorcore.Actor.shutdown(self)

        self.stopAllControllers()


class SDSS_ICC(ICC, actorcore.Actor.SDSSActor):
    """
    An ICC that communicates with the hub, handles commands, knows its own location.

    After subclassing it and replacing newActor(), create and start a new actor via:
        someActor = someActor.newActor()
        someActor.run(someActor.Msg)
    """

    pass
