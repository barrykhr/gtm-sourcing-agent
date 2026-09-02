"""Conversation History (WhatsApp/call/email demo batch): the rolling
summary generated across a candidate's full communication log. Distinct
from OutreachSequence (a draft to be sent) and Candidate's own
EvidencedFacts (extracted from a resume) — this summarizes what actually
happened across every logged touchpoint, in the recruiter's own log
entries and call notes/transcripts, not from the resume.

`ConversationIntelligence` (Conversation Intelligence batch) is the
structured extraction over the same log — current/expected compensation,
notice period, interest level, concerns — each field left empty (or
`interest_level`/`recommendation` left "Insufficient evidence") rather
than guessed when the log doesn't support it. This is genuinely derived
from whatever the recruiter has logged (including a pasted call
transcript, if one was entered) — there is no telephony/STT integration
producing these transcripts automatically; see CommunicationLogEntry's
own docstring."""

from typing import Literal

from pydantic import BaseModel, Field

InterestLevel = Literal["High", "Medium", "Low", "Insufficient evidence"]


class ConversationSummaryResult(BaseModel):
    summary: str = Field(
        description="2-4 sentence rolling summary of the relationship so far across every "
        "channel — tone, where things stand, any commitments made on either side"
    )
    open_items: list[str] = Field(
        default_factory=list,
        description="concrete unresolved things from the log, e.g. 'said they'd share updated CTC by Friday'",
    )


class ConversationIntelligence(BaseModel):
    """Structured extraction over the same communication log ConversationSummaryResult
    summarizes — every field is left empty/"Insufficient evidence" rather than guessed
    when the log doesn't actually support it (never invented)."""

    current_compensation: str = Field(default="", description="as stated in the log; empty if never mentioned")
    expected_compensation: str = Field(default="", description="as stated in the log; empty if never mentioned")
    notice_period: str = Field(default="", description="as stated in the log; empty if never mentioned")
    location: str = Field(default="", description="as stated in the log; empty if never mentioned")
    relocation_willingness: str = Field(default="", description="as stated in the log; empty if never discussed")
    relevant_experience: str = Field(default="", description="relevant experience the candidate raised in conversation, distinct from resume-derived evidence")
    leadership: str = Field(default="", description="anything the candidate said about managing/leading people or projects; empty if not discussed")
    motivation: str = Field(default="", description="why they're engaging with this role/move, in their own stated terms")
    interest_level: InterestLevel = Field(default="Insufficient evidence")
    concerns: list[str] = Field(default_factory=list, description="hesitations or worries the candidate raised")
    risks: list[str] = Field(default_factory=list, description="risk signals for the recruiter to weigh — distinct from the candidate's own stated concerns")
    unanswered_questions: list[str] = Field(default_factory=list, description="questions asked (by either side) that the log shows were never answered")
    recommendation: str = Field(
        default="Insufficient evidence",
        description='a next step, e.g. "Move to interview" — or literally "Insufficient evidence" if the log is too thin to recommend one',
    )
