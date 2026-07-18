"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState } from "@/components/query-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function TeamDetailPage() {
  const { id: tournamentId, teamId } = useParams<{ id: string; teamId: string }>();

  const { data: team, isLoading, error } = useQuery({
    queryKey: queryKeys.team(tournamentId, teamId),
    queryFn: () => api.teams.get(tournamentId, teamId),
    staleTime: 60_000,
  });

  const { data: standings } = useQuery({
    queryKey: queryKeys.standings(tournamentId),
    queryFn: () => api.standings.list(tournamentId),
    staleTime: 15_000,
  });

  const standing = standings?.find((s) => s.team.id === team?.id);

  if (isLoading) return <LoadingState label="Cargando equipo…" />;
  if (error) return <ErrorState error={error} />;
  if (!team) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <span className="text-2xl">{team.emoji}</span> {team.name}
        </h2>
        {team.institution && <Badge variant="secondary">{team.institution.name}</Badge>}
      </div>

      {standing && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatBox label="Rank" value={`#${standing.rank}`} />
          <StatBox label="Pts equipo" value={standing.team_points} />
          <StatBox label="Pts oradores" value={standing.total_speaker_points} />
          <StatBox label="Debates" value={standing.debates_played} />
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Speakers</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nombre</TableHead>
                <TableHead>Categorías</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {team.speakers.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="flex flex-wrap gap-1">
                    {s.categories.length > 0
                      ? s.categories.map((c) => (
                          <Badge key={c} variant="outline">
                            {c}
                          </Badge>
                        ))
                      : <span className="text-muted-foreground text-sm">—</span>}
                  </TableCell>
                </TableRow>
              ))}
              {team.speakers.length === 0 && (
                <TableRow>
                  <TableCell colSpan={2} className="text-center text-muted-foreground">
                    Sin speakers asignados
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}
