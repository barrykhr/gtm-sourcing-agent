/**
 * Node.js port of src/gtm_sourcing_agent/db_storage.py — every exported
 * function here is a deliberate behavioral match to its Python
 * namesake, not a reinterpretation. Section comments mirror the
 * Python file's own section breaks so the two can be read side by
 * side.
 */
import crypto from "node:crypto";
import { prisma } from "./client.js";
import { expectedRevenue } from "../revenue.js";

export type JobState = Record<string, any> & {
  role_id: string;
  candidates: Record<string, any>;
  prioritizations: Record<string, any>;
};

const CANDIDATE_OWNED_KEYS = new Set(["candidates", "prioritizations"]);

export class StorageError extends Error {}

// ── per-role workspace state (job_sections + candidate_evaluations) ────

export async function loadRole(roleId: string): Promise<JobState> {
  const job = await prisma.job.findUnique({ where: { roleId } });
  const state: JobState = { role_id: roleId, candidates: {}, prioritizations: {} };
  if (!job) return state;

  const sections = await prisma.jobSection.findMany({ where: { roleId } });
  for (const row of sections) {
    state[row.sectionKey] = row.data;
  }
  const clientShares: Record<string, boolean> = state.client_shares ?? {};
  const conversationIntelligence: Record<string, any> = state.conversation_intelligence ?? {};

  const evaluations = await prisma.candidateEvaluation.findMany({ where: { roleId } });
  for (const ev of evaluations) {
    state.candidates[ev.candidateEvaluationId] = {
      ...(ev.data as object),
      canonical_candidate_id: ev.canonicalCandidateId,
      note: ev.note,
      phone: ev.phone,
      email: ev.email,
      resume_file_key: ev.resumeFileKey,
      resume_filename: ev.resumeFilename,
      conversation_summary: ev.conversationSummary,
      conversation_summary_updated_at: ev.conversationSummaryUpdatedAt?.toISOString() ?? null,
      conversation_summary_entry_count: ev.conversationSummaryEntryCount,
      client_visible: Boolean(clientShares[ev.candidateEvaluationId]),
      conversation_intelligence: conversationIntelligence[ev.candidateEvaluationId] ?? null,
    };
    if (ev.prioritization !== null) {
      state.prioritizations[ev.candidateEvaluationId] = ev.prioritization;
    }
  }
  return state;
}

export async function saveRole(roleId: string, state: JobState): Promise<void> {
  await prisma.job.upsert({
    where: { roleId },
    update: {},
    create: { roleId },
  });
  for (const [key, value] of Object.entries(state)) {
    if (key === "role_id" || CANDIDATE_OWNED_KEYS.has(key)) continue;
    await prisma.jobSection.upsert({
      where: { roleId_sectionKey: { roleId, sectionKey: key } },
      update: { data: value },
      create: { roleId, sectionKey: key, data: value },
    });
  }
}

export async function requireSection(roleId: string, key: string): Promise<any> {
  const state = await loadRole(roleId);
  const value = state[key];
  if (!value || (Array.isArray(value) && value.length === 0)) {
    throw new StorageError(`role '${roleId}' has no '${key}' yet — run that stage first (see README.md pipeline order)`);
  }
  return value;
}

export async function mergeSection(roleId: string, key: string, value: any): Promise<JobState> {
  const state = await loadRole(roleId);
  state[key] = value;
  await saveRole(roleId, state);
  return state;
}

// ── candidates & dedup ───────────────────────────────────────────────

function normalize(text: string | null | undefined): string {
  return (text ?? "").trim().toLowerCase().replace(/\s+/g, " ");
}

async function findMatchingCanonical(name: string, currentCompany: string, sourceUrl: string) {
  if (sourceUrl) {
    const target = sourceUrl.trim().replace(/\/+$/, "").toLowerCase();
    const all = await prisma.canonicalCandidate.findMany();
    const bySource = all.find((c) => c.sourceUrl && c.sourceUrl.trim().replace(/\/+$/, "").toLowerCase() === target);
    if (bySource) return { candidate: bySource, method: "source_url" as const };
  }
  if (name) {
    const normName = normalize(name);
    const normCompany = normalize(currentCompany);
    const all = await prisma.canonicalCandidate.findMany();
    const byName = all.find((c) => normalize(c.name) === normName && normalize(c.currentCompany) === normCompany);
    if (byName) return { candidate: byName, method: "name+company" as const };
  }
  return { candidate: null, method: "new" as const };
}

export async function mergeCandidate(roleId: string, candidateId: string, value: Record<string, any>): Promise<JobState> {
  await prisma.job.upsert({ where: { roleId }, update: {}, create: { roleId } });

  const existingEval = await prisma.candidateEvaluation.findUnique({
    where: { roleId_candidateEvaluationId: { roleId, candidateEvaluationId: candidateId } },
  });

  if (existingEval) {
    await prisma.candidateEvaluation.update({ where: { id: existingEval.id }, data: { data: value } });
  } else {
    const name = value.name ?? "";
    const currentCompany = value.current_company ?? "";
    const sourceUrl = value.source_url ?? "";
    const { candidate: found } = await findMatchingCanonical(name, currentCompany, sourceUrl);
    let canonicalId: string;
    if (!found) {
      const created = await prisma.canonicalCandidate.create({
        data: {
          id: `cand-${crypto.randomBytes(6).toString("hex")}`,
          name, currentCompany, currentTitle: value.current_title ?? "", location: value.location ?? "",
          sourceUrl, firstSeenJobId: roleId,
        },
      });
      canonicalId = created.id;
    } else {
      canonicalId = found.id;
      await prisma.canonicalCandidate.update({
        where: { id: found.id },
        data: {
          currentCompany: currentCompany || found.currentCompany,
          currentTitle: value.current_title || found.currentTitle,
          location: value.location || found.location,
          sourceUrl: sourceUrl || found.sourceUrl,
        },
      });
    }
    await prisma.candidateEvaluation.create({
      data: { roleId, candidateEvaluationId: candidateId, canonicalCandidateId: canonicalId, data: value },
    });
  }
  return loadRole(roleId);
}

