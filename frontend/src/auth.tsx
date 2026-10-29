import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, clearToken, getToken, setToken, SESSION_EXPIRED_EVENT, type Role, type User } from "./api";
import { classifySessionFailure, SESSION_MESSAGES } from "./lib/session";

interface AuthState {
  user: User | null;
  loading: boolean;
  notice: string | null;
  canAnalyze: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const RETRY_START_MS = 2_000;
const RETRY_MAX_MS = 30_000;

/** Analysts and administrators may upload, run, and create cases. Viewers are read-only. */
export function hasAnalystRole(role: Role | undefined): boolean {
  return role === "analyst" || role === "administrator";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  // Each session check gets a number. Logout, login, and expiry bump it, so a check that
  // was in flight before them cannot restore or change state afterwards.
  const sessionVersion = useRef(0);
  // While the server is unreachable the token is kept and the check is retried with backoff.
  const retryTimer = useRef<number | undefined>(undefined);
  const retryDelay = useRef(RETRY_START_MS);
  const awaitingReconnect = useRef(false);

  function stopRetry() {
    window.clearTimeout(retryTimer.current);
    retryTimer.current = undefined;
    retryDelay.current = RETRY_START_MS;
    awaitingReconnect.current = false;
  }

  function scheduleRetry() {
    awaitingReconnect.current = true;
    window.clearTimeout(retryTimer.current);
    retryTimer.current = window.setTimeout(() => {
      retryTimer.current = undefined;
      if (getToken()) {
        void checkSession();
      } else {
        stopRetry();
      }
    }, retryDelay.current);
    retryDelay.current = Math.min(retryDelay.current * 2, RETRY_MAX_MS);
  }

  // Restoring a session never grants access without a successful /auth/me response.
  function checkSession(): Promise<void> {
    const version = ++sessionVersion.current;
    return api.get<User>("/auth/me").then(
      (me) => {
        if (version !== sessionVersion.current) return;
        stopRetry();
        setUser(me);
        setNotice(null);
      },
      (err: unknown) => {
        if (version !== sessionVersion.current) return;
        setUser(null);
        const failure = classifySessionFailure(err);
        if (failure === "unreachable") {
          setNotice(SESSION_MESSAGES.unreachable);
          scheduleRetry();
          return;
        }
        stopRetry();
        if (failure === "rejected") {
          clearToken();
          setNotice(SESSION_MESSAGES.rejected);
        } else {
          setNotice(err instanceof ApiError ? err.message : SESSION_MESSAGES.unreachable);
        }
      },
    );
  }

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    checkSession().finally(() => setLoading(false));
    // Runs once on mount. checkSession reads only refs and stable setters, so re-running it is never wanted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Reconnecting, or regaining focus, retries right away instead of waiting for the backoff.
    function retryNow() {
      if (!awaitingReconnect.current || !getToken()) return;
      window.clearTimeout(retryTimer.current);
      retryTimer.current = undefined;
      retryDelay.current = RETRY_START_MS;
      void checkSession();
    }
    // Any authenticated request that receives 401 drops the session and returns to sign-in.
    function onExpired() {
      sessionVersion.current += 1;
      stopRetry();
      setUser(null);
      setNotice("Your session has expired. Sign in again.");
    }
    window.addEventListener("online", retryNow);
    window.addEventListener("focus", retryNow);
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => {
      window.removeEventListener("online", retryNow);
      window.removeEventListener("focus", retryNow);
      window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
      stopRetry();
    };
    // Listeners are registered once. retryNow calls checkSession, which reads only refs and stable setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(username: string, password: string) {
    const { access_token } = await api.post<{ access_token: string }>("/auth/login", {
      username,
      password,
    });
    sessionVersion.current += 1;
    const version = sessionVersion.current;
    stopRetry();
    setToken(access_token);
    setNotice(null);
    const me = await api.get<User>("/auth/me");
    if (version !== sessionVersion.current) return;
    setUser(me);
  }

  function logout() {
    sessionVersion.current += 1;
    stopRetry();
    clearToken();
    setNotice("You have signed out.");
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        notice,
        canAnalyze: hasAnalystRole(user?.role),
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
