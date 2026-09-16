import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from rayforge.machine.driver.driver import (
    DeviceStatus,
    DriverPrecheckError,
)
from rayforge.machine.transport import TransportStatus

from epilog_zing import EpilogZingDriver
from epilog_zing.encoder import decode_job


@pytest.fixture
def driver(lite_context, zing_machine, monkeypatch):
    client = Mock()
    client.host = "127.0.0.1"
    client.port = 515
    client.probe = AsyncMock()
    client.upload = AsyncMock()
    monkeypatch.setattr(
        "epilog_zing.driver.EpilogLpdClient",
        Mock(return_value=client),
    )
    driver = EpilogZingDriver(lite_context, zing_machine)
    driver.setup(host="127.0.0.1")
    driver.job_finished.send = Mock()
    driver.connection_status_changed.send = Mock()
    return driver


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"host": "bad\nhost"},
        {"host": "127.0.0.1", "port": 0},
        {"host": "127.0.0.1", "port": True},
        {"host": "127.0.0.1", "resolution": "300"},
        {"host": "127.0.0.1", "frequency": 5001},
    ],
)
def test_precheck(kwargs):
    with pytest.raises(DriverPrecheckError):
        EpilogZingDriver.precheck(**kwargs)


def test_precheck_valid_and_capabilities(driver):
    EpilogZingDriver.precheck(host="laser.local", resolution="500", port=515)
    assert driver.resource_uri == "tcp://127.0.0.1:515"
    assert not driver.uses_gcode
    assert not driver.reports_granular_progress
    assert not driver.can_home()
    assert not driver.can_jog()
    assert not driver.supports_travel_speed(None)
    assert driver.supported_wcs == ["MACHINE"]


@pytest.mark.asyncio
async def test_connection_does_not_claim_machine_is_idle(driver):
    await driver.connect()
    driver._client.probe.assert_awaited_once()
    assert driver.state.status == DeviceStatus.UNKNOWN
    assert driver.can_receive_job()
    assert (
        driver.connection_status_changed.send.call_args.kwargs["status"]
        == TransportStatus.CONNECTED
    )


@pytest.mark.asyncio
async def test_upload_uses_persisted_text_without_execution_callbacks(
    driver, zing_machine, zing_doc, zing_ops
):
    encoded = driver.get_encoder().encode(zing_ops, zing_machine, zing_doc)
    callback = Mock()
    await driver.run(encoded, zing_doc, zing_ops, callback)
    driver._client.upload.assert_awaited_once_with(
        decode_job(encoded.text), zing_doc.name
    )
    callback.assert_not_called()
    driver.job_finished.send.assert_called_once_with(driver)
    assert driver.state.status == DeviceStatus.UNKNOWN


@pytest.mark.asyncio
async def test_failed_upload_is_not_retried_or_marked_finished(
    driver, zing_machine, zing_doc, zing_ops
):
    driver._client.upload.side_effect = ConnectionError("lost acknowledgement")
    encoded = driver.get_encoder().encode(zing_ops, zing_machine, zing_doc)
    with pytest.raises(ConnectionError):
        await driver.run(encoded, zing_doc, zing_ops)
    driver._client.upload.assert_awaited_once()
    driver.job_finished.send.assert_not_called()
    assert driver._upload_task is None


@pytest.mark.asyncio
async def test_cancel_and_concurrent_upload_guard(
    driver, zing_machine, zing_doc, zing_ops
):
    started = asyncio.Event()

    async def pending(*args):
        started.set()
        await asyncio.Event().wait()

    driver._client.upload.side_effect = pending
    encoded = driver.get_encoder().encode(zing_ops, zing_machine, zing_doc)
    task = asyncio.create_task(driver.run(encoded, zing_doc, zing_ops))
    await asyncio.wait_for(started.wait(), 2)
    assert not driver.can_receive_job()
    with pytest.raises(RuntimeError, match="already in progress"):
        await driver.run(encoded, zing_doc, zing_ops)
    await driver.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    driver.job_finished.send.assert_not_called()
    assert driver.state.status == DeviceStatus.UNKNOWN
    assert driver.can_receive_job()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, args",
    [
        ("cancel", ()),
        ("set_hold", (True,)),
        ("home", ()),
        ("jog", (600,)),
        ("move_to", (1, 1)),
        ("run_raw", ("G1 X10",)),
        ("set_power", (None, 0.5)),
        ("set_focus_power", (None, 0.5)),
    ],
)
async def test_panel_only_controls_fail_explicitly(driver, method, args):
    with pytest.raises(NotImplementedError, match="control panel"):
        await getattr(driver, method)(*args)
    driver._client.upload.assert_not_called()
