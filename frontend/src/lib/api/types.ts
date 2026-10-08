/**
 * The API's wire format, as zod schemas (validated at runtime) and inferred types.
 * Mirrors backend/src/text2sql/api/routes and pipeline/events.py.
 */
import { z } from "zod";

export const STAGE_NAMES = [
  "input_guard",
  "cache",
  "retrieve",
  "generate",
  "validate",
  "execute",
] as const;
export const stageName = z.enum(STAGE_NAMES);
export type StageName = z.infer<typeof stageName>;

export const ANSWER_STATUSES = [
  "answered",
  "cannot_answer",
  "blocked",
  "rejected",
  "failed",
] as const;
export type AnswerStatus = (typeof ANSWER_STATUSES)[number];

export const tokenResponse = z.object({
  access_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
});
export type TokenResponse = z.infer<typeof tokenResponse>;

export const errorBody = z.object({
  code: z.string(),
  message: z.string(),
  request_id: z.string().nullable(),
});
export const errorResponse = z.object({ error: errorBody });
export type ErrorBody = z.infer<typeof errorBody>;

export const stageStarted = z.object({
  type: z.literal("stage_started"),
  stage: stageName,
  attempt: z.number().int(),
});
export const stageDone = z.object({
  type: z.literal("stage_done"),
  stage: stageName,
  attempt: z.number().int(),
  latency_ms: z.number(),
});
export const stageError = z.object({
  type: z.literal("error"),
  stage: stageName,
  attempt: z.number().int(),
  latency_ms: z.number(),
  error: z.string(),
  message: z.string(),
  retryable: z.boolean(),
});
export const stageEvent = z.discriminatedUnion("type", [stageStarted, stageDone, stageError]);
export type StageEvent = z.infer<typeof stageEvent>;

/** Any JSON value a result cell can hold. */
export type Cell = string | number | boolean | null | Cell[] | { [key: string]: Cell };
const cell: z.ZodType<Cell> = z.lazy(() =>
  z.union([
    z.string(),
    z.number(),
    z.boolean(),
    z.null(),
    z.array(cell),
    z.record(z.string(), cell),
  ]),
);

export const resultColumn = z.object({ name: z.string(), type: z.string() });
export type ResultColumn = z.infer<typeof resultColumn>;

export const stageTiming = z.object({
  stage: stageName,
  attempt: z.number().int(),
  status: z.enum(["ok", "error"]),
  latency_ms: z.number(),
  tokens: z.number().int(),
  cost_usd: z.number().nullable(),
});
export type StageTiming = z.infer<typeof stageTiming>;

export const GUARDRAIL_LAYERS = [
  "input_rules",
  "input_classifier",
  "sql_validator",
  "database",
] as const;
export const guardrail = z.object({ layer: z.enum(GUARDRAIL_LAYERS), code: z.string() });
export type Guardrail = z.infer<typeof guardrail>;
export type GuardrailLayer = Guardrail["layer"];

export const answer = z.object({
  query_id: z.string().uuid(),
  status: z.enum(ANSWER_STATUSES),
  message: z.string(),
  sql: z.string().nullable(),
  explanation: z.string().nullable(),
  assumptions: z.array(z.string()),
  columns: z.array(resultColumn),
  rows: z.array(z.array(cell)),
  row_count: z.number().int(),
  truncated: z.boolean(),
  attempts: z.number().int(),
  cache: z.enum(["exact", "semantic"]).nullable(),
  guardrail: guardrail.nullable(),
  timings: z.object({ total_ms: z.number(), stages: z.array(stageTiming) }),
  tokens: z.number().int(),
  cost_usd: z.number().nullable(),
});
export type Answer = z.infer<typeof answer>;

export const queryStarted = z.object({ query_id: z.string().uuid() });

export const feedbackRequest = z.object({
  query_id: z.string().uuid(),
  rating: z.number().int().min(1).max(5),
  comment: z.string().max(2000).nullable(),
});
export type FeedbackRequest = z.infer<typeof feedbackRequest>;
export const feedbackResponse = z.object({ feedback_id: z.number().int() });

/** What `ask` reports while the answer streams in. */
export type ProgressEvent = { type: "query"; queryId: string } | StageEvent;
