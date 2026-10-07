"""stages/role_intelligence_extraction.py — the Feature 01 "Create Role"
stage. Mocks llm_client.generate directly (same seam test_workload_planning.py
and every other stage test uses) so these tests verify the stage's own
logic — persistence via role_intelligence.save_extraction, and the
anti-hallucination source_span guardrail — never real model behavior.
AI evaluation fixtures (messy/contradictory/incomplete/ambiguous JDs) live
in test_role_intelligence_eval_fixtures.py."""

import pytest

from gtm_sourcing_agent import db, db_storage, llm_client, role_intelligence
from gtm_sourcing_agent.models.role_intelligence import EvidencedField, ExtractedAmbiguity, ExtractedRequirement, RoleExtraction
from gtm_sourcing_agent.stages import role_intelligence_extraction


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db_storage.create_job("acme-ae-2026", title="Acme AE", owner_email="r1@example.com")
    return tmp_path


@pytest.fixture
def fake_generate(monkeypatch):
    calls = []
    queue = []

    def _fake(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage="", on_usage=None):
        calls.append({"prompt": prompt, "output_model": output_model, "stage": stage})
        if on_usage is not None:
            class _Usage:
                input_tokens = 100
                output_tokens = 50
            on_usage(_Usage())
        return queue.pop(0)

    monkeypatch.setattr(llm_client, "generate", _fake)
    _fake.calls = calls
    _fake.queue = queue
    return _fake


JD_TEXT = "We need an Account Executive with 5+ years of experience selling into enterprise SaaS accounts."


def test_run_persists_requirements_icp_and_ambiguities(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="experience", value="5+ years enterprise SaaS sales", priority="must_have",
            evidence_level="CONFIRMED", source_span="5+ years of experience selling into enterprise SaaS accounts",
            confidence=0.9, rationale="directly stated",
        )],
        icp_fields={"customer_segment": EvidencedField(value="Enterprise", evidence_level="CONFIRMED", source_span="enterprise SaaS accounts", confidence=0.8)},
        ambiguities=[ExtractedAmbiguity(description="seniority unclear", candidate_resolutions=["ask hiring manager"])],
    ))

    role_intelligence_extraction.run("acme-ae-2026", JD_TEXT, user_email="r1@example.com")

    reqs = role_intelligence.get_requirements("acme-ae-2026")
    assert len(reqs) == 1
    assert reqs[0]["evidence_level"] == "CONFIRMED"

    icp = role_intelligence.get_icp("acme-ae-2026")
    assert icp["fields"]["customer_segment"]["value"] == "Enterprise"

    ambs = role_intelligence.get_ambiguities("acme-ae-2026")
    assert len(ambs) == 1

    assert fake_generate.calls[0]["stage"] == "role_intelligence_extraction"


def test_run_downgrades_confirmed_requirement_with_fabricated_source_span(isolated_db, fake_generate):
    """Anti-hallucination guardrail (Architecture §5): a requirement
    claiming CONFIRMED evidence with a source_span that isn't a real
    substring of the JD must be downgraded, never trusted as-is."""
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="skill", value="Salesforce CPQ", priority="must_have",
            evidence_level="CONFIRMED", source_span="must have Salesforce CPQ certification",  # not in JD_TEXT
            confidence=0.95, rationale="fabricated",
        )],
        icp_fields={}, ambiguities=[],
    ))

    role_intelligence_extraction.run("acme-ae-2026", JD_TEXT)

    req = role_intelligence.get_requirements("acme-ae-2026")[0]
    assert req["evidence_level"] == "INFERRED"


def test_run_downgrades_confirmed_requirement_with_empty_source_span(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="skill", value="Salesforce CPQ", priority="must_have",
            evidence_level="CONFIRMED", source_span="", confidence=0.95,
        )],
        icp_fields={}, ambiguities=[],
    ))

    role_intelligence_extraction.run("acme-ae-2026", JD_TEXT)

    req = role_intelligence.get_requirements("acme-ae-2026")[0]
    assert req["evidence_level"] == "INFERRED"


def test_run_keeps_confirmed_when_source_span_is_a_real_substring(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="experience", value="5+ years", priority="must_have",
            evidence_level="CONFIRMED", source_span="5+ years of experience", confidence=0.9,
        )],
        icp_fields={}, ambiguities=[],
    ))

    role_intelligence_extraction.run("acme-ae-2026", JD_TEXT)

    req = role_intelligence.get_requirements("acme-ae-2026")[0]
    assert req["evidence_level"] == "CONFIRMED"


def test_run_downgrades_confirmed_icp_field_with_fabricated_source_span(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(
        requirements=[],
        icp_fields={"comp_band": EvidencedField(value="$150k OTE", evidence_level="CONFIRMED", source_span="not in the jd", confidence=0.9)},
        ambiguities=[],
    ))

    role_intelligence_extraction.run("acme-ae-2026", JD_TEXT)

    icp = role_intelligence.get_icp("acme-ae-2026")
    assert icp["fields"]["comp_band"]["evidence_level"] == "INFERRED"


def test_run_records_an_agent_run_for_observability(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(requirements=[], icp_fields={}, ambiguities=[]))
    role_intelligence_extraction.run("acme-ae-2026", JD_TEXT, user_email="r1@example.com")

    from gtm_sourcing_agent import agent_observability
    runs = agent_observability.get_agent_runs("acme-ae-2026")
    assert len(runs) == 1
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["user_email"] == "r1@example.com"
    assert runs[0]["actions"][0]["tool_name"] == "extract_role_intelligence"
    assert runs[0]["actions"][0]["input_tokens"] == 100
    assert runs[0]["actions"][0]["output_tokens"] == 50
