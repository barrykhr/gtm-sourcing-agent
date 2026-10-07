"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  RequirementCategory,
  RequirementPriority,
  RoleAmbiguity,
  RoleICP,
  RoleRequirement,
  RoleVersion,
  createRoleRequirement,
  extractRoleIntelligence,
  getRoleIcp,
  listRoleAmbiguities,
  listRoleRequirements,
  getRoleIntelligenceHistory,
  removeRoleRequirement,
  resolveRoleAmbiguity,
  updateRoleRequirement,
} from "@/lib/api";

/**
 * Feature 01's Role Intelligence view (TALYN_V2_ARCHITECTURE.md §3/§4):
 * a role's requirements/ICP/ambiguities as individually editable,
 * evidence-labeled records — the replacement for letting an opaque
 * AI-generated hiring-profile summary be the only thing a recruiter
 * sees. Every edit here is the recruiter's own explicit action (typing
 * in a field, clicking Save/Delete), so it applies directly — no
 * confirm step. Only a change proposed through the AI Copilot's chat
 * (ambiguous natural language) goes through propose/confirm, rendered
 * in CopilotPanel, not here.
 */

const CATEGORIES: RequirementCategory[] = ["skill", "experience", "location", "comp", "other"];

const EVIDENCE_STYLES: Record<string, string> = {
  CONFIRMED: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-400",
  INFERRED: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-400",
  NOT_STATED: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  CONFLICTING: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-400",
};

