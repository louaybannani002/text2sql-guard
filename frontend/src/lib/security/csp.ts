/**
 * The Content-Security-Policy, built per request around a fresh nonce (see src/proxy.ts).
 *
 * Strict CSP: scripts run only with this request's nonce ('strict-dynamic' lets those scripts
 * load Next.js chunks); no 'unsafe-inline', no 'unsafe-eval' outside development, no plugins,
 * no <base> tag, no framing. The browser may only talk to this origin and the API.
 */
export interface CspOptions {
  nonce: string;
  apiOrigin: string;
  isDev: boolean;
  /** Only when served over HTTPS: upgrading on plain http://localhost would break the API calls. */
  https: boolean;
}

export function buildCsp({ nonce, apiOrigin, isDev, https }: CspOptions): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": [`'nonce-${nonce}'`, "'strict-dynamic'", ...(isDev ? ["'unsafe-eval'"] : [])],
    // Dev: Next's error overlay and HMR inject unnonced styles.
    "style-src": ["'self'", isDev ? "'unsafe-inline'" : `'nonce-${nonce}'`],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'"],
    "connect-src": ["'self'", apiOrigin],
    "object-src": ["'none'"],
    "base-uri": ["'none'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
    "manifest-src": ["'self'"],
    "worker-src": ["'self'"],
  };
  const policy = Object.entries(directives).map(([name, values]) => `${name} ${values.join(" ")}`);
  if (https) policy.push("upgrade-insecure-requests");
  return policy.join("; ");
}

/** 128 random bits, base64: unguessable and unique per response. */
export function createNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}
