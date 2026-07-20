import Link from "next/link";
import { Ticket } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import type { Prediction } from "@/lib/api/types";

export function MyPredictionsCard({
  tournamentId,
  predictions,
}: {
  tournamentId: string;
  predictions: Prediction[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Ticket className="size-4 text-pink-400" /> Mis predicciones
        </CardTitle>
      </CardHeader>
      <CardContent>
        {predictions.length === 0 && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-muted-foreground">Todavía no has hecho predicciones.</p>
            <Link
              href={`/tournaments/${tournamentId}/bets`}
              className="text-xs font-medium text-primary hover:underline"
            >
              Ver mercados abiertos →
            </Link>
          </div>
        )}
        <div className="flex flex-col divide-y divide-border">
          {predictions.slice(0, 6).map((p) => (
            <div key={p.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="text-muted-foreground">Mercado #{p.bet_market_id}</span>
              <div className="flex items-center gap-2">
                {p.points_awarded === null ? (
                  <span className="tabular-nums text-muted-foreground">
                    ${p.stake_amount} @ {p.odds}x
                  </span>
                ) : (
                  <span
                    className={`tabular-nums font-medium ${p.points_awarded > 0 ? "text-emerald-400" : "text-red-400"}`}
                  >
                    {p.points_awarded > 0
                      ? `+$${p.points_awarded.toLocaleString("es")}`
                      : `-$${p.stake_amount.toLocaleString("es")}`}
                  </span>
                )}
                <StatusBadge status={p.status} />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
