"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { DoorOpen } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/status-badge";
import { MotionList, MotionItem } from "@/components/motion";

const POSITION_ORDER = ["OG", "OO", "CG", "CO"] as const;

export default function RoundDebatesPage() {
  const { id: tournamentId, roundId } = useParams<{ id: string; roundId: string }>();

  const { data: debates, isLoading, error } = useQuery({
    queryKey: queryKeys.roundDebates(tournamentId, roundId),
    queryFn: () => api.rounds.debates(tournamentId, roundId),
    staleTime: 20_000,
  });

  const { data: rounds } = useQuery({
    queryKey: queryKeys.rounds(tournamentId),
    queryFn: () => api.rounds.list(tournamentId),
    staleTime: 30_000,
  });

  const round = rounds?.find((r) => String(r.id) === roundId);

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold tracking-tight">
        {round ? round.name : `Ronda ${roundId}`}
      </h2>

      {isLoading && <LoadingState label="Cargando debates…" />}
      {error && <ErrorState error={error} />}
      {debates && debates.length === 0 && <EmptyState title="Sin debates para esta ronda" />}

      {debates && debates.length > 0 && (
        <MotionList className="flex flex-col gap-3">
          {debates.map((debate) => (
            <MotionItem key={debate.id}>
              <Link href={`/tournaments/${tournamentId}/debates/${debate.id}`}>
                <Card className="transition-colors hover:border-primary/50">
                  <CardContent className="flex flex-col gap-3 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="flex items-center gap-1.5 text-sm font-medium">
                        <DoorOpen className="size-4 text-muted-foreground" />
                        {debate.room?.name ?? "Sala por definir"}
                      </span>
                      <StatusBadge status={debate.status} />
                    </div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {POSITION_ORDER.map((pos) => {
                        const teamInfo = debate.teams.find((t) => t.position === pos);
                        return (
                          <div
                            key={pos}
                            className="flex flex-col gap-1 rounded-md border border-border/70 px-2.5 py-2"
                          >
                            <Badge variant="secondary" className="w-fit text-[10px]">
                              {pos}
                            </Badge>
                            {teamInfo ? (
                              <>
                                <span className="truncate text-sm">
                                  {teamInfo.team.emoji} {teamInfo.team.name}
                                </span>
                                <span className="text-xs text-muted-foreground">
                                  {teamInfo.rank_in_debate
                                    ? `Rank ${teamInfo.rank_in_debate}`
                                    : "Sin resultado"}
                                  {teamInfo.team_points !== null && ` · ${teamInfo.team_points} pts`}
                                </span>
                              </>
                            ) : (
                              <span className="text-xs text-muted-foreground">—</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
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
