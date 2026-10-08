import type { FullConfig } from "@playwright/test";

import { API_URL } from "./env";

/** Fail fast, with the fix, when the docker compose stack is not up. */
export default async function globalSetup(config: FullConfig): Promise<void> {
  const web = config.projects[0]?.use.baseURL ?? "http://127.0.0.1:3000";
  for (const [name, url] of [
    ["API", `${API_URL}/readyz`],
    ["web UI", web],
  ] as const) {
    let ok = false;
    try {
      ok = (await fetch(url, { signal: AbortSignal.timeout(5000) })).ok;
    } catch {
      ok = false;
    }
    if (!ok) {
      throw new Error(`The ${name} is not ready at ${url}. Start the stack first: cd backend && make up`);
    }
  }
}
