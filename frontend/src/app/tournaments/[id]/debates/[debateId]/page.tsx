"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Gavel, Scale, DoorOpen } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState } from "@/components/query-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/status-badge";
import { MotionList, MotionItem } from "@/components/motion";
import type { BpPosition } from "@/lib/api/types";

const POSITION_ORDER: BpPosition[] = ["OG", "OO", "CG", "CO"];
const POSITION_LABELS: Record<BpPosition, string> = {
  OG: "Opening Government",
  OO: "Opening Opposition",
  CG: "Closing Government",
  CO: "Closing Opposition",
};

export default function DebateDetailPage() {
  const { id: tournamentId, debateId } = useParams<{ id: string; debateId: string }>();

  const { data: debate, isLoading, error } = useQuery({
    queryKey: queryKeys.debate(tournamentId, debateId),
    queryFn: () => api.debates.get(tournamentId, debateId),
    staleTime: 20_000,
  });

  if (isLoading) return <LoadingState label="Cargando debate…" />;
  if (error) return <ErrorState error={error} />;
  if (!debate) return null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Link
            href={`/tournaments/${tournamentId}/rounds/${debate.round.id}`}
            className="hover:text-foreground transition-colors"
          >
            {debate.round.name}
          </Link>
          <span>·</span>
          <span className="flex items-center gap-1">
            <DoorOpen className="size-3.5" /> {debate.room?.name ?? "Sala por definir"}
          </span>
          <StatusBadge status={debate.status} />
        </div>
        <h2 className="text-xl font-semibold tracking-tight">
          {debate.motion_text ?? "Moción por confirmar"}
        </h2>
        {debate.ballot_source_url && (
          <a
            href={debate.ballot_source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary hover:underline"
          >
            Ver balota original →
          </a>
        )}
      </div>

      <MotionList className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {POSITION_ORDER.map((pos) => {
          const teamInfo = debate.teams.find((t) => t.position === pos);
          return (
            <MotionItem key={pos}>
              <Card className="h-full">
                <CardHeader>
                  <CardTitle className="flex items-center justify-between text-base">
                    <span className="flex items-center gap-2">
                      <Badge variant="secondary">{pos}</Badge>
                      {POSITION_LABELS[pos]}
                    </span>
                    {teamInfo?.rank_in_debate && (
                      <span className="text-sm font-normal text-muted-foreground">
                        Rank {teamInfo.rank_in_debate}
                      </span>
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {!teamInfo && <p className="text-sm text-muted-foreground">Sin asignar</p>}
                  {teamInfo && (
                    <div className="flex flex-col gap-3">
                      <div className="flex items-center justify-between">
                        <Link
                          href={`/tournaments/${tournamentId}/teams/${teamInfo.team.id}`}
                          className="font-medium hover:text-primary transition-colors"
                        >
                          {teamInfo.team.emoji} {teamInfo.team.name}
                        </Link>
                        {teamInfo.team_points !== null && (
                          <span className="tabular-nums text-sm font-medium">
                            {teamInfo.team_points} pts
                          </span>
                        )}
                      </div>
                      <div className="flex flex-col divide-y divide-border/70">
                        {teamInfo.speakers.map((sp) => (
                          <div
                            key={sp.speaker.id}
                            className="flex items-center justify-between gap-2 py-1.5 text-sm"
                          >
                            <span className="truncate">
                              {sp.speaker.name}
                              {sp.is_iron && (
                                <Badge variant="outline" className="ml-1.5 text-[10px]">
                                  iron
                                </Badge>
                              )}
                              <span className="ml-1.5 text-xs text-muted-foreground capitalize">
                                {sp.role}
                              </span>
                            </span>
                            <span className="tabular-nums font-medium">{sp.score ?? "—"}</span>
                          </div>
                        ))}
                      </div>
                      {teamInfo.speaker_points_total !== null && (
                        <p className="text-xs text-muted-foreground">
                          Total oradores: {teamInfo.speaker_points_total}
                        </p>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            </MotionItem>
          );
        })}
      </MotionList>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gavel className="size-4" /> Jueces
          </CardTitle>
        </CardHeader>
        <CardContent>
          {debate.adjudicators.length === 0 && (
            <p className="text-sm text-muted-foreground">Sin jueces asignados aún.</p>
          )}
          <div className="flex flex-wrap gap-2">
            {debate.adjudicators.map((adj) => (
              <Badge key={adj.adjudicator_id} variant="outline" className="gap-1.5">
                <Scale className="size-3" />
                {adj.name}
                <span className="text-muted-foreground capitalize">({adj.role})</span>
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
