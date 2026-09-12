/**
 * Dev-only stand-in for the Anthropic API, for exercising the real
 * Fastify server + real Postgres + real task queue end-to-end without a
 * real ANTHROPIC_API_KEY -- the Node equivalent of
 * scripts/mock_llm_server.py's role, but as an actual HTTP server (since
 * llmClient.ts talks to the API over HTTP, there's no in-process
 * function to monkeypatch the way Python's llm_client.generate is).
 *
 * Dispatches a canned, schema-appropriate response by inspecting which
 * fields the request's output_config.format.schema requires -- every
 * one of this repo's Zod models has at least one field name unique
 * enough to key off of.
 *
 * Usage: ANTHROPIC_BASE_URL=http://127.0.0.1:8790 tsx src/server.ts
 *        (in another terminal) tsx scripts/mock-anthropic-server.ts
 */
import http from "node:http";

const PORT = Number(process.argv[2] ?? 8790);

function pick<T>(items: T[], n: number): T {
  return items[n % items.length]!;
}

let counter = 0;

function responseFor(properties: Record<string, unknown>): any {
  const has = (k: string) => k in properties;

  if (has("raw_jd_text")) {
    return {
      raw_jd_text: "(mock) Enterprise Account Executive JD.", company: "Acme Robotics",
      role_title: "Enterprise Account Executive", function: "Sales", seniority: "Senior", geography: "US Remote",
      role_objective: "Own net-new enterprise logos.",
      must_have_requirements: ["5+ years closing enterprise SaaS"], nice_to_have_requirements: ["Industrial domain"],
    };
  }
  if (has("must_have_criteria")) {
    return {
      must_have_criteria: ["Closed $1M+ ACV deals"], evaluation_criteria: ["Discovery quality"],
      strong_candidate_definition: "Consistently over quota", red_flags: ["Job hops under 12 months"],
    };
  }
  if (has("target_background")) {
    return {
      target_background: "Enterprise SaaS AE", relevant_titles: ["Enterprise Account Executive"],
      must_have: ["5+ years closing enterprise SaaS"], nice_to_have: ["Industrial/manufacturing domain"],
    };
  }
  if (has("target_companies")) {
    const n = counter++;
    const companies = Array.from({ length: 16 }, (_, i) => ({
      name: `Target Co ${n}-${i + 1}`, tier: pick([1, 2, 3], i), why_relevant: "shares product + customer base",
      match_dimensions: ["product", "customer_base"], roles_to_target: ["Enterprise AE"],
    }));
    return {
      target_companies: companies,
      title_intelligence: { exact_target_titles: ["Enterprise Account Executive"] },
      search_strategies: [{ name: "Naukri broad", search_type: "broad", purpose: "cast a wide net", naukri_search: "title:AE" }],
    };
  }
  if (has("core_questions")) {
    const q = (label: string, n: number) => Array.from({ length: n }, (_, i) => ({ question: `${label} question ${i + 1} (mock)`, why_it_matters: "validates a must-have" }));
    return { core_questions: q("Core", 4), role_specific_questions: q("Role-specific", 4), red_flag_questions: q("Red-flag", 3) };
  }
  if (has("current_ctc")) {
    const names = ["Priya Sharma", "Marcus Chen", "Elena Volkov", "Jordan Reyes"];
    const name = pick(names, counter++);
    return {
      candidate_id: "", name, email: `${name.toLowerCase().replace(/\s+/g, ".")}@example.com`,
      current_company: "Globex Corp", current_title: "Senior Enterprise AE", total_experience: "7 years",
      evidence_of_fit: [{ fact: "Closed $1.2M ACV deal in FY24", evidence_level: "VERIFIED", source: "resume" }],
    };
  }
  if (has("fit_score")) {
    return {
      candidate_id: "", tier: "A", fit_score: 87, fit_rating: "GREEN",
      why_they_fit: ["Strong closing history", "Relevant industry background"],
    };
  }
  if (has("must_ask")) {
    return { candidate_id: "", must_ask: ["Walk me through your largest closed deal"], nice_to_ask: ["Why this role?"] };
  }
  if (has("linkedin_connection_note")) {
    return {
      candidate_id: "", email: "Hi {name}, I came across your background at Globex and thought of our Enterprise AE opening...",
      linkedin_connection_note: "Enjoyed learning about your work at Globex -- would love to connect.",
      personalization_basis: ["Closed $1.2M ACV deal in FY24"],
    };
  }
  if (has("open_items")) {
    return { summary: "(mock) Initial outreach sent; candidate has not yet responded.", open_items: ["Awaiting reply to outreach"] };
  }
  if (has("interest_level")) {
    return { current_compensation: "", interest_level: "Insufficient evidence", recommendation: "Insufficient evidence" };
  }
  throw new Error(`mock-anthropic-server: no canned response matches this schema: ${Object.keys(properties).join(", ")}`);
}

