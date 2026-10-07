"""AI evaluation fixtures for stages/role_intelligence_extraction.py, per
TALYN_V2_ARCHITECTURE.md §10/§8 step 6: messy/contradictory/incomplete/
ambiguous/implicit-requirement job descriptions, checked against the
stage's *deterministic* guarantees — schema validity, the anti-
hallucination source_span guardrail, and persistence — not model
judgment quality (grading "did it extract the right requirements" needs
real inference and a human/LLM-judge rubric, out of scope for a unit
test; see orchestrator.py's module docstring for the same distinction
made there).

Each fixture mocks llm_client.generate with a response shaped the way a
real model's response to that kind of JD plausibly would be (including,
deliberately, a bad one in test_run_survives_a_fabricated_confirmed_span)
— this tests the stage's handling of that shape, not whether a real model
would actually produce it."""

import pytest

from gtm_sourcing_agent import db, db_storage, llm_client, role_intelligence
from gtm_sourcing_agent.models.role_intelligence import EvidencedField, ExtractedAmbiguity, ExtractedRequirement, RoleExtraction
from gtm_sourcing_agent.stages import role_intelligence_extraction


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db_storage.create_job("role-under-test", title="Role", owner_email="r1@example.com")
    return tmp_path


@pytest.fixture
def fake_generate(monkeypatch):
    queue = []

    def _fake(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage="", on_usage=None):
        if on_usage is not None:
            class _Usage:
                input_tokens = 1
                output_tokens = 1
            on_usage(_Usage())
        return queue.pop(0)

    monkeypatch.setattr(llm_client, "generate", _fake)
    _fake.queue = queue
    return _fake


# ── fixture 1: contradictory JD (explicit CONFLICTING requirement) ────

CONTRADICTORY_JD = (
    "Senior Account Executive. Must have 8+ years of enterprise sales experience. "
    "We're also open to high-potential junior candidates early in their career."
)


def test_contradictory_jd_produces_a_conflicting_requirement_and_an_ambiguity(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="experience", value="8+ years enterprise sales experience", priority="must_have",
            evidence_level="CONFLICTING", source_span="8+ years of enterprise sales experience",
            confidence=0.5, rationale="contradicts the junior-candidate statement below",
        )],
        icp_fields={}, ambiguities=[ExtractedAmbiguity(
            description="8+ years required vs. open to junior candidates",
            candidate_resolutions=["confirm seniority bar with hiring manager", "treat junior note as aspirational, not a real path"],
        )],
    ))

    role_intelligence_extraction.run("role-under-test", CONTRADICTORY_JD)

    reqs = role_intelligence.get_requirements("role-under-test")
    assert reqs[0]["evidence_level"] == "CONFLICTING"
    ambs = role_intelligence.get_ambiguities("role-under-test")
    assert len(ambs) == 1
    assert len(ambs[0]["candidate_resolutions"]) >= 1


# ── fixture 2: incomplete JD (almost nothing stated) ───────────────────

INCOMPLETE_JD = "Looking for a great salesperson. Fast-paced environment."


def test_incomplete_jd_produces_not_stated_rather_than_invented_requirements(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="experience", value="sales experience", priority="must_have",
            evidence_level="NOT_STATED", source_span="", confidence=0.2,
            rationale="JD gives no concrete years/domain — can't confirm or meaningfully infer",
        )],
        icp_fields={}, ambiguities=[ExtractedAmbiguity(
            description="no seniority, domain, or compensation stated",
            candidate_resolutions=["request a fuller JD from the hiring manager"],
        )],
    ))

    role_intelligence_extraction.run("role-under-test", INCOMPLETE_JD)

    reqs = role_intelligence.get_requirements("role-under-test")
    assert reqs[0]["evidence_level"] == "NOT_STATED"
    assert reqs[0]["source_span"] == ""


# ── fixture 3: implicit requirement (never stated outright) ───────────

