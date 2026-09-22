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

from gtm_sourcing_agent import db_storage, file_storage, llm_client, orchestrator, transcription  # noqa: E402
from gtm_sourcing_agent.models import (  # noqa: E402
    AskInterviewAnswer,
    Candidate,
    CandidatePrioritization,
    CompetencyEvidenceRef,
    CompetencyScore,
    ConversationIntelligence,
    ConversationSummaryResult,
    FollowUpQuestionResult,
    HiringManagerCalibration,
    IdealCandidateProfile,
    InterviewCompetencyResult,
    InterviewIntelligenceResult,
    InterviewSummaryResult,
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
    # (mock) 5 companies per tier, same four-dimension logic
    # (product / business_segment / customer_base / industry) the real
    # prompt now asks for — Tier 1 shares nearly all four with this
    # role's IoT/industrial-software, enterprise-SaaS-AE persona; Tier 2
    # shares some; Tier 3 shares few but is still a real source.
    tier1 = [
        ("Samsara", "Same buyer persona (industrial ops leaders), similar deal size and cycle length.",
         ["product", "business_segment", "customer_base", "industry"]),
        ("Uptake", "Direct industrial-software competitor, comparable ACV and sales motion.",
         ["product", "customer_base", "industry"]),
        ("C3.ai", "Enterprise industrial AI platform, same buyer and deal complexity.",
         ["product", "business_segment", "customer_base", "industry"]),
        ("Augury", "Industrial IoT/predictive-maintenance product sold to the same plant-ops buyer.",
         ["product", "customer_base", "industry"]),
        ("Seeq", "Industrial analytics software, near-identical enterprise motion and buyer.",
         ["product", "business_segment", "customer_base"]),
    ]
    tier2 = [
        ("PTC", "Industrial software (PLM/IoT) — same industry and customer base, broader product line.",
         ["customer_base", "industry"]),
        ("Salesforce", "Enterprise SaaS sales motion is highly transferable even though the product differs.",
         ["business_segment", "customer_base"]),
        ("Honeywell Forge", "Industrial software arm of a legacy industrial company — same industry, different segment maturity.",
         ["customer_base", "industry"]),
        ("Cognite", "Industrial data platform — same industry, adjacent product (data infra vs. ops software).",
         ["customer_base", "industry"]),
        ("Verkada", "Enterprise IoT/security hardware+software — same enterprise segment, different industry.",
         ["product", "business_segment"]),
    ]
    tier3 = [
        ("ServiceNow", "Enterprise workflow software — same segment and deal complexity, unrelated product/industry.",
         ["business_segment"]),
        ("Palantir", "Enterprise platform sales to complex operational buyers — comparable scale and complexity.",
         ["business_segment", "customer_base"]),
        ("Datadog", "Enterprise infra SaaS — transferable technical-sale motion, different buyer and industry.",
         ["business_segment"]),
        ("Flexport", "Enterprise logistics software selling into industrial/ops buyers — adjacent customer base.",
         ["customer_base"]),
        ("Toast", "Vertical SaaS enterprise motion — comparable sales complexity from a less obvious source.",
         ["business_segment"]),
    ]
    companies = [
        TargetCompany(
            name=name, tier=tier, why_relevant=why, match_dimensions=dims,
            roles_to_target=["Enterprise AE", "Strategic AE"], seniority_levels_to_target=["Senior IC"],
        )
        for tier, group in ((1, tier1), (2, tier2), (3, tier3))
        for name, why, dims in group
    ]
    return TalentMap(
        target_companies=companies,
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
        email=f"{name.lower().replace(' ', '.')}@example.com",
        phone="+1 512-555-0142",
        current_company="Samsara",
        current_title="Enterprise Account Executive",
        location="Austin, TX",
        total_experience="6 years",
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
        competency_scores=[
            CompetencyScore(
                dimension="technical_alignment", label="Technical alignment", score=88, strength="STRONG",
                rationale="132% quota attainment on a comparable $1M enterprise quota matches the must-have bar directly.",
            ),
            CompetencyScore(
                dimension="role_motivation", label="Role motivation", score=76, strength="STRONG",
                rationale="Moved from mid-market to enterprise deals over the last two roles, the same trajectory this role continues.",
            ),
            CompetencyScore(
                dimension="team_alignment", label="Team alignment", score=71, strength="STRONG",
                rationale="Carried an individual quota with no reports, matching the ICP's individual-contributor seniority level.",
            ),
            CompetencyScore(
                dimension="communication", label="Communication", score=68, strength="STRONG",
                rationale="Resume achievements are specific and quantified (ACV, cycle length) rather than generic — a proxy signal only, not observed communication.",
            ),
            CompetencyScore(
                dimension="compensation_alignment", label="Compensation alignment", score=100, strength="CONFIRMED",
                rationale="Expected CTC is stated and falls within the ICP's compensation band.",
            ),
        ],
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


def _fake_conversation_summary(**_) -> ConversationSummaryResult:
    return ConversationSummaryResult(
        summary=(
            "(mock) Warm initial contact — candidate responded positively to the WhatsApp outreach and "
            "a follow-up call was logged; tone throughout has been receptive, no objections raised yet."
        ),
        open_items=["(mock) Confirm updated compensation expectations on the next call"],
    )


def _fake_conversation_intelligence(**_) -> ConversationIntelligence:
    return ConversationIntelligence(
        current_compensation="(mock) $165,000 base + $85,000 variable",
        expected_compensation="(mock) $190,000 OTE",
        notice_period="(mock) 30 days",
        interest_level="High",
        concerns=["(mock) Wants clarity on territory size before proceeding"],
        risks=["(mock) Currently interviewing with one other company"],
        unanswered_questions=["(mock) Has not confirmed relocation willingness"],
        recommendation="(mock) Move to interview",
    )


def _fake_interview_summary(**_) -> InterviewSummaryResult:
    return InterviewSummaryResult(
        overview="(mock) Candidate walked through a five-year enterprise sales run, gave one detailed deal example, and asked clarifying questions about territory size.",
        key_experience=["(mock) 5 years closing enterprise SaaS deals", "(mock) Managed a 9-month sales cycle across three stakeholders"],
        technical_skills=["(mock) Salesforce", "(mock) MEDDIC qualification"],
        examples_provided=["(mock) $1.2M ACV deal, 9-month cycle, three stakeholders"],
        areas_not_discussed=["(mock) Team leadership experience", "(mock) International/cross-border deals"],
        potential_followups=["(mock) Ask for a second deal example at a different deal size", "(mock) Validate team leadership claims from the resume"],
    )


def _fake_interview_intelligence(**_) -> InterviewIntelligenceResult:
    # Indices below line up with _fake_transcribe's canned 4-segment
    # transcript (mock_llm_server.py's file_storage/transcription mocks,
    # below) — [0] recruiter asks background, [1] candidate: 5 years
    # enterprise sales, [2] recruiter asks about largest deal, [3]
    # candidate: $1.2M ACV / nine-month cycle / three stakeholders.
    return InterviewIntelligenceResult(
        competencies=[
            InterviewCompetencyResult(
                competency="(mock) 5+ years closing enterprise SaaS deals", category="must_have",
                status="Strong evidence",
                rationale="(mock) Candidate directly stated five years in enterprise sales, most recently at Samsara.",
                evidence=[CompetencyEvidenceRef(segment_index=1, note="(mock) states years of experience")],
            ),
            InterviewCompetencyResult(
                competency="(mock) History of $1M+ quota attainment", category="must_have",
                status="Needs validation",
                rationale="(mock) Candidate described a $1.2M deal but never stated overall quota attainment.",
                evidence=[CompetencyEvidenceRef(segment_index=3, note="(mock) largest deal, not quota attainment")],
            ),
            InterviewCompetencyResult(
                competency="(mock) Industrial/manufacturing domain experience", category="nice_to_have",
                status="Not discussed", rationale="(mock) Never came up in this conversation.", evidence=[],
            ),
        ],
        follow_up_questions=[
            FollowUpQuestionResult(
                question="(mock) What was your quota attainment percentage over the last two years?",
                rationale="(mock) Closes the gap on quota attainment, which the $1.2M deal example doesn't confirm on its own.",
                related_competency="(mock) History of $1M+ quota attainment",
            ),
        ],
    )


def _fake_ask_interview_question(**_) -> AskInterviewAnswer:
    return AskInterviewAnswer(
        answer="(mock) The candidate described closing a $1.2M ACV deal with a nine-month sales cycle across three stakeholders.",
        citations=[CompetencyEvidenceRef(segment_index=3)],
        unable_to_answer=False,
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
    "conversation_summary": _fake_conversation_summary,
    "conversation_intelligence": _fake_conversation_intelligence,
    "interview_summary": _fake_interview_summary,
    "interview_intelligence": _fake_interview_intelligence,
    "ask_interview_question": _fake_ask_interview_question,
}


def _fake_generate(prompt, output_model, *, model=llm_client.DEFAULT_MODEL, max_tokens=0, stage=""):
    builder = _BY_STAGE.get(stage)
    if builder is None:
        raise RuntimeError(f"mock_llm_server has no canned response for stage={stage!r}")
    return builder()


llm_client.generate = _fake_generate

# Interview recording storage + transcription (Interview Intelligence,
# Phase 1) — real production code needs RESUME_STORAGE_* (S3/R2) and
# ASSEMBLYAI_API_KEY, neither of which this dev-only mock server has.
# Stand in an in-memory "bucket" and a canned transcript so the full
# record -> upload -> transcribe -> summarize pipeline is exercisable in
# a real browser without either credential.
_mock_interview_audio: dict[str, bytes] = {}


def _fake_upload_interview_recording(interview_id: str, filename: str, content: bytes, content_type: str) -> str:
    key = f"mock/interviews/{interview_id}/{filename}"
    _mock_interview_audio[key] = content
    return key


def _fake_download_file(file_key: str) -> bytes | None:
    return _mock_interview_audio.get(file_key)


def _fake_transcribe(audio_bytes, content_type):
    return [
        {"speaker": "recruiter", "text": "(mock) Thanks for joining — walk me through your background.", "start_time": 0.0, "end_time": 4.0},
        {"speaker": "candidate", "text": "(mock) Sure — I've spent the last five years in enterprise sales, most recently at Samsara.", "start_time": 4.5, "end_time": 12.0},
        {"speaker": "recruiter", "text": "(mock) What's the largest deal you've closed?", "start_time": 12.5, "end_time": 15.0},
        {"speaker": "candidate", "text": "(mock) A $1.2M ACV deal with a nine-month cycle across three stakeholders.", "start_time": 15.5, "end_time": 22.0},
    ]


file_storage.upload_interview_recording = _fake_upload_interview_recording
file_storage.download_file = _fake_download_file
transcription.transcribe = _fake_transcribe


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
