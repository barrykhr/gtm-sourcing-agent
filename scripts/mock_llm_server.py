"""Dev-only helper: runs the FastAPI service with llm_client.generate AND
orchestrator.run_chat_turn monkeypatched to return plausible canned
responses, so the frontend (and a human) can exercise the product end to
end without a real ANTHROPIC_API_KEY. NEVER use this for anything but
local UI development — every response below is fabricated, and the chat
mock is a fixed keyword trigger, not natural language understanding (see
_fake_run_chat_turn's docstring).

Usage:
    cd gtm-sourcing-agent
    source .venv/bin/activate
    python scripts/mock_llm_server.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gtm_sourcing_agent import db_storage, llm_client, orchestrator  # noqa: E402
from gtm_sourcing_agent.models import (  # noqa: E402
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
from gtm_sourcing_agent.models.interview_questions import InterviewQuestion  # noqa: E402
from gtm_sourcing_agent.models.candidate import EvidencedFact  # noqa: E402
from gtm_sourcing_agent.models.talent_map import (  # noqa: E402
    SearchStrategy,
    TargetCompany,
    TitleIntelligence,
)

_CANDIDATE_NAMES = ["Priya Sharma", "Marcus Chen", "Elena Volkov", "Jordan Reyes"]
_candidate_counter = {"n": 0}


def _fake_job_description(**_) -> JobDescription:
    return JobDescription(
        raw_jd_text="(mock) Enterprise Account Executive, SaaS, $2-5M territory.",
        company="Acme Robotics",
        role_title="Enterprise Account Executive",
        function="Sales",
        seniority="Senior",
        geography="US Remote",
        reporting_structure="Reports to VP Sales",
        role_objective="Own net-new enterprise logos in industrial robotics software.",
        core_responsibilities=["Prospect and close $150k+ ACV deals", "Manage a 9-12 month sales cycle"],
        must_have_requirements=["5+ years closing enterprise SaaS", "History of $1M+ quota attainment"],
        nice_to_have_requirements=["Industrial/manufacturing domain experience"],
        transferable_experience=["Enterprise sales in adjacent verticals"],
        disqualifiers=["No closing experience, only SDR background"],
        industry_domain="Industrial software",
        customer_segment="Enterprise",
        relevant_years_experience="5-10 years",
        contradictions=["JD asks for '3-5 years' in the summary but 'senior, 8+ years' in requirements"],
        missing_critical_information=["Compensation band / OTE not specified"],
    )


def _fake_calibration(**_) -> HiringManagerCalibration:
    return HiringManagerCalibration(
        must_have_criteria=["$1M+ quota attainment in last 2 years", "Enterprise (not SMB) closing experience"],
        evaluation_criteria=["ACV size", "Sales cycle length managed", "Logo quality"],
        strong_candidate_definition="Consistently 100%+ of a $1M+ quota selling into enterprise accounts.",
        acceptable_candidate_definition="80-100% attainment with strong deal narratives.",
        weak_candidate_definition="Inconsistent attainment or primarily SMB/transactional deals.",
        red_flags=["Job-hops under 12 months repeatedly", "Cannot name specific ACV or quota numbers"],
        transferable_profiles_worth_considering=["Strong SDR/BDR promoted internally to closer with 2+ years quota-carrying"],
        looks_good_on_paper_but_reject=["Big-logo companies but SMB/mid-market book, not enterprise"],
        interview_questions_to_validate_ambiguous_areas=["Walk me through your largest deal — ACV, cycle length, stakeholders"],
    )


def _fake_icp(**_) -> IdealCandidateProfile:
    return IdealCandidateProfile(
        target_background="Enterprise AE at a Series C+ vertical SaaS company",
        relevant_companies=["Samsara", "Uptake", "C3.ai"],
        relevant_titles=["Enterprise Account Executive", "Strategic Account Executive"],
        adjacent_titles=["Senior Account Executive", "Named Account Executive"],
        geography="US, remote-friendly",
        seniority="Senior IC, 5-10 years",
        customer_segment="Enterprise (5000+ employees)",
        relevant_metrics=["Quota attainment %", "ACV", "Sales cycle length"],
        must_have=["Enterprise closing experience", "$1M+ quota history"],
        nice_to_have=["Industrial/manufacturing domain"],
        transferable=["Adjacent vertical SaaS enterprise sales"],
        disqualifier=["SMB-only or SDR-only background"],
    )


def _fake_talent_map(**_) -> TalentMap:
    return TalentMap(
        target_companies=[
            TargetCompany(name="Samsara", tier=1, why_relevant="Same buyer persona, similar deal size and cycle length.", roles_to_target=["Enterprise AE"], seniority_levels_to_target=["Senior IC"]),
            TargetCompany(name="Uptake", tier=1, why_relevant="Direct industrial-software competitor, comparable ACV.", roles_to_target=["Enterprise AE", "Strategic AE"]),
            TargetCompany(name="Salesforce", tier=2, why_relevant="Enterprise sales motion is transferable even though the product differs.", roles_to_target=["Enterprise AE"], limitations="Larger brand may mean less hunting experience."),
        ],
        title_intelligence=TitleIntelligence(
            exact_target_titles=["Enterprise Account Executive"],
            adjacent_titles=["Strategic Account Executive", "Named Account Executive"],
            market_terminology=["Enterprise AE", "Strategic AE"],
        ),
    )


def _fake_search_strategy(**_) -> TalentMap:
    return TalentMap(
        search_strategies=[
            SearchStrategy(
                name="Broad enterprise AE", search_type="broad",
                purpose="Cast a wide net across enterprise SaaS AEs before narrowing.",
                linkedin_boolean='"Enterprise Account Executive" AND (SaaS OR "B2B software") AND "quota"',
            ),
            SearchStrategy(
                name="Tier 1 competitors", search_type="competitor",
                purpose="Direct industrial-software competitor AEs.",
                linkedin_boolean='"Account Executive" AND (Samsara OR Uptake OR "C3.ai")',
            ),
        ]
    )


def _fake_candidate(**_) -> Candidate:
    _candidate_counter["n"] += 1
    name = _CANDIDATE_NAMES[(_candidate_counter["n"] - 1) % len(_CANDIDATE_NAMES)]
    return Candidate(
        candidate_id="",
        name=name,
        current_company="Samsara",
        current_title="Enterprise Account Executive",
        location="Austin, TX",
        current_ctc="$165,000 base + $85,000 variable",
        expected_ctc="$190,000 OTE",
        notice_period="30 days",
        previous_relevant_companies=["Salesforce", "Outreach"],
        relevant_experience_summary="4 years enterprise AE at Samsara, 2 years mid-market AE at Salesforce.",
        industry="IoT / industrial software",
        customer_segment="Enterprise",
        achievements=[
            EvidencedFact(fact="132% of quota FY25 ($1.3M closed on $1M quota)", evidence_level="VERIFIED", source="LinkedIn About section"),
            EvidencedFact(fact="Managed a 9-month average sales cycle", evidence_level="INFERRED", source="deal cadence implied by role tenure vs. deal count"),
        ],
        metrics=[EvidencedFact(fact="Average ACV $180k", evidence_level="VERIFIED", source="LinkedIn post")],
        concerns=["No visibility into win rate"],
        recommended_next_action="Screen — validate deal cycle and ACV consistency.",
    )


def _fake_prioritization(**_) -> CandidatePrioritization:
    return CandidatePrioritization(
        candidate_id="",
        tier="A",
        fit_score=87,
        fit_rating="GREEN",
        why_they_fit=["132% quota attainment matches the must-have bar", "Enterprise segment at a comparable company"],
        weaknesses=["No visibility into win rate or self-sourced vs. inbound split"],
        what_is_unknown=["Win rate", "Whether deals were self-sourced or inbound"],
        what_to_validate=["Ask for a specific deal walkthrough with ACV and cycle length"],
    )


def _fake_screening(**_) -> ScreeningQuestionSet:
    return ScreeningQuestionSet(
        candidate_id="",
        must_ask=["You closed 132% of a $1M quota — walk me through your 3 largest deals: ACV, cycle length, and how self-sourced they were."],
        nice_to_ask=["What CRM/sales stack did you use at Samsara?"],
        red_flag_followups=["Have you had a quarter below 60% attainment? What happened?"],
    )


_interview_question_generation_counter = {"n": 0}

# Larger than what's picked per generation, so successive calls rotate
# through a different subset — a stand-in for "the model found new
# angles instead of repeating itself," so the generation-history UI has
# something real to show across multiple regenerations.
_CORE_QUESTION_POOL = [
    ("Walk me through your last 3 closed deals — ACV, cycle length, and how self-sourced they were.",
     "Validates the $1M+ quota / enterprise-closing must-have."),
    ("How did you break into net-new accounts vs. expand existing ones?",
     "Confirms hunter vs. farmer mix expected for this seat."),
    ("Describe your typical sales cycle from first meeting to signature — who else gets involved along the way?",
     "Validates enterprise cycle complexity and multi-stakeholder navigation."),
    ("What CRM and forecasting discipline have you used to manage a $1M+ pipeline?",
     "Validates process rigor expected at this quota level."),
    ("How do you build a business case that survives a procurement or legal review?",
     "Probes enterprise deal-closing mechanics beyond the initial pitch."),
    ("What does a strong month-over-month pipeline-generation cadence look like for you, concretely?",
     "Confirms self-sourced pipeline habit, not just working inbound leads."),
]
_ROLE_SPECIFIC_QUESTION_POOL = [
    ("Have you sold into industrial/manufacturing buyers before? What was different about that sales motion?",
     "This role's ICP calls out industrial/manufacturing domain as nice-to-have."),
    ("How do you adapt your pitch for a technical buyer vs. an economic buyer in the same deal?",
     "Validates multi-stakeholder selling for this segment."),
    ("What's the largest deal you've closed, and who were the internal champions who got it over the line?",
     "Confirms deal-size fit for this seat."),
    ("Tell me about a deal where the technical evaluation nearly killed it — how did you keep it alive?",
     "Probes domain credibility with technical buyers, called out in the ICP."),
    ("How would you segment and prioritize a territory in this industry if you started today?",
     "Validates territory-planning skill specific to this role's market."),
]
_RED_FLAG_QUESTION_POOL = [
    ("Tell me about a quarter you missed — what happened and what did you change?",
     "Probes the calibration's red flag: inconsistent attainment."),
    ("Have you ever inherited a book of business rather than sourced it yourself? How much of your number came from each?",
     "Probes self-sourced vs. inherited pipeline, a common looks-good-on-paper-but-reject pattern."),
    ("Describe a deal you lost late-stage — what would you do differently with what you know now?",
     "Probes resilience and deal-qualification discipline."),
    ("Walk me through a time a deal stalled in legal or procurement for months — how did you keep it moving?",
     "Probes the calibration's red flag around deals that stall and never close."),
]


def _fake_interview_questions(**_) -> RoleInterviewQuestions:
    offset = _interview_question_generation_counter["n"]
    _interview_question_generation_counter["n"] += 1

    def _pick(pool: list[tuple[str, str]], count: int) -> list[InterviewQuestion]:
        return [
            InterviewQuestion(question=q, why_it_matters=w)
            for q, w in (pool[(offset + i) % len(pool)] for i in range(count))
        ]

    return RoleInterviewQuestions(
        core_questions=_pick(_CORE_QUESTION_POOL, 4),
        role_specific_questions=_pick(_ROLE_SPECIFIC_QUESTION_POOL, 3),
        red_flag_questions=_pick(_RED_FLAG_QUESTION_POOL, 3),
    )


def _fake_outreach(**_) -> OutreachSequence:
    return OutreachSequence(
        candidate_id="",
        linkedin_connection_note="Hi — noticed your enterprise AE run at Samsara, exploring something in industrial software that might be a strong next step. Open to a quick chat?",
        email="Hi {name},\n\nSaw your 132% attainment at Samsara — that kind of enterprise closing track record is exactly what we're looking for on a new Enterprise AE seat at Acme Robotics.\n\nWorth 15 minutes this week?\n\nBest,\nRecruiter",
        personalization_basis=["132% of quota FY25 ($1.3M closed on $1M quota)"],
    )


_BY_STAGE = {
    "intake": _fake_job_description,
    "calibration": _fake_calibration,
    "icp": _fake_icp,
    "talent_map": _fake_talent_map,
    "search_strategy": _fake_search_strategy,
    "interview_questions": _fake_interview_questions,
    "candidate_analysis": _fake_candidate,
    "prioritization": _fake_prioritization,
    "screening": _fake_screening,
    "outreach": _fake_outreach,
}


def _fake_generate(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage=""):
    builder = _BY_STAGE.get(stage)
    if builder is None:
        raise RuntimeError(f"mock_llm_server has no canned response for stage={stage!r}")
    return builder()


llm_client.generate = _fake_generate


def _fake_run_chat_turn(role_id, user_message, history, *, storage_backend=db_storage, model=None):
    """Scripted stand-in for orchestrator.run_chat_turn — NOT natural
    language understanding, just a fixed keyword trigger so the chat UI's
    plumbing (message round-trip, tool execution, the confirm-before-
    mutate flow) is exercisable in a real browser without live inference.
    Real tool-selection quality is unverified in this environment — see
    docs/product-plan.md Phase 3.

    Type a message starting with "propose_remove:" followed by the exact
    must-have text to see the confirm/decline flow; anything else lists
    candidates and reports the count.
    """
    lowered = user_message.strip()
    if lowered.lower().startswith("propose_remove:"):
        value = lowered.split(":", 1)[1].strip()
        result = json.loads(
            orchestrator.TOOL_IMPLS["propose_hiring_profile_edit"](
                role_id, storage_backend, "must_have", "remove", value
            )
        )
        if "proposal" in result:
            reply = f'Here\'s what removing "{value}" would do — see below.'
            pending = {**result["proposal"], "role_id": role_id}
        else:
            reply = f"I couldn't propose that: {result['error']}"
            pending = None
    else:
        candidates = json.loads(orchestrator.TOOL_IMPLS["list_candidates"](role_id, storage_backend))
        reply = (
            f"You have {len(candidates)} candidate(s) so far: "
            + ", ".join(c["name"] for c in candidates)
            if candidates
            else "No candidates captured for this job yet."
        )
        pending = None

    new_history = [
        *history,
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": [{"type": "text", "text": reply}]},
    ]
    return {"reply": reply, "history": new_history, "pending_proposal": pending}


orchestrator.run_chat_turn = _fake_run_chat_turn

if __name__ == "__main__":
    import os

    import uvicorn

    from gtm_sourcing_agent.api import app

    print("Mock LLM dev server — every stage returns fabricated data. Do not use for real sourcing.")
    # Local dev binds 127.0.0.1 only; a hosted deploy (Render et al.) sets
    # $PORT and needs 0.0.0.0 to accept connections from outside the
    # container at all.
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host=host, port=port)
