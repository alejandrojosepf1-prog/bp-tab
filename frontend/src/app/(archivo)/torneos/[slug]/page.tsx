"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Quote, Trophy } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";

const STATUS_LABEL: Record<string, string> = {
  upcoming: "Por empezar",
  in_progress: "En curso",
  break_pending: "Definiendo el break",
  eliminations: "Eliminatorias",
  completed: "Finalizado",
};

export default function TorneoPage() {
  const { slug } = useParams<{ slug: string }>();

  const {
    data: tournament,
    isLoading: loadingTournament,
    error: tournamentError,
  } = useQuery({
    queryKey: queryKeys.tournamentBySlug(slug),
    queryFn: () => api.tournaments.getBySlug(slug),
  });

  const { data: champion } = useQuery({
    queryKey: queryKeys.team(tournament?.id ?? "", tournament?.champion_team_id ?? ""),
    queryFn: () => api.teams.get(tournament!.id, tournament!.champion_team_id!),
    enabled: !!tournament?.champion_team_id,
  });

  const { data: rounds } = useQuery({
    queryKey: queryKeys.rounds(tournament?.id ?? ""),
    queryFn: () => api.rounds.list(tournament!.id),
    enabled: !!tournament,
  });

  if (loadingTournament) return <LoadingState label="Cargando torneo…" />;
  if (tournamentError || !tournament)
    return <ErrorState error={tournamentError ?? new Error("Torneo no encontrado")} />;

  const releasedRounds = (rounds ?? []).filter((r) => r.motion_text);

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="font-heading text-3xl font-bold tracking-tight">{tournament.name}</h1>
          <Badge variant="outline">{STATUS_LABEL[tournament.status] ?? tournament.status}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
          {tournament.year && (
            <span className="flex items-center gap-1.5">
              <Calendar className="size-3.5" /> {tournament.year}
            </span>
          )}
          {champion && (
            <span className="flex items-center gap-1.5">
              <Trophy className="size-3.5 text-secondary" /> Campeón: {champion.name}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="font-heading text-lg font-bold">Rondas</h2>
        {releasedRounds.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Sin mociones publicadas todavía para este torneo.
          </p>
        ) : (
          <div className="flex flex-col gap-2.5">
            {releasedRounds.map((round) => (
              <div key={round.id} className="rounded-xl border border-border bg-card p-4">
                <div className="mb-1.5 flex items-center gap-2 text-sm font-medium">
                  {round.name}
                </div>
                <div className="flex items-start gap-2 text-sm text-muted-foreground">
                  <Quote className="mt-0.5 size-3.5 shrink-0" />
                  <p>{round.motion_text}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
