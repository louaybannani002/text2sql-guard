# syntax=docker/dockerfile:1
# text2sql-guard web UI: Next.js standalone server on a distroless runtime (no shell, no
# package manager, non-root). Base images are pinned by version AND digest: bump both together.

FROM node:22.23.3-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY . .
# Inlined into the browser bundle (and the CSP's connect-src) at build time: the API's URL
# as the *browser* sees it, i.e. the port published on the host.
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# Debian 13 distroless: no high/critical findings (Debian 12's libssl3 had fixable ones).
FROM gcr.io/distroless/nodejs22-debian13:nonroot@sha256:6c19627684167feb45e7ab0b4938e01a4922fc4abd9abd430df07606a6ab0e26
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
# Owned by root, readable by the nonroot user (uid 65532): the app cannot modify itself.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER nonroot
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=10s --start-period=20s --retries=5 \
  CMD ["/nodejs/bin/node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
# The distroless entrypoint is node itself.
CMD ["server.js"]
