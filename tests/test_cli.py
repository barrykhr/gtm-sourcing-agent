"""CLI tests via Typer's CliRunner — no network calls. LLM-backed
commands mock llm_client.generate the same way tests/test_stages.py
does; funnel/status/show/candidate-list are pure and need no mocking."""

import json

import pytest
from typer.testing import CliRunner

from gtm_sourcing_agent import cli, llm_client, storage
from gtm_sourcing_agent.models import JobDescription

runner = CliRunner()


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "WORKSPACE_DIR", tmp_path)
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


def test_status_on_fresh_role_shows_intake_next(isolated_workspace):
    result = runner.invoke(cli.app, ["status", "acme-ae-2026"])
    assert result.exit_code == 0
    assert "next: intake" in result.output
    assert "[ ] intake" in result.output


def test_calibrate_before_intake_fails_with_friendly_message(isolated_workspace):
    result = runner.invoke(cli.app, ["calibrate", "acme-ae-2026"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "job_description" in result.output
    # no raw traceback leaked to the user
    assert "Traceback" not in result.output


def test_intake_rejects_nonexistent_jd_path(isolated_workspace):
    result = runner.invoke(cli.app, ["intake", "no-such-file.txt", "--role-id", "acme-ae-2026"])
    assert result.exit_code != 0


def test_intake_end_to_end_updates_status(isolated_workspace, fake_generate, tmp_path):
    jd_file = tmp_path / "jd.txt"
    jd_file.write_text("Enterprise AE role, own net-new logos.")
    fixed = JobDescription(
        raw_jd_text="x", company="Acme", role_title="AE", function="Sales",
        seniority="Senior", geography="US", role_objective="Own net-new logos.",
    )
    fake_generate.queue.append(fixed)

    result = runner.invoke(cli.app, ["intake", str(jd_file), "--role-id", "acme-ae-2026"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["company"] == "Acme"

    status_result = runner.invoke(cli.app, ["status", "acme-ae-2026"])
    assert "[x] intake" in status_result.output
    assert "next: calibration" in status_result.output


def test_show_missing_section_exits_nonzero(isolated_workspace):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    result = runner.invoke(cli.app, ["show", "acme-ae-2026", "icp"])
    assert result.exit_code == 1
    assert "No 'icp' data yet" in result.output


def test_show_whole_workspace_and_one_section(isolated_workspace):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    whole = runner.invoke(cli.app, ["show", "acme-ae-2026"])
    assert whole.exit_code == 0
    assert json.loads(whole.output)["job_description"]["company"] == "Acme"

    section = runner.invoke(cli.app, ["show", "acme-ae-2026", "job_description"])
    assert section.exit_code == 0
    assert json.loads(section.output)["company"] == "Acme"


def test_candidate_list_empty_then_populated(isolated_workspace):
    empty = runner.invoke(cli.app, ["candidate", "list", "acme-ae-2026"])
    assert "No candidates yet" in empty.output

    storage.merge_candidate(
        "acme-ae-2026", "cand-1",
        {"name": "Jane Doe", "current_title": "AE", "current_company": "Rippling"},
    )
    storage.merge_prioritization("acme-ae-2026", "cand-1", {"candidate_id": "cand-1", "tier": "A"})

    populated = runner.invoke(cli.app, ["candidate", "list", "acme-ae-2026"])
    assert populated.exit_code == 0
    assert "[A] cand-1" in populated.output
    assert "Jane Doe" in populated.output
    assert "Rippling" in populated.output


def test_candidate_add_rejects_nonexistent_source_path(isolated_workspace):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    result = runner.invoke(
        cli.app,
        ["candidate", "add", "acme-ae-2026", "--source-path", "nope.txt", "--role-family", "sales"],
    )
    assert result.exit_code != 0


def test_funnel_update_and_report_are_pure_no_mocking_needed(isolated_workspace):
    update = runner.invoke(cli.app, ["funnel", "update", "acme-ae-2026", "cand-1", "contacted"])
    assert update.exit_code == 0

    report = runner.invoke(cli.app, ["funnel", "report", "acme-ae-2026"])
    assert report.exit_code == 0
    assert json.loads(report.output)["counts_by_stage"]["CONTACTED"] == 1


def test_funnel_update_rejects_unknown_stage_with_friendly_message(isolated_workspace):
    result = runner.invoke(cli.app, ["funnel", "update", "acme-ae-2026", "cand-1", "not_a_stage"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_funnel_forecast_labels_assumption_source(isolated_workspace):
    result = runner.invoke(cli.app, ["funnel", "forecast", "5", "12"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["hires_needed"] == 5
    assert payload["assumptions"]["source"] == "market_default"


def test_funnel_forecast_rejects_invalid_source_with_friendly_message(isolated_workspace):
    result = runner.invoke(cli.app, ["funnel", "forecast", "5", "12", "--source", "guess"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output
