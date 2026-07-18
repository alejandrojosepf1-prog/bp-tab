import Link from "next/link";
import { Medal } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MotionList, MotionItem } from "@/components/motion";
import type { LeaderboardEntry } from "@/lib/api/types";

const MEDAL_COLORS = ["text-amber-400", "text-zinc-300", "text-amber-700"];

export function TopBettorsCard({
  tournamentId,
  entries,
}: {
  tournamentId: string;
  entries: LeaderboardEntry[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Medal className="size-4 text-amber-400" /> Mejores apostadores
        </CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 && (
          <p className="text-sm text-muted-foreground">Aún no hay puntos otorgados.</p>
        )}
        <MotionList className="flex flex-col divide-y divide-border">
          {entries.slice(0, 5).map((e, i) => (
            <MotionItem
              key={e.user.id}
              className="flex items-center justify-between gap-2 py-2 text-sm"
            >
              <span className="flex items-center gap-2 truncate">
                <Medal className={`size-3.5 ${MEDAL_COLORS[i] ?? "text-transparent"}`} />
                <span className="truncate">{e.user.display_name}</span>
              </span>
              <span className="tabular-nums font-medium">${e.total_points.toLocaleString("es")}</span>
            </MotionItem>
          ))}
        </MotionList>
        <Link
          href={`/tournaments/${tournamentId}/leaderboard`}
          className="mt-3 inline-block text-xs font-medium text-primary hover:underline"
        >
          Ver ranking completo →
        </Link>
      </CardContent>
    </Card>
  );
}
