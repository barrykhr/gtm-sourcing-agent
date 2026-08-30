"""Stage orchestration tests using a mocked llm_client.generate — no
network calls, no API key required (Phase 6: "no live API calls in CI").
These test what our code does around the LLM call (checkpoint gating,
storage merging, id generation, field overrides), not model output
quality — that needs a real credential and is tracked separately in
docs/implementation-plan.md as outstanding acceptance testing.
"""

import pytest

from gtm_sourcing_agent import llm_client, storage
from gtm_sourcing_agent.models import (
    Candidate,
    CandidatePrioritization,
    HiringManagerCalibration,
    IdealCandidateProfile,
    JobDescription,
    OutreachSequence,
    RoleInterviewQuestions,
    ScreeningQuestionSet,
    TalentMap,
)
from gtm_sourcing_agent.models.interview_questions import InterviewQuestion
from gtm_sourcing_agent.models.talent_map import SearchStrategy, TargetCompany
from gtm_sourcing_agent.stages import (
    calibration,
    candidate_analysis,
    icp,
    intake,
    interview_questions,
    outreach,
    prioritization,
    screening,
    search_strategy,
    talent_map,
)


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "WORKSPACE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def fake_generate(monkeypatch):
    """Replace llm_client.generate with a stub that returns a
    caller-queued fixed model instance and records every call's args, so
    tests assert what stage code did around the call without hitting the
    network."""
    calls = []
    queue = []

    def _fake(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage=""):
        calls.append({"prompt": prompt, "output_model": output_model, "stage": stage})
        return queue.pop(0)

    monkeypatch.setattr(llm_client, "generate", _fake)
    _fake.calls = calls
    _fake.queue = queue
    return _fake


def test_intake_persists_result_and_includes_jd_text_in_prompt(isolated_workspace, fake_generate):
    fixed = JobDescription(
        raw_jd_text="x", company="Acme", role_title="AE", function="Sales",
        seniority="Senior", geography="US", role_objective="Own net-new logos.",
    )
    fake_generate.queue.append(fixed)

    result = intake.run("acme-ae-2026", "Enterprise AE, own net-new logos.")

    assert result == fixed
    assert storage.load_role("acme-ae-2026")["job_description"] == fixed.model_dump()
    assert "Enterprise AE, own net-new logos." in fake_generate.calls[0]["prompt"]
    assert fake_generate.calls[0]["stage"] == "intake"


def test_calibration_requires_job_description_first(isolated_workspace, fake_generate):
    with pytest.raises(ValueError, match="job_description"):
        calibration.run("acme-ae-2026")
    assert fake_generate.calls == []  # never reached the LLM without the checkpoint


