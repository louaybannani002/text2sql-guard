# Load and latency tests

Results and analysis: `docs/performance.md`. Raw summaries: `results/`.

## System load test (fake LLM mode, no quota spent)

```sh
# From the repository root. Start the API in fake LLM mode (recorded SQL, realistic delays):
docker compose -f docker-compose.yml -f load/compose.fake.yml --env-file backend/.env up -d --wait api
# k6 in a container on the compose network; it reads DEMO_USERNAME / DEMO_PASSWORD from .env:
docker run --rm --network text2sql-guard_default -v "$PWD:/work" -w /work \
  --env-file backend/.env -e API=http://api:8000 \
  grafana/k6 run --summary-export load/results/fake.json load/query.js
# Back to the normal API:
docker compose -f docker-compose.yml --env-file backend/.env up -d --wait api
```

Fake mode (`LLM_FAKE_MODE=true`) is never on by default and refused with
`APP_ENV=production`. Its model names get a `fake/` prefix, so its cache entries never mix
with real ones. Recorded SQL: `backend/src/text2sql/llm/fake_recordings.json`, rebuilt with
`uv run python -m text2sql.eval.fake_recordings` (a test fails when it is out of date).

## Real-LLM latency run (spends free-tier quota: keep it small)

```sh
docker compose -f docker-compose.yml -f load/compose.real-run.yml --env-file backend/.env up -d --wait api
cd backend && uv run python ../load/real_run.py --n 20 --pause 8 --out ../load/results/real.json
```

One question at a time, 8 s apart (two LLM calls per question, ~15 requests a minute on the
free tier). Use `--offset` to pick questions that are not cached yet.
