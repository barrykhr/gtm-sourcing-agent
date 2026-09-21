"""Interview Intelligence, Phase 2: competency/evidence scorecard +
follow-up questions + "Ask Talyn", exercised through the real HTTP layer
via TestClient (same pattern as test_interview_intelligence.py).
llm_client.generate is mocked — no real model call — but the segment-
index -> real-transcript-segment resolution (the part that guards
against a fabricated quote) runs for real."""

import time

import pytest
from fastapi.testclient import TestClient

from gtm_sourcing_agent import db, db_storage, llm_client
from gtm_sourcing_agent.api import app
from gtm_sourcing_agent.models import (
    AskInterviewAnswer,
    CompetencyEvidenceRef,
    FollowUpQuestionResult,
    InterviewCompetencyResult,
    InterviewIntelligenceResult,
)

client = TestClient(app)


def _wait_for_task(role_id: str, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    task = None
    while time.time() < deadline:
        task = client.get(f"/jobs/{role_id}/tasks/{task_id}").json()
        if task["status"] in ("succeeded", "failed"):
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish within {timeout}s: last seen {task}")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    client.cookies.clear()
    client.post("/auth/signup", json={"email": "recruiter@example.com", "password": "test-password-123"})
    return tmp_path


@pytest.fixture
def fake_generate(monkeypatch):
    calls = []
    queue = []

    def _fake(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage=""):
        calls.append({"prompt": prompt, "output_model": output_model, "stage": stage})
        return queue.pop(0)

    monkeypatch.setattr(llm_client, "generate", _fake)
    _fake.calls = calls
    _fake.queue = queue
    return _fake


def _set_up_interview_with_transcript(role_id: str = "job-a", candidate_id: str = "cand-1") -> str:
    """Job + candidate + ICP + a completed interview with a real
    transcript — the state analyze_interview needs to have anything to
    work with."""
    db_storage.create_job(role_id, title="GTM Engineer")
    db_storage.merge_candidate(role_id, candidate_id, {"name": "Rahul Sharma"})
    db_storage.merge_section(role_id, "icp", {
        "must_have": ["5+ years closing enterprise SaaS", "History of $1M+ quota attainment"],
        "nice_to_have": ["Industrial/manufacturing domain experience"],
    })
    interview = client.post(f"/jobs/{role_id}/candidates/{candidate_id}/interviews", json={}).json()
    db_storage.save_transcript_segments(interview["id"], [
        {"speaker": "recruiter", "text": "Walk me through your background.", "start_time": 0.0, "end_time": 3.0},
        {"speaker": "candidate", "text": "Five years in enterprise SaaS sales, most recently at Samsara.", "start_time": 3.5, "end_time": 9.0},
        {"speaker": "recruiter", "text": "What's the largest deal you closed?", "start_time": 9.5, "end_time": 11.0},
        {"speaker": "candidate", "text": "A $1.2M ACV deal, nine-month cycle, three stakeholders.", "start_time": 11.5, "end_time": 18.0},
    ])
    # Mirrors a real completed Phase 1 pipeline run (see
    # stages/interview_processing.py) rather than just the one field
    # analyze_interview itself checks, so a test can assert Phase 1's
    # status/error are untouched by a Phase 2 analysis.
    db_storage.update_interview(interview["id"], status="completed", transcript_status="completed")
    return interview["id"]


def _fake_intelligence_result() -> InterviewIntelligenceResult:
    return InterviewIntelligenceResult(
        competencies=[
            InterviewCompetencyResult(
                competency="5+ years closing enterprise SaaS", category="must_have",
                status="Strong evidence", rationale="Candidate directly stated 5 years in enterprise SaaS sales.",
                evidence=[CompetencyEvidenceRef(segment_index=1, note="states years of experience")],
            ),
            InterviewCompetencyResult(
                competency="History of $1M+ quota attainment", category="must_have",
                status="Needs validation",
                rationale="Described a $1.2M deal but never stated overall quota attainment.",
                evidence=[CompetencyEvidenceRef(segment_index=3, note="largest deal, not quota attainment")],
            ),
            InterviewCompetencyResult(
                competency="Industrial/manufacturing domain experience", category="nice_to_have",
                status="Not discussed", rationale="Never came up.", evidence=[],
            ),
        ],
        follow_up_questions=[
            FollowUpQuestionResult(
                question="What was your quota attainment over the last two years?",
                rationale="Closes the gap the $1.2M deal example doesn't confirm on its own.",
                related_competency="History of $1M+ quota attainment",
            ),
        ],
    )


def test_analyze_requires_completed_transcript(isolated_db):
    db_storage.create_job("job-a", title="GTM Engineer")
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Rahul Sharma"})
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    resp = client.post(f"/interviews/{interview['id']}/analyze")
    assert resp.status_code == 400


def test_analyze_404s_for_missing_interview(isolated_db):
    resp = client.post("/interviews/no-such-interview/analyze")
    assert resp.status_code == 404


def test_get_intelligence_before_analysis_is_empty(isolated_db):
    interview_id = _set_up_interview_with_transcript()
    resp = client.get(f"/interviews/{interview_id}/intelligence")
    assert resp.status_code == 200
    assert resp.json() == {"competencies": [], "follow_up_questions": []}


def test_full_analysis_happy_path(isolated_db, fake_generate):
    interview_id = _set_up_interview_with_transcript()
    fake_generate.queue.append(_fake_intelligence_result())

    resp = client.post(f"/interviews/{interview_id}/analyze")
    assert resp.status_code == 202, resp.text
    task = resp.json()
    finished = _wait_for_task("job-a", task["task_id"])
    assert finished["status"] == "succeeded", finished

    assert fake_generate.calls[0]["stage"] == "interview_intelligence"

    intelligence = client.get(f"/interviews/{interview_id}/intelligence").json()
    assert len(intelligence["competencies"]) == 3

    strong = next(c for c in intelligence["competencies"] if c["status"] == "Strong evidence")
    assert strong["competency"] == "5+ years closing enterprise SaaS"
    assert len(strong["evidence"]) == 1
    # evidence resolved to the REAL transcript segment text, not a model quote
    assert strong["evidence"][0]["text"] == "Five years in enterprise SaaS sales, most recently at Samsara."
    assert strong["evidence"][0]["speaker"] == "candidate"
    assert strong["evidence"][0]["start_time"] == 3.5

    not_discussed = next(c for c in intelligence["competencies"] if c["status"] == "Not discussed")
    assert not_discussed["evidence"] == []

    assert len(intelligence["follow_up_questions"]) == 1
    assert "quota attainment" in intelligence["follow_up_questions"][0]["question"]

    interview = client.get(f"/interviews/{interview_id}").json()
    assert interview["intelligence_status"] == "completed"
    assert interview["intelligence_error"] is None


def test_analysis_drops_evidence_citing_an_invalid_segment_index(isolated_db, fake_generate):
    interview_id = _set_up_interview_with_transcript()
    fake_generate.queue.append(InterviewIntelligenceResult(
        competencies=[
            InterviewCompetencyResult(
                competency="Some requirement", category="must_have", status="Strong evidence",
                rationale="claims evidence at a segment index that doesn't exist",
                evidence=[CompetencyEvidenceRef(segment_index=999, note="hallucinated segment")],
            ),
        ],
    ))
    task = client.post(f"/interviews/{interview_id}/analyze").json()
    assert _wait_for_task("job-a", task["task_id"])["status"] == "succeeded"

    intelligence = client.get(f"/interviews/{interview_id}/intelligence").json()
    assert intelligence["competencies"][0]["evidence"] == []


def test_re_analyze_replaces_the_previous_scorecard(isolated_db, fake_generate):
    interview_id = _set_up_interview_with_transcript()
    fake_generate.queue.append(_fake_intelligence_result())
    task = client.post(f"/interviews/{interview_id}/analyze").json()
    _wait_for_task("job-a", task["task_id"])
    assert len(client.get(f"/interviews/{interview_id}/intelligence").json()["competencies"]) == 3

    fake_generate.queue.append(InterviewIntelligenceResult(
        competencies=[
            InterviewCompetencyResult(
                competency="Only one this time", category="must_have", status="Not discussed",
                rationale="second pass", evidence=[],
            ),
        ],
    ))
    task2 = client.post(f"/interviews/{interview_id}/analyze").json()
    _wait_for_task("job-a", task2["task_id"])

    intelligence = client.get(f"/interviews/{interview_id}/intelligence").json()
    assert len(intelligence["competencies"]) == 1
    assert intelligence["competencies"][0]["competency"] == "Only one this time"


def test_analysis_failure_is_recorded_and_recoverable(isolated_db, monkeypatch):
    interview_id = _set_up_interview_with_transcript()

    def _boom(*a, **kw):
        raise RuntimeError("model call failed")

    monkeypatch.setattr(llm_client, "generate", _boom)
    task = client.post(f"/interviews/{interview_id}/analyze").json()
    finished = _wait_for_task("job-a", task["task_id"])
    assert finished["status"] == "failed"
    assert "model call failed" in finished["error"]

    interview = client.get(f"/interviews/{interview_id}").json()
    assert interview["intelligence_status"] == "failed"
    assert "model call failed" in interview["intelligence_error"]
    # Phase 1's own status/error are untouched by a Phase 2 failure
    assert interview["status"] == "completed"
    assert interview["error"] is None


def test_ask_interview_question_happy_path(isolated_db, fake_generate):
    interview_id = _set_up_interview_with_transcript()
    fake_generate.queue.append(AskInterviewAnswer(
        answer="The candidate closed a $1.2M ACV deal with a nine-month cycle across three stakeholders.",
        citations=[CompetencyEvidenceRef(segment_index=3)],
    ))

    resp = client.post(f"/interviews/{interview_id}/ask", json={"question": "What was their biggest deal?"})
    assert resp.status_code == 202, resp.text
    task = resp.json()
    finished = _wait_for_task("job-a", task["task_id"])
    assert finished["status"] == "succeeded", finished

    assert fake_generate.calls[0]["stage"] == "ask_interview_question"
    result = finished["result"]
    assert "1.2M" in result["answer"]
    assert len(result["citations"]) == 1
    assert result["citations"][0]["text"] == "A $1.2M ACV deal, nine-month cycle, three stakeholders."
    assert result["unable_to_answer"] is False


def test_ask_requires_a_question(isolated_db):
    interview_id = _set_up_interview_with_transcript()
    resp = client.post(f"/interviews/{interview_id}/ask", json={"question": "  "})
    assert resp.status_code == 400


def test_ask_requires_completed_transcript(isolated_db):
    db_storage.create_job("job-a", title="GTM Engineer")
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Rahul Sharma"})
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    resp = client.post(f"/interviews/{interview['id']}/ask", json={"question": "Anything?"})
    assert resp.status_code == 400


def test_unauthenticated_analyze_is_rejected(isolated_db):
    interview_id = _set_up_interview_with_transcript()
    client.cookies.clear()
    resp = client.post(f"/interviews/{interview_id}/analyze")
    assert resp.status_code == 401
