"""Rubric tuning (Phase 8, docs/product-plan.md): icp.update_criteria's
deterministic direct-edit path, distinct from run()'s model call."""

import pytest

from gtm_sourcing_agent import storage
from gtm_sourcing_agent.stages import icp


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "WORKSPACE_DIR", tmp_path)
    return tmp_path


def _seed_icp(**overrides):
    base = {"must_have": ["SaaS"], "nice_to_have": ["enterprise"], "target_background": "AE"}
    base.update(overrides)
    storage.merge_section("acme-ae-2026", "icp", base)


def test_update_criteria_replaces_must_have(isolated_workspace):
    _seed_icp()
    result = icp.update_criteria("acme-ae-2026", must_have=["SaaS", "$1M+ quota"])
    assert result.must_have == ["SaaS", "$1M+ quota"]
    assert result.nice_to_have == ["enterprise"]  # untouched


def test_update_criteria_replaces_nice_to_have(isolated_workspace):
    _seed_icp()
    result = icp.update_criteria("acme-ae-2026", nice_to_have=[])
    assert result.nice_to_have == []
    assert result.must_have == ["SaaS"]  # untouched


def test_update_criteria_leaves_other_icp_fields_intact(isolated_workspace):
    _seed_icp()
    result = icp.update_criteria("acme-ae-2026", must_have=["SaaS", "enterprise"])
    assert result.target_background == "AE"


def test_update_criteria_persists(isolated_workspace):
    _seed_icp()
    icp.update_criteria("acme-ae-2026", must_have=["SaaS", "$1M+ quota"])
    state = storage.load_role("acme-ae-2026")
    assert state["icp"]["must_have"] == ["SaaS", "$1M+ quota"]


def test_update_criteria_requires_existing_icp(isolated_workspace):
    with pytest.raises(ValueError, match="icp"):
        icp.update_criteria("acme-ae-2026", must_have=["SaaS"])
