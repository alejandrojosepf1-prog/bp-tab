"use client";

import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { UserRound, Wallet, History, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { RequireAuth } from "@/components/auth/require-auth";
import { LoadingState, EmptyState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { MyPrediction } from "@/lib/api/types";

const PREDICTION_STATUS: Record<string, { label: string; className: string }> = {
  open: { label: "Abierta", className: "border-primary/40 bg-primary/10 text-primary" },
  locked: { label: "Bloqueada", className: "border-amber-500/40 bg-amber-500/10 text-amber-400" },
  settled: { label: "Liquidada", className: "border-border bg-muted text-muted-foreground" },
};

function HistoryRow({ prediction }: { prediction: MyPrediction }) {
  const settled = prediction.status === "settled";
  const won = settled && (prediction.points_awarded ?? 0) > 0;
  const status = PREDICTION_STATUS[prediction.status];
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border/70 bg-card/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{prediction.market_label}</p>
          <p className="truncate text-xs text-muted-foreground">
            {prediction.tournament_name} ·{" "}
            {format(new Date(prediction.created_at), "d MMM HH:mm", { locale: es })}
          </p>
        </div>
        {status && (
          <Badge variant="outline" className={cn("shrink-0", status.className)}>
            {status.label}
          </Badge>
        )}
      </div>

      <div className="rounded-lg bg-muted/40 px-3 py-2 text-sm font-medium">
        {prediction.selection_label}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="text-muted-foreground">
          Apostado{" "}
          <span className="font-mono font-medium text-foreground">
            ${prediction.stake_amount.toLocaleString("es")}
          </span>{" "}
          · cuota <span className="font-mono">{prediction.odds}x</span>
        </span>
        {settled ? (
          won ? (
            <span className="font-mono text-sm font-semibold text-primary">
              +${(prediction.points_awarded ?? 0).toLocaleString("es")}
            </span>
          ) : (
            <span className="font-mono text-sm font-semibold text-destructive">
              −${prediction.stake_amount.toLocaleString("es")}
            </span>
          )
        ) : (
          <span className="font-mono text-xs text-muted-foreground">
            pagaría ${prediction.potential_payout.toLocaleString("es")}
          </span>
        )}
      </div>
    </div>
  );
}

function AccountContent() {
  const { user } = useAuth();

  const { data: history, isLoading } = useQuery({
    queryKey: ["me", "predictions"],
    queryFn: api.auth.myPredictions,
    staleTime: 15_000,
  });

  if (!user) return null;

  const settled = (history ?? []).filter((p) => p.status === "settled");
  const netProfit = settled.reduce(
    (acc, p) => acc + ((p.points_awarded ?? 0) - p.stake_amount),
    0
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-border bg-card/70 p-5">
        <span className="flex size-12 items-center justify-center rounded-xl bg-primary/15 text-primary">
          <UserRound className="size-6" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 font-heading text-lg font-bold">
            {user.display_name}
            {user.role === "admin" && (
              <Badge
                variant="outline"
                className="border-primary/40 bg-primary/10 text-primary"
              >
                <ShieldCheck className="mr-1 size-3" /> Admin
              </Badge>
            )}
          </p>
          <p className="truncate text-sm text-muted-foreground">{user.email}</p>
        </div>
        <div className="flex gap-3">
          <div className="rounded-xl bg-primary/10 px-4 py-2 text-right">
            <p className="flex items-center gap-1 text-[0.7rem] uppercase tracking-wider text-primary/80">
              <Wallet className="size-3" /> Bankroll
            </p>
            <p className="font-mono text-xl font-bold text-primary">
              ${user.balance.toLocaleString("es")}
            </p>
          </div>
          <div className="rounded-xl bg-muted/60 px-4 py-2 text-right">
            <p className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
              Neto liquidado
            </p>
            <p
              className={cn(
                "font-mono text-xl font-bold",
                netProfit >= 0 ? "text-primary" : "text-destructive"
              )}
            >
              {netProfit >= 0 ? "+" : "−"}${Math.abs(netProfit).toLocaleString("es")}
            </p>
          </div>
        </div>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-heading text-base font-bold">
          <History className="size-4 text-primary" /> Historial de apuestas
        </h2>
        {isLoading && <LoadingState label="Cargando historial…" />}
        {history && history.length === 0 && (
          <EmptyState
            title="Todavía no apostaste"
            description="Tus jugadas van a aparecer acá con su estado y resultado."
          />
        )}
        {history && history.length > 0 && (
          <div className="flex flex-col gap-2">
            {history.map((p) => (
              <HistoryRow key={p.id} prediction={p} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default function AccountPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-8">
      <h1 className="font-heading text-2xl font-bold tracking-tight">Cuenta</h1>
      <RequireAuth>
        <AccountContent />
      </RequireAuth>
    </div>
  );
}
