"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { PageTransition } from "@/components/motion";
import { LiveRankingCard } from "@/components/dashboard/live-ranking-card";
import { LatestRoundCard } from "@/components/dashboard/latest-round-card";
import { RecentChangesCard } from "@/components/dashboard/recent-changes-card";
import { BreakProbabilityCard } from "@/components/dashboard/break-probability-card";
import { MyPredictionsCard } from "@/components/dashboard/my-predictions-card";
import { TopBettorsCard } from "@/components/dashboard/top-bettors-card";
import { OpenMarketsCard } from "@/components/dashboard/open-markets-card";

export default function DashboardPage() {
  const { isAuthenticated } = useAuth();
  // No effect needed to "auto-select" a tournament: the preferred one is fully derived from
  // `tournaments`, so it's just computed on every render. `manualTournamentId` only exists to
  // remember an explicit user choice, which does need real state.
  const [manualTournamentId, setManualTournamentId] = useState<string | null>(null);

  const { data: tournaments, isLoading: loadingTournaments } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
    staleTime: 60_000,
  });

  const preferred =
    tournaments?.find((t) => t.status === "in_progress" || t.status === "eliminations") ??
    tournaments?.find((t) => t.is_active) ??
    tournaments?.[0];
  const tournamentId = manualTournamentId ?? (preferred ? String(preferred.id) : null);

  const {
    data: dashboard,
    isLoading: loadingDashboard,
    error,
  } = useQuery({
    queryKey: tournamentId ? queryKeys.dashboard(tournamentId) : ["dashboard", "none"],
    queryFn: () => api.dashboard.get(tournamentId!),
    enabled: !!tournamentId,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  if (loadingTournaments) return <LoadingState label="Cargando torneos…" />;

  if (!tournaments?.length) {
    return (
      <EmptyState
        title="Todavía no hay torneos"
        description="Cuando un administrador agregue un torneo, aparecerá aquí."
      />
    );
  }

  return (
    <PageTransition>
      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
            <p className="text-sm text-muted-foreground">
              Resumen en vivo del torneo seleccionado.
            </p>
          </div>
          {tournaments.length > 1 && (
            <Select value={tournamentId ?? ""} onValueChange={setManualTournamentId}>
              <SelectTrigger className="w-[240px]">
                <SelectValue placeholder="Seleccionar torneo" />
              </SelectTrigger>
              <SelectContent>
                {tournaments.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {loadingDashboard && <LoadingState label="Cargando dashboard…" />}
        {error && <ErrorState error={error} />}

        {dashboard && tournamentId && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <LiveRankingCard tournamentId={tournamentId} />
            <LatestRoundCard tournamentId={tournamentId} round={dashboard.latest_round} />
            <RecentChangesCard changes={dashboard.recent_changes} />
            <BreakProbabilityCard tournamentId={tournamentId} />
            {isAuthenticated && (
              <MyPredictionsCard
                tournamentId={tournamentId}
                predictions={dashboard.my_predictions}
              />
            )}
            <TopBettorsCard tournamentId={tournamentId} entries={dashboard.leaderboard_top} />
            <OpenMarketsCard tournamentId={tournamentId} markets={dashboard.open_bet_markets} />
          </div>
        )}
      </div>
    </PageTransition>
  );
}
