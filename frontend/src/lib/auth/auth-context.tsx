"use client";

import { createContext, useCallback, useContext, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, clearToken, getToken, setToken as persistToken } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
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
  const queryClient = useQueryClient();

  // Backed by React Query (not local state) specifically so `queryClient.invalidateQueries({
  // queryKey: queryKeys.me })` -- already called after every place a bet/prize/raffle entry can
  // change `balance` -- actually does something. Before this, `user` lived in plain useState and
  // nothing ever subscribed to the `me` query key, so those invalidations were silent no-ops and
  // the sidebar balance never updated after a bet without a full page reload.
  const { data: user = null, isLoading } = useQuery({
    queryKey: queryKeys.me,
    queryFn: async () => {
      try {
        return await api.auth.me();
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clearToken();
        }
        throw err;
      }
    },
    enabled: !!getToken(),
    retry: false,
    staleTime: 10_000,
  });

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.auth.login({ email, password });
      persistToken(res.access_token);
      const me = await api.auth.me();
      queryClient.setQueryData(queryKeys.me, me);
    },
    [queryClient]
  );

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      await api.auth.register({ email, password, display_name: displayName });
      await login(email, password);
    },
    [login]
  );

  const logout = useCallback(() => {
    clearToken();
    queryClient.setQueryData(queryKeys.me, null);
  }, [queryClient]);

  const refreshUser = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.me });
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user,
      isAdmin: user?.role === "admin",
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, isLoading, login, register, logout, refreshUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
