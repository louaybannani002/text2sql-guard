import { makeAnswer } from "@/test/fixtures";

import type { StageEvent } from "./api/types";
import { applyEvent, finishSteps, initialSteps, type Step } from "./stages";

function run(events: StageEvent[]): Step[] {
  return events.reduce(applyEvent, initialSteps());
}

const status = (steps: Step[]) => Object.fromEntries(steps.map((s) => [s.stage, s.status]));

describe("stage progress", () => {
  it("starts with the five user-facing stages pending", () => {
    expect(initialSteps().map((s) => s.label)).toEqual([
      "Checking input",
      "Finding tables",
      "Writing SQL",
      "Validating",
      "Running",
    ]);
  });

  it("tracks running, done and errors with their message", () => {
    const steps = run([
      { type: "stage_done", stage: "input_guard", attempt: 1, latency_ms: 12 },
      { type: "stage_started", stage: "retrieve", attempt: 1 },
    ]);
    expect(status(steps)).toMatchObject({ input_guard: "done", retrieve: "running", generate: "pending" });
    expect(steps[0]?.latencyMs).toBe(12);

    const failed = applyEvent(steps, {
      type: "error",
      stage: "retrieve",
      attempt: 1,
      latency_ms: 3,
      error: "CatalogNotBuiltError",
      message: "The data catalog is not ready.",
      retryable: false,
    });
    expect(failed[1]).toMatchObject({ status: "error", message: "The data catalog is not ready." });
  });

  it("inserts the cache stage in pipeline order when it appears", () => {
    const steps = run([{ type: "stage_started", stage: "cache", attempt: 1 }]);
    expect(steps.map((s) => s.stage)).toEqual([
      "input_guard",
      "cache",
      "retrieve",
      "generate",
      "validate",
      "execute",
    ]);
  });

  it("resets later stages when the SQL is regenerated", () => {
    const steps = run([
      { type: "stage_done", stage: "generate", attempt: 1, latency_ms: 5 },
      {
        type: "error",
        stage: "validate",
        attempt: 1,
        latency_ms: 1,
        error: "rejected:columns",
        message: "Unknown column.",
        retryable: true,
      },
      { type: "stage_started", stage: "generate", attempt: 2 },
    ]);
    expect(steps.find((s) => s.stage === "generate")).toMatchObject({ status: "running", attempt: 2 });
    expect(steps.find((s) => s.stage === "validate")).toMatchObject({
      status: "pending",
      attempt: 2,
      message: null,
    });
  });

  it("marks stages that never ran as skipped, explaining cache hits", () => {
    const steps = run([
      { type: "stage_done", stage: "input_guard", attempt: 1, latency_ms: 5 },
      { type: "stage_done", stage: "cache", attempt: 1, latency_ms: 5 },
      { type: "stage_done", stage: "validate", attempt: 0, latency_ms: 1 },
    ]);
    const finished = finishSteps(steps, makeAnswer({ cache: "exact" }));
    expect(status(finished)).toMatchObject({ retrieve: "skipped", generate: "skipped", execute: "skipped" });
    expect(finished.find((s) => s.stage === "execute")?.message).toBe("Rows reused from the cache");
  });
});
