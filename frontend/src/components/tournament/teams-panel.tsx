"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";

/**
 * Equipos SIEMPRE por nombre real + sus dos integrantes visibles — nunca IDs ni códigos.
 */
export function TeamsPanel({ tournamentId }: { tournamentId: string }) {
  const { data: teams, isLoading, error } = useQuery({
    queryKey: queryKeys.teams(tournamentId),
    queryFn: () => api.teams.list(tournamentId),
    staleTime: 60_000,
  });

  if (isLoading) return <LoadingState label="Cargando equipos…" />;
  if (error) return <ErrorState error={error} />;
  if (!teams?.length) return <EmptyState title="Sin equipos registrados todavía" />;

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
      {teams
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((team) => (
          <div
            key={team.id}
            className="flex items-start gap-2.5 rounded-lg border border-border/70 bg-card/60 px-3 py-2.5"
          >
            <span className="text-lg leading-none">{team.emoji ?? "🏳️"}</span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{team.name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {team.speakers.length
                  ? team.speakers.map((s) => s.name).join(" · ")
                  : "Integrantes por confirmar"}
              </p>
              {team.institution && (
                <p className="truncate text-[0.7rem] text-muted-foreground/70">
                  {team.institution.name}
                </p>
              )}
            </div>
          </div>
        ))}
    </div>
  );
}
