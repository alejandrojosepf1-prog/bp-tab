"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Coins,
  Landmark,
  TrendingDown,
  TrendingUp,
  Users,
  Wallet,
} from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { TournamentChips } from "@/components/admin/tournament-chips";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";

function StatCard({
  label,
  value,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  icon: typeof Wallet;
  tone?: "neutral" | "positive" | "negative";
}) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-border/70 bg-card/50 p-4">
      <span className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-muted-foreground">
        <Icon className="size-3.5" /> {label}
      </span>
      <span
        className={cn(
          "font-mono text-xl font-bold",
          tone === "positive" && "text-primary",
          tone === "negative" && "text-destructive"
        )}
      >
        {value}
      </span>
    </div>
  );
}

const fmt = (n: number) => `${n.toLocaleString("es", { maximumFractionDigits: 0 })} tokens`;
const fmtCount = (n: number) => n.toLocaleString("es");

export default function AdminFinancePage() {
  const [tournamentId, setTournamentId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.adminGameEconomy(tournamentId ?? undefined),
    queryFn: () => api.admin.gameEconomy(tournamentId ?? undefined),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  return (
    <div className="flex flex-col gap-5">
      <TournamentChips value={tournamentId} onChange={setTournamentId} allowAll />
      <p className="text-xs text-muted-foreground">
        Claim no tiene casa: nadie cobra comisión ni respalda los pagos con un fondo propio. Esto
        es una vista de la economía de tokens del juego, no de ganancias de un operador.
      </p>

      {isLoading && <LoadingState label="Calculando economía…" />}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <StatCard
              label="Tokens en circulación"
              value={fmt(data.tokens_in_circulation)}
              icon={Coins}
            />
            <StatCard
              label="Comprometido en apuestas abiertas"
              value={fmt(data.total_staked_open)}
              icon={ArrowDownToLine}
            />
            <StatCard
              label="Apostado histórico (liquidado)"
              value={fmt(data.total_staked_settled)}
              icon={Wallet}
            />
            <StatCard label="Pagado a ganadores" value={fmt(data.total_paid_out)} icon={ArrowUpFromLine} />
            <StatCard
              label="Inflación neta de tokens"
              value={`${data.net_token_inflation >= 0 ? "+" : "−"}${fmt(Math.abs(data.net_token_inflation))}`}
              icon={data.net_token_inflation >= 0 ? TrendingUp : TrendingDown}
              tone={data.net_token_inflation >= 0 ? "positive" : "negative"}
            />
            <StatCard
              label="Apostadores activos"
              value={fmtCount(data.active_bettors_count)}
              icon={Users}
            />
            <StatCard
              label="Apuestas abiertas / liquidadas"
              value={`${fmtCount(data.open_predictions_count)} / ${fmtCount(data.settled_predictions_count)}`}
              icon={Activity}
            />
            <StatCard
              label="Pago proyectado — peor caso"
              value={`−${fmt(Math.abs(data.payout_spread_worst_case_total))}`}
              icon={TrendingDown}
              tone="negative"
            />
            <StatCard
              label="Pago proyectado — mejor caso"
              value={`+${fmt(Math.abs(data.payout_spread_best_case_total))}`}
              icon={TrendingUp}
              tone="positive"
            />
          </div>

          <section className="flex flex-col gap-3">
            <h2 className="flex items-center gap-2 font-heading text-base font-bold">
              <Landmark className="size-4 text-primary" /> Pago proyectado por mercado abierto
            </h2>
            <p className="text-xs text-muted-foreground">
              Cuántos tokens se pagarían según cómo resuelva cada mercado todavía abierto, basado
              en las apuestas pendientes actuales — no es riesgo de ningún operador, es solo la
              variación posible del pago.
            </p>
            {data.payout_spread.length === 0 && (
              <EmptyState
                title="Sin pagos pendientes por proyectar"
                description="No hay apuestas abiertas en este momento."
              />
            )}
            {data.payout_spread.length > 0 && (
              <div className="flex flex-col gap-2">
                {data.payout_spread.map((m) => (
                  <div
                    key={m.market_id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-card/40 p-4"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold">{m.market_label}</p>
                      <p className="text-xs text-muted-foreground">
                        Pool: <span className="font-mono">{fmt(m.pool_total)}</span>
                      </p>
                    </div>
                    <div className="flex gap-4 text-sm">
                      <span className="font-mono font-medium text-destructive">
                        peor: −{fmt(Math.abs(m.worst_case))}
                      </span>
                      <span className="font-mono font-medium text-primary">
                        mejor: +{fmt(Math.abs(m.best_case))}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
