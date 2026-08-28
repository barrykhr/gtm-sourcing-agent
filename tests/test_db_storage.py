"""Mirrors tests/test_storage.py exactly, against db_storage.py instead —
same contract, SQLite backend. If these two test files ever diverge in
what they assert, the two backends have drifted apart."""

import pytest

from gtm_sourcing_agent import db, db_storage


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    return tmp_path


def test_load_role_returns_empty_skeleton_when_missing(isolated_db):
    state = db_storage.load_role("acme-ae-2026")
    assert state == {"role_id": "acme-ae-2026", "candidates": {}, "prioritizations": {}}


def test_merge_section_persists_across_loads(isolated_db):
    db_storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    reloaded = db_storage.load_role("acme-ae-2026")
    assert reloaded["job_description"] == {"company": "Acme"}


def test_merge_section_preserves_other_sections(isolated_db):
    db_storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    db_storage.merge_section("acme-ae-2026", "calibration", {"must_have_criteria": ["quota history"]})
    state = db_storage.load_role("acme-ae-2026")
    assert state["job_description"] == {"company": "Acme"}
    assert state["calibration"] == {"must_have_criteria": ["quota history"]}


def test_merge_section_overwrites_same_key_in_place(isolated_db):
    db_storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS", "enterprise"]})
    state = db_storage.load_role("acme-ae-2026")
    assert state["icp"] == {"must_have": ["SaaS", "enterprise"]}


def test_require_section_raises_when_missing(isolated_db):
    with pytest.raises(ValueError, match="job_description"):
        db_storage.require_section("acme-ae-2026", "job_description")


def test_require_section_returns_value_when_present(isolated_db):
    db_storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    assert db_storage.require_section("acme-ae-2026", "icp") == {"must_have": ["SaaS"]}


def test_merge_candidate_and_prioritization(isolated_db):
    db_storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    db_storage.merge_prioritization("acme-ae-2026", "cand-1", {"candidate_id": "cand-1", "tier": "A"})
    state = db_storage.load_role("acme-ae-2026")
    assert state["candidates"]["cand-1"]["name"] == "Jane"
    assert state["prioritizations"]["cand-1"]["tier"] == "A"


