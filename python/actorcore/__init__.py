import configparser
import os


try:
    import pkg_resources
except (ImportError, ModuleNotFoundError):
    pkg_resources = None


def get_version():

    if pkg_resources:
        try:
            return pkg_resources.get_distribution("sdss-actorcore").version
        except pkg_resources.DistributionNotFound:
            pass

    setup_cfg = os.path.join(os.path.dirname(__file__), "../../setup.cfg")
    if os.path.exists(setup_cfg):
        config = configparser.ConfigParser()
        config.read(setup_cfg)
        return config.get("metadata", "version")

    return "dev"


__version__ = get_version()

NAME = "sdss-actorcore"
