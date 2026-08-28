const VARIANTS = {
  ok: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400",
  pending: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  running: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  critical: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400",
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
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          variant === "ok"
            ? "bg-emerald-500"
            : variant === "running"
              ? "bg-amber-500"
              : variant === "critical"
                ? "bg-red-500"
                : "bg-zinc-400"
        }`}
      />
      {label}
    </span>
  );
}
