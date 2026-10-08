import json

from pydantic import BaseModel

from text2sql.api.sse import sse_event


class Payload(BaseModel):
    text: str


def test_dict_payload_with_id() -> None:
    assert sse_event("query", {"query_id": "abc"}, event_id=0) == (
        'event: query\nid: 0\ndata: {"query_id": "abc"}\n\n'
    )


def test_model_payload_stays_on_one_line() -> None:
    message = sse_event("answer", Payload(text="line one\nline two"))
    lines = message.rstrip("\n").split("\n")
    assert lines[0] == "event: answer"
    assert len(lines) == 2  # newlines inside data are JSON-escaped
    assert json.loads(lines[1].removeprefix("data: ")) == {"text": "line one\nline two"}
    assert message.endswith("\n\n")
