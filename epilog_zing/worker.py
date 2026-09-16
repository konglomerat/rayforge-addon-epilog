"""Register the driver in both the application and encoding workers."""

from pathlib import Path

from rayforge.core.hooks import hookimpl
from rayforge.machine.driver import (
    driver_by_classname,
    drivers,
    register_driver,
)

from .driver import EpilogZingDriver

DEVICES_DIR = Path(__file__).resolve().parent.parent / "devices"


def register_epilog_driver():
    """Replace an earlier instance without duplicating the driver list."""
    name = EpilogZingDriver.__name__
    drivers[:] = [driver for driver in drivers if driver.__name__ != name]
    driver_by_classname.pop(name, None)
    register_driver(EpilogZingDriver)


register_epilog_driver()


@hookimpl
def rayforge_init(context):
    """Make the bundled device profile available when Rayforge starts."""
    manager = context.device_profile_mgr
    manager.add_source_dir(DEVICES_DIR)
    manager.load_profile(DEVICES_DIR / "epilog-zing-24")
