"""One HTTP session for every LLM completion, so connections (TLS included) are reused.

LiteLLM accepts an aiohttp ``ClientSession`` per call (``shared_session``); the API opens one
at startup, passes it through ``LLMConfig.http_session`` and closes it on shutdown. Without
it, LiteLLM keeps its own per-provider clients, which expire after an hour.
"""

from aiohttp import ClientSession, ClientTimeout, TCPConnector

KEEPALIVE_S = 60.0


def open_http_session(max_connections: int) -> ClientSession:
    """A session with a bounded, keep-alive connection pool (call from a running loop).

    Timeouts stay per call (``LLMConfig.timeout_s``); the session itself sets none.
    """
    connector = TCPConnector(limit=max_connections, keepalive_timeout=KEEPALIVE_S)
    return ClientSession(connector=connector, timeout=ClientTimeout(total=None))
