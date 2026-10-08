import type { NextConfig } from "next";

/**
 * Security headers for every response. The Content-Security-Policy is not here: a strict CSP
 * needs a fresh nonce per request, so src/proxy.ts builds it (src/lib/security/csp.ts).
 */
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  { key: "Origin-Agent-Cluster", value: "?1" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  { key: "X-Permitted-Cross-Domain-Policies", value: "none" },
  // Browsers ignore HSTS over plain HTTP, so this is safe locally and active behind TLS.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  {
    key: "Permissions-Policy",
    value:
      "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), " +
      "magnetometer=(), gyroscope=(), accelerometer=(), browsing-topics=()",
  },
];

const nextConfig: NextConfig = {
  // A self-contained server (.next/standalone) for the Docker image.
  output: "standalone",
  poweredByHeader: false,
  // Nonce-based CSP requires per-request rendering, which Cache Components (Partial
  // Prerendering) would bypass with a static shell. The page is a client app; nothing to cache.
  cacheComponents: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
