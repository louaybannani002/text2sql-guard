"""Point connection URLs at another host without touching their credentials.

Inside docker compose, Postgres and Redis are reached by service name (``postgres:5432``), not
``127.0.0.1``; the role passwords live only inside the URLs, so the URLs are rewritten rather
than duplicated.
"""

from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr


def with_host(url: SecretStr | str, host: str) -> SecretStr:
    """``url`` with its ``host[:port]`` replaced by ``host``; user, password, path kept."""
    raw = url.get_secret_value() if isinstance(url, SecretStr) else url
    parts = urlsplit(raw)
    userinfo, at, _ = parts.netloc.rpartition("@")
    netloc = f"{userinfo}{at}{host}"
    return SecretStr(urlunsplit(parts._replace(netloc=netloc)))
