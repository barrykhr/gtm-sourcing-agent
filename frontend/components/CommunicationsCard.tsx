"use client";

import { useEffect, useState } from "react";
import {
  CommunicationChannel,
  ConversationHistory,
  getCommunications,
  logCommunication,
  pollTaskUntilDone,
  setCandidateContact,
} from "@/lib/api";
import { Card } from "@/components/ui/Card";

// Confirm-before-handoff popup for the WhatsApp/call demo below — a
// small local dialog, same overlay pattern as CommandPalette.tsx.
function ConfirmDialog({
  title, body, confirmLabel, onConfirm, onCancel, children,
}: {
  title: string; body: string; confirmLabel: string; onConfirm: () => void; onCancel: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/40 px-4 backdrop-blur-[1px]"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-xl border border-zinc-200 bg-surface p-5 shadow-[var(--shadow-lg)] dark:border-zinc-800"
      >
        <h3 className="font-display text-lg">{title}</h3>
        <p className="mt-1 text-sm text-zinc-500">{body}</p>
        {children}
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="rounded-md bg-indigo-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-800"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

const CHANNEL_LABEL: Record<CommunicationChannel, string> = {
  email: "Email", whatsapp: "WhatsApp", call: "Call", note: "Note",
};

// Conversation History (email/WhatsApp/call demo): every logged
// touchpoint with this candidate in one place, plus a rolling AI
// summary that regenerates after each new entry. WhatsApp/call
// "sending" here means the wa.me/tel: device handoff the buttons below
// open — genuinely functional (same tier as the Outreach tab's mailto:
// handoff), not a stub — but there is no messaging or telephony backend
// behind it, so logging happens on confirm, not on delivery. See
// api.py's route docstring for the same framing.
//
// Self-contained (own contact/history/busy state) rather than threaded
// through a parent's action-runner, so it drops into any page that has
// a role_id + candidate_evaluation_id — the per-job workspace and the
// global cross-job candidate page both use this same component.
export function CommunicationsCard({
  roleId, candidateId, name, initialPhone, initialEmail, onContactSaved,
}: {
  roleId: string; candidateId: string; name: string; initialPhone: string; initialEmail: string;
  onContactSaved?: (phone: string, email: string) => void;
}) {
  const [phone, setPhone] = useState(initialPhone);
  const [email, setEmail] = useState(initialEmail);
  const [phoneDraft, setPhoneDraft] = useState(initialPhone);
  const [emailDraft, setEmailDraft] = useState(initialEmail);
  const [savingContact, setSavingContact] = useState(false);
  const contactDirty = phoneDraft !== phone || emailDraft !== email;

  const [history, setHistory] = useState<ConversationHistory | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loggingEntry, setLoggingEntry] = useState(false);

  function loadHistory() {
    getCommunications(roleId, candidateId).then(setHistory).catch(() => setLoadError(true));
  }
  useEffect(loadHistory, [roleId, candidateId]);

  const [confirmChannel, setConfirmChannel] = useState<"whatsapp" | "call" | null>(null);
  const [waMessage, setWaMessage] = useState(
    `Hi ${name.split(" ")[0] || ""}, reaching out about an opportunity we think could be a strong fit — do you have a few minutes to connect?`,
  );
  const [manualChannel, setManualChannel] = useState<CommunicationChannel>("email");
  const [manualContent, setManualContent] = useState("");
  const [manualTranscript, setManualTranscript] = useState("");

  async function saveContact() {
    setSavingContact(true);
    try {
      await setCandidateContact(roleId, candidateId, phoneDraft, emailDraft);
      setPhone(phoneDraft);
      setEmail(emailDraft);
      onContactSaved?.(phoneDraft, emailDraft);
    } finally {
      setSavingContact(false);
    }
  }

  async function logAndRefresh(channel: CommunicationChannel, content: string, contactUsed = "", transcript?: string) {
    setLoggingEntry(true);
    setRefreshing(true);
    try {
      const { summary_task, intelligence_task } = await logCommunication(roleId, candidateId, {
        channel, direction: "outbound", content, contact_used: contactUsed, transcript,
      });
      loadHistory(); // shows the new entry immediately, summary/intelligence not yet refreshed
      await Promise.all([
        pollTaskUntilDone(roleId, summary_task.task_id),
        pollTaskUntilDone(roleId, intelligence_task.task_id),
      ]);
      loadHistory(); // now picks up the regenerated summary + intelligence
    } finally {
      setLoggingEntry(false);
      setRefreshing(false);
    }
  }

  function confirmWhatsApp() {
    const digits = phone.replace(/[^\d+]/g, "");
    window.open(`https://wa.me/${digits.replace(/^\+/, "")}?text=${encodeURIComponent(waMessage)}`, "_blank", "noopener");
    setConfirmChannel(null);
    logAndRefresh("whatsapp", waMessage, phone);
  }

  function confirmCall() {
    window.location.href = `tel:${phone}`;
    setConfirmChannel(null);
    logAndRefresh("call", `Call initiated to ${phone} (device handoff — no telephony backend, so connection isn't confirmed here).`, phone);
  }

  function saveManualEntry() {
    if (!manualContent.trim()) return;
    const content = manualContent.trim();
    const transcript = manualTranscript.trim() || undefined;
    setManualContent("");
    setManualTranscript("");
    logAndRefresh(manualChannel, content, "", transcript);
  }

  return (
    <Card title="Conversation history">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="text-xs font-medium text-zinc-500">Phone</label>
            <input
              value={phoneDraft}
              onChange={(e) => setPhoneDraft(e.target.value)}
              placeholder="+91XXXXXXXXXX"
              className="block w-40 rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-zinc-500">Email</label>
            <input
              value={emailDraft}
              onChange={(e) => setEmailDraft(e.target.value)}
              placeholder="name@example.com"
              className="block w-48 rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
            />
          </div>
          {contactDirty && (
            <button
              onClick={saveContact}
              disabled={savingContact}
              className="rounded-md bg-indigo-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
            >
              {savingContact ? "Saving…" : "Save contact"}
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setConfirmChannel("whatsapp")}
            disabled={!phone}
            title={phone ? "" : "Add a phone number first"}
            className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400"
          >
            Message on WhatsApp
          </button>
          <button
            onClick={() => setConfirmChannel("call")}
            disabled={!phone}
            title={phone ? "" : "Add a phone number first"}
            className="rounded-md border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-800 hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-300"
          >
            Call
          </button>
        </div>
        <p className="-mt-2 text-[11px] text-zinc-400">
          Both open your own device&apos;s WhatsApp/dialer via a standard wa.me/tel: link — there&apos;s no messaging or
          telephony backend here, so this confirms intent, not delivery or connection.
        </p>

        {confirmChannel === "whatsapp" && (
          <ConfirmDialog
            title="Message on WhatsApp?"
            body={`This opens WhatsApp to message ${phone}.`}
            confirmLabel="Open WhatsApp"
            onConfirm={confirmWhatsApp}
            onCancel={() => setConfirmChannel(null)}
          >
            <textarea
              value={waMessage}
              onChange={(e) => setWaMessage(e.target.value)}
              rows={3}
              className="mt-3 w-full rounded-md border border-zinc-300 p-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
            />
          </ConfirmDialog>
        )}
        {confirmChannel === "call" && (
          <ConfirmDialog
            title="Call this number?"
            body={`This opens your device's dialer for ${phone}. Cancel if you'd rather not.`}
            confirmLabel={`Call ${phone}`}
            onConfirm={confirmCall}
            onCancel={() => setConfirmChannel(null)}
          />
        )}

        <div className="rounded-md border border-indigo-200 bg-indigo-50/60 p-3 dark:border-indigo-900 dark:bg-indigo-950/40">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-indigo-800 dark:text-indigo-300">Conversation summary</p>
            {refreshing && <span className="text-[11px] text-indigo-500">Updating…</span>}
          </div>
          {history === null ? (
            <p className="mt-1 text-xs text-zinc-400">{loadError ? "Could not load." : "Loading…"}</p>
          ) : history.entries.length === 0 ? (
            <p className="mt-1 text-xs text-zinc-400">No communications logged yet — the summary appears after the first one.</p>
          ) : (
            <>
              <p className="mt-1 text-sm">{history.summary || "Generating…"}</p>
              <p className="mt-1 text-[11px] text-zinc-400">
                Based on {history.based_on_entries} logged communication{history.based_on_entries === 1 ? "" : "s"}
                {history.updated_at && ` · updated ${new Date(history.updated_at).toLocaleString()}`}
              </p>
            </>
          )}
        </div>

        {history?.intelligence && (
          <div className="rounded-md border border-zinc-200 bg-zinc-50/60 p-3 dark:border-zinc-800 dark:bg-zinc-900/40">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">Conversation intelligence</p>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                  history.intelligence.interest_level === "High"
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
                    : history.intelligence.interest_level === "Medium"
                      ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400"
                      : history.intelligence.interest_level === "Low"
                        ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400"
                        : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                }`}
              >
                {history.intelligence.interest_level === "Insufficient evidence"
                  ? "Insufficient evidence"
                  : `${history.intelligence.interest_level} interest`}
              </span>
            </div>

            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <div><dt className="text-zinc-400">Current comp</dt><dd>{history.intelligence.current_compensation || "—"}</dd></div>
              <div><dt className="text-zinc-400">Expected comp</dt><dd>{history.intelligence.expected_compensation || "—"}</dd></div>
              <div><dt className="text-zinc-400">Notice period</dt><dd>{history.intelligence.notice_period || "—"}</dd></div>
              <div><dt className="text-zinc-400">Relocation</dt><dd>{history.intelligence.relocation_willingness || "—"}</dd></div>
            </dl>

            {history.intelligence.motivation && (
              <p className="mt-2 text-xs"><span className="text-zinc-400">Motivation: </span>{history.intelligence.motivation}</p>
            )}
            {history.intelligence.concerns.length > 0 && (
              <div className="mt-2">
                <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">Concerns</p>
                <ul className="list-disc pl-4 text-xs text-zinc-600 dark:text-zinc-400">
                  {history.intelligence.concerns.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}
            {history.intelligence.risks.length > 0 && (
              <div className="mt-2">
                <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">Risks</p>
                <ul className="list-disc pl-4 text-xs text-zinc-600 dark:text-zinc-400">
                  {history.intelligence.risks.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}
            {history.intelligence.unanswered_questions.length > 0 && (
              <div className="mt-2">
                <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">Unanswered</p>
                <ul className="list-disc pl-4 text-xs text-zinc-600 dark:text-zinc-400">
                  {history.intelligence.unanswered_questions.map((q, i) => <li key={i}>{q}</li>)}
                </ul>
              </div>
            )}
            <p className="mt-2 border-t border-zinc-200 pt-2 text-xs font-medium dark:border-zinc-800">
              <span className="text-zinc-400 font-normal">Talyn recommendation: </span>
              {history.intelligence.recommendation}
            </p>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <p className="text-xs font-semibold text-zinc-500">Log a communication (email sent, call notes/transcript, or anything else)</p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={manualChannel}
              onChange={(e) => setManualChannel(e.target.value as CommunicationChannel)}
              aria-label="Communication channel"
              className="rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
            >
              {(["email", "whatsapp", "call", "note"] as CommunicationChannel[]).map((c) => (
                <option key={c} value={c}>{CHANNEL_LABEL[c]}</option>
              ))}
            </select>
            <input
              value={manualContent}
              onChange={(e) => setManualContent(e.target.value)}
              placeholder="What happened / message content"
              className="min-w-[220px] flex-1 rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
            />
          </div>
          {manualChannel === "call" && (
            <textarea
              value={manualTranscript}
              onChange={(e) => setManualTranscript(e.target.value)}
              placeholder="Transcript (optional) — paste it here today; a real transcription provider would fill this in automatically"
              rows={2}
              className="w-full rounded-md border border-zinc-300 p-2 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
            />
          )}
          <button
            onClick={saveManualEntry}
            disabled={!manualContent.trim() || loggingEntry}
            className="self-start rounded-md border border-zinc-300 px-2.5 py-1 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            {loggingEntry ? "Logging…" : "Log entry"}
          </button>
        </div>

        {history && history.entries.length > 0 && (
          <ul className="flex flex-col gap-2 border-t border-zinc-100 pt-3 dark:border-zinc-800">
            {[...history.entries].reverse().map((e) => (
              <li key={e.id} className="text-sm">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    {CHANNEL_LABEL[e.channel]}
                  </span>
                  <span className="text-[11px] text-zinc-400">{new Date(e.created_at).toLocaleString()}</span>
                </div>
                {e.content && <p className="mt-0.5">{e.content}</p>}
                {e.transcript && (
                  <p className="mt-0.5 whitespace-pre-wrap text-xs text-zinc-500">Transcript: {e.transcript}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
