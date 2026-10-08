/** The pipeline's stages as the user sees them, and how stream events move them along. */
import type { Answer, StageEvent, StageName } from "./api/types";

export type StepStatus = "pending" | "running" | "done" | "error" | "skipped";

export interface Step {
  stage: StageName;
  label: string;
  status: StepStatus;
  /** SQL attempt (1, 2, 3...); 0 when validating/running a query reused from the cache. */
  attempt: number;
  latencyMs: number | null;
  /** Safe message from an `error` event (e.g. why the SQL was rejected). */
  message: string | null;
}

export const STAGE_LABELS: Record<StageName, string> = {
  input_guard: "Checking input",
  cache: "Checking cache",
  retrieve: "Finding tables",
  generate: "Writing SQL",
  validate: "Validating",
  execute: "Running",
};

/** `cache` only appears when the API has a cache and the question passed the input guard. */
const ALWAYS_SHOWN: StageName[] = ["input_guard", "retrieve", "generate", "validate", "execute"];
const ORDER: StageName[] = ["input_guard", "cache", "retrieve", "generate", "validate", "execute"];

export function initialSteps(): Step[] {
  return ALWAYS_SHOWN.map((stage) => ({
    stage,
    label: STAGE_LABELS[stage],
    status: "pending",
    attempt: 1,
    latencyMs: null,
    message: null,
  }));
}

/** Apply one stream event; returns a new array (state stays immutable). */
export function applyEvent(steps: Step[], event: StageEvent): Step[] {
  let next = steps.some((s) => s.stage === event.stage) ? steps : insert(steps, event.stage);
  if (event.type === "stage_started" && event.stage === "generate" && event.attempt > 1) {
    // A retry: the later stages run again for the new attempt.
    next = next.map((s) =>
      s.stage === "validate" || s.stage === "execute"
        ? { ...s, status: "pending", attempt: event.attempt, latencyMs: null, message: null }
        : s,
    );
  }
  return next.map((s) => {
    if (s.stage !== event.stage) return s;
    switch (event.type) {
      case "stage_started":
        return { ...s, status: "running", attempt: event.attempt, latencyMs: null, message: null };
      case "stage_done":
        return { ...s, status: "done", attempt: event.attempt, latencyMs: event.latency_ms };
      case "error":
        return {
          ...s,
          status: "error",
          attempt: event.attempt,
          latencyMs: event.latency_ms,
          message: event.message,
        };
    }
  });
}

/** The answer is in: stages that never ran were skipped (cache hit, blocked, ...). */
export function finishSteps(steps: Step[], answer: Answer): Step[] {
  return steps.map((s) => {
    if (s.status === "pending" || s.status === "running") {
      return { ...s, status: "skipped", message: skipReason(s.stage, answer) };
    }
    return s;
  });
}

function skipReason(stage: StageName, answer: Answer): string | null {
  if (answer.cache && (stage === "retrieve" || stage === "generate")) return "Reused from the cache";
  if (answer.cache === "exact" && stage === "execute") return "Rows reused from the cache";
  return null;
}

function insert(steps: Step[], stage: StageName): Step[] {
  const step: Step = {
    stage,
    label: STAGE_LABELS[stage],
    status: "pending",
    attempt: 1,
    latencyMs: null,
    message: null,
  };
  const all = [...steps, step];
  return all.sort((a, b) => ORDER.indexOf(a.stage) - ORDER.indexOf(b.stage));
}
