"""FastAPI service tests via TestClient — no network calls. Mirrors
tests/test_stages.py and tests/test_cli.py's mocking pattern: mock
llm_client.generate, isolate the DB per test, exercise the real HTTP
layer end to end.

Phase 4 (async + scale): every LLM-touching POST route now enqueues a
background task and returns 202 immediately instead of the stage result
— see task_queue.py. Tests call _wait_for_task() to poll the real task
status to completion (bounded, short timeout — the mocked
llm_client.generate below returns instantly, so the worker thread
finishes in well under a second) rather than asserting on the enqueue
response's body."""

import time

import pytest
from fastapi.testclient import TestClient

from gtm_sourcing_agent import db, llm_client
from gtm_sourcing_agent.api import app
from gtm_sourcing_agent.models import HiringManagerCalibration, JobDescription

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
    """Isolated DB *and* an authenticated session (Phase 7: every route
    except /health and /auth/* now requires one) — signing up and
    logging in here, once, means none of the ~40 test functions below
    needed to change when auth was added."""
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


def test_health(isolated_db):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_job_and_list(isolated_db):
    resp = client.post("/jobs", json={"title": "Enterprise AE — Acme", "role_family": "sales"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role_id"] == "enterprise-ae-acme"
    assert body["status"]["intake"] is False
    assert body["next_stage"] == "intake"

    jobs = client.get("/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Enterprise AE — Acme"


def test_create_job_dedupes_slug(isolated_db):
    first = client.post("/jobs", json={"title": "Enterprise AE"}).json()
    second = client.post("/jobs", json={"title": "Enterprise AE"}).json()
    assert first["role_id"] == "enterprise-ae"
    assert second["role_id"] == "enterprise-ae-2"


def test_get_job_404_when_missing(isolated_db):
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


def test_intake_requires_job_to_exist_first(isolated_db):
    resp = client.post("/jobs/no-such-job/intake", json={"jd_text": "some JD"})
    assert resp.status_code == 404


def test_calibrate_before_intake_surfaces_as_failed_task(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post("/jobs/ae-role/calibrate")
    assert resp.status_code == 202, resp.text

    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "failed"
    assert "job_description" in task["error"]


def test_intake_end_to_end_updates_job_status(isolated_db, fake_generate):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    fixed = JobDescription(
        raw_jd_text="x", company="Acme", role_title="AE", function="Sales",
        seniority="Senior", geography="US", role_objective="Own net-new logos.",
    )
    fake_generate.queue.append(fixed)

    resp = client.post("/jobs/ae-role/intake", json={"jd_text": "Enterprise AE role."})
    assert resp.status_code == 202, resp.text

    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "succeeded", task
    assert task["result"]["company"] == "Acme"

    job = client.get("/jobs/ae-role").json()
    assert job["status"]["intake"] is True
    assert job["next_stage"] == "calibration"
    assert job["state"]["job_description"]["company"] == "Acme"


def test_full_job_and_calibration_chain(isolated_db, fake_generate):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    fake_generate.queue.append(
        JobDescription(
            raw_jd_text="x", company="Acme", role_title="AE", function="Sales",
            seniority="Senior", geography="US", role_objective="x",
        )
    )
    intake_resp = client.post("/jobs/ae-role/intake", json={"jd_text": "JD text"})
    _wait_for_task("ae-role", intake_resp.json()["task_id"])

    fake_generate.queue.append(HiringManagerCalibration(must_have_criteria=["quota history"]))
    resp = client.post("/jobs/ae-role/calibrate")
    assert resp.status_code == 202

    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "succeeded", task
    assert task["result"]["must_have_criteria"] == ["quota history"]


def test_candidate_add_prioritize_requires_icp_first(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post(
        "/jobs/ae-role/candidates",
        json={"source_text": "resume text", "role_family": "sales"},
    )
    assert resp.status_code == 202, resp.text

    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "failed"
    assert "icp" in task["error"]


def test_candidate_list_empty_then_populated(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})

    assert client.get("/jobs/ae-role/candidates").json() == []

    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    resp = client.post(
        "/jobs/ae-role/candidates",
        json={"source_text": "resume text", "role_family": "sales"},
    )
    assert resp.status_code == 202

    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "succeeded", task

    listed = client.get("/jobs/ae-role/candidates").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Jane Doe"


def test_upload_candidate_extracts_text_and_enqueues(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))

    resp = client.post(
        "/jobs/ae-role/candidates/upload",
        files={"file": ("resume.txt", b"Jane Doe resume text", "text/plain")},
        data={"role_family": "sales"},
    )
    assert resp.status_code == 202, resp.text
    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "succeeded", task
    assert task["result"]["name"] == "Jane Doe"
    assert fake_generate.calls[-1]["prompt"].find("Jane Doe resume text") != -1


def test_upload_candidate_rejects_unsupported_file(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post(
        "/jobs/ae-role/candidates/upload",
        files={"file": ("resume.rtf", b"whatever", "application/rtf")},
        data={"role_family": "sales"},
    )
    assert resp.status_code == 400
    assert "unsupported file type" in resp.json()["detail"]


def test_upload_jd_extracts_text_without_running_analysis(isolated_db):
    # Extraction only — this route never calls the LLM or writes
    # job_description; the recruiter reviews/edits the returned text in
    # the same box the existing paste flow already feeds into "Analyse JD".
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})

    resp = client.post(
        "/jobs/ae-role/intake/upload",
        files={"file": ("jd.txt", b"Enterprise AE, own net-new logos.", "text/plain")},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "Enterprise AE, own net-new logos."
    assert "job_description" not in client.get("/jobs/ae-role").json()["state"]


def test_upload_jd_rejects_unsupported_file(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post(
        "/jobs/ae-role/intake/upload",
        files={"file": ("jd.rtf", b"whatever", "application/rtf")},
    )
    assert resp.status_code == 400
    assert "unsupported file type" in resp.json()["detail"]


def test_update_job_description_corrects_extracted_fields(isolated_db, fake_generate):
    from gtm_sourcing_agent.models import JobDescription

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    fake_generate.queue.append(
        JobDescription(raw_jd_text="x", company="Acme", role_title="AE", function="Sales",
                       seniority="Mid", geography="US", role_objective="Own net-new logos.")
    )
    resp = client.post("/jobs/ae-role/intake", json={"jd_text": "Enterprise AE."})
    _wait_for_task("ae-role", resp.json()["task_id"])

    resp = client.patch(
        "/jobs/ae-role/job-description", json={"seniority": "Senior", "compensation": "$150k OTE"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["seniority"] == "Senior"
    assert resp.json()["compensation"] == "$150k OTE"
    assert resp.json()["role_title"] == "AE"


def test_update_job_description_requires_jd_first(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/job-description", json={"seniority": "Senior"})
    assert resp.status_code == 400


def test_prioritize_screen_outreach_are_async_tasks(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization, OutreachSequence, ScreeningQuestionSet

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "job_description", {"company": "Acme", "role_title": "AE"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section("ae-role", "calibration", {"must_have_criteria": ["quota history"]})

    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post(
        "/jobs/ae-role/candidates", json={"source_text": "resume text", "role_family": "sales"}
    )
    add_task = _wait_for_task("ae-role", add_resp.json()["task_id"])
    candidate_id = add_task["result"]["candidate_id"]

    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    assert p_resp.status_code == 202, p_resp.text
    p_task = _wait_for_task("ae-role", p_resp.json()["task_id"])
    assert p_task["status"] == "succeeded", p_task
    assert p_task["result"]["tier"] == "A"

    fake_generate.queue.append(ScreeningQuestionSet(candidate_id=candidate_id))
    s_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/screen")
    s_task = _wait_for_task("ae-role", s_resp.json()["task_id"])
    assert s_task["status"] == "succeeded", s_task["error"]

    fake_generate.queue.append(OutreachSequence(candidate_id=candidate_id))
    o_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach")
    o_task = _wait_for_task("ae-role", o_resp.json()["task_id"])
    assert o_task["status"] == "succeeded", o_task["error"]

    all_tasks = client.get("/jobs/ae-role/tasks").json()
    assert {t["kind"] for t in all_tasks} == {"add_candidate", "prioritize", "screen", "outreach"}
    assert all(t["status"] == "succeeded" for t in all_tasks)


def test_task_404_when_missing_or_wrong_job(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    client.post("/jobs", json={"title": "Other Role", "role_id": "other-role"})
    assert client.get("/jobs/ae-role/tasks/task-doesnotexist").status_code == 404

    resp = client.post("/jobs/ae-role/calibrate")
    task_id = resp.json()["task_id"]
    # right task id, wrong job in the URL — must not leak across jobs
    assert client.get(f"/jobs/other-role/tasks/{task_id}").status_code == 404
    _wait_for_task("ae-role", task_id)  # drain it so it doesn't run past this test


def test_funnel_update_and_report(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post("/jobs/ae-role/funnel/cand-1", json={"stage": "contacted"})
    assert resp.status_code == 200
    assert resp.json()["current_stage"] == "CONTACTED"

    report = client.get("/jobs/ae-role/funnel/report").json()
    assert report["counts_by_stage"]["CONTACTED"] == 1


def test_funnel_update_records_note(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post(
        "/jobs/ae-role/funnel/cand-1", json={"stage": "recruiter_screen", "note": "HM loved the resume"}
    )
    assert resp.status_code == 200
    assert resp.json()["stage_history"][-1]["note"] == "HM loved the resume"


def test_mark_outreach_sent_requires_draft_then_advances_pipeline(isolated_db, fake_generate):
    from gtm_sourcing_agent.models import Candidate, OutreachSequence

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})

    # no draft yet — 400, not a 500
    resp = client.post("/jobs/ae-role/candidates/cand-1/outreach/mark-sent")
    assert resp.status_code == 400
    assert "no outreach draft" in resp.json()["detail"]

    from gtm_sourcing_agent import db_storage

    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section("ae-role", "job_description", {"company": "Acme"})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    add_task = _wait_for_task("ae-role", add_resp.json()["task_id"])
    candidate_id = add_task["result"]["candidate_id"]

    fake_generate.queue.append(OutreachSequence(candidate_id=candidate_id, email="Hi Jane"))
    o_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach")
    _wait_for_task("ae-role", o_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/outreach/mark-sent")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["funnel_stage"] == "CONTACTED"
    assert body["sent_at"]


def test_recruiter_decision_requires_prioritization_then_persists(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("ae-role", add_resp.json()["task_id"])["result"]["candidate_id"]

    # no tier yet — 400, not a 500
    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/decision", json={"decision": "pursue"})
    assert resp.status_code == 400
    assert "not been prioritized" in resp.json()["detail"]

    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    _wait_for_task("ae-role", p_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/decision", json={"decision": "pursue"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"candidate_id": candidate_id, "recruiter_decision": "pursue"}

    listed = client.get("/jobs/ae-role/candidates").json()
    assert listed[0]["prioritization"]["recruiter_decision"] == "pursue"


def test_placement_route_requires_prioritization_then_persists(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("ae-role", add_resp.json()["task_id"])["result"]["candidate_id"]

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/placement", json={"placed": True, "fee": 15000.0})
    assert resp.status_code == 400
    assert "not been prioritized" in resp.json()["detail"]

    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    _wait_for_task("ae-role", p_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/placement", json={"placed": True, "fee": 15000.0})
    assert resp.status_code == 200, resp.text
    assert resp.json()["placed"] is True
    assert resp.json()["placement_fee"] == 15000.0

    listed = client.get("/jobs/ae-role/candidates").json()
    assert listed[0]["prioritization"]["placed"] is True
    assert listed[0]["prioritization"]["placement_fee"] == 15000.0

    overview = client.get("/analytics/overview").json()
    assert overview["total_placements"] == 1
    assert overview["total_placement_fees"] == 15000.0


def test_analytics_overview_route(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("ae-role", add_resp.json()["task_id"])["result"]["candidate_id"]
    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    _wait_for_task("ae-role", p_resp.json()["task_id"])

    overview = client.get("/analytics/overview").json()
    assert overview["total_jobs"] == 1
    assert overview["total_candidates"] == 1
    assert overview["tier_distribution"]["A"] == 1
    assert overview["decisions_pending"] == 1


def _ten_question_set(first_question: str = "Walk me through a deal."):
    from gtm_sourcing_agent.models import RoleInterviewQuestions
    from gtm_sourcing_agent.models.interview_questions import InterviewQuestion

    return RoleInterviewQuestions(
        core_questions=[
            InterviewQuestion(question=first_question, why_it_matters="validates quota"),
            InterviewQuestion(question="q2", why_it_matters="w2"),
            InterviewQuestion(question="q3", why_it_matters="w3"),
            InterviewQuestion(question="q4", why_it_matters="w4"),
        ],
        role_specific_questions=[
            InterviewQuestion(question="q5", why_it_matters="w5"),
            InterviewQuestion(question="q6", why_it_matters="w6"),
            InterviewQuestion(question="q7", why_it_matters="w7"),
        ],
        red_flag_questions=[
            InterviewQuestion(question="q8", why_it_matters="w8"),
            InterviewQuestion(question="q9", why_it_matters="w9"),
            InterviewQuestion(question="q10", why_it_matters="w10"),
        ],
    )


def test_interview_questions_route(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section("ae-role", "calibration", {"red_flags": ["job-hopping"]})

    fake_generate.queue.append(_ten_question_set())
    resp = client.post("/jobs/ae-role/interview-questions")
    assert resp.status_code == 202, resp.text
    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "succeeded", task
    # The task result and the job state are both the full generation
    # history (append-only), not a single flat question set.
    assert len(task["result"]["generations"]) == 1
    assert task["result"]["generations"][0]["core_questions"][0]["question"] == "Walk me through a deal."

    job = client.get("/jobs/ae-role").json()
    history = job["state"]["interview_questions"]
    assert len(history["generations"]) == 1
    assert history["generations"][0]["core_questions"][0]["question"] == "Walk me through a deal."

    # Regenerating appends a second generation instead of overwriting the first.
    fake_generate.queue.append(_ten_question_set(first_question="Walk me through a different deal."))
    resp2 = client.post("/jobs/ae-role/interview-questions")
    _wait_for_task("ae-role", resp2.json()["task_id"])
    job = client.get("/jobs/ae-role").json()
    history = job["state"]["interview_questions"]
    assert len(history["generations"]) == 2
    assert history["generations"][0]["core_questions"][0]["question"] == "Walk me through a deal."
    assert history["generations"][1]["core_questions"][0]["question"] == "Walk me through a different deal."


def test_team_usage_route(isolated_db, fake_generate):
    from gtm_sourcing_agent.models import Candidate

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})

    usage = client.get("/team/usage").json()
    assert usage["total_users"] == 1
    recruiter = usage["recruiters"][0]
    assert recruiter["email"] == "recruiter@example.com"
    assert recruiter["jobs_owned"] == 1
    assert recruiter["total_actions"] >= 1


def test_team_velocity_route(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("ae-role", add_resp.json()["task_id"])["result"]["candidate_id"]
    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    _wait_for_task("ae-role", p_resp.json()["task_id"])

    velocity = client.get("/team/velocity").json()
    role = next(r for r in velocity["by_role"] if r["role_id"] == "ae-role")
    assert role["conversion"]["sourced"] == 1
    assert role["conversion"]["tiered_a"] == 1
    recruiter = next(r for r in velocity["by_recruiter"] if r["email"] == "recruiter@example.com")
    assert recruiter["conversion"]["sourced"] == 1


def test_funnel_update_rejects_unknown_stage(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post("/jobs/ae-role/funnel/cand-1", json={"stage": "not_a_stage"})
    assert resp.status_code == 400


def test_funnel_forecast_labels_assumption_source(isolated_db):
    resp = client.post("/funnel/forecast", json={"hires": 5, "weeks": 12})
    assert resp.status_code == 200
    body = resp.json()
    assert body["hires_needed"] == 5
    assert body["assumptions"]["source"] == "market_default"


def test_funnel_forecast_rejects_invalid_source(isolated_db):
    resp = client.post("/funnel/forecast", json={"hires": 5, "weeks": 12, "source": "guess"})
    assert resp.status_code == 400


def test_global_candidates_roster_dedupes_across_jobs(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate

    client.post("/jobs", json={"title": "Job A", "role_id": "job-a"})
    client.post("/jobs", json={"title": "Job B", "role_id": "job-b"})
    db_storage.merge_section("job-a", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section("job-b", "icp", {"must_have": ["SaaS"]})

    same_url = "https://linkedin.com/in/janedoe"
    fake_generate.queue.append(Candidate(candidate_id="", name="Jane Doe", source_url=same_url))
    r1 = client.post(
        "/jobs/job-a/candidates",
        json={"source_text": "resume", "role_family": "sales", "source_url": same_url},
    )
    assert r1.status_code == 202, r1.text
    t1 = _wait_for_task("job-a", r1.json()["task_id"])
    assert t1["status"] == "succeeded", t1

    fake_generate.queue.append(Candidate(candidate_id="", name="Jane Doe", source_url=same_url))
    r2 = client.post(
        "/jobs/job-b/candidates",
        json={"source_text": "resume", "role_family": "sales", "source_url": same_url},
    )
    assert r2.status_code == 202, r2.text
    t2 = _wait_for_task("job-b", r2.json()["task_id"])
    assert t2["status"] == "succeeded", t2

    roster = client.get("/candidates").json()
    assert len(roster) == 1
    assert len(roster[0]["evaluations"]) == 2
    assert {e["role_id"] for e in roster[0]["evaluations"]} == {"job-a", "job-b"}

    detail = client.get(f"/candidates/{roster[0]['candidate_id']}").json()
    assert detail["name"] == "Jane Doe"
    job_titles = {e["role_id"]: e["job_title"] for e in detail["evaluations"]}
    assert job_titles == {"job-a": "Job A", "job-b": "Job B"}


def test_global_candidate_detail_404_when_missing(isolated_db):
    resp = client.get("/candidates/cand-doesnotexist")
    assert resp.status_code == 404


def test_export_candidates_csv(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate(
        "ae-role", "cand-1", {"name": "Jane Doe", "current_title": "AE", "current_company": "Acme"}
    )
    db_storage.merge_prioritization(
        "ae-role", "cand-1", {"candidate_id": "cand-1", "tier": "A", "recruiter_decision": "pursue"}
    )

    resp = client.get("/jobs/ae-role/candidates/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="ae-role-candidates.csv"' in resp.headers["content-disposition"]
    rows = resp.text.strip().splitlines()
    assert rows[0] == "Name,Current title,Current company,Tier,Recruiter decision,Pipeline stage,Outreach drafted,Source URL"
    assert rows[1] == "Jane Doe,AE,Acme,A,pursue,IDENTIFIED,no,"


def test_export_candidates_csv_404_for_missing_job(isolated_db):
    resp = client.get("/jobs/does-not-exist/candidates/export.csv")
    assert resp.status_code == 404


def test_export_candidates_json(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe", "source_url": "https://x.com/jane"})
    db_storage.merge_prioritization("ae-role", "cand-1", {"candidate_id": "cand-1", "tier": "A"})

    resp = client.get("/jobs/ae-role/candidates/export.json")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role_id"] == "ae-role"
    assert len(body["candidates"]) == 1
    c = body["candidates"][0]
    assert c["name"] == "Jane Doe"
    assert c["prioritization"]["tier"] == "A"
    assert c["pipeline_stage"] == "IDENTIFIED"
    assert c["outreach_drafted"] is False


def test_export_candidates_json_404_for_missing_job(isolated_db):
    resp = client.get("/jobs/does-not-exist/candidates/export.json")
    assert resp.status_code == 404


# ── role templates (Phase 8) ────────────────────────────────────────────


def test_clone_job_copies_hiring_strategy(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "Acme AE", "role_id": "acme-ae", "role_family": "sales"})
    db_storage.merge_section("acme-ae", "job_description", {"company": "Acme"})
    db_storage.merge_section("acme-ae", "icp", {"must_have": ["SaaS"]})

    resp = client.post("/jobs/acme-ae/clone", json={"title": "Beta AE"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role_id"] == "beta-ae"

    cloned = client.get("/jobs/beta-ae").json()
    assert cloned["role_family"] == "sales"
    assert cloned["state"]["job_description"] == {"company": "Acme"}
    assert cloned["state"]["icp"] == {"must_have": ["SaaS"]}
    assert cloned["state"]["candidates"] == {}


def test_clone_job_404_for_missing_source(isolated_db):
    resp = client.post("/jobs/does-not-exist/clone", json={"title": "Beta AE"})
    assert resp.status_code == 400  # ValueError -> 400 via _run_stage
    assert "not found" in resp.json()["detail"]


# ── rubric tuning (Phase 8) ─────────────────────────────────────────────


def test_update_icp_criteria(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"], "nice_to_have": ["enterprise"]})

    resp = client.patch("/jobs/ae-role/icp/criteria", json={"must_have": ["SaaS", "$1M+ quota"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["must_have"] == ["SaaS", "$1M+ quota"]
    assert resp.json()["nice_to_have"] == ["enterprise"]  # untouched

    job = client.get("/jobs/ae-role").json()
    assert job["state"]["icp"]["must_have"] == ["SaaS", "$1M+ quota"]


def test_update_icp_criteria_requires_existing_icp(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/icp/criteria", json={"must_have": ["SaaS"]})
    assert resp.status_code == 400


# ── activity log (Phase 8) ──────────────────────────────────────────────


def test_activity_log_records_job_creation_and_decision(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("ae-role", add_resp.json()["task_id"])["result"]["candidate_id"]
    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    _wait_for_task("ae-role", p_resp.json()["task_id"])
    client.post(f"/jobs/ae-role/candidates/{candidate_id}/decision", json={"decision": "pass for now"})

    entries = client.get("/jobs/ae-role/activity").json()
    actions = [e["action"] for e in entries]
    assert "created job" in actions
    assert "added candidate (pasted text)" in actions
    assert "requested prioritization" in actions
    assert "set decision: pass for now" in actions
    assert all(e["user_email"] == "recruiter@example.com" for e in entries if e["action"] != "webhook delivery")


def test_activity_log_404_for_missing_job(isolated_db):
    resp = client.get("/jobs/does-not-exist/activity")
    assert resp.status_code == 404


# ── integrations / webhooks (Phase 8) ───────────────────────────────────


def test_webhook_config_round_trips(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    assert client.get("/jobs/ae-role/integrations").json() == {"webhook_url": ""}

    resp = client.post("/jobs/ae-role/integrations/webhook", json={"webhook_url": "https://example.com/hook"})
    assert resp.status_code == 200, resp.text
    assert client.get("/jobs/ae-role/integrations").json() == {"webhook_url": "https://example.com/hook"}


def test_webhook_test_requires_configured_url(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post("/jobs/ae-role/integrations/webhook/test")
    assert resp.status_code == 400
    assert "no webhook URL configured" in resp.json()["detail"]


def test_webhook_test_delivers_via_mocked_transport(isolated_db, monkeypatch):
    from gtm_sourcing_agent import webhooks

    class _FakeResponse:
        status_code = 200

    captured = {}

    def _fake_request(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return _FakeResponse()

    monkeypatch.setattr(webhooks, "send_webhook_request", _fake_request)

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    client.post("/jobs/ae-role/integrations/webhook", json={"webhook_url": "https://example.com/hook"})
    resp = client.post("/jobs/ae-role/integrations/webhook/test")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "detail": "delivered (HTTP 200)"}
    assert captured["url"] == "https://example.com/hook"
    assert captured["payload"]["event"] == "webhook.test"


def test_decision_pursue_fires_configured_webhook(isolated_db, fake_generate, monkeypatch):
    from gtm_sourcing_agent import webhooks
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    class _FakeResponse:
        status_code = 200

    captured = {}

    def _fake_request(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return _FakeResponse()

    monkeypatch.setattr(webhooks, "send_webhook_request", _fake_request)

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    from gtm_sourcing_agent import db_storage
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    client.post("/jobs/ae-role/integrations/webhook", json={"webhook_url": "https://example.com/hook"})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("ae-role", add_resp.json()["task_id"])["result"]["candidate_id"]
    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    _wait_for_task("ae-role", p_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/decision", json={"decision": "pursue"})
    assert resp.status_code == 200, resp.text
    assert captured["payload"]["event"] == "candidate.decision.pursue"
    assert captured["payload"]["candidate_id"] == candidate_id


def test_decision_not_pursue_does_not_fire_webhook(isolated_db, fake_generate, monkeypatch):
    from gtm_sourcing_agent import webhooks
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    called = {"count": 0}

    def _fake_request(url, payload):
        called["count"] += 1
        raise AssertionError("should not be called for a non-pursue decision")

    monkeypatch.setattr(webhooks, "send_webhook_request", _fake_request)

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    from gtm_sourcing_agent import db_storage
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    client.post("/jobs/ae-role/integrations/webhook", json={"webhook_url": "https://example.com/hook"})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("ae-role", add_resp.json()["task_id"])["result"]["candidate_id"]
    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/prioritize")
    _wait_for_task("ae-role", p_resp.json()["task_id"])

    resp = client.post(f"/jobs/ae-role/candidates/{candidate_id}/decision", json={"decision": "pass for now"})
    assert resp.status_code == 200, resp.text
    assert called["count"] == 0


# ── job lifecycle (Phase 10) ────────────────────────────────────────────


def test_create_job_defaults_owner_to_creator(isolated_db):
    resp = client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_email"] == "recruiter@example.com"
    assert resp.json()["lifecycle_status"] == "OPEN"


def test_set_job_lifecycle(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/lifecycle", json={"lifecycle_status": "FILLED"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "FILLED"

    job = client.get("/jobs/ae-role").json()
    assert job["lifecycle_status"] == "FILLED"


def test_set_job_lifecycle_rejects_unknown_status(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/lifecycle", json={"lifecycle_status": "NOT_A_STATUS"})
    assert resp.status_code == 400
    assert "not a valid job status" in resp.json()["detail"]


def test_set_job_lifecycle_404_for_missing_job(isolated_db):
    resp = client.patch("/jobs/does-not-exist/lifecycle", json={"lifecycle_status": "FILLED"})
    assert resp.status_code == 400  # ValueError -> 400 via _run_stage


# ── job ownership (Phase 10) ────────────────────────────────────────────


def test_set_job_owner_reassigns(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/owner", json={"owner_email": "teammate@example.com"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_email"] == "teammate@example.com"


def test_set_job_owner_can_clear(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/owner", json={"owner_email": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_email"] is None


def test_clone_job_inherits_cloning_recruiter_as_owner(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    client.patch("/jobs/ae-role/owner", json={"owner_email": "someone-else@example.com"})
    resp = client.post("/jobs/ae-role/clone", json={"title": "AE Role (clone)"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_email"] == "recruiter@example.com"


# ── multi-recruiter assignment ──────────────────────────────────────────


def test_creating_a_job_seeds_the_creator_as_primary_recruiter(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.get("/jobs/ae-role/recruiters")
    assert resp.status_code == 200, resp.text
    assert resp.json() == [{"email": "recruiter@example.com", "assignment": "primary", "added_at": resp.json()[0]["added_at"]}]


def test_add_and_list_contributors(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post("/jobs/ae-role/recruiters", json={"email": "contributor@example.com"})
    assert resp.status_code == 200, resp.text
    emails = [r["email"] for r in resp.json()]
    assert emails == ["recruiter@example.com", "contributor@example.com"]
    assert resp.json()[1]["assignment"] == "contributor"


def test_cannot_add_the_same_recruiter_twice(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    client.post("/jobs/ae-role/recruiters", json={"email": "contributor@example.com"})
    resp = client.post("/jobs/ae-role/recruiters", json={"email": "contributor@example.com"})
    assert resp.status_code == 400
    assert "already assigned" in resp.json()["detail"]


def test_cannot_add_the_primary_as_a_contributor(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post("/jobs/ae-role/recruiters", json={"email": "recruiter@example.com"})
    assert resp.status_code == 400
    assert "already assigned" in resp.json()["detail"]


def test_remove_contributor(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    client.post("/jobs/ae-role/recruiters", json={"email": "contributor@example.com"})
    resp = client.delete("/jobs/ae-role/recruiters/contributor@example.com")
    assert resp.status_code == 200, resp.text
    assert [r["email"] for r in resp.json()] == ["recruiter@example.com"]


def test_cannot_remove_the_primary_recruiter_directly(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.delete("/jobs/ae-role/recruiters/recruiter@example.com")
    assert resp.status_code == 400
    assert "primary" in resp.json()["detail"]


def test_reassigning_owner_updates_the_primary_recruiter(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    client.patch("/jobs/ae-role/owner", json={"owner_email": "teammate@example.com"})
    resp = client.get("/jobs/ae-role/recruiters")
    assert [r["email"] for r in resp.json() if r["assignment"] == "primary"] == ["teammate@example.com"]
    # the old primary isn't left behind as an orphaned row of any kind
    assert "recruiter@example.com" not in [r["email"] for r in resp.json()]


def test_promoting_a_contributor_to_primary_removes_the_contributor_row(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    client.post("/jobs/ae-role/recruiters", json={"email": "contributor@example.com"})
    client.patch("/jobs/ae-role/owner", json={"owner_email": "contributor@example.com"})
    resp = client.get("/jobs/ae-role/recruiters").json()
    assert len(resp) == 1
    assert resp[0] == {"email": "contributor@example.com", "assignment": "primary", "added_at": resp[0]["added_at"]}


# ── client tagging (Batch B) ────────────────────────────────────────────


def test_create_job_with_client_name(isolated_db):
    resp = client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role", "client_name": "Acme Robotics"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_name"] == "Acme Robotics"


def test_set_job_client_reassigns(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/client", json={"client_name": "Globex Corp"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_name"] == "Globex Corp"


def test_set_job_client_can_clear(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role", "client_name": "Acme Robotics"})
    resp = client.patch("/jobs/ae-role/client", json={"client_name": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_name"] is None


# ── revenue intelligence (8.33% model) ──────────────────────────────────


def test_create_job_with_role_value_computes_expected_revenue(isolated_db):
    resp = client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role", "role_value": 4000000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role_value"] == 4000000
    # 40,00,000 * 8.33% = 3,33,200 — the exact worked example from the brief
    assert resp.json()["expected_revenue"] == 333200.0


def test_job_with_no_role_value_has_no_expected_revenue(isolated_db):
    resp = client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    assert resp.json()["role_value"] is None
    assert resp.json()["expected_revenue"] is None


def test_set_job_value_reassigns_and_recomputes(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/value", json={"role_value": 2000000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role_value"] == 2000000
    assert resp.json()["expected_revenue"] == 166600.0


def test_set_job_value_rejects_negative(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/value", json={"role_value": -100})
    assert resp.status_code == 400


def test_revenue_overview_aggregates_expected_and_realized(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate, CandidatePrioritization

    client.post("/jobs", json={"title": "Priced open role", "role_id": "priced", "role_value": 1000000})
    client.post("/jobs", json={"title": "Unpriced open role", "role_id": "unpriced"})
    client.post("/jobs", json={"title": "Filled role", "role_id": "filled", "role_value": 5000000})
    client.patch("/jobs/filled/lifecycle", json={"lifecycle_status": "FILLED"})

    overview = client.get("/revenue/overview").json()
    assert overview["open_roles"] == 2  # "filled" no longer counts as open
    assert overview["open_roles_priced"] == 1  # only "priced" is open AND has a role_value
    assert overview["expected_revenue"] == 83300.0  # 10,00,000 * 8.33%
    assert overview["pipeline_revenue"] == 0.0  # no candidates sourced anywhere yet
    assert overview["margin_percentage"] == 8.33

    # Add a candidate to the priced role — now it counts as "in pipeline"
    db_storage.merge_section("priced", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="cand-1", name="Jane Doe"))
    add_resp = client.post("/jobs/priced/candidates", json={"source_text": "resume", "role_family": "sales"})
    candidate_id = _wait_for_task("priced", add_resp.json()["task_id"])["result"]["candidate_id"]
    overview = client.get("/revenue/overview").json()
    assert overview["pipeline_revenue"] == 83300.0

    # A real placement fee on the (now-filled, so no longer "open") role
    # shows up as realized revenue, independent of the 8.33% estimate.
    fake_generate.queue.append(CandidatePrioritization(candidate_id=candidate_id, tier="A"))
    p_resp = client.post(f"/jobs/priced/candidates/{candidate_id}/prioritize")
    _wait_for_task("priced", p_resp.json()["task_id"])
    client.post(f"/jobs/priced/candidates/{candidate_id}/placement", json={"placed": True, "fee": 400000.0})
    overview = client.get("/revenue/overview").json()
    assert overview["realized_revenue"] == 400000.0


def test_recruiter_revenue_credits_primary_for_their_role(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role", "role_value": 1000000})
    resp = client.get("/revenue/by-recruiter").json()
    assert len(resp) == 1
    assert resp[0]["email"] == "recruiter@example.com"
    assert resp[0]["roles"] == 1
    assert resp[0]["expected_revenue"] == 83300.0
    assert resp[0]["total_revenue"] == 83300.0
    assert resp[0]["share_of_firm"] == 100.0


def test_recruiter_revenue_credits_both_primary_and_contributor_fully(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role", "role_value": 1000000})
    client.post("/jobs/ae-role/recruiters", json={"email": "contributor@example.com"})
    resp = client.get("/revenue/by-recruiter").json()
    by_email = {r["email"]: r for r in resp}
    assert by_email["recruiter@example.com"]["expected_revenue"] == 83300.0
    assert by_email["contributor@example.com"]["expected_revenue"] == 83300.0
    # both are credited in full — not a 50/50 split — so both share 100%
    # of the firm total, which is real revenue.expected_revenue(1000000)
    assert by_email["recruiter@example.com"]["share_of_firm"] == 100.0
    assert by_email["contributor@example.com"]["share_of_firm"] == 100.0


def test_integrations_status_reports_not_connected_honestly(isolated_db, monkeypatch):
    # No real OAuth/telephony credentials exist in test — must never
    # report "connected", regardless of env vars.
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALENDLY_CLIENT_ID", raising=False)
    monkeypatch.delenv("TELEPHONY_PROVIDER_API_KEY", raising=False)

    resp = client.get("/integrations/status")
    assert resp.status_code == 200, resp.text
    statuses = resp.json()
    providers = {s["provider"] for s in statuses}
    assert providers == {"google_workspace", "calendly", "telephony"}
    for s in statuses:
        assert s["status"] == "not_connected"
        assert s["environment_configured"] is False

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "fake-client-id-for-test")
    resp2 = client.get("/integrations/status")
    google = next(s for s in resp2.json() if s["provider"] == "google_workspace")
    # Even with credentials present, there is no OAuth callback flow —
    # still must never claim "connected".
    assert google["status"] == "not_connected"
    assert google["environment_configured"] is True


def test_recruiter_revenue_with_no_priced_roles_is_empty_or_zeroed(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.get("/revenue/by-recruiter").json()
    assert resp[0]["expected_revenue"] == 0.0
    assert resp[0]["share_of_firm"] == 0.0


# ── client-facing share links (Batch B) ─────────────────────────────────


def test_share_link_lifecycle_and_public_route(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role", "client_name": "Acme Robotics"})

    gen = client.post("/jobs/ae-role/share-link")
    assert gen.status_code == 200, gen.text
    token = gen.json()["share_token"]
    assert token

    # public route needs no auth — a fresh client with no cookies
    from fastapi.testclient import TestClient as _TestClient
    from gtm_sourcing_agent.api import app as _app
    anon = _TestClient(_app)
    public = anon.get(f"/public/roles/{token}")
    assert public.status_code == 200, public.text
    assert public.json()["title"] == "AE Role"
    assert public.json()["client_name"] == "Acme Robotics"

    revoke = client.delete("/jobs/ae-role/share-link")
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["share_token"] is None

    after_revoke = anon.get(f"/public/roles/{token}")
    assert after_revoke.status_code == 404


def test_client_sharing_exposes_only_the_safe_fields_of_shared_candidates(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(
        candidate_id="cand-1", name="Jane Doe", current_title="AE", current_company="Acme",
        current_ctc="$200k", email="jane@example.com", phone="+1 555-0100",
        concerns=["Limited enterprise exposure"],
    ))
    resp = client.post("/jobs/ae-role/candidates", json={"source_text": "resume", "role_family": "sales"})
    _wait_for_task("ae-role", resp.json()["task_id"])
    # A second, never-shared candidate to prove it stays excluded.
    fake_generate.queue.append(Candidate(candidate_id="cand-2", name="Not Shared"))
    resp2 = client.post("/jobs/ae-role/candidates", json={"source_text": "resume2", "role_family": "sales"})
    _wait_for_task("ae-role", resp2.json()["task_id"])

    token = client.post("/jobs/ae-role/share-link").json()["share_token"]

    share = client.patch("/jobs/ae-role/candidates/cand-1/share", json={"visible": True})
    assert share.status_code == 200, share.text
    assert share.json() == {"candidate_id": "cand-1", "client_visible": True}

    from fastapi.testclient import TestClient as _TestClient
    from gtm_sourcing_agent.api import app as _app
    anon = _TestClient(_app)
    public = anon.get(f"/public/roles/{token}").json()

    shared = public["shared_candidates"]
    assert len(shared) == 1
    assert shared[0]["name"] == "Jane Doe"
    assert shared[0]["current_title"] == "AE"
    # Never on a client-facing link, shared or not.
    for forbidden in ("current_ctc", "email", "phone", "concerns", "note", "recruiter_decision"):
        assert forbidden not in shared[0]

    # Unsharing removes it again.
    client.patch("/jobs/ae-role/candidates/cand-1/share", json={"visible": False})
    public_after = anon.get(f"/public/roles/{token}").json()
    assert public_after["shared_candidates"] == []


def test_sharing_an_unknown_candidate_404s(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/candidates/nope/share", json={"visible": True})
    assert resp.status_code == 400


def test_bulk_import_candidates_from_csv(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import Candidate

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})

    csv_content = (
        "name,notes,source_url\n"
        "Jane,Enterprise AE with 5 years experience,https://linkedin.com/in/jane\n"
        "Marcus,Senior AE closing $200k deals,\n"
        ",,\n"  # empty row — should be skipped
    ).encode("utf-8")

    fake_generate.queue.append(Candidate(candidate_id="", name="Jane Doe"))
    fake_generate.queue.append(Candidate(candidate_id="", name="Marcus Lee"))

    resp = client.post(
        "/jobs/ae-role/candidates/bulk-import",
        files={"file": ("candidates.csv", csv_content, "text/csv")},
        data={"role_family": "sales"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["queued"] == 2
    assert body["skipped_empty_rows"] == 1
    assert len(body["task_ids"]) == 2

    for task_id in body["task_ids"]:
        task = _wait_for_task("ae-role", task_id)
        assert task["status"] == "succeeded", task

    candidates = client.get("/jobs/ae-role/candidates").json()
    assert len(candidates) == 2


def test_bulk_import_rejects_csv_without_notes_column(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    csv_content = b"name,company\nJane,Acme\n"
    resp = client.post(
        "/jobs/ae-role/candidates/bulk-import",
        files={"file": ("candidates.csv", csv_content, "text/csv")},
        data={"role_family": "sales"},
    )
    assert resp.status_code == 400
    assert "notes" in resp.json()["detail"]


def test_bulk_import_404_for_missing_job(isolated_db):
    csv_content = b"notes\nsome text\n"
    resp = client.post(
        "/jobs/does-not-exist/candidates/bulk-import",
        files={"file": ("candidates.csv", csv_content, "text/csv")},
        data={"role_family": "sales"},
    )
    assert resp.status_code == 404


def test_public_route_404_for_unknown_token(isolated_db):
    from fastapi.testclient import TestClient as _TestClient
    from gtm_sourcing_agent.api import app as _app
    anon = _TestClient(_app)
    resp = anon.get("/public/roles/not-a-real-token")
    assert resp.status_code == 404


# ── candidate notes (Phase 10) ──────────────────────────────────────────


def test_set_candidate_note(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe"})

    resp = client.patch("/jobs/ae-role/candidates/cand-1/note", json={"note": "Great culture fit."})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"candidate_id": "cand-1", "note": "Great culture fit."}

    listed = client.get("/jobs/ae-role/candidates").json()
    assert listed[0]["note"] == "Great culture fit."


def test_set_candidate_note_404_for_missing_candidate(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.patch("/jobs/ae-role/candidates/no-such-candidate/note", json={"note": "x"})
    assert resp.status_code == 400


# ── conversation history: email/WhatsApp/call log + rolling summary ────


def test_set_candidate_contact(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe"})

    resp = client.patch(
        "/jobs/ae-role/candidates/cand-1/contact", json={"phone": "+919876543210", "email": "jane@example.com"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"candidate_id": "cand-1", "phone": "+919876543210", "email": "jane@example.com"}

    listed = client.get("/jobs/ae-role/candidates").json()
    assert listed[0]["phone"] == "+919876543210"
    assert listed[0]["email"] == "jane@example.com"


def test_log_communication_creates_entry_and_enqueues_summary(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import ConversationIntelligence, ConversationSummaryResult

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe"})
    fake_generate.queue.append(ConversationSummaryResult(summary="Warm contact so far.", open_items=["Follow up Friday"]))
    fake_generate.queue.append(ConversationIntelligence(interest_level="High"))

    resp = client.post(
        "/jobs/ae-role/candidates/cand-1/communications",
        json={"channel": "whatsapp", "direction": "outbound", "content": "Hi Jane, following up on the AE role.", "contact_used": "+919876543210"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["entry"]["channel"] == "whatsapp"
    assert body["entry"]["content"] == "Hi Jane, following up on the AE role."

    task = _wait_for_task("ae-role", body["summary_task"]["task_id"])
    assert task["status"] == "succeeded", task
    intelligence_task = _wait_for_task("ae-role", body["intelligence_task"]["task_id"])
    assert intelligence_task["status"] == "succeeded", intelligence_task

    fetched = client.get("/jobs/ae-role/candidates/cand-1/communications").json()
    assert len(fetched["entries"]) == 1
    assert fetched["summary"] == "Warm contact so far."
    assert fetched["based_on_entries"] == 1
    assert fetched["intelligence"]["interest_level"] == "High"
    assert {c["stage"] for c in fake_generate.calls} == {"conversation_summary", "conversation_intelligence"}


def test_communications_history_accumulates_across_channels(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import ConversationIntelligence, ConversationSummaryResult

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe"})

    fake_generate.queue.append(ConversationSummaryResult(summary="First contact."))
    fake_generate.queue.append(ConversationIntelligence())
    r1 = client.post(
        "/jobs/ae-role/candidates/cand-1/communications",
        json={"channel": "email", "content": "Reaching out about the role."},
    )
    _wait_for_task("ae-role", r1.json()["summary_task"]["task_id"])
    _wait_for_task("ae-role", r1.json()["intelligence_task"]["task_id"])

    fake_generate.queue.append(ConversationSummaryResult(summary="Called and discussed comp expectations."))
    fake_generate.queue.append(ConversationIntelligence(current_compensation="$120k", interest_level="Medium"))
    r2 = client.post(
        "/jobs/ae-role/candidates/cand-1/communications",
        json={"channel": "call", "content": "20-min call, discussed comp.", "transcript": "Recruiter: Hi Jane... Jane: Sure, happy to chat."},
    )
    _wait_for_task("ae-role", r2.json()["summary_task"]["task_id"])
    _wait_for_task("ae-role", r2.json()["intelligence_task"]["task_id"])

    fetched = client.get("/jobs/ae-role/candidates/cand-1/communications").json()
    assert [e["channel"] for e in fetched["entries"]] == ["email", "call"]
    assert fetched["entries"][1]["transcript"].startswith("Recruiter:")
    assert fetched["summary"] == "Called and discussed comp expectations."
    assert fetched["based_on_entries"] == 2


def test_conversation_intelligence_extracts_structured_fields(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import ConversationIntelligence, ConversationSummaryResult

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe"})
    fake_generate.queue.append(ConversationSummaryResult(summary="Discussed comp and notice."))
    fake_generate.queue.append(ConversationIntelligence(
        current_compensation="$120k", expected_compensation="$140k", notice_period="30 days",
        interest_level="High", concerns=["Limited remote flexibility"],
        recommendation="Move to interview",
    ))

    resp = client.post(
        "/jobs/ae-role/candidates/cand-1/communications",
        json={"channel": "call", "content": "Discussed comp, notice period, and interest."},
    )
    _wait_for_task("ae-role", resp.json()["summary_task"]["task_id"])
    _wait_for_task("ae-role", resp.json()["intelligence_task"]["task_id"])

    fetched = client.get("/jobs/ae-role/candidates/cand-1/communications").json()
    intel = fetched["intelligence"]
    assert intel["current_compensation"] == "$120k"
    assert intel["expected_compensation"] == "$140k"
    assert intel["notice_period"] == "30 days"
    assert intel["interest_level"] == "High"
    assert intel["concerns"] == ["Limited remote flexibility"]
    assert intel["recommendation"] == "Move to interview"

    # Also reachable off the candidate's own record (Candidates tab reads it there too).
    listed = client.get("/jobs/ae-role/candidates").json()
    assert listed[0]["conversation_intelligence"]["interest_level"] == "High"


def test_conversation_intelligence_defaults_to_insufficient_evidence(isolated_db, fake_generate):
    from gtm_sourcing_agent import db_storage
    from gtm_sourcing_agent.models import ConversationIntelligence, ConversationSummaryResult

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe"})
    fake_generate.queue.append(ConversationSummaryResult(summary="Brief first touch."))
    fake_generate.queue.append(ConversationIntelligence())  # nothing substantive discussed yet

    resp = client.post(
        "/jobs/ae-role/candidates/cand-1/communications",
        json={"channel": "email", "content": "Sent an intro note."},
    )
    _wait_for_task("ae-role", resp.json()["summary_task"]["task_id"])
    _wait_for_task("ae-role", resp.json()["intelligence_task"]["task_id"])

    intel = client.get("/jobs/ae-role/candidates/cand-1/communications").json()["intelligence"]
    assert intel["interest_level"] == "Insufficient evidence"
    assert intel["recommendation"] == "Insufficient evidence"
    assert intel["current_compensation"] == ""


def test_log_communication_404_for_missing_candidate(isolated_db):
    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    resp = client.post(
        "/jobs/ae-role/candidates/no-such-candidate/communications", json={"channel": "email", "content": "x"}
    )
    assert resp.status_code == 400


def test_communications_empty_before_any_logged(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_candidate("ae-role", "cand-1", {"name": "Jane Doe"})

    fetched = client.get("/jobs/ae-role/candidates/cand-1/communications").json()
    assert fetched["entries"] == []
    assert fetched["summary"] == ""
    assert fetched["based_on_entries"] == 0


# ── global search (Phase 10) ────────────────────────────────────────────


def test_search_route(isolated_db):
    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "Enterprise AE — Acme", "role_id": "acme-ae"})
    db_storage.merge_candidate("acme-ae", "cand-1", {"name": "Jane Doe"})

    resp = client.get("/search", params={"q": "acme"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(j["role_id"] == "acme-ae" for j in body["jobs"])

    resp2 = client.get("/search", params={"q": "jane"})
    assert any(c["name"] == "Jane Doe" for c in resp2.json()["candidates"])


def test_search_empty_query(isolated_db):
    resp = client.get("/search")
    assert resp.status_code == 200
    assert resp.json() == {"jobs": [], "candidates": []}
