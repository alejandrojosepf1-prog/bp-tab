"use client";

import { useQuery } from "@tanstack/react-query";
import { Medal, Trophy } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";
import { formatSignedTokens, formatTokens } from "@/lib/format";
import type { GlobalLeaderboardEntry } from "@/lib/api/types";

const MEDAL_CLASS: Record<number, string> = {
  1: "text-amber-400",
  2: "text-zinc-400",
  3: "text-amber-700",
};

function RankBadge({ rank }: { rank: number }) {
  if (rank <= 3) {
    return <Medal className={cn("size-5", MEDAL_CLASS[rank])} />;
  }
  return <span className="w-5 text-center font-mono text-sm text-muted-foreground">{rank}</span>;
}

function RankingRow({ entry }: { entry: GlobalLeaderboardEntry }) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border px-4 py-3",
        entry.rank === 1
          ? "border-amber-400/40 bg-amber-400/5"
          : "border-border/70 bg-card/40"
      )}
    >
      <RankBadge rank={entry.rank} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{entry.user.display_name}</p>
        <p className="text-xs text-muted-foreground">
          {entry.tournaments_played}{" "}
          {entry.tournaments_played === 1 ? "torneo jugado" : "torneos jugados"} ·{" "}
          {formatTokens(entry.balance)} en cuenta
        </p>
      </div>
      <span
        className={cn(
          "font-mono text-sm font-bold",
          entry.total_points >= 0 ? "text-primary" : "text-destructive"
        )}
      >
        {formatSignedTokens(entry.total_points)}
      </span>
    </div>
  );
}

export default function RankingPage() {
  const { data: ranking, isLoading, error } = useQuery({
    queryKey: queryKeys.globalLeaderboard,
    queryFn: api.leaderboard.global,
    staleTime: 30_000,
  });

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="flex items-center gap-2 font-heading text-2xl font-bold tracking-tight">
          <Trophy className="size-6 text-primary" /> Ranking
        </h1>
        <p className="text-sm text-muted-foreground">
          Los mejores predictores de la plataforma, por ganancia neta acumulada en apuestas
          liquidadas en todos los torneos.
        </p>
      </div>

      {isLoading && <LoadingState label="Cargando ranking…" />}
      {error && <ErrorState error={error} />}
      {ranking && ranking.length === 0 && (
        <EmptyState
          title="Todavía no hay ranking"
          description="Aparece acá en cuanto se liquide la primera apuesta de alguien."
        />
      )}
      {ranking && ranking.length > 0 && (
        <div className="flex flex-col gap-2">
          {ranking.map((entry) => (
            <RankingRow key={entry.user.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