function slugifyName(name: string, roleId: string): string {
  const normalized = name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${roleId}-${normalized}`;
}

export async function attachExistingCandidate(roleId: string, canonicalCandidateId: string): Promise<JobState> {
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const canonical = await prisma.canonicalCandidate.findUnique({ where: { id: canonicalCandidateId } });
  if (!canonical) throw new StorageError(`candidate '${canonicalCandidateId}' not found`);
  const sourceEval = await prisma.candidateEvaluation.findFirst({
    where: { canonicalCandidateId },
    orderBy: { updatedAt: "desc" },
  });
  if (!sourceEval) throw new StorageError(`'${canonical.name}' has no existing evaluation to reuse`);
  const candidateEvaluationId = slugifyName(canonical.name, roleId);
  const already = await prisma.candidateEvaluation.findUnique({
    where: { roleId_candidateEvaluationId: { roleId, candidateEvaluationId } },
  });
  if (already) throw new StorageError(`'${canonical.name}' has already been added to this role`);
  const data = { ...(sourceEval.data as object), candidate_id: candidateEvaluationId };
  await prisma.candidateEvaluation.create({
    data: {
      roleId, candidateEvaluationId, canonicalCandidateId: canonical.id, data,
      phone: sourceEval.phone, email: sourceEval.email,
    },
  });
  return loadRole(roleId);
}

export async function mergePrioritization(roleId: string, candidateId: string, value: Record<string, any>): Promise<JobState> {
  const row = await prisma.candidateEvaluation.findUnique({
    where: { roleId_candidateEvaluationId: { roleId, candidateEvaluationId: candidateId } },
  });
  if (!row) throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  await prisma.candidateEvaluation.update({ where: { id: row.id }, data: { prioritization: value } });
  return loadRole(roleId);
}

async function requireEvaluation(roleId: string, candidateId: string) {
  const row = await prisma.candidateEvaluation.findUnique({
    where: { roleId_candidateEvaluationId: { roleId, candidateEvaluationId: candidateId } },
  });
  if (!row) throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  return row;
}

export async function setCandidateNote(roleId: string, candidateId: string, note: string) {
  const row = await requireEvaluation(roleId, candidateId);
  const updated = await prisma.candidateEvaluation.update({ where: { id: row.id }, data: { note } });
  return { candidate_id: candidateId, note: updated.note };
}

export async function setCandidateContact(
  roleId: string, candidateId: string, args: { phone?: string | null; email?: string | null }
) {
  const row = await requireEvaluation(roleId, candidateId);
  const data: Record<string, any> = {};
  if (args.phone !== undefined && args.phone !== null) data.phone = args.phone;
  if (args.email !== undefined && args.email !== null) data.email = args.email;
  const updated = await prisma.candidateEvaluation.update({ where: { id: row.id }, data });
  return { candidate_id: candidateId, phone: updated.phone, email: updated.email };
}

export async function setCandidateResume(roleId: string, candidateId: string, fileKey: string, filename: string) {
  const row = await requireEvaluation(roleId, candidateId);
  await prisma.candidateEvaluation.update({
    where: { id: row.id },
    data: { resumeFileKey: fileKey, resumeFilename: filename },
  });
  return { candidate_id: candidateId, resume_file_key: fileKey, resume_filename: filename };
}

export async function listCommunications(roleId: string, candidateId: string) {
  const rows = await prisma.communicationLogEntry.findMany({
    where: { roleId, candidateEvaluationId: candidateId },
    orderBy: { createdAt: "asc" },
  });
  return rows.map((r) => ({
    id: r.id, channel: r.channel, direction: r.direction, content: r.content,
    transcript: r.transcript, contact_used: r.contactUsed, logged_by: r.loggedBy,
    followup_stage: r.followupStage, created_at: r.createdAt.toISOString(),
  }));
}

export async function logCommunication(
  roleId: string, candidateId: string,
  args: {
    channel: string; direction: string; content: string; transcript?: string | null;
    contactUsed?: string; loggedBy?: string; followupStage?: number;
  }
) {
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  await requireEvaluation(roleId, candidateId);
  const entry = await prisma.communicationLogEntry.create({
    data: {
      roleId, candidateEvaluationId: candidateId, channel: args.channel, direction: args.direction,
      content: args.content, transcript: args.transcript ?? null, contactUsed: args.contactUsed ?? "",
      loggedBy: args.loggedBy ?? "", followupStage: args.followupStage ?? 0,
    },
  });
  return {
    id: entry.id, channel: entry.channel, direction: entry.direction, content: entry.content,
    transcript: entry.transcript, contact_used: entry.contactUsed, logged_by: entry.loggedBy,
    followup_stage: entry.followupStage, created_at: entry.createdAt.toISOString(),
  };
}

export async function getConversationSummary(roleId: string, candidateId: string) {
  const row = await requireEvaluation(roleId, candidateId);
  return {
    summary: row.conversationSummary,
    updated_at: row.conversationSummaryUpdatedAt?.toISOString() ?? null,
    based_on_entries: row.conversationSummaryEntryCount,
  };
}

export async function setConversationSummary(roleId: string, candidateId: string, summary: string, entryCount: number) {
  const row = await requireEvaluation(roleId, candidateId);
  await prisma.candidateEvaluation.update({
    where: { id: row.id },
    data: { conversationSummary: summary, conversationSummaryUpdatedAt: new Date(), conversationSummaryEntryCount: entryCount },
  });
}

// ── jobs, ownership, revenue ─────────────────────────────────────────

function jobDict(job: NonNullable<Awaited<ReturnType<typeof prisma.job.findUnique>>>) {
  return {
    role_id: job.roleId, title: job.title, role_family: job.roleFamily,
    client_name: job.clientName, share_token: job.shareToken,
    lifecycle_status: job.lifecycleStatus, owner_email: job.ownerEmail,
    role_value: job.roleValue, expected_revenue: expectedRevenue(job.roleValue),
    created_at: job.createdAt, updated_at: job.updatedAt,
  };
}

async function syncPrimaryRecruiter(roleId: string, email: string | null) {
  const existingPrimary = await prisma.jobRecruiter.findFirst({ where: { roleId, assignment: "primary" } });
  if (existingPrimary) {
    if (existingPrimary.email === email) return;
    await prisma.jobRecruiter.delete({ where: { id: existingPrimary.id } });
  }
  if (email) {
    const staleContributor = await prisma.jobRecruiter.findFirst({ where: { roleId, email } });
    if (staleContributor) await prisma.jobRecruiter.delete({ where: { id: staleContributor.id } });
    await prisma.jobRecruiter.create({ data: { roleId, email, assignment: "primary" } });
  }
}

export async function createJob(
  roleId: string,
  args: { title?: string; roleFamily?: string; ownerEmail?: string; clientName?: string; roleValue?: number | null }
) {
  const existing = await prisma.job.findUnique({ where: { roleId } });
  if (!existing) {
    const job = await prisma.job.create({
      data: {
        roleId, title: args.title || roleId, roleFamily: args.roleFamily || null,
        ownerEmail: args.ownerEmail || null, clientName: args.clientName || null,
        roleValue: args.roleValue ?? null,
      },
    });
    await syncPrimaryRecruiter(roleId, args.ownerEmail || null);
    return jobDict((await prisma.job.findUnique({ where: { roleId } }))!);
  }
  const data: Record<string, any> = {};
  if (args.title) data.title = args.title;
  if (args.roleFamily) data.roleFamily = args.roleFamily;
  if (args.clientName) data.clientName = args.clientName;
  const updated = Object.keys(data).length ? await prisma.job.update({ where: { roleId }, data }) : existing;
  return jobDict(updated);
}

export async function listJobs() {
  const jobs = await prisma.job.findMany({ orderBy: { updatedAt: "desc" } });
  return jobs.map(jobDict);
}

export const JOB_LIFECYCLE_STATUSES = ["OPEN", "ON_HOLD", "FILLED", "CANCELLED"] as const;

export async function setJobLifecycle(roleId: string, lifecycleStatus: string) {
  if (!(JOB_LIFECYCLE_STATUSES as readonly string[]).includes(lifecycleStatus)) {
    throw new StorageError(`'${lifecycleStatus}' is not a valid job status — use one of ${JOB_LIFECYCLE_STATUSES}`);
  }
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const updated = await prisma.job.update({ where: { roleId }, data: { lifecycleStatus } });
  return jobDict(updated);
}

export async function setJobOwner(roleId: string, ownerEmail: string | null) {
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const updated = await prisma.job.update({ where: { roleId }, data: { ownerEmail: ownerEmail || null } });
  await syncPrimaryRecruiter(roleId, ownerEmail || null);
  return jobDict(updated);
}

export async function listRecruiters(roleId: string) {
  const rows = await prisma.jobRecruiter.findMany({ where: { roleId } });
  const ordered = rows.sort((a, b) => {
    const aPrimary = a.assignment === "primary" ? 0 : 1;
    const bPrimary = b.assignment === "primary" ? 0 : 1;
    if (aPrimary !== bPrimary) return aPrimary - bPrimary;
    return a.addedAt.getTime() - b.addedAt.getTime();
  });
  return ordered.map((r) => ({ email: r.email, assignment: r.assignment, added_at: r.addedAt }));
}

export async function addRecruiter(roleId: string, email: string) {
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const existing = await prisma.jobRecruiter.findFirst({ where: { roleId, email } });
  if (existing) throw new StorageError(`'${email}' is already assigned to this role as ${existing.assignment}`);
  await prisma.jobRecruiter.create({ data: { roleId, email, assignment: "contributor" } });
  return listRecruiters(roleId);
}

export async function removeRecruiter(roleId: string, email: string) {
  const row = await prisma.jobRecruiter.findFirst({ where: { roleId, email } });
  if (!row) throw new StorageError(`'${email}' is not assigned to this role`);
  if (row.assignment === "primary") {
    throw new StorageError("can't remove the primary recruiter this way — reassign ownership instead");
  }
  await prisma.jobRecruiter.delete({ where: { id: row.id } });
  return listRecruiters(roleId);
}

export async function setJobClient(roleId: string, clientName: string | null) {
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const updated = await prisma.job.update({ where: { roleId }, data: { clientName: clientName || null } });
  return jobDict(updated);
}

export async function setJobValue(roleId: string, roleValue: number | null) {
  if (roleValue !== null && roleValue !== undefined && roleValue < 0) {
    throw new StorageError("role value can't be negative");
  }
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const updated = await prisma.job.update({ where: { roleId }, data: { roleValue: roleValue ?? null } });
  return jobDict(updated);
}

export async function revenueOverview() {
  const jobs = await listJobs();
  const openRoles = jobs.filter((j) => j.lifecycle_status === "OPEN");
  let totalExpected = 0;
  let totalPipeline = 0;
  let pricedOpenRoles = 0;
  for (const j of openRoles) {
    const rev = expectedRevenue(j.role_value);
    if (rev === null) continue;
    pricedOpenRoles++;
    totalExpected += rev;
    const state = await loadRole(j.role_id);
    if (Object.keys(state.candidates).length > 0) totalPipeline += rev;
  }
  const analytics = await analyticsOverview();
  return {
    open_roles: openRoles.length,
    open_roles_priced: pricedOpenRoles,
    expected_revenue: Math.round(totalExpected * 100) / 100,
    pipeline_revenue: Math.round(totalPipeline * 100) / 100,
    realized_revenue: analytics.total_placement_fees,
    margin_percentage: 8.33,
  };
}

export async function recruiterRevenue() {
  const jobs = await listJobs();
  const jobsById = new Map(jobs.map((j) => [j.role_id, j]));
  const recruiterRows = await prisma.jobRecruiter.findMany();
  const evaluations = await prisma.candidateEvaluation.findMany();

  const roleRecruiters = new Map<string, string[]>();
  for (const row of recruiterRows) {
    const list = roleRecruiters.get(row.roleId) ?? [];
    list.push(row.email);
    roleRecruiters.set(row.roleId, list);
  }

  const roleRealized = new Map<string, number>();
  for (const ev of evaluations) {
    const p = ev.prioritization as any;
    if (p?.placed) {
      roleRealized.set(ev.roleId, (roleRealized.get(ev.roleId) ?? 0) + (p.placement_fee ?? 0));
    }
  }

  const byRecruiter = new Map<string, { email: string; roles: number; expected_revenue: number; realized_revenue: number }>();
  const bucket = (email: string) => {
    let b = byRecruiter.get(email);
    if (!b) {
      b = { email, roles: 0, expected_revenue: 0, realized_revenue: 0 };
      byRecruiter.set(email, b);
    }
    return b;
  };

  for (const [roleId, emails] of roleRecruiters) {
    const job = jobsById.get(roleId);
    if (!job) continue;
    const expected = job.lifecycle_status === "OPEN" ? expectedRevenue(job.role_value) : null;
    const realized = roleRealized.get(roleId) ?? 0;
    for (const email of emails) {
      const b = bucket(email);
      b.roles += 1;
      if (expected !== null) b.expected_revenue += expected;
      b.realized_revenue += realized;
    }
  }

  const firmTotal = await revenueOverview();
  const firmDenominator = firmTotal.expected_revenue + firmTotal.realized_revenue;

  const result = Array.from(byRecruiter.values()).map((b) => {
    const total = Math.round((b.expected_revenue + b.realized_revenue) * 100) / 100;
    return {
      email: b.email,
      roles: b.roles,
      expected_revenue: Math.round(b.expected_revenue * 100) / 100,
      realized_revenue: Math.round(b.realized_revenue * 100) / 100,
      total_revenue: total,
      share_of_firm: firmDenominator > 0 ? Math.round((total / firmDenominator) * 1000) / 10 : 0,
    };
  });
  return result.sort((a, b) => b.total_revenue - a.total_revenue);
}

export async function generateShareLink(roleId: string) {
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const shareToken = crypto.randomBytes(18).toString("base64url");
  const updated = await prisma.job.update({ where: { roleId }, data: { shareToken } });
  return jobDict(updated);
}

export async function revokeShareLink(roleId: string) {
  const job = await prisma.job.findUnique({ where: { roleId } });
  if (!job) throw new StorageError(`job '${roleId}' not found`);
  const updated = await prisma.job.update({ where: { roleId }, data: { shareToken: null } });
  return jobDict(updated);
}

export async function setConversationIntelligence(roleId: string, candidateId: string, intelligence: Record<string, any>) {
  const state = await loadRole(roleId);
  if (!(candidateId in state.candidates)) throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  const all = { ...(state.conversation_intelligence ?? {}) };
  all[candidateId] = intelligence;
  await mergeSection(roleId, "conversation_intelligence", all);
}

export async function setCandidateClientVisible(roleId: string, candidateId: string, visible: boolean) {
  const state = await loadRole(roleId);
  if (!(candidateId in state.candidates)) throw new StorageError(`candidate '${candidateId}' not found for role '${roleId}'`);
  const shares = { ...(state.client_shares ?? {}) };
  if (visible) shares[candidateId] = true;
  else delete shares[candidateId];
  await mergeSection(roleId, "client_shares", shares);
  return { candidate_id: candidateId, client_visible: visible };
}

const CLIENT_SAFE_CANDIDATE_FIELDS = [
  "name", "current_title", "current_company", "location", "relevant_experience_summary", "achievements", "evidence_of_fit",
];

export async function getPublicRoleSummary(shareToken: string) {
  const job = await prisma.job.findFirst({ where: { shareToken } });
  if (!job) return null;
  const roleId = job.roleId;
  const totalCandidates = await prisma.candidateEvaluation.count({ where: { roleId } });

  const state = await loadRole(roleId);
  const funnel = state.funnel ?? {};
  const countsByStage: Record<string, number> = {};
  for (const record of Object.values<any>(funnel)) {
    const stage = record.current_stage ?? "IDENTIFIED";
    countsByStage[stage] = (countsByStage[stage] ?? 0) + 1;
  }

  const candidates = state.candidates ?? {};
  const prioritizations = state.prioritizations ?? {};
  const shares: Record<string, boolean> = state.client_shares ?? {};
  const sharedCandidates: Record<string, any>[] = [];
  for (const [candidateId, isShared] of Object.entries(shares)) {
    if (!isShared || !(candidateId in candidates)) continue;
    const full = candidates[candidateId];
    const safe: Record<string, any> = {};
    for (const k of CLIENT_SAFE_CANDIDATE_FIELDS) safe[k] = full[k] ?? null;
    const p = prioritizations[candidateId] ?? {};
    safe.tier = p.tier ?? null;
    safe.fit_rating = p.fit_rating ?? null;
    safe.why_they_fit = p.why_they_fit ?? null;
    safe.current_stage = (funnel[candidateId] ?? {}).current_stage ?? "IDENTIFIED";
    sharedCandidates.push(safe);
  }

  return {
    role_id: roleId, title: job.title, client_name: job.clientName,
    lifecycle_status: job.lifecycleStatus, updated_at: job.updatedAt,
    total_candidates: totalCandidates, counts_by_stage: countsByStage,
    shared_candidates: sharedCandidates,
  };
}

const CLONEABLE_SECTIONS = ["job_description", "calibration", "icp", "talent_map"];

export async function cloneRole(
  sourceRoleId: string, newRoleId: string, args: { title?: string; roleFamily?: string; ownerEmail?: string }
) {
  const sourceJob = await prisma.job.findUnique({ where: { roleId: sourceRoleId } });
  if (!sourceJob) throw new StorageError(`job '${sourceRoleId}' not found`);
  const sourceFamily = sourceJob.roleFamily || "";
  const sourceState = await loadRole(sourceRoleId);
  const newJob = await createJob(newRoleId, {
    title: args.title, roleFamily: args.roleFamily || sourceFamily, ownerEmail: args.ownerEmail,
  });
  const newState: JobState = { role_id: newRoleId, candidates: {}, prioritizations: {} };
  let clonedAnything = false;
  for (const key of CLONEABLE_SECTIONS) {
    if (sourceState[key]) {
      newState[key] = sourceState[key];
      clonedAnything = true;
    }
  }
  if (clonedAnything) await saveRole(newRoleId, newState);
  return newJob;
}

export async function jobExists(roleId: string): Promise<boolean> {
  return (await prisma.job.count({ where: { roleId } })) > 0;
}

// ── global candidate roster ──────────────────────────────────────────

function evaluationSummary(ev: any, jobsById: Map<string, any>) {
  const p = ev.prioritization ?? {};
  const job = jobsById.get(ev.roleId);
  return {
    role_id: ev.roleId,
    job_title: job ? job.title : ev.roleId,
    candidate_evaluation_id: ev.candidateEvaluationId,
    tier: p.tier ?? null,
    fit_rating: p.fit_rating ?? null,
    why_they_fit: p.why_they_fit ?? null,
    recruiter_decision: p.recruiter_decision ?? null,
    phone: ev.phone,
    email: ev.email,
    resume_file_key: ev.resumeFileKey,
    resume_filename: ev.resumeFilename,
  };
}

export async function listCanonicalCandidates() {
  const jobs = await prisma.job.findMany();
  const jobsById = new Map(jobs.map((j) => [j.roleId, j]));
  const candidates = await prisma.canonicalCandidate.findMany({ orderBy: { updatedAt: "desc" } });
  const result = [];
  for (const c of candidates) {
    const evals = await prisma.candidateEvaluation.findMany({ where: { canonicalCandidateId: c.id } });
    result.push({
      candidate_id: c.id, name: c.name, current_company: c.currentCompany,
      current_title: c.currentTitle, location: c.location, source_url: c.sourceUrl,
      evaluations: evals.map((e) => evaluationSummary(e, jobsById)),
    });
  }
  return result;
}

export async function getCanonicalCandidate(canonicalId: string) {
  const c = await prisma.canonicalCandidate.findUnique({ where: { id: canonicalId } });
  if (!c) return null;
  const jobs = await prisma.job.findMany();
  const jobsById = new Map(jobs.map((j) => [j.roleId, j]));
  const evals = await prisma.candidateEvaluation.findMany({ where: { canonicalCandidateId: canonicalId } });
  return {
    candidate_id: c.id, name: c.name, current_company: c.currentCompany,
    current_title: c.currentTitle, location: c.location, source_url: c.sourceUrl,
    evaluations: evals.map((e) => evaluationSummary(e, jobsById)),
  };
}

// ── global search ────────────────────────────────────────────────────

const SEARCH_RESULT_LIMIT = 10;

export async function search(query: string) {
  const q = (query ?? "").trim();
  if (!q) return { jobs: [], candidates: [] };
  const jobs = await prisma.job.findMany({
    where: { OR: [{ title: { contains: q, mode: "insensitive" } }, { roleId: { contains: q, mode: "insensitive" } }] },
    orderBy: { updatedAt: "desc" },
    take: SEARCH_RESULT_LIMIT,
  });
  const candidates = await prisma.canonicalCandidate.findMany({
    where: { name: { contains: q, mode: "insensitive" } },
    orderBy: { updatedAt: "desc" },
    take: SEARCH_RESULT_LIMIT,
  });
  return {
    jobs: jobs.map((j) => ({ role_id: j.roleId, title: j.title })),
    candidates: candidates.map((c) => ({
      candidate_id: c.id, name: c.name, current_title: c.currentTitle, current_company: c.currentCompany,
    })),
  };
}

// ── cross-job analytics ──────────────────────────────────────────────

export async function analyticsOverview() {
  const totalJobs = await prisma.job.count();
  const totalCandidates = await prisma.canonicalCandidate.count();
  const evaluations = await prisma.candidateEvaluation.findMany();

  const tierDistribution: Record<string, number> = { A: 0, B: 0, C: 0, D: 0, not_prioritized: 0 };
  let decisionsRecorded = 0;
  let decisionsPending = 0;
  const decisionBreakdown: Record<string, number> = {};
  let totalPlacements = 0;
  let totalPlacementFees = 0;

  for (const ev of evaluations) {
    const p = ev.prioritization as any;
    if (!p) {
      tierDistribution.not_prioritized!++;
      continue;
    }
    if (p.tier in tierDistribution) tierDistribution[p.tier]!++;
    if (p.recruiter_decision) {
      decisionsRecorded++;
      decisionBreakdown[p.recruiter_decision] = (decisionBreakdown[p.recruiter_decision] ?? 0) + 1;
    } else {
      decisionsPending++;
    }
    if (p.placed) {
      totalPlacements++;
      totalPlacementFees += p.placement_fee ?? 0;
    }
  }

  return {
    total_jobs: totalJobs, total_candidates: totalCandidates, total_evaluations: evaluations.length,
    tier_distribution: tierDistribution, decisions_recorded: decisionsRecorded, decisions_pending: decisionsPending,
    decision_breakdown: decisionBreakdown, total_placements: totalPlacements, total_placement_fees: totalPlacementFees,
  };
}

const AWAITING_RESPONSE_STAGES = new Set(["CONTACTED", "RESPONDED", "RECRUITER_SCREEN", "HM_INTERVIEW", "FINAL_INTERVIEW"]);

export async function attentionNeeded(followUpThresholdDays = 3) {
  const needsFollowUp: Record<string, any>[] = [];
  const upcomingInterviews: Record<string, any>[] = [];
  const now = Date.now();

  for (const job of await listJobs()) {
    const roleId = job.role_id;
    const state = await loadRole(roleId);
    const candidates = state.candidates ?? {};
    const funnel = state.funnel ?? {};
    for (const [candidateId, record] of Object.entries<any>(funnel)) {
      const history = record.stage_history ?? [];
      if (!history.length) continue;
      const last = history[history.length - 1];
      const name = candidates[candidateId]?.name ?? candidateId;
      const currentStage = record.current_stage ?? "IDENTIFIED";

      const daysInStage = last.at ? (now - new Date(last.at).getTime()) / 86_400_000 : null;
      if (AWAITING_RESPONSE_STAGES.has(currentStage) && daysInStage !== null && daysInStage >= followUpThresholdDays) {
        needsFollowUp.push({
          role_id: roleId, job_title: job.title, candidate_id: candidateId, candidate_name: name,
          current_stage: currentStage, days_in_stage: Math.floor(daysInStage),
        });
      }
      if (last.scheduled_at && new Date(last.scheduled_at).getTime() > now) {
        upcomingInterviews.push({
          role_id: roleId, job_title: job.title, candidate_id: candidateId, candidate_name: name,
          current_stage: currentStage, scheduled_at: last.scheduled_at,
        });
      }
    }
  }
  needsFollowUp.sort((a, b) => b.days_in_stage - a.days_in_stage);
  upcomingInterviews.sort((a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime());
  return { needs_follow_up: needsFollowUp, upcoming_interviews: upcomingInterviews };
}

export async function velocityReport() {
  const jobs = await listJobs();
  const jobsById = new Map(jobs.map((j) => [j.role_id, j]));

  const emptyConv = { sourced: 0, tiered_a: 0, pursued: 0, placed: 0 };
  const convByRole = new Map<string, typeof emptyConv>();
  const convByRecruiter = new Map<string, typeof emptyConv>();
  const stageDaysByRole = new Map<string, Map<string, number[]>>();
  const stageDaysByRecruiter = new Map<string, Map<string, number[]>>();

  function bump(bucket: Map<string, typeof emptyConv>, key: string, field: keyof typeof emptyConv) {
    if (!bucket.has(key)) bucket.set(key, { ...emptyConv });
    bucket.get(key)![field]++;
  }

  for (const [roleId, job] of jobsById) {
    const owner = job.owner_email as string | null;
    const state = await loadRole(roleId);
    const candidates = state.candidates ?? {};
    const prioritizations = state.prioritizations ?? {};
    const funnel = state.funnel ?? {};

    for (const candidateId of Object.keys(candidates)) {
      bump(convByRole, roleId, "sourced");
      if (owner) bump(convByRecruiter, owner, "sourced");
      const p = prioritizations[candidateId];
      if (!p) continue;
      if (p.tier === "A") {
        bump(convByRole, roleId, "tiered_a");
        if (owner) bump(convByRecruiter, owner, "tiered_a");
      }
      if (p.recruiter_decision === "pursue") {
        bump(convByRole, roleId, "pursued");
        if (owner) bump(convByRecruiter, owner, "pursued");
      }
      if (p.placed) {
        bump(convByRole, roleId, "placed");
        if (owner) bump(convByRecruiter, owner, "placed");
      }
    }

    for (const record of Object.values<any>(funnel)) {
      const history = record.stage_history ?? [];
      for (let i = 0; i < history.length - 1; i++) {
        const stage = history[i].stage;
        const startRaw = history[i].at;
        const endRaw = history[i + 1].at;
        if (!stage || !startRaw || !endRaw) continue;
        const days = (new Date(endRaw).getTime() - new Date(startRaw).getTime()) / 86_400_000;
        if (days < 0) continue;
        if (!stageDaysByRole.has(roleId)) stageDaysByRole.set(roleId, new Map());
        const roleMap = stageDaysByRole.get(roleId)!;
        roleMap.set(stage, [...(roleMap.get(stage) ?? []), days]);
        if (owner) {
          if (!stageDaysByRecruiter.has(owner)) stageDaysByRecruiter.set(owner, new Map());
          const recMap = stageDaysByRecruiter.get(owner)!;
          recMap.set(stage, [...(recMap.get(stage) ?? []), days]);
        }
      }
    }
  }

  function avgDays(bucket?: Map<string, number[]>): Record<string, number> {
    const out: Record<string, number> = {};
    if (!bucket) return out;
    for (const [stage, vals] of bucket) out[stage] = Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
    return out;
  }

  const byRole = Array.from(jobsById.entries()).map(([roleId, job]) => ({
    role_id: roleId, title: job.title,
    conversion: convByRole.get(roleId) ?? { ...emptyConv },
    avg_days_in_stage: avgDays(stageDaysByRole.get(roleId)),
  }));
  const byRecruiter = Array.from(convByRecruiter.entries()).map(([email, conv]) => ({
    email, conversion: conv, avg_days_in_stage: avgDays(stageDaysByRecruiter.get(email)),
  }));

  return { by_role: byRole, by_recruiter: byRecruiter };
}

// ── background tasks ─────────────────────────────────────────────────

function taskDict(task: NonNullable<Awaited<ReturnType<typeof prisma.task.findUnique>>>) {
  return {
    task_id: task.id, role_id: task.roleId, kind: task.kind, status: task.status,
    args: task.args, result: task.result, error: task.error,
    created_at: task.createdAt, updated_at: task.updatedAt, finished_at: task.finishedAt,
  };
}

export async function createTask(roleId: string, kind: string, args: Record<string, any>) {
  const task = await prisma.task.create({
    data: { id: `task-${crypto.randomBytes(8).toString("hex")}`, roleId, kind, args, status: "pending" },
  });
  return taskDict(task);
}

export async function getTask(taskId: string) {
  const task = await prisma.task.findUnique({ where: { id: taskId } });
  return task ? taskDict(task) : null;
}

export async function listTasks(roleId: string) {
  const tasks = await prisma.task.findMany({ where: { roleId }, orderBy: { createdAt: "desc" } });
  return tasks.map(taskDict);
}

export async function updateTask(
  taskId: string, args: { status?: string; result?: any; error?: string | null }
) {
  const data: Record<string, any> = {};
  if (args.status) {
    data.status = args.status;
    if (args.status === "succeeded" || args.status === "failed") data.finishedAt = new Date();
  }
  if (args.result !== undefined) data.result = args.result;
  if (args.error !== undefined) data.error = args.error;
  const task = await prisma.task.update({ where: { id: taskId }, data });
  return taskDict(task);
}

export async function resetIncompleteTasks(errorMessage: string): Promise<number> {
  const result = await prisma.task.updateMany({
    where: { status: { in: ["pending", "running"] } },
    data: { status: "failed", error: errorMessage, finishedAt: new Date() },
  });
  return result.count;
}

// ── activity log ─────────────────────────────────────────────────────

export async function logActivity(
  roleId: string, userEmail: string, action: string, args: { detail?: string; candidateId?: string | null } = {}
) {
  await prisma.activityLog.create({
    data: { roleId, userEmail, action, detail: args.detail ?? "", candidateId: args.candidateId ?? null },
  });
}

export async function listActivity(roleId: string, limit = 50) {
  const rows = await prisma.activityLog.findMany({
    where: { roleId }, orderBy: { createdAt: "desc" }, take: limit,
  });
  return rows.map((r) => ({
    id: r.id, role_id: r.roleId, user_email: r.userEmail, action: r.action,
    detail: r.detail, candidate_id: r.candidateId, created_at: r.createdAt,
  }));
}

export async function teamUsage() {
  const users = await prisma.user.findMany({ orderBy: { createdAt: "asc" } });
  const logs = await prisma.activityLog.findMany();
  const jobs = await prisma.job.findMany();
  const evaluations = await prisma.candidateEvaluation.findMany();

  const logsByUser = new Map<string, typeof logs>();
  for (const log of logs) {
    const list = logsByUser.get(log.userEmail) ?? [];
    list.push(log);
    logsByUser.set(log.userEmail, list);
  }

  const jobsOwnedByUser = new Map<string, number>();
  const openJobsByUser = new Map<string, number>();
  const ownerByRole = new Map<string, string>();
  const jobByRole = new Map<string, (typeof jobs)[number]>();
  for (const job of jobs) {
    jobByRole.set(job.roleId, job);
    if (job.ownerEmail) {
      jobsOwnedByUser.set(job.ownerEmail, (jobsOwnedByUser.get(job.ownerEmail) ?? 0) + 1);
      ownerByRole.set(job.roleId, job.ownerEmail);
      if (job.lifecycleStatus === "OPEN") {
        openJobsByUser.set(job.ownerEmail, (openJobsByUser.get(job.ownerEmail) ?? 0) + 1);
      }
    }
  }

  const placementsByUser = new Map<string, number>();
  const feesByUser = new Map<string, number>();
  const activeCandidatesByUser = new Map<string, number>();
  for (const ev of evaluations) {
    const p = ev.prioritization as any;
    const owner = ownerByRole.get(ev.roleId);
    const job = jobByRole.get(ev.roleId);
    if (p?.placed) {
      if (owner) {
        placementsByUser.set(owner, (placementsByUser.get(owner) ?? 0) + 1);
        feesByUser.set(owner, (feesByUser.get(owner) ?? 0) + (p.placement_fee ?? 0));
      }
      continue;
    }
    if (owner && job && job.lifecycleStatus === "OPEN" && (!p || p.recruiter_decision !== "pass for now")) {
      activeCandidatesByUser.set(owner, (activeCandidatesByUser.get(owner) ?? 0) + 1);
    }
  }

  const recruiters = users.map((u) => {
    const userLogs = logsByUser.get(u.email) ?? [];
    const candidatesAdded = userLogs.filter((l) => l.action.startsWith("added candidate")).length;
    const lastActive = userLogs.length
      ? userLogs.reduce((max, l) => (l.createdAt > max ? l.createdAt : max), userLogs[0]!.createdAt)
      : null;
    return {
      email: u.email, joined_at: u.createdAt, jobs_owned: jobsOwnedByUser.get(u.email) ?? 0,
      candidates_added: candidatesAdded, total_actions: userLogs.length, last_active: lastActive,
      placements: placementsByUser.get(u.email) ?? 0, placement_fees: feesByUser.get(u.email) ?? 0,
      open_jobs: openJobsByUser.get(u.email) ?? 0, active_candidates: activeCandidatesByUser.get(u.email) ?? 0,
    };
  });

  return { total_users: users.length, recruiters };
}

// ── outreach follow-up reminders ─────────────────────────────────────

const FOLLOWUP_THRESHOLDS_DAYS: Record<number, number> = { 1: 3, 2: 6, 3: 9 };
const MAX_FOLLOWUP_STAGE = 3;
const DEFAULT_FOLLOWUP_TEMPLATE =
  "Hi {candidate_name},\n\n" +
  "Just following up on my note about the {role_title} role — wanted to check " +
  "if you'd had a chance to look it over. Happy to share more detail or jump " +
  "on a quick call, whichever's easier.\n\n" +
  "Best,\n{recruiter_name}";

export async function getWorkspaceSettings() {
  let row = await prisma.workspaceSettings.findUnique({ where: { id: "default" } });
  if (!row) {
    row = await prisma.workspaceSettings.create({
      data: { id: "default", followupTemplate: DEFAULT_FOLLOWUP_TEMPLATE },
    });
  }
  return { followup_template: row.followupTemplate, auto_send_followups: row.autoSendFollowups };
}

export async function setWorkspaceSettings(args: { followupTemplate?: string | null; autoSendFollowups?: boolean | null }) {
  const data: Record<string, any> = {};
  if (args.followupTemplate !== undefined && args.followupTemplate !== null) data.followupTemplate = args.followupTemplate;
  if (args.autoSendFollowups !== undefined && args.autoSendFollowups !== null) data.autoSendFollowups = args.autoSendFollowups;
  const row = await prisma.workspaceSettings.upsert({
    where: { id: "default" },
    update: data,
    create: { id: "default", followupTemplate: DEFAULT_FOLLOWUP_TEMPLATE, ...data },
  });
  return { followup_template: row.followupTemplate, auto_send_followups: row.autoSendFollowups };
}

export function renderFollowupMessage(
  template: string, args: { candidateName: string; roleTitle: string; recruiterName: string }
): string {
  try {
    return template
      .replace(/\{candidate_name\}/g, args.candidateName || "there")
      .replace(/\{role_title\}/g, args.roleTitle || "this role")
      .replace(/\{recruiter_name\}/g, args.recruiterName || "the team");
  } catch {
    return template;
  }
}

export async function dueFollowups() {
  const settings = await getWorkspaceSettings();
  const now = Date.now();
  const jobs = await prisma.job.findMany();
  const jobsById = new Map(jobs.map((j) => [j.roleId, j]));
  const evaluations = await prisma.candidateEvaluation.findMany({ where: { email: { not: "" } } });

  const due: Record<string, any>[] = [];
  for (const ev of evaluations) {
    const job = jobsById.get(ev.roleId);
    if (!job) continue;
    const entries = await prisma.communicationLogEntry.findMany({
      where: { roleId: ev.roleId, candidateEvaluationId: ev.candidateEvaluationId },
      orderBy: { createdAt: "asc" },
    });
    const initial = entries.find((e) => e.channel === "email" && e.direction === "outbound" && e.followupStage === 0);
    if (!initial) continue;
    const initialAt = initial.createdAt.getTime();
    const hasResponse = entries.some((e) => e.createdAt.getTime() > initialAt && e.direction === "inbound");
    if (hasResponse) continue;
    const sentStages = new Set(
      entries.filter((e) => e.channel === "email" && e.direction === "outbound" && e.followupStage > 0).map((e) => e.followupStage)
    );
    const nextStage = [1, 2, 3].find((s) => !sentStages.has(s));
    if (nextStage === undefined || nextStage > MAX_FOLLOWUP_STAGE) continue;
    const daysSince = (now - initialAt) / 86_400_000;
    if (daysSince < FOLLOWUP_THRESHOLDS_DAYS[nextStage]!) continue;
    const candidateName = (ev.data as any)?.name ?? "";
    due.push({
      role_id: ev.roleId, role_title: job.title || ev.roleId,
      candidate_id: ev.candidateEvaluationId, candidate_name: candidateName,
      email: ev.email, followup_stage: nextStage, days_since_initial_outreach: Math.round(daysSince * 10) / 10,
      draft_message: renderFollowupMessage(settings.followup_template, {
        candidateName, roleTitle: job.title || ev.roleId, recruiterName: job.ownerEmail || "",
      }),
    });
  }
  return due;
}
