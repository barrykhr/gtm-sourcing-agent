"use client";

import { useEffect, useState } from "react";
import {
  AskInterviewAnswer,
  EvidenceStrength,
  Interview,
  InterviewIntelligence,
  analyzeInterview,
  askInterviewQuestion,
  getInterviewIntelligence,
  listInterviews,
  pollTaskUntilDone,
} from "@/lib/api";
import { Card } from "@/components/ui/Card";

const EVIDENCE_CLASS: Record<EvidenceStrength, string> = {
  "Strong evidence": "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400",
  "Needs validation": "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  "Not discussed": "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  "Insufficient evidence": "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-400",
};

const SPEAKER_LABEL: Record<"recruiter" | "candidate" | "unknown", string> = {
  recruiter: "Recruiter",
  candidate: "Candidate",
  unknown: "Unknown",
};

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// Interview Intelligence, Phase 3: the evidence scorecard + Ask Talyn,
// promoted out of each interview's own expandable row (Phase 2's first
// home for it) into its own top-level card — a candidate can have
// several interviews, and picking "which interview's intelligence am I
// looking at" belongs here, not buried inside a recording's detail view.
//
// Self-contained like InterviewsCard, CommunicationsCard, etc. — fetches
// its own interview list rather than sharing InterviewsCard's state, so
// it drops into the candidate row independently.
export function IntelligenceCard({ roleId, candidateId }: { roleId: string; candidateId: string }) {
  const [interviews, setInterviews] = useState<Interview[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [intelligence, setIntelligence] = useState<InterviewIntelligence | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [expandedCompetencyId, setExpandedCompetencyId] = useState<number | null>(null);
  const [askQuestion, setAskQuestion] = useState("");
  const [askAnswer, setAskAnswer] = useState<AskInterviewAnswer | null>(null);
  const [asking, setAsking] = useState(false);

  function loadIntelligenceFor(interviewId: string) {
    getInterviewIntelligence(interviewId).then(setIntelligence).catch(() => setIntelligence(null));
  }

  function selectInterview(list: Interview[], id: string | null) {
    setSelectedId(id);
    setIntelligence(null);
    setAskQuestion("");
    setAskAnswer(null);
    const iv = list.find((x) => x.id === id);
    if (iv?.intelligence_status === "completed") {
      loadIntelligenceFor(iv.id);
    }
  }

  // Interviews are recorded in the sibling InterviewsCard, so a newly
  // completed one won't appear here until this refetches — keeps the two
  // cards decoupled (no shared state) at the cost of needing an explicit
  // refresh, surfaced as a button rather than polling.
  async function loadInterviewsList(keepSelection: boolean) {
    try {
      const list = await listInterviews(roleId, candidateId);
      // Most-recent-first, matching InterviewsCard's list order. Only
      // interviews with a finished transcript have anything to analyze.
      const analyzable = [...list].reverse().filter((iv) => iv.transcript_status === "completed");
      setInterviews(analyzable);
      const keep = keepSelection && analyzable.some((iv) => iv.id === selectedId);
      selectInterview(analyzable, keep ? selectedId : (analyzable[0]?.id ?? null));
    } catch {
      setLoadError(true);
    }
  }

  useEffect(() => {
    listInterviews(roleId, candidateId)
      .then((list) => {
        const analyzable = [...list].reverse().filter((iv) => iv.transcript_status === "completed");
        setInterviews(analyzable);
        selectInterview(analyzable, analyzable[0]?.id ?? null);
      })
      .catch(() => setLoadError(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roleId, candidateId]);

  async function refresh() {
    setRefreshing(true);
    try {
      await loadInterviewsList(true);
    } finally {
      setRefreshing(false);
    }
  }

  const selected = interviews?.find((iv) => iv.id === selectedId) ?? null;

  async function runAnalysis() {
    if (!selected) return;
    setAnalyzing(true);
    try {
      const task = await analyzeInterview(selected.id);
      await pollTaskUntilDone(roleId, task.task_id);
      // Refreshing (keeping the current selection) picks up the outcome
      // either way: intelligence_status/intelligence_error on success or
      // failure, and selectInterview loads the scorecard automatically
      // once intelligence_status reads "completed".
      await loadInterviewsList(true);
    } finally {
      setAnalyzing(false);
    }
  }

  async function askTalyn() {
    if (!selected || !askQuestion.trim()) return;
    setAsking(true);
    setAskAnswer(null);
    try {
      const task = await askInterviewQuestion(selected.id, askQuestion.trim());
      const finished = await pollTaskUntilDone(roleId, task.task_id);
      if (finished.status === "succeeded" && finished.result) {
        setAskAnswer(finished.result as AskInterviewAnswer);
      }
    } finally {
      setAsking(false);
    }
  }

  return (
    <Card title="Intelligence">
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <p className="text-[11px] text-zinc-400">
            Maps this role&apos;s must-haves/nice-to-haves against what the candidate actually said in a completed
            interview — never the resume, and never a hire/reject call.
          </p>
          <button
            onClick={refresh}
            disabled={refreshing}
            title="Pick up a newly completed interview from the Interviews card above"
            className="shrink-0 rounded-md border border-zinc-300 px-2 py-1 text-[11px] font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {interviews === null ? (
          <p className="text-xs text-zinc-400">{loadError ? "Could not load interviews." : "Loading…"}</p>
        ) : interviews.length === 0 ? (
          <p className="text-xs text-zinc-400">
            Record and complete an interview first — intelligence needs a finished transcript to work from.
          </p>
        ) : (
          <>
            {interviews.length > 1 && (
              <select
                value={selectedId ?? ""}
                onChange={(e) => selectInterview(interviews, e.target.value)}
                aria-label="Interview"
                className="rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
              >
                {interviews.map((iv) => (
                  <option key={iv.id} value={iv.id}>
                    {(iv.title || "Interview") + " — " + new Date(iv.started_at).toLocaleString()}
                  </option>
                ))}
              </select>
            )}

            {selected && (
              <div>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">
                    {selected.title || "Interview"}
                  </p>
                  {selected.intelligence_status !== "processing" && (
                    <button
                      onClick={runAnalysis}
                      disabled={analyzing}
                      className="rounded-md border border-zinc-300 px-2 py-1 text-[11px] font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    >
                      {analyzing ? "Analyzing…" : intelligence ? "Re-analyze" : "Analyze interview"}
                    </button>
                  )}
                </div>

                {selected.intelligence_status === "processing" && (
                  <p className="mt-2 text-xs text-indigo-600 dark:text-indigo-400">Analyzing transcript…</p>
                )}
                {selected.intelligence_status === "failed" && selected.intelligence_error && (
                  <p className="mt-2 text-xs text-red-600 dark:text-red-400">{selected.intelligence_error}</p>
                )}
                {selected.intelligence_status === "pending" && !analyzing && (
                  <p className="mt-2 text-xs text-zinc-400">Not analyzed yet.</p>
                )}

                {intelligence && intelligence.competencies.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1.5">
                    {intelligence.competencies.map((c) => (
                      <li key={c.id} className="rounded border border-zinc-200 dark:border-zinc-800">
                        <button
                          onClick={() => setExpandedCompetencyId(expandedCompetencyId === c.id ? null : c.id)}
                          className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-xs"
                        >
                          <span className="flex items-center gap-2">
                            <span
                              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${EVIDENCE_CLASS[c.status]}`}
                            >
                              {c.status}
                            </span>
                            <span>{c.competency}</span>
                            <span className="text-[10px] uppercase text-zinc-400">
                              {c.category === "must_have" ? "must-have" : "nice-to-have"}
                            </span>
                          </span>
                        </button>
                        {expandedCompetencyId === c.id && (
                          <div className="border-t border-zinc-100 px-2 py-1.5 dark:border-zinc-800">
                            <p className="text-xs text-zinc-600 dark:text-zinc-400">{c.rationale}</p>
                            {c.evidence.length > 0 && (
                              <ul className="mt-1.5 flex flex-col gap-1">
                                {c.evidence.map((e, i) => (
                                  <li key={i} className="rounded bg-zinc-50 p-1.5 text-[11px] dark:bg-zinc-900">
                                    <span className="mr-1.5 text-zinc-400">{formatTimestamp(e.start_time)}</span>
                                    <span className="mr-1.5 font-medium">{SPEAKER_LABEL[e.speaker]}:</span>
                                    {e.text}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}

                {intelligence && intelligence.follow_up_questions.length > 0 && (
                  <div className="mt-3">
                    <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                      Suggested follow-up questions
                    </p>
                    <ul className="mt-1 list-disc pl-4 text-xs text-zinc-700 dark:text-zinc-300">
                      {intelligence.follow_up_questions.map((f) => (
                        <li key={f.id} title={f.rationale}>{f.question}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="mt-3 border-t border-zinc-100 pt-3 dark:border-zinc-800">
                  <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">Ask Talyn</p>
                  <div className="mt-1 flex gap-2">
                    <input
                      value={askQuestion}
                      onChange={(e) => setAskQuestion(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && askTalyn()}
                      placeholder="Ask a question about this interview…"
                      className="flex-1 rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
                    />
                    <button
                      onClick={askTalyn}
                      disabled={asking || !askQuestion.trim()}
                      className="shrink-0 rounded-md border border-zinc-300 px-2 py-1 text-[11px] font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    >
                      {asking ? "Asking…" : "Ask"}
                    </button>
                  </div>
                  {askAnswer && (
                    <div className="mt-2 rounded-md bg-indigo-50/60 p-2 dark:bg-indigo-950/30">
                      <p className="text-xs">{askAnswer.answer}</p>
                      {askAnswer.citations.length > 0 && (
                        <ul className="mt-1 flex flex-col gap-1">
                          {askAnswer.citations.map((c, i) => (
                            <li key={i} className="text-[11px] text-zinc-500">
                              <span className="mr-1">{formatTimestamp(c.start_time)}</span>
                              <span className="font-medium">{SPEAKER_LABEL[c.speaker]}:</span> {c.text}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                  <p className="mt-1 text-[11px] text-zinc-400">
                    Answers only from this transcript, the resume, and the job requirements — never invents evidence.
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
