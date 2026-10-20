"""OpenTelemetry spans (OTLP/JSON) for one request, as Langfuse reads them (pure, no I/O).

One trace per request (trace id = the query id), a root ``query`` span carrying the trace
attributes, one child span per stage and attempt, and one ``generation`` per LLM or embedding
call under its stage, with the provider and model that actually answered (a fallback
included), tokens and cost. Never sent: result rows, prompts, raw model output, the internal
``Answer.detail``, or the user id in clear (a pseudonym is sent instead).
"""

import hashlib
import json
import secrets
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from text2sql.llm.types import Usage
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.trace import StageTrace

type Span = dict[str, object]
type AttrValue = str | int | float | bool | list[str] | None

_STATUS_ERROR = 2
_KIND_INTERNAL = 1
_PROMPTED = {"generate": "generate", "input_guard": "guard"}  # stages using a versioned prompt


@dataclass(frozen=True)
class RequestInfo:
    """What the API knows about the request around an answer."""

    query_id: uuid.UUID
    request_id: str | None
    user_id: str
    guard_layer: str | None = None  # the guardrail that blocked or rejected it, if any


@dataclass(frozen=True)
class TraceConfig:
    """Static context added to every trace."""

    environment: str
    generate_prompt: str
    guard_prompt: str
    free_tier_providers: frozenset[str] = frozenset()
    capture_question: bool = True


def call_cost(call: Usage, free_tier_providers: frozenset[str]) -> float | None:
    """The call's cost in USD: 0 on a free-tier provider, None when the price is unknown."""
    if call.provider in free_tier_providers:
        return 0.0
    return call.cost_usd


def pseudonym(user_id: str) -> str:
    """A stable identifier for the user that is not the user name."""
    return "user-" + hashlib.sha256(user_id.encode()).hexdigest()[:16]


def _value(value: AttrValue) -> dict[str, object]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [{"stringValue": v} for v in value]}}
    return {"stringValue": str(value)}


def attributes(values: Mapping[str, AttrValue]) -> list[dict[str, object]]:
    """OTLP key/value attributes (None values are left out)."""
    return [{"key": k, "value": _value(v)} for k, v in values.items() if v is not None]


def _json(value: object) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _metadata(prefix: str, values: Mapping[str, object]) -> dict[str, AttrValue]:
    return {
        f"{prefix}.{k}": v if isinstance(v, str | int | float | bool) else _json(v)
        for k, v in values.items()
        if v is not None
    }


