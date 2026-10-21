# Performance

Measured on 2026-10-21 on the development laptop: Docker Desktop, 8 vCPUs, 4 GB for the VM,
postgres, redis and one API container (one uvicorn worker). Two kinds of numbers, never mixed:

- **System numbers (fake LLM mode):** the whole stack under load, with the LLM replaced by
  recorded answers and realistic delays (`LLM_FAKE_MODE`, see below). They measure our code,
  Postgres and Redis, not a provider, and spend no quota.
- **Real-LLM numbers:** a few questions, one at a time, on the free tiers. They measure what a
  user waits for, provider included.

Targets: p95 < 6 s for an uncached real question, < 300 ms for a cached one.

## Where the time went (before)

Per-stage timings from the traces (the same numbers Langfuse and `/metrics` show), with the
configured main model `gemini/gemini-3.8-flash`:

| Question | Total | input_guard | cache | retrieve | generate | validate + execute |
|---|---|---|---|---|---|---|
| uncached, first call (cold model) | 36.2 s | 1.5 s | 0.45 s | 1.5 s | **32.6 s** | 0.06 s |
| uncached | 11.3 s | 0.7 s | 0.33 s | 0.01 s | **10.0 s** | 0.2 s |
| exact cache hit | 0.80 s | **0.78 s** | 0.003 s | - | - | 0.003 s |

SQL generation is 85-90% of an uncached question; everything else is 1.5-2.5 s, mostly the
LLM classifier and the embedding lookup, one after the other. A cached answer was almost
entirely the classifier.

## What changed

| Change | Where | Effect |
|---|---|---|
| Layer-1 rules first; an **exact cache hit skips the LLM classifier** (only answers that passed it are stored; the classifier prompt version is part of the key) | `pipeline/orchestrator.py`, `cache/keys.py` | cached: 0.8 s -> 0.02 s |
| On a miss, the **classifier runs concurrently** with the semantic lookup and retrieval; generation still waits for the verdict, a block cancels the rest | `pipeline/orchestrator.py` | hides 0.3-0.8 s behind the classifier |
| Static prompt parts first (system prompt, then schema, examples, question last), so the providers' automatic prefix caching applies; cached prompt tokens are now recorded | `pipeline/generate.py` (test), `llm/provider.py` | `t2s_llm_cached_tokens_total`, `input_cached_tokens` in Langfuse |
| One aiohttp session for every completion (keep-alive pool) | `llm/http.py`, `api/services.py` | no TLS handshake per call |
| Pool sizes configurable: `CATALOG_POOL_SIZE` 5 -> 10, `REDIS_MAX_CONNECTIONS` 50, `EXECUTOR_POOL_SIZE` 5 | `config/settings.py` | no pool waits at 50 VUs |
| Fake LLM mode for load tests | `llm/fake.py` | load tests without quota |

The generation prompts already had the static parts first: they were not changed.

## System numbers (fake LLM mode, k6)

`load/query.js`: ramp to 50 virtual users (1 min to 10, 1.5 min to 50, 3 min at 50), mixed
questions: 60% recorded gold/example questions (mostly cache hits once seen), 15% a small hot
set, 15% attacks stopped by the input rules, 10% unrecorded questions. Fake delays: classifier
0.6 s, generator 2.5 s, embedding 0.15 s (+-25%). "Before" is the previous commit (dfbd793)
with only the fake LLM layer added and the old pool size, so the difference is the pipeline.

| Metric | Before | After |
|---|---|---|
| Throughput | 56.5 req/s | **89.7 req/s** (+59%) |
| Error rate | 0.00% | 0.00% |
| All requests p50 / p95 / p99 | 661 / 913 / 1,490 ms | **385 / 806 / 1,060 ms** |
| Exact cache hits p50 / p95 | 689 / 908 ms | 413 / 825 ms |
| Rule-blocked attacks p50 / p95 | 34 / 145 ms | 194 / 440 ms |

At 50 VUs one API process is CPU-bound at about 90 requests/s (validation is 4 ms per query,
the rest is JWT, Redis round trips, the query log and SSE), so requests queue: a cache hit
answers in 20 ms alone but waits 0.4 s at that load, and attacks wait in the same queue. The
answer is more processes, not faster code: Container Apps adds replicas under HTTP load (max
3, each with its own `/metrics`). More uvicorn workers in one container would need the
Prometheus multiprocess mode.

## Real-LLM numbers

`load/real_run.py`: 20 gold-subset questions, concurrency 1, 8 s apart (two LLM calls per
question; the free tier allows about 15 requests a minute), then 5 repeats. Main and fast
model `gemini/gemini-3.5-flash-lite`, Groq fallback off (it would spend the running
evaluation's quota). The configured `gemini-3.8-flash` allows 20 requests a day, too few for
this run.

| Metric | Before | After |
|---|---|---|
| Uncached p50 / p95 | 9.3 / 17.6 s | **2.6 / 5.3 s** (target < 6 s) |
| Cached p50 / p95 | 871 / 3,899 ms | **24 / 30 ms** (target < 300 ms) |
| Error rate | 0% | 0% |

The uncached "before" run is dominated by provider latency spikes during that run (single
classifier calls of 10 s; median stage times were close to "after": generate 1.9 vs 1.6 s,
classifier 1.0 vs 0.8 s), so treat that comparison as noisy. What the code gains for an
uncached question is the cache lookup and retrieval moved under the classifier (0.3-0.8 s);
the cached gain is structural.

With `gemini-3.8-flash` as main model, uncached questions take 11-36 s (generation alone 10-33
s): the latency target is met only with a faster main model such as `gemini-3.5-flash-lite`,
whose accuracy has not been evaluated yet. Choosing the main model is a configuration change
(`LLM_MODEL_MAIN`), to decide on accuracy and quota, not code.

## Reproduce

See `load/README.md`. Raw summaries: `load/results/*.json`.
