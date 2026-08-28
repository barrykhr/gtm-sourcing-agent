import pytest
from pydantic import ValidationError

from gtm_sourcing_agent.models.candidate import Candidate, CandidatePrioritization, EvidencedFact
from gtm_sourcing_agent.models.funnel import ForecastAssumptions
from gtm_sourcing_agent.models.job_description import JobDescription


def test_job_description_requires_core_fields():
    with pytest.raises(ValidationError):
        JobDescription()  # type: ignore[call-arg]


def test_job_description_minimal_valid():
    jd = JobDescription(
        raw_jd_text="...",
        company="Acme",
        role_title="Enterprise AE",
        function="Sales",
        seniority="Senior",
        geography="US Remote",
        role_objective="Own net-new enterprise logos in fintech.",
    )
    assert jd.core_responsibilities == []
    assert jd.contradictions == []


def test_evidenced_fact_rejects_unknown_evidence_level():
    with pytest.raises(ValidationError):
        EvidencedFact(fact="Owned $2M territory", evidence_level="PROBABLY_TRUE")


def test_evidenced_fact_accepts_valid_levels():
    for level in ("VERIFIED", "NOT_STATED", "INFERRED"):
        EvidencedFact(fact="x", evidence_level=level)


def test_candidate_prioritization_recruiter_decision_defaults_null():
    p = CandidatePrioritization(candidate_id="c1", tier="A", why_they_fit=["strong metrics"])
    assert p.recruiter_decision is None


def test_candidate_prioritization_rejects_invalid_tier():
    with pytest.raises(ValidationError):
        CandidatePrioritization(candidate_id="c1", tier="E")


def test_candidate_round_trips_through_dict():
    c = Candidate(
        candidate_id="acme-ae-jane-doe",
        name="Jane Doe",
        achievements=[EvidencedFact(fact="Hit 130% of quota FY25", evidence_level="VERIFIED", source="LinkedIn")],
    )
    restored = Candidate(**c.model_dump())
    assert restored == c


def test_forecast_assumptions_source_is_labeled():
    with pytest.raises(ValidationError):
        ForecastAssumptions(
            source="guess",  # not a valid literal
            screen_to_hm_interview=0.5,
            hm_interview_to_final=0.5,
            final_to_offer=0.5,
            offer_to_accept=0.8,
            contacted_to_screen=0.3,
            sourced_to_contacted=0.3,
        )
