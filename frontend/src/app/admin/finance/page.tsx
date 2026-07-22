"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Landmark, TrendingDown, TrendingUp, Wallet, ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
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

const fmt = (n: number) => `$${n.toLocaleString("es", { maximumFractionDigits: 0 })}`;

export default function AdminFinancePage() {
  const [tournamentId, setTournamentId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.adminHouseFinance(tournamentId ?? undefined),
    queryFn: () => api.admin.houseFinance(tournamentId ?? undefined),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  return (
    <div className="flex flex-col gap-5">
      <TournamentChips value={tournamentId} onChange={setTournamentId} allowAll />

      {isLoading && <LoadingState label="Calculando finanzas…" />}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <StatCard label="Entrando (apuestas abiertas)" value={fmt(data.total_staked_open)} icon={ArrowDownToLine} />
            <StatCard label="Apostado histórico (liquidado)" value={fmt(data.total_staked_settled)} icon={Wallet} />
            <StatCard label="Pagado a ganadores" value={fmt(data.total_paid_out)} icon={ArrowUpFromLine} />
            <StatCard
              label="Ganancia/pérdida neta liquidada"
              value={`${data.realized_net_profit >= 0 ? "+" : "−"}${fmt(Math.abs(data.realized_net_profit))}`}
              icon={data.realized_net_profit >= 0 ? TrendingUp : TrendingDown}
              tone={data.realized_net_profit >= 0 ? "positive" : "negative"}
            />
            <StatCard
              label="Exposición — peor caso"
              value={`−${fmt(Math.abs(data.exposure_worst_case_total))}`}
              icon={TrendingDown}
              tone="negative"
            />
            <StatCard
              label="Exposición — mejor caso"
              value={`+${fmt(Math.abs(data.exposure_best_case_total))}`}
              icon={TrendingUp}
              tone="positive"
            />
          </div>

          <section className="flex flex-col gap-3">
            <h2 className="flex items-center gap-2 font-heading text-base font-bold">
              <Landmark className="size-4 text-primary" /> Exposición por mercado abierto
            </h2>
            <p className="text-xs text-muted-foreground">
              Proyección de cuánto podría ganar o perder la casa según cómo resuelva cada mercado
              todavía abierto, basado en las apuestas pendientes actuales.
            </p>
            {data.exposure.length === 0 && (
              <EmptyState
                title="Sin exposición pendiente"
                description="No hay apuestas abiertas en este momento."
              />
            )}
            {data.exposure.length > 0 && (
              <div className="flex flex-col gap-2">
                {data.exposure.map((m) => (
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
