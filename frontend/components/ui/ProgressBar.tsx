/** Design-system progress bar (Batch 1) — role hiring progress, bulk
 * action progress, funnel completion. `tone` picks the fill color from
 * the semantic tokens (accent for neutral/in-progress work, success once
 * something is fully done) rather than a one-off hex. */
export function ProgressBar({
  value,
  max = 100,
  tone = "accent",
  className = "",
}: {
  value: number;
  max?: number;
  tone?: "accent" | "success";
  className?: string;
}) {
  const pct = max <= 0 ? 0 : Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-[var(--border)] ${className}`}>
      <div
        className={`h-full rounded-full transition-[width] duration-300 ease-out ${
          tone === "success" ? "bg-success" : "bg-accent"
        }`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
