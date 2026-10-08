"""Server-Sent Events framing (https://html.spec.whatwg.org/multipage/server-sent-events.html)."""

import json

from pydantic import BaseModel


def sse_event(
    event: str, data: BaseModel | dict[str, object], *, event_id: int | None = None
) -> str:
    """One SSE message: ``event:`` name, optional ``id:``, and a single-line JSON ``data:``.

    JSON is serialised compactly (no newlines), so a single ``data:`` line is always valid.
    """
    payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data)
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"
