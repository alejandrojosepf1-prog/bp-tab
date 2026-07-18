"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ListOrdered } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { MotionList, MotionItem } from "@/components/motion";

export default function RoundsPage() {
  const { id: tournamentId } = useParams<{ id: string }>();

  const { data: rounds, isLoading, error } = useQuery({
    queryKey: queryKeys.rounds(tournamentId),
    queryFn: () => api.rounds.list(tournamentId),
    staleTime: 30_000,
  });

  return (
    <div className="flex flex-col gap-4">
      <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <ListOrdered className="size-5" /> Rondas
      </h2>

      {isLoading && <LoadingState label="Cargando rondas…" />}
      {error && <ErrorState error={error} />}
      {rounds && rounds.length === 0 && <EmptyState title="Sin rondas registradas" />}

      {rounds && rounds.length > 0 && (
        <MotionList className="flex flex-col gap-2">
          {rounds
            .slice()
            .sort((a, b) => a.seq - b.seq)
            .map((round) => (
              <MotionItem key={round.id}>
                <Link href={`/tournaments/${tournamentId}/rounds/${round.id}`}>
                  <Card className="transition-colors hover:border-primary/50">
                    <CardContent className="flex items-center justify-between gap-3 py-4">
                      <div className="flex items-center gap-3">
                        <span className="tabular-nums text-sm text-muted-foreground">
                          #{round.seq}
                        </span>
                        <span className="font-medium">{round.name}</span>
                        <span className="text-xs text-muted-foreground capitalize">
                          {round.stage === "preliminary" ? "Preliminar" : "Eliminatoria"}
                        </span>
                      </div>
                      <StatusBadge status={round.status} />
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
