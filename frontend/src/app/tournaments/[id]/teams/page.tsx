"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MotionList, MotionItem } from "@/components/motion";

export default function TeamsPage() {
  const { id: tournamentId } = useParams<{ id: string }>();

  const { data: teams, isLoading, error } = useQuery({
    queryKey: queryKeys.teams(tournamentId),
    queryFn: () => api.teams.list(tournamentId),
    staleTime: 60_000,
  });

  return (
    <div className="flex flex-col gap-4">
      <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <Users className="size-5" /> Equipos
      </h2>

      {isLoading && <LoadingState label="Cargando equipos…" />}
      {error && <ErrorState error={error} />}
      {teams && teams.length === 0 && <EmptyState title="Sin equipos registrados" />}

      {teams && teams.length > 0 && (
        <MotionList className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {teams.map((team) => (
            <MotionItem key={team.id}>
              <Link href={`/tournaments/${tournamentId}/teams/${team.id}`}>
                <Card className="h-full transition-colors hover:border-primary/50">
                  <CardContent className="flex flex-col gap-2 pt-6">
                    <div className="flex items-center gap-2 text-base font-medium">
                      <span className="text-xl">{team.emoji}</span>
                      {team.name}
                    </div>
                    {team.institution && (
                      <Badge variant="secondary" className="w-fit">
                        {team.institution.code}
                      </Badge>
                    )}
                    <p className="truncate text-xs text-muted-foreground">
                      {team.speakers.map((s) => s.name).join(", ") || "Sin speakers asignados"}
                    </p>
                  </CardContent>
                </Card>
              </Link>
            </MotionItem>
          ))}
        </MotionList>
      )}
    </div>
  );
}
