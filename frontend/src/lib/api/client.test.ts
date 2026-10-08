import {
  QUERY_ID,
  STAGE_EVENTS,
  TOKEN,
  errorJson,
  fakeFetch,
  jsonResponse,
  makeAnswer,
  sseBody,
  streamResponse,
} from "@/test/fixtures";

import { ApiClient, ApiError } from "./client";
import type { ProgressEvent } from "./types";

function client(fetchImpl: typeof fetch, token: string | null = "tkn", onUnauthorized = vi.fn()) {
  return {
    api: new ApiClient({ baseUrl: "http://api.test/", getToken: () => token, onUnauthorized, fetch: fetchImpl }),
    onUnauthorized,
  };
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected an ApiError");
}

describe("login", () => {
  it("posts the credentials without a token and validates the response", async () => {
    const { fetch, calls } = fakeFetch({ "POST /v1/auth/token": () => jsonResponse(200, TOKEN) });
    const { api } = client(fetch, null);
    await expect(api.login("demo", "pw")).resolves.toEqual(TOKEN);
    expect(calls[0]?.url).toBe("http://api.test/v1/auth/token");
    expect(calls[0]?.body).toEqual({ username: "demo", password: "pw" });
    expect(calls[0]?.headers.authorization).toBeUndefined();
  });

  it("does not sign the user out on a failed login", async () => {
    const { fetch } = fakeFetch({
      "POST /v1/auth/token": () => errorJson(401, "unauthorized", "Invalid username or password."),
    });
    const { api, onUnauthorized } = client(fetch, null);
    const error = await rejection(api.login("demo", "nope"));
    expect([error.status, error.message]).toEqual([401, "Invalid username or password."]);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe("ask", () => {
  it("streams progress events and returns the validated answer", async () => {
    const answer = makeAnswer();
    const body = sseBody([["query", { query_id: QUERY_ID }], ...STAGE_EVENTS, ["answer", answer]]);
    const { fetch, calls } = fakeFetch({ "POST /v1/query": () => streamResponse(body, 7) });
    const events: ProgressEvent[] = [];

    const result = await client(fetch).api.ask("Orders?", { onEvent: (e) => events.push(e) });

    expect(result).toEqual(answer);
    expect(events[0]).toEqual({ type: "query", queryId: QUERY_ID });
    expect(events.slice(1).map((e) => e.type)).toEqual(Array(5).fill(["stage_started", "stage_done"]).flat());
    expect(calls[0]?.headers.authorization).toBe("Bearer tkn");
    expect(calls[0]?.headers.accept).toBe("text/event-stream");
    expect(calls[0]?.body).toEqual({ question: "Orders?" });
  });

  it("turns a server_error event into an ApiError with the request id", async () => {
    const body = sseBody([
      ["query", { query_id: QUERY_ID }],
      ["server_error", { error: { code: "internal_error", message: "Something went wrong.", request_id: "abc" } }],
    ]);
    const { fetch } = fakeFetch({ "POST /v1/query": () => streamResponse(body) });
    const error = await rejection(client(fetch).api.ask("q"));
    expect([error.status, error.code, error.requestId]).toEqual([500, "internal_error", "abc"]);
  });

  it("fails clearly when the stream ends without an answer", async () => {
    const body = sseBody([["query", { query_id: QUERY_ID }]]);
    const { fetch } = fakeFetch({ "POST /v1/query": () => streamResponse(body) });
    expect((await rejection(client(fetch).api.ask("q"))).code).toBe("stream_ended");
  });

  it("rejects an answer that does not match the schema", async () => {
    const body = sseBody([["answer", { ...makeAnswer(), status: "maybe" }]]);
    const { fetch } = fakeFetch({ "POST /v1/query": () => streamResponse(body) });
    expect((await rejection(client(fetch).api.ask("q"))).code).toBe("bad_response");
  });

  it("reports rate limits with Retry-After", async () => {
    const { fetch } = fakeFetch({
      "POST /v1/query": () => errorJson(429, "rate_limited", "Too many requests.", { "Retry-After": "42" }),
    });
    const error = await rejection(client(fetch).api.ask("q"));
    expect([error.status, error.code, error.retryAfterS]).toEqual([429, "rate_limited", 42]);
  });

  it("signs the user out on a 401", async () => {
    const { fetch } = fakeFetch({
      "POST /v1/query": () => errorJson(401, "unauthorized", "Invalid or expired token."),
    });
    const { api, onUnauthorized } = client(fetch);
    expect((await rejection(api.ask("q"))).status).toBe(401);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("does not call the API without a token", async () => {
    const { fetch, calls } = fakeFetch({});
    const { api, onUnauthorized } = client(fetch, null);
    expect((await rejection(api.ask("q"))).status).toBe(401);
    expect(calls).toEqual([]);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("explains network failures", async () => {
    const failing = (() => Promise.reject(new TypeError("Failed to fetch"))) as typeof fetch;
    const error = await rejection(client(failing).api.ask("q"));
    expect(error.code).toBe("network_error");
    expect(error.message).toContain("http://api.test");
  });

  it("lets aborts through untouched", async () => {
    const aborting = (() => Promise.reject(new DOMException("aborted", "AbortError"))) as typeof fetch;
    await expect(client(aborting).api.ask("q")).rejects.toMatchObject({ name: "AbortError" });
  });

  it("copes with a non-JSON error body", async () => {
    const { fetch } = fakeFetch({ "POST /v1/query": () => new Response("Bad gateway", { status: 502 }) });
    const error = await rejection(client(fetch).api.ask("q"));
    expect([error.status, error.code]).toEqual([502, "http_502"]);
  });
});

describe("sendFeedback", () => {
  it("posts the rating and returns the feedback id", async () => {
    const { fetch, calls } = fakeFetch({ "POST /v1/feedback": () => jsonResponse(201, { feedback_id: 7 }) });
    const feedback = { query_id: QUERY_ID, rating: 5, comment: null };
    await expect(client(fetch).api.sendFeedback(feedback)).resolves.toBe(7);
    expect(calls[0]?.body).toEqual(feedback);
    expect(calls[0]?.headers.authorization).toBe("Bearer tkn");
  });
});
