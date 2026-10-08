/** Test data and a scripted fake `fetch` that speaks the API's wire format. */
import type { Answer } from "@/lib/api/types";

export const QUERY_ID = "0785e893-0127-4c24-9f0c-eae4e2be462d";

export function makeAnswer(overrides: Partial<Answer> = {}): Answer {
  return {
    query_id: QUERY_ID,
    status: "answered",
    message: "Counts orders by status.",
    sql: "SELECT o.order_status, count(*) AS orders\nFROM shop.orders AS o\nGROUP BY 1\nLIMIT 1000",
    explanation: "Counts orders by status.",
    assumptions: ["All statuses count."],
    columns: [
      { name: "order_status", type: "text" },
      { name: "orders", type: "int8" },
    ],
    rows: [
      ["delivered", 96478],
      ["shipped", 1107],
      ["canceled", 625],
    ],
    row_count: 3,
    truncated: false,
    attempts: 1,
    cache: null,
    guardrail: null,
    timings: {
      total_ms: 5652,
      stages: [
        { stage: "input_guard", attempt: 1, status: "ok", latency_ms: 2038, tokens: 120, cost_usd: 0.0001 },
        { stage: "retrieve", attempt: 1, status: "ok", latency_ms: 438, tokens: 9, cost_usd: 0 },
        { stage: "generate", attempt: 1, status: "ok", latency_ms: 1918, tokens: 3600, cost_usd: 0.0095 },
        { stage: "validate", attempt: 1, status: "ok", latency_ms: 4, tokens: 0, cost_usd: 0 },
        { stage: "execute", attempt: 1, status: "ok", latency_ms: 99, tokens: 0, cost_usd: 0 },
      ],
    },
    tokens: 3729,
    cost_usd: 0.0096,
    ...overrides,
  };
}

export type SseEvent = [event: string, data: unknown];

export const STAGE_EVENTS: SseEvent[] = (
  ["input_guard", "retrieve", "generate", "validate", "execute"] as const
).flatMap((stage) => [
  ["stage_started", { type: "stage_started", stage, attempt: 1 }],
  ["stage_done", { type: "stage_done", stage, attempt: 1, latency_ms: 10 }],
]);

export function sseBody(events: SseEvent[]): string {
  return events
    .map(([event, data], id) => `event: ${event}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
}

/** A streamed response that delivers `body` in small chunks (splitting lines and events). */
export function streamResponse(body: string, chunkSize = 37, headers: Record<string, string> = {}): Response {
  const bytes = new TextEncoder().encode(body);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) controller.enqueue(bytes.slice(i, i + chunkSize));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream", "X-Request-ID": "req-1", ...headers },
  });
}

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "req-1", ...headers },
  });
}

export function errorJson(status: number, code: string, message: string, headers: Record<string, string> = {}): Response {
  return jsonResponse(status, { error: { code, message, request_id: "req-1" } }, headers);
}

export interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: Call) => Response | Promise<Response>;

/** `fetch` replacement routing by "METHOD /path"; records every call. */
export function fakeFetch(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const impl = async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));
    const method = init.method ?? "GET";
    const call: Call = {
      url: url.toString(),
      method,
      headers: Object.fromEntries(new Headers(init.headers).entries()),
      body: typeof init.body === "string" ? JSON.parse(init.body) : null,
    };
    calls.push(call);
    const handler = routes[`${method} ${url.pathname}`];
    if (!handler) throw new Error(`unexpected request ${method} ${url.pathname}`);
    return handler(call);
  };
  return { fetch: impl as typeof fetch, calls };
}

export const TOKEN = { access_token: "header.payload.signature", token_type: "bearer", expires_in: 900 };
