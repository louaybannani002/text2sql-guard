"use client";

import { Check, CircleDashed, CircleSlash, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { formatMs } from "@/lib/format";
import type { Step, StepStatus } from "@/lib/stages";
import { cn } from "@/lib/utils";

interface Props {
  steps: Step[];
  running: boolean;
  startedAt: number;
}

const ICONS: Record<StepStatus, React.ReactNode> = {
  pending: <CircleDashed className="size-4 text-muted-foreground/60" aria-hidden />,
  running: <Loader2 className="size-4 animate-spin text-primary" aria-hidden />,
  done: <Check className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden />,
  error: <X className="size-4 text-destructive" aria-hidden />,
  skipped: <CircleSlash className="size-4 text-muted-foreground/60" aria-hidden />,
};

const STATUS_TEXT: Record<StepStatus, string> = {
  pending: "waiting",
  running: "in progress",
  done: "done",
  error: "failed",
  skipped: "skipped",
};

export function StageProgress({ steps, running, startedAt }: Props) {
  const elapsed = useElapsed(running, startedAt);
  const active = steps.find((s) => s.status === "running");

  return (
    <section aria-label="Pipeline progress" className="grid grid-cols-1 gap-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{running ? "Working on it…" : "Pipeline"}</span>
        {running ? (
          <span className="text-muted-foreground tabular-nums">{formatMs(elapsed)}</span>
        ) : null}
      </div>
      <p className="sr-only" aria-live="polite">
        {active ? `${active.label}…` : ""}
      </p>
      <ol className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {steps.map((step) => (
          <li
            key={step.stage}
            className={cn(
              "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm transition-colors",
              step.status === "running" && "border-primary/40 bg-primary/5",
              step.status === "error" && "border-destructive/40 bg-destructive/5",
              (step.status === "pending" || step.status === "skipped") && "text-muted-foreground",
            )}
            data-status={step.status}
          >
            <span className="mt-0.5">{ICONS[step.status]}</span>
            <span className="grid min-w-0 flex-1 gap-0.5">
              <span className="flex items-center justify-between gap-2">
                <span>
                  {step.label}
                  {step.attempt === 0 ? (
                    <span className="text-muted-foreground"> · cached query</span>
                  ) : step.attempt > 1 ? (
                    <span className="text-muted-foreground"> · attempt {step.attempt}</span>
                  ) : null}
                  <span className="sr-only"> ({STATUS_TEXT[step.status]})</span>
                </span>
                {step.latencyMs !== null ? (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {formatMs(step.latencyMs)}
                  </span>
                ) : null}
              </span>
              {step.message ? (
                <span className="text-xs break-words text-muted-foreground">{step.message}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function useElapsed(running: boolean, startedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(timer);
  }, [running]);
  return Math.max(0, now - startedAt);
}
