import math

import pytest
from rayforge.machine.driver import get_driver_cls
from rayforge.machine.driver.driver import DriverMaturity
from rayforge.pipeline.encoder.base import EncodedOutput
from raygeo.ops import Ops
from raygeo.ops.state import AirAssistMode

from epilog_zing import EpilogZingDriver
from epilog_zing.encoder import (
    FOOTER,
    EpilogZingEncoder,
    ZingSettings,
    decode_job,
)


def test_profile_and_driver_registration(zing_machine):
    assert zing_machine.driver_name == "EpilogZingDriver"
    assert get_driver_cls("EpilogZingDriver") is EpilogZingDriver
    assert zing_machine.axis_extents == (609.6, 304.8)
    assert zing_machine.y_axis_down
    assert not zing_machine.has_z_axis
    assert not zing_machine.home_on_start
    assert zing_machine.dialect is None
    assert zing_machine.driver_args["host"] == ""
    assert EpilogZingDriver.maturity == DriverMaturity.UNTESTED


def test_rectangle_wire_format(zing_machine, zing_doc, zing_ops):
    result = EpilogZingEncoder().encode(zing_ops, zing_machine, zing_doc)
    payload = decode_job(result.text)
    assert payload.startswith(b"\x1b%-12345X@PJL JOB NAME=Epilog test\r\n")
    assert b"\x1b&u500D" in payload
    assert b"\x1b*r1A\x1b*rC\x1b%1BIN;" in payload
    assert b"XR1000;YP000;YP025;ZS010;" in payload
    assert b"PU500,500;PD1000,500;PD1000,1000;PD500,1000;PD500,500;" in payload
    assert payload.endswith(b"PU;YP000;WF0;" + FOOTER + bytes(4096))
    assert "\x1b" not in result.text
    assert "\x00" not in result.text


def test_pipeline_text_only_roundtrip(zing_machine, zing_doc, zing_ops):
    result = EpilogZingEncoder().encode(zing_ops, zing_machine, zing_doc)
    stored = EncodedOutput(result.text, result.op_map)
    assert stored.driver_data == {}
    assert decode_job(stored.text) == decode_job(result.text)
    assert result.op_map.op_count == zing_ops.len()
    for index in range(zing_ops.len()):
        start, count = result.op_map.span_for_op(index)
        assert count > 0
        for line in range(start, start + count):
            assert result.op_map.op_for_line(line) == index


@pytest.mark.parametrize("dpi", [100, 200, 250, 400, 500, 1000])
def test_dpi_and_machine_space_coordinates(
    zing_machine, zing_doc, zing_ops, dpi
):
    zing_machine.driver_args["resolution"] = str(dpi)
    result = EpilogZingEncoder().encode(zing_ops, zing_machine, zing_doc)
    assert f"PU{dpi},{dpi};".encode() in decode_job(result.text)


def test_title_cannot_inject_commands(zing_machine, zing_doc, zing_ops):
    zing_doc.name = 'Grüße\r\n\x1bE@PJL EOJ\\x1b"' * 10
    payload = decode_job(
        EpilogZingEncoder().encode(zing_ops, zing_machine, zing_doc).text
    )
    label = payload.split(b"\r\n", 1)[0].split(b"NAME=", 1)[1]
    assert len(label) <= 64
    assert b"\x1b" not in label
    assert b"\\" not in label
    assert payload.count(b"@PJL EOJ") == 1


def test_power_off_moves_and_multiple_settings(zing_machine, zing_doc):
    ops = Ops()
    ops.set_feed_rate(600)
    ops.set_power(0.25)
    ops.move_to(25.4, 25.4, 0)
    ops.line_to(50.8, 25.4, 0)
    ops.set_power(0)
    ops.line_to(76.2, 25.4, 0)
    ops.set_power(0.5)
    ops.set_feed_rate(1200)
    ops.set_frequency(500)
    ops.line_to(101.6, 25.4, 0)
    payload = decode_job(
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc).text
    )
    assert b"YP000;PU1500,500;YP050;ZS020;XR0500;PD2000,500;" in payload


def test_curves_are_linearized_and_mapped(zing_machine, zing_doc):
    ops = Ops()
    ops.set_power(0.2)
    ops.set_feed_rate(600)
    ops.move_to(30, 30, 0)
    ops.arc_to(40, 30, 5, 0, clockwise=True)
    result = EpilogZingEncoder().encode(ops, zing_machine, zing_doc)
    assert decode_job(result.text).count(b"PD") >= 3
    start, count = result.op_map.span_for_op(3)
    assert count >= 3
    assert all(
        result.op_map.op_for_line(line) == 3
        for line in range(start, start + count)
    )


def test_scanline_power_and_following_vector(zing_machine, zing_doc):
    ops = Ops()
    ops.set_power(0.25)
    ops.set_feed_rate(600)
    ops.move_to(25.4, 25.4, 0)
    ops.scan_to(50.8, 25.4, 0, bytearray([0, 128, 255, 0]))
    ops.line_to(76.2, 25.4, 0)
    payload = decode_job(
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc).text
    )
    assert b"YP050;" in payload
    assert b"YP100;" in payload
    assert b"YP000;" in payload
    assert b"YP025;PD1500,500;" in payload


