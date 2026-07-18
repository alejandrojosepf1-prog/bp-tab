"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { StatusBadge } from "@/components/status-badge";
import { LoadingState, ErrorState } from "@/components/query-state";
import { PageTransition } from "@/components/motion";

export default function TournamentLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ id: string }>();
  const tournamentId = params.id;

  const { data: tournament, isLoading, error } = useQuery({
    queryKey: queryKeys.tournament(tournamentId),
    queryFn: () => api.tournaments.get(tournamentId),
    staleTime: 60_000,
  });

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 px-4 py-6">
      {isLoading && <LoadingState label="Cargando torneo…" />}
      {error && <ErrorState error={error} />}
      {tournament && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{tournament.name}</h1>
            <StatusBadge status={tournament.status} />
          </div>
          <a
            href={tournament.source_base_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Fuente (Tabbycat) <ExternalLink className="size-3" />
          </a>
        </div>
      )}
      <PageTransition>{children}</PageTransition>
    </div>
  );
}