IMPLICIT_JD = (
    "You'll own the full enterprise sales cycle end-to-end, from cold outreach "
    "through multi-stakeholder negotiation to close, carrying a $2M annual quota."
)


def test_implicit_requirement_is_inferred_not_confirmed(isolated_db, fake_generate):
    # The JD never says "5+ years" outright, but a $2M quota + full-cycle
    # ownership implies real seniority — INFERRED, not CONFIRMED, since
    # there's no literal years-of-experience statement to quote.
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="experience", value="senior, full-cycle enterprise sales experience", priority="must_have",
            evidence_level="INFERRED", source_span="", confidence=0.7,
            rationale="implied by full-cycle ownership and $2M quota size, not stated directly",
        )],
        icp_fields={}, ambiguities=[],
    ))

    role_intelligence_extraction.run("role-under-test", IMPLICIT_JD)

    reqs = role_intelligence.get_requirements("role-under-test")
    assert reqs[0]["evidence_level"] == "INFERRED"


# ── fixture 4: messy JD (unstructured, run-on, mixed signal) ──────────

MESSY_JD = (
    "hey we need someone ASAP for our sales team - needs to know salesforce "
    "and hubspot both really, prior saas background a huge plus but not "
    "dealbreaker, must be ok with travel 20% comp is competitive will discuss"
)


def test_messy_jd_still_produces_schema_valid_output_with_real_spans(isolated_db, fake_generate):
    fake_generate.queue.append(RoleExtraction(
        requirements=[
            ExtractedRequirement(
                category="skill", value="Salesforce", priority="must_have", evidence_level="CONFIRMED",
                source_span="needs to know salesforce", confidence=0.8,
            ),
            ExtractedRequirement(
                category="skill", value="HubSpot", priority="must_have", evidence_level="CONFIRMED",
                source_span="hubspot", confidence=0.8,
            ),
            ExtractedRequirement(
                category="experience", value="SaaS background", priority="nice_to_have", evidence_level="CONFIRMED",
                source_span="prior saas background a huge plus", confidence=0.7,
            ),
        ],
        icp_fields={"comp_band": EvidencedField(value="unspecified, described as competitive", evidence_level="NOT_STATED", source_span="", confidence=None)},
        ambiguities=[],
    ))

    role_intelligence_extraction.run("role-under-test", MESSY_JD)

    reqs = role_intelligence.get_requirements("role-under-test")
    assert len(reqs) == 3
    assert {r["evidence_level"] for r in reqs} == {"CONFIRMED"}
    assert all(r["source_span"] in MESSY_JD for r in reqs)


# ── fixture 5: a response that fabricates a CONFIRMED span (adversarial) ─


def test_run_survives_a_fabricated_confirmed_span_everywhere_it_appears(isolated_db, fake_generate):
    """Belt-and-suspenders on the anti-hallucination guardrail: even if
    *every* requirement and *every* ICP field claims CONFIRMED with a
    made-up quote, none of it reaches the database still labeled
    CONFIRMED."""
    fake_generate.queue.append(RoleExtraction(
        requirements=[ExtractedRequirement(
            category="comp", value="$500k OTE", priority="must_have", evidence_level="CONFIRMED",
            source_span="guaranteed $500k OTE minimum", confidence=0.99,
        )],
        icp_fields={"comp_band": EvidencedField(value="$500k OTE", evidence_level="CONFIRMED", source_span="guaranteed $500k OTE minimum", confidence=0.99)},
        ambiguities=[],
    ))

    role_intelligence_extraction.run("role-under-test", MESSY_JD)  # none of this text is in MESSY_JD

    reqs = role_intelligence.get_requirements("role-under-test")
    icp = role_intelligence.get_icp("role-under-test")
    assert reqs[0]["evidence_level"] == "INFERRED"
    assert icp["fields"]["comp_band"]["evidence_level"] == "INFERRED"