class _Builder:
    def __init__(self, answer: Answer, config: TraceConfig, new_span_id: Callable[[], str]) -> None:
        self.answer, self.config, self.new_span_id = answer, config, new_span_id
        self.start_ns = int(answer.trace.started_at.timestamp() * 1_000_000_000)
        self.spans: list[Span] = []

    def nanos(self, offset_ms: float) -> str:
        return str(self.start_ns + int(offset_ms * 1_000_000))

    def add(  # noqa: PLR0913 - one span's coordinates
        self,
        trace_id: str,
        parent: str | None,
        name: str,
        window_ms: tuple[float, float],
        *,
        values: Mapping[str, AttrValue],
        error: str | None = None,
    ) -> str:
        span_id = self.new_span_id()
        span: Span = {
            "traceId": trace_id,
            "spanId": span_id,
            "name": name,
            "kind": _KIND_INTERNAL,
            "startTimeUnixNano": self.nanos(window_ms[0]),
            "endTimeUnixNano": self.nanos(window_ms[1]),
            "attributes": attributes(values),
        }
        if parent is not None:
            span["parentSpanId"] = parent
        if error is not None:
            span["status"] = {"code": _STATUS_ERROR, "message": error}
        self.spans.append(span)
        return span_id

    def stage(self, trace_id: str, root: str, stage: StageTrace) -> None:
        name = stage.stage if stage.attempt <= 1 else f"{stage.stage} (retry {stage.attempt - 1})"
        span_id = self.add(
            trace_id,
            root,
            name,
            (stage.started_ms, stage.started_ms + stage.latency_ms),
            values={
                "langfuse.observation.type": "span",
                "langfuse.observation.input": _json(stage.input),
                "langfuse.observation.output": _json(stage.output),
                "langfuse.observation.level": "ERROR" if stage.status == "error" else "DEFAULT",
                "langfuse.observation.status_message": stage.error,
                **_metadata(
                    "langfuse.observation.metadata",
                    {"stage": stage.stage, "attempt": stage.attempt, "tokens": stage.tokens},
                ),
            },
            error=stage.error if stage.status == "error" else None,
        )
        offset = stage.started_ms
        for call in stage.calls:
            self.call(trace_id, span_id, stage, call, offset)
            offset += call.latency_ms

    def call(
        self, trace_id: str, parent: str, stage: StageTrace, call: Usage, offset_ms: float
    ) -> None:
        cost = call_cost(call, self.config.free_tier_providers)
        prompt = _PROMPTED.get(stage.stage)
        version = {"generate": self.config.generate_prompt, "guard": self.config.guard_prompt}
        metadata: dict[str, object] = {
            "provider": call.provider,
            "fallback": call.fallback,
            "role": call.role,
            "attempts": call.attempts,
            "free_tier": call.provider in self.config.free_tier_providers,
            "prompt_version": version[prompt] if prompt else None,
        }
        usage = {
            "input": call.prompt_tokens,
            "output": call.completion_tokens,
            "total": call.total_tokens,
        }
        self.add(
            trace_id,
            parent,
            "embedding" if call.role == "embedding" else f"{stage.stage}.llm",
            (offset_ms, offset_ms + call.latency_ms),
            values={
                "langfuse.observation.type": "generation",
                "langfuse.observation.model.name": call.model,
                "gen_ai.request.model": call.model,
                "gen_ai.system": call.provider,
                "gen_ai.usage.input_tokens": call.prompt_tokens,
                "gen_ai.usage.output_tokens": call.completion_tokens,
                "langfuse.observation.usage_details": _json(usage),
                "langfuse.observation.cost_details": (
                    _json({"total": cost}) if cost is not None else None
                ),
                **_metadata("langfuse.observation.metadata", metadata),
            },
        )


def trace_spans(
    answer: Answer,
    request: RequestInfo,
    config: TraceConfig,
    *,
    new_span_id: Callable[[], str] = lambda: secrets.token_hex(8),
) -> list[Span]:
    """The OTLP spans (root, stages, generations) for one answered request."""
    builder = _Builder(answer, config, new_span_id)
    trace_id = request.query_id.hex
    result = answer.result
    calls = [call for stage in answer.trace.stages for call in stage.calls]
    costs = [call_cost(call, config.free_tier_providers) for call in calls]
    question = (
        {"question": answer.question}
        if config.capture_question
        else {"question_chars": len(answer.question)}
    )
    output = {
        "status": answer.status,
        "sql": answer.sql if answer.status == "answered" else None,
        "row_count": result.row_count if result else 0,
        "columns": [c.name for c in result.columns] if result else [],
        "truncated": result.truncated if result else False,
    }
    trace_metadata: dict[str, object] = {
        "request_id": request.request_id,
        "query_id": str(request.query_id),
        "generate_prompt": config.generate_prompt,
        "guard_prompt": config.guard_prompt,
        "attempts": answer.attempts,
        "retries": max(answer.attempts - 1, 0),
        "cache": answer.cache,
        "guard_layer": request.guard_layer,
        "models": sorted({call.model for call in calls}),
        "fallbacks": sum(call.fallback for call in calls),
        "total_tokens": answer.trace.total_tokens,
        "total_cost_usd": None if None in costs else round(sum(c or 0.0 for c in costs), 6),
        "total_ms": answer.trace.total_ms,
    }
    root = builder.add(
        trace_id,
        None,
        "query",
        (0.0, answer.trace.total_ms),
        values={
            "langfuse.trace.name": "query",
            "langfuse.user.id": pseudonym(request.user_id),
            "user.id": pseudonym(request.user_id),
            "langfuse.environment": config.environment,
            "langfuse.trace.tags": [answer.status, config.environment],
            "langfuse.trace.input": _json(question),
            "langfuse.trace.output": _json(output),
            "langfuse.observation.input": _json(question),
            "langfuse.observation.output": _json(output),
            **_metadata("langfuse.trace.metadata", trace_metadata),
        },
    )
    for stage in answer.trace.stages:
        builder.stage(trace_id, root, stage)
    return builder.spans
