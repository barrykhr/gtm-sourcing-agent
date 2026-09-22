"""stages/workload_planning.py — DB-only (see its own docstring), so this
uses the db_storage backend directly rather than the file-backed
isolated_workspace fixture test_stages.py's other stage tests share.
"""

import pytest

from gtm_sourcing_agent import db, db_storage, llm_client
from gtm_sourcing_agent.models.workload import RoleEffortAllocation, WeeklyEffortPlan
from gtm_sourcing_agent.stages import workload_planning


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
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


def test_run_passes_available_days_and_roster_into_the_prompt(isolated_db, fake_generate):
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    fake_generate.queue.append(WeeklyEffortPlan(
        available_days_per_week=5,
        allocations=[RoleEffortAllocation(role_id="acme-ae-2026", title="Acme AE", recommended_days_this_week=5, rationale="only role")],
    ))

    workload_planning.run("r1@example.com", 5, storage_backend=db_storage)

    assert fake_generate.calls[0]["stage"] == "workload_planning"
    assert "acme-ae-2026" in fake_generate.calls[0]["prompt"]
    assert "5" in fake_generate.calls[0]["prompt"]


def test_run_sets_available_days_on_the_result(isolated_db, fake_generate):
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    fake_generate.queue.append(WeeklyEffortPlan(available_days_per_week=0, allocations=[]))

    result = workload_planning.run("r1@example.com", 4, storage_backend=db_storage)

    assert result.available_days_per_week == 4


def test_run_keeps_a_matched_allocation_as_is(isolated_db, fake_generate):
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    fake_generate.queue.append(WeeklyEffortPlan(
        available_days_per_week=5,
        allocations=[RoleEffortAllocation(
            role_id="acme-ae-2026", title="Acme AE", recommended_days_this_week=3, rationale="overdue deadline",
        )],
    ))

    result = workload_planning.run("r1@example.com", 5, storage_backend=db_storage)

    assert len(result.allocations) == 1
    assert result.allocations[0].recommended_days_this_week == 3
    assert result.allocations[0].rationale == "overdue deadline"


def test_run_backfills_a_role_the_model_omitted(isolated_db, fake_generate):
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    db_storage.create_job("globex-se-2026", title="Globex SE", owner_email="r1@example.com")
    # Only responds for one of the two open roles.
    fake_generate.queue.append(WeeklyEffortPlan(
        available_days_per_week=5,
        allocations=[RoleEffortAllocation(
            role_id="acme-ae-2026", title="Acme AE", recommended_days_this_week=3, rationale="urgent",
        )],
    ))

    result = workload_planning.run("r1@example.com", 5, storage_backend=db_storage)

    by_id = {a.role_id: a for a in result.allocations}
    assert set(by_id) == {"acme-ae-2026", "globex-se-2026"}
    assert by_id["globex-se-2026"].recommended_days_this_week == 2.0
    assert "not explicitly addressed" in by_id["globex-se-2026"].rationale


def test_run_drops_an_allocation_for_a_role_not_in_the_roster(isolated_db, fake_generate):
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    fake_generate.queue.append(WeeklyEffortPlan(
        available_days_per_week=5,
        allocations=[
            RoleEffortAllocation(role_id="acme-ae-2026", title="Acme AE", recommended_days_this_week=5, rationale="only real role"),
            RoleEffortAllocation(role_id="made-up-role", title="Made Up", recommended_days_this_week=99, rationale="hallucinated"),
        ],
    ))

    result = workload_planning.run("r1@example.com", 5, storage_backend=db_storage)

    assert [a.role_id for a in result.allocations] == ["acme-ae-2026"]


def test_run_with_no_open_roles_returns_empty_allocations(isolated_db, fake_generate):
    fake_generate.queue.append(WeeklyEffortPlan(available_days_per_week=5, allocations=[]))

    result = workload_planning.run("nobody@example.com", 5, storage_backend=db_storage)

    assert result.allocations == []
