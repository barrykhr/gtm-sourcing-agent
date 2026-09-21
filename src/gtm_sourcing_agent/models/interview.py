"""Interview Intelligence models.

Phase 1 (Notetaker): `InterviewSummaryResult`, the AI summary generated
once a recorded interview has been transcribed. Deliberately
recruitment-specific, not a generic meeting summary — see
`prompts/interview_summary.md`.

Phase 2 (Intelligence): `InterviewIntelligenceResult` maps the JD's
must-have/nice-to-have requirements and the candidate's resume claims
onto the interview transcript itself, competency by competency. The
critical discipline here (see prompts/interview_intelligence.md and
stages/interview_intelligence.py): a resume claim is never treated as
interview evidence. If the resume says a skill and the transcript never
discusses it, the status is "Needs validation", not "Strong evidence" —
evidence only ever comes from what the candidate actually said in this
transcript. Evidence cites a transcript segment *index* (from the
numbered transcript in the prompt) rather than a free-text quote, so the
real segment text/timestamp is looked up server-side afterward instead
of trusting the model to reproduce it verbatim — see
stages/interview_intelligence.py's segment-index resolution.

`AskInterviewAnswer` backs the "Ask Talyn" Q&A: answers only from the
JD, the candidate's resume claims, and this transcript — never inventing
evidence, and citing the same segment-index mechanism as evidence above.
"""

from typing import Literal

from pydantic import BaseModel, Field

CompetencyCategory = Literal["must_have", "nice_to_have"]
EvidenceStrength = Literal["Strong evidence", "Needs validation", "Not discussed", "Insufficient evidence"]


class InterviewSummaryResult(BaseModel):
    overview: str = Field(description="2-4 sentences on what was actually discussed and demonstrated")
    key_experience: list[str] = Field(
        default_factory=list, description="specific experience the candidate described, in their own terms"
    )
    technical_skills: list[str] = Field(
        default_factory=list,
        description="specific tools/technologies/skills the candidate meaningfully discussed — not just named in passing",
    )
    examples_provided: list[str] = Field(
        default_factory=list, description="concrete examples/projects/stories the candidate gave"
    )
    areas_not_discussed: list[str] = Field(
        default_factory=list,
        description="topics relevant to a hiring decision that never came up in this transcript",
    )
    potential_followups: list[str] = Field(
        default_factory=list, description="short list of what's worth asking about next time, based on gaps or vague answers"
    )


class CompetencyEvidenceRef(BaseModel):
    segment_index: int = Field(
        description="the [N] index of the transcript segment (from the numbered transcript) that supports this competency"
    )
    note: str = Field(
        default="", description="optional short note on why this segment is relevant — not a substitute for the segment itself"
    )


class InterviewCompetencyResult(BaseModel):
    competency: str = Field(description="one specific, concrete requirement — not a vague category")
    category: CompetencyCategory
    status: EvidenceStrength = Field(
        description=(
            "'Strong evidence' only when the CANDIDATE's own words in this transcript clearly demonstrate it. "
            "'Needs validation' when the resume claims it but the transcript doesn't clearly confirm it, or the "
            "transcript only partially/vaguely touches it. 'Not discussed' when neither the transcript nor the "
            "resume ever addresses it. 'Insufficient evidence' when it came up but too briefly/ambiguously to "
            "judge either way. Never mark 'Strong evidence' from a resume claim alone."
        )
    )
    rationale: str = Field(description="1-2 sentences on why this status, referencing what was or wasn't actually said")
    evidence: list[CompetencyEvidenceRef] = Field(
        default_factory=list, description="transcript segments backing this status — empty for 'Not discussed'"
    )


class FollowUpQuestionResult(BaseModel):
    question: str
    rationale: str = Field(default="", description="what gap or ambiguity this question would resolve")
    related_competency: str = Field(default="", description="the competency this question would help validate, if any")


class InterviewIntelligenceResult(BaseModel):
    competencies: list[InterviewCompetencyResult] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestionResult] = Field(
        default_factory=list,
        description="questions worth asking in a follow-up round, focused on 'Needs validation'/'Not discussed' competencies",
    )


class AskInterviewAnswer(BaseModel):
    answer: str = Field(
        description="a direct answer grounded only in the JD requirements, the candidate's resume claims, and this transcript"
    )
    citations: list[CompetencyEvidenceRef] = Field(
        default_factory=list, description="transcript segments (by index) the answer is based on"
    )
    unable_to_answer: bool = Field(
        default=False,
        description="true if the transcript/resume/JD genuinely don't contain enough to answer — set this instead of guessing",
    )
