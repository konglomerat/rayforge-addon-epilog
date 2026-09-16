"""Upload action for Rayforge versions requiring IDLE to enable Send."""

from gi.repository import Gio, GLib
from rayforge.context import get_context
from rayforge.core.hooks import hookimpl
from rayforge.machine.transport import TransportStatus
from rayforge.shared.tasker import task_mgr
from rayforge.ui_gtk.action_registry import MenuPlacement, ToolbarPlacement

from .driver import EpilogZingDriver

ACTION_NAME = "epilog-upload"


def can_upload(window):
    machine = get_context().config.machine
    return bool(
        machine
        and isinstance(machine.driver, EpilogZingDriver)
        and machine.driver.can_receive_job()
        and machine.connection_status == TransportStatus.CONNECTED
        and window.doc_editor.doc.has_result()
        and not window.doc_editor.pipeline.is_data_stale
        and not task_mgr.has_tasks()
        and not window.machine_cmd.is_job_running
    )


@hookimpl
def register_actions(action_registry):
    window = action_registry.window
    if window is None:
        return
    action = Gio.SimpleAction.new(ACTION_NAME, None)
    action.set_enabled(False)

    def activate(action, parameter):
        if can_upload(window):
            window.on_send_clicked(action, parameter)

    def refresh():
        info = action_registry.get(ACTION_NAME)
        if info is None or info.action is not action:
            return GLib.SOURCE_REMOVE
        action.set_enabled(can_upload(window))
        return GLib.SOURCE_CONTINUE

    action.connect("activate", activate)
    action_registry.register(
        ACTION_NAME,
        action,
        addon_name="epilog_zing",
        label="Upload to Epilog",
        icon_name="document-send-symbolic",
        menu=MenuPlacement(menu_id="tools"),
        toolbar=ToolbarPlacement(group="main"),
    )
    GLib.timeout_add(250, refresh)
