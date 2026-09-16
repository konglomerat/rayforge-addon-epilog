import asyncio
import re

import pytest
from rayforge.core.doc import Doc
from rayforge.core.workpiece import WorkPiece
from rayforge.machine.device.profile import DeviceProfile
from rayforge.pipeline.intent_builder import IntentBuilder, job_encode_key
from raygeo.geo import Geometry
from raygeo.pipeline.execute import execute_stages

from epilog_zing.encoder import decode_job
from epilog_zing.worker import DEVICES_DIR


@pytest.mark.asyncio
async def test_contour_pipeline_encodes_epilog_and_flips_y_once(
    context_initializer, contour_step_class, task_mgr
):
    context = context_initializer
    profile = DeviceProfile.from_path(DEVICES_DIR / "epilog-zing-24")
    machine = profile.create_machine(context)
    machine.auto_connect = False
    try:
        step = contour_step_class.create(context, name="cut")
        step.set_selected_head_uid(machine.get_default_head().uid)
        step.set_cut_speed(600)
        step.set_power(0.25)
        geometry = Geometry()
        geometry.move_to(0, 0)
        geometry.line_to(1, 0)
        geometry.line_to(1, 1)
        geometry.line_to(0, 1)
        geometry.close_path()
        workpiece = WorkPiece(name="square")
        workpiece._edited_boundaries = geometry
        workpiece.set_size(10, 10)
        workpiece.set_pos(50, 50)
        doc = Doc()
        workflow = doc.active_layer.workflow
        assert workflow is not None
        workflow.add_child(step)
        doc.active_layer.add_child(workpiece)
        nodes = IntentBuilder(machine=machine, generation_id=1).build(doc)
        completed = []
        execute_stages(nodes, completed.append)
        encoded = next(n for n in completed if n.key == job_encode_key())
        assert encoded.error is None, encoded.error
        assert encoded.output is not None
        payload = decode_job(encoded.output.text)
        assert b"ZS010;" in payload
        assert b"YP025;" in payload
        cuts = re.findall(rb"PD(\d+),(\d+);", payload)
        assert len(cuts) >= 4
        for x, y in cuts:
            assert 20 < int(x) * 25.4 / 500 < 80
            assert 200 < int(y) * 25.4 / 500 < 300
    finally:
        await machine.shutdown()
        assert await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
