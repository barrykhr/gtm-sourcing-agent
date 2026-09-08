// Port of models/*.py -- one Zod schema per Pydantic BaseModel, field for
// field. Used both for structured-output enforcement (zodOutputFormat in
// llm_client.ts) and as the TS static types for stage return values.
// `.describe()` calls mirror Pydantic's Field(description=...) verbatim
// where Python had one -- these strings are part of what's sent to the
// model as the output schema, not just documentation, so they're ported
// with the same care as the prompt text itself.
import { z } from "zod";

// ── job_description.py ──────────────────────────────────────────────

export const RequirementClassification = z.object({
  requirement: z.string(),
  category: z.string().describe("one of: explicit | implied | unnecessary | ambiguous | overly_narrowing"),
  note: z.string().default("").describe("why it's classified this way"),
});

export const JobDescription = z.object({
  raw_jd_text: z.string(),
  company: z.string(),
  role_title: z.string(),
  function: z.string(),
  seniority: z.string(),
  geography: z.string(),
  reporting_structure: z.string().default(""),
  role_objective: z.string(),
  core_responsibilities: z.array(z.string()).default([]),
  compensation: z.string().default("").describe(
    "salary/OTE/band as stated in the JD, free text — empty if the JD never mentions it, never estimated"
  ),
  must_have_requirements: z.array(z.string()).default([]),
  nice_to_have_requirements: z.array(z.string()).default([]),
  transferable_experience: z.array(z.string()).default([]),
  disqualifiers: z.array(z.string()).default([]),
  industry_domain: z.string().default(""),
  customer_segment: z.string().default(""),
  product_exposure: z.string().default(""),
  technical_requirements: z.array(z.string()).default([]),
  commercial_requirements: z.array(z.string()).default([]),
  leadership_requirements: z.array(z.string()).default([]),
  relevant_years_experience: z.string().default(""),
  requirement_classifications: z.array(RequirementClassification).default([]).describe(
    "explicit/implied/unnecessary/ambiguous/overly-narrowing breakdown, per §1"
  ),
  contradictions: z.array(z.string()).default([]).describe("contradictions found in the JD"),
  missing_critical_information: z.array(z.string()).default([]).describe(
    "information needed before sourcing can responsibly begin"
  ),
});
export type JobDescription = z.infer<typeof JobDescription>;

// ── icp.py ───────────────────────────────────────────────────────────

export const HiringManagerCalibration = z.object({
  must_have_criteria: z.array(z.string()).default([]),
  evaluation_criteria: z.array(z.string()).default([]),
  strong_candidate_definition: z.string().default(""),
  acceptable_candidate_definition: z.string().default(""),
  weak_candidate_definition: z.string().default(""),
  red_flags: z.array(z.string()).default([]),
  transferable_profiles_worth_considering: z.array(z.string()).default([]),
  looks_good_on_paper_but_reject: z.array(z.string()).default([]),
  interview_questions_to_validate_ambiguous_areas: z.array(z.string()).default([]),
  unrealistic_requirements_flag: z.string().default("").describe(
    "non-empty only if requirements appear unrealistic for the market; explain why"
  ),
});
export type HiringManagerCalibration = z.infer<typeof HiringManagerCalibration>;

export const IdealCandidateProfile = z.object({
  target_background: z.string().default(""),
  relevant_companies: z.array(z.string()).default([]),
  relevant_industries: z.array(z.string()).default([]),
  relevant_titles: z.array(z.string()).default([]),
  adjacent_titles: z.array(z.string()).default([]),
  geography: z.string().default(""),
  seniority: z.string().default(""),
  typical_career_progression: z.string().default(""),
  customer_segment: z.string().default(""),
  product_environment: z.string().default(""),
  relevant_metrics: z.array(z.string()).default([]),
  relevant_accomplishments: z.array(z.string()).default([]),
  likely_motivations: z.array(z.string()).default([]),
  likely_objections: z.array(z.string()).default([]),
  transferable_backgrounds: z.array(z.string()).default([]),
  must_have: z.array(z.string()).default([]),
  nice_to_have: z.array(z.string()).default([]),
  transferable: z.array(z.string()).default([]),
  disqualifier: z.array(z.string()).default([]),
});
export type IdealCandidateProfile = z.infer<typeof IdealCandidateProfile>;

// ── talent_map.py ────────────────────────────────────────────────────

export const Tier = z.union([z.literal(1), z.literal(2), z.literal(3)]);
export const SearchType = z.enum([
  "broad", "targeted", "competitor", "adjacent", "transferable", "geography", "seniority",
]);
export const MatchDimension = z.enum(["product", "business_segment", "customer_base", "industry"]);

export const TargetCompany = z.object({
  name: z.string(),
  tier: Tier,
  match_dimensions: z.array(MatchDimension).default([]).describe(
    "which of product / business_segment / customer_base / industry this company actually " +
    "shares with the target role — the basis for its tier, not a separate opinion from it"
  ),
  why_relevant: z.string(),
  roles_to_target: z.array(z.string()).default([]),
  likely_talent_type: z.string().default(""),
  seniority_levels_to_target: z.array(z.string()).default([]),
  limitations: z.string().default("").describe("potential limitations of this talent pool"),
});

