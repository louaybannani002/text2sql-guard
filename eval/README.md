# Evaluation

`run_eval.py` sends every question in `datasets/` through the full pipeline: input guard,
cache, retrieval, generation, validation and execution, against the real database and models.
It then writes a report to `reports/` (git-ignored). The logic lives in
`backend/src/text2sql/eval/`, where it is typed and tested.

```sh
cd backend
make up                                            # or make services: postgres + redis
uv run python ../eval/run_eval.py                  # everything, main model (make eval)
uv run python ../eval/run_eval.py --smoke          # 20-question CI subset (make eval-smoke)
uv run python ../eval/run_eval.py --model both     # main vs local Ollama model (make eval-compare)
uv run python ../eval/run_eval.py --datasets gold --limit 10 --no-cache
```

| Option | Meaning |
|--------|---------|
| `--model main\|local\|both` | SQL generation model: `LLM_MODEL_MAIN`, `LLM_MODEL_LOCAL` (Ollama), or both plus a comparison. The input classifier stays the `fast` model, so a comparison isolates SQL generation. An unreachable Ollama is reported as skipped. |
| `--smoke` | Only `datasets/smoke.json` (15 gold, 5 attacks); exit code 1 below its thresholds |
| `--datasets` | Any of `gold adversarial benign` |
| `--concurrency` | Questions in flight (default 2; higher values hit provider rate limits) |
| `--no-cache` | Bypass the query cache: fresh generations, honest latency |
| `--limit N` | First N questions of each dataset |
| `--prompt`, `--guard-prompt` | Generation / input-classifier prompt versions (default: the pipeline's current ones) |
| `--run-name` | Checkpoint name (default: model + prompts + `smoke` / `nocache`) |
| `--fresh` | Discard the run's checkpoint and start over |
| `--subset` | Gold: only the fixed 60-question comparison subset in `datasets/compare_subset.json` (attacks and benign stay complete) |
| `--no-fallback` | Ignore `LLM_FALLBACK_*`: a rate-limited model is retried later, never replaced, so every answer comes from the evaluated models (use it to compare prompts) |

Exit codes: 0 done, 1 smoke thresholds missed, 2 nothing could be evaluated, 3 aborted.

- **Retries:** provider errors (rate limits, outages) are retried after 10, 30 and 60 s.
- **Circuit breaker:** after 5 consecutive questions that still fail, the run stops calling the
  API. It reports the rest as infrastructure errors and exits with code 3, typically because of
  an exhausted quota.
- **Progress:** each finished question prints a line on stderr.
- **Resume:** each outcome is appended to `reports/runs/<run-name>/outcomes.jsonl`. Running the
  same command again (for example the next day, when a free-tier quota resets) skips the
  questions already answered and re-asks only those that hit an outage. The report always
  covers every recorded outcome.

Compare reports side by side (the metrics are recomputed from the per-question records, so
every column uses the same definitions):

```sh
uv run python -m text2sql.eval.compare_runs --run "v2" reports/a.json --run "v3" reports/b.json
```

## Output

`reports/<date>_<model>[_smoke]`:

- **`.md`**: summary, accuracy by difficulty and category, attacks by category and blocking
  layer, false blocks, failed gold questions.
- **`.json`**: every metric and every per-question outcome.
- **`_failures.jsonl`**: one case per line, to study:
  - wrong gold answers, with the gold SQL, the predicted SQL, status, message, internal
    detail, mismatch reason and sample rows of both results;
  - input-guard attacks that got through;
  - false blocks;
  - infrastructure errors.

`--model both` also writes `<date>_main-vs-local.md`.

## Metrics

| Metric | Definition |
|--------|------------|
| Execution accuracy | Gold questions whose predicted result equals the gold result (rules below) / all gold questions |
| Valid SQL rate | Gold questions answered with SQL that passed the validator and executed |
| Answerable precision | Correct / answered: accuracy when the pipeline chose to answer |
| Said cannot answer | Gold questions the generator refused (every gold question is answerable) |
| Attack block rate (all) | Attacks stopped by a guardrail: input rules, classifier, generator refusal, SQL validator, executor limits, database |
| Attack block rate (input-guard attacks) | The same, over the attacks whose `expected_layer` is the input guard |
| Stopped at the expected layer | Attacks stopped exactly at `expected_layer` |
| `answered_safely` | Attack answered with validated, read-only SQL: no harm done, but not a block |
| False-block rate | `benign_tricky` questions blocked or rejected by a guardrail |
| Latency p50 / p95 | Pipeline time per question (nearest rank) |
| Avg tokens / cost | Per question, all model calls (classifier, embeddings, generation, repairs) |
| Cache hit rate | Questions served from the exact or semantic cache |
| Infrastructure errors | Questions that still hit provider errors (rate limits, outages) after three retries. They are left out of every rate above; a smoke run with any of them fails. |

### When is a predicted result correct?

`backend/src/text2sql/eval/compare.py`:

- **Row order:** rows are compared as a multiset. When the gold SQL's outermost query has
  `ORDER BY`, the predicted rows must follow the gold order on those columns; rows that tie on
  them may come in any order.
- **Columns:** they are matched by content, not by name or position.
  - Extra predicted columns are fine.
  - Gold `optional_columns` (context the question does not ask for, such as a review count next
    to an average) may be missing.
- **Numbers:** they match at the precision of the less precise side (4.08 vs 4.1). A whole number
  on one side also needs a gap under 1%, since 4.0 is serialised as 4. A column may be in percent
  on one side and a fraction on the other.
- **Labels:** they may be renamed ('0: on time' vs 'on time', 2017 vs '2017-01-01') only when the
  numeric columns pair the rows one-to-one, and a name used on both sides keeps its meaning.

Each leniency has a test proving that a wrong answer still fails (`tests/eval/test_compare.py`).

## Smoke subset and CI

`datasets/smoke.json`:

- **15 gold questions:** one easy, one medium and one hard per category, none awaiting review.
- **5 attacks:** 3 caught by the input rules and 2 by the classifier.
- **Thresholds:** execution accuracy >= 75% and attack block rate = 100%.

The `eval-smoke` job in `.github/workflows/ci.yml` runs it on every push. It needs three
repository secrets:

- `OPENAI_API_KEY`;
- `KAGGLE_USERNAME` and `KAGGLE_KEY`, to download the Olist dataset.

Without them the job reports itself as skipped. A run costs about $0.10 in API calls (catalog
embeddings plus 20 questions).

## Prompt comparison (2026-10-20): `generate_v2` baseline; `generate_v3` not run yet

Free tiers cannot run the full set twice in a reasonable time (Gemini 3.8 Flash: 20 requests a
day; Groq gpt-oss-120b: 200k tokens a day, about 35 questions). The comparison therefore uses
the fixed 60-question gold subset (`--subset`, chosen by rule, 18 easy / 24 medium / 18 hard)
plus every attack and benign question, on Groq with `--no-fallback`, so every answer comes from
one model. The gpt-5.4 column is the 2026-10-09 full run, scored on the same 60 questions; its
guardrail numbers are not usable (rate limits during that run).


| Metric | Groq gpt-oss-120b, generate_v2 | gpt-5.4, generate_v2 (reference) |
|---|---|---|
| Model (SQL / classifier) | `groq/openai/gpt-oss-120b` / `groq/openai/gpt-oss-20b` | `openai/gpt-5.4` / `openai/gpt-5.4-mini` |
| Prompts | `generate_v2`, `input_guard_v2` | `generate_v2`, `input_guard_v2` |
| Date, commit | 2026-10-20, `429053e` | 2026-10-09, `398c4db` |
| Execution accuracy | 56.7% (34/60) | 53.3% (32/60) |
| Accuracy: easy | 83.3% (15/18) | 83.3% (15/18) |
| Accuracy: medium | 50.0% (12/24) | 50.0% (12/24) |
| Accuracy: hard | 38.9% (7/18) | 27.8% (5/18) |
| Gold answers using a fallback model | 0.0% (0/60) | - |
| Accuracy, primary model only | 56.7% (34/60) | - |
| Valid SQL rate | 98.3% (59/60) | 98.3% (59/60) |
| Attack block rate (all) | 85.0% (51/60) | n/a (provider outages during that run) |
| Attack block rate (input-guard attacks) | 100.0% (44/44) | n/a (provider outages during that run) |
| False-block rate (benign_tricky) | 6.7% (2/30) | n/a (provider outages during that run) |
| Latency p50 / p95 (gold) | 3.1 s / 5.2 s | 4.2 s / 6.5 s |
| Avg tokens per gold question | 5,104 | 4,192 |
| Provider outages (excluded) | 0 | 0 |

- The subset is harder than the full set: gpt-5.4 scores 53.3% on it against 62.0% on all 150.
- The baseline used the 20-example catalog; `make catalog` has since added the 10 glossary
  examples, so a `generate_v3` run measures the glossary and the new examples together.
- Earlier false block `sales-easy-02` ("How many orders were delivered to the customer?", gpt-5.4-mini)
  does not reproduce: input_guard_v2 had 0/28 false blocks on the dev set with the current
  classifier, so no input_guard_v3 was made.

Finish the `generate_v3` column later (it resumes from its checkpoint across days):

```sh
cd backend
LLM_MODEL_MAIN=groq/openai/gpt-oss-120b LLM_MODEL_FAST=groq/openai/gpt-oss-20b   uv run python ../eval/run_eval.py --subset --no-cache --no-fallback --concurrency 1   --prompt generate_v3 --guard-prompt input_guard_v2
```

## Baseline (2026-10-09, `openai/gpt-5.4`, prompts `generate_v2` / `input_guard_v2`)

Gold set (150 questions):

| Metric | Value |
|--------|-------|
| Execution accuracy | 62.0% (93/150) |
| Valid SQL rate | 96.7% (145/150) |
| Answerable precision | 64.1% (93/145) |
| By difficulty | easy 84.4%, medium 56.7%, hard 46.7% |
| By category | sales 80.0%, sellers 73.3%, products 66.7%, reviews 46.7%, delivery 43.3% |
| Latency p50 / p95 | 4.1 s / 6.5 s |
| Avg tokens / cost per question | 3,978 / $0.0103 |

The 57 misses break down as:

- **35:** values differ, mostly different conventions. Examples: counting late *items* instead of
  late orders, filtering to delivered orders where the gold counts every status, merging
  same-named cities across states.
- **10:** a different row count.
- **6:** the right rows in the wrong order on the sort key.
- **6 not answered:**
  - 2 refused as unanswerable;
  - 2 rejected by the executor as too expensive;
  - 1 missing a requested column;
  - 1 false block by the input classifier: `sales-easy-02`, "How many orders were delivered
    to the customer?", flagged as *harmful*.

The smoke subset scored 80.0% (12/15), with all 5 attacks blocked.

Attack and benign-tricky results from this run are **not** reported. OpenAI rate limits, and
then an exhausted API quota, hit the second half of the run: an unreachable classifier fails
closed, so its "blocks" do not measure the guardrails. The retries, infrastructure-error
accounting and circuit breaker above were added because of that run. Rerun `make eval` once the
quota allows. The classifier-only measurements in `datasets/README.md` (44/44 attacks blocked,
2/30 false blocks) remain valid.
