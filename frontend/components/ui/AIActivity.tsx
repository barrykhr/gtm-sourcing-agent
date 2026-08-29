import { Check } from "lucide-react";

export type AIActivityStep = {
  label: string;
  status: "done" | "active" | "pending";
};

/** The product's visual language for "AI is doing something" (Batch 1) —
 * a checklist, not a chatbot. ✓ for done, a pulsing ring for the step
 * in progress, a quiet dot for what hasn't started yet. Used on role
 * workspace headers and anywhere a multi-step AI pipeline's state needs
 * to be visible at a glance instead of buried in per-tab busy spinners. */
export function AIActivity({ steps, className = "" }: { steps: AIActivityStep[]; className?: string }) {
  return (
    <ul className={`flex flex-col gap-1.5 ${className}`}>
      {steps.map((step) => (
        <li key={step.label} className="flex items-center gap-2 text-sm">
          {step.status === "done" ? (
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-success text-white">
              <Check size={11} strokeWidth={3} />
            </span>
          ) : step.status === "active" ? (
            <span className="relative flex h-4 w-4 shrink-0 items-center justify-center">
              <span className="ai-pulse absolute h-4 w-4 rounded-full bg-accent/30" />
              <span className="h-2 w-2 rounded-full bg-accent" />
            </span>
          ) : (
            <span className="flex h-4 w-4 shrink-0 items-center justify-center">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--border)]" />
            </span>
          )}
          <span
            className={
              step.status === "pending" ? "text-muted-foreground" : step.status === "active" ? "font-medium" : ""
            }
          >
            {step.label}
          </span>
        </li>
      ))}
    </ul>
  );
}
