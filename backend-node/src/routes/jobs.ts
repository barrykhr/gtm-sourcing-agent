// Port of api.py's job/revenue/task routes (lines 543-996, the
// deterministic, non-AI subset). AI-triggering routes (intake, calibrate,
// icp, talent-map, search-strategy, interview-questions, add-candidate,
// prioritize, screen, outreach draft) are ported alongside the AI stage
// modules, not here -- see docs/migration.md Phase 5.
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import * as storage from "../db/storage.js";
import * as icpStage from "../stages/icp.js";
import * as intakeStage from "../stages/intake.js";
import { requireRole } from "../lib/authMiddleware.js";
import { jobSummary, logAction, runStage, slugify } from "../lib/routeHelpers.js";

const JobCreateRequest = z.object({
  title: z.string(),
  role_family: z.string().default(""),
  client_name: z.string().default(""),
  role_value: z.number().nullable().optional(),
  role_id: z.string().nullable().optional(),
});

const CloneJobRequest = z.object({
  title: z.string(),
  role_family: z.string().default(""),
  role_id: z.string().nullable().optional(),
});

const JobLifecycleRequest = z.object({ lifecycle_status: z.string() });
const JobOwnerRequest = z.object({ owner_email: z.string().nullable().optional() });
const RecruiterAddRequest = z.object({ email: z.string() });
const JobClientRequest = z.object({ client_name: z.string().nullable().optional() });
const JobValueRequest = z.object({ role_value: z.number().nullable().optional() });
const IcpCriteriaRequest = z.object({
  must_have: z.array(z.string()).nullable().optional(),
  nice_to_have: z.array(z.string()).nullable().optional(),
});
const JobDescriptionUpdateRequest = z.object({
  role_title: z.string().nullable().optional(),
  seniority: z.string().nullable().optional(),
  geography: z.string().nullable().optional(),
  compensation: z.string().nullable().optional(),
  must_have_requirements: z.array(z.string()).nullable().optional(),
  nice_to_have_requirements: z.array(z.string()).nullable().optional(),
});

async function findUniqueRoleId(base: string): Promise<string> {
  let roleId = base;
  let n = 2;
  while (await storage.jobExists(roleId)) {
    roleId = `${base}-${n}`;
    n++;
  }
  return roleId;
}

