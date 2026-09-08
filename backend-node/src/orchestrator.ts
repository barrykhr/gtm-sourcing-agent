/**
 * Port of orchestrator.py -- a Claude tool-use loop over the existing
 * stage functions, job-scoped. The orchestrator's only job is to turn
 * natural language into calls to code that already exists -- the same
 * stage functions the UI buttons call, plus read-only lookups. It never
 * mutates state directly for anything that changes established criteria
 * after candidates have been evaluated: proposeHiringProfileEdit is
 * read-only and returns a proposal; the actual mutation
 * (applyHiringProfileEdit) is plain deterministic code that only runs
 * when the recruiter explicitly confirms in the UI (the /chat/confirm
 * route) -- the model is never the thing that writes that change, only
 * the thing that understands the request and explains its impact.
 *
 * Testing note, as load-bearing here as in Python: there is no way to
 * check *tool-selection quality* without real inference. runToolLoop is
 * the one function that talks to the Anthropic API; TOOL_IMPLS (plain
 * functions, not the betaZodTool-wrapped closures) is what a test would
 * call directly to verify tool execution/confirmation-gating/history
 * persistence given a tool call the model made, without depending on SDK
 * response internals.
 */
import Anthropic from "@anthropic-ai/sdk";
import { betaZodTool } from "@anthropic-ai/sdk/helpers/beta/zod";
import { z } from "zod";
import * as storage from "./db/storage.js";
import { LlmError, DEFAULT_MODEL } from "./llmClient.js";
import * as intakeStage from "./stages/intake.js";
import * as calibrationStage from "./stages/calibration.js";
import * as icpStage from "./stages/icp.js";
import * as talentMapStage from "./stages/talentMap.js";
import * as searchStrategyStage from "./stages/searchStrategy.js";
import * as prioritizationStage from "./stages/prioritization.js";
import * as screeningStage from "./stages/screening.js";
import * as outreachStage from "./stages/outreach.js";
import * as funnelStage from "./stages/funnel.js";

export const SYSTEM_PROMPT =
  "You are the recruiter's assistant inside Talyn, scoped to " +
  "one specific job — the recruiter never needs to restate which job or which " +
  "candidate they mean if it was mentioned earlier in this conversation. Use " +
  "the tools to answer questions and take the actions the recruiter asks for; " +
  "don't describe what a tool would do instead of calling it. Never state a " +
  "candidate fact as verified unless the underlying data labels it VERIFIED — " +
  "pass through NOT_STATED/INFERRED labels honestly. When the recruiter asks " +
  "to change a hiring-profile requirement (must-have, nice-to-have, " +
  "disqualifier), always call propose_hiring_profile_edit rather than " +
  "describing the change yourself — that tool does not apply anything, it " +
  "only prepares a proposal the recruiter approves or declines through the " +
  "product UI. Never treat a vague or ambiguous reply as approval.";

let _client: Anthropic | null = null;
function getClient(): Anthropic {
  if (_client === null) _client = new Anthropic();
  return _client;
}

// ── tool implementations (plain async functions -- what a direct test would call) ──

async function toolAnalyzeJd(roleId: string, jdText: string): Promise<string> {
  const result = await intakeStage.run(roleId, jdText);
  return JSON.stringify(result);
}

async function toolBuildHiringProfile(roleId: string): Promise<string> {
  await calibrationStage.run(roleId);
  const result = await icpStage.run(roleId);
  return JSON.stringify(result);
}

async function toolBuildTalentMap(roleId: string): Promise<string> {
  const result = await talentMapStage.run(roleId);
  return JSON.stringify(result);
}

async function toolCreateSourcingStrategy(roleId: string): Promise<string> {
  const result = await searchStrategyStage.run(roleId);
  return JSON.stringify(result);
}

async function toolListCandidates(roleId: string): Promise<string> {
  const state = await storage.loadRole(roleId);
  const candidates = state.candidates ?? {};
  const prioritizations = state.prioritizations ?? {};
  const rows = Object.entries(candidates).map(([cid, c]: [string, any]) => ({
    candidate_id: cid, name: c.name, current_title: c.current_title, current_company: c.current_company,
    tier: prioritizations[cid]?.tier ?? null,
  }));
  return JSON.stringify(rows);
}

