import type { CompetencyScore, CompetencyStrength } from "@/lib/api";

const STRENGTH_CLASS: Record<CompetencyStrength, string> = {
  STRONG: "text-accent",
  CONFIRMED: "text-accent",
  MODERATE: "text-[var(--warning)]",
  WEAK: "text-muted-foreground",
  UNCONFIRMED: "text-muted-foreground",
};

/** Five dash segments, filled left-to-right by score/100 — the same
 * "———— STRONG" meter the reference recruiter-workspace mockup uses for
 * per-dimension candidate scoring, rather than a generic progress bar. */
function DashedMeter({ score }: { score: number }) {
  const filled = Math.max(0, Math.min(5, Math.round(score / 20)));
  return (
    <span className="flex items-center gap-1" aria-hidden="true">
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className={`h-[2px] w-3.5 rounded-full ${i < filled ? "bg-accent" : "bg-[var(--border-strong)]"}`}
        />
      ))}
    </span>
  );
}

function CompetencyRow({ score }: { score: CompetencyScore }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2" title={score.rationale}>
      <span className="text-sm">{score.label}</span>
      <span className="flex items-center gap-2.5 shrink-0">
        <DashedMeter score={score.score} />
        <span className={`font-mono text-[11px] font-medium tracking-wide ${STRENGTH_CLASS[score.strength]}`}>
          {score.strength}
        </span>
      </span>
    </div>
  );
}

/** "Candidate Intelligence" — per-dimension competency breakdown plus the
 * recommend/watch panel, matching the reference candidate-detail mockup.
 * `scores` come from CandidatePrioritization.competency_scores (real,
 * model-generated, evidence-grounded — see prompts/prioritization.md);
 * this component only lays them out, it never invents a number. */
export function CompetencyScorePanel({
  scores,
  whyTheyFit,
  watch,
}: {
  scores: CompetencyScore[];
  whyTheyFit: string[];
  watch: string[];
}) {
  if (scores.length === 0 && whyTheyFit.length === 0 && watch.length === 0) return null;

  return (
    <div className="grid gap-3 lg:grid-cols-5">
      {scores.length > 0 && (
        <div className="rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] lg:col-span-3 dark:border-zinc-800">
          <p className="eyebrow mb-1">Candidate intelligence</p>
          <div className="divide-y divide-[var(--border-subtle)]">
            {scores.map((s) => (
              <CompetencyRow key={s.dimension} score={s} />
            ))}
          </div>
        </div>
      )}

      {(whyTheyFit.length > 0 || watch.length > 0) && (
        <div className="rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] lg:col-span-2 dark:border-zinc-800">
          {whyTheyFit.length > 0 && (
            <>
              <p className="eyebrow mb-2">Why we&apos;re recommending this person</p>
              <ul className="space-y-1.5 text-sm">
                {whyTheyFit.map((v, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-accent">•</span>
                    <span>{v}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {whyTheyFit.length > 0 && watch.length > 0 && (
            <hr className="my-3 border-[var(--border-subtle)]" />
          )}
          {watch.length > 0 && (
            <>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">What to watch</p>
              <ul className="space-y-1.5 text-sm text-muted-foreground">
                {watch.map((v, i) => (
                  <li key={i} className="flex gap-2">
                    <span>•</span>
                    <span>{v}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
