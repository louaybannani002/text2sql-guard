# text2sql-guard — frontend

Next.js (App Router) UI for the text2sql-guard API: ask a question, watch the pipeline run
live, and get the explanation, SQL, a sortable table, an automatic chart and the trace.

## Run it

The whole app (database, cache, API and this UI) in Docker:

```sh
cd ../backend && make up        # http://localhost:3000
```

Or this UI alone, against an API you run yourself (`make services && make run` in `backend/`):

```sh
pnpm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL, default http://127.0.0.1:8000
pnpm dev                        # http://localhost:3000
```

The API must be running (`make run` in `backend/`), and its `CORS_ALLOWED_ORIGINS` must list
`http://localhost:3000`. Sign in with the demo user from `backend/.env`
(`DEMO_USERNAME` / `DEMO_PASSWORD`).

## Commands

| Command          | What it does                                        |
|------------------|-----------------------------------------------------|
| `pnpm dev`       | Dev server on port 3000                             |
| `pnpm build`     | Production build (standalone server, per-request CSP) |
| `pnpm start`     | Serve the production build                          |
| `pnpm lint`      | ESLint (Next.js + React Compiler rules)             |
| `pnpm typecheck` | `next typegen` + `tsc --noEmit` (strict)            |
| `pnpm test`      | Vitest + Testing Library (jsdom)                    |
| `pnpm check`     | lint + typecheck + test: run before every commit    |
| `pnpm e2e`       | Playwright e2e against the running compose stack    |
| `pnpm lighthouse`| Lighthouse mobile + desktop; fails under 90         |

`pnpm e2e` uses your installed Google Chrome (`PLAYWRIGHT_CHANNEL=chromium` plus
`pnpm exec playwright install chromium` to use Playwright's own build). It calls the real
API and LLM: a fresh question costs about $0.01, and repeats are served by the cache.

## Layout

| Path                     | Contents                                                       |
|--------------------------|----------------------------------------------------------------|
| `src/lib/api/`           | Typed client: zod schemas, SSE parser, in-memory token store   |
| `src/lib/`               | Pure logic: stage progress, chart detection, CSV, formatting   |
| `src/hooks/use-ask.ts`   | One question at a time: streaming, cancel, stale-event guard   |
| `src/components/ask/`    | Question box, example chips, live progress, request errors     |
| `src/components/results/`| Answer, SQL, table, chart, guardrail notice, feedback, trace   |
| `src/components/ui/`     | shadcn/ui components (generated; edit sparingly)               |

## Security notes

- The JWT lives only in memory (`TokenStore`): never `localStorage`, `sessionStorage` or a
  cookie. Reloading the page signs you out; tokens expire after 15 minutes.
- Requests send `credentials: "omit"`; the API is reached only with the bearer header.
- Every API payload is validated with zod before use.
- CSV export neutralises cells that a spreadsheet would run as formulas.
- Strict Content-Security-Policy from `src/proxy.ts`: a new nonce per request,
  `'strict-dynamic'`, no `'unsafe-inline'` or `'unsafe-eval'`, `object-src`/`base-uri`/
  `frame-ancestors 'none'`, `connect-src` limited to this origin and the API. The e2e tests
  fail on any violation.
- `next.config.ts` adds `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `nosniff`,
  COOP/CORP `same-origin`, a restrictive `Permissions-Policy` and HSTS (honoured over HTTPS).
- The Docker image runs Next's standalone server as the unprivileged `node` user on a
  read-only filesystem.
