"""Encode machine-space paths as Epilog Zing PJL/PCL/HPGL jobs.

The text representation contains escaped ASCII chunks, one per line. This
keeps control characters out of the editor and survives the pipeline's
text-only artifact storage. ``decode_job`` produces a printable PRN file.
"""

import codecs
import logging
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rayforge.pipeline.encoder.base import (
    EncodedOutput,
    MachineCodeOpMap,
    OpsEncoder,
)
from raygeo.ops import Ops
from raygeo.ops.state import AirAssistMode, CoolantMode
from raygeo.ops.types import CommandType

if TYPE_CHECKING:
    from rayforge.core.doc import Doc
    from rayforge.machine.models.machine import Machine


RESOLUTIONS = (100, 200, 250, 400, 500, 1000)
DEFAULT_RESOLUTION = 500
DEFAULT_FREQUENCY = 1000
FOOTER = b"\x1bE\x1b%-12345X@PJL EOJ \r\n"
logger = logging.getLogger(__name__)


def job_name(value: str) -> str:
    """Return a bounded ASCII label without printer-language controls."""
    return re.sub(r"[^A-Za-z0-9 ._-]", "_", value)[:64].strip() or "Rayforge"


def decode_job(text: str) -> bytes:
    """Restore an encoder transcript, including Epilog's trailing padding."""
    if not text:
        raise ValueError("The Epilog job is empty")
    payload = b"".join(
        codecs.escape_decode(line.encode("ascii"))[0]
        for line in text.splitlines()
    )
    if not payload.startswith(b"\x1b%-12345X@PJL JOB NAME="):
        raise ValueError("Not an Epilog Zing job")
    if not payload.endswith(FOOTER):
        raise ValueError("Incomplete Epilog Zing job")
    return payload + bytes(4096)


@dataclass(frozen=True)
class ZingSettings:
    resolution: int = DEFAULT_RESOLUTION
    frequency: int = DEFAULT_FREQUENCY

    def __post_init__(self) -> None:
        if self.resolution not in RESOLUTIONS:
            raise ValueError("Unsupported Epilog Zing resolution")
        if not 10 <= self.frequency <= 5000:
            raise ValueError("Epilog frequency must be between 10 and 5000")


class EpilogZingEncoder(OpsEncoder):
    """Encode vectors and linearized engraving paths without reordering.

    Epilog uses integer speed percentages. ``machine.max_cut_speed`` is the
    reference for 100%, not a measured hardware speed. Native raster commands
    are not used: scan lines become vector segments with per-segment power.
    """

    def encode(
        self, ops: Ops, machine: "Machine", doc: "Doc"
    ) -> EncodedOutput:
        settings = ZingSettings(
            resolution=int(
                machine.driver_args.get("resolution", DEFAULT_RESOLUTION)
            ),
            frequency=int(
                machine.driver_args.get("frequency", DEFAULT_FREQUENCY)
            ),
        )
        if not ops.len():
            return EncodedOutput("", MachineCodeOpMap())
        if any(layer.rotary_enabled for layer in doc.layers):
            raise ValueError("Epilog Zing supports flat XY jobs only")
        session = _EncodingSession(machine, settings)
        return session.encode(ops, job_name(doc.name or "Rayforge"))


