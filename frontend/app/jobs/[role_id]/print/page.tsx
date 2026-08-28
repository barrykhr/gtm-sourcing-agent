"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, Candidate, getFunnelReport, getJob, Json, JobDetail, listCandidates } from "@/lib/api";

/**
 * A print-only summary of a job — deliberately separate from the
 * workspace itself (Phase 8, docs/product-plan.md) rather than trying
 * to make every tab's interactive UI printable. Hit Ctrl/Cmd+P and
 * "Save as PDF" — no server-side PDF dependency, the browser already
 * does this well.
 */
export default function PrintReportPage() {
  const params = useParams<{ role_id: string }>();
  const roleId = params.role_id;

  const [job, setJob] = useState<JobDetail | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [report, setReport] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getJob(roleId), listCandidates(roleId), getFunnelReport(roleId)])
      .then(([j, c, r]) => {
        setJob(j);
        setCandidates(c);
        setReport(r);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load this report."));
  }, [roleId]);

  if (error) return <p className="p-8 text-sm text-red-700">{error}</p>;
  if (!job) return <p className="p-8 text-sm text-zinc-500">Loading…</p>;

  const icp: Json | undefined = job.state.icp;
  const funnel: Json = job.state.funnel ?? {};

  return (
    <div className="mx-auto max-w-3xl p-8 text-zinc-900 print:p-0">
      <style>{`
        @media print {
          aside, header, .no-print { display: none !important; }
          body { background: white; }
        }
      `}</style>

      <div className="no-print mb-6 flex items-center justify-between rounded-md border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm">
        <span>Print-friendly report — use your browser&apos;s Print (Ctrl/Cmd+P) and save as PDF.</span>
        <button
          onClick={() => window.print()}
          className="rounded-md bg-indigo-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-800"
        >
          Print / Save as PDF
        </button>
      </div>

      <h1 className="text-2xl font-semibold">{job.title}</h1>
      {job.role_family && <p className="text-sm text-zinc-500">{job.role_family}</p>}
      <p className="mt-1 text-xs text-zinc-400">Generated {new Date().toLocaleString()}</p>

      {icp && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Hiring profile</h2>
          <div className="mt-2 grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="font-medium">Must have</p>
              <ul className="list-disc pl-4 text-zinc-700">
                {(icp.must_have ?? []).map((v: string, i: number) => <li key={i}>{v}</li>)}
              </ul>
            </div>
            <div>
              <p className="font-medium">Nice to have</p>
              <ul className="list-disc pl-4 text-zinc-700">
                {(icp.nice_to_have ?? []).map((v: string, i: number) => <li key={i}>{v}</li>)}
              </ul>
            </div>
          </div>
        </section>
      )}

      <section className="mt-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Candidates ({candidates.length})
        </h2>
        <table className="mt-2 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-zinc-300 text-left text-xs uppercase text-zinc-500">
              <th className="py-1 pr-2">Name</th>
              <th className="py-1 pr-2">Role &amp; company</th>
              <th className="py-1 pr-2">Tier</th>
              <th className="py-1 pr-2">Stage</th>
              <th className="py-1">Decision</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.candidate_id} className="border-b border-zinc-100">
                <td className="py-1 pr-2">{c.name}</td>
                <td className="py-1 pr-2 text-zinc-600">{c.current_title} @ {c.current_company}</td>
                <td className="py-1 pr-2">{c.prioritization?.tier ?? "—"}</td>
                <td className="py-1 pr-2">{funnel[c.candidate_id]?.current_stage ?? "IDENTIFIED"}</td>
                <td className="py-1">{c.prioritization?.recruiter_decision ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {report && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">Funnel</h2>
          <div className="mt-2 grid grid-cols-3 gap-x-4 gap-y-1 text-sm">
            {Object.entries(report.counts_by_stage as Record<string, number>).map(([stage, count]) => (
              <div key={stage} className="flex justify-between">
                <span className="text-zinc-500">{stage.replace(/_/g, " ")}</span>
                <span>{count}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