export const TitleIntelligence = z.object({
  exact_target_titles: z.array(z.string()).default([]),
  alternative_titles: z.array(z.string()).default([]),
  previous_titles: z.array(z.string()).default([]),
  adjacent_titles: z.array(z.string()).default([]),
  market_terminology: z.array(z.string()).default([]),
  competitor_titles: z.array(z.string()).default([]),
  geography_specific_titles: z.array(z.string()).default([]),
});

export const SearchStrategy = z.object({
  name: z.string(),
  search_type: SearchType,
  purpose: z.string().describe("what this specific search is intended to capture"),
  linkedin_boolean: z.string().default(""),
  google_xray: z.string().default(""),
  naukri_search: z.string().default(""),
  github_search: z.string().default(""),
  other_channels: z.array(z.string()).default([]),
});

export const TalentMap = z.object({
  target_companies: z.array(TargetCompany).default([]),
  title_intelligence: TitleIntelligence.default({
    exact_target_titles: [], alternative_titles: [], previous_titles: [], adjacent_titles: [],
    market_terminology: [], competitor_titles: [], geography_specific_titles: [],
  }),
  search_strategies: z.array(SearchStrategy).default([]),
});
export type TalentMap = z.infer<typeof TalentMap>;

// ── candidate.py ─────────────────────────────────────────────────────

export const EvidenceLevel = z.enum(["VERIFIED", "NOT_STATED", "INFERRED"]);
export const PriorityTier = z.enum(["A", "B", "C", "D"]);
export const FitRating = z.enum(["RED", "YELLOW", "GREEN"]);

export const EvidencedFact = z.object({
  fact: z.string(),
  evidence_level: EvidenceLevel,
  source: z.string().default("").describe("where this came from, e.g. 'LinkedIn About section'"),
});

export const Candidate = z.object({
  candidate_id: z.string().describe("stable id, e.g. slugified name + role_id"),
  name: z.string(),
  email: z.string().default("").describe("from the resume/source text; empty if never stated — never invented"),
  phone: z.string().default("").describe("from the resume/source text; empty if never stated — never invented"),
  current_company: z.string().default(""),
  current_title: z.string().default(""),
  location: z.string().default(""),
  total_experience: z.string().default("").describe(
    "e.g. '7 years', '4.5 yrs' — as stated or clearly computable from the source's own dates; " +
    "empty if not determinable, never guessed"
  ),
  current_ctc: z.string().default("").describe(
    "as stated by the candidate/source — currency and period vary, keep free text"
  ),
  expected_ctc: z.string().default("").describe(
    "as stated by the candidate/source; NOT STATED if never mentioned"
  ),
  notice_period: z.string().default("").describe(
    "e.g. 'Immediate', '30 days', '3 months'; NOT STATED if never mentioned"
  ),
  previous_relevant_companies: z.array(z.string()).default([]),
  relevant_experience_summary: z.string().default(""),
  industry: z.string().default(""),
  customer_segment: z.string().default(""),
  seniority: z.string().default(""),
  achievements: z.array(EvidencedFact).default([]),
  metrics: z.array(EvidencedFact).default([]),
  education: z.string().default("").describe("only populate when relevant to fit"),
  source_url: z.string().default(""),
  evidence_of_fit: z.array(EvidencedFact).default([]),
  missing_information: z.array(z.string()).default([]),
  concerns: z.array(z.string()).default([]),
  recommended_next_action: z.string().default(""),
});
export type Candidate = z.infer<typeof Candidate>;

export const CandidatePrioritization = z.object({
  candidate_id: z.string(),
  tier: PriorityTier,
  fit_score: z.number().int().min(0).max(100).default(0).describe(
    "0-100 fit against this job's ICP/must-haves — a number, not a replacement for the tier or rationale below"
  ),
  fit_rating: FitRating.default("YELLOW").describe(
    "RED = clear mismatch, YELLOW = partial fit / needs validation, GREEN = strong fit — " +
    "a fast visual read, tier stays the primary recommendation"
  ),
  why_they_fit: z.array(z.string()).default([]),
  weaknesses: z.array(z.string()).default([]).describe(
    "concrete gaps against the ICP's must-haves — distinct from what_is_unknown, which is missing evidence, not a weakness"
  ),
  what_is_unknown: z.array(z.string()).default([]),
  what_to_validate: z.array(z.string()).default([]),
  recruiter_decision: z.string().nullable().default(null).describe(
    "set only by the recruiter, e.g. 'pursue', 'pass for now', 'revisit in Q3'"
  ),
  placed: z.boolean().default(false).describe("set only by the recruiter — never inferred"),
  placement_fee: z.number().default(0.0).describe("set only by the recruiter, in the consultancy's own currency"),
  placed_at: z.string().nullable().default(null).describe("set only by the recruiter"),
});
export type CandidatePrioritization = z.infer<typeof CandidatePrioritization>;

