"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Mic2 } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { SortableHead } from "@/components/sortable-head";
import { useSortableData, type SortColumn } from "@/hooks/use-sortable-data";
import type { Speaker, Team } from "@/lib/api/types";

interface SpeakerRow extends Speaker {
  teamName?: string;
}

export default function SpeakersPage() {
  const { id: tournamentId } = useParams<{ id: string }>();

  const { data: speakers, isLoading, error } = useQuery({
    queryKey: queryKeys.speakers(tournamentId),
    queryFn: () => api.speakers.list(tournamentId),
    staleTime: 60_000,
  });

  const { data: teams } = useQuery({
    queryKey: queryKeys.teams(tournamentId),
    queryFn: () => api.teams.list(tournamentId),
    staleTime: 60_000,
  });

  const teamById = new Map<number, Team>((teams ?? []).map((t) => [t.id, t]));

  const rows: SpeakerRow[] = (speakers ?? []).map((s) => ({
    ...s,
    teamName: s.team_id ? teamById.get(s.team_id)?.name : undefined,
  }));

  const columns: SortColumn<SpeakerRow>[] = [
    { key: "name", label: "Nombre", value: (s) => s.name },
    { key: "team", label: "Equipo", value: (s) => s.teamName ?? "" },
  ];

  const { sorted, sortKey, dir, toggle } = useSortableData(rows, columns, "name");

  return (
    <div className="flex flex-col gap-4">
      <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <Mic2 className="size-5" /> Speakers
      </h2>

      {isLoading && <LoadingState label="Cargando speakers…" />}
      {error && <ErrorState error={error} />}
      {rows.length === 0 && !isLoading && <EmptyState title="Sin speakers registrados" />}

      {rows.length > 0 && (
        <Card>
          <CardContent className="pt-6">
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
                    <TableHead>Categorías</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sorted.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-medium">{s.name}</TableCell>
                      <TableCell>
                        {s.team_id ? (
                          <Link
                            href={`/tournaments/${tournamentId}/teams/${s.team_id}`}
                            className="hover:text-primary transition-colors"
                          >
                            {s.teamName ?? `#${s.team_id}`}
                          </Link>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="flex flex-wrap gap-1">
                        {s.categories.map((c) => (
                          <Badge key={c} variant="outline">
                            {c}
                          </Badge>
                        ))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
