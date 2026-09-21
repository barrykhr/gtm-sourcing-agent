"""Interview Intelligence, Phase 1 (Notetaker): the full recording ->
transcription -> summary pipeline, exercised through the real HTTP
layer via TestClient, same pattern as test_outreach_automation.py.
transcription.transcribe and llm_client.generate are mocked (no network,
no real speech-to-text or model call); file storage uses moto's mocked
S3 (test_file_storage.py's pattern) so the real upload/download code
path runs end to end, not just the parts around it."""

import time

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from gtm_sourcing_agent import db, db_storage, file_storage, llm_client, transcription
from gtm_sourcing_agent.api import app
from gtm_sourcing_agent.models import InterviewSummaryResult

client = TestClient(app)
BUCKET = "talyn-interviews-test"


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
def configured_storage(monkeypatch):
    monkeypatch.setenv(file_storage.ENV_BUCKET, BUCKET)
    monkeypatch.setenv(file_storage.ENV_ACCESS_KEY_ID, "test-access-key")
    monkeypatch.setenv(file_storage.ENV_SECRET_ACCESS_KEY, "test-secret-key")
    monkeypatch.setenv(file_storage.ENV_REGION, "us-east-1")
    monkeypatch.delenv(file_storage.ENV_ENDPOINT_URL, raising=False)
    file_storage._client = None
    file_storage._client_env_key = None
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield
    file_storage._client = None
    file_storage._client_env_key = None


@pytest.fixture
def fake_transcribe(monkeypatch):
    calls = []

    def _fake(audio_bytes, content_type):
        calls.append({"audio_bytes": audio_bytes, "content_type": content_type})
        return [
            {"speaker": "recruiter", "text": "Tell me about your n8n experience.", "start_time": 0.0, "end_time": 3.2},
            {"speaker": "candidate", "text": "I built a production lead enrichment workflow.", "start_time": 3.5, "end_time": 8.0},
        ]

    monkeypatch.setattr(transcription, "transcribe", _fake)
    _fake.calls = calls
    return _fake


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


def _create_job_and_candidate(role_id: str = "job-a", candidate_id: str = "cand-1") -> None:
    db_storage.create_job(role_id, title="GTM Engineer")
    db_storage.merge_candidate(role_id, candidate_id, {"name": "Rahul Sharma"})


