"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";
import { SortableHead } from "@/components/sortable-head";
import { useSortableData, type SortColumn } from "@/hooks/use-sortable-data";
import type { TeamStanding } from "@/lib/api/types";

const columns: SortColumn<TeamStanding>[] = [
  { key: "rank", label: "#", value: (s) => s.rank },
  { key: "team", label: "Equipo", value: (s) => s.team.name },
  { key: "team_points", label: "Pts equipo", value: (s) => s.team_points },
  { key: "total_speaker_points", label: "Pts oradores", value: (s) => s.total_speaker_points },
  { key: "firsts", label: "1ros", value: (s) => s.firsts },
  { key: "seconds", label: "2dos", value: (s) => s.seconds },
  { key: "thirds", label: "3ros", value: (s) => s.thirds },
  { key: "fourths", label: "4tos", value: (s) => s.fourths },
  { key: "debates_played", label: "Debates", value: (s) => s.debates_played },
];

export default function TournamentOverviewPage() {
  const { id: tournamentId } = useParams<{ id: string }>();

  const { data: standings, isLoading, error } = useQuery({
    queryKey: queryKeys.standings(tournamentId),
    queryFn: () => api.standings.list(tournamentId),
    staleTime: 15_000,
  });

  const { sorted, sortKey, dir, toggle } = useSortableData(standings, columns, "rank");

  const quickLinks = [
    { href: `/tournaments/${tournamentId}/teams`, label: "Equipos" },
    { href: `/tournaments/${tournamentId}/speakers`, label: "Speakers" },
    { href: `/tournaments/${tournamentId}/institutions`, label: "Instituciones" },
    { href: `/tournaments/${tournamentId}/rounds`, label: "Rondas" },
    { href: `/tournaments/${tournamentId}/break`, label: "Break predictor" },
    { href: `/tournaments/${tournamentId}/bets`, label: "Apuestas" },
    { href: `/tournaments/${tournamentId}/leaderboard`, label: "Ranking de apostadores" },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {quickLinks.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="rounded-lg border border-border bg-card px-4 py-3 text-sm font-medium transition-colors hover:border-primary/50 hover:bg-accent"
          >
            {l.label}
          </Link>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Standings generales</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <LoadingState label="Cargando standings…" />}
          {error && <ErrorState error={error} />}
          {standings && standings.length === 0 && (
            <EmptyState title="Sin standings todavía" />
          )}
          {standings && standings.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {columns.map((c) => (
                      <SortableHead
                        key={c.key}
                        columnKey={c.key}
                        label={c.label}
                        activeKey={sortKey}
                        dir={dir}
                        onSort={toggle}
                      />
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sorted.map((s) => (
                    <TableRow key={s.team.id}>
                      <TableCell className="tabular-nums text-muted-foreground">{s.rank}</TableCell>
                      <TableCell>
                        <Link
                          href={`/tournaments/${tournamentId}/teams/${s.team.id}`}
                          className="font-medium hover:text-primary transition-colors"
                        >
                          {s.team.emoji} {s.team.name}
                        </Link>
                      </TableCell>
                      <TableCell className="tabular-nums">{s.team_points}</TableCell>
                      <TableCell className="tabular-nums">{s.total_speaker_points}</TableCell>
                      <TableCell className="tabular-nums">{s.firsts}</TableCell>
                      <TableCell className="tabular-nums">{s.seconds}</TableCell>
                      <TableCell className="tabular-nums">{s.thirds}</TableCell>
                      <TableCell className="tabular-nums">{s.fourths}</TableCell>
                      <TableCell className="tabular-nums">{s.debates_played}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