// ── screening.py ─────────────────────────────────────────────────────

export const ScreeningQuestionSet = z.object({
  candidate_id: z.string(),
  must_ask: z.array(z.string()).default([]).describe(
    "validate facts/unknowns from this candidate's prioritization record"
  ),
  nice_to_ask: z.array(z.string()).default([]),
  red_flag_followups: z.array(z.string()).default([]),
});
export type ScreeningQuestionSet = z.infer<typeof ScreeningQuestionSet>;

// ── interview_questions.py ──────────────────────────────────────────

export const InterviewQuestion = z.object({
  question: z.string(),
  why_it_matters: z.string().default("").describe(
    "which must-have, red flag, or ambiguity this question is meant to validate"
  ),
});
export type InterviewQuestion = z.infer<typeof InterviewQuestion>;

export const RoleInterviewQuestions = z.object({
  core_questions: z.array(InterviewQuestion).default([]).describe("ask every candidate for this role"),
  role_specific_questions: z.array(InterviewQuestion).default([]).describe(
    "specific to what makes this role different, not generic to the function"
  ),
  red_flag_questions: z.array(InterviewQuestion).default([]).describe(
    "probe this role's specific red flags / disqualifiers"
  ),
});
export type RoleInterviewQuestions = z.infer<typeof RoleInterviewQuestions>;

export const InterviewQuestionGeneration = RoleInterviewQuestions.extend({
  generated_at: z.string().default("").describe("ISO 8601 timestamp of this generation"),
  repeated_questions: z.array(z.string()).default([]).describe(
    "questions in this generation whose text closely matches an earlier generation's — the model is " +
    "instructed not to repeat itself, but this is surfaced honestly rather than silently assumed to have worked"
  ),
});
export type InterviewQuestionGeneration = z.infer<typeof InterviewQuestionGeneration>;

export interface InterviewQuestionHistory {
  generations: InterviewQuestionGeneration[];
}

export function interviewQuestionHistoryFromRaw(raw: any): InterviewQuestionHistory {
  if (!raw) return { generations: [] };
  if ("generations" in raw) return { generations: raw.generations ?? [] };
  return { generations: [InterviewQuestionGeneration.parse({ generated_at: "", ...raw })] };
}

// ── outreach.py ──────────────────────────────────────────────────────

export const OutreachSequence = z.object({
  candidate_id: z.string(),
  linkedin_connection_note: z.string().default(""),
  linkedin_inmail: z.string().default(""),
  email: z.string().default(""),
  follow_up_1: z.string().default(""),
  follow_up_2: z.string().default(""),
  personalization_basis: z.array(z.string()).default([]).describe(
    "verified facts (candidate_id's EvidencedFacts with evidence_level=VERIFIED) actually used for " +
    "personalization; empty means this draft could not be personalized and is a generic fallback — " +
    "the recruiter should know that"
  ),
});
export type OutreachSequence = z.infer<typeof OutreachSequence>;

// ── conversation.py ──────────────────────────────────────────────────

export const InterestLevel = z.enum(["High", "Medium", "Low", "Insufficient evidence"]);

export const ConversationSummaryResult = z.object({
  summary: z.string().describe(
    "2-4 sentence rolling summary of the relationship so far across every channel — tone, where things " +
    "stand, any commitments made on either side"
  ),
  open_items: z.array(z.string()).default([]).describe(
    "concrete unresolved things from the log, e.g. 'said they'd share updated CTC by Friday'"
  ),
});
export type ConversationSummaryResult = z.infer<typeof ConversationSummaryResult>;

export const ConversationIntelligence = z.object({
  current_compensation: z.string().default("").describe("as stated in the log; empty if never mentioned"),
  expected_compensation: z.string().default("").describe("as stated in the log; empty if never mentioned"),
  notice_period: z.string().default("").describe("as stated in the log; empty if never mentioned"),
  location: z.string().default("").describe("as stated in the log; empty if never mentioned"),
  relocation_willingness: z.string().default("").describe("as stated in the log; empty if never discussed"),
  relevant_experience: z.string().default("").describe(
    "relevant experience the candidate raised in conversation, distinct from resume-derived evidence"
  ),
  leadership: z.string().default("").describe(
    "anything the candidate said about managing/leading people or projects; empty if not discussed"
  ),
  motivation: z.string().default("").describe("why they're engaging with this role/move, in their own stated terms"),
  interest_level: InterestLevel.default("Insufficient evidence"),
  concerns: z.array(z.string()).default([]).describe("hesitations or worries the candidate raised"),
  risks: z.array(z.string()).default([]).describe(
    "risk signals for the recruiter to weigh — distinct from the candidate's own stated concerns"
  ),
  unanswered_questions: z.array(z.string()).default([]).describe(
    "questions asked (by either side) that the log shows were never answered"
  ),
  recommendation: z.string().default("Insufficient evidence").describe(
    "a next step, e.g. \"Move to interview\" — or literally \"Insufficient evidence\" if the log is too thin to recommend one"
  ),
});
export type ConversationIntelligence = z.infer<typeof ConversationIntelligence>;
