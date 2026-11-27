import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import { fetchProfile, login } from "../api/cohortiq";
import type { UserProfile } from "../api/types";

const STORAGE_KEY = "cohortiq.session";
/** Sign out slightly before the token expires, so a request never races the expiry. */
const EXPIRY_MARGIN_MS = 15_000;

interface StoredSession {
  token: string;
  expiresAt: number;
}

export type SessionState =
  | { status: "restoring" }
  | { status: "signed_out"; notice: string | null }
  | { status: "signed_in"; token: string; user: UserProfile; expiresAt: number };

interface SessionContextValue {
  session: SessionState;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: (notice?: string | null) => void;
  /** Call when the API answers 401: the token is no longer valid. */
  handleUnauthorized: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

// sessionStorage can be unavailable (privacy modes); the app then works for the tab's lifetime only.
function readStored(): StoredSession | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (typeof parsed.token !== "string" || typeof parsed.expiresAt !== "number") return null;
    return { token: parsed.token, expiresAt: parsed.expiresAt };
  } catch {
    return null;
  }
}

function writeStored(value: StoredSession | null): void {
  try {
    if (value) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: keep the session in memory only */
  }
}

export const SESSION_EXPIRED_NOTICE = "Your session has ended. Please sign in again.";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState>({ status: "restoring" });
  const expiryTimer = useRef<number | undefined>(undefined);

  const signOut = useCallback((notice: string | null = null) => {
    window.clearTimeout(expiryTimer.current);
    writeStored(null);
    setSession({ status: "signed_out", notice });
  }, []);

  const startSession = useCallback(
    (token: string, user: UserProfile, expiresAt: number) => {
      window.clearTimeout(expiryTimer.current);
      expiryTimer.current = window.setTimeout(
        () => signOut(SESSION_EXPIRED_NOTICE),
        Math.max(0, expiresAt - Date.now() - EXPIRY_MARGIN_MS),
      );
      setSession({ status: "signed_in", token, user, expiresAt });
    },
    [signOut],
  );

  // Restore a session stored in this tab, checking the token with the API.
  useEffect(() => {
    const stored = readStored();
    if (!stored || stored.expiresAt - EXPIRY_MARGIN_MS <= Date.now()) {
      writeStored(null);
      setSession({ status: "signed_out", notice: null });
      return;
    }
    const controller = new AbortController();
    fetchProfile(stored.token, controller.signal)
      .then((user) => startSession(stored.token, user, stored.expiresAt))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        const notice = error instanceof ApiError && error.kind === "unauthorized" ? SESSION_EXPIRED_NOTICE : null;
        signOut(notice);
      });
    return () => controller.abort();
  }, [signOut, startSession]);

  useEffect(() => () => window.clearTimeout(expiryTimer.current), []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const token = await login(email, password);
      const expiresAt = Date.now() + token.expires_in * 1000;
      const user = await fetchProfile(token.access_token);
      writeStored({ token: token.access_token, expiresAt });
      startSession(token.access_token, user, expiresAt);
    },
    [startSession],
  );

  const handleUnauthorized = useCallback(() => signOut(SESSION_EXPIRED_NOTICE), [signOut]);

  const value = useMemo(
    () => ({ session, signIn, signOut, handleUnauthorized }),
    [session, signIn, signOut, handleUnauthorized],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider.");
  return value;
}