def test_create_job_sets_title_and_is_idempotent(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Enterprise AE — Acme", role_family="sales")
    db_storage.create_job("acme-ae-2026")  # re-creating shouldn't blank out the title
    jobs = db_storage.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Enterprise AE — Acme"
    assert jobs[0]["role_family"] == "sales"


def test_create_job_defaults_title_to_role_id(isolated_db):
    db_storage.create_job("acme-ae-2026")
    assert db_storage.list_jobs()[0]["title"] == "acme-ae-2026"


def test_list_jobs_orders_most_recently_updated_first(isolated_db):
    db_storage.create_job("job-a", title="A")
    db_storage.create_job("job-b", title="B")
    db_storage.merge_section("job-a", "job_description", {"company": "Acme"})  # bumps job-a's updated_at
    role_ids = [j["role_id"] for j in db_storage.list_jobs()]
    assert role_ids[0] == "job-a"


def test_job_exists(isolated_db):
    assert db_storage.job_exists("acme-ae-2026") is False
    db_storage.create_job("acme-ae-2026")
    assert db_storage.job_exists("acme-ae-2026") is True


def test_role_id_isolation_across_two_jobs(isolated_db):
    db_storage.merge_section("job-a", "job_description", {"company": "A"})
    db_storage.merge_section("job-b", "job_description", {"company": "B"})
    assert db_storage.load_role("job-a")["job_description"]["company"] == "A"
    assert db_storage.load_role("job-b")["job_description"]["company"] == "B"


def test_analytics_overview_counts_across_jobs(isolated_db):
    db_storage.create_job("job-a", title="A")
    db_storage.create_job("job-b", title="B")
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane"})
    db_storage.merge_candidate("job-a", "cand-2", {"name": "Marcus"})
    db_storage.merge_candidate("job-b", "cand-3", {"name": "Elena"})
    db_storage.merge_prioritization("job-a", "cand-1", {"candidate_id": "cand-1", "tier": "A", "recruiter_decision": "pursue"})
    db_storage.merge_prioritization("job-a", "cand-2", {"candidate_id": "cand-2", "tier": "B"})
    # cand-3 never prioritized

    overview = db_storage.analytics_overview()

    assert overview["total_jobs"] == 2
    assert overview["total_candidates"] == 3
    assert overview["total_evaluations"] == 3
    assert overview["tier_distribution"] == {"A": 1, "B": 1, "C": 0, "D": 0, "not_prioritized": 1}
    assert overview["decisions_recorded"] == 1
    assert overview["decisions_pending"] == 1
    assert overview["decision_breakdown"] == {"pursue": 1}


def test_analytics_overview_empty_state(isolated_db):
    overview = db_storage.analytics_overview()
    assert overview["total_jobs"] == 0
    assert overview["total_evaluations"] == 0
    assert overview["decision_breakdown"] == {}


def test_team_usage_counts_per_recruiter(isolated_db):
    from gtm_sourcing_agent import auth

    auth.create_user("priya@example.com", "password123")
    auth.create_user("marcus@example.com", "password123")

    db_storage.create_job("job-a", title="A", owner_email="priya@example.com")
    db_storage.create_job("job-b", title="B", owner_email="priya@example.com")
    db_storage.log_activity("job-a", "priya@example.com", "added candidate (pasted text)")
    db_storage.log_activity("job-a", "priya@example.com", "added candidate (resume upload)")
    db_storage.log_activity("job-a", "priya@example.com", "requested prioritization", candidate_id="cand-1")
    db_storage.log_activity("job-b", "marcus@example.com", "requested calibration")

    usage = db_storage.team_usage()

    assert usage["total_users"] == 2
    by_email = {r["email"]: r for r in usage["recruiters"]}
    assert by_email["priya@example.com"]["jobs_owned"] == 2
    assert by_email["priya@example.com"]["candidates_added"] == 2
    assert by_email["priya@example.com"]["total_actions"] == 3
    assert by_email["priya@example.com"]["last_active"] is not None
    assert by_email["marcus@example.com"]["jobs_owned"] == 0
    assert by_email["marcus@example.com"]["candidates_added"] == 0
    assert by_email["marcus@example.com"]["total_actions"] == 1


def test_team_usage_empty_state(isolated_db):
    usage = db_storage.team_usage()
    assert usage["total_users"] == 0
    assert usage["recruiters"] == []


def test_attention_needed_flags_stalled_and_scheduled(isolated_db):
    from datetime import UTC, datetime, timedelta

    db_storage.create_job("job-a", title="Job A")
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane"})
    db_storage.merge_candidate("job-a", "cand-2", {"name": "Marcus"})

    stale_at = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    future_at = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    db_storage.merge_section("job-a", "funnel", {
        "cand-1": {
            "candidate_id": "cand-1", "role_id": "job-a", "current_stage": "CONTACTED",
            "stage_history": [{"stage": "CONTACTED", "at": stale_at, "note": "", "scheduled_at": None}],
        },
        "cand-2": {
            "candidate_id": "cand-2", "role_id": "job-a", "current_stage": "HM_INTERVIEW",
            "stage_history": [{"stage": "HM_INTERVIEW", "at": stale_at, "note": "", "scheduled_at": future_at}],
        },
    })

    result = db_storage.attention_needed()

    assert {f["candidate_name"] for f in result["needs_follow_up"]} == {"Jane", "Marcus"}
    assert len(result["upcoming_interviews"]) == 1
    assert result["upcoming_interviews"][0]["candidate_name"] == "Marcus"
    assert result["upcoming_interviews"][0]["scheduled_at"] == future_at


def test_attention_needed_ignores_recent_and_non_awaiting_stages(isolated_db):
    from datetime import UTC, datetime

    db_storage.create_job("job-a", title="Job A")
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane"})
    recent_at = datetime.now(UTC).isoformat()
    db_storage.merge_section("job-a", "funnel", {
        "cand-1": {
            "candidate_id": "cand-1", "role_id": "job-a", "current_stage": "CONTACTED",
            "stage_history": [{"stage": "CONTACTED", "at": recent_at, "note": "", "scheduled_at": None}],
        },
    })
    result = db_storage.attention_needed()
    assert result["needs_follow_up"] == []
    assert result["upcoming_interviews"] == []


# ── role templates (Phase 8) ────────────────────────────────────────────


def test_clone_role_copies_cloneable_sections(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE", role_family="sales")
    db_storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    db_storage.merge_section("acme-ae-2026", "calibration", {"must_have_criteria": ["quota history"]})
    db_storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    db_storage.merge_section("acme-ae-2026", "talent_map", {"target_companies": ["Salesforce"]})
    db_storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})

    cloned = db_storage.clone_role("acme-ae-2026", "beta-ae-2026", title="Beta AE")

    assert cloned["role_id"] == "beta-ae-2026"
    assert cloned["role_family"] == "sales"  # inherited, not overridden
    state = db_storage.load_role("beta-ae-2026")
    assert state["job_description"] == {"company": "Acme"}
    assert state["calibration"] == {"must_have_criteria": ["quota history"]}
    assert state["icp"] == {"must_have": ["SaaS"]}
    assert state["talent_map"] == {"target_companies": ["Salesforce"]}
    assert state["candidates"] == {}  # never carried over


def test_clone_role_raises_for_missing_source(isolated_db):
    with pytest.raises(ValueError, match="not found"):
        db_storage.clone_role("does-not-exist", "beta-ae-2026")