def test_create_interview_starts_in_recording_status(isolated_db):
    _create_job_and_candidate()
    resp = client.post(
        "/jobs/job-a/candidates/cand-1/interviews", json={"title": "Technical Screening"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "recording"
    assert body["title"] == "Technical Screening"
    assert body["recruiter_email"] == "recruiter@example.com"


def test_create_interview_404s_for_missing_candidate(isolated_db):
    db_storage.create_job("job-a", title="GTM Engineer")
    resp = client.post("/jobs/job-a/candidates/no-such-candidate/interviews", json={})
    assert resp.status_code == 400


def test_list_interviews_for_a_candidate(isolated_db):
    _create_job_and_candidate()
    client.post("/jobs/job-a/candidates/cand-1/interviews", json={"title": "Round 1"})
    client.post("/jobs/job-a/candidates/cand-1/interviews", json={"title": "Round 2"})
    resp = client.get("/jobs/job-a/candidates/cand-1/interviews")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_interview_404s_when_missing(isolated_db):
    resp = client.get("/interviews/no-such-interview")
    assert resp.status_code == 404


def test_complete_interview_sets_ended_at(isolated_db):
    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    resp = client.post(f"/interviews/{interview['id']}/complete")
    assert resp.status_code == 200
    assert resp.json()["ended_at"] is not None
    assert resp.json()["status"] == "processing"


def test_upload_recording_without_configured_storage_fails_honestly(isolated_db):
    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    resp = client.post(
        f"/interviews/{interview['id']}/recording",
        files={"file": ("rec.webm", b"fake audio bytes", "audio/webm")},
    )
    assert resp.status_code == 503
    updated = client.get(f"/interviews/{interview['id']}").json()
    assert updated["status"] == "failed"


def test_upload_recording_rejects_empty_file(isolated_db, configured_storage):
    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    resp = client.post(
        f"/interviews/{interview['id']}/recording",
        files={"file": ("rec.webm", b"", "audio/webm")},
    )
    assert resp.status_code == 400


def test_full_pipeline_happy_path(isolated_db, configured_storage, fake_transcribe, fake_generate):
    _create_job_and_candidate()
    interview = client.post(
        "/jobs/job-a/candidates/cand-1/interviews", json={"title": "Technical Screening"}
    ).json()

    fake_generate.queue.append(InterviewSummaryResult(
        overview="Candidate described building a production n8n workflow for lead enrichment.",
        key_experience=["Built a lead enrichment workflow using n8n"],
        technical_skills=["n8n"],
        examples_provided=["Production lead enrichment workflow"],
        areas_not_discussed=["Business impact / measurable results"],
        potential_followups=["What measurable impact did the automation have?"],
    ))

    upload_resp = client.post(
        f"/interviews/{interview['id']}/recording",
        files={"file": ("rec.webm", b"fake audio bytes", "audio/webm")},
    )
    assert upload_resp.status_code == 202, upload_resp.text
    task = upload_resp.json()
    finished = _wait_for_task("job-a", task["task_id"])
    assert finished["status"] == "succeeded", finished

    assert len(fake_transcribe.calls) == 1
    assert fake_transcribe.calls[0]["audio_bytes"] == b"fake audio bytes"

    final = client.get(f"/interviews/{interview['id']}").json()
    assert final["status"] == "completed"
    assert final["transcript_status"] == "completed"
    assert final["summary"]["overview"].startswith("Candidate described")
    assert "Business impact" in final["summary"]["areas_not_discussed"][0]

    transcript = client.get(f"/interviews/{interview['id']}/transcript").json()
    assert len(transcript) == 2
    assert transcript[0]["speaker"] == "recruiter"
    assert transcript[1]["speaker"] == "candidate"

    search_hits = client.get(f"/interviews/{interview['id']}/transcript?q=n8n").json()
    assert len(search_hits) == 1
    assert "n8n" in search_hits[0]["text"]


def test_pipeline_failure_when_transcription_errors(isolated_db, configured_storage, monkeypatch):
    def _fail(audio_bytes, content_type):
        raise transcription.TranscriptionError("provider rejected the request")

    monkeypatch.setattr(transcription, "transcribe", _fail)

    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    task = client.post(
        f"/interviews/{interview['id']}/recording",
        files={"file": ("rec.webm", b"fake audio bytes", "audio/webm")},
    ).json()
    finished = _wait_for_task("job-a", task["task_id"])
    assert finished["status"] == "failed"
    assert "provider rejected the request" in finished["error"]

    final = client.get(f"/interviews/{interview['id']}").json()
    assert final["status"] == "failed"
    assert final["transcript_status"] == "failed"


def test_retry_reprocesses_after_a_failure(isolated_db, configured_storage, fake_generate, monkeypatch):
    attempt = {"n": 0}

    def _flaky(audio_bytes, content_type):
        attempt["n"] += 1
        if attempt["n"] == 1:
            raise transcription.TranscriptionError("transient provider error")
        return [{"speaker": "recruiter", "text": "Hello.", "start_time": 0.0, "end_time": 1.0}]

    monkeypatch.setattr(transcription, "transcribe", _flaky)
    fake_generate.queue.append(InterviewSummaryResult(overview="Short call, just a greeting."))

    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    first_task = client.post(
        f"/interviews/{interview['id']}/recording",
        files={"file": ("rec.webm", b"fake audio bytes", "audio/webm")},
    ).json()
    assert _wait_for_task("job-a", first_task["task_id"])["status"] == "failed"

    retry_resp = client.post(f"/interviews/{interview['id']}/retry")
    assert retry_resp.status_code == 202, retry_resp.text
    retry_task = retry_resp.json()
    assert _wait_for_task("job-a", retry_task["task_id"])["status"] == "succeeded"

    final = client.get(f"/interviews/{interview['id']}").json()
    assert final["status"] == "completed"
    assert attempt["n"] == 2


def test_retry_without_a_recording_is_rejected(isolated_db):
    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    resp = client.post(f"/interviews/{interview['id']}/retry")
    assert resp.status_code == 400


def test_correct_segment_speaker(isolated_db):
    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    db_storage.save_transcript_segments(interview["id"], [
        {"speaker": "recruiter", "text": "Misattributed.", "start_time": 0.0, "end_time": 1.0},
    ])
    segment_id = client.get(f"/interviews/{interview['id']}/transcript").json()[0]["id"]

    resp = client.patch(
        f"/interviews/{interview['id']}/transcript/{segment_id}/speaker", json={"speaker": "candidate"}
    )
    assert resp.status_code == 200
    assert resp.json()["speaker"] == "candidate"


def test_correct_segment_speaker_rejects_invalid_value(isolated_db):
    _create_job_and_candidate()
    interview = client.post("/jobs/job-a/candidates/cand-1/interviews", json={}).json()
    db_storage.save_transcript_segments(interview["id"], [
        {"speaker": "recruiter", "text": "Hello.", "start_time": 0.0, "end_time": 1.0},
    ])
    segment_id = client.get(f"/interviews/{interview['id']}/transcript").json()[0]["id"]

    resp = client.patch(
        f"/interviews/{interview['id']}/transcript/{segment_id}/speaker", json={"speaker": "interviewer"}
    )
    assert resp.status_code == 400


def test_unauthenticated_request_is_rejected(isolated_db):
    client.cookies.clear()
    resp = client.get("/jobs/job-a/candidates/cand-1/interviews")
    assert resp.status_code == 401
