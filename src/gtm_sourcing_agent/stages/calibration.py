"""Stage 2: Hiring Manager Calibration. See prompts/calibration.md."""

import json

from .. import llm_client, storage
from ..models import HiringManagerCalibration


def run(role_id: str, *, storage_backend=storage) -> HiringManagerCalibration:
    jd = storage_backend.require_section(role_id, "job_description")
    prompt = llm_client.render_prompt("calibration.md", job_description_json=json.dumps(jd))
    result = llm_client.generate(prompt, HiringManagerCalibration, stage="calibration")
    storage_backend.merge_section(role_id, "calibration", result.model_dump())
    return result