async function toolGetCandidate(roleId: string, candidateId: string): Promise<string> {
  const state = await storage.loadRole(roleId);
  const candidate = (state.candidates ?? {})[candidateId];
  if (candidate === undefined) {
    return JSON.stringify({ error: `candidate '${candidateId}' not found` });
  }
  const prioritization = (state.prioritizations ?? {})[candidateId] ?? null;
  return JSON.stringify({ candidate, prioritization });
}

async function toolPrioritizeCandidate(roleId: string, candidateId: string): Promise<string> {
  const result = await prioritizationStage.run(roleId, candidateId);
  return JSON.stringify(result);
}

async function toolGenerateScreeningQuestions(roleId: string, candidateId: string): Promise<string> {
  const result = await screeningStage.run(roleId, candidateId);
  return JSON.stringify(result);
}

async function toolGenerateOutreach(roleId: string, candidateId: string): Promise<string> {
  const result = await outreachStage.run(roleId, candidateId);
  return JSON.stringify(result);
}

async function toolGetFunnelReport(roleId: string): Promise<string> {
  const result = await funnelStage.report(roleId);
  return JSON.stringify(result);
}

const PROFILE_FIELDS = ["must_have", "nice_to_have", "disqualifier"] as const;

async function toolProposeHiringProfileEdit(
  roleId: string, field: string, action: string, value: string
): Promise<string> {
  if (!(PROFILE_FIELDS as readonly string[]).includes(field)) {
    return JSON.stringify({ error: `unknown field '${field}', must be one of ${PROFILE_FIELDS.join(",")}` });
  }
  if (action !== "add" && action !== "remove") {
    return JSON.stringify({ error: `unknown action '${action}', must be 'add' or 'remove'` });
  }
  const icp = await storage.requireSection(roleId, "icp");
  const current: string[] = icp[field] ?? [];
  if (action === "remove" && !current.includes(value)) {
    return JSON.stringify({ error: `'${value}' is not currently in ${field}` });
  }
  if (action === "add" && current.includes(value)) {
    return JSON.stringify({ error: `'${value}' is already in ${field}` });
  }
  const evaluatedCount = Object.keys((await storage.loadRole(roleId)).prioritizations ?? {}).length;
  const verb = action === "remove" ? "Remove" : "Add";
  const prep = action === "remove" ? "from" : "to";
  const proposal = {
    field, action, value,
    description: `${verb} "${value}" ${prep} ${field.replace(/_/g, " ")}.`,
    impact: evaluatedCount
      ? `${evaluatedCount} candidate(s) already evaluated against the current criteria may need re-evaluation.`
      : "No candidates evaluated yet for this job — safe to apply.",
  };
  return JSON.stringify({ proposal });
}

/** The actual mutation. Deterministic, no LLM involved -- only called by
 * the /chat/confirm route after explicit recruiter approval, never by the
 * tool loop directly. */
export async function applyHiringProfileEdit(roleId: string, field: string, action: string, value: string) {
  const icp = await storage.requireSection(roleId, "icp");
  const current: string[] = [...(icp[field] ?? [])];
  if (action === "add" && !current.includes(value)) current.push(value);
  else if (action === "remove" && current.includes(value)) {
    const idx = current.indexOf(value);
    current.splice(idx, 1);
  }
  icp[field] = current;
  await storage.mergeSection(roleId, "icp", icp);
  return icp;
}

export const TOOL_IMPLS = {
  analyze_jd: toolAnalyzeJd,
  build_hiring_profile: toolBuildHiringProfile,
  build_talent_map: toolBuildTalentMap,
  create_sourcing_strategy: toolCreateSourcingStrategy,
  list_candidates: toolListCandidates,
  get_candidate: toolGetCandidate,
  prioritize_candidate: toolPrioritizeCandidate,
  generate_screening_questions: toolGenerateScreeningQuestions,
  generate_outreach: toolGenerateOutreach,
  get_funnel_report: toolGetFunnelReport,
  propose_hiring_profile_edit: toolProposeHiringProfileEdit,
};

// ── betaZodTool wrappers (what the real tool_runner sees) ──────────────
// role_id is fixed context for the whole conversation -- bound here via
// closure, never a parameter the model fills in, so the model cannot
// address a different job than the one the recruiter is looking at.

