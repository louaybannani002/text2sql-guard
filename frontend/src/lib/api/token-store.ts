/**
 * The access token, in memory only: never localStorage, sessionStorage or a cookie. A reload
 * or a new tab means signing in again; tokens are short-lived anyway.
 */
const CLOCK_SKEW_MS = 10_000;

export class TokenStore {
  private token: string | null = null;
  private expiresAt = 0;

  constructor(private readonly now: () => number = Date.now) {}

  /** Keep a token valid for `expiresInS` seconds (minus a margin for clock skew). */
  set(token: string, expiresInS: number): number {
    this.token = token;
    this.expiresAt = this.now() + expiresInS * 1000 - CLOCK_SKEW_MS;
    return this.expiresAt;
  }

  /** The token, or null when there is none or it has expired. */
  get(): string | null {
    return this.token !== null && this.now() < this.expiresAt ? this.token : null;
  }

  clear(): void {
    this.token = null;
    this.expiresAt = 0;
  }
}