// Copilot chat (orchestrator.ts's beta.messages.toolRunner) posts here
// too -- a `tools` array with no `output_config` distinguishes it from
// a stage's structured-output call. Same "canned, not clever" contract
// as responseFor(): a keyword trigger on the recruiter's own message
// picks a tool, exactly like scripts/mock_llm_server.py's
// _fake_run_chat_turn does in the Python demo server -- not real
// tool-selection reasoning, just enough to drive a real end-to-end
// exchange (real tool execution, real DB) for manual/E2E testing.
function chatResponseFor(body: any): { content: any[]; stopReason: string } {
  const messages: any[] = body.messages ?? [];
  const last = messages[messages.length - 1];
  const lastHasToolResult = Array.isArray(last?.content) && last.content.some((b: any) => b?.type === "tool_result");
  if (lastHasToolResult) {
    return { content: [{ type: "text", text: "Done — see above." }], stopReason: "end_turn" };
  }

  const toolNames = new Set((body.tools ?? []).map((t: any) => t.name));
  const lastUserText = typeof last?.content === "string" ? last.content : "";

  if (toolNames.has("propose_hiring_profile_edit") && /\badd\b/i.test(lastUserText)) {
    const value = lastUserText.replace(/.*\badd\b/i, "").replace(/\bas a?\s*must[- ]?have\b/i, "").trim() || "Kubernetes";
    return {
      content: [{
        type: "tool_use", id: `toolu_mock_${Date.now()}`, name: "propose_hiring_profile_edit",
        input: { field: "must_have", action: "add", value },
      }],
      stopReason: "tool_use",
    };
  }
  if (toolNames.has("list_candidates")) {
    return {
      content: [{ type: "tool_use", id: `toolu_mock_${Date.now()}`, name: "list_candidates", input: {} }],
      stopReason: "tool_use",
    };
  }
  return { content: [{ type: "text", text: "(mock) I don't have a canned action for that -- try asking who the candidates are." }], stopReason: "end_turn" };
}

const server = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    try {
      const body = JSON.parse(raw);
      const isChatToolCall = Array.isArray(body.tools) && !body.output_config;
      if (isChatToolCall) {
        const { content, stopReason } = chatResponseFor(body);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({
          id: `msg_mock_${Date.now()}`, type: "message", role: "assistant", model: body.model,
          content, stop_reason: stopReason, stop_sequence: null,
          usage: { input_tokens: 100, output_tokens: 80 },
        }));
        return;
      }
      const schema = body?.output_config?.format?.schema;
      const properties = schema?.properties ?? {};
      const canned = responseFor(properties);
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        id: `msg_mock_${Date.now()}`, type: "message", role: "assistant", model: body.model,
        content: [{ type: "text", text: JSON.stringify(canned) }],
        stop_reason: "end_turn", stop_sequence: null,
        usage: { input_tokens: 100, output_tokens: 80 },
      }));
    } catch (e: any) {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: String(e?.message ?? e) }));
    }
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`mock-anthropic-server listening on http://127.0.0.1:${PORT}`);
});
