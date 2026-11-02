import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, DEMO, setCsrfToken } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  checked: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  canEdit: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthState | null>(null);
const DEMO_USER: Me = { id: 0, username: "demo", role: "bioinformatician", csrf_token: "" };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(DEMO ? DEMO_USER : null);
  const [checked, setChecked] = useState(DEMO);
  useEffect(() => {
    if (DEMO) return;
    api<Me>("/auth/me")
      .then((m) => {
        setCsrfToken(m.csrf_token);
        setMe(m);
      })
      .catch((e: unknown) => {
        if (!(e instanceof ApiError) || e.status !== 401) console.error(e);
      })
      .finally(() => setChecked(true));
  }, []);
  const login = useCallback(async (username: string, password: string) => {
    const m = await api<Me>("/auth/login", { method: "POST", body: { username, password } });
    setCsrfToken(m.csrf_token);
    setMe(m);
  }, []);
  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setCsrfToken(null);
    setMe(null);
  }, []);
  // In the demo the role only shows what a bioinformatician sees; writes are refused.
  const canEdit = !DEMO && (me?.role === "admin" || me?.role === "bioinformatician");
  const isAdmin = !DEMO && me?.role === "admin";
  return <AuthContext.Provider value={{ me, checked, login, logout, canEdit, isAdmin }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
