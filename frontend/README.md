# text2sql-guard — frontend

Next.js (App Router) UI for the text2sql-guard API: ask a question, watch the pipeline run
live, and get the explanation, SQL, a sortable table, an automatic chart and the trace.

## Run it

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
| `pnpm build`     | Production build (the page is static)               |
| `pnpm start`     | Serve the production build                          |
| `pnpm lint`      | ESLint (Next.js + React Compiler rules)             |
| `pnpm typecheck` | `next typegen` + `tsc --noEmit` (strict)            |
| `pnpm test`      | Vitest + Testing Library (jsdom)                    |
| `pnpm check`     | lint + typecheck + test: run before every commit    |

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
- `next.config.ts` sends a CSP (`connect-src` limited to this origin and the API),
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and `nosniff`.