export async function registerJobRoutes(app: FastifyInstance) {
  app.post("/jobs", async (request, reply) => {
    const body = JobCreateRequest.parse(request.body);
    const baseRoleId = body.role_id || slugify(body.title);
    const roleId = await findUniqueRoleId(baseRoleId);
    const ownerEmail = (request as any).user.email;
    const job = await storage.createJob(roleId, {
      title: body.title, roleFamily: body.role_family, clientName: body.client_name,
      roleValue: body.role_value ?? null, ownerEmail,
    });
    await logAction(request, roleId, "created job", { detail: body.title });
    reply.send({ ...job, ...(await jobSummary(roleId)) });
  });

  app.post("/jobs/:roleId/clone", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = CloneJobRequest.parse(request.body);
    const newRoleId = await findUniqueRoleId(body.role_id || slugify(body.title));
    const ownerEmail = (request as any).user.email;
    const job = await runStage(() =>
      storage.cloneRole(roleId, newRoleId, { title: body.title, roleFamily: body.role_family, ownerEmail })
    );
    await logAction(request, roleId, "cloned as new job", { detail: newRoleId });
    await logAction(request, newRoleId, "cloned from job", { detail: roleId });
    reply.send({ ...job, ...(await jobSummary(newRoleId)) });
  });

  app.patch("/jobs/:roleId/lifecycle", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = JobLifecycleRequest.parse(request.body);
    const job = await runStage(() => storage.setJobLifecycle(roleId, body.lifecycle_status));
    await logAction(request, roleId, `set job status: ${body.lifecycle_status}`);
    reply.send({ ...job, ...(await jobSummary(roleId)) });
  });

  app.patch("/jobs/:roleId/owner", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = JobOwnerRequest.parse(request.body);
    const job = await runStage(() => storage.setJobOwner(roleId, body.owner_email ?? null));
    await logAction(request, roleId, "changed job owner", { detail: body.owner_email || "(unassigned)" });
    reply.send({ ...job, ...(await jobSummary(roleId)) });
  });

  app.get("/jobs/:roleId/recruiters", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    reply.send(await storage.listRecruiters(roleId));
  });

  app.post("/jobs/:roleId/recruiters", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = RecruiterAddRequest.parse(request.body);
    const recruiters = await runStage(() => storage.addRecruiter(roleId, body.email));
    await logAction(request, roleId, "added recruiter", { detail: body.email });
    reply.send(recruiters);
  });

  app.delete("/jobs/:roleId/recruiters/:email", async (request, reply) => {
    const { roleId, email } = request.params as { roleId: string; email: string };
    const recruiters = await runStage(() => storage.removeRecruiter(roleId, email));
    await logAction(request, roleId, "removed recruiter", { detail: email });
    reply.send(recruiters);
  });

  app.patch("/jobs/:roleId/client", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = JobClientRequest.parse(request.body);
    const job = await runStage(() => storage.setJobClient(roleId, body.client_name ?? null));
    await logAction(request, roleId, "changed client", { detail: body.client_name || "(unassigned)" });
    reply.send({ ...job, ...(await jobSummary(roleId)) });
  });

  app.patch("/jobs/:roleId/value", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = JobValueRequest.parse(request.body);
    const job = await runStage(() => storage.setJobValue(roleId, body.role_value ?? null));
    await logAction(request, roleId, "changed role value", {
      detail: body.role_value !== null && body.role_value !== undefined ? String(body.role_value) : "(unset)",
    });
    reply.send({ ...job, ...(await jobSummary(roleId)) });
  });

  app.get("/revenue/overview", async (_request, reply) => {
    reply.send(await storage.revenueOverview());
  });

  app.get("/revenue/by-recruiter", { preHandler: requireRole("admin") }, async (_request, reply) => {
    reply.send(await storage.recruiterRevenue());
  });

  app.post("/jobs/:roleId/share-link", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const job = await runStage(() => storage.generateShareLink(roleId));
    await logAction(request, roleId, "generated client share link");
    reply.send({ ...job, ...(await jobSummary(roleId)) });
  });

  app.delete("/jobs/:roleId/share-link", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const job = await runStage(() => storage.revokeShareLink(roleId));
    await logAction(request, roleId, "revoked client share link");
    reply.send({ ...job, ...(await jobSummary(roleId)) });
  });

  app.get("/public/roles/:shareToken", async (request, reply) => {
    const { shareToken } = request.params as { shareToken: string };
    const summary = await storage.getPublicRoleSummary(shareToken);
    if (summary === null) {
      reply.code(404).send({ detail: "This link is no longer valid." });
      return;
    }
    reply.send(summary);
  });

  app.get("/jobs", async (_request, reply) => {
    const jobs = await storage.listJobs();
    const withSummary = await Promise.all(jobs.map(async (j) => ({ ...j, ...(await jobSummary(j.role_id)) })));
    reply.send(withSummary);
  });

  app.get("/jobs/:roleId", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    const state = await storage.loadRole(roleId);
    const jobs = await storage.listJobs();
    const job = jobs.find((j) => j.role_id === roleId)!;
    reply.send({ ...job, ...(await jobSummary(roleId)), state });
  });

  app.get("/jobs/:roleId/activity", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    if (!(await storage.jobExists(roleId))) {
      reply.code(404).send({ detail: `job '${roleId}' not found` });
      return;
    }
    reply.send(await storage.listActivity(roleId));
  });

  app.patch("/jobs/:roleId/icp/criteria", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = IcpCriteriaRequest.parse(request.body);
    const result = await runStage(() =>
      icpStage.updateCriteria(roleId, { mustHave: body.must_have ?? null, niceToHave: body.nice_to_have ?? null })
    );
    await logAction(request, roleId, "updated hiring criteria");
    reply.send(result);
  });

  app.patch("/jobs/:roleId/job-description", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    const body = JobDescriptionUpdateRequest.parse(request.body);
    const fields = Object.fromEntries(Object.entries(body).filter(([, v]) => v !== undefined));
    const result = await runStage(() => intakeStage.updateFields(roleId, fields));
    await logAction(request, roleId, "corrected JD extraction");
    reply.send(result);
  });

  app.get("/jobs/:roleId/tasks/:taskId", async (request, reply) => {
    const { roleId, taskId } = request.params as { roleId: string; taskId: string };
    const task = await storage.getTask(taskId);
    if (task === null || task.role_id !== roleId) {
      reply.code(404).send({ detail: `task '${taskId}' not found` });
      return;
    }
    reply.send(task);
  });

  app.get("/jobs/:roleId/tasks", async (request, reply) => {
    const { roleId } = request.params as { roleId: string };
    reply.send(await storage.listTasks(roleId));
  });
}
