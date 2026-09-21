"use client";

import { useEffect, useRef, useState } from "react";
import {
  Interview,
  TranscriptSegment,
  completeInterview,
  correctSegmentSpeaker,
  createInterview,
  getInterview,
  getTranscript,
  listInterviews,
  pollTaskUntilDone,
  retryInterviewProcessing,
  uploadInterviewRecording,
} from "@/lib/api";
import { Card } from "@/components/ui/Card";

const STATUS_LABEL: Record<Interview["status"], string> = {
  recording: "Recording",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
};

const STATUS_CLASS: Record<Interview["status"], string> = {
  recording: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  processing: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400",
  failed: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};

const SPEAKER_LABEL: Record<TranscriptSegment["speaker"], string> = {
  recruiter: "Recruiter",
  candidate: "Candidate",
  unknown: "Unknown",
};

function formatElapsed(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// Interview recording + transcript + AI summary (Interview Intelligence,
// Phase 1 — the notetaker). Uses the browser's own MediaRecorder API to
// capture the interview locally, uploads the recording once the
// recruiter ends it, then polls the same background-task pipeline the
// rest of this app uses (transcribe -> speaker labels -> summary).
//
// Self-contained, same pattern as CommunicationsCard — owns its own
// state, drops into the candidate row alongside it.
export function InterviewsCard({
  roleId,
  candidateId,
  candidateName,
}: {
  roleId: string;
  candidateId: string;
  candidateName: string;
}) {
  const [interviews, setInterviews] = useState<Interview[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  function loadInterviews() {
    listInterviews(roleId, candidateId)
      .then((list) => setInterviews([...list].reverse()))
      .catch(() => setLoadError(true));
  }
  useEffect(loadInterviews, [roleId, candidateId]);

  // ── recording ────────────────────────────────────────────────────────
  const [micError, setMicError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [active, setActive] = useState<Interview | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopTimer() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  function stopStream() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  // Release the microphone if the recruiter navigates away mid-recording.
  useEffect(() => () => {
    stopTimer();
    stopStream();
  }, []);

  async function startInterview() {
    setMicError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicError("This browser doesn't support microphone recording.");
      return;
    }
    setStarting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const interview = await createInterview(roleId, candidateId, `Interview — ${candidateName}`);
      streamRef.current = stream;
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorderRef.current = recorder;
      recorder.start();
      setActive(interview);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
      loadInterviews();
    } catch {
      setMicError("Microphone access was denied or unavailable — allow microphone access and try again.");
    } finally {
      setStarting(false);
    }
  }

  async function endInterview() {
    const interview = active;
    const recorder = recorderRef.current;
    if (!interview || !recorder) return;
    setEnding(true);
    stopTimer();

    const recordingDone = new Promise<Blob>((resolve) => {
      recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }));
    });
    recorder.stop();
    stopStream();

    try {
      const blob = await recordingDone;
      await completeInterview(interview.id);
      setActive(null);
      loadInterviews();

      setPipelineStatus("Uploading recording…");
      const task = await uploadInterviewRecording(interview.id, blob, `${interview.id}.webm`);
      setPipelineStatus("Transcribing and summarizing…");
      await pollTaskUntilDone(roleId, task.task_id);
      setPipelineStatus(null);
      loadInterviews();
    } catch (err) {
      // Upload/transcription failures are also written to the interview
      // record itself (see interview_processing.py) — reload so the
      // failed status + error message shows in the list below, and
      // surface a quick inline note for the case that fails before that
      // (audio storage not configured, so the interview stays "failed"
      // with the error already set server-side, or a network error here).
      setPipelineStatus(null);
      setMicError(err instanceof Error ? err.message : "Something went wrong processing the recording.");
      loadInterviews();
    } finally {
      setEnding(false);
      recorderRef.current = null;
    }
  }

  // ── viewing a past interview ────────────────────────────────────────
  const [openId, setOpenId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptSegment[] | null>(null);
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [retryingId, setRetryingId] = useState<string | null>(null);

  function toggleOpen(interview: Interview) {
    if (openId === interview.id) {
      setOpenId(null);
      setTranscript(null);
      return;
    }
    setOpenId(interview.id);
    setTranscript(null);
    setTranscriptQuery("");
    if (interview.transcript_status === "completed") {
      getTranscript(interview.id).then(setTranscript).catch(() => setTranscript([]));
    }
  }

  function searchTranscript(interviewId: string, q: string) {
    setTranscriptQuery(q);
    getTranscript(interviewId, q || undefined).then(setTranscript).catch(() => {});
  }

  async function fixSpeaker(interviewId: string, segmentId: number, speaker: TranscriptSegment["speaker"]) {
    const updated = await correctSegmentSpeaker(interviewId, segmentId, speaker);
    setTranscript((prev) => prev?.map((s) => (s.id === segmentId ? updated : s)) ?? prev);
  }

  async function retry(interviewId: string) {
    setRetryingId(interviewId);
    try {
      const task = await retryInterviewProcessing(interviewId);
      loadInterviews();
      await pollTaskUntilDone(roleId, task.task_id);
      loadInterviews();
      const fresh = await getInterview(interviewId);
      if (fresh.transcript_status === "completed" && openId === interviewId) {
        getTranscript(interviewId).then(setTranscript).catch(() => {});
      }
    } finally {
      setRetryingId(null);
    }
  }

  return (
    <Card title="Interviews">
      <div className="flex flex-col gap-4">
        {active ? (
          <div className="flex items-center justify-between rounded-md border border-red-200 bg-red-50/60 px-3 py-2 dark:border-red-900 dark:bg-red-950/30">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 animate-pulse rounded-full bg-red-600" />
              <span className="text-sm font-medium text-red-800 dark:text-red-400">
                Recording — {formatElapsed(elapsed)}
              </span>
            </div>
            <button
              onClick={endInterview}
              disabled={ending}
              className="rounded-md bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-800 disabled:opacity-50"
            >
              {ending ? "Ending…" : "End interview"}
            </button>
          </div>
        ) : (
          <div>
            <button
              onClick={startInterview}
              disabled={starting}
              className="rounded-md bg-indigo-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
            >
              {starting ? "Requesting microphone…" : "Start interview"}
            </button>
            {micError && <p className="mt-1 text-[11px] text-red-600 dark:text-red-400">{micError}</p>}
            <p className="mt-1 text-[11px] text-zinc-400">
              Records audio in this browser tab, then transcribes it and maps the conversation into an interview
              summary. Nothing decides hire/reject for you — evidence and gaps only.
            </p>
          </div>
        )}

        {pipelineStatus && <p className="text-xs text-indigo-600 dark:text-indigo-400">{pipelineStatus}</p>}

        {interviews === null ? (
          <p className="text-xs text-zinc-400">{loadError ? "Could not load interviews." : "Loading…"}</p>
        ) : interviews.length === 0 ? (
          <p className="text-xs text-zinc-400">No interviews recorded yet.</p>
        ) : (
          <ul className="flex flex-col gap-2 border-t border-zinc-100 pt-3 dark:border-zinc-800">
            {interviews.map((interview) => (
              <li key={interview.id} className="rounded-md border border-zinc-200 dark:border-zinc-800">
                <button
                  onClick={() => toggleOpen(interview)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STATUS_CLASS[interview.status]}`}
                    >
                      {STATUS_LABEL[interview.status]}
                    </span>
                    <span className="text-sm">{interview.title || "Interview"}</span>
                  </div>
                  <span className="text-[11px] text-zinc-400">
                    {new Date(interview.started_at).toLocaleString()}
                  </span>
                </button>

                {openId === interview.id && (
                  <div className="border-t border-zinc-100 px-3 py-3 dark:border-zinc-800">
                    {interview.error && (
                      <div className="mb-3 flex items-center justify-between gap-2 rounded-md border border-red-200 bg-red-50/60 px-2.5 py-1.5 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
                        <span>{interview.error}</span>
                        <button
                          onClick={() => retry(interview.id)}
                          disabled={retryingId === interview.id}
                          className="shrink-0 rounded border border-red-300 px-2 py-0.5 text-[11px] font-medium hover:bg-red-100 disabled:opacity-50 dark:border-red-800 dark:hover:bg-red-900"
                        >
                          {retryingId === interview.id ? "Retrying…" : "Retry"}
                        </button>
                      </div>
                    )}

                    {interview.summary && (
                      <div className="mb-3 rounded-md border border-indigo-200 bg-indigo-50/60 p-3 dark:border-indigo-900 dark:bg-indigo-950/40">
                        <p className="text-xs font-semibold text-indigo-800 dark:text-indigo-300">Summary</p>
                        <p className="mt-1 text-sm">{interview.summary.overview}</p>
                        <div className="mt-2 grid gap-2 sm:grid-cols-2">
                          {interview.summary.key_experience.length > 0 && (
                            <div>
                              <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                                Key experience
                              </p>
                              <ul className="list-disc pl-4 text-xs text-zinc-700 dark:text-zinc-300">
                                {interview.summary.key_experience.map((v, i) => <li key={i}>{v}</li>)}
                              </ul>
                            </div>
                          )}
                          {interview.summary.technical_skills.length > 0 && (
                            <div>
                              <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                                Technical skills
                              </p>
                              <ul className="list-disc pl-4 text-xs text-zinc-700 dark:text-zinc-300">
                                {interview.summary.technical_skills.map((v, i) => <li key={i}>{v}</li>)}
                              </ul>
                            </div>
                          )}
                          {interview.summary.examples_provided.length > 0 && (
                            <div>
                              <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                                Examples provided
                              </p>
                              <ul className="list-disc pl-4 text-xs text-zinc-700 dark:text-zinc-300">
                                {interview.summary.examples_provided.map((v, i) => <li key={i}>{v}</li>)}
                              </ul>
                            </div>
                          )}
                          {interview.summary.areas_not_discussed.length > 0 && (
                            <div>
                              <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                                Not discussed
                              </p>
                              <ul className="list-disc pl-4 text-xs text-zinc-700 dark:text-zinc-300">
                                {interview.summary.areas_not_discussed.map((v, i) => <li key={i}>{v}</li>)}
                              </ul>
                            </div>
                          )}
                        </div>
                        {interview.summary.potential_followups.length > 0 && (
                          <div className="mt-2">
                            <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                              Potential follow-ups
                            </p>
                            <ul className="list-disc pl-4 text-xs text-zinc-700 dark:text-zinc-300">
                              {interview.summary.potential_followups.map((v, i) => <li key={i}>{v}</li>)}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {interview.transcript_status === "processing" && (
                      <p className="text-xs text-zinc-400">Transcribing…</p>
                    )}

                    {interview.transcript_status === "completed" && interview.intelligence_status === "completed" && (
                      <p className="mb-3 text-[11px] text-zinc-400">
                        See the Intelligence card below for this interview&apos;s evidence scorecard and Ask Talyn.
                      </p>
                    )}

                    {transcript && (
                      <div>
                        <input
                          value={transcriptQuery}
                          onChange={(e) => searchTranscript(interview.id, e.target.value)}
                          placeholder="Search transcript"
                          className="mb-2 w-full rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
                        />
                        {transcript.length === 0 ? (
                          <p className="text-xs text-zinc-400">
                            {transcriptQuery ? "No matching segments." : "No transcript segments."}
                          </p>
                        ) : (
                          <ul className="flex max-h-64 flex-col gap-1.5 overflow-y-auto">
                            {transcript.map((seg) => (
                              <li key={seg.id} className="text-xs">
                                <span className="mr-1.5 text-zinc-400">{formatTimestamp(seg.start_time)}</span>
                                <select
                                  value={seg.speaker}
                                  onChange={(e) =>
                                    fixSpeaker(interview.id, seg.id, e.target.value as TranscriptSegment["speaker"])
                                  }
                                  aria-label="Speaker"
                                  className={`mr-1.5 rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                                    seg.speaker === "recruiter"
                                      ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-400"
                                      : seg.speaker === "candidate"
                                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
                                        : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                                  }`}
                                >
                                  {(["recruiter", "candidate", "unknown"] as const).map((s) => (
                                    <option key={s} value={s}>{SPEAKER_LABEL[s]}</option>
                                  ))}
                                </select>
                                {seg.text}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