class _EncodingSession:
    """State scoped to one encode, so cached encoders can be reused."""

    def __init__(self, machine: "Machine", settings: ZingSettings):
        self.machine = machine
        self.settings = settings
        self.position = (0.0, 0.0, 0.0)
        self.power = 0
        self.speed: int | None = None
        self.chunks: list[bytes] = []
        self.owners: list[int] = []
        self.owner = -1
        self.has_cut = False
        self.has_position = False
        self.air_assist_requested = False

    def emit(self, value: str | bytes) -> None:
        self.chunks.append(
            value.encode("ascii") if isinstance(value, str) else value
        )
        self.owners.append(self.owner)

    def encode(self, ops: Ops, title: str) -> EncodedOutput:
        self._validate_machine()
        self._header(title)
        spans = []
        for index in range(ops.len()):
            start = len(self.chunks)
            self.owner = index
            self.command(ops, index)
            spans.append((start, len(self.chunks) - start))
        self.owner = -1
        if not self.has_cut:
            raise ValueError("The Epilog job has no powered cutting paths")
        self.emit("PU;YP000;WF0;")
        self.emit(FOOTER)
        if self.air_assist_requested:
            logger.warning(
                "Epilog Zing air assist must be enabled at the machine; "
                "the print protocol cannot switch it."
            )
        text = "\n".join(
            codecs.escape_encode(chunk)[0].decode("ascii")
            for chunk in self.chunks
        )
        return EncodedOutput(
            text, MachineCodeOpMap.from_lists(spans, self.owners)
        )

    def _validate_machine(self) -> None:
        if self.machine.origin.value != "top_left":
            raise ValueError("Epilog Zing requires a top-left machine origin")
        if any(
            not math.isfinite(v) or v <= 0 for v in self.machine.axis_extents
        ):
            raise ValueError("Epilog bed dimensions must be positive")
        if (
            not math.isfinite(self.machine.max_cut_speed)
            or self.machine.max_cut_speed <= 0
        ):
            raise ValueError("Epilog maximum cut speed must be positive")
        if self.machine.has_z_axis:
            raise ValueError("Epilog Zing supports flat XY jobs only")

    def _header(self, title: str) -> None:
        dpi = self.settings.resolution
        width, height = self.machine.axis_extents
        self.emit(f"\x1b%-12345X@PJL JOB NAME={title}\r\n")
        self.emit("\x1bE@PJL ENTER LANGUAGE=PCL\r\n")
        self.emit("\x1b&y0A\x1b&y0C\x1b&y0Z\x1b&l0U\x1b&l0Z")
        self.emit(f"\x1b&u{dpi}D\x1b*p0X\x1b*p0Y")
        self.emit(
            f"\x1b*t{dpi}R\x1b*r0F\x1b&y0P\x1b&z1S\x1b&y0A"
            f"\x1b*r{int(height * dpi / 25.4)}T"
            f"\x1b*r{int(width * dpi / 25.4)}S"
            "\x1b*b2M\x1b&y0O\x1b*r1A\x1b*rC"
        )
        self.emit(f"\x1b%1BIN;WF0;XR{self.settings.frequency:04d};YP000;")

    def command(self, ops: Ops, index: int) -> None:
        kind = ops.command_type(index)
        if kind == CommandType.SET_POWER:
            self._set_power(ops.power(index))
        elif kind == CommandType.SET_FEED_RATE:
            self._set_speed(ops.rate(index))
        elif kind == CommandType.SET_FREQUENCY:
            frequency = ops.frequency(index)
            if not 10 <= frequency <= 5000:
                raise ValueError(
                    "Epilog frequency must be between 10 and 5000"
                )
            self.emit(f"XR{frequency:04d};")
        elif kind in (CommandType.MOVE_TO, CommandType.LINE_TO):
            self._move(ops.endpoint(index), kind == CommandType.LINE_TO)
        elif kind in (
            CommandType.ARC_TO,
            CommandType.BEZIER_TO,
            CommandType.QUADRATIC_BEZIER_TO,
            CommandType.SCAN_LINE,
        ):
            self._linearize(ops, index)
        elif kind == CommandType.SET_HEAD:
            if ops.head_uid(index) != self.machine.get_default_head().uid:
                raise ValueError("Epilog Zing has only one laser head")
        elif kind == CommandType.SET_AIR_ASSIST:
            self.air_assist_requested |= (
                ops.air_assist(index) == AirAssistMode.ON
            )
        elif kind == CommandType.SET_COOLANT:
            if ops.coolant(index) != CoolantMode.OFF:
                raise ValueError("Epilog Zing cannot control coolant")
        elif kind in (
            CommandType.JOB_START,
            CommandType.JOB_END,
            CommandType.LAYER_START,
            CommandType.LAYER_END,
            CommandType.WORKPIECE_START,
            CommandType.WORKPIECE_END,
            CommandType.OPS_SECTION_START,
            CommandType.OPS_SECTION_END,
            CommandType.STATE_BLOCK_START,
            CommandType.STATE_BLOCK_END,
            CommandType.SET_RAPID_RATE,
        ):
            return
        else:
            raise ValueError(f"Unsupported Epilog Zing operation: {kind.name}")

    def _set_power(self, fraction: float) -> None:
        if not math.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError("Epilog power must be between 0 and 1")
        power = int(fraction * 100 + 1e-9)
        if power != self.power:
            self.power = power
            self.emit(f"YP{power:03d};")

    def _set_speed(self, speed: float) -> None:
        reference = self.machine.max_cut_speed
        if not math.isfinite(speed) or not 0 < speed <= reference:
            raise ValueError("Epilog cut speed must be within machine limits")
        if speed < reference / 100:
            raise ValueError("Epilog minimum speed is 1% of maximum speed")
        percent = int(speed * 100 / reference + 0.5)
        if not 1 <= percent <= 100:
            raise ValueError("Epilog minimum speed is 1% of maximum speed")
        if percent != self.speed:
            self.speed = percent
            self.emit(f"ZS{percent:03d};")

    def _move(self, point: tuple[float, ...], cut: bool) -> None:
        """Validate the exact dot coordinates emitted to the printer.

        Curve approximation and floating-point transforms can place a
        boundary point fractionally outside the bed in millimeters while
        it still addresses a valid printer dot.
        """
        x, y, z = point
        width, height = self.machine.axis_extents
        if not all(math.isfinite(v) for v in point):
            raise ValueError("Epilog coordinates must be finite")
        if z != 0:
            raise ValueError("Epilog Zing cannot execute Z moves")
        dpi = self.settings.resolution
        device_x, device_y = int(x * dpi / 25.4), int(y * dpi / 25.4)
        max_x, max_y = int(width * dpi / 25.4), int(height * dpi / 25.4)
        if not 0 <= device_x <= max_x or not 0 <= device_y <= max_y:
            raise ValueError(
                "Epilog path is outside the machine bed: "
                f"X={x:.6f}, Y={y:.6f} mm; "
                f"bed={width:g} x {height:g} mm"
            )
        active = cut and self.power > 0
        if active and not self.has_position:
            raise ValueError("Move to a start position before an Epilog cut")
        if active and self.speed is None:
            raise ValueError("Set a cutting speed before an Epilog cut")
        command = "PD" if active else "PU"
        self.emit(f"{command}{device_x},{device_y};")
        self.position = (x, y, z)
        self.has_position = True
        self.has_cut |= active

    def _linearize(self, ops: Ops, index: int) -> None:
        original_power = self.power
        segments = ops.linearize(index, self.position)
        for sub_index in range(segments.len()):
            self.command(segments, sub_index)
        if ops.command_type(index) == CommandType.SCAN_LINE:
            self._set_power(original_power / 100)
