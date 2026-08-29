import { HTMLAttributes } from "react";

/** Design-system Card (Batch 1) — every job-workspace tab today defines
 * its own local `Card` component with slightly different padding/border
 * treatment. This is the one going forward: a bordered surface for
 * content that benefits from grouping, not a container for everything
 * (per the "don't put every piece of information in a rounded card"
 * direction — open canvas and inline text are just as valid). */
export function Card({
  title,
  action,
  padded = true,
  className = "",
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { title?: string; action?: React.ReactNode; padded?: boolean }) {
  return (
    <div
      className={`rounded-lg border border-[var(--border)] bg-surface shadow-xs ${padded ? "p-5" : ""} ${className}`}
      {...rest}
    >
      {(title || action) && (
        <div className={`flex items-center justify-between gap-3 ${padded ? "mb-3" : "border-b border-[var(--border)] p-4"}`}>
          {title && <h3 className="text-sm font-semibold tracking-tight">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
