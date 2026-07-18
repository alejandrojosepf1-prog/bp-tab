"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Trophy } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";
import { SortableHead } from "@/components/sortable-head";
import { useSortableData } from "@/hooks/use-sortable-data";
import { cn } from "@/lib/utils";
import type { LeaderboardEntry } from "@/lib/api/types";

const MEDAL_STYLES = [
  "bg-amber-400/15 text-amber-400 border-amber-400/40",
  "bg-zinc-300/15 text-zinc-300 border-zinc-300/40",
  "bg-amber-700/15 text-amber-600 border-amber-700/40",
];

export default function LeaderboardPage() {
  const { id: tournamentId } = useParams<{ id: string }>();
  const { user } = useAuth();

  const { data: entries, isLoading, error } = useQuery({
    queryKey: queryKeys.leaderboard(tournamentId),
    queryFn: () => api.leaderboard.list(tournamentId),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const { sorted, sortKey, dir, toggle } = useSortableData<LeaderboardEntry>(
    entries,
    [
      { key: "rank", label: "Puesto", value: (e) => e.rank },
      { key: "name", label: "Apostador", value: (e) => e.user.display_name },
      { key: "total", label: "Dólares (ficticios) ganados", value: (e) => e.total_points },
    ],
    "rank",
    "asc"
  );

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Trophy className="size-5 text-amber-400" /> Ranking de apostadores
        </h2>
        <p className="text-sm text-muted-foreground">
          Puntaje llevado en dólares ficticios apostados — no hay dinero real involucrado.
        </p>
      </div>

      {isLoading && <LoadingState label="Cargando ranking…" />}
      {error && <ErrorState error={error} />}
      {entries && entries.length === 0 && (
        <EmptyState
          title="Todavía no hay puntajes"
          description="El ranking aparecerá una vez se liquide la primera apuesta."
        />
      )}

      {entries && entries.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead label="Puesto" columnKey="rank" activeKey={sortKey} dir={dir} onSort={toggle} />
                  <SortableHead label="Apostador" columnKey="name" activeKey={sortKey} dir={dir} onSort={toggle} />
                  <SortableHead
                    label="Dólares ganados"
                    columnKey="total"
                    activeKey={sortKey}
                    dir={dir}
                    onSort={toggle}
                    className="text-right"
                  />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((entry) => (
                  <TableRow key={entry.user.id} className={cn(user?.id === entry.user.id && "bg-accent/40")}>
                    <TableCell>
                      <span
                        className={cn(
                          "inline-flex size-7 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
                          MEDAL_STYLES[entry.rank - 1] ?? "border-border text-muted-foreground"
                        )}
                      >
                        {entry.rank}
                      </span>
                    </TableCell>
                    <TableCell className="font-medium">
                      {entry.user.display_name}
                      {user?.id === entry.user.id && (
                        <span className="ml-2 text-xs text-muted-foreground">(tú)</span>
                      )}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums font-semibold",
                        entry.total_points >= 0 ? "text-emerald-400" : "text-red-400"
                      )}
                    >
                      {entry.total_points >= 0 ? "+" : "-"}$
                      {Math.abs(entry.total_points).toLocaleString("es")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
