"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Gauge } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BreakGauge } from "@/components/break-gauge";

export function BreakProbabilityCard({ tournamentId }: { tournamentId: string }) {
  const { data: categories, isLoading: loadingCats } = useQuery({
    queryKey: queryKeys.breakCategories(tournamentId),
    queryFn: () => api.breakCategories.list(tournamentId),
    staleTime: 60_000,
  });

  const generalCategory = categories?.find((c) => c.is_general) ?? categories?.[0];

  const { data: predictions, isLoading: loadingPredictions } = useQuery({
    queryKey: queryKeys.breakPredictions(tournamentId, generalCategory?.id ?? "none"),
    queryFn: () => api.breakCategories.predictions(tournamentId, generalCategory!.id),
    enabled: !!generalCategory,
    staleTime: 15_000,
  });

  const borderline = predictions
    ?.filter((p) => p.status === "alive")
    .sort((a, b) => b.probability - a.probability)
    .slice(0, 5);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Gauge className="size-4 text-emerald-400" /> Probabilidad de break
        </CardTitle>
      </CardHeader>
      <CardContent>
        {(loadingCats || loadingPredictions) && (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}
        {!loadingCats && !generalCategory && (
          <p className="text-sm text-muted-foreground">Aún no hay categorías de break.</p>
        )}
        {generalCategory && predictions && (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">
              Equipos en la frontera del break — {generalCategory.name}
            </p>
            {borderline?.map((p) => (
              <div key={p.team.id} className="flex flex-col gap-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="truncate">
                    {p.team.emoji} {p.team.name}
                  </span>
                  <span className="tabular-nums font-medium">
                    {Math.round(p.probability * 100)}%
                  </span>
                </div>
                <BreakGauge probability={p.probability} colorClass="bg-amber-400" />
              </div>
            ))}
            {borderline?.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No hay equipos en zona de riesgo por ahora.
              </p>
            )}
            <Link
              href={`/tournaments/${tournamentId}/break`}
              className="mt-1 text-xs font-medium text-primary hover:underline"
            >
              Ver predictor completo →
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