function EvidenceBadge({ level }: { level: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${EVIDENCE_STYLES[level] ?? EVIDENCE_STYLES.NOT_STATED}`}>
      {level.replace("_", " ")}
    </span>
  );
}

function Panel({ title, children, actions }: { title: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] dark:border-zinc-800">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-500">{title}</h3>
        {actions}
      </div>
      {children}
    </div>
  );
}

export function RoleIntelligencePanel({ roleId }: { roleId: string }) {
  const [requirements, setRequirements] = useState<RoleRequirement[] | null>(null);
  const [icp, setIcp] = useState<RoleICP | null>(null);
  const [ambiguities, setAmbiguities] = useState<RoleAmbiguity[] | null>(null);
  const [history, setHistory] = useState<RoleVersion[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [jdText, setJdText] = useState("");
  const [extracting, setExtracting] = useState(false);

  const load = useCallback(() => {
    Promise.all([listRoleRequirements(roleId), getRoleIcp(roleId), listRoleAmbiguities(roleId)])
      .then(([reqs, icpResult, ambs]) => {
        setRequirements(reqs);
        setIcp(icpResult);
        setAmbiguities(ambs);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load role intelligence."));
  }, [roleId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (showHistory) {
      getRoleIntelligenceHistory(roleId).then(setHistory).catch(() => setHistory([]));
    }
  }, [showHistory, roleId]);

  async function extract() {
    if (!jdText.trim()) return;
    setExtracting(true);
    setError(null);
    try {
      await extractRoleIntelligence(roleId, jdText);
      setJdText("");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Extraction failed.");
    } finally {
      setExtracting(false);
    }
  }

  async function addRequirement(category: RequirementCategory, value: string, priority: RequirementPriority) {
    try {
      await createRoleRequirement(roleId, { category, value, priority, evidence_level: "NOT_STATED" });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add that requirement.");
    }
  }

  async function changePriority(req: RoleRequirement) {
    try {
      await updateRoleRequirement(roleId, req.id, {
        priority: req.priority === "must_have" ? "nice_to_have" : "must_have",
      });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update that requirement.");
    }
  }

  async function removeRequirement(req: RoleRequirement) {
    try {
      await removeRoleRequirement(roleId, req.id);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not remove that requirement.");
    }
  }

  async function resolveAmbiguity(amb: RoleAmbiguity, note: string) {
    if (!note.trim()) return;
    try {
      await resolveRoleAmbiguity(roleId, amb.id, note);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not resolve that ambiguity.");
    }
  }

  if (requirements === null) {
    return <p className="text-sm text-zinc-400">Loading role intelligence…</p>;
  }

  const hasAnything = requirements.length > 0 || icp !== null;

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      <Panel title={hasAnything ? "Extract more from another JD" : "Extract role intelligence from a JD"}>
        <div className="flex flex-col gap-3">
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={hasAnything ? 4 : 10}
            placeholder="Paste the job description here…"
            className="w-full rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-signal-600 dark:border-zinc-700"
          />
          <button
            onClick={extract}
            disabled={extracting || !jdText.trim()}
            className="self-start rounded-md bg-signal-700 px-4 py-2 text-sm font-medium text-white hover:bg-signal-800 disabled:opacity-50"
          >
            {extracting ? "Extracting…" : "Extract requirements"}
          </button>
          <p className="text-xs text-zinc-500">
            Every requirement gets its own evidence label — CONFIRMED (a real quote from the JD), INFERRED, NOT
            STATED, or CONFLICTING — nothing is stated as fact unless the JD actually says it.
          </p>
        </div>
      </Panel>

      <Panel title="Requirements" actions={<AddRequirementForm onAdd={addRequirement} />}>
        {requirements.length === 0 ? (
          <p className="text-sm text-zinc-400">No requirements yet — extract from a JD above, or add one.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {(["must_have", "nice_to_have"] as RequirementPriority[]).map((priority) => {
              const rows = requirements.filter((r) => r.priority === priority);
              if (rows.length === 0) return null;
              return (
                <div key={priority} className="flex flex-col gap-1.5">
                  <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                    {priority === "must_have" ? "Must have" : "Nice to have"}
                  </p>
                  {rows.map((req) => (
                    <div
                      key={req.id}
                      className="flex items-start justify-between gap-3 rounded-md border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800"
                    >
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                          <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] uppercase text-zinc-500 dark:bg-zinc-800">
                            {req.category}
                          </span>
                          <span>{req.value}</span>
                          <EvidenceBadge level={req.evidence_level} />
                        </div>
                        {req.source_span && (
                          <p className="text-xs italic text-zinc-400">&ldquo;{req.source_span}&rdquo;</p>
                        )}
                      </div>
                      <div className="flex shrink-0 gap-2">
                        <button
                          onClick={() => changePriority(req)}
                          className="rounded-md border border-zinc-300 px-2 py-1 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                        >
                          {req.priority === "must_have" ? "Make nice-to-have" : "Make must-have"}
                        </button>
                        <button
                          onClick={() => removeRequirement(req)}
                          className="rounded-md border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      {icp && Object.keys(icp.fields).length > 0 && (
        <Panel title="Ideal Candidate Profile">
          <div className="flex flex-col gap-2">
            {Object.entries(icp.fields).map(([key, field]) => (
              <div key={key} className="flex items-start justify-between gap-3 rounded-md border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800">
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                    {key.replace(/_/g, " ")}
                  </span>
                  <span>{field.value || "—"}</span>
                </div>
                <EvidenceBadge level={field.evidence_level} />
              </div>
            ))}
          </div>
        </Panel>
      )}

      {ambiguities && ambiguities.length > 0 && (
        <Panel title="Ambiguities">
          <div className="flex flex-col gap-2">
            {ambiguities.map((amb) => (
              <AmbiguityRow key={amb.id} ambiguity={amb} onResolve={resolveAmbiguity} />
            ))}
          </div>
        </Panel>
      )}

      <button
        onClick={() => setShowHistory((v) => !v)}
        className="self-start text-xs font-medium text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
      >
        {showHistory ? "Hide change history" : "Show change history"}
      </button>
      {showHistory && (
        <Panel title="Change history">
          {history.length === 0 ? (
            <p className="text-sm text-zinc-400">No changes yet.</p>
          ) : (
            <ul className="flex flex-col gap-1.5 text-xs text-zinc-500">
              {history.map((v) => (
                <li key={v.id}>
                  <span className="font-medium text-zinc-700 dark:text-zinc-300">
                    {v.action} {v.entity_type}
                  </span>{" "}
                  by {v.changed_by} — {new Date(v.changed_at).toLocaleString()}
                  {v.reason && <span> ({v.reason})</span>}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}
    </div>
  );
}

function AddRequirementForm({
  onAdd,
}: { onAdd: (category: RequirementCategory, value: string, priority: RequirementPriority) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<RequirementCategory>("skill");
  const [value, setValue] = useState("");
  const [priority, setPriority] = useState<RequirementPriority>("must_have");
  const [saving, setSaving] = useState(false);

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="text-xs font-medium text-signal-700 hover:text-signal-800 dark:text-signal-400">
        + Add requirement
      </button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        aria-label="Requirement category"
        value={category}
        onChange={(e) => setCategory(e.target.value as RequirementCategory)}
        className="rounded-md border border-zinc-300 bg-transparent px-2 py-1 text-xs dark:border-zinc-700"
      >
        {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <select
        aria-label="Requirement priority"
        value={priority}
        onChange={(e) => setPriority(e.target.value as RequirementPriority)}
        className="rounded-md border border-zinc-300 bg-transparent px-2 py-1 text-xs dark:border-zinc-700"
      >
        <option value="must_have">must have</option>
        <option value="nice_to_have">nice to have</option>
      </select>
      <input
        aria-label="Requirement text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="e.g. Salesforce CPQ"
        className="rounded-md border border-zinc-300 bg-transparent px-2 py-1 text-xs outline-none focus:border-signal-600 dark:border-zinc-700"
      />
      <button
        disabled={saving || !value.trim()}
        onClick={async () => {
          setSaving(true);
          await onAdd(category, value.trim(), priority);
          setValue("");
          setOpen(false);
          setSaving(false);
        }}
        className="rounded-md bg-signal-700 px-2 py-1 text-xs font-medium text-white hover:bg-signal-800 disabled:opacity-50"
      >
        Save
      </button>
      <button onClick={() => setOpen(false)} className="text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        Cancel
      </button>
    </div>
  );
}

function AmbiguityRow({
  ambiguity, onResolve,
}: { ambiguity: RoleAmbiguity; onResolve: (amb: RoleAmbiguity, note: string) => Promise<void> }) {
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);

  return (
    <div className="flex flex-col gap-2 rounded-md border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800">
      <div className="flex items-center justify-between">
        <span>{ambiguity.description}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
            ambiguity.status === "open"
              ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-400"
              : "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-400"
          }`}
        >
          {ambiguity.status}
        </span>
      </div>
      {ambiguity.candidate_resolutions.length > 0 && (
        <ul className="list-disc pl-4 text-xs text-zinc-500">
          {ambiguity.candidate_resolutions.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      {ambiguity.status === "open" ? (
        <div className="flex gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="How is this resolved?"
            className="flex-1 rounded-md border border-zinc-300 bg-transparent px-2 py-1 text-xs outline-none focus:border-signal-600 dark:border-zinc-700"
          />
          <button
            disabled={resolving || !note.trim()}
            onClick={async () => {
              setResolving(true);
              await onResolve(ambiguity, note.trim());
              setResolving(false);
            }}
            className="rounded-md bg-signal-700 px-2 py-1 text-xs font-medium text-white hover:bg-signal-800 disabled:opacity-50"
          >
            Resolve
          </button>
        </div>
      ) : (
        <p className="text-xs text-zinc-500">{ambiguity.resolution_note}</p>
      )}
    </div>
  );
}
