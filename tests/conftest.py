import asyncio

import pytest
import pytest_asyncio
from rayforge.core.doc import Doc
from rayforge.machine.device.profile import DeviceProfile
from raygeo.ops import Ops

from epilog_zing.worker import DEVICES_DIR


@pytest_asyncio.fixture
async def zing_machine(lite_context, task_mgr):
    profile = DeviceProfile.from_path(DEVICES_DIR / "epilog-zing-24")
    machine = profile.create_machine(lite_context)
    machine.auto_connect = False
    yield machine
    await machine.shutdown()
    assert await asyncio.to_thread(task_mgr.wait_until_settled, 5000)


@pytest.fixture
def zing_doc():
    doc = Doc()
    doc.name = "Epilog test"
    return doc


@pytest.fixture
def zing_ops():
    ops = Ops()
    ops.set_power(0.25)
    ops.set_feed_rate(600)
    ops.move_to(25.4, 25.4, 0)
    ops.line_to(50.8, 25.4, 0)
    ops.line_to(50.8, 50.8, 0)
    ops.line_to(25.4, 50.8, 0)
    ops.line_to(25.4, 25.4, 0)
    return ops
