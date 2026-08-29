"""Role-level interview questions, generated from the JD/ICP analysis
(§icp, §calibration) — distinct from screening.py's ScreeningQuestionSet,
which validates one specific candidate's record against what that
candidate already claimed. This is the standard question set for the
role itself, and varies by role because it's grounded in that role's own
must-haves and red flags, not a generic template reused across roles.

Regeneration is append-only (a generation history), not an overwrite —
a recruiter regenerating to get a different angle shouldn't lose what
they already had. `RoleInterviewQuestions` is what one LLM call
produces; `InterviewQuestionGeneration` wraps that with a timestamp and
a repeat-detection flag; `InterviewQuestionHistory` is what's actually
persisted under the role's `interview_questions` section."""

from typing import Any

from pydantic import BaseModel, Field


class InterviewQuestion(BaseModel):
    question: str
    why_it_matters: str = Field(
        default="",
        description="which must-have, red flag, or ambiguity this question is meant to validate",
    )


class RoleInterviewQuestions(BaseModel):
    core_questions: list[InterviewQuestion] = Field(
        default_factory=list, description="ask every candidate for this role"
    )
    role_specific_questions: list[InterviewQuestion] = Field(
        default_factory=list,
        description="specific to what makes this role different, not generic to the function",
    )
    red_flag_questions: list[InterviewQuestion] = Field(
        default_factory=list, description="probe this role's specific red flags / disqualifiers"
    )


class InterviewQuestionGeneration(RoleInterviewQuestions):
    generated_at: str = Field(default="", description="ISO 8601 timestamp of this generation")
    repeated_questions: list[str] = Field(
        default_factory=list,
        description="questions in this generation whose text closely matches an earlier "
        "generation's — the model is instructed not to repeat itself, but this is surfaced "
        "honestly rather than silently assumed to have worked",
    )


class InterviewQuestionHistory(BaseModel):
    generations: list[InterviewQuestionGeneration] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> "InterviewQuestionHistory":
        """Normalizes the persisted JobSection blob on read. Roles whose
        interview questions were generated before this history shape
        existed still have the old flat single-generation dict (no
        `generations` key) — treat that as generation one rather than
        losing it. Read-time only; never rewrites storage itself."""
        if not raw:
            return cls()
        if "generations" in raw:
            return cls.model_validate(raw)
        return cls(generations=[InterviewQuestionGeneration(generated_at="", **raw)])
