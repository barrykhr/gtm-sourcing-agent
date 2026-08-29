import { ReactNode } from "react";

/** Browser-chrome preview card — lifted directly from Zocket's product
 * screenshots (traffic-light dots + a tab title bar around live-looking
 * content). Used wherever AI output should read as "a real, live
 * surface" rather than plain text in a plain card: a sourcing-search
 * string, a generated draft, a Copilot exchange. */
export function PreviewFrame({
  label,
  live,
  children,
}: {
  label: string;
  live?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-surface shadow-xs">
      <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2">
        <span className="flex gap-1">
          <span className="h-2 w-2 rounded-full bg-[var(--border)]" />
          <span className="h-2 w-2 rounded-full bg-[var(--border)]" />
          <span className="h-2 w-2 rounded-full bg-[var(--border)]" />
        </span>
        <span className="flex-1 text-center text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        {live && (
          <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-success">
            <span className="ai-pulse h-1.5 w-1.5 rounded-full bg-success" />
            Live
          </span>
        )}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
