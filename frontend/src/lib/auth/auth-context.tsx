"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ApiError, api, clearToken, getToken, setToken as persistToken } from "@/lib/api/client";
import type { User } from "@/lib/api/types";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Lazy initializer: reading the token synchronously at mount (not inside an effect) is the
  // sanctioned way to seed state from an external, impure source in React -- if there's no
  // token there's nothing to load, so we start already "not loading" instead of flipping it
  // off from inside an effect.
  const [isLoading, setIsLoading] = useState(() => !!getToken());

  const loadMe = useCallback(async () => {
    // Only ever invoked when a token is known to exist (see the effect below), and its first
    // statement is an `await`, so no setState call happens synchronously within the effect
    // that calls it.
    try {
      const me = await api.auth.me();
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        clearToken();
      }
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    // This is the standard "fetch on mount" effect pattern -- `loadMe`'s own setState calls
    // all happen after its internal `await`, never synchronously within this effect's call
    // frame, but the lint rule's static check can't see across that await boundary and flags
    // the call site itself. Session bootstrapping on mount is exactly what effects are for.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadMe();
  }, [loadMe]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.auth.login({ email, password });
    persistToken(res.access_token);
    const me = await api.auth.me();
    setUser(me);
  }, []);

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      await api.auth.register({ email, password, display_name: displayName });
      await login(email, password);
    },
    [login]
  );

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user,
      isAdmin: user?.role === "admin",
      login,
      register,
      logout,
      refreshUser: loadMe,
    }),
    [user, isLoading, login, register, logout, loadMe]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
