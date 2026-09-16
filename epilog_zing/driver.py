"""Network job submission for the Epilog Zing 24 / 6030."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from gettext import gettext as _
from typing import TYPE_CHECKING, Any

from rayforge.context import RayforgeContext
from rayforge.core.varset import (
    ChoiceVar,
    HostnameVar,
    IntVar,
    PortVar,
    VarSet,
)
from rayforge.core.varset.hostnamevar import hostname_validator
from rayforge.machine.driver.driver import (
    DeviceStatus,
    Driver,
    DriverMaturity,
    DriverPrecheckError,
    DriverSetupError,
    Pos,
)
from rayforge.machine.transport import TransportStatus
from rayforge.pipeline.encoder.base import EncodedOutput, OpsEncoder
from raygeo.ops.axis import Axis

from .encoder import (
    DEFAULT_FREQUENCY,
    DEFAULT_RESOLUTION,
    RESOLUTIONS,
    EpilogZingEncoder,
    ZingSettings,
    decode_job,
)
from .lpd import EpilogLpdClient

if TYPE_CHECKING:
    from rayforge.core.doc import Doc
    from rayforge.machine.models.dialect import GcodeDialect
    from rayforge.machine.models.laser import Laser
    from rayforge.machine.models.machine import Machine
    from raygeo.ops import Ops


logger = logging.getLogger(__name__)


class EpilogZingDriver(Driver):
    label = _("Epilog Zing")
    subtitle = _("Upload jobs via Ethernet; start at the laser")
    uses_gcode = False
    maturity = DriverMaturity.UNTESTED
    supports_multi_depth_raster = False

    def __init__(self, context: RayforgeContext, machine: "Machine"):
        super().__init__(context, machine)
        self._client: EpilogLpdClient | None = None
        self._upload_task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def machine_space_wcs(self) -> str:
        return "MACHINE"

    @property
    def machine_space_wcs_display_name(self) -> str:
        return _("Epilog Bed Coordinates")

    @property
    def supported_wcs(self) -> list[str]:
        return ["MACHINE"]

    @property
    def resource_uri(self) -> str | None:
        if self._client:
            return f"tcp://{self._client.host.lower()}:{self._client.port}"
        return None

    @classmethod
    def supports_travel_speed(cls, dialect: "GcodeDialect | None") -> bool:
        return False

    @classmethod
    def get_setup_vars(cls) -> VarSet:
        return VarSet(
            title=_("Epilog Zing"),
            description=_(
                "Jobs are stored on the laser. Start, pause, and stop them "
                "using its control panel. Focus and air assist are manual. "
                "Speed is converted to a percentage of Maximum Cut Speed."
            ),
            vars=[
                HostnameVar(key="host", label=_("Hostname / IP")),
                PortVar(key="port", label=_("Port"), default=515),
                ChoiceVar(
                    key="resolution",
                    label=_("Resolution (DPI)"),
                    choices=[str(dpi) for dpi in RESOLUTIONS],
                    default=str(DEFAULT_RESOLUTION),
                    allow_none=False,
                ),
                IntVar(
                    key="frequency",
                    label=_("Vector Frequency"),
                    description=_("Epilog vector frequency setting (10–5000)"),
                    default=DEFAULT_FREQUENCY,
                    min_val=10,
                    max_val=5000,
                ),
            ],
        )

    @classmethod
    def precheck(cls, **kwargs: Any) -> None:
        try:
            hostname_validator(kwargs.get("host"))
            port = kwargs.get("port", 515)
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError(_("Port must be between 1 and 65535"))
            ZingSettings(
                int(kwargs.get("resolution", DEFAULT_RESOLUTION)),
                int(kwargs.get("frequency", DEFAULT_FREQUENCY)),
            )
        except (ValueError, TypeError) as exc:
            raise DriverPrecheckError(str(exc)) from exc

    def _setup_implementation(self, **kwargs: Any) -> None:
        try:
            self.precheck(**kwargs)
        except DriverPrecheckError as exc:
            raise DriverSetupError(str(exc)) from exc
        self._client = EpilogLpdClient(kwargs["host"], kwargs.get("port", 515))
        self._stopping.clear()

    @classmethod
    def create_encoder(cls, machine: "Machine") -> OpsEncoder:
        return EpilogZingEncoder()

    def get_setting_vars(self) -> list[VarSet]:
        return []

    def _connection(self, status: TransportStatus, message: str) -> None:
        logger.info(message, extra=self._log_extra("CONNECTION"))
        self.connection_status_changed.send(
            self, status=status, message=message
        )

    async def _connect_implementation(self) -> None:
        if self._client is None:
            self._connection(
                TransportStatus.ERROR,
                _("Configure the Epilog hostname first"),
            )
            return
        while not self._stopping.is_set():
            self._connection(TransportStatus.CONNECTING, _("Checking Epilog"))
            try:
                await self._client.probe()
            except (OSError, TimeoutError) as exc:
                self._connection(TransportStatus.ERROR, str(exc))
                try:
                    await asyncio.wait_for(self._stopping.wait(), 5)
                except TimeoutError:
                    continue
            else:
                self._connection(
                    TransportStatus.CONNECTED,
                    _("Epilog reachable; machine status is unavailable"),
                )
                return

    async def cleanup(self) -> None:
        self._stopping.set()
        await self._cancel_upload()
        self._client = None
        self._connection(TransportStatus.DISCONNECTED, _("Disconnected"))
        await super().cleanup()

    async def run(
        self,
        encoded: EncodedOutput,
        doc: "Doc",
        ops: "Ops",
        on_command_done: Callable[[int], None | Awaitable[None]] | None = None,
    ) -> None:
        if self._client is None:
            raise DriverSetupError(_("Configure the Epilog hostname first"))
        if self._upload_task is not None:
            raise RuntimeError(_("An Epilog upload is already in progress"))
        payload = decode_job(encoded.text)
        self._upload_task = asyncio.create_task(
            self._client.upload(payload, doc.name or "Rayforge")
        )
        self.state.status = DeviceStatus.QUEUE
        self.state_changed.send(self, state=self.state)
        try:
            await self._upload_task
        except (OSError, TimeoutError) as exc:
            self._connection(TransportStatus.ERROR, str(exc))
            logger.error(
                "Epilog upload failed. Check the laser's job list before "
                "retrying; the device may have received the job.",
                extra=self._log_extra("DRIVER_CMD"),
            )
            raise
        else:
            self._connection(
                TransportStatus.CONNECTED,
                _(
                    "Upload complete. Select the job and press Go "
                    "at the laser."
                ),
            )
            self.job_finished.send(self)
        finally:
            self._upload_task = None
            self.state.status = DeviceStatus.UNKNOWN
            self.state_changed.send(self, state=self.state)

    async def _cancel_upload(self) -> bool:
        task = self._upload_task
        if task is None or task.done():
            return False
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.warning(
            "Epilog upload interrupted. Inspect the job list at the laser; "
            "this does not stop a running laser job.",
            extra=self._log_extra("DRIVER_CMD"),
        )
        return True

    async def cancel(self, emergency: bool = False) -> None:
        if not await self._cancel_upload():
            self._panel_only()

    @staticmethod
    def _panel_only() -> None:
        raise NotImplementedError(
            _("Use the Epilog control panel for this operation")
        )

    def can_home(self, axis: Axis | None = None) -> bool:
        return False

    def can_jog(self, axis: Axis | None = None) -> bool:
        return False

    def can_receive_job(self) -> bool:
        return (
            self._client is not None
            and self._upload_task is None
            and self.state.status in (DeviceStatus.UNKNOWN, DeviceStatus.IDLE)
            and not self.state.error
        )

    async def run_raw(self, machine_code: str) -> None:
        self._panel_only()

    async def set_hold(self, hold: bool = True) -> None:
        self._panel_only()

    async def home(self, axes: Axis | None = None) -> None:
        self._panel_only()

    async def move_to(self, pos_x: float, pos_y: float) -> None:
        self._panel_only()

    async def select_tool(self, tool_number: int) -> None:
        if tool_number != self._machine.get_default_head().tool_number:
            self._panel_only()

    async def read_settings(self) -> None:
        self._panel_only()

    async def write_setting(self, key: str, value: Any) -> None:
        self._panel_only()

    async def clear_alarm(self) -> None:
        self._panel_only()

    async def set_power(self, head: "Laser", percent: float) -> None:
        self._panel_only()

    async def set_focus_power(self, head: "Laser", percent: float) -> None:
        self._panel_only()

    async def jog(self, speed: int, **deltas: float) -> None:
        self._panel_only()

    async def set_wcs_offset(
        self, wcs_slot: str, x: float, y: float, z: float | None
    ) -> None:
        self._panel_only()

    async def read_wcs_offsets(self) -> dict[str, Pos]:
        return {"MACHINE": (0.0, 0.0, 0.0)}

    async def read_parser_state(self) -> str | None:
        return "MACHINE"

    async def select_wcs(self, wcs: str) -> None:
        if wcs != "MACHINE":
            self._panel_only()

    async def run_probe_cycle(
        self, axis: Axis, max_travel: float, feed_rate: int
    ) -> Pos | None:
        self._panel_only()
        return None
