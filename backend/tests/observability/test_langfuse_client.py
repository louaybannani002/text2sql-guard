import asyncio
import base64
import json

import httpx
import pytest

from text2sql.observability.langfuse_client import (
    OTLP_PATH,
    SERVICE_NAME,
    LangfuseSink,
    NoopSink,
    otlp_payload,
)

SPANS: list[dict[str, object]] = [{"traceId": "ab" * 16, "spanId": "cd" * 8, "name": "query"}]


class Recorder:
    def __init__(self, status: int = 200, body: object = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status, self.body = status, body if body is not None else {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


def _sink(handler: Recorder) -> LangfuseSink:
    return LangfuseSink(
        "https://lf.example.com/",
        "pk-lf-test",
        "sk-lf-test",
        environment="test",
        transport=httpx.MockTransport(handler),
    )


async def test_posts_otlp_json_with_basic_auth() -> None:
    recorder = Recorder()
    sink = _sink(recorder)
    sink.submit(SPANS)
    await sink.aclose()
    (request,) = recorder.requests
    assert request.url == f"https://lf.example.com{OTLP_PATH}"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == otlp_payload(SPANS, environment="test")
    expected = base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert request.headers["authorization"] == f"Basic {expected}"


def test_payload_shape() -> None:
    assert otlp_payload(SPANS) == {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": SERVICE_NAME}}]
                },
                "scopeSpans": [{"scope": {"name": SERVICE_NAME}, "spans": SPANS}],
            }
        ]
    }


@pytest.mark.parametrize(
    ("status", "body", "event"),
    [
        (401, {"message": "bad key"}, "langfuse_rejected"),
        (200, {"partialSuccess": {"rejectedSpans": 1, "errorMessage": "bad"}}, "langfuse_partial"),
    ],
)
async def test_failures_are_logged_without_content(
    status: int, body: object, event: str, capsys: pytest.CaptureFixture[str]
) -> None:
    sink = _sink(Recorder(status, body))
    sink.submit(SPANS)
    await sink.aclose()
    out = capsys.readouterr().out
    assert event in out
    assert "bad key" not in out
    assert "query" not in out.replace("langfuse", "")


async def test_network_errors_never_raise(capsys: pytest.CaptureFixture[str]) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        msg = "down"
        raise httpx.ConnectError(msg, request=request)

    sink = LangfuseSink("https://lf.example.com", "pk", "sk", transport=httpx.MockTransport(broken))
    sink.submit(SPANS)
    await sink.aclose()
    assert "langfuse_send_failed" in capsys.readouterr().out


async def test_submit_does_not_wait_for_the_network() -> None:
    gate = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        del request
        await gate.wait()
        return httpx.Response(200, json={})

    sink = LangfuseSink("https://lf.example.com", "pk", "sk", transport=httpx.MockTransport(slow))
    sink.submit(SPANS)  # returns at once
    gate.set()
    await sink.aclose()


async def test_aclose_gives_up_on_a_hung_send(capsys: pytest.CaptureFixture[str]) -> None:
    async def hang(request: httpx.Request) -> httpx.Response:
        del request
        await asyncio.Event().wait()
        raise AssertionError

    sink = LangfuseSink("https://lf.example.com", "pk", "sk", transport=httpx.MockTransport(hang))
    sink.submit(SPANS)
    await sink.aclose(timeout_s=0.05)
    assert "langfuse_flush_timeout" in capsys.readouterr().out


async def test_empty_batches_and_noop_sink_send_nothing() -> None:
    recorder = Recorder()
    sink = _sink(recorder)
    sink.submit([])
    await sink.aclose()
    assert recorder.requests == []
    noop = NoopSink()
    noop.submit(SPANS)
    await noop.aclose()
