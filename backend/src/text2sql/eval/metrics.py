"""Aggregate evaluation outcomes into the numbers the reports show."""

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from text2sql.eval.outcomes import AttackOutcome, BenignOutcome, GoldOutcome, Usage

INPUT_LAYERS = frozenset({"input_rules", "input_classifier"})


@dataclass(frozen=True)
class Rate:
    """``hits`` out of ``n`` (rate is None when n is 0)."""

    n: int
    hits: int

    @property
    def rate(self) -> float | None:
        """Hits divided by n."""
        return self.hits / self.n if self.n else None


@dataclass(frozen=True)
class GoldMetrics:
    """SQL accuracy on the gold set."""

    execution_accuracy: Rate
    valid_sql: Rate  # answered: the SQL passed the validator and executed
    answerable_precision: Rate  # correct among the answered ones
    cannot_answer: int
    by_difficulty: dict[str, Rate]
    by_category: dict[str, Rate]


@dataclass(frozen=True)
class AttackMetrics:
    """Attack blocking: overall, per category and per layer."""

    blocked: Rate
    input_guard_blocked: Rate  # attacks whose expected layer is the input guard
    at_expected_layer: Rate
    by_category: dict[str, Rate]
    layers_by_category: dict[str, dict[str, int]]
    answered_safely: int  # read-only validated SQL ran: no harm, but not blocked
    failed: int


@dataclass(frozen=True)
class BenignMetrics:
    """False blocks on legitimate but suspicious-looking questions."""

    false_blocked: Rate
    unexpected_false_blocks: list[str]  # not recorded as known_false_block
    layers: dict[str, int]


@dataclass(frozen=True)
class CostMetrics:
    """Latency, tokens, cost and cache use per question."""

    questions: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    avg_tokens: float | None
    avg_cost_usd: float | None
    cost_unknown: int
    cache_hits: Rate


@dataclass(frozen=True)
class EvalMetrics:
    """Everything a report shows."""

    gold: GoldMetrics | None = None
    attacks: AttackMetrics | None = None
    benign: BenignMetrics | None = None
    cost: CostMetrics | None = None
    notes: list[str] = field(default_factory=list)
    # Questions that still hit a provider outage after retries: left out of every rate above.
    infrastructure_errors: list[str] = field(default_factory=list)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100)."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(q / 100 * len(ordered)) - 1)
    return ordered[index]


def _rates(groups: dict[str, list[bool]]) -> dict[str, Rate]:
    return {key: Rate(len(hits), sum(hits)) for key, hits in sorted(groups.items())}


def gold_metrics(outcomes: Sequence[GoldOutcome]) -> GoldMetrics:
    """Accuracy, valid-SQL rate and answerable precision, overall and per group."""
    answered = [o for o in outcomes if o.valid_sql]
    by_difficulty: dict[str, list[bool]] = {}
    by_category: dict[str, list[bool]] = {}
    for o in outcomes:
        by_difficulty.setdefault(o.difficulty, []).append(o.correct)
        by_category.setdefault(o.category, []).append(o.correct)
    return GoldMetrics(
        execution_accuracy=Rate(len(outcomes), sum(o.correct for o in outcomes)),
        valid_sql=Rate(len(outcomes), len(answered)),
        answerable_precision=Rate(len(answered), sum(o.correct for o in answered)),
        cannot_answer=sum(o.status == "cannot_answer" for o in outcomes),
        by_difficulty=_rates(by_difficulty),
        by_category=_rates(by_category),
    )


def attack_metrics(outcomes: Sequence[AttackOutcome]) -> AttackMetrics:
    """Block rates and the layer that stopped each attack."""
    by_category: dict[str, list[bool]] = {}
    layers: dict[str, Counter[str]] = {}
    for o in outcomes:
        by_category.setdefault(o.category, []).append(o.blocked)
        layers.setdefault(o.category, Counter())[o.stopped_by or "answered_safely"] += 1
    must_block = [o for o in outcomes if o.expected_layer in INPUT_LAYERS]
    return AttackMetrics(
        blocked=Rate(len(outcomes), sum(o.blocked for o in outcomes)),
        input_guard_blocked=Rate(len(must_block), sum(o.blocked for o in must_block)),
        at_expected_layer=Rate(
            len(outcomes), sum(o.stopped_by == o.expected_layer for o in outcomes)
        ),
        by_category=_rates(by_category),
        layers_by_category={k: dict(sorted(v.items())) for k, v in sorted(layers.items())},
        answered_safely=sum(o.stopped_by is None for o in outcomes),
        failed=sum(o.stopped_by == "failed" for o in outcomes),
    )


def benign_metrics(outcomes: Sequence[BenignOutcome]) -> BenignMetrics:
    """False-block rate and where the false blocks happen."""
    blocked = [o for o in outcomes if o.false_block]
    return BenignMetrics(
        false_blocked=Rate(len(outcomes), len(blocked)),
        unexpected_false_blocks=[o.id for o in blocked if o.known_false_block is None],
        layers=dict(Counter(o.stopped_by or "unknown" for o in blocked)),
    )


def cost_metrics(usages: Iterable[Usage]) -> CostMetrics:
    """Latency percentiles, average tokens and cost, cache hit rate."""
    items = list(usages)
    costs = [u.cost_usd for u in items if u.cost_usd is not None]
    return CostMetrics(
        questions=len(items),
        latency_p50_ms=percentile([u.total_ms for u in items], 50),
        latency_p95_ms=percentile([u.total_ms for u in items], 95),
        avg_tokens=sum(u.tokens for u in items) / len(items) if items else None,
        avg_cost_usd=sum(costs) / len(costs) if costs else None,
        cost_unknown=len(items) - len(costs),
        cache_hits=Rate(len(items), sum(u.cache is not None for u in items)),
    )
