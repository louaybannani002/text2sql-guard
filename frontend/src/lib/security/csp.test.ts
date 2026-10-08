import { buildCsp, createNonce } from "./csp";

const base = { nonce: "abc123==", apiOrigin: "http://127.0.0.1:8000", isDev: false, https: false };

function directives(csp: string): Map<string, string[]> {
  return new Map(
    csp.split("; ").map((d) => {
      const [name = "", ...values] = d.split(" ");
      return [name, values];
    }),
  );
}

describe("buildCsp", () => {
  it("is a strict, nonce-based policy in production", () => {
    const csp = directives(buildCsp(base));
    expect(csp.get("script-src")).toEqual(["'nonce-abc123=='", "'strict-dynamic'"]);
    expect(csp.get("style-src")).toEqual(["'self'", "'nonce-abc123=='"]);
    expect(csp.get("object-src")).toEqual(["'none'"]);
    expect(csp.get("base-uri")).toEqual(["'none'"]);
    expect(csp.get("frame-ancestors")).toEqual(["'none'"]);
    expect(csp.get("connect-src")).toEqual(["'self'", "http://127.0.0.1:8000"]);
    expect(buildCsp(base)).not.toMatch(/unsafe-inline|unsafe-eval|\*/);
    expect(csp.has("upgrade-insecure-requests")).toBe(false);
  });

  it("relaxes only what Next.js dev tooling needs in development", () => {
    const csp = directives(buildCsp({ ...base, isDev: true }));
    expect(csp.get("script-src")).toContain("'unsafe-eval'");
    expect(csp.get("script-src")).not.toContain("'unsafe-inline'");
    expect(csp.get("style-src")).toContain("'unsafe-inline'");
  });

  it("upgrades insecure requests only over HTTPS", () => {
    expect(buildCsp({ ...base, https: true })).toMatch(/; upgrade-insecure-requests$/);
  });
});

describe("createNonce", () => {
  it("is 128 random bits in base64, different every time", () => {
    const nonces = new Set(Array.from({ length: 50 }, createNonce));
    expect(nonces.size).toBe(50);
    for (const nonce of nonces) expect(atob(nonce)).toHaveLength(16);
  });
});