@pytest.mark.parametrize(
    "point",
    [(-1, 10, 0), (610, 10, 0), (10, 305, 0), (10, 10, 1), (math.inf, 0, 0)],
)
def test_invalid_paths_are_rejected(zing_machine, zing_doc, point):
    ops = Ops()
    ops.set_power(0.25)
    ops.set_feed_rate(600)
    ops.move_to(*point)
    ops.line_to(10, 10, 0)
    with pytest.raises(ValueError):
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc)


@pytest.mark.parametrize(
    "point,command",
    [
        ((-1.6604133e-8, 0, 0), b"PU0,0;"),
        ((67.8214396, -1.6604133e-8, 0), b"PU1335,0;"),
        ((-0.001195, 24.829478, 0), b"PU0,488;"),
        ((609.6 + 1e-8, 304.8 + 1e-8, 0), b"PU12000,6000;"),
    ],
)
def test_bed_edges_are_validated_at_device_resolution(
    zing_machine, zing_doc, point, command
):
    ops = Ops()
    ops.set_power(0.25)
    ops.set_feed_rate(600)
    ops.move_to(*point)
    ops.line_to(10, 10, 0)
    encoded = EpilogZingEncoder().encode(ops, zing_machine, zing_doc)
    assert command in decode_job(encoded.text)


@pytest.mark.parametrize("dpi", [100, 200, 250, 400, 500, 1000])
def test_outside_device_bed_is_rejected(zing_machine, zing_doc, dpi):
    zing_machine.driver_args["resolution"] = str(dpi)
    ops = Ops()
    ops.move_to(10, -25.4 / dpi * 1.1, 0)
    with pytest.raises(ValueError, match="outside the machine bed"):
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc)


@pytest.mark.parametrize("speed", [0, -1, 1, 50, 6001, math.nan, math.inf])
def test_invalid_speed_is_not_silently_clamped(
    zing_machine, zing_doc, zing_ops, speed
):
    ops = Ops()
    ops.set_feed_rate(speed)
    ops.extend(zing_ops)
    with pytest.raises(ValueError):
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc)


def test_missing_speed_and_unsupported_ops(zing_machine, zing_doc):
    ops = Ops()
    ops.set_power(0.5)
    ops.move_to(1, 1, 0)
    ops.line_to(2, 2, 0)
    with pytest.raises(ValueError, match="cutting speed"):
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc)
    ops = Ops()
    ops.dwell(1)
    with pytest.raises(ValueError, match="Unsupported.*DWELL"):
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc)


def test_air_assist_is_reported_as_manual(
    zing_machine, zing_doc, zing_ops, caplog
):
    zing_ops.set_air_assist(AirAssistMode.ON)
    EpilogZingEncoder().encode(zing_ops, zing_machine, zing_doc)
    assert "air assist must be enabled at the machine" in caplog.text


def test_encoder_is_reusable(zing_machine, zing_doc, zing_ops):
    encoder = EpilogZingEncoder()
    first = encoder.encode(zing_ops, zing_machine, zing_doc)
    assert encoder.encode(zing_ops, zing_machine, zing_doc).text == first.text
    empty = encoder.encode(Ops(), zing_machine, zing_doc)
    assert empty.text == ""
    assert empty.op_map.op_count == 0


@pytest.mark.parametrize(
    "text", ["", "G1 X10", r"\x1b%-12345X@PJL JOB NAME=x"]
)
def test_invalid_transcripts_are_rejected(text):
    with pytest.raises(ValueError):
        decode_job(text)


@pytest.mark.parametrize(
    "kwargs", [{"resolution": 300}, {"frequency": 9}, {"frequency": 5001}]
)
def test_settings_validation(kwargs):
    with pytest.raises(ValueError):
        ZingSettings(**kwargs)


@pytest.mark.parametrize("fraction", [0.29, 0.57, 0.58])
def test_integer_power_is_not_reduced_by_float_roundoff(
    zing_machine, zing_doc, fraction
):
    ops = Ops()
    ops.set_power(fraction)
    ops.set_feed_rate(600)
    ops.move_to(1, 1, 0)
    ops.line_to(2, 2, 0)
    result = EpilogZingEncoder().encode(ops, zing_machine, zing_doc)
    assert f"YP{round(fraction * 100):03d};".encode() in decode_job(
        result.text
    )


def test_cut_requires_explicit_start_position(zing_machine, zing_doc):
    ops = Ops()
    ops.set_power(0.5)
    ops.set_feed_rate(600)
    ops.line_to(1, 1, 0)
    with pytest.raises(ValueError, match="start position"):
        EpilogZingEncoder().encode(ops, zing_machine, zing_doc)


def test_wrong_origin_is_rejected(zing_machine, zing_doc, zing_ops):
    from rayforge.machine.models.machine import Origin

    zing_machine.origin = Origin.BOTTOM_LEFT
    with pytest.raises(ValueError, match="top-left"):
        EpilogZingEncoder().encode(zing_ops, zing_machine, zing_doc)
