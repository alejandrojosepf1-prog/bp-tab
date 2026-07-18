import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { Flame } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MotionList, MotionItem } from "@/components/motion";
import type { BetMarket } from "@/lib/api/types";

const BET_TYPE_LABELS: Record<string, string> = {
  champion: "Campeón",
  top_n_break: "Top N break",
  top_n_speakers: "Top N speakers",
  round_winner: "Ganador de ronda",
  head_to_head: "Cara a cara",
  breakout_team: "Equipo revelación",
  best_institution: "Mejor institución",
};

export function OpenMarketsCard({
  tournamentId,
  markets,
}: {
  tournamentId: string;
  markets: BetMarket[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Flame className="size-4 text-orange-400" /> Últimas apuestas abiertas
        </CardTitle>
      </CardHeader>
      <CardContent>
        {markets.length === 0 && (
          <p className="text-sm text-muted-foreground">No hay mercados abiertos ahora mismo.</p>
        )}
        <MotionList className="flex flex-col divide-y divide-border">
          {markets.slice(0, 6).map((m) => (
            <MotionItem key={m.id} className="py-2">
              <Link
                href={`/tournaments/${tournamentId}/bets`}
                className="flex flex-col gap-0.5 text-sm hover:text-primary transition-colors"
              >
                <span className="font-medium">{m.label}</span>
                <span className="text-xs text-muted-foreground">
                  {BET_TYPE_LABELS[m.bet_type] ?? m.bet_type} · cierra{" "}
                  {formatDistanceToNow(new Date(m.closes_at), { addSuffix: true, locale: es })}
                </span>
              </Link>
            </MotionItem>
          ))}
        </MotionList>
        <Link
          href={`/tournaments/${tournamentId}/bets`}
          className="mt-3 inline-block text-xs font-medium text-primary hover:underline"
        >
          Ir a apuestas →
        </Link>
      </CardContent>
    </Card>
  );
}
