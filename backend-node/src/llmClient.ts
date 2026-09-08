// Port of llm_client.py -- one place for model choice, system prompt,
// prompt rendering, and error handling, used by every AI stage.
//
// Python calls `client.messages.parse(..., output_format=PydanticModel)`
// and reads `response.parsed_output`. The Node SDK's equivalent (added
// in @anthropic-ai/sdk 0.5x+) is `client.messages.parse({..., output_config:
// { format: zodOutputFormat(ZodSchema) }})` / `message.parsed_output` --
// same server-side structured-output enforcement, just a different
// parameter name. See @anthropic-ai/sdk/helpers/zod.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import type { z } from "zod";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROMPTS_DIR = path.join(__dirname, "prompts");

export const DEFAULT_MODEL = "claude-sonnet-5";
export const DEFAULT_MAX_TOKENS = 16000;

export const SYSTEM_PROMPT =
  "You are a senior recruiting research assistant operating under a strict " +
  "evidence-discipline policy. For every candidate-facing fact, label it " +
  "VERIFIED (explicitly stated in the source), NOT_STATED (looked for and " +
  "absent), or INFERRED (a reasonable read that isn't explicit) — never " +
  "present an inferred or absent fact as verified, and never invent " +
  "information to fill a gap. You never make a final hiring, rejection, or " +
  "send decision — every output is a recommendation for the recruiter, who " +
  "remains the decision-maker. Follow the field-level instructions in the " +
  "user prompt exactly.";

let _client: Anthropic | null = null;

function getClient(): Anthropic {
  if (_client === null) _client = new Anthropic();
  return _client;
}

const templateCache = new Map<string, string>();

export function renderPrompt(templateName: string, context: Record<string, unknown>): string {
  let template = templateCache.get(templateName);
  if (template === undefined) {
    template = fs.readFileSync(path.join(PROMPTS_DIR, templateName), "utf-8");
    templateCache.set(templateName, template);
  }
  return template.replace(/\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g, (_match, key: string) => {
    const value = context[key];
    return value === undefined ? "" : String(value);
  });
}

export class LlmError extends Error {}

export async function generate<Schema extends z.ZodType>(
  prompt: string,
  outputModel: Schema,
  args: { model?: string; maxTokens?: number; stage?: string } = {}
): Promise<z.infer<Schema>> {
  const model = args.model ?? DEFAULT_MODEL;
  const maxTokens = args.maxTokens ?? DEFAULT_MAX_TOKENS;
  const stage = args.stage ?? "";
  const client = getClient();

  let response;
  try {
    response = await client.messages.parse({
      model,
      max_tokens: maxTokens,
      system: SYSTEM_PROMPT,
      messages: [{ role: "user", content: prompt }],
      output_config: { format: zodOutputFormat(outputModel) },
    });
  } catch (e: any) {
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

  if (response.stop_reason === "refusal") {
    throw new LlmError(`Claude declined to generate a response (stage=${stage || "?"}).`);
  }

  return outputModel.parse(response.parsed_output);
}
