"""Phase 2: canonical candidate identity + dedup-on-add. See
docs/product-plan.md and models_orm.py's CanonicalCandidate/
CandidateEvaluation docstrings for the design."""

import pytest

from gtm_sourcing_agent import db, db_storage


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    return tmp_path


def test_two_jobs_same_source_url_dedupe_to_one_canonical(isolated_db):
    db_storage.merge_candidate(
        "job-a", "job-a-jane-doe",
        {"name": "Jane Doe", "current_company": "Acme", "source_url": "https://linkedin.com/in/janedoe"},
    )
    db_storage.merge_candidate(
        "job-b", "job-b-jane-doe",
        {"name": "Jane Doe", "current_company": "Acme Corp (new title)", "source_url": "https://linkedin.com/in/janedoe/"},
    )
    roster = db_storage.list_canonical_candidates()
    assert len(roster) == 1
    assert len(roster[0]["evaluations"]) == 2
    assert {e["role_id"] for e in roster[0]["evaluations"]} == {"job-a", "job-b"}


def test_dedup_falls_back_to_normalized_name_and_company_without_source_url(isolated_db):
    db_storage.merge_candidate("job-a", "job-a-jane-doe", {"name": "Jane Doe", "current_company": "Acme Corp"})
    db_storage.merge_candidate("job-b", "job-b-jane-doe", {"name": "  jane   doe ", "current_company": "acme corp"})
    roster = db_storage.list_canonical_candidates()
    assert len(roster) == 1
    assert len(roster[0]["evaluations"]) == 2


def test_different_people_stay_separate_canonical_records(isolated_db):
    db_storage.merge_candidate("job-a", "job-a-jane-doe", {"name": "Jane Doe", "current_company": "Acme"})
    db_storage.merge_candidate("job-a", "job-a-john-smith", {"name": "John Smith", "current_company": "Acme"})
    roster = db_storage.list_canonical_candidates()
    assert len(roster) == 2


def test_same_name_different_company_does_not_dedupe(isolated_db):
    db_storage.merge_candidate("job-a", "job-a-jane-doe", {"name": "Jane Doe", "current_company": "Acme"})
    db_storage.merge_candidate("job-b", "job-b-jane-doe", {"name": "Jane Doe", "current_company": "Globex"})
    roster = db_storage.list_canonical_candidates()
    assert len(roster) == 2


def test_re_running_candidate_analysis_for_the_same_job_updates_in_place(isolated_db):
    db_storage.merge_candidate("job-a", "job-a-jane-doe", {"name": "Jane Doe", "current_company": "Acme"})
    db_storage.merge_candidate("job-a", "job-a-jane-doe", {"name": "Jane Doe", "current_company": "Acme", "location": "NYC"})
    roster = db_storage.list_canonical_candidates()
    assert len(roster) == 1
    assert len(roster[0]["evaluations"]) == 1  # not two evaluations from one re-run
    assert db_storage.load_role("job-a")["candidates"]["job-a-jane-doe"]["location"] == "NYC"


def test_get_canonical_candidate_includes_job_title_and_tier(isolated_db):
    db_storage.create_job("job-a", title="Enterprise AE — Acme")
    db_storage.merge_candidate("job-a", "job-a-jane-doe", {"name": "Jane Doe", "current_company": "Acme"})
    db_storage.merge_prioritization("job-a", "job-a-jane-doe", {"candidate_id": "job-a-jane-doe", "tier": "A"})

    roster = db_storage.list_canonical_candidates()
    canonical_id = roster[0]["candidate_id"]
    detail = db_storage.get_canonical_candidate(canonical_id)

    assert detail["name"] == "Jane Doe"
    assert detail["evaluations"][0]["job_title"] == "Enterprise AE — Acme"
    assert detail["evaluations"][0]["tier"] == "A"


def test_get_canonical_candidate_returns_none_when_missing(isolated_db):
    assert db_storage.get_canonical_candidate("cand-doesnotexist") is None


def test_load_role_exposes_canonical_candidate_id_on_each_candidate(isolated_db):
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane Doe"})
    state = db_storage.load_role("job-a")
    canonical_id = state["candidates"]["cand-1"]["canonical_candidate_id"]
    assert canonical_id.startswith("cand-")
    assert db_storage.get_canonical_candidate(canonical_id)["name"] == "Jane Doe"


def test_load_role_still_returns_prioritizations_dict_shape(isolated_db):
    # Phase 1 contract must survive Phase 2's storage rewrite unchanged.
    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane Doe"})
    db_storage.merge_prioritization("job-a", "cand-1", {"candidate_id": "cand-1", "tier": "B"})
    state = db_storage.load_role("job-a")
    assert state["candidates"]["cand-1"]["name"] == "Jane Doe"
    assert state["prioritizations"]["cand-1"]["tier"] == "B"


def test_save_role_does_not_create_a_stray_job_section_for_candidates(isolated_db):
    # Guards against the "candidates"/"prioritizations" keys getting
    # double-stored (once via CandidateEvaluation, once as a generic
    # JobSection blob) if some future caller round-trips load_role() -> save_role().
    from sqlalchemy import select

    from gtm_sourcing_agent.models_orm import JobSection

    db_storage.merge_candidate("job-a", "cand-1", {"name": "Jane Doe"})
    state = db_storage.load_role("job-a")
    db_storage.save_role("job-a", state)

    with db.get_session() as session:
        section_keys = {
            row.section_key
            for row in session.scalars(select(JobSection).where(JobSection.role_id == "job-a")).all()
        }
    assert "candidates" not in section_keys
    assert "prioritizations" not in section_keys
