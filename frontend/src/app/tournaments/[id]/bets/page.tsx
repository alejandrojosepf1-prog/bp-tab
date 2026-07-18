"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { Ticket } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { MotionList, MotionItem } from "@/components/motion";
import { PredictionForm } from "@/components/betting/prediction-form";
import type { BetMarket, Institution, Speaker, Team } from "@/lib/api/types";

const BET_TYPE_LABELS: Record<string, string> = {
  champion: "¿Quién será campeón?",
  top_n_break: "Top 3 equipos que rompen",
  top_n_speakers: "Top 3 speakers",
  round_winner: "Ganador de un debate",
  head_to_head: "Cara a cara entre equipos",
  breakout_team: "Equipo revelación",
  best_institution: "Mejor institución",
};

export default function BetsPage() {
  const { id: tournamentId } = useParams<{ id: string }>();
  const { isAuthenticated } = useAuth();

  const { data: markets, isLoading, error } = useQuery({
    queryKey: queryKeys.betMarkets(tournamentId),
    queryFn: () => api.betMarkets.list(tournamentId),
    staleTime: 15_000,
  });

  const { data: teams } = useQuery({
    queryKey: queryKeys.teams(tournamentId),
    queryFn: () => api.teams.list(tournamentId),
    staleTime: 60_000,
  });
  const { data: speakers } = useQuery({
    queryKey: queryKeys.speakers(tournamentId),
    queryFn: () => api.speakers.list(tournamentId),
    staleTime: 60_000,
  });
  const { data: institutions } = useQuery({
    queryKey: queryKeys.institutions(tournamentId),
    queryFn: () => api.institutions.list(tournamentId),
    staleTime: 60_000,
  });

  const openMarkets = markets?.filter((m) => m.status === "open") ?? [];
  const otherMarkets = markets?.filter((m) => m.status !== "open") ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Ticket className="size-5 text-pink-400" /> Predicciones y apuestas
        </h2>
        <p className="text-sm text-muted-foreground">
          Los puntos se llevan en dólares ficticios apostados — nunca hay dinero real de por
          medio.
        </p>
      </div>

      {isLoading && <LoadingState label="Cargando mercados…" />}
      {error && <ErrorState error={error} />}
      {markets && markets.length === 0 && (
        <EmptyState
          title="Todavía no hay mercados de apuestas"
          description="Cuando un administrador abra uno, aparecerá aquí."
        />
      )}

      {openMarkets.length > 0 && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-muted-foreground">Abiertos ahora</h3>
          <MotionList className="flex flex-col gap-3">
            {openMarkets.map((market) => (
              <MotionItem key={market.id}>
                <BetMarketCard
                  tournamentId={tournamentId}
                  market={market}
                  teams={teams ?? []}
                  speakers={speakers ?? []}
                  institutions={institutions ?? []}
                  isAuthenticated={isAuthenticated}
                />
              </MotionItem>
            ))}
          </MotionList>
        </div>
      )}

      {otherMarkets.length > 0 && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-muted-foreground">Cerrados / liquidados</h3>
          <MotionList className="flex flex-col gap-2">
            {otherMarkets.map((market) => (
              <MotionItem key={market.id}>
                <Card className="opacity-80">
                  <CardContent className="flex flex-wrap items-center justify-between gap-2 py-3">
                    <div>
                      <p className="text-sm font-medium">{market.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {BET_TYPE_LABELS[market.bet_type] ?? market.bet_type}
                      </p>
                    </div>
                    <StatusBadge status={market.status} />
                  </CardContent>
                </Card>
              </MotionItem>
            ))}
          </MotionList>
        </div>
      )}
    </div>
  );
}

function BetMarketCard({
  tournamentId,
  market,
  teams,
  speakers,
  institutions,
  isAuthenticated,
}: {
  tournamentId: string;
  market: BetMarket;
  teams: Team[];
  speakers: Speaker[];
  institutions: Institution[];
  isAuthenticated: boolean;
}) {
  const { data: myPrediction } = useQuery({
    queryKey: queryKeys.myPrediction(market.id),
    queryFn: () => api.betMarkets.myPrediction(market.id),
    enabled: isAuthenticated,
    staleTime: 10_000,
  });

  // `Date.now()` is impure and must not be called during render; a lazily-initialized state
  // value is the sanctioned way to snapshot "now" once, at mount.
  const [now] = useState(() => Date.now());
  const closesAt = new Date(market.closes_at);
  const isPastClose = closesAt.getTime() < now;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">{market.label}</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            {BET_TYPE_LABELS[market.bet_type] ?? market.bet_type}
            {market.description ? ` · ${market.description}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <StatusBadge status={market.status} />
          <span className="text-[0.7rem] text-muted-foreground">
            {isPastClose ? "cerró" : "cierra"}{" "}
            {formatDistanceToNow(closesAt, { addSuffix: true, locale: es })}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {!isAuthenticated && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
            Inicia sesión para predecir en este mercado.
            <Button size="sm" variant="outline" render={<Link href="/login" />}>
              Iniciar sesión
            </Button>
          </div>
        )}

        {isAuthenticated && isPastClose && (
          <p className="text-sm text-muted-foreground">Este mercado ya cerró.</p>
        )}

        {isAuthenticated && !isPastClose && (
          <PredictionForm
            tournamentId={tournamentId}
            market={market}
            existing={myPrediction ?? null}
            teams={teams}
            speakers={speakers}
            institutions={institutions}
          />
        )}

        {isAuthenticated && myPrediction && (
          <p className="mt-3 text-xs text-muted-foreground">
            Ya tienes una predicción guardada para este mercado
            {myPrediction.points_awarded !== null && (
              <>
                {" "}
                — resultado:{" "}
                <span
                  className={
                    myPrediction.points_awarded >= 0 ? "text-emerald-400" : "text-red-400"
                  }
                >
                  {myPrediction.points_awarded >= 0 ? "+" : "-"}$
                  {Math.abs(myPrediction.points_awarded).toLocaleString("es")}
                </span>
              </>
            )}
            .
          </p>
        )}
      </CardContent>
    </Card>
  );
}
