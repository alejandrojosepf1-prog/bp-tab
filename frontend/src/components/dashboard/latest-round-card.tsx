import Link from "next/link";
import { CalendarClock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import type { Round } from "@/lib/api/types";

export function LatestRoundCard({
  tournamentId,
  round,
}: {
  tournamentId: string;
  round: Round | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="size-4 text-blue-400" /> Última ronda
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!round && <p className="text-sm text-muted-foreground">Aún no hay rondas registradas.</p>}
        {round && (
          <Link
            href={`/tournaments/${tournamentId}/rounds/${round.id}`}
            className="flex flex-col gap-2 rounded-lg border border-border p-3 transition-colors hover:border-primary/50"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{round.name}</span>
              <StatusBadge status={round.status} />
            </div>
            <span className="text-xs text-muted-foreground capitalize">
              Ronda #{round.seq} · {round.stage === "preliminary" ? "Preliminar" : "Eliminatoria"}
            </span>
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