export function buildToolsForJob(roleId: string) {
  return [
    betaZodTool({
      name: "analyze_jd",
      description:
        "Run the JD intake stage: parse a job description into a structured record (company, role, " +
        "must-haves, contradictions flagged, missing information). Use when the recruiter pastes a JD " +
        "or asks you to analyse one.",
      inputSchema: z.object({ jd_text: z.string().describe("the full job description text to analyse") }),
      run: async (args) => toolAnalyzeJd(roleId, args.jd_text),
    }),
    betaZodTool({
      name: "build_hiring_profile",
      description:
        "Run hiring-manager calibration, then build the Ideal Candidate Profile (must-have / nice-to-have / " +
        "transferable / disqualifier). Requires the JD to have been analysed first.",
      inputSchema: z.object({}),
      run: async () => toolBuildHiringProfile(roleId),
    }),
    betaZodTool({
      name: "build_talent_map",
      description:
        "Build the talent-market map: target companies by tier and title intelligence. Requires a hiring " +
        "profile to exist first.",
      inputSchema: z.object({}),
      run: async () => toolBuildTalentMap(roleId),
    }),
    betaZodTool({
      name: "create_sourcing_strategy",
      description:
        "Generate search strategies (boolean strings, X-ray queries) against the talent map. Requires a " +
        "talent map to exist first.",
      inputSchema: z.object({}),
      run: async () => toolCreateSourcingStrategy(roleId),
    }),
    betaZodTool({
      name: "list_candidates",
      description:
        "List every candidate captured for this job: id, name, current role, and prioritization tier if " +
        "one has been set. Call this before referring to a candidate by name or id if you haven't already " +
        "seen the list this conversation.",
      inputSchema: z.object({}),
      run: async () => toolListCandidates(roleId),
    }),
    betaZodTool({
      name: "get_candidate",
      description:
        "Get full detail for one candidate: achievements and evidence (each labeled VERIFIED, NOT_STATED, " +
        "or INFERRED — never state one as fact if it isn't VERIFIED), and prioritization rationale if scored.",
      inputSchema: z.object({ candidate_id: z.string().describe("the candidate's id, from list_candidates") }),
      run: async (args) => toolGetCandidate(roleId, args.candidate_id),
    }),
    betaZodTool({
      name: "prioritize_candidate",
      description:
        "Score/tier a candidate (A/B/C/D) against the hiring profile, with a rationale. This is a " +
        "recommendation only — it never rejects a candidate; the recruiter decides.",
      inputSchema: z.object({ candidate_id: z.string().describe("the candidate's id, from list_candidates") }),
      run: async (args) => toolPrioritizeCandidate(roleId, args.candidate_id),
    }),
    betaZodTool({
      name: "generate_screening_questions",
      description:
        "Generate targeted screening questions for a candidate, based on what's unknown from their " +
        "prioritization. Requires the candidate to be prioritized first.",
      inputSchema: z.object({ candidate_id: z.string().describe("the candidate's id, from list_candidates") }),
      run: async (args) => toolGenerateScreeningQuestions(roleId, args.candidate_id),
    }),
    betaZodTool({
      name: "generate_outreach",
      description:
        "Draft outreach (LinkedIn note, InMail, email, two follow-ups) for a candidate. Draft only — this " +
        "never sends anything.",
      inputSchema: z.object({ candidate_id: z.string().describe("the candidate's id, from list_candidates") }),
      run: async (args) => toolGenerateOutreach(roleId, args.candidate_id),
    }),
    betaZodTool({
      name: "get_funnel_report",
      description: "Get sourcing funnel conversion metrics and the biggest leakage stage for this job.",
      inputSchema: z.object({}),
      run: async () => toolGetFunnelReport(roleId),
    }),
    betaZodTool({
      name: "propose_hiring_profile_edit",
      description:
        "Propose a change to the hiring profile's requirement lists. This does NOT apply the change — it " +
        "only prepares a proposal for the recruiter to explicitly approve, because changing requirements " +
        "after candidates have already been evaluated can invalidate their scores. Always call this instead " +
        "of just describing the change, and let the recruiter approve or decline it through the product UI " +
        "— never assume approval from an ambiguous reply.",
      inputSchema: z.object({
        field: z.enum(PROFILE_FIELDS),
        action: z.enum(["add", "remove"]),
        value: z.string().describe("the requirement text to add or remove, matching existing wording exactly for \"remove\""),
      }),
      run: async (args) => toolProposeHiringProfileEdit(roleId, args.field, args.action, args.value),
    }),
  ];
}

