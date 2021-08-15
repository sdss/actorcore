"""
Instrument Control Computer

An ICC is a specialized actor with a controller that interfaces with a given
instrument.
"""

import imp
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
        file = None
        try:
            file, filename, description = imp.find_module(name, path)
            self.logger.debug(
                "controller file=%s filename=%s from path %s", file, filename, path
            )
            mod = imp.load_module(name, file, filename, description)
            self.logger.debug(
                "load_module(%s, %s, %s, %s) = %08x",
                name,
                file,
                filename,
                description,
                id(mod),
            )
        except ImportError as e:
            raise RuntimeError("Import of %s failed: %s" % (name, e))
        finally:
            if file:
                file.close()

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
