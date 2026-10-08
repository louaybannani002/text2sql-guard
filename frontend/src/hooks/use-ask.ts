"use client";

/** Runs one question at a time against the API and tracks its live progress. */
import { useCallback, useEffect, useReducer, useRef } from "react";

import { ApiError, isAbort, type ApiClient } from "@/lib/api/client";
import type { Answer, ProgressEvent } from "@/lib/api/types";
import { applyEvent, finishSteps, initialSteps, type Step } from "@/lib/stages";

export type AskState =
  | { phase: "idle" }
  | {
      phase: "running" | "done" | "error";
      run: number;
      question: string;
      queryId: string | null;
      steps: Step[];
      startedAt: number;
      answer: Answer | null;
      error: ApiError | null;
    };

type Action =
  | { type: "start"; run: number; question: string; at: number }
  | { type: "event"; run: number; event: ProgressEvent }
  | { type: "answer"; run: number; answer: Answer }
  | { type: "error"; run: number; error: ApiError }
  | { type: "reset" };

export function askReducer(state: AskState, action: Action): AskState {
  if (action.type === "reset") return { phase: "idle" };
  if (action.type === "start") {
    return {
      phase: "running",
      run: action.run,
      question: action.question,
      queryId: null,
      steps: initialSteps(),
      startedAt: action.at,
      answer: null,
      error: null,
    };
  }
  // Late events from a cancelled or replaced run are ignored.
  if (state.phase !== "running" || state.run !== action.run) return state;
  switch (action.type) {
    case "event":
      return action.event.type === "query"
        ? { ...state, queryId: action.event.queryId }
        : { ...state, steps: applyEvent(state.steps, action.event) };
    case "answer":
      return {
        ...state,
        phase: "done",
        queryId: action.answer.query_id,
        steps: finishSteps(state.steps, action.answer),
        answer: action.answer,
      };
    case "error":
      return { ...state, phase: "error", error: action.error };
  }
}

export function useAsk(client: ApiClient) {
  const [state, dispatch] = useReducer(askReducer, { phase: "idle" });
  const controller = useRef<AbortController | null>(null);
  const runs = useRef(0);

  const ask = useCallback(
    async (question: string) => {
      controller.current?.abort();
      const current = new AbortController();
      controller.current = current;
      const run = ++runs.current;
      dispatch({ type: "start", run, question, at: Date.now() });
      try {
        const answer = await client.ask(question, {
          signal: current.signal,
          onEvent: (event) => dispatch({ type: "event", run, event }),
        });
        dispatch({ type: "answer", run, answer });
      } catch (error) {
        if (isAbort(error)) return;
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError(0, "unexpected", "Something went wrong in the browser. Please retry.");
        dispatch({ type: "error", run, error: apiError });
      }
    },
    [client],
  );

  const cancel = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    runs.current += 1;
    dispatch({ type: "reset" });
  }, []);

  useEffect(() => () => controller.current?.abort(), []);

  return { state, ask, cancel };
}
