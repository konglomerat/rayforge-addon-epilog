from pathlib import Path
from unittest.mock import Mock

import pluggy
import pytest
from rayforge.addon_mgr.addon import Addon
from rayforge.addon_mgr.addon_manager import AddonManager
from rayforge.core.hooks import RayforgeSpecs
from rayforge.machine.driver import drivers, get_driver_cls
from rayforge.shared.util.versioning import UnknownVersion

from epilog_zing.worker import register_epilog_driver

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("worker_only", [True, False])
def test_native_addon_loading(tmp_path, worker_only):
    plugin_manager = pluggy.PluginManager("rayforge")
    plugin_manager.add_hookspecs(RayforgeSpecs)
    manager = AddonManager(
        [ROOT], tmp_path / "installed", plugin_manager, Mock()
    )
    try:
        addon = Addon.load_from_directory(ROOT, version=UnknownVersion)
        assert addon.validate()
        manager.load_addon(ROOT, worker_only=worker_only)
        assert "epilog_zing" in manager.loaded_addons
        assert not manager._load_errors
        driver = get_driver_cls("EpilogZingDriver")
        assert driver.__module__.startswith("rayforge_addons.epilog_zing.")
        assert sum(d.__name__ == driver.__name__ for d in drivers) == 1
        context = Mock()
        plugin_manager.hook.rayforge_init(context=context)
        context.device_profile_mgr.load_profile.assert_called_once_with(
            ROOT / "devices/epilog-zing-24"
        )
    finally:
        register_epilog_driver()
