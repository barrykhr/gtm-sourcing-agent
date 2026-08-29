const VARIANTS = {
  ok: "bg-success-soft text-success",
  pending: "bg-[var(--border)]/60 text-muted-foreground",
  running: "bg-warning-soft text-warning",
  critical: "bg-critical-soft text-critical",
} as const;

const DOT_VARIANTS = {
  ok: "bg-success",
  pending: "bg-muted-foreground",
  running: "bg-warning",
  critical: "bg-critical",
} as const;

/** Tier "A" -> ok, "D" -> pending, "B"/"C" -> running, no tier yet -> pending. */
export function tierVariant(tier: string | null | undefined): keyof typeof VARIANTS {
  if (tier === "A") return "ok";
  if (tier === "D" || !tier) return "pending";
  return "running";
}

/** Red/Yellow/Green fit rating -> chip variant. */
export function rygVariant(rating: string | null | undefined): keyof typeof VARIANTS {
  if (rating === "GREEN") return "ok";
  if (rating === "RED") return "critical";
  if (rating === "YELLOW") return "running";
  return "pending";
}

export function StatusChip({
  label,
  variant,
}: {
  label: string;
  variant: keyof typeof VARIANTS;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${VARIANTS[variant]}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_VARIANTS[variant]}`} />
      {label}
    </span>
  );
}
