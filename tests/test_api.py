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


def test_interview_questions_route(isolated_db, fake_generate):
    from gtm_sourcing_agent.models import RoleInterviewQuestions
    from gtm_sourcing_agent.models.interview_questions import InterviewQuestion

    from gtm_sourcing_agent import db_storage

    client.post("/jobs", json={"title": "AE Role", "role_id": "ae-role"})
    db_storage.merge_section("ae-role", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section("ae-role", "calibration", {"red_flags": ["job-hopping"]})

    fake_generate.queue.append(
        RoleInterviewQuestions(
            core_questions=[InterviewQuestion(question="Walk me through a deal.", why_it_matters="validates quota")],
        )
    )
    resp = client.post("/jobs/ae-role/interview-questions")
    assert resp.status_code == 202, resp.text
    task = _wait_for_task("ae-role", resp.json()["task_id"])
    assert task["status"] == "succeeded", task
    assert task["result"]["core_questions"][0]["question"] == "Walk me through a deal."

    job = client.get("/jobs/ae-role").json()
    assert job["state"]["interview_questions"]["core_questions"][0]["question"] == "Walk me through a deal."


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
