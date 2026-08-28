"""Role-level interview questions, generated once from the JD/ICP
analysis (§icp, §calibration) — distinct from screening.py's
ScreeningQuestionSet, which validates one specific candidate's record
against what that candidate already claimed. This is the standard
question set for the role itself, and varies by role because it's
grounded in that role's own must-haves and red flags, not a generic
template reused across roles."""

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
