import { ApiError } from "@/lib/api/client";
import { makeAnswer } from "@/test/fixtures";

import { askReducer, type AskState } from "./use-ask";

const started = askReducer({ phase: "idle" }, { type: "start", run: 1, question: "q", at: 0 });

describe("askReducer", () => {
  it("records the query id and stage progress for the current run", () => {
    let state: AskState = askReducer(started, { type: "event", run: 1, event: { type: "query", queryId: "id-1" } });
    state = askReducer(state, {
      type: "event",
      run: 1,
      event: { type: "stage_started", stage: "input_guard", attempt: 1 },
    });
    expect(state).toMatchObject({ phase: "running", queryId: "id-1" });
    expect(state.phase !== "idle" && state.steps[0]?.status).toBe("running");
  });

  it("ignores events from an older run", () => {
    const next = askReducer(started, { type: "answer", run: 0, answer: makeAnswer() });
    expect(next).toBe(started);
  });

  it("finishes with the answer, or with an error", () => {
    expect(askReducer(started, { type: "answer", run: 1, answer: makeAnswer() })).toMatchObject({
      phase: "done",
      answer: { status: "answered" },
    });
    const error = new ApiError(429, "rate_limited", "slow down");
    expect(askReducer(started, { type: "error", run: 1, error })).toMatchObject({ phase: "error", error });
  });

  it("resets to idle", () => {
    expect(askReducer(started, { type: "reset" })).toEqual({ phase: "idle" });
  });
});
