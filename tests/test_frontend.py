from unittest.mock import Mock

import pytest
from gi.repository import GLib
from rayforge.machine.transport import TransportStatus
from rayforge.ui_gtk.action_registry import ActionRegistry

from epilog_zing import EpilogZingDriver, frontend


@pytest.mark.parametrize(
    "blocked",
    [None, "disconnected", "busy", "running", "stale", "empty", "error"],
)
def test_upload_action_rechecks_readiness(
    lite_context, zing_machine, monkeypatch, blocked
):
    driver = EpilogZingDriver(lite_context, zing_machine)
    driver.setup(host="127.0.0.1")
    machine = Mock(driver=driver)
    machine.connection_status = TransportStatus.CONNECTED
    context = Mock()
    context.config.machine = machine
    monkeypatch.setattr(frontend, "get_context", lambda: context)
    tasks = Mock()
    tasks.has_tasks.return_value = blocked == "busy"
    monkeypatch.setattr(frontend, "task_mgr", tasks)
    timer = Mock()
    monkeypatch.setattr(GLib, "timeout_add", timer)
    window = Mock()
    window.doc_editor.doc.has_result.return_value = blocked != "empty"
    window.doc_editor.pipeline.is_data_stale = blocked == "stale"
    window.machine_cmd.is_job_running = blocked == "running"
    if blocked == "disconnected":
        machine.connection_status = TransportStatus.DISCONNECTED
    if blocked == "error":
        driver.state.error = "test error"
    registry = ActionRegistry()
    registry.set_window(window)
    frontend.register_actions(registry)
    info = registry.get(frontend.ACTION_NAME)
    assert info is not None
    refresh = timer.call_args.args[1]
    assert refresh() == GLib.SOURCE_CONTINUE
    assert info.action.get_enabled() == (blocked is None)
    info.action.activate(None)
    assert window.on_send_clicked.call_count == int(blocked is None)
    context.config.machine = None
    info.action.activate(None)
    assert window.on_send_clicked.call_count == int(blocked is None)
    registry.unregister_all_from_addon("epilog_zing")
    assert refresh() == GLib.SOURCE_REMOVE
