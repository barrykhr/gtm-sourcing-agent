"""Interview Intelligence, Phase 2: maps a job's must-have/nice-to-have
requirements against what was actually said in an already-transcribed
interview (Phase 1), competency by competency, with evidence and
follow-up questions. Also backs "Ask Talyn" — a narrow Q&A that answers
only from the JD, the candidate's resume claims, and this transcript.

Same "no storage_backend kwarg" reasoning as
stages/interview_processing.py: db_storage is the only backend for
interviews, so importing it directly here loses no real swappability.

The critical discipline (see prompts/interview_intelligence.md and
models/interview.py's EvidenceStrength): a resume claim is context, not
evidence. Evidence only ever comes from the CANDIDATE's own words in
this transcript. To keep that grounded rather than trusting the model to
reproduce transcript text verbatim, the model cites evidence by
*transcript segment index* (the `[N]` numbers in the numbered transcript
built below) — this module resolves those indices back to real
TranscriptSegment rows (real text, real timestamp) after the model call,
so what the recruiter sees is never a model-paraphrased "quote"."""

import json
from typing import Any

from .. import db_storage, llm_client
from ..models import AskInterviewAnswer, InterviewIntelligenceResult


def _numbered_transcript(segments: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{s['sequence']}] {s['speaker'].upper()}: {s['text']}" for s in segments)


def _resume_claims(candidate: dict[str, Any]) -> str:
    """Formats the structured, already-evidence-labeled fields on the
    Candidate record (models/candidate.py) into readable text for the
    prompt — deliberately not the raw resume text, so the model sees the
    same VERIFIED/NOT_STATED/INFERRED discipline the rest of the product
    already applies to this candidate's data."""
    lines: list[str] = []
    if candidate.get("current_title") or candidate.get("current_company"):
        lines.append(f"Current role: {candidate.get('current_title', '')} at {candidate.get('current_company', '')}".strip())
    if candidate.get("total_experience"):
        lines.append(f"Total experience: {candidate['total_experience']}")
    if candidate.get("relevant_experience_summary"):
        lines.append(f"Experience summary: {candidate['relevant_experience_summary']}")
    if candidate.get("education"):
        lines.append(f"Education: {candidate['education']}")
    for label, key in (("Achievements", "achievements"), ("Metrics", "metrics"), ("Evidence of fit", "evidence_of_fit")):
        facts = candidate.get(key) or []
        if facts:
            lines.append(f"{label}:")
            for f in facts:
                lines.append(f"  - {f.get('fact', '')} [{f.get('evidence_level', 'NOT_STATED')}]")
    if candidate.get("missing_information"):
        lines.append("Missing information: " + "; ".join(candidate["missing_information"]))
    return "\n".join(lines) if lines else "(no structured resume data captured for this candidate)"


def _job_requirements(role_id: str) -> tuple[list[str], list[str]]:
    """Prefers the ICP's must_have/nice_to_have (the recruiter-tunable
    rubric — see icp.py's update_criteria) over the raw JD extraction,
    falling back to the JD's own requirements if no ICP has been built
    yet for this role."""
    state = db_storage.load_role(role_id)
    icp = state.get("icp") or {}
    job_description = state.get("job_description") or {}
    must_have = icp.get("must_have") or job_description.get("must_have_requirements") or []
    nice_to_have = icp.get("nice_to_have") or job_description.get("nice_to_have_requirements") or []
    return must_have, nice_to_have


def _get_interview_and_candidate(interview_id: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    interview = db_storage.get_interview(interview_id)
    if interview is None:
        raise ValueError(f"interview '{interview_id}' not found")
    if interview["transcript_status"] != "completed":
        raise ValueError("the transcript must finish processing before intelligence can run")
    segments = db_storage.get_transcript(interview_id)
    if not segments:
        raise ValueError("this interview has no transcript to analyze")
    state = db_storage.load_role(interview["role_id"])
    candidate = state["candidates"].get(interview["candidate_id"])
    if candidate is None:
        raise ValueError(f"candidate '{interview['candidate_id']}' not found for role '{interview['role_id']}'")
    return interview, candidate, segments


def run(interview_id: str) -> dict[str, Any]:
    interview, candidate, segments = _get_interview_and_candidate(interview_id)
    must_have, nice_to_have = _job_requirements(interview["role_id"])

    db_storage.update_interview(interview_id, intelligence_status="processing", intelligence_error=None)

    prompt = llm_client.render_prompt(
        "interview_intelligence.md",
        must_have_json=json.dumps(must_have),
        nice_to_have_json=json.dumps(nice_to_have),
        resume_claims=_resume_claims(candidate),
        transcript=_numbered_transcript(segments),
    )
    try:
        result = llm_client.generate(prompt, InterviewIntelligenceResult, stage="interview_intelligence")
    except Exception as e:
        db_storage.update_interview(interview_id, intelligence_status="failed", intelligence_error=str(e))
        raise

    seg_by_sequence = {s["sequence"]: s for s in segments}
    competencies_to_save = []
    for c in result.competencies:
        evidence = [
            {"segment_id": seg_by_sequence[e.segment_index]["id"], "note": e.note}
            for e in c.evidence
            if e.segment_index in seg_by_sequence
        ]
        competencies_to_save.append({
            "competency": c.competency, "category": c.category,
            "status": c.status, "rationale": c.rationale, "evidence": evidence,
        })
    follow_ups_to_save = [f.model_dump() for f in result.follow_up_questions]

    # A re-run (analyze_interview is callable again any time) replaces
    # the prior scorecard from scratch rather than doubling up.
    db_storage.delete_interview_intelligence(interview_id)
    db_storage.save_interview_intelligence(interview_id, competencies_to_save, follow_ups_to_save)
    db_storage.update_interview(interview_id, intelligence_status="completed")
    return {"competency_count": len(competencies_to_save), "follow_up_count": len(follow_ups_to_save)}


def ask(interview_id: str, question: str) -> dict[str, Any]:
    """"Ask Talyn" — a narrow Q&A over this one interview. Deliberately
    ephemeral (not persisted): each call is a fresh, grounded answer, not
    a chat history the model could drift from. Doesn't require Phase 2's
    scorecard to have run first, though it's included as context when
    available (get_interview_intelligence returns empty lists rather than
    raising if it hasn't run yet)."""
    interview, candidate, segments = _get_interview_and_candidate(interview_id)
    must_have, nice_to_have = _job_requirements(interview["role_id"])
    intelligence = db_storage.get_interview_intelligence(interview_id)

    prompt = llm_client.render_prompt(
        "ask_interview.md",
        must_have_json=json.dumps(must_have),
        nice_to_have_json=json.dumps(nice_to_have),
        resume_claims=_resume_claims(candidate),
        competencies_json=json.dumps(intelligence["competencies"]),
        transcript=_numbered_transcript(segments),
        question=question,
    )
    result = llm_client.generate(prompt, AskInterviewAnswer, stage="ask_interview_question")

    seg_by_sequence = {s["sequence"]: s for s in segments}
    citations = []
    for c in result.citations:
        seg = seg_by_sequence.get(c.segment_index)
        if seg is None:
            continue
        citations.append({
            "segment_id": seg["id"], "speaker": seg["speaker"], "text": seg["text"], "start_time": seg["start_time"],
        })
    return {"answer": result.answer, "citations": citations, "unable_to_answer": result.unable_to_answer}
