"""Interview Intelligence, Phase 1 (Notetaker): the AI summary generated
once a recorded interview has been transcribed. Deliberately
recruitment-specific, not a generic meeting summary — see
`prompts/interview_summary.md`. Phase 2 (competency/evidence extraction,
scorecard, follow-up questions) adds its own models alongside this one
once that batch lands; this file only covers what Phase 1 needs.
"""

from pydantic import BaseModel, Field


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
