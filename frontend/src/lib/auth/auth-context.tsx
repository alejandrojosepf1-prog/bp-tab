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
  // The logged-in user's play-token balance for the currently active tournament (CNADE 2026
  // Roadmap Pieza 3 -- balance is per-tournament, not a flat field on `user` anymore). `null`
  // while loading or when there's no active tournament to have a balance in.
  balance: number | null;
  activeTournamentId: number | null;
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
    // Balance also moves from actions this tab didn't trigger -- another market getting
    // liquidated, a prize/raffle payout -- so invalidating `me` only after the user's OWN
    // mutations (bet placed, etc.) isn't enough; without this the sidebar balance was stuck
    // until the user happened to refocus the window or navigate. Same interval market-card's
    // own polling queries already use.
    refetchInterval: 30_000,
  });

  // "Active tournament" = the one bettable one right now (see Tournament.is_active) -- this
  // product only ever runs one live tournament at a time, so the balance shown app-wide (the
  // sidebar, market cards) is that tournament's TournamentBalance, not a global figure that no
  // longer exists.
  const { data: tournaments = [] } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
    enabled: !!user,
    staleTime: 30_000,
  });
  const activeTournamentId = tournaments.find((t) => t.is_active)?.id ?? null;

  const { data: balanceData } = useQuery({
    queryKey: queryKeys.myBalance(activeTournamentId ?? "none"),
    queryFn: () => api.tournaments.myBalance(activeTournamentId!),
    enabled: !!user && activeTournamentId !== null,
    staleTime: 10_000,
    // Same reasoning as the `me` query above: balance moves from actions this tab didn't
    // trigger (a market settling, a prize payout), so polling is the only way the sidebar
    // stays live without a manual refresh.
    refetchInterval: 30_000,
  });
  const balance = balanceData?.balance ?? null;

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
      balance,
      activeTournamentId,
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, isLoading, balance, activeTournamentId, login, register, logout, refreshUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
