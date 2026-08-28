"""Role-level interview questions, generated from the ICP and
calibration — see prompts/interview_questions.md. Distinct from
stages/screening.py, which validates one candidate's own record; this
runs once per role and applies to every candidate reaching a screen."""

import json

from .. import llm_client, storage
from ..models import RoleInterviewQuestions


def run(role_id: str, *, storage_backend=storage) -> RoleInterviewQuestions:
    icp = storage_backend.require_section(role_id, "icp")
    calibration = storage_backend.require_section(role_id, "calibration")
    prompt = llm_client.render_prompt(
        "interview_questions.md",
        icp_json=json.dumps(icp),
        calibration_json=json.dumps(calibration),
    )
    result = llm_client.generate(prompt, RoleInterviewQuestions, stage="interview_questions")
    storage_backend.merge_section(role_id, "interview_questions", result.model_dump())
    return result
