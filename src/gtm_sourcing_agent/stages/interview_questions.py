"""Role-level interview questions, generated from the ICP and
calibration — see prompts/interview_questions.md. Distinct from
stages/screening.py, which validates one candidate's own record; this
runs once per role and applies to every candidate reaching a screen.

Each run appends a new generation rather than overwriting the last one
(see models/interview_questions.py's InterviewQuestionHistory) — a
recruiter regenerating wants another angle, not to lose what they had."""

import json
import re
from datetime import UTC, datetime

from .. import llm_client, storage
from ..models import InterviewQuestion, InterviewQuestionGeneration, InterviewQuestionHistory, RoleInterviewQuestions

MIN_QUESTIONS = 10


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _all_questions(gen: RoleInterviewQuestions) -> list[InterviewQuestion]:
    return [*gen.core_questions, *gen.role_specific_questions, *gen.red_flag_questions]


def run(role_id: str, *, storage_backend=storage) -> InterviewQuestionHistory:
    icp = storage_backend.require_section(role_id, "icp")
    calibration = storage_backend.require_section(role_id, "calibration")
    state = storage_backend.load_role(role_id)
    history = InterviewQuestionHistory.from_raw(state.get("interview_questions"))

    prior_questions = [q.question for gen in history.generations for q in _all_questions(gen)]
    prior_questions_text = (
        "\n".join(f"- {q}" for q in prior_questions)
        if prior_questions
        else "(none yet — this is the first generation for this role)"
    )

    prompt = llm_client.render_prompt(
        "interview_questions.md",
        icp_json=json.dumps(icp),
        calibration_json=json.dumps(calibration),
        prior_questions_text=prior_questions_text,
    )
    result = llm_client.generate(prompt, RoleInterviewQuestions, stage="interview_questions")

    total = len(_all_questions(result))
    if total < MIN_QUESTIONS:
        # One retry, with the shortfall spelled out — a real safety net
        # for an under-count, not a way to pad the result with invented
        # questions. If the retry still comes up short, we keep it as-is
        # and let the count speak for itself.
        retry_prompt = prompt + (
            f"\n\nYour previous attempt returned only {total} questions total across all three "
            f"groups combined — this role needs at least {MIN_QUESTIONS}. Cover more ground within "
            f"each group and try again."
        )
        retried = llm_client.generate(retry_prompt, RoleInterviewQuestions, stage="interview_questions")
        if len(_all_questions(retried)) > total:
            result = retried

    prior_normalized = {_normalize(q) for q in prior_questions}
    repeated = [q.question for q in _all_questions(result) if _normalize(q.question) in prior_normalized]

    generation = InterviewQuestionGeneration(
        generated_at=datetime.now(UTC).isoformat(),
        core_questions=result.core_questions,
        role_specific_questions=result.role_specific_questions,
        red_flag_questions=result.red_flag_questions,
        repeated_questions=repeated,
    )
    history.generations.append(generation)
    storage_backend.merge_section(role_id, "interview_questions", history.model_dump())
    return history
