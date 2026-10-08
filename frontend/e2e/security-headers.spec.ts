import { expect, test } from "@playwright/test";

function directives(csp: string): Map<string, string> {
  return new Map(
    csp.split(";").map((d) => {
      const [name = "", ...rest] = d.trim().split(/\s+/);
      return [name, rest.join(" ")];
    }),
  );
}

test("pages carry a strict, per-request CSP and the security headers", async ({ request }) => {
  const first = await request.get("/");
  const second = await request.get("/");
  const headers = first.headers();
  const csp = directives(headers["content-security-policy"] ?? "");

  const nonce = /'nonce-([^']+)'/.exec(csp.get("script-src") ?? "")?.[1];
  expect(nonce, "script-src nonce").toBeTruthy();
  expect(second.headers()["content-security-policy"]).not.toContain(nonce!); // fresh per request
  expect(csp.get("script-src")).toContain("'strict-dynamic'");
  expect(headers["content-security-policy"]).not.toMatch(/unsafe-inline|unsafe-eval/);
  expect(csp.get("object-src")).toBe("'none'");
  expect(csp.get("base-uri")).toBe("'none'");
  expect(csp.get("frame-ancestors")).toBe("'none'");

  // Next.js stamped the nonce on its own scripts.
  const html = await first.text();
  expect(html).toContain(`nonce="${nonce}"`);

  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["referrer-policy"]).toBe("no-referrer");
  expect(headers["cross-origin-opener-policy"]).toBe("same-origin");
  expect(headers["permissions-policy"]).toContain("camera=()");
  expect(headers["x-powered-by"]).toBeUndefined();
});
