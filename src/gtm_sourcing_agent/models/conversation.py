"""Conversation History (WhatsApp/call/email demo batch): the rolling
summary generated across a candidate's full communication log. Distinct
from OutreachSequence (a draft to be sent) and Candidate's own
EvidencedFacts (extracted from a resume) — this summarizes what actually
happened across every logged touchpoint, in the recruiter's own log
entries and call notes/transcripts, not from the resume."""

from pydantic import BaseModel, Field


class ConversationSummaryResult(BaseModel):
    summary: str = Field(
        description="2-4 sentence rolling summary of the relationship so far across every "
        "channel — tone, where things stand, any commitments made on either side"
    )
    open_items: list[str] = Field(
        default_factory=list,
        description="concrete unresolved things from the log, e.g. 'said they'd share updated CTC by Friday'",
    )
