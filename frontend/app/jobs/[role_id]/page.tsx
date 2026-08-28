"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  API_BASE,
  ApiError,
  ActivityEntry,
  Candidate,
  CanonicalCandidate,
  FUNNEL_STAGES,
  JOB_LIFECYCLE_LABELS,
  JOB_LIFECYCLE_STATUSES,
  Json,
  JobDetail,
  JobLifecycleStatus,
  addCandidate,
  bulkImportCandidates,
  cloneJob,
  getActivity,
  getCandidateGlobal,
  getFunnelReport,
  getJob,
  getWebhookConfig,
  listCandidates,
  markOutreachSent,
  outreachCandidate,
  pollTaskUntilDone,
  prioritizeCandidate,
  runCalibrate,
  runIcp,
  runIntake,
  runInterviewQuestions,
  runSearchStrategy,
  runTalentMap,
  screenCandidate,
  generateShareLink,
  revokeShareLink,
  setCandidateNote,
  setJobClient,
  setJobLifecycle,
  setJobOwner,
  setRecruiterDecision,
  setWebhookConfig,
  testWebhook,
  updateFunnelStage,
  updateIcpCriteria,
  uploadCandidate,
} from "@/lib/api";
import { StatusChip, rygVariant, tierVariant } from "@/components/StatusChip";
import { CopilotPanel } from "@/components/CopilotPanel";
import { useAuth } from "@/lib/auth-context";

const TABS = [
  "Overview",
  "Hiring Intelligence",
  "Interview Questions",
  "Talent Map",
  "Sourcing",
  "Candidates",
  "Outreach",
  "Pipeline",
  "Analytics",
] as const;
type Tab = (typeof TABS)[number];

export default function JobWorkspace() {
  const params = useParams<{ role_id: string }>();
  const roleId = params.role_id;

  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Overview");
  const [busy, setBusy] = useState<string | null>(null); // which action is in flight
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  // Bumped whenever the copilot changes something a tab fetches on its own
  // (candidates, funnel) — those tabs include this in their reload
  // dependency so a copilot action is visible without a manual tab switch.
  const [dataVersion, setDataVersion] = useState(0);

  const refresh = useCallback(() => {
    getJob(roleId)
      .then(setJob)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
  }, [roleId]);

  useEffect(refresh, [refresh]);

  function onCopilotAction() {
    refresh();
    setDataVersion((v) => v + 1);
  }

  async function runAction(name: string, action: () => Promise<unknown>) {
    setBusy(name);
    setError(null);
    try {
      await action();
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `${name} failed.`);
    } finally {
      setBusy(null);
    }
  }

  if (error && !job) {
    return <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">{error}</div>;
  }
  if (!job) return <p className="text-sm text-zinc-500">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{job.title}</h1>
          {job.role_family && <p className="mt-1 text-sm text-zinc-500">{job.role_family}</p>}
          <JobMetaRow job={job} refresh={refresh} />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={() => setCloneOpen((v) => !v)}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Clone as new role
          </button>
          <button
            onClick={() => setCopilotOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            AI Copilot
          </button>
        </div>
      </div>

      {cloneOpen && <CloneRoleForm roleId={roleId} defaultTitle={job.title} onClose={() => setCloneOpen(false)} />}

      <nav className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-t-md px-3 py-2 text-sm font-medium ${
              tab === t
                ? "border-b-2 border-indigo-700 text-indigo-800 dark:text-indigo-400"
                : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
            }`}
          >
            {t}
          </button>
        ))}
      </nav>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      {tab === "Overview" && <OverviewTab job={job} busy={busy} runAction={runAction} />}
      {tab === "Hiring Intelligence" && <HiringProfileTab job={job} busy={busy} runAction={runAction} />}
      {tab === "Interview Questions" && <InterviewQuestionsTab job={job} busy={busy} runAction={runAction} />}
      {tab === "Talent Map" && <TalentMapTab job={job} busy={busy} runAction={runAction} />}
      {tab === "Sourcing" && <SourcingTab job={job} busy={busy} runAction={runAction} />}
      {tab === "Candidates" && (
        <CandidatesTab roleId={roleId} job={job} refresh={refresh} dataVersion={dataVersion} />
      )}
      {tab === "Outreach" && <OutreachTab roleId={roleId} job={job} refresh={refresh} dataVersion={dataVersion} />}
      {tab === "Pipeline" && (
        <PipelineTab roleId={roleId} job={job} refresh={refresh} dataVersion={dataVersion} />
      )}
      {tab === "Analytics" && <AnalyticsTab roleId={roleId} dataVersion={dataVersion} />}

      <CopilotPanel
        roleId={roleId}
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        onAction={onCopilotAction}
      />
    </div>
  );
}

// ── job lifecycle + ownership (Phase 10) ────────────────────────────────

function JobMetaRow({ job, refresh }: { job: JobDetail; refresh: () => void }) {
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);
  const [editingOwner, setEditingOwner] = useState(false);
  const [ownerDraft, setOwnerDraft] = useState(job.owner_email ?? "");
  const [editingClient, setEditingClient] = useState(false);
  const [clientDraft, setClientDraft] = useState(job.client_name ?? "");
  const [linkCopied, setLinkCopied] = useState(false);

  async function changeLifecycle(status: JobLifecycleStatus) {
    setBusy(true);
    try {
      await setJobLifecycle(job.role_id, status);
      refresh();
    } catch {
      // surfaced implicitly — refresh() below will just show the unchanged value
    } finally {
      setBusy(false);
    }
  }

  async function saveOwner() {
    setBusy(true);
    try {
      await setJobOwner(job.role_id, ownerDraft.trim() || null);
      refresh();
      setEditingOwner(false);
    } finally {
      setBusy(false);
    }
  }

  async function saveClient() {
    setBusy(true);
    try {
      await setJobClient(job.role_id, clientDraft.trim() || null);
      refresh();
      setEditingClient(false);
    } finally {
      setBusy(false);
    }
  }

  async function generateLink() {
    setBusy(true);
    try {
      await generateShareLink(job.role_id);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function revokeLink() {
    setBusy(true);
    try {
      await revokeShareLink(job.role_id);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  function copyLink() {
    const url = `${window.location.origin}/share/${job.share_token}`;
    navigator.clipboard.writeText(url).then(() => {
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    });
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-zinc-500">
      <select
        value={job.lifecycle_status}
        onChange={(e) => changeLifecycle(e.target.value as JobLifecycleStatus)}
        disabled={busy}
        aria-label="Job status"
        className={`rounded border px-2 py-1 text-xs font-medium outline-none disabled:opacity-50 ${
          job.lifecycle_status === "OPEN" || job.lifecycle_status === "FILLED"
            ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-400"
            : "border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400"
        }`}
      >
        {JOB_LIFECYCLE_STATUSES.map((s) => (
          <option key={s} value={s}>{JOB_LIFECYCLE_LABELS[s]}</option>
        ))}
      </select>

      {editingOwner ? (
        <span className="flex items-center gap-1">
          <input
            value={ownerDraft}
            onChange={(e) => setOwnerDraft(e.target.value)}
            placeholder="owner email"
            className="rounded border border-zinc-300 px-1.5 py-0.5 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
          />
          <button onClick={saveOwner} disabled={busy} className="text-indigo-700 hover:underline dark:text-indigo-400">Save</button>
          <button onClick={() => setEditingOwner(false)} className="text-zinc-400 hover:underline">Cancel</button>
        </span>
      ) : (
        <button
          onClick={() => { setOwnerDraft(job.owner_email ?? ""); setEditingOwner(true); }}
          className="hover:underline"
        >
          Owner: {job.owner_email ?? "unassigned"}
          {job.owner_email && job.owner_email === user?.email ? " (you)" : ""}
        </button>
      )}

      {editingClient ? (
        <span className="flex items-center gap-1">
          <input
            value={clientDraft}
            onChange={(e) => setClientDraft(e.target.value)}
            placeholder="client name"
            className="rounded border border-zinc-300 px-1.5 py-0.5 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
          />
          <button onClick={saveClient} disabled={busy} className="text-indigo-700 hover:underline dark:text-indigo-400">Save</button>
          <button onClick={() => setEditingClient(false)} className="text-zinc-400 hover:underline">Cancel</button>
        </span>
      ) : (
        <button
          onClick={() => { setClientDraft(job.client_name ?? ""); setEditingClient(true); }}
          className="hover:underline"
        >
          Client: {job.client_name ?? "none"}
        </button>
      )}

      {job.share_token ? (
        <span className="flex items-center gap-1.5">
          <button onClick={copyLink} className="hover:underline">
            {linkCopied ? "Link copied" : "Copy client link"}
          </button>
          <button onClick={revokeLink} disabled={busy} className="text-zinc-400 hover:underline disabled:opacity-50">
            Revoke
          </button>
        </span>
      ) : (
        <button onClick={generateLink} disabled={busy} className="hover:underline disabled:opacity-50">
          Generate client link
        </button>
      )}
    </div>
  );
}

// ── role templates (Phase 8) ────────────────────────────────────────────

function CloneRoleForm({
  roleId, defaultTitle, onClose,
}: { roleId: string; defaultTitle: string; onClose: () => void }) {
  const router = useRouter();
  const [title, setTitle] = useState(`${defaultTitle} (copy)`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!title.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const cloned = await cloneJob(roleId, title.trim());
      router.push(`/jobs/${cloned.role_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not clone this role.");
      setBusy(false);
    }
  }

  return (
    <Card title="Clone this role's hiring strategy into a new job">
      <p className="mb-2 text-xs text-zinc-500">
        Copies the JD, calibration, hiring profile, and talent map/search strategy. Candidates, pipeline, and
        outreach are never carried over — the new job starts with a clean slate for people.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={title} onChange={(e) => setTitle(e.target.value)} placeholder="New role title"
          className="flex-1 min-w-40 rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
        />
        <ActionButton label="Create clone" busyLabel="Cloning…" busy={busy} disabled={!title.trim()} onClick={submit} />
        <button
          onClick={onClose}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Cancel
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </Card>
  );
}

