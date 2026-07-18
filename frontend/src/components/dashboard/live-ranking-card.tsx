"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Trophy } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/query-state";
import { MotionList, MotionItem } from "@/components/motion";

export function LiveRankingCard({ tournamentId }: { tournamentId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.standings(tournamentId),
    queryFn: () => api.standings.list(tournamentId),
    staleTime: 15_000,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Trophy className="size-4 text-amber-400" /> Ranking en vivo
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        )}
        {error && <ErrorState error={error} />}
        {data && (
          <MotionList className="flex flex-col divide-y divide-border">
            {data.slice(0, 5).map((s) => (
              <MotionItem key={s.team.id}>
                <Link
                  href={`/tournaments/${tournamentId}/teams/${s.team.id}`}
                  className="flex items-center justify-between gap-2 py-2 text-sm hover:text-primary transition-colors"
                >
                  <span className="flex items-center gap-2 truncate">
                    <span className="w-5 shrink-0 text-muted-foreground tabular-nums">
                      {s.rank}
                    </span>
                    <span className="truncate">
                      {s.team.emoji} {s.team.name}
                    </span>
                  </span>
                  <span className="shrink-0 tabular-nums font-medium">{s.team_points} pts</span>
                </Link>
              </MotionItem>
            ))}
            {data.length === 0 && (
              <p className="py-4 text-sm text-muted-foreground">Sin datos de standings aún.</p>
            )}
          </MotionList>
        )}
      </CardContent>
    </Card>
  );
}
