# ruff: noqa: INP001 - a script run with `uv run python ../load/real_run.py`, not a package
"""Small real-LLM latency run: N gold questions one at a time, then a few repeats (cached).

Spends real (free-tier) quota, so keep N small and concurrency at 1. Run from backend/ against
the running API (see load/README.md):

    uv run python ../load/real_run.py --n 20 --out ../load/results/real.json
"""

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

import httpx

from text2sql.config.settings import get_settings
from text2sql.eval.datasets import load_gold
from text2sql.eval.subset import load_subset_ids


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)] if ordered else 0.0


async def _ask(api: httpx.AsyncClient, token: str, question: str) -> dict[str, object]:
    started = time.perf_counter()
    response = await api.post(
        "/v1/query", json={"question": question}, headers={"Authorization": f"Bearer {token}"}
    )
    wall_ms = (time.perf_counter() - started) * 1000
    events = [json.loads(x[6:]) for x in response.text.splitlines() if x.startswith("data: ")]
    answer = events[-1] if events else {}
    stages = answer.get("timings", {}).get("stages", []) if isinstance(answer, dict) else []
    return {
        "status": answer.get("status"),
        "cache": answer.get("cache"),
        "wall_ms": round(wall_ms, 1),
        "stages": {f"{s['stage']}#{s['attempt']}": s["latency_ms"] for s in stages},
    }


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    walls = [float(r["wall_ms"]) for r in rows]  # type: ignore[arg-type]
    errors = sum(r["status"] not in ("answered", "cannot_answer") for r in rows)
    return {
        "n": len(rows),
        "p50_ms": _percentile(walls, 50),
        "p95_ms": _percentile(walls, 95),
        "max_ms": max(walls, default=0.0),
        "error_rate": round(errors / len(rows), 3) if rows else 0.0,
    }


async def main() -> None:
    """Run the questions and write the report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0, help="skip questions already cached")
    parser.add_argument("--repeats", type=int, default=5)
    # Two LLM calls per question; free tiers allow ~15 requests a minute: pace the questions.
    parser.add_argument("--pause", type=float, default=8.0, help="seconds between questions")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    ids = set(load_subset_ids())
    questions = [g.question for g in load_gold() if g.id in ids][args.offset : args.offset + args.n]
    async with httpx.AsyncClient(base_url=args.api, timeout=180) as api:
        login = {
            "username": settings.demo_username,
            "password": settings.demo_password.get_secret_value(),
        }
        token = (await api.post("/v1/auth/token", json=login)).json()["access_token"]
        uncached = []
        for question in questions:  # concurrency 1: free-tier limits
            uncached.append(await _ask(api, token, question))
            print(len(uncached), uncached[-1]["status"], uncached[-1]["wall_ms"])  # noqa: T201
            await asyncio.sleep(args.pause)
        cached = [await _ask(api, token, q) for q in questions[: args.repeats]]
    report = {
        "uncached": _summary([r for r in uncached if r["cache"] is None]),
        "cached": _summary([r for r in cached if r["cache"] == "exact"]),
        "rows": uncached + cached,
    }
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))  # noqa: T201


asyncio.run(main())
