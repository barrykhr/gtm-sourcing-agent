import type { FastifyInstance, LightMyRequestResponse } from "fastify";
import { buildServer } from "../src/server.js";
import { prisma } from "../src/db/client.js";
import * as storage from "../src/db/storage.js";
import { SESSION_COOKIE_NAME } from "../src/auth/service.js";

export function buildApp(): FastifyInstance {
  return buildServer();
}

export function sessionCookie(response: LightMyRequestResponse): string {
  const cookie = response.cookies.find((c) => c.name === SESSION_COOKIE_NAME);
  if (!cookie) throw new Error(`no '${SESSION_COOKIE_NAME}' cookie in response (status ${response.statusCode}): ${response.body}`);
  return cookie.value;
}

/** Signs up a brand-new account and returns its session cookie + user.
 * The very first account created in a clean test DB becomes "admin";
 * every one after that is "recruiter" -- same as production. */
export async function signup(
  app: FastifyInstance, email: string, password = "correct-horse-battery"
): Promise<{ cookie: string; user: { id: string; email: string; role: string } }> {
  const res = await app.inject({ method: "POST", url: "/auth/signup", payload: { email, password } });
  if (res.statusCode !== 200) throw new Error(`signup failed (${res.statusCode}): ${res.body}`);
  return { cookie: sessionCookie(res), user: res.json() };
}

export async function login(app: FastifyInstance, email: string, password = "correct-horse-battery") {
  const res = await app.inject({ method: "POST", url: "/auth/login", payload: { email, password } });
  if (res.statusCode !== 200) throw new Error(`login failed (${res.statusCode}): ${res.body}`);
  return { cookie: sessionCookie(res), user: res.json() };
}

export function authHeader(cookie: string): Record<string, string> {
  return { cookie: `${SESSION_COOKIE_NAME}=${cookie}` };
}

/** Creates a job directly via the real storage layer (bypassing the
 * HTTP route) -- used to set up preconditions for tests that aren't
 * themselves testing job creation. */
export async function createJob(roleId: string, args: Partial<Parameters<typeof storage.createJob>[1]> = {}, ownerEmail = "owner@test.com") {
  return storage.createJob(roleId, { title: "Test Role", roleFamily: "", clientName: "", roleValue: null, ownerEmail, ...args });
}

/** Seeds a minimal ICP section directly -- candidateAnalysisStage.run()
 * (behind /candidates and /candidates/upload) requires one to already
 * exist via requireSection(roleId, "icp"), same precondition Python
 * enforces. Real pipeline order (intake -> calibrate -> icp) is exercised
 * separately in job-lifecycle tests; here we only need its *presence*. */
export async function seedIcp(roleId: string) {
  await storage.mergeSection(roleId, "icp", {
    must_have: ["5+ years experience"], nice_to_have: [], disqualifiers: [],
  });
}

/** Seeds a candidate with a drafted outreach email, bypassing the AI
 * drafting stage -- used by outreach send/sweep tests that only care
 * about the deterministic send/log/mark-sent logic. */
export async function seedCandidateWithOutreachDraft(
  roleId: string, candidateId: string, args: { email: string; name?: string; draftBody?: string }
) {
  await storage.mergeCandidate(roleId, candidateId, { candidate_id: candidateId, name: args.name ?? "Test Candidate" });
  await storage.setCandidateContact(roleId, candidateId, { email: args.email });
  const state = await storage.loadRole(roleId);
  const outreach = state.outreach ?? {};
  outreach[candidateId] = { email: args.draftBody ?? "Hi, following up on this opportunity." };
  await storage.mergeSection(roleId, "outreach", outreach);
}

/** Polls a background task (taskQueue.ts) until it leaves pending/running.
 * The in-process worker starts draining as soon as enqueue() returns, so
 * with the Anthropic client mocked this normally resolves in a handful
 * of milliseconds -- the loop exists so tests never hardcode a sleep. */
export async function pollTask(
  app: FastifyInstance, cookie: string, roleId: string, taskId: string, timeoutMs = 5000
): Promise<any> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const res = await app.inject({ method: "GET", url: `/jobs/${roleId}/tasks/${taskId}`, headers: authHeader(cookie) });
    const task = res.json();
    if (task.status === "succeeded" || task.status === "failed") return task;
    if (Date.now() > deadline) throw new Error(`task ${taskId} still '${task.status}' after ${timeoutMs}ms`);
    await new Promise((r) => setTimeout(r, 20));
  }
}

/** Builds a real multipart/form-data body (boundary and all) using
 * Node's built-in FormData/Request -- no extra dependency needed --
 * for routes behind @fastify/multipart's attachFieldsToBody. */
export async function multipartPayload(
  fields: Record<string, string>,
  file: { field: string; filename: string; content: Buffer | string; contentType: string }
): Promise<{ buffer: Buffer; contentType: string }> {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  form.append(file.field, new Blob([file.content], { type: file.contentType }), file.filename);
  const req = new Request("http://local/", { method: "POST", body: form });
  const buffer = Buffer.from(await req.arrayBuffer());
  return { buffer, contentType: req.headers.get("content-type")! };
}

export { prisma };
