"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  ChatMessage,
  PendingProposal,
  confirmChatProposal,
  getChat,
  postChat,
} from "@/lib/api";

/**
 * The AI Copilot: a persistent side panel, not a tab you switch into
 * (see the product correction in the session history — chat is a
 * secondary control layer over the product, not the product itself).
 * Available from any job-workspace tab; `onAction` fires after every
 * turn and every confirm so the parent can refresh whatever tab is
 * currently visible — the whole point is that talking to the copilot
 * visibly changes the product, not just the chat transcript.
 */
export function CopilotPanel({
  roleId,
  open,
  onClose,
  onAction,
}: {
  roleId: string;
  open: boolean;
  onClose: () => void;
  onAction: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<PendingProposal | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getChat(roleId)
      .then((c) => {
        setMessages(c.messages);
        setPending(c.pending_proposal);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the copilot."));
  }, [roleId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  async function send() {
    const message = input.trim();
    if (!message) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: message }]);
    setSending(true);
    setError(null);
    try {
      const result = await postChat(roleId, message);
      setMessages((prev) => [...prev, { role: "assistant", text: result.reply }]);
      setPending(result.pending_proposal);
      onAction();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The copilot didn't respond.");
    } finally {
      setSending(false);
    }
  }

  async function confirm(approve: boolean) {
    setConfirming(true);
    try {
      await confirmChatProposal(roleId, approve);
      setPending(null);
      load();
      onAction();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not apply the change.");
    } finally {
      setConfirming(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-sm flex-col border-l border-zinc-200 bg-surface shadow-[var(--shadow-lg)] dark:border-zinc-800">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div>
          <h2 className="text-sm font-semibold">AI Copilot</h2>
          <p className="text-xs text-zinc-500">Acts on this job — never sends outreach or applies requirement changes without your OK.</p>
        </div>
        <button
          onClick={onClose}
          className="rounded-md px-2 py-1 text-sm text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          aria-label="Close copilot"
        >
          ✕
        </button>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
        {messages.length === 0 ? (
          <p className="text-sm text-zinc-400">
            Ask about this job — e.g. &ldquo;who have we got so far?&rdquo; or &ldquo;remove Fabric as a mandatory
            requirement.&rdquo;
          </p>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                m.role === "user"
                  ? "self-end bg-indigo-700 text-white"
                  : "self-start bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
              }`}
            >
              {m.text}
            </div>
          ))
        )}

        {pending && (
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">Proposed change</p>
            <p>{pending.description}</p>
            <p className="mt-1 text-zinc-500">{pending.impact}</p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => confirm(true)}
                disabled={confirming}
                className="rounded-md bg-indigo-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
              >
                {confirming ? "Applying…" : "Yes — apply"}
              </button>
              <button
                onClick={() => confirm(false)}
                disabled={confirming}
                className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                No
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
            {error}
          </div>
        )}
      </div>

      <div className="flex gap-2 border-t border-zinc-200 p-3 dark:border-zinc-800">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !sending && send()}
          placeholder="Ask the copilot…"
          className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
        />
        <button
          onClick={send}
          disabled={sending || !input.trim()}
          className="rounded-md bg-indigo-700 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
        >
          {sending ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
