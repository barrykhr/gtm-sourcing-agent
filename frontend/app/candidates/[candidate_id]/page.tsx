"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ApiError, CanonicalCandidate, getCandidateGlobal } from "@/lib/api";
import { StatusChip, rygVariant, tierVariant } from "@/components/StatusChip";
import { CommunicationsCard } from "@/components/CommunicationsCard";

export default function CandidateDetail() {
  const params = useParams<{ candidate_id: string }>();
  const [candidate, setCandidate] = useState<CanonicalCandidate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);

  useEffect(() => {
    getCandidateGlobal(params.candidate_id)
      .then((c) => {
        setCandidate(c);
        if (c.evaluations.length > 0) setSelectedRoleId(c.evaluations[0].role_id);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
  }, [params.candidate_id]);

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
        {error}
      </div>
    );
  }
  if (!candidate) return <p className="text-sm text-zinc-500">Loading…</p>;

  const selectedEvaluation = candidate.evaluations.find((e) => e.role_id === selectedRoleId) ?? null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/candidates" className="text-sm text-indigo-700 hover:underline dark:text-indigo-400">
          ← Candidates
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">{candidate.name}</h1>
        <p className="mt-1 text-sm text-zinc-500">
          {candidate.current_title} @ {candidate.current_company}
          {candidate.location && ` · ${candidate.location}`}
        </p>
        {candidate.source_url && (
          <a
            href={candidate.source_url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-xs text-indigo-700 hover:underline dark:text-indigo-400"
          >
            {candidate.source_url}
          </a>
        )}
      </div>

      <div className="rounded-lg border border-zinc-200 bg-surface shadow-[var(--shadow-sm)] dark:border-zinc-800">
        <div className="border-b border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-500">
            Evaluated for {candidate.evaluations.length} job{candidate.evaluations.length === 1 ? "" : "s"}
          </h2>
        </div>
        {candidate.evaluations.length === 0 ? (
          <p className="p-4 text-sm text-zinc-400">No evaluations yet.</p>
        ) : (
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {candidate.evaluations.map((e) => (
              <Link
                key={e.role_id}
                href={`/jobs/${e.role_id}`}
                className="flex items-center justify-between gap-3 p-4 hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
              >
                <div>
                  <p className="font-medium">{e.job_title}</p>
                  {e.why_they_fit && e.why_they_fit.length > 0 && (
                    <p className="mt-0.5 text-xs text-zinc-500">{e.why_they_fit[0]}</p>
                  )}
                  {e.recruiter_decision && (
                    <p className="mt-0.5 text-xs text-zinc-500">recruiter: {e.recruiter_decision}</p>
                  )}
                </div>
                {e.tier ? (
                  <div className="flex items-center gap-1.5">
                    <StatusChip label={`Tier ${e.tier}`} variant={tierVariant(e.tier)} />
                    {e.fit_rating && <StatusChip label={e.fit_rating} variant={rygVariant(e.fit_rating)} />}
                  </div>
                ) : (
                  <StatusChip label="Not prioritized" variant="pending" />
                )}
              </Link>
            ))}
          </div>
        )}
      </div>

      {selectedEvaluation && (
        <div className="flex flex-col gap-2">
          {candidate.evaluations.length > 1 && (
            <div className="flex items-center gap-2 text-xs text-zinc-500">
              <label htmlFor="conversation-role" className="font-medium">Conversation for</label>
              <select
                id="conversation-role"
                value={selectedRoleId ?? ""}
                onChange={(e) => setSelectedRoleId(e.target.value)}
                className="rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
              >
                {candidate.evaluations.map((e) => (
                  <option key={e.role_id} value={e.role_id}>{e.job_title}</option>
                ))}
              </select>
              <span>
                — contact info and logged communications are tracked per role, since the same person can be reached
                differently across different hiring processes.
              </span>
            </div>
          )}
          <CommunicationsCard
            key={selectedEvaluation.role_id}
            roleId={selectedEvaluation.role_id}
            candidateId={selectedEvaluation.candidate_evaluation_id}
            name={candidate.name}
            initialPhone={selectedEvaluation.phone}
            initialEmail={selectedEvaluation.email}
          />
        </div>
      )}
    </div>
  );
}
