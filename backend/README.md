# text2sql-guard backend

Python 3.12 service, managed with [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env   # then fill in secrets
make install
make up                # postgres (pgvector) + redis in docker
make check             # lint + typecheck + test
make test-integration  # smoke tests against the docker services
make run               # http://127.0.0.1:8000/healthz
```

See [../CLAUDE.md](../CLAUDE.md) for conventions.
