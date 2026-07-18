"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Gauge, Trophy } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/status-badge";
import { BreakGauge } from "@/components/break-gauge";
import { MotionList, MotionItem } from "@/components/motion";
import type { BreakAssessment } from "@/lib/api/types";

const STATUS_ORDER: Record<string, number> = { safe: 0, alive: 1, eliminated: 2 };
const GAUGE_COLOR: Record<string, string> = {
  safe: "bg-emerald-400",
  alive: "bg-amber-400",
  eliminated: "bg-red-400",
};

export default function BreakPredictorPage() {
  const { id: tournamentId } = useParams<{ id: string }>();
  // Derived, not an effect: the preferred category is fully computed from `categories`.
  // `manualCategoryId` only holds an explicit user choice from the dropdown.
  const [manualCategoryId, setManualCategoryId] = useState<string | null>(null);

  const { data: categories, isLoading: loadingCategories } = useQuery({
    queryKey: queryKeys.breakCategories(tournamentId),
    queryFn: () => api.breakCategories.list(tournamentId),
    staleTime: 60_000,
  });

  const preferredCategory = categories?.find((c) => c.is_general) ?? categories?.[0];
  const categoryId = manualCategoryId ?? (preferredCategory ? String(preferredCategory.id) : null);

  const { data: officialBreak, isLoading: loadingOfficial } = useQuery({
    queryKey: queryKeys.officialBreak(tournamentId, categoryId ?? "none"),
    queryFn: () => api.breakCategories.officialBreak(tournamentId, categoryId!),
    enabled: !!categoryId,
    staleTime: 30_000,
  });

  const hasOfficialBreak = !!officialBreak?.length;

  const { data: predictions, isLoading: loadingPredictions, error } = useQuery({
    queryKey: queryKeys.breakPredictions(tournamentId, categoryId ?? "none"),
    queryFn: () => api.breakCategories.predictions(tournamentId, categoryId!),
    enabled: !!categoryId && !hasOfficialBreak,
    staleTime: 15_000,
  });

  const sortedPredictions = predictions
    ? [...predictions].sort((a, b) => {
        const byStatus = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
        if (byStatus !== 0) return byStatus;
        return b.probability - a.probability;
      })
    : undefined;

  const selectedCategory = categories?.find((c) => String(c.id) === categoryId);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Gauge className="size-5 text-emerald-400" /> Break Predictor
          </h2>
          <p className="text-sm text-muted-foreground">
            Proyección en vivo de quién rompe — se reemplaza por el resultado oficial en cuanto
            el torneo lo publica.
          </p>
        </div>
        {categories && categories.length > 1 && (
          <Select value={categoryId ?? ""} onValueChange={setManualCategoryId}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="Categoría" />
            </SelectTrigger>
            <SelectContent>
              {categories.map((c) => (
                <SelectItem key={c.id} value={String(c.id)}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {(loadingCategories || loadingOfficial) && <LoadingState label="Cargando categorías…" />}
      {!loadingCategories && categories?.length === 0 && (
        <EmptyState title="Este torneo todavía no tiene categorías de break configuradas" />
      )}
      {error && <ErrorState error={error} />}

      {hasOfficialBreak && officialBreak && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Trophy className="size-4 text-amber-400" /> Break oficial — {selectedCategory?.name}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MotionList className="flex flex-col divide-y divide-border">
              {officialBreak
                .sort((a, b) => a.rank - b.rank)
                .map((entry) => (
                  <MotionItem
                    key={entry.team.id}
                    className="flex items-center justify-between gap-3 py-2.5 text-sm"
                  >
                    <span className="flex items-center gap-2">
                      <span className="w-6 tabular-nums text-muted-foreground">#{entry.rank}</span>
                      <span className="text-base">{entry.team.emoji}</span>
                      <span className="font-medium">{entry.team.name}</span>
                    </span>
                  </MotionItem>
                ))}
            </MotionList>
          </CardContent>
        </Card>
      )}

      {!hasOfficialBreak && categoryId && (
        <>
          {loadingPredictions && <LoadingState label="Calculando predicción…" />}
          {sortedPredictions && sortedPredictions.length === 0 && (
            <EmptyState
              title="Sin datos suficientes todavía"
              description="La predicción aparecerá una vez se complete al menos una ronda."
            />
          )}
          {sortedPredictions && sortedPredictions.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{selectedCategory?.name}</CardTitle>
              </CardHeader>
              <CardContent>
                <MotionList className="flex flex-col divide-y divide-border">
                  {sortedPredictions.map((p: BreakAssessment) => (
                    <MotionItem key={p.team.id} className="flex flex-col gap-2 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-sm">
                          <span className="text-base">{p.team.emoji}</span>
                          <span className="font-medium">{p.team.name}</span>
                        </span>
                        <div className="flex items-center gap-2">
                          {p.status === "alive" && p.points_needed_for_safety !== null && (
                            <span className="text-xs text-muted-foreground">
                              +{p.points_needed_for_safety} pts para asegurar
                            </span>
                          )}
                          <span className="w-10 text-right text-sm font-semibold tabular-nums">
                            {Math.round(p.probability * 100)}%
                          </span>
                          <StatusBadge status={p.status} />
                        </div>
                      </div>
                      <BreakGauge probability={p.probability} colorClass={GAUGE_COLOR[p.status]} />
                    </MotionItem>
                  ))}
                </MotionList>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
