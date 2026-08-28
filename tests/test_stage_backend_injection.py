"""Proves stages actually route through storage_backend end-to-end against
the DB backend, not just that the default (file) backend still works —
de-risks the FastAPI layer, which passes db_storage into every stage call.
"""

import pytest

from gtm_sourcing_agent import db, db_storage, llm_client
from gtm_sourcing_agent.models import HiringManagerCalibration, JobDescription
from gtm_sourcing_agent.stages import calibration, intake


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


def test_intake_and_calibration_chain_through_db_storage(isolated_db, fake_generate):
    jd = JobDescription(
        raw_jd_text="x", company="Acme", role_title="AE", function="Sales",
        seniority="Senior", geography="US", role_objective="Own net-new logos.",
    )
    fake_generate.queue.append(jd)
    result = intake.run("acme-ae-2026", "Enterprise AE.", storage_backend=db_storage)
    assert result == jd
    assert db_storage.load_role("acme-ae-2026")["job_description"]["company"] == "Acme"

    calib = HiringManagerCalibration(must_have_criteria=["quota history"])
    fake_generate.queue.append(calib)
    result = calibration.run("acme-ae-2026", storage_backend=db_storage)
    assert result == calib
    assert db_storage.load_role("acme-ae-2026")["calibration"]["must_have_criteria"] == ["quota history"]


def test_calibration_via_db_backend_still_gates_on_missing_intake(isolated_db, fake_generate):
    with pytest.raises(ValueError, match="job_description"):
        calibration.run("acme-ae-2026", storage_backend=db_storage)
    assert fake_generate.calls == []


def test_file_backend_and_db_backend_are_fully_isolated(isolated_db, fake_generate, tmp_path, monkeypatch):
    from gtm_sourcing_agent import storage

    monkeypatch.setattr(storage, "WORKSPACE_DIR", tmp_path / "workspace")
    jd = JobDescription(
        raw_jd_text="x", company="FileBackendCo", role_title="AE", function="Sales",
        seniority="Senior", geography="US", role_objective="x",
    )
    fake_generate.queue.append(jd)
    intake.run("acme-ae-2026", "text")  # default storage_backend=storage (file)

    # the DB backend must not see what the file backend just wrote
    assert "job_description" not in db_storage.load_role("acme-ae-2026")
    assert storage.load_role("acme-ae-2026")["job_description"]["company"] == "FileBackendCo"
