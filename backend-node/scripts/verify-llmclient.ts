/**
 * Verifies llmClient.ts's request/response plumbing end-to-end against a
 * real HTTP server (not a mock of the SDK itself) standing in for the
 * Anthropic API, since no ANTHROPIC_API_KEY is available in this sandbox
 * to hit the real API. This proves: renderPrompt() interpolation, the
 * request actually reaching messages.parse with output_config set from
 * zodOutputFormat, and generate() correctly unwrapping parsed_output --
 * plus the refusal and 4xx/5xx error-mapping paths, matching Python's
 * generate()'s own exception mapping.
 */
import http from "node:http";
import { z } from "zod";
import { Candidate } from "../src/models.js";

let failures = 0;
function check(label: string, ok: boolean, detail?: unknown) {
  if (ok) console.log(`PASS: ${label}`);
  else { console.log(`FAIL: ${label}`, detail ?? ""); failures++; }
}

const FAKE_CANDIDATE = {
  candidate_id: "test-candidate-1", name: "Jamie Rivera", email: "jamie@example.com",
  current_company: "Acme Corp", current_title: "Senior AE",
};

let lastRequestBody: any = null;
let mode: "ok" | "refusal" | "ratelimit" = "ok";

const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    lastRequestBody = JSON.parse(body);
    if (mode === "ratelimit") {
      res.writeHead(429, { "content-type": "application/json" });
      res.end(JSON.stringify({ type: "error", error: { type: "rate_limit_error", message: "slow down" } }));
      return;
    }
    if (mode === "refusal") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        id: "msg_1", type: "message", role: "assistant", model: lastRequestBody.model,
        content: [], stop_reason: "refusal", stop_sequence: null,
        usage: { input_tokens: 10, output_tokens: 0 },
      }));
      return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      id: "msg_1", type: "message", role: "assistant", model: lastRequestBody.model,
      content: [{ type: "text", text: JSON.stringify(FAKE_CANDIDATE) }],
      stop_reason: "end_turn", stop_sequence: null,
      usage: { input_tokens: 42, output_tokens: 17 },
    }));
  });
});

async function main() {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as any).port;
  process.env.ANTHROPIC_BASE_URL = `http://127.0.0.1:${port}`;
  process.env.ANTHROPIC_API_KEY = "sk-test-not-real";

  // Import after env vars are set, since the SDK client reads them at construction time.
  const llmClient = await import("../src/llmClient.js");

  const prompt = llmClient.renderPrompt("candidate_analysis.md", {
    candidate_source_text: "Jamie Rivera, Senior AE at Acme Corp.", role_family: "sales",
  });
  check("renderPrompt interpolates {{ var }} placeholders", prompt.includes("Jamie Rivera, Senior AE at Acme Corp."), prompt.slice(0, 120));
  check("renderPrompt interpolates role_family", prompt.includes(": sales"), prompt);

  mode = "ok";
  const result = await llmClient.generate(prompt, Candidate, { stage: "candidate_analysis" });
  check("generate() returns a value matching the Zod schema (parsed_output round-trip)",
    result.name === "Jamie Rivera" && result.candidate_id === "test-candidate-1", result);
  check("request sent the rendered prompt as the user message",
    lastRequestBody.messages[0].content === prompt);
  check("request set the exact system prompt", lastRequestBody.system === llmClient.SYSTEM_PROMPT);
  check("request included output_config.format built from the Zod schema",
    lastRequestBody.output_config?.format?.type === "json_schema", lastRequestBody.output_config);
  check("request used the stage-appropriate model", lastRequestBody.model === llmClient.DEFAULT_MODEL);

  mode = "refusal";
  let refusalThrew = false;
  try {
    await llmClient.generate(prompt, Candidate, { stage: "candidate_analysis" });
  } catch (e: any) {
    refusalThrew = e instanceof llmClient.LlmError;
  }
  check("a refusal stop_reason raises LlmError (matches Python's RuntimeError->502 mapping)", refusalThrew);

  mode = "ratelimit";
  let rateLimitThrew = false;
  try {
    await llmClient.generate(prompt, Candidate, { stage: "candidate_analysis" });
  } catch (e: any) {
    rateLimitThrew = e instanceof llmClient.LlmError && /rate limit/i.test(e.message);
  }
  check("a 429 response raises LlmError with a rate-limit message", rateLimitThrew);

  server.close();
  console.log(failures === 0 ? "\nALL CHECKS PASSED" : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
