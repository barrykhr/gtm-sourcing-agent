import pytest

from gtm_sourcing_agent import storage


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "WORKSPACE_DIR", tmp_path)
    return tmp_path


def test_load_role_returns_empty_skeleton_when_missing(isolated_workspace):
    state = storage.load_role("acme-ae-2026")
    assert state == {"role_id": "acme-ae-2026", "candidates": {}, "prioritizations": {}}


def test_merge_section_persists_across_loads(isolated_workspace):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    reloaded = storage.load_role("acme-ae-2026")
    assert reloaded["job_description"] == {"company": "Acme"}


def test_merge_section_preserves_other_sections(isolated_workspace):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    storage.merge_section("acme-ae-2026", "calibration", {"must_have_criteria": ["quota history"]})
    state = storage.load_role("acme-ae-2026")
    assert state["job_description"] == {"company": "Acme"}
    assert state["calibration"] == {"must_have_criteria": ["quota history"]}


def test_require_section_raises_when_missing(isolated_workspace):
    with pytest.raises(ValueError, match="job_description"):
        storage.require_section("acme-ae-2026", "job_description")


def test_require_section_returns_value_when_present(isolated_workspace):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    assert storage.require_section("acme-ae-2026", "icp") == {"must_have": ["SaaS"]}


def test_role_id_path_traversal_rejected(isolated_workspace):
    with pytest.raises(ValueError):
        storage.load_role("../evil")