# ── activity log (Phase 8) ──────────────────────────────────────────────


def test_log_activity_and_list_activity_round_trip(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    db_storage.log_activity("acme-ae-2026", "r1@example.com", "created job")
    db_storage.log_activity(
        "acme-ae-2026", "r2@example.com", "set decision: pursue", candidate_id="cand-1", detail="tier A"
    )

    entries = db_storage.list_activity("acme-ae-2026")

    assert len(entries) == 2
    assert entries[0]["action"] == "set decision: pursue"  # most recent first
    assert entries[0]["candidate_id"] == "cand-1"
    assert entries[0]["detail"] == "tier A"
    assert entries[1]["action"] == "created job"


def test_list_activity_is_scoped_per_job(isolated_db):
    db_storage.create_job("job-a", title="Job A")
    db_storage.create_job("job-b", title="Job B")
    db_storage.log_activity("job-a", "r1@example.com", "created job")
    db_storage.log_activity("job-b", "r1@example.com", "created job")

    assert len(db_storage.list_activity("job-a")) == 1
    assert len(db_storage.list_activity("job-b")) == 1


# ── job lifecycle (Phase 10) ────────────────────────────────────────────


def test_create_job_defaults_to_open_lifecycle(isolated_db):
    job = db_storage.create_job("acme-ae-2026", title="Acme AE")
    assert job["lifecycle_status"] == "OPEN"


def test_set_job_lifecycle_updates_and_persists(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    result = db_storage.set_job_lifecycle("acme-ae-2026", "FILLED")
    assert result["lifecycle_status"] == "FILLED"
    jobs = {j["role_id"]: j for j in db_storage.list_jobs()}
    assert jobs["acme-ae-2026"]["lifecycle_status"] == "FILLED"


def test_set_job_lifecycle_rejects_unknown_status(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    with pytest.raises(ValueError, match="not a valid job status"):
        db_storage.set_job_lifecycle("acme-ae-2026", "DEFINITELY_NOT_A_STATUS")


def test_set_job_lifecycle_raises_for_missing_job(isolated_db):
    with pytest.raises(ValueError, match="not found"):
        db_storage.set_job_lifecycle("does-not-exist", "FILLED")


# ── job ownership (Phase 10) ────────────────────────────────────────────


def test_create_job_sets_owner(isolated_db):
    job = db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    assert job["owner_email"] == "r1@example.com"


def test_set_job_owner_reassigns(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    result = db_storage.set_job_owner("acme-ae-2026", "r2@example.com")
    assert result["owner_email"] == "r2@example.com"


def test_set_job_owner_can_clear(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    result = db_storage.set_job_owner("acme-ae-2026", None)
    assert result["owner_email"] is None


def test_set_job_owner_raises_for_missing_job(isolated_db):
    with pytest.raises(ValueError, match="not found"):
        db_storage.set_job_owner("does-not-exist", "r1@example.com")


# ── candidate notes (Phase 10) ──────────────────────────────────────────


def test_set_candidate_note_persists_and_is_separate_from_data(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    db_storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane Doe"})

    result = db_storage.set_candidate_note("acme-ae-2026", "cand-1", "Seemed distracted on the intro call.")
    assert result["note"] == "Seemed distracted on the intro call."

    state = db_storage.load_role("acme-ae-2026")
    assert state["candidates"]["cand-1"]["note"] == "Seemed distracted on the intro call."
    assert state["candidates"]["cand-1"]["name"] == "Jane Doe"  # data untouched


def test_set_candidate_note_defaults_to_empty(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    db_storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane Doe"})
    state = db_storage.load_role("acme-ae-2026")
    assert state["candidates"]["cand-1"]["note"] == ""


def test_set_candidate_note_raises_for_missing_candidate(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    with pytest.raises(ValueError, match="not found"):
        db_storage.set_candidate_note("acme-ae-2026", "no-such-candidate", "a note")


# ── global search (Phase 10) ────────────────────────────────────────────


def test_search_matches_job_title_case_insensitively(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Enterprise AE — Acme")
    result = db_storage.search("enterprise")
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["role_id"] == "acme-ae-2026"


def test_search_matches_job_role_id(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Something Else Entirely")
    result = db_storage.search("acme-ae")
    assert len(result["jobs"]) == 1


def test_search_matches_candidate_name(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    db_storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane Doe"})
    result = db_storage.search("jane")
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["name"] == "Jane Doe"


def test_search_empty_query_returns_nothing(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    result = db_storage.search("")
    assert result == {"jobs": [], "candidates": []}


def test_search_no_match_returns_empty_lists(isolated_db):
    db_storage.create_job("acme-ae-2026", title="Acme AE")
    result = db_storage.search("zzz-no-such-thing")
    assert result == {"jobs": [], "candidates": []}