// ── shared bits ────────────────────────────────────────────────────────

function ActionButton({
  label, busyLabel, onClick, busy, disabled,
}: { label: string; busyLabel: string; onClick: () => void; busy: boolean; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={busy || disabled}
      className="rounded-md bg-indigo-700 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
    >
      {busy ? busyLabel : label}
    </button>
  );
}

function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] dark:border-zinc-800">
      {title && <h3 className="mb-2 text-sm font-semibold text-zinc-500">{title}</h3>}
      {children}
    </div>
  );
}

function List({ items }: { items?: string[] }) {
  if (!items || items.length === 0) return <p className="text-sm text-zinc-400">—</p>;
  return (
    <ul className="list-disc space-y-1 pl-4 text-sm">
      {items.map((v, i) => <li key={i}>{v}</li>)}
    </ul>
  );
}

type StageProps = {
  job: JobDetail;
  busy: string | null;
  runAction: (name: string, action: () => Promise<unknown>) => void;
};

// ── Overview ───────────────────────────────────────────────────────────

function OverviewTab({ job, busy, runAction }: StageProps) {
  const [jdText, setJdText] = useState("");
  const jd: Json | undefined = job.state.job_description;

  if (!jd) {
    return (
      <div className="flex flex-col gap-4">
        <Card title="Analyse the job description">
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={10}
            placeholder="Paste the JD here…"
            className="w-full rounded-md border border-zinc-300 p-3 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
          />
          <div className="mt-3">
            <ActionButton
              label="Analyse JD" busyLabel="Analysing…" busy={busy === "intake"}
              disabled={!jdText.trim()}
              onClick={() => runAction("intake", () => runIntake(job.role_id, jdText))}
            />
          </div>
        </Card>
        <ActivityFeed roleId={job.role_id} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Role">
          <dl className="space-y-1 text-sm">
            <Row label="Company" value={jd.company} />
            <Row label="Title" value={jd.role_title} />
            <Row label="Seniority" value={jd.seniority} />
            <Row label="Geography" value={jd.geography} />
            <Row label="Objective" value={jd.role_objective} />
          </dl>
        </Card>
        <Card title="Must-haves">
          <List items={jd.must_have_requirements} />
        </Card>
        {jd.contradictions?.length > 0 && (
          <Card title="Contradictions flagged">
            <List items={jd.contradictions} />
          </Card>
        )}
        {jd.missing_critical_information?.length > 0 && (
          <Card title="Missing critical information">
            <List items={jd.missing_critical_information} />
          </Card>
        )}
      </div>
      <ActivityFeed roleId={job.role_id} />
    </div>
  );
}

// Who did what, when (Phase 8) — see api.py's _log() and
// db_storage.log_activity. Refetches on every mount (tab switch) rather
// than polling; this is a look-back log, not a live feed.
function ActivityFeed({ roleId }: { roleId: string }) {
  const [entries, setEntries] = useState<ActivityEntry[] | null>(null);

  useEffect(() => {
    getActivity(roleId).then(setEntries).catch(() => setEntries([]));
  }, [roleId]);

  if (!entries || entries.length === 0) return null;

  return (
    <Card title="Recent activity">
      <ul className="flex flex-col gap-1.5 text-sm">
        {entries.slice(0, 15).map((e) => (
          <li key={e.id} className="flex items-baseline justify-between gap-3 text-xs">
            <span>
              <span className="font-medium text-zinc-700 dark:text-zinc-300">{e.user_email}</span>{" "}
              <span className="text-zinc-500">{e.action}</span>
              {e.detail && <span className="text-zinc-400"> — {e.detail}</span>}
            </span>
            <span className="shrink-0 text-zinc-400">{new Date(e.created_at).toLocaleString()}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Row({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-24 shrink-0 text-zinc-500">{label}</dt>
      <dd>{value || "—"}</dd>
    </div>
  );
}

// ── Hiring Profile (calibration + icp) ────────────────────────────────

function HiringProfileTab({ job, busy, runAction }: StageProps) {
  const calibration: Json | undefined = job.state.calibration;
  const icp: Json | undefined = job.state.icp;

  return (
    <div className="flex flex-col gap-4">
      {!job.status.intake && <p className="text-sm text-zinc-500">Run Overview → Analyse JD first.</p>}

      {job.status.intake && !calibration && (
        <ActionButton
          label="Run calibration" busyLabel="Calibrating…" busy={busy === "calibration"}
          onClick={() => runAction("calibration", () => runCalibrate(job.role_id))}
        />
      )}

      {calibration && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Must-have criteria"><List items={calibration.must_have_criteria} /></Card>
          <Card title="Red flags"><List items={calibration.red_flags} /></Card>
          {calibration.unrealistic_requirements_flag && (
            <Card title="⚠ Unrealistic requirements flag">
              <p className="text-sm">{calibration.unrealistic_requirements_flag}</p>
            </Card>
          )}
        </div>
      )}

      {calibration && !icp && (
        <ActionButton
          label="Build hiring profile (ICP)" busyLabel="Building…" busy={busy === "icp"}
          onClick={() => runAction("icp", () => runIcp(job.role_id))}
        />
      )}

      {icp && (
        <div className="grid gap-4 md:grid-cols-2">
          <EditableCriteriaList
            title="Must have" roleId={job.role_id} field="must_have" items={icp.must_have ?? []}
            busy={busy} runAction={runAction}
          />
          <EditableCriteriaList
            title="Nice to have" roleId={job.role_id} field="nice_to_have" items={icp.nice_to_have ?? []}
            busy={busy} runAction={runAction}
          />
          <Card title="Transferable"><List items={icp.transferable} /></Card>
          <Card title="Disqualifier"><List items={icp.disqualifier} /></Card>
        </div>
      )}
    </div>
  );
}

// ── Interview Questions ────────────────────────────────────────────────
// Role-level, generated once from the ICP + calibration (varies per
// role) — distinct from the per-candidate screening questions on the
// Candidates tab, which validate one specific candidate's own record.

function QuestionList({ items }: { items?: { question: string; why_it_matters: string }[] }) {
  if (!items || items.length === 0) return <p className="text-sm text-zinc-400">—</p>;
  return (
    <ul className="space-y-3 text-sm">
      {items.map((q, i) => (
        <li key={i}>
          <p className="font-medium">{q.question}</p>
          {q.why_it_matters && <p className="mt-0.5 text-xs text-zinc-500">{q.why_it_matters}</p>}
        </li>
      ))}
    </ul>
  );
}

function InterviewQuestionsTab({ job, busy, runAction }: StageProps) {
  const icp: Json | undefined = job.state.icp;
  const questions: Json | undefined = job.state.interview_questions;

  if (!icp) {
    return <p className="text-sm text-zinc-500">Build the hiring profile (ICP) on the Hiring Intelligence tab first.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <ActionButton
        label={questions ? "Regenerate questions" : "Generate interview questions"}
        busyLabel="Writing…" busy={busy === "interview_questions"}
        onClick={() => runAction("interview_questions", () => runInterviewQuestions(job.role_id))}
      />

      {questions && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card title="Core questions"><QuestionList items={questions.core_questions} /></Card>
          <Card title="Specific to this role"><QuestionList items={questions.role_specific_questions} /></Card>
          <Card title="Red-flag follow-ups"><QuestionList items={questions.red_flag_questions} /></Card>
        </div>
      )}
    </div>
  );
}

// Rubric tuning (Phase 8): the recruiter's own direct edit to the
// scoring criteria — add/remove an item, save, done. Distinct from the
// AI Copilot's propose/apply flow (that's for AI-suggested edits); this
// is deterministic, no confirmation step needed since it's the
// recruiter's own hand on their own criteria. Save goes through the
// parent's runAction so a successful save refetches job.state.icp,
// which is what actually clears "unsaved changes" here.
function EditableCriteriaList({
  title, roleId, field, items, busy, runAction,
}: {
  title: string; roleId: string; field: "must_have" | "nice_to_have"; items: string[];
  busy: string | null; runAction: (name: string, action: () => Promise<unknown>) => void;
}) {
  const [prevItems, setPrevItems] = useState(items);
  const [draft, setDraft] = useState<string[]>(items);
  const [newItem, setNewItem] = useState("");
  const busyKey = `criteria-${field}`;

  // Adjusting state from a prop change during render, not in an effect
  // (React's recommended pattern for this) — a fresh job.state.icp after
  // a successful save is what clears "unsaved changes" here.
  if (items !== prevItems) {
    setPrevItems(items);
    setDraft(items);
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(items);

  function addItem() {
    if (!newItem.trim()) return;
    setDraft((prev) => [...prev, newItem.trim()]);
    setNewItem("");
  }

  function removeItem(i: number) {
    setDraft((prev) => prev.filter((_, idx) => idx !== i));
  }

  function save() {
    runAction(busyKey, () =>
      field === "must_have" ? updateIcpCriteria(roleId, draft, undefined) : updateIcpCriteria(roleId, undefined, draft)
    );
  }

  return (
    <Card title={title}>
      {draft.length === 0 ? (
        <p className="mb-2 text-sm text-zinc-400">—</p>
      ) : (
        <ul className="mb-2 space-y-1 text-sm">
          {draft.map((v, i) => (
            <li key={i} className="flex items-center justify-between gap-2">
              <span>{v}</span>
              <button
                onClick={() => removeItem(i)}
                aria-label={`Remove ${v}`}
                className="text-xs text-zinc-400 hover:text-red-600 dark:hover:text-red-400"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addItem()}
          placeholder="Add criterion…"
          className="flex-1 rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
        />
        <button
          onClick={addItem}
          className="rounded-md border border-zinc-300 px-2.5 py-1 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Add
        </button>
      </div>
      {dirty && (
        <div className="mt-2 flex items-center gap-2">
          <button
            onClick={save}
            disabled={busy === busyKey}
            className="rounded-md bg-indigo-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
          >
            {busy === busyKey ? "Saving…" : "Save criteria"}
          </button>
          <span className="text-xs text-zinc-400">unsaved changes</span>
        </div>
      )}
    </Card>
  );
}

// ── Talent Map ─────────────────────────────────────────────────────────

function TalentMapTab({ job, busy, runAction }: StageProps) {
  const tm: Json | undefined = job.state.talent_map;
  const companies: Json[] = tm?.target_companies ?? [];

  return (
    <div className="flex flex-col gap-4">
      {!job.status.icp && <p className="text-sm text-zinc-500">Build the hiring profile first.</p>}
      {job.status.icp && companies.length === 0 && (
        <ActionButton
          label="Build talent map" busyLabel="Mapping…" busy={busy === "talent_map"}
          onClick={() => runAction("talent_map", () => runTalentMap(job.role_id))}
        />
      )}
      {companies.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {companies.map((c, i) => (
            <Card key={i}>
              <div className="mb-1 flex items-center justify-between">
                <h3 className="font-medium">{c.name}</h3>
                <StatusChip label={`Tier ${c.tier}`} variant={c.tier === 1 ? "ok" : c.tier === 2 ? "running" : "pending"} />
              </div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">{c.why_relevant}</p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Sourcing (search strategy) ─────────────────────────────────────────

function SourcingTab({ job, busy, runAction }: StageProps) {
  const tm: Json | undefined = job.state.talent_map;
  const companies: Json[] = tm?.target_companies ?? [];
  const strategies: Json[] = tm?.search_strategies ?? [];

  return (
    <div className="flex flex-col gap-4">
      {companies.length === 0 && <p className="text-sm text-zinc-500">Build the talent map first.</p>}
      {companies.length > 0 && strategies.length === 0 && (
        <ActionButton
          label="Create sourcing strategy" busyLabel="Generating…" busy={busy === "search_strategy"}
          onClick={() => runAction("search_strategy", () => runSearchStrategy(job.role_id))}
        />
      )}
      {strategies.map((s, i) => (
        <Card key={i} title={`${s.name} · ${s.search_type}`}>
          <p className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">{s.purpose}</p>
          {s.linkedin_boolean && <BooleanBlock label="LinkedIn" value={s.linkedin_boolean} />}
          {s.google_xray && <BooleanBlock label="Google X-ray" value={s.google_xray} />}
          {s.naukri_search && <BooleanBlock label="Naukri" value={s.naukri_search} />}
          {s.github_search && <BooleanBlock label="GitHub" value={s.github_search} />}
        </Card>
      ))}
    </div>
  );
}

function BooleanBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-2">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <code className="block overflow-x-auto rounded bg-zinc-100 px-2 py-1 text-xs dark:bg-zinc-800">{value}</code>
    </div>
  );
}

// ── Candidates ─────────────────────────────────────────────────────────

function CandidatesTab({
  roleId, job, refresh, dataVersion,
}: { roleId: string; job: JobDetail; refresh: () => void; dataVersion: number }) {
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [roleFamily, setRoleFamily] = useState(job.role_family ?? "");
  const [sourceUrl, setSourceUrl] = useState("");
  const [addMode, setAddMode] = useState<"paste" | "upload" | "bulk">("paste");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [decisionDraft, setDecisionDraft] = useState<Record<string, string>>({});
  // "loading" while the cross-job fetch is in flight, null once it fails or
  // resolves to nothing worth showing — undefined means never fetched yet.
  const [crossJob, setCrossJob] = useState<Record<string, CanonicalCandidate | "loading" | null>>({});
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comparing, setComparing] = useState(false);

  function toggleSelected(candidateId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  }

  const loadCandidates = useCallback(() => {
    listCandidates(roleId)
      .then(setCandidates)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load candidates."));
  }, [roleId]);

  useEffect(loadCandidates, [loadCandidates, dataVersion]);

  async function run(name: string, action: () => Promise<unknown>) {
    setBusy(name);
    setError(null);
    try {
      await action();
      loadCandidates();
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `${name} failed.`);
    } finally {
      setBusy(null);
    }
  }

  function toggleExpand(c: Candidate) {
    const opening = expanded !== c.candidate_id;
    setExpanded(opening ? c.candidate_id : null);
    if (opening && c.canonical_candidate_id && crossJob[c.candidate_id] === undefined) {
      setCrossJob((prev) => ({ ...prev, [c.candidate_id]: "loading" }));
      getCandidateGlobal(c.canonical_candidate_id)
        .then((detail) => setCrossJob((prev) => ({ ...prev, [c.candidate_id]: detail })))
        .catch(() => setCrossJob((prev) => ({ ...prev, [c.candidate_id]: null })));
    }
  }

  function saveDecision(candidateId: string, decision: string) {
    return run(`dec-${candidateId}`, () => setRecruiterDecision(roleId, candidateId, decision));
  }

  async function bulkPrioritize() {
    const targets = (candidates ?? []).filter((c) => !c.prioritization);
    if (targets.length === 0) return;
    setError(null);
    setBulkProgress({ done: 0, total: targets.length });
    let done = 0;
    const results = await Promise.allSettled(
      targets.map((c) =>
        prioritizeCandidate(roleId, c.candidate_id).then(() => {
          done += 1;
          setBulkProgress({ done, total: targets.length });
        })
      )
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed > 0) setError(`${failed} of ${targets.length} candidates failed to prioritize.`);
    setBulkProgress(null);
    loadCandidates();
    refresh();
  }

  async function bulkImportCsv() {
    if (!csvFile || !roleFamily.trim()) return;
    setError(null);
    setBusy("add");
    try {
      const result = await bulkImportCandidates(roleId, csvFile, roleFamily);
      if (result.queued === 0) {
        setError("No candidates found in that CSV — check that the 'notes' column has text in every row.");
        return;
      }
      setBulkProgress({ done: 0, total: result.queued });
      let done = 0;
      const results = await Promise.allSettled(
        result.task_ids.map((taskId) =>
          pollTaskUntilDone(roleId, taskId).then((task) => {
            done += 1;
            setBulkProgress({ done, total: result.queued });
            if (task.status === "failed") throw new Error(task.error ?? "import failed");
          })
        )
      );
      const failed = results.filter((r) => r.status === "rejected").length;
      if (failed > 0) setError(`${failed} of ${result.queued} candidates failed to import.`);
      setCsvFile(null);
      setShowAddForm(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Bulk import failed.");
    } finally {
      setBulkProgress(null);
      setBusy(null);
      loadCandidates();
      refresh();
    }
  }

  if (!job.status.icp) return <p className="text-sm text-zinc-500">Build the hiring profile first — candidates are evaluated against it.</p>;

  const unscored = (candidates ?? []).filter((c) => !c.prioritization);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-500">
          {bulkProgress
            ? `Prioritizing ${bulkProgress.done}/${bulkProgress.total}…`
            : `${candidates?.length ?? 0} candidate${candidates?.length === 1 ? "" : "s"}`}
        </h2>
        <div className="flex gap-2">
          {unscored.length > 0 && (
            <button
              onClick={bulkPrioritize}
              disabled={bulkProgress !== null}
              className="rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Prioritize all ({unscored.length})
            </button>
          )}
          {selected.size >= 2 && (
            <button
              onClick={() => setComparing(true)}
              className="rounded-md border border-indigo-600 px-3 py-2 text-sm font-medium text-indigo-800 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-950"
            >
              Compare selected ({selected.size})
            </button>
          )}
          <a
            href={`${API_BASE}/jobs/${roleId}/candidates/export.csv`}
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Export CSV
          </a>
          <a
            href={`${API_BASE}/jobs/${roleId}/candidates/export.json`}
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Export JSON
          </a>
          <Link
            href={`/jobs/${roleId}/print`}
            target="_blank"
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Print report
          </Link>
          <button
            onClick={() => setShowAddForm((v) => !v)}
            className="rounded-md bg-indigo-700 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-800"
          >
            {showAddForm ? "Cancel" : "+ Add candidate"}
          </button>
        </div>
      </div>

      {showAddForm && (
        <Card title="Add a candidate">
          <div className="flex flex-col gap-3">
            <div className="flex gap-1 rounded-md border border-zinc-300 p-1 text-sm dark:border-zinc-700 w-fit">
              {(["paste", "upload", "bulk"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setAddMode(m)}
                  className={`rounded px-3 py-1 font-medium ${
                    addMode === m
                      ? "bg-indigo-700 text-white"
                      : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  }`}
                >
                  {m === "paste" ? "Paste text" : m === "upload" ? "Upload file" : "Bulk CSV"}
                </button>
              ))}
            </div>

            {addMode === "paste" ? (
              <textarea
                value={sourceText} onChange={(e) => setSourceText(e.target.value)} rows={6}
                placeholder="Paste resume text / LinkedIn profile text / recruiter notes…"
                className="w-full rounded-md border border-zinc-300 p-3 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
              />
            ) : addMode === "upload" ? (
              <div>
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  className="w-full rounded-md border border-zinc-300 p-3 text-sm outline-none file:mr-3 file:rounded file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-zinc-200 dark:border-zinc-700 dark:bg-zinc-950 dark:file:bg-zinc-800 dark:hover:file:bg-zinc-700"
                />
                <p className="mt-1 text-xs text-zinc-500">PDF, DOCX, or TXT — text is extracted, then analysed same as pasted text.</p>
              </div>
            ) : (
              <div>
                <input
                  type="file"
                  accept=".csv"
                  onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                  className="w-full rounded-md border border-zinc-300 p-3 text-sm outline-none file:mr-3 file:rounded file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-zinc-200 dark:border-zinc-700 dark:bg-zinc-950 dark:file:bg-zinc-800 dark:hover:file:bg-zinc-700"
                />
                <p className="mt-1 text-xs text-zinc-500">
                  One row per candidate. Needs a <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">notes</code>{" "}
                  column (resume text or recruiter notes) — an optional{" "}
                  <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">source_url</code> column too. Other columns
                  are ignored.
                </p>
                {bulkProgress && (
                  <p className="mt-2 text-sm font-medium text-indigo-700 dark:text-indigo-400">
                    Importing {bulkProgress.done}/{bulkProgress.total}…
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <input
                value={roleFamily} onChange={(e) => setRoleFamily(e.target.value)} placeholder="role family (sales, csm…)"
                className="flex-1 min-w-40 rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
              />
              {addMode !== "bulk" && (
                <input
                  value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="source URL (optional)"
                  className="flex-1 min-w-40 rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
                />
              )}
              {addMode === "paste" ? (
                <ActionButton
                  label="Add candidate" busyLabel="Analysing…" busy={busy === "add"}
                  disabled={!sourceText.trim() || !roleFamily.trim()}
                  onClick={() =>
                    run("add", () => addCandidate(roleId, sourceText, roleFamily, sourceUrl)).then(() => {
                      setSourceText(""); setSourceUrl(""); setShowAddForm(false);
                    })
                  }
                />
              ) : addMode === "upload" ? (
                <ActionButton
                  label="Upload & add" busyLabel="Analysing…" busy={busy === "add"}
                  disabled={!uploadFile || !roleFamily.trim()}
                  onClick={() =>
                    run("add", () => uploadCandidate(roleId, uploadFile!, roleFamily, sourceUrl)).then(() => {
                      setUploadFile(null); setSourceUrl(""); setShowAddForm(false);
                    })
                  }
                />
              ) : (
                <ActionButton
                  label="Import candidates" busyLabel="Importing…" busy={busy === "add"}
                  disabled={!csvFile || !roleFamily.trim()}
                  onClick={bulkImportCsv}
                />
              )}
            </div>
          </div>
        </Card>
      )}

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">{error}</div>}

      {comparing && (
        <CandidateComparison
          candidates={(candidates ?? []).filter((c) => selected.has(c.candidate_id))}
          onClose={() => setComparing(false)}
        />
      )}

      {candidates === null ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : candidates.length === 0 ? (
        <p className="text-sm text-zinc-500">No candidates yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900">
              <tr>
                <th className="px-4 py-2 font-medium">
                  <span className="sr-only">Select</span>
                </th>
                <th className="px-4 py-2 font-medium">Candidate</th>
                <th className="px-4 py-2 font-medium">Role &amp; company</th>
                <th className="px-4 py-2 font-medium">Tier</th>
                <th className="px-4 py-2 font-medium">Pipeline stage</th>
                <th className="px-4 py-2 font-medium">Outreach</th>
                <th className="px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {candidates.map((c) => {
                const isOpen = expanded === c.candidate_id;
                const stage = job.state.funnel?.[c.candidate_id]?.current_stage ?? "IDENTIFIED";
                const outreachDrafted = Boolean(job.state.outreach?.[c.candidate_id]);
                return (
                  <Fragment key={c.candidate_id}>
                    <tr className="hover:bg-zinc-50 dark:hover:bg-zinc-900/50">
                      <td className="px-4 py-2.5">
                        <input
                          type="checkbox"
                          checked={selected.has(c.candidate_id)}
                          onChange={() => toggleSelected(c.candidate_id)}
                          aria-label={`Select ${c.name} to compare`}
                        />
                      </td>
                      <td className="px-4 py-2.5 font-medium">
                        <button onClick={() => toggleExpand(c)} className="hover:underline">
                          {c.name}
                        </button>
                      </td>
                      <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">
                        {c.current_title} @ {c.current_company}
                      </td>
                      <td className="px-4 py-2.5">
                        {c.prioritization ? (
                          <div className="flex items-center gap-1.5">
                            <StatusChip label={c.prioritization.tier} variant={tierVariant(c.prioritization.tier)} />
                            <StatusChip
                              label={`${c.prioritization.fit_rating} · ${c.prioritization.fit_score}`}
                              variant={rygVariant(c.prioritization.fit_rating)}
                            />
                          </div>
                        ) : (
                          <StatusChip label="—" variant="pending" />
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-zinc-500">{stage}</td>
                      <td className="px-4 py-2.5">
                        <StatusChip label={outreachDrafted ? "Drafted" : "—"} variant={outreachDrafted ? "ok" : "pending"} />
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex gap-2">
                          <button
                            onClick={() => run(`pri-${c.candidate_id}`, () => prioritizeCandidate(roleId, c.candidate_id))}
                            disabled={busy === `pri-${c.candidate_id}`}
                            className="rounded-md border border-zinc-300 px-2 py-1 text-xs font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                          >
                            {busy === `pri-${c.candidate_id}` ? "Scoring…" : c.prioritization ? "Re-rank" : "Prioritize"}
                          </button>
                          <button
                            onClick={() => toggleExpand(c)}
                            className="rounded-md border border-zinc-300 px-2 py-1 text-xs font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                          >
                            {isOpen ? "Hide" : "View"}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={7} className="border-t border-zinc-100 bg-zinc-50/50 px-4 py-4 dark:border-zinc-800 dark:bg-zinc-950/50">
                          <div className="flex flex-col gap-3">
                            <button
                              onClick={() => run(`scr-${c.candidate_id}`, () => screenCandidate(roleId, c.candidate_id))}
                              disabled={!c.prioritization || busy === `scr-${c.candidate_id}`}
                              className="self-start rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                            >
                              {busy === `scr-${c.candidate_id}` ? "Writing…" : "Generate screening questions"}
                            </button>

                            <Card title="Compensation & availability">
                              <dl className="space-y-1 text-sm">
                                <Row label="Current CTC" value={c.current_ctc} />
                                <Row label="Expected CTC" value={c.expected_ctc} />
                                <Row label="Notice period" value={c.notice_period} />
                              </dl>
                            </Card>

                            {c.prioritization && (
                              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                                <Card title="Why they fit"><List items={c.prioritization.why_they_fit} /></Card>
                                <Card title="Weaknesses"><List items={c.prioritization.weaknesses} /></Card>
                                <Card title="Unknown"><List items={c.prioritization.what_is_unknown} /></Card>
                                <Card title="To validate"><List items={c.prioritization.what_to_validate} /></Card>
                              </div>
                            )}

                            {c.prioritization && (
                              <Card title="Recruiter decision">
                                <div className="flex flex-col gap-2">
                                  <div className="flex flex-wrap gap-2">
                                    {["pursue", "pass for now", "revisit later"].map((d) => (
                                      <button
                                        key={d}
                                        onClick={() => saveDecision(c.candidate_id, d)}
                                        disabled={busy === `dec-${c.candidate_id}`}
                                        className={`rounded-md border px-2.5 py-1 text-xs font-medium capitalize disabled:opacity-50 ${
                                          c.prioritization?.recruiter_decision === d
                                            ? "border-indigo-600 bg-indigo-50 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300"
                                            : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                                        }`}
                                      >
                                        {d}
                                      </button>
                                    ))}
                                  </div>
                                  <div className="flex gap-2">
                                    <input
                                      value={decisionDraft[c.candidate_id] ?? c.prioritization.recruiter_decision ?? ""}
                                      onChange={(e) =>
                                        setDecisionDraft((prev) => ({ ...prev, [c.candidate_id]: e.target.value }))
                                      }
                                      placeholder="Custom decision…"
                                      className="flex-1 rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
                                    />
                                    <button
                                      onClick={() => saveDecision(c.candidate_id, decisionDraft[c.candidate_id] ?? "")}
                                      disabled={busy === `dec-${c.candidate_id}`}
                                      className="rounded-md bg-indigo-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
                                    >
                                      Save
                                    </button>
                                    {c.prioritization.recruiter_decision && (
                                      <button
                                        onClick={() => saveDecision(c.candidate_id, "")}
                                        disabled={busy === `dec-${c.candidate_id}`}
                                        className="rounded-md border border-zinc-300 px-2.5 py-1 text-xs text-zinc-500 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                                      >
                                        Clear
                                      </button>
                                    )}
                                  </div>
                                </div>
                              </Card>
                            )}

                            <CandidateNoteCard
                              roleId={roleId} candidateId={c.candidate_id} note={c.note}
                              busy={busy === `note-${c.candidate_id}`}
                              run={run}
                            />

                            {crossJob[c.candidate_id] === "loading" && (
                              <p className="text-xs text-zinc-400">Checking other jobs…</p>
                            )}
                            {crossJob[c.candidate_id] && crossJob[c.candidate_id] !== "loading" && (() => {
                              const detail = crossJob[c.candidate_id] as CanonicalCandidate;
                              const others = detail.evaluations.filter((e) => e.role_id !== roleId);
                              if (others.length === 0) return null;
                              return (
                                <Card title={`Seen before — ${others.length} other job${others.length === 1 ? "" : "s"}`}>
                                  <ul className="flex flex-col gap-1.5 text-sm">
                                    {others.map((e) => (
                                      <li key={e.candidate_evaluation_id} className="flex items-center justify-between gap-2">
                                        <span>{e.job_title}</span>
                                        <span className="flex items-center gap-2">
                                          {e.tier && <StatusChip label={`Tier ${e.tier}`} variant={tierVariant(e.tier)} />}
                                          {e.recruiter_decision && (
                                            <span className="text-xs italic text-zinc-500">&ldquo;{e.recruiter_decision}&rdquo;</span>
                                          )}
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                </Card>
                              );
                            })()}

                            <Card title="Evidence">
                              {c.achievements.length === 0 ? <p className="text-sm text-zinc-400">—</p> : (
                                <ul className="space-y-1 text-sm">
                                  {c.achievements.map((a, i) => (
                                    <li key={i}>
                                      <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                                        a.evidence_level === "VERIFIED" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
                                        : a.evidence_level === "INFERRED" ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400"
                                        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                                      }`}>{a.evidence_level}</span>
                                      {a.fact}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </Card>

                            {job.state.screening?.[c.candidate_id] && (
                              <Card title="Screening — must-ask">
                                <List items={job.state.screening[c.candidate_id].must_ask} />
                              </Card>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Side-by-side candidate comparison (Phase 8) — reuses whatever's already
// on the page (listCandidates' response), no new backend route needed.
// Private recruiter notes (Phase 10) — deliberately separate from the
// model's evidence-labeled fields and from the structured
// recruiter_decision above; this is just a place to jot an impression.
function CandidateNoteCard({
  roleId, candidateId, note, busy, run,
}: {
  roleId: string; candidateId: string; note: string; busy: boolean;
  run: (name: string, action: () => Promise<unknown>) => void;
}) {
  const [draft, setDraft] = useState(note);
  const [prevNote, setPrevNote] = useState(note);

  if (note !== prevNote) {
    setPrevNote(note);
    setDraft(note);
  }

  const dirty = draft !== note;

  return (
    <Card title="Notes (private)">
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={2}
        placeholder="Your own impressions — nothing here is read by the AI or shown outside this workspace."
        className="w-full rounded-md border border-zinc-300 p-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
      />
      {dirty && (
        <button
          onClick={() => run(`note-${candidateId}`, () => setCandidateNote(roleId, candidateId, draft))}
          disabled={busy}
          className="mt-2 rounded-md bg-indigo-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save note"}
        </button>
      )}
    </Card>
  );
}

function CandidateComparison({ candidates, onClose }: { candidates: Candidate[]; onClose: () => void }) {
  const rows: [string, (c: Candidate) => React.ReactNode][] = [
    ["Role & company", (c) => `${c.current_title} @ ${c.current_company}`],
    ["Location", (c) => c.location || "—"],
    ["Current CTC", (c) => c.current_ctc || "—"],
    ["Expected CTC", (c) => c.expected_ctc || "—"],
    ["Notice period", (c) => c.notice_period || "—"],
    [
      "Tier & fit",
      (c) =>
        c.prioritization ? (
          <div className="flex items-center gap-1.5">
            <StatusChip label={c.prioritization.tier} variant={tierVariant(c.prioritization.tier)} />
            <StatusChip
              label={`${c.prioritization.fit_rating} · ${c.prioritization.fit_score}`}
              variant={rygVariant(c.prioritization.fit_rating)}
            />
          </div>
        ) : (
          "—"
        ),
    ],
    ["Why they fit", (c) => <List items={c.prioritization?.why_they_fit} />],
    ["Weaknesses", (c) => <List items={c.prioritization?.weaknesses} />],
    ["What's unknown", (c) => <List items={c.prioritization?.what_is_unknown} />],
    ["To validate", (c) => <List items={c.prioritization?.what_to_validate} />],
    ["Decision", (c) => c.prioritization?.recruiter_decision || "—"],
    ["Concerns", (c) => <List items={c.concerns} />],
  ];

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-500">Comparing {candidates.length} candidates</h3>
        <button onClick={onClose} className="text-xs text-indigo-700 hover:underline dark:text-indigo-400">Close</button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] table-fixed border-collapse text-left text-sm">
          <thead>
            <tr>
              <th className="w-32 px-2 py-1.5 align-top text-xs font-medium text-zinc-500"></th>
              {candidates.map((c) => (
                <th key={c.candidate_id} className="px-2 py-1.5 align-top font-medium">{c.name}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {rows.map(([label, render]) => (
              <tr key={label}>
                <td className="px-2 py-2 align-top text-xs font-medium text-zinc-500">{label}</td>
                {candidates.map((c) => (
                  <td key={c.candidate_id} className="px-2 py-2 align-top">{render(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Outreach ───────────────────────────────────────────────────────────

// Outreach → email handoff (Phase 8): a mailto: link, never a send —
// candidates don't have a captured email address (evidence discipline:
// this product doesn't fabricate contact info it was never given), so
// the recipient is left for the recruiter to fill in themselves. Still
// real value: the subject and body arrive pre-filled in their own email
// client, nothing here pretends to have sent anything.
function mailtoHref(candidateName: string, jobTitle: string, body: string): string {
  const subject = `${candidateName} — ${jobTitle}`;
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function OutreachTab({
  roleId, job, refresh, dataVersion,
}: { roleId: string; job: JobDetail; refresh: () => void; dataVersion: number }) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);

  const load = useCallback(() => {
    listCandidates(roleId)
      .then(setCandidates)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load candidates."));
  }, [roleId]);

  useEffect(load, [load, dataVersion]);

  async function bulkGenerate() {
    const targets = candidates.filter((c) => !job.state.outreach?.[c.candidate_id]);
    if (targets.length === 0) return;
    setError(null);
    setBulkProgress({ done: 0, total: targets.length });
    let done = 0;
    const results = await Promise.allSettled(
      targets.map((c) =>
        outreachCandidate(roleId, c.candidate_id).then(() => {
          done += 1;
          setBulkProgress({ done, total: targets.length });
        })
      )
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed > 0) setError(`${failed} of ${targets.length} drafts failed to generate.`);
    setBulkProgress(null);
    load();
    refresh();
  }

  async function generate(candidateId: string) {
    setBusy(candidateId);
    setError(null);
    try {
      await outreachCandidate(roleId, candidateId);
      load();
      refresh(); // job.state.outreach lives on the parent job object, not the candidates list
      setExpanded(candidateId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not generate outreach.");
    } finally {
      setBusy(null);
    }
  }

  async function markSent(candidateId: string) {
    setBusy(candidateId);
    setError(null);
    try {
      await markOutreachSent(roleId, candidateId);
      refresh(); // job.state.outreach_log + job.state.funnel both live on the parent job object
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record outreach as sent.");
    } finally {
      setBusy(null);
    }
  }

  if (candidates.length === 0) {
    return <p className="text-sm text-zinc-500">No candidates yet — add some in the Candidates tab.</p>;
  }

  const undrafted = candidates.filter((c) => !job.state.outreach?.[c.candidate_id]);

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400">
        Drafts only — sending isn&apos;t built yet (no email/LinkedIn integration). Copy the draft you want to
        use, then mark it sent here once you&apos;ve reached out yourself — that just records your own action
        and moves the pipeline card to Contacted, it doesn&apos;t send anything.
      </div>
      {undrafted.length > 0 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-zinc-500">
            {bulkProgress ? `Drafting ${bulkProgress.done}/${bulkProgress.total}…` : null}
          </p>
          <button
            onClick={bulkGenerate}
            disabled={bulkProgress !== null}
            className="self-end rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Draft outreach for all ({undrafted.length})
          </button>
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}
      {candidates.map((c) => {
        const draft = job.state.outreach?.[c.candidate_id];
        const sentAt: string | undefined = job.state.outreach_log?.[c.candidate_id]?.sent_at;
        const isOpen = expanded === c.candidate_id;
        return (
          <Card key={c.candidate_id}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-medium">{c.name}</p>
                <p className="text-xs text-zinc-500">{c.current_title} @ {c.current_company}</p>
              </div>
              <div className="flex items-center gap-2">
                <StatusChip
                  label={sentAt ? "Sent" : draft ? "Drafted" : "No draft"}
                  variant={sentAt ? "ok" : draft ? "running" : "pending"}
                />
                <button
                  onClick={() => generate(c.candidate_id)}
                  disabled={busy === c.candidate_id}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                >
                  {busy === c.candidate_id ? "Working…" : draft ? "Regenerate" : "Generate outreach"}
                </button>
                {draft?.email && (
                  <a
                    href={mailtoHref(c.name, job.title, draft.email)}
                    className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    title="Opens your email client with the draft pre-filled — you fill in the recipient and hit send yourself"
                  >
                    Open in email
                  </a>
                )}
                {draft && !sentAt && (
                  <button
                    onClick={() => markSent(c.candidate_id)}
                    disabled={busy === c.candidate_id}
                    className="rounded-md bg-indigo-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
                  >
                    Mark as sent
                  </button>
                )}
                {draft && (
                  <button
                    onClick={() => setExpanded(isOpen ? null : c.candidate_id)}
                    className="text-xs text-indigo-700 hover:underline dark:text-indigo-400"
                  >
                    {isOpen ? "Hide" : "View"}
                  </button>
                )}
              </div>
            </div>
            {sentAt && (
              <p className="mt-1 text-xs text-zinc-500">Marked sent {new Date(sentAt).toLocaleString()}</p>
            )}
            {isOpen && draft && (
              <div className="mt-3 flex flex-col gap-3 border-t border-zinc-200 pt-3 dark:border-zinc-800">
                <OutreachBlock label="LinkedIn connection note" value={draft.linkedin_connection_note} />
                <OutreachBlock label="InMail" value={draft.linkedin_inmail} />
                <OutreachBlock label="Email" value={draft.email} />
                <OutreachBlock label="Follow-up 1" value={draft.follow_up_1} />
                <OutreachBlock label="Follow-up 2" value={draft.follow_up_2} />
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function OutreachBlock({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div>
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="whitespace-pre-wrap text-sm">{value}</p>
    </div>
  );
}

// ── Pipeline (visual board) ───────────────────────────────────────────

type StageHistoryEntry = { stage: string; at: string; note?: string; scheduled_at?: string | null };

function upcomingSchedule(history: StageHistoryEntry[] | undefined): string | null {
  const scheduledAt = history?.[history.length - 1]?.scheduled_at;
  if (!scheduledAt) return null;
  return new Date(scheduledAt).getTime() > Date.now() ? scheduledAt : null;
}

function daysInStage(history: StageHistoryEntry[] | undefined): number | null {
  if (!history || history.length === 0) return null;
  const lastAt = new Date(history[history.length - 1].at).getTime();
  return Math.floor((Date.now() - lastAt) / (1000 * 60 * 60 * 24));
}

function PipelineTab({
  roleId, job, refresh, dataVersion,
}: { roleId: string; job: JobDetail; refresh: () => void; dataVersion: number }) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [scheduleDrafts, setScheduleDrafts] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    listCandidates(roleId).then(setCandidates).catch(() => {});
  }, [roleId]);

  useEffect(load, [load, dataVersion]);

  async function moveStage(candidateId: string, stage: string) {
    setBusy(candidateId);
    try {
      await updateFunnelStage(
        roleId, candidateId, stage, noteDrafts[candidateId] ?? "", scheduleDrafts[candidateId] || undefined
      );
      setNoteDrafts((prev) => ({ ...prev, [candidateId]: "" }));
      setScheduleDrafts((prev) => ({ ...prev, [candidateId]: "" }));
      load();
      refresh();
    } finally {
      setBusy(null);
    }
  }

  const funnel: Json = job.state.funnel ?? {};

  if (candidates.length === 0) {
    return <p className="text-sm text-zinc-500">No candidates yet — add some in the Candidates tab.</p>;
  }

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex gap-3" style={{ minWidth: `${FUNNEL_STAGES.length * 176}px` }}>
        {FUNNEL_STAGES.map((stage, stageIdx) => {
          const inStage = candidates.filter(
            (c) => (funnel[c.candidate_id]?.current_stage ?? "IDENTIFIED") === stage
          );
          return (
            <div
              key={stage}
              className="flex w-44 shrink-0 flex-col gap-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2 dark:border-zinc-800 dark:bg-zinc-900/50"
            >
              <div className="flex items-center justify-between px-1">
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                  {stage.replace(/_/g, " ")}
                </h3>
                <span className="text-xs tabular-nums text-zinc-400">{inStage.length}</span>
              </div>
              <div className="flex flex-col gap-1.5">
                {inStage.map((c) => {
                  const history: StageHistoryEntry[] = funnel[c.candidate_id]?.stage_history ?? [];
                  const days = daysInStage(history);
                  const isOpen = expanded === c.candidate_id;
                  const scheduled = upcomingSchedule(history);
                  return (
                    <div
                      key={c.candidate_id}
                      className="rounded-md border border-zinc-200 bg-surface px-2 py-1.5 text-xs shadow-[var(--shadow-sm)] dark:border-zinc-700"
                    >
                      <button
                        onClick={() => setExpanded(isOpen ? null : c.candidate_id)}
                        className="block w-full truncate text-left font-medium hover:underline"
                        title={c.name}
                      >
                        {c.name}
                      </button>
                      {days !== null && (
                        <p className="mt-0.5 text-[10px] text-zinc-400">
                          {days === 0 ? "in stage <1d" : `${days}d in stage`}
                        </p>
                      )}
                      {scheduled && (
                        <p className="mt-0.5 text-[10px] font-medium text-indigo-700 dark:text-indigo-400">
                          Scheduled: {new Date(scheduled).toLocaleString(undefined, {
                            month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                          })}
                        </p>
                      )}
                      <div className="mt-1 flex justify-between">
                        <button
                          onClick={() => moveStage(c.candidate_id, FUNNEL_STAGES[stageIdx - 1])}
                          disabled={stageIdx === 0 || busy === c.candidate_id}
                          className="text-zinc-400 hover:text-zinc-800 disabled:opacity-30 dark:hover:text-zinc-200"
                          aria-label={`Move ${c.name} to previous stage`}
                        >
                          ‹ back
                        </button>
                        <button
                          onClick={() => moveStage(c.candidate_id, FUNNEL_STAGES[stageIdx + 1])}
                          disabled={stageIdx === FUNNEL_STAGES.length - 1 || busy === c.candidate_id}
                          className="text-zinc-400 hover:text-zinc-800 disabled:opacity-30 dark:hover:text-zinc-200"
                          aria-label={`Move ${c.name} to next stage`}
                        >
                          next ›
                        </button>
                      </div>
                      {isOpen && (
                        <div className="mt-2 flex flex-col gap-2 border-t border-zinc-200 pt-2 dark:border-zinc-800">
                          <div className="flex flex-col gap-1">
                            {history.length === 0 ? (
                              <p className="text-[10px] text-zinc-400">No stage history yet.</p>
                            ) : (
                              [...history].reverse().map((h, i) => (
                                <div key={i} className="text-[10px] text-zinc-500">
                                  <span className="font-medium text-zinc-700 dark:text-zinc-300">
                                    {h.stage.replace(/_/g, " ")}
                                  </span>{" "}
                                  · {new Date(h.at).toLocaleString()}
                                  {h.note && <p className="italic text-zinc-400">&ldquo;{h.note}&rdquo;</p>}
                                  {h.scheduled_at && (
                                    <p className="text-indigo-700 dark:text-indigo-400">
                                      scheduled for {new Date(h.scheduled_at).toLocaleString()}
                                    </p>
                                  )}
                                </div>
                              ))
                            )}
                          </div>
                          <label className="flex flex-col gap-0.5 text-[10px] text-zinc-500">
                            Schedule an interview for the next move (optional)
                            <input
                              type="datetime-local"
                              value={scheduleDrafts[c.candidate_id] ?? ""}
                              onChange={(e) =>
                                setScheduleDrafts((prev) => ({ ...prev, [c.candidate_id]: e.target.value }))
                              }
                              className="rounded border border-zinc-300 px-1.5 py-1 text-[10px] outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
                            />
                          </label>
                          <input
                            value={noteDrafts[c.candidate_id] ?? ""}
                            onChange={(e) =>
                              setNoteDrafts((prev) => ({ ...prev, [c.candidate_id]: e.target.value }))
                            }
                            placeholder="Note for next move (optional)"
                            className="rounded border border-zinc-300 px-1.5 py-1 text-[10px] outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Analytics ──────────────────────────────────────────────────────────

function AnalyticsTab({ roleId, dataVersion }: { roleId: string; dataVersion: number }) {
  const [report, setReport] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getFunnelReport(roleId)
      .then(setReport)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load analytics."));
  }, [roleId, dataVersion]);

  if (error) {
    return <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">{error}</div>;
  }
  if (!report) return <p className="text-sm text-zinc-500">Loading…</p>;

  const rates: [string, number | null][] = [
    ["Contact rate", report.contact_rate], ["Response rate", report.response_rate],
    ["Positive response", report.positive_response_rate], ["Screen conversion", report.screen_conversion],
    ["HM conversion", report.hm_conversion], ["Final conversion", report.final_conversion],
    ["Offer rate", report.offer_rate], ["Offer acceptance", report.offer_acceptance_rate],
    ["Joining rate", report.joining_rate],
  ];

  return (
    <div className="flex flex-col gap-4">
      <Card title="Funnel counts">
        <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {Object.entries(report.counts_by_stage as Record<string, number>).map(([stage, count]) => (
            <div key={stage} className="flex justify-between">
              <span className="text-zinc-500">{stage}</span>
              <span className="tabular-nums">{count}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Conversion rates">
        <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {rates.map(([label, value]) => (
            <div key={label} className="flex justify-between">
              <span className="text-zinc-500">{label}</span>
              <span className="tabular-nums">{value === null ? "—" : `${Math.round(value * 100)}%`}</span>
            </div>
          ))}
        </div>
      </Card>

      {report.biggest_leakage_stage && (
        <Card title="Insight (computed from funnel data — not a separate AI call)">
          <p className="text-sm text-amber-700 dark:text-amber-400">
            Biggest leakage: {report.biggest_leakage_stage} — {report.recommended_intervention}
          </p>
        </Card>
      )}

      <IntegrationsCard roleId={roleId} />
    </div>
  );
}

// Outbound webhook (Phase 8) — a real HTTP POST the recruiter configures
// for their own job, same pattern as a Slack incoming webhook. Fires
// automatically on a "pursue" decision (api.py's
// _maybe_fire_decision_webhook); the test button here fires it on
// demand so a recruiter can verify the URL works before relying on it.
function IntegrationsCard({ roleId }: { roleId: string }) {
  const [webhookUrl, setWebhookUrl] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Guards against the mount-time fetch below resolving after the
  // recruiter has already started typing — without this, a slow GET
  // would silently stomp their in-progress edit back to the old value.
  const editedRef = useRef(false);

  useEffect(() => {
    getWebhookConfig(roleId)
      .then((c) => {
        if (!editedRef.current) setWebhookUrl(c.webhook_url);
      })
      .catch(() => {});
  }, [roleId]);

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await setWebhookConfig(roleId, webhookUrl.trim());
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the webhook URL.");
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError(null);
    setTestResult(null);
    try {
      setTestResult(await testWebhook(roleId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not send the test payload.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Integrations">
      <p className="mb-2 text-xs text-zinc-500">
        Configure a webhook URL (e.g. an ATS intake endpoint, a Zapier catch hook, a Slack incoming webhook) and a
        &ldquo;pursue&rdquo; decision on any candidate in this job will POST a JSON payload to it automatically.
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          value={webhookUrl}
          onChange={(e) => { editedRef.current = true; setWebhookUrl(e.target.value); setSaved(false); }}
          placeholder="https://example.com/webhook"
          className="flex-1 min-w-48 rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
        />
        <button
          onClick={save}
          disabled={busy}
          className="rounded-md bg-indigo-700 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
        >
          {busy ? "Working…" : "Save"}
        </button>
        <button
          onClick={test}
          disabled={busy || !webhookUrl.trim()}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Send test payload
        </button>
      </div>
      {saved && <p className="mt-2 text-xs text-indigo-700 dark:text-indigo-400">Saved.</p>}
      {testResult && (
        <p className={`mt-2 text-xs ${testResult.ok ? "text-indigo-700 dark:text-indigo-400" : "text-red-600 dark:text-red-400"}`}>
          {testResult.detail}
        </p>
      )}
      {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </Card>
  );
}
