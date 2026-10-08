import { NextResponse, type NextRequest } from "next/server";

import { API_URL } from "@/lib/config";
import { buildCsp, createNonce } from "@/lib/security/csp";

const API_ORIGIN = new URL(API_URL).origin;

/** Per-request nonce + CSP. Next.js reads the nonce from the request's CSP header. */
export function proxy(request: NextRequest) {
  const nonce = createNonce();
  const csp = buildCsp({
    nonce,
    apiOrigin: API_ORIGIN,
    isDev: process.env.NODE_ENV === "development",
    https: request.nextUrl.protocol === "https:",
  });
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages only: static assets carry no inline code.
      source: "/((?!_next/static|_next/image|favicon.ico|icon.svg|robots.txt).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
