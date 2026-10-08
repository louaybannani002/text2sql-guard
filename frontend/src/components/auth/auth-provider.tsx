"use client";

/** Session state for the page; the token itself lives in a memory-only `TokenStore`. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiClient } from "@/lib/api/client";
import { TokenStore } from "@/lib/api/token-store";
import { API_URL } from "@/lib/config";

const EXPIRED = "Your session expired. Please sign in again.";

interface Session {
  username: string;
  expiresAt: number;
}

interface AuthValue {
  client: ApiClient;
  session: Session | null;
  /** Why the user was signed out (expired session), if they did not do it themselves. */
  notice: string | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
}

type ClientFactory = (tokens: TokenStore, onUnauthorized: () => void) => ApiClient;

const defaultFactory: ClientFactory = (tokens, onUnauthorized) =>
  new ApiClient({ baseUrl: API_URL, getToken: () => tokens.get(), onUnauthorized });

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({
  children,
  createClient = defaultFactory,
}: {
  children: React.ReactNode;
  /** Tests inject a client with a fake `fetch`. */
  createClient?: ClientFactory;
}) {
  const [tokens] = useState(() => new TokenStore());
  const [session, setSession] = useState<Session | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const expire = useCallback(() => {
    tokens.clear();
    setSession(null);
    setNotice(EXPIRED);
  }, [tokens]);

  const [client] = useState(() => createClient(tokens, expire));

  const signIn = useCallback(
    async (username: string, password: string) => {
      const issued = await client.login(username, password);
      const expiresAt = tokens.set(issued.access_token, issued.expires_in);
      setSession({ username, expiresAt });
      setNotice(null);
    },
    [client, tokens],
  );

  const signOut = useCallback(() => {
    tokens.clear();
    setSession(null);
    setNotice(null);
  }, [tokens]);

  // Show the sign-in form as soon as the token lapses, not only on the next request.
  useEffect(() => {
    if (!session) return undefined;
    const timer = setTimeout(expire, Math.max(0, session.expiresAt - Date.now()));
    return () => clearTimeout(timer);
  }, [session, expire]);

  const value = useMemo(
    () => ({ client, session, notice, signIn, signOut }),
    [client, session, notice, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
