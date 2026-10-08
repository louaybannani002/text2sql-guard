/**
 * Typed client for the text2sql-guard API. Every response is validated with zod.
 *
 * The client never stores the access token: it asks `getToken()` (memory only, see
 * AuthProvider) for every request and calls `onUnauthorized()` on a 401.
 */
import { z } from "./zod";

import { SseParser, type SseMessage } from "./sse";
import {
  answer as answerSchema,
  errorResponse,
  feedbackResponse,
  queryStarted,
  stageEvent,
  tokenResponse,
  type Answer,
  type FeedbackRequest,
  type ProgressEvent,
  type TokenResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
    readonly retryAfterS: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  getToken: () => string | null;
  onUnauthorized?: () => void;
  fetch?: typeof fetch;
}

export interface AskOptions {
  onEvent?: (event: ProgressEvent) => void;
  signal?: AbortSignal;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  /** Exchange the demo credentials for a short-lived access token. */
  async login(username: string, password: string): Promise<TokenResponse> {
    const response = await this.send("/v1/auth/token", {
      method: "POST",
      body: JSON.stringify({ username, password }),
      auth: false,
    });
    return parse(tokenResponse, await response.json());
  }

  /** Store a rating (1..5) and optional comment for an answered query (upsert). */
  async sendFeedback(feedback: FeedbackRequest): Promise<number> {
    const response = await this.send("/v1/feedback", {
      method: "POST",
      body: JSON.stringify(feedback),
    });
    return parse(feedbackResponse, await response.json()).feedback_id;
  }

  /** Ask a question; stage events stream to `onEvent`, the final answer is returned. */
  async ask(question: string, { onEvent, signal }: AskOptions = {}): Promise<Answer> {
    const response = await this.send("/v1/query", {
      method: "POST",
      body: JSON.stringify({ question }),
      accept: "text/event-stream",
      signal,
    });
    const requestId = response.headers.get("x-request-id");
    let final: Answer | null = null;
    let failure: ApiError | null = null;

    const handle = (message: SseMessage): void => {
      const data: unknown = JSON.parse(message.data);
      switch (message.event) {
        case "query":
          onEvent?.({ type: "query", queryId: parse(queryStarted, data).query_id });
          break;
        case "stage_started":
        case "stage_done":
        case "error":
          onEvent?.(parse(stageEvent, data));
          break;
        case "answer":
          final = parse(answerSchema, data);
          break;
        case "server_error": {
          const { error } = parse(errorResponse, data);
          failure = new ApiError(500, error.code, error.message, error.request_id ?? requestId);
          break;
        }
        default:
          break; // unknown events are ignored (forward compatible)
      }
    };

    await readStream(response, new SseParser(handle));
    if (failure) throw failure;
    if (!final) {
      throw new ApiError(0, "stream_ended", "The connection closed before the answer arrived.", requestId);
    }
    return final;
  }

  private async send(
    path: string,
    init: { method: string; body?: string; auth?: boolean; accept?: string; signal?: AbortSignal },
  ): Promise<Response> {
    const headers: Record<string, string> = { Accept: init.accept ?? "application/json" };
    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    if (init.auth !== false) {
      const token = this.options.getToken();
      if (!token) {
        this.options.onUnauthorized?.();
        throw new ApiError(401, "unauthorized", "Please sign in again.");
      }
      headers.Authorization = `Bearer ${token}`;
    }

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: init.method,
        headers,
        body: init.body,
        signal: init.signal,
        credentials: "omit", // bearer token only: no cookies, no ambient credentials
        cache: "no-store",
      });
    } catch (error) {
      if (isAbort(error)) throw error;
      throw new ApiError(0, "network_error", `Can't reach the API at ${this.baseUrl}. Is it running?`);
    }
    if (!response.ok) throw await toApiError(response, () => this.options.onUnauthorized?.(), init.auth !== false);
    return response;
  }
}

async function readStream(response: Response, parser: SseParser): Promise<void> {
  if (!response.body) throw new ApiError(0, "stream_ended", "The API sent no response body.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.push(decoder.decode(value, { stream: true }));
  }
  parser.push(decoder.decode());
  parser.end();
}

async function toApiError(
  response: Response,
  onUnauthorized: () => void,
  authenticated: boolean,
): Promise<ApiError> {
  const requestId = response.headers.get("x-request-id");
  const retryAfter = Number(response.headers.get("retry-after"));
  const retryAfterS = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null;
  let code = `http_${response.status}`;
  let message = `The API answered ${response.status}.`;
  const body = errorResponse.safeParse(await response.json().catch(() => null));
  if (body.success) {
    code = body.data.error.code;
    message = body.data.error.message;
  }
  if (response.status === 401 && authenticated) onUnauthorized();
  return new ApiError(response.status, code, message, body.data?.error.request_id ?? requestId, retryAfterS);
}

function parse<T>(schema: z.ZodType<T>, data: unknown): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new ApiError(0, "bad_response", "The API sent a response this app does not understand.");
  }
  return result.data;
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
