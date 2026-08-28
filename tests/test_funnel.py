import pytest

from gtm_sourcing_agent import storage
from gtm_sourcing_agent.models.funnel import ForecastAssumptions
from gtm_sourcing_agent.stages import funnel


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "WORKSPACE_DIR", tmp_path)
    return tmp_path


def test_update_creates_and_advances_record(isolated_workspace):
    funnel.update("acme-ae-2026", "cand-1", "IDENTIFIED")
    record = funnel.update("acme-ae-2026", "cand-1", "CONTACTED")
    assert record["current_stage"] == "CONTACTED"
    assert [t["stage"] for t in record["stage_history"]] == ["IDENTIFIED", "CONTACTED"]


def test_update_records_optional_note(isolated_workspace):
    funnel.update("acme-ae-2026", "cand-1", "IDENTIFIED")
    record = funnel.update("acme-ae-2026", "cand-1", "RECRUITER_SCREEN", note="strong resume, HM wants to meet")
    assert record["stage_history"][-1]["note"] == "strong resume, HM wants to meet"
    assert record["stage_history"][0]["note"] == ""  # default stays empty when not given


def test_update_records_optional_schedule(isolated_workspace):
    record = funnel.update("acme-ae-2026", "cand-1", "HM_INTERVIEW", scheduled_at="2026-09-01T14:00")
    assert record["stage_history"][-1]["scheduled_at"] == "2026-09-01T14:00"
    record2 = funnel.update("acme-ae-2026", "cand-1", "FINAL_INTERVIEW")
    assert record2["stage_history"][-1]["scheduled_at"] is None  # not sticky across moves


def test_update_rejects_unknown_stage(isolated_workspace):
    with pytest.raises(ValueError):
        funnel.update("acme-ae-2026", "cand-1", "NOT_A_STAGE")


def test_report_counts_are_cumulative_by_stage_reached(isolated_workspace):
    funnel.update("acme-ae-2026", "cand-1", "HM_INTERVIEW")
    funnel.update("acme-ae-2026", "cand-2", "CONTACTED")
    metrics = funnel.report("acme-ae-2026")
    assert metrics.counts_by_stage["IDENTIFIED"] == 2
    assert metrics.counts_by_stage["CONTACTED"] == 2
    assert metrics.counts_by_stage["RECRUITER_SCREEN"] == 1
    assert metrics.counts_by_stage["HM_INTERVIEW"] == 1
    assert metrics.counts_by_stage["OFFER"] == 0


def test_report_flags_biggest_leakage(isolated_workspace):
    for i in range(10):
        funnel.update("acme-ae-2026", f"cand-{i}", "CONTACTED")
    # advance the one survivor all the way through so every stage past
    # RESPONDED has an equal (non-zero) count, isolating the CONTACTED ->
    # RESPONDED drop as the only real leak in this scenario.
    funnel.update("acme-ae-2026", "cand-0", "JOINED")
    metrics = funnel.report("acme-ae-2026")
    assert metrics.biggest_leakage_stage == "CONTACTED -> RESPONDED"


def test_forecast_back_calculates_required_volume(isolated_workspace):
    assumptions = ForecastAssumptions(
        source="market_default",
        screen_to_hm_interview=0.5,
        hm_interview_to_final=0.5,
        final_to_offer=0.5,
        offer_to_accept=1.0,
        contacted_to_screen=0.5,
        sourced_to_contacted=0.5,
    )
    result = funnel.forecast(hires_needed=1, timeline_weeks=8, assumptions=assumptions)
    assert result.required_offers == 1
    assert result.required_finalists == 2
    assert result.required_hm_interviews == 4
    assert result.required_recruiter_screens == 8
    assert result.required_qualified_candidates == 16
    assert result.required_sourced_candidates == 32


def test_forecast_labels_assumption_source():
    assumptions = ForecastAssumptions(
        source="historical",
        screen_to_hm_interview=0.5,
        hm_interview_to_final=0.5,
        final_to_offer=0.5,
        offer_to_accept=0.8,
        contacted_to_screen=0.3,
        sourced_to_contacted=0.3,
    )
    result = funnel.forecast(hires_needed=3, timeline_weeks=6, assumptions=assumptions)
    assert result.assumptions.source == "historical"
