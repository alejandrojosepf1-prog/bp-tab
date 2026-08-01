"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { toast } from "sonner";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  History,
  Send,
  ShieldCheck,
  UserRound,
  Wallet,
} from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { RequireAuth } from "@/components/auth/require-auth";
import { EmptyState } from "@/components/query-state";
import { AnimatedTokens } from "@/components/ui/animated-number";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { OptionPicker } from "@/components/ui/option-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { formatSignedTokens, formatTokens } from "@/lib/format";
import type { MyPrediction, Transaction } from "@/lib/api/types";

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
            {formatTokens(prediction.stake_amount)}
          </span>{" "}
          · cuota <span className="font-mono">{prediction.odds}x</span>
        </span>
        {settled ? (
          won ? (
            <span className="font-mono text-sm font-semibold text-primary">
              {formatSignedTokens(prediction.points_awarded ?? 0)}
            </span>
          ) : (
            <span className="font-mono text-sm font-semibold text-destructive">
              −{formatTokens(prediction.stake_amount)}
            </span>
          )
        ) : (
          <span className="font-mono text-xs text-muted-foreground">
            pagaría {formatTokens(prediction.potential_payout)}
          </span>
        )}
      </div>
    </div>
  );
}

function SendTokensDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const queryClient = useQueryClient();
  const [recipientId, setRecipientId] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const { data: users } = useQuery({
    queryKey: queryKeys.users,
    queryFn: api.auth.users,
    enabled: open,
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: () =>
      api.transfers.create({
        recipient_id: Number(recipientId),
        amount: Number(amount),
        note: note.trim() || undefined,
      }),
    onSuccess: (data) => {
      toast.success(`Enviaste ${formatTokens(data.sent.amount)} a ${data.sent.counterparty_display_name}`);
      // El mismo patrón que cada acción que mueve balance en esta app: invalidar queryKeys.me
      // para que el saldo del header/sidebar se actualice solo, sin recargar la página.
      queryClient.invalidateQueries({ queryKey: queryKeys.me });
      queryClient.invalidateQueries({ queryKey: queryKeys.myTransfers });
      setRecipientId(null);
      setAmount("");
      setNote("");
      onOpenChange(false);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Error al enviar tokens"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Enviar tokens</DialogTitle>
          <DialogDescription>
            Transferí tokens directamente a otro usuario. Es instantáneo e irreversible.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>Destinatario</Label>
            <OptionPicker
              options={(users ?? []).map((u) => ({ value: String(u.id), label: u.display_name }))}
              value={recipientId}
              onChange={setRecipientId}
              placeholder="Buscar usuario…"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Monto</Label>
            <Input
              type="number"
              min={1}
              step="1"
              placeholder="50"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="font-mono"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Nota (opcional)</Label>
            <Input
              placeholder="para la próxima ronda…"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={280}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button
            disabled={!recipientId || !amount || Number(amount) <= 0 || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Enviando…" : "Enviar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TransferRow({ tx }: { tx: Transaction }) {
  const sent = tx.type === "transfer_out";
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-card/40 px-3 py-2 text-sm">
      <div className="flex items-center gap-2 min-w-0">
        {sent ? (
          <ArrowUpFromLine className="size-4 shrink-0 text-destructive" />
        ) : (
          <ArrowDownToLine className="size-4 shrink-0 text-primary" />
        )}
        <div className="min-w-0">
          <p className="truncate font-medium">
            {sent ? "A " : "De "}
            {tx.counterparty_display_name ?? "usuario eliminado"}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {format(new Date(tx.created_at), "d MMM HH:mm", { locale: es })}
            {tx.note ? ` · ${tx.note}` : ""}
          </p>
        </div>
      </div>
      <span
        className={cn(
          "shrink-0 font-mono font-semibold",
          sent ? "text-destructive" : "text-primary"
        )}
      >
        {sent ? "−" : "+"}
        {formatTokens(tx.amount)}
      </span>
    </div>
  );
}

/** Agrupa el historial por torneo conservando el orden en que vino la lista (más reciente
 * primero), y calcula el neto liquidado de cada grupo. Sólo las liquidadas cuentan para el neto:
 * una apuesta abierta todavía no ganó ni perdió nada. */
function groupByTournament(
  history: MyPrediction[]
): { tournamentName: string; predictions: MyPrediction[]; net: number }[] {
  const groups = new Map<string, MyPrediction[]>();
  for (const prediction of history) {
    const existing = groups.get(prediction.tournament_name);
    if (existing) existing.push(prediction);
    else groups.set(prediction.tournament_name, [prediction]);
  }
  return [...groups.entries()].map(([tournamentName, predictions]) => ({
    tournamentName,
    predictions,
    net: predictions
      .filter((p) => p.status === "settled")
      .reduce((acc, p) => acc + ((p.points_awarded ?? 0) - p.stake_amount), 0),
  }));
}

function AccountContent() {
  const { user } = useAuth();
  const [sendOpen, setSendOpen] = useState(false);

  const { data: history, isLoading } = useQuery({
    queryKey: ["me", "predictions"],
    queryFn: api.auth.myPredictions,
    staleTime: 15_000,
  });
  const { data: transfers, isLoading: transfersLoading } = useQuery({
    queryKey: queryKeys.myTransfers,
    queryFn: api.transfers.myTransfers,
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
      {/* Identidad arriba, métricas en su propia grilla abajo. Antes era UNA sola fila flex con
          avatar + nombre + email + 2 tarjetas + botón: a menos de ~1100px el badge de Admin se
          montaba encima de "TOKENS" y el email se cortaba en "alejand...". Separar las dos
          responsabilidades hace que nada dependa de que sobre ancho. */}
      <section className="rounded-2xl border border-border bg-card/70 p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-primary">
            <UserRound className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <h2 className="min-w-0 truncate font-heading text-lg font-bold">
                {user.display_name}
              </h2>
              {user.role === "admin" && (
                <Badge
                  variant="outline"
                  className="shrink-0 border-primary/40 bg-primary/10 text-primary"
                >
                  <ShieldCheck className="mr-1 size-3" /> Admin
                </Badge>
              )}
            </div>
            {/* title= para que el email completo siga siendo recuperable al truncarse */}
            <p className="truncate text-sm text-muted-foreground" title={user.email}>
              {user.email}
            </p>
          </div>
          {/* Sin label en móvil, pero 44x44 igual: por debajo de eso el objetivo táctil queda
              fuera de guía (medido: quedaba en 38x28 con size="sm"). En sm+ recupera el texto. */}
          <Button
            variant="outline"
            className="size-11 shrink-0 p-0 sm:h-9 sm:w-auto sm:px-3"
            onClick={() => setSendOpen(true)}
          >
            <Send className="size-4" />
            <span className="hidden sm:inline">Enviar tokens</span>
            <span className="sr-only sm:hidden">Enviar tokens</span>
          </Button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:gap-3">
          <div className="rounded-xl bg-primary/10 px-3 py-2 sm:px-4">
            <p className="flex items-center gap-1 text-[0.7rem] uppercase tracking-wider text-primary/80">
              <Wallet className="size-3 shrink-0" /> Tokens
            </p>
            <AnimatedTokens
              value={user.balance}
              className="block truncate text-xl font-bold text-primary"
            />
          </div>
          <div className="rounded-xl bg-muted/60 px-3 py-2 sm:px-4">
            <p className="truncate text-[0.7rem] uppercase tracking-wider text-muted-foreground">
              Neto liquidado
            </p>
            <p
              className={cn(
                "truncate font-mono text-xl font-bold tabular-nums",
                netProfit >= 0 ? "text-primary" : "text-destructive"
              )}
            >
              {formatSignedTokens(netProfit)}
            </p>
          </div>
        </div>
      </section>

      <SendTokensDialog open={sendOpen} onOpenChange={setSendOpen} />

      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-heading text-base font-bold">
          <Send className="size-4 text-primary" /> Transferencias
        </h2>
        {/* Skeleton de la MISMA altura que una fila real, no un spinner centrado: el spinner
            ocupaba una caja alta y al llegar los datos toda la página saltaba (layout shift). */}
        {transfersLoading && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-[58px] rounded-lg" />
            <Skeleton className="h-[58px] rounded-lg" />
          </div>
        )}
        {transfers && transfers.length === 0 && (
          <EmptyState
            title="Todavía no hiciste transferencias"
            description="Enviá o recibí tokens de otros usuarios y van a aparecer acá."
          />
        )}
        {transfers && transfers.length > 0 && (
          <div className="flex flex-col gap-2">
            {transfers.slice(0, 10).map((tx) => (
              <TransferRow key={tx.id} tx={tx} />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-heading text-base font-bold">
          <History className="size-4 text-primary" /> Historial de apuestas
        </h2>
        {isLoading && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-[132px] rounded-xl" />
            <Skeleton className="h-[132px] rounded-xl" />
          </div>
        )}
        {history && history.length === 0 && (
          <EmptyState
            title="Todavía no apostaste"
            description="Tus jugadas van a aparecer acá con su estado y resultado."
          />
        )}
        {history && history.length > 0 && (
          <div className="flex flex-col gap-5">
            {groupByTournament(history).map((group) => (
              <div key={group.tournamentName} className="flex flex-col gap-2">
                {/* Cabecera por torneo con su neto propio: en una lista plana de 40 apuestas
                    across varios torneos no había forma de leer "cómo me fue en CMUDE". */}
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border/60 pb-1.5">
                  <h3 className="min-w-0 truncate text-sm font-semibold">
                    {group.tournamentName}
                  </h3>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {group.predictions.length}{" "}
                    {group.predictions.length === 1 ? "apuesta" : "apuestas"} ·{" "}
                    <span
                      className={cn(
                        "font-mono font-semibold tabular-nums",
                        group.net >= 0 ? "text-primary" : "text-destructive"
                      )}
                    >
                      {formatSignedTokens(group.net)}
                    </span>
                  </span>
                </div>
                {group.predictions.map((p) => (
                  <HistoryRow key={p.id} prediction={p} />
                ))}
              </div>
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