// ── the tool-use loop ───────────────────────────────────────────────────

export interface ChatMessage {
  role: string;
  content: any;
}

export interface ToolCallRecord {
  name: string;
  input: any;
  id: string;
  result?: string;
}

async function runToolLoop(
  model: string, system: string, tools: ReturnType<typeof buildToolsForJob>, messages: ChatMessage[]
): Promise<{ messages: ChatMessage[]; finalText: string; toolCalls: ToolCallRecord[] }> {
  const client = getClient();
  const toolCalls: ToolCallRecord[] = [];
  let finalText = "";

  try {
    const runner = client.beta.messages.toolRunner({
      model, max_tokens: 4096, system, tools, messages: messages as any,
    });

    for await (const message of runner) {
      const content = (message as any).content as any[];
      messages.push({ role: "assistant", content });
      for (const block of content) {
        if (block.type === "text") {
          finalText = block.text ?? "";
        } else if (block.type === "tool_use") {
          toolCalls.push({ name: block.name, input: block.input, id: block.id });
        }
      }

      const toolResponse = await runner.generateToolResponse();
      if (toolResponse !== null) {
        messages.push(toolResponse as any);
        const responseContent = (toolResponse as any).content ?? [];
        for (const resultBlock of responseContent) {
          for (const tc of toolCalls) {
            if (tc.id === resultBlock.tool_use_id) {
              tc.result = resultBlock.content;
            }
          }
        }
      }
    }
  } catch (e: any) {
    // Mirrors llmClient.generate()'s exception mapping -- without this,
    // the copilot's own model call (as opposed to a stage call it
    // delegates to) would crash with a raw SDK exception that route
    // handlers don't specially catch, surfacing as an opaque 500 with no
    // indication of what actually failed.
    if (e instanceof Anthropic.AuthenticationError) {
      throw new LlmError("Anthropic API authentication failed — check ANTHROPIC_API_KEY.");
    }
    if (e instanceof Anthropic.PermissionDeniedError) {
      throw new LlmError("Anthropic API key lacks required permissions.");
    }
    if (e instanceof Anthropic.NotFoundError) {
      throw new LlmError(`Anthropic model '${model}' not found.`);
    }
    if (e instanceof Anthropic.RateLimitError) {
      throw new LlmError("Anthropic API rate limit hit — retry later.");
    }
    if (e instanceof Anthropic.BadRequestError) {
      throw new LlmError(`Anthropic API rejected the request: ${e.message}`);
    }
    if (e instanceof Anthropic.APIConnectionError) {
      throw new LlmError("Network error calling the Anthropic API.");
    }
    if (e instanceof Anthropic.APIError) {
      throw new LlmError(`Anthropic API error (${e.status}): ${e.message}`);
    }
    throw e;
  }

  return { messages, finalText, toolCalls };
}

export async function runChatTurn(
  roleId: string, userMessage: string, history: ChatMessage[], args: { model?: string } = {}
): Promise<{ reply: string; history: ChatMessage[]; pending_proposal: Record<string, any> | null }> {
  const tools = buildToolsForJob(roleId);
  const messages: ChatMessage[] = [...history, { role: "user", content: userMessage }];
  const { messages: updatedMessages, finalText, toolCalls } = await runToolLoop(
    args.model ?? DEFAULT_MODEL, SYSTEM_PROMPT, tools, messages
  );

  let pendingProposal: Record<string, any> | null = null;
  for (let i = toolCalls.length - 1; i >= 0; i--) {
    const tc = toolCalls[i]!;
    if (tc.name === "propose_hiring_profile_edit") {
      let parsed: any = {};
      try {
        parsed = JSON.parse(tc.result ?? "{}");
      } catch {
        parsed = {};
      }
      if ("proposal" in parsed) {
        pendingProposal = { ...parsed.proposal, role_id: roleId };
      }
      break;
    }
  }

  return { reply: finalText, history: updatedMessages, pending_proposal: pendingProposal };
}