def test_calibration_persists_after_intake(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    fixed = HiringManagerCalibration(must_have_criteria=["quota history"])
    fake_generate.queue.append(fixed)

    result = calibration.run("acme-ae-2026")

    assert result == fixed
    assert storage.load_role("acme-ae-2026")["calibration"] == fixed.model_dump()


def test_icp_requires_both_upstream_sections(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    with pytest.raises(ValueError, match="calibration"):
        icp.run("acme-ae-2026")
    assert fake_generate.calls == []


def _target_companies(*names: str, n: int = 15) -> list[TargetCompany]:
    """Builds `n` TargetCompany entries, spread across the 3 tiers, with
    the given `names` first — keeps most tests above talent_map.py's
    MIN_TARGET_COMPANIES floor without hand-writing fifteen companies
    inline every time."""
    all_names = list(names) + [f"Company {i}" for i in range(n - len(names))]
    return [
        TargetCompany(name=name, tier=(i % 3) + 1, why_relevant="test fixture")
        for i, name in enumerate(all_names)
    ]


def test_talent_map_and_search_strategy_preserve_each_others_data(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(TalentMap(target_companies=_target_companies("Rippling")))
    talent_map.run("acme-ae-2026")

    state = storage.load_role("acme-ae-2026")["talent_map"]
    assert state["target_companies"][0]["name"] == "Rippling"
    assert state["search_strategies"] == []

    strategy = SearchStrategy(name="broad", search_type="broad", purpose="cast a wide net")
    fake_generate.queue.append(TalentMap(search_strategies=[strategy]))
    search_strategy.run("acme-ae-2026")

    state = storage.load_role("acme-ae-2026")["talent_map"]
    # search_strategy.run must not have clobbered the companies talent_map.run wrote
    assert state["target_companies"][0]["name"] == "Rippling"
    assert state["search_strategies"][0]["name"] == "broad"


def test_talent_map_retries_once_when_company_list_is_thin(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    too_few = TalentMap(target_companies=[TargetCompany(name="Only One", tier=1, why_relevant="x")])
    fake_generate.queue.append(too_few)
    fake_generate.queue.append(TalentMap(target_companies=_target_companies("Retried Co")))

    result = talent_map.run("acme-ae-2026")

    assert len(fake_generate.calls) == 2  # the retry actually happened
    assert result.target_companies[0].name == "Retried Co"


def test_talent_map_keeps_thin_list_if_retry_does_not_improve(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    too_few = TalentMap(target_companies=[TargetCompany(name="Original", tier=1, why_relevant="x")])
    still_too_few = TalentMap(target_companies=[TargetCompany(name="Retry", tier=1, why_relevant="x")])
    fake_generate.queue.append(too_few)
    fake_generate.queue.append(still_too_few)

    result = talent_map.run("acme-ae-2026")

    assert len(fake_generate.calls) == 2
    # retry didn't add more companies than the original, so the original is kept
    assert result.target_companies[0].name == "Original"


def test_target_company_carries_match_dimensions(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    company = TargetCompany(
        name="Rippling", tier=1, why_relevant="same everything",
        match_dimensions=["product", "business_segment", "customer_base", "industry"],
    )
    fake_generate.queue.append(TalentMap(target_companies=_target_companies() + [company]))

    result = talent_map.run("acme-ae-2026")

    rippling = next(c for c in result.target_companies if c.name == "Rippling")
    assert set(rippling.match_dimensions) == {"product", "business_segment", "customer_base", "industry"}


def test_candidate_analysis_slugifies_missing_id_and_sets_source_url(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    fake_generate.queue.append(Candidate(candidate_id="", name="Jane O'Doe"))

    result = candidate_analysis.run(
        "acme-ae-2026", "resume text", "sales", source_url="https://linkedin.com/in/janedoe"
    )

    assert result.candidate_id == "acme-ae-2026-jane-o-doe"
    assert result.source_url == "https://linkedin.com/in/janedoe"
    assert result.candidate_id in storage.load_role("acme-ae-2026")["candidates"]


def test_prioritization_never_lets_the_model_set_recruiter_decision(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    # a fake LLM response that tries to sneak a decision in
    fake_generate.queue.append(
        CandidatePrioritization(candidate_id="cand-1", tier="A", recruiter_decision="pursue")
    )

    result = prioritization.run("acme-ae-2026", "cand-1")

    assert result.recruiter_decision is None
    assert storage.load_role("acme-ae-2026")["prioritizations"]["cand-1"]["recruiter_decision"] is None


def test_prioritization_rejects_unknown_candidate(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    with pytest.raises(ValueError, match="cand-999"):
        prioritization.run("acme-ae-2026", "cand-999")
    assert fake_generate.calls == []


def test_prioritization_carries_score_rating_and_weaknesses(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(
        CandidatePrioritization(
            candidate_id="cand-1", tier="A", fit_score=82, fit_rating="GREEN",
            weaknesses=["No self-sourced pipeline evidence"],
        )
    )

    result = prioritization.run("acme-ae-2026", "cand-1")

    assert result.fit_score == 82
    assert result.fit_rating == "GREEN"
    assert result.weaknesses == ["No self-sourced pipeline evidence"]
    stored = storage.load_role("acme-ae-2026")["prioritizations"]["cand-1"]
    assert stored["fit_score"] == 82
    assert stored["fit_rating"] == "GREEN"


def test_interview_questions_requires_icp_and_calibration(isolated_workspace, fake_generate):
    with pytest.raises(ValueError, match="icp"):
        interview_questions.run("acme-ae-2026")
    assert fake_generate.calls == []

    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    with pytest.raises(ValueError, match="calibration"):
        interview_questions.run("acme-ae-2026")
    assert fake_generate.calls == []


def _questions(*texts: str, n: int = 10) -> RoleInterviewQuestions:
    """Builds a RoleInterviewQuestions with `n` total questions, the first
    (or first len(texts)) named explicitly and the rest padded out —
    keeps most tests above the MIN_QUESTIONS floor without hand-writing
    ten questions inline every time."""
    all_texts = list(texts) + [f"padding question {i}" for i in range(n - len(texts))]

    def make(qs: list[str]) -> list[InterviewQuestion]:
        return [InterviewQuestion(question=q, why_it_matters="w") for q in qs]

    return RoleInterviewQuestions(
        core_questions=make(all_texts[0::3]),
        role_specific_questions=make(all_texts[1::3]),
        red_flag_questions=make(all_texts[2::3]),
    )


def test_interview_questions_persists_first_generation(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": ["job-hopping"]})
    fixed = _questions("Walk me through a deal.")
    fake_generate.queue.append(fixed)

    result = interview_questions.run("acme-ae-2026")

    assert len(result.generations) == 1
    assert result.generations[0].core_questions[0].question == "Walk me through a deal."
    assert result.generations[0].generated_at  # a real timestamp, not left blank
    persisted = storage.load_role("acme-ae-2026")["interview_questions"]
    assert persisted == result.model_dump()
    prompt = fake_generate.calls[0]["prompt"]
    assert "SaaS" in prompt
    assert "job-hopping" in prompt
    assert fake_generate.calls[0]["stage"] == "interview_questions"


def test_interview_questions_regeneration_appends_a_new_generation(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": ["job-hopping"]})
    fake_generate.queue.append(_questions("First-generation question."))
    interview_questions.run("acme-ae-2026")

    fake_generate.queue.append(_questions("Second-generation question."))
    result = interview_questions.run("acme-ae-2026")

    assert len(result.generations) == 2
    assert result.generations[0].core_questions[0].question == "First-generation question."
    assert result.generations[1].core_questions[0].question == "Second-generation question."
    # the prompt for the second call includes the first generation's
    # questions so the model can avoid repeating them
    second_prompt = fake_generate.calls[1]["prompt"]
    assert "First-generation question." in second_prompt


def test_interview_questions_retries_once_when_under_the_minimum(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": ["job-hopping"]})
    too_few = RoleInterviewQuestions(
        core_questions=[InterviewQuestion(question="Only one question.", why_it_matters="w")]
    )
    fake_generate.queue.append(too_few)
    fake_generate.queue.append(_questions("Retried and sufficient."))

    result = interview_questions.run("acme-ae-2026")

    assert len(fake_generate.calls) == 2  # the retry actually happened
    assert len(result.generations) == 1  # still one generation, not two
    assert result.generations[0].core_questions[0].question == "Retried and sufficient."


def test_interview_questions_keeps_shortfall_if_retry_does_not_improve(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": ["job-hopping"]})
    too_few = RoleInterviewQuestions(
        core_questions=[InterviewQuestion(question="Original.", why_it_matters="w")]
    )
    still_too_few = RoleInterviewQuestions(
        core_questions=[InterviewQuestion(question="Retry, still short.", why_it_matters="w")]
    )
    fake_generate.queue.append(too_few)
    fake_generate.queue.append(still_too_few)

    result = interview_questions.run("acme-ae-2026")

    assert len(fake_generate.calls) == 2
    # retry didn't add more questions than the original, so the original is kept
    assert result.generations[0].core_questions[0].question == "Original."


def test_interview_questions_flags_repeats_across_generations(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": ["job-hopping"]})
    fake_generate.queue.append(_questions("Walk me through your last deal."))
    interview_questions.run("acme-ae-2026")

    # same question, different casing/whitespace — still counts as a repeat
    fake_generate.queue.append(_questions("  Walk me through your LAST deal.  "))
    result = interview_questions.run("acme-ae-2026")

    assert "  Walk me through your LAST deal.  " in result.generations[1].repeated_questions


def test_interview_questions_normalizes_old_flat_shape_on_regeneration(isolated_workspace, fake_generate):
    """Roles generated before this generation-history shape existed have
    the old flat {core_questions, role_specific_questions,
    red_flag_questions} dict persisted directly — regenerating on one of
    those roles must not lose that data."""
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": ["job-hopping"]})
    storage.merge_section("acme-ae-2026", "interview_questions", _questions("Pre-existing legacy question.").model_dump())

    fake_generate.queue.append(_questions("New generation question."))
    result = interview_questions.run("acme-ae-2026")

    assert len(result.generations) == 2
    assert result.generations[0].core_questions[0].question == "Pre-existing legacy question."
    assert result.generations[1].core_questions[0].question == "New generation question."


def test_reprioritizing_preserves_decision_and_placement(isolated_workspace, fake_generate):
    """Re-running prioritization (a "re-rank") must never silently wipe a
    recruiter's own recorded decision or placement — those come from the
    recruiter's own actions, not from this stage, and a fresh model call
    has no way to know about them."""
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(CandidatePrioritization(candidate_id="cand-1", tier="B"))
    prioritization.run("acme-ae-2026", "cand-1")
    prioritization.set_recruiter_decision("acme-ae-2026", "cand-1", "pursue")
    prioritization.set_placement("acme-ae-2026", "cand-1", placed=True, fee=15000.0)

    fake_generate.queue.append(CandidatePrioritization(candidate_id="cand-1", tier="A"))
    result = prioritization.run("acme-ae-2026", "cand-1")

    assert result.tier == "A"  # the re-rank itself did update
    assert result.recruiter_decision == "pursue"
    assert result.placed is True
    assert result.placement_fee == 15000.0
    stored = storage.load_role("acme-ae-2026")["prioritizations"]["cand-1"]
    assert stored["recruiter_decision"] == "pursue"
    assert stored["placed"] is True


def test_set_placement_marks_and_clears(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(CandidatePrioritization(candidate_id="cand-1", tier="A"))
    prioritization.run("acme-ae-2026", "cand-1")

    result = prioritization.set_placement("acme-ae-2026", "cand-1", placed=True, fee=20000.0)
    assert result["placed"] is True
    assert result["placement_fee"] == 20000.0
    assert result["placed_at"] is not None

    cleared = prioritization.set_placement("acme-ae-2026", "cand-1", placed=False)
    assert cleared["placed"] is False
    assert cleared["placement_fee"] == 0.0
    assert cleared["placed_at"] is None


def test_set_placement_requires_prioritization_first(isolated_workspace):
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    with pytest.raises(ValueError, match="not been prioritized"):
        prioritization.set_placement("acme-ae-2026", "cand-1", placed=True, fee=1000.0)


def test_set_recruiter_decision_requires_prioritization_first(isolated_workspace):
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    with pytest.raises(ValueError, match="not been prioritized"):
        prioritization.set_recruiter_decision("acme-ae-2026", "cand-1", "pursue")


def test_set_recruiter_decision_persists_without_touching_the_rest_of_the_record(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(
        CandidatePrioritization(candidate_id="cand-1", tier="B", why_they_fit=["strong resume"])
    )
    prioritization.run("acme-ae-2026", "cand-1")

    result = prioritization.set_recruiter_decision("acme-ae-2026", "cand-1", "pass for now")

    assert result == {"candidate_id": "cand-1", "recruiter_decision": "pass for now"}
    record = storage.load_role("acme-ae-2026")["prioritizations"]["cand-1"]
    assert record["recruiter_decision"] == "pass for now"
    assert record["tier"] == "B"
    assert record["why_they_fit"] == ["strong resume"]


def test_set_recruiter_decision_can_be_cleared(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "icp", {"must_have": ["SaaS"]})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(CandidatePrioritization(candidate_id="cand-1", tier="A"))
    prioritization.run("acme-ae-2026", "cand-1")
    prioritization.set_recruiter_decision("acme-ae-2026", "cand-1", "pursue")

    result = prioritization.set_recruiter_decision("acme-ae-2026", "cand-1", "")

    assert result["recruiter_decision"] is None


def test_screening_rejects_candidate_missing_its_own_prioritization(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": []})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    storage.merge_candidate("acme-ae-2026", "cand-2", {"name": "Jo"})
    # a *different* candidate has been prioritized, so the "prioritizations"
    # section is non-empty — this isolates the per-candidate check in
    # screening.py from storage.require_section's own upstream-missing check
    storage.merge_prioritization("acme-ae-2026", "cand-2", {"candidate_id": "cand-2", "tier": "A"})
    with pytest.raises(ValueError, match="not been prioritized"):
        screening.run("acme-ae-2026", "cand-1")


def test_screening_requires_prioritizations_section_to_exist_at_all(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": []})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    with pytest.raises(ValueError, match="prioritizations"):
        screening.run("acme-ae-2026", "cand-1")


def test_screening_persists_after_prioritization(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "calibration", {"red_flags": []})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    storage.merge_prioritization("acme-ae-2026", "cand-1", {"candidate_id": "cand-1", "tier": "A"})
    fake_generate.queue.append(ScreeningQuestionSet(candidate_id="", must_ask=["What was your quota?"]))

    result = screening.run("acme-ae-2026", "cand-1")

    assert result.candidate_id == "cand-1"
    assert storage.load_role("acme-ae-2026")["screening"]["cand-1"]["must_ask"] == ["What was your quota?"]


def test_outreach_persists_and_stamps_candidate_id(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(OutreachSequence(candidate_id="", email="Hi Jane, ..."))

    result = outreach.run("acme-ae-2026", "cand-1")

    assert result.candidate_id == "cand-1"
    assert storage.load_role("acme-ae-2026")["outreach"]["cand-1"]["email"] == "Hi Jane, ..."


def test_mark_sent_requires_a_draft_first(isolated_workspace):
    with pytest.raises(ValueError, match="no outreach draft"):
        outreach.mark_sent("acme-ae-2026", "cand-1")


def test_mark_sent_records_timestamp_and_advances_to_contacted(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(OutreachSequence(candidate_id="", email="Hi Jane, ..."))
    outreach.run("acme-ae-2026", "cand-1")

    result = outreach.mark_sent("acme-ae-2026", "cand-1")

    assert result["funnel_stage"] == "CONTACTED"
    assert result["sent_at"]
    state = storage.load_role("acme-ae-2026")
    assert state["outreach_log"]["cand-1"]["sent_at"] == result["sent_at"]
    assert state["funnel"]["cand-1"]["stage_history"][-1]["note"] == "outreach marked sent"


def test_mark_sent_never_moves_a_candidate_backward(isolated_workspace, fake_generate):
    storage.merge_section("acme-ae-2026", "job_description", {"company": "Acme"})
    storage.merge_candidate("acme-ae-2026", "cand-1", {"name": "Jane"})
    fake_generate.queue.append(OutreachSequence(candidate_id="", email="Hi Jane, ..."))
    outreach.run("acme-ae-2026", "cand-1")

    from gtm_sourcing_agent.stages import funnel as funnel_stage

    funnel_stage.update("acme-ae-2026", "cand-1", "HM_INTERVIEW")
    result = outreach.mark_sent("acme-ae-2026", "cand-1")

    assert result["funnel_stage"] == "HM_INTERVIEW"  # already past CONTACTED — not pulled back
