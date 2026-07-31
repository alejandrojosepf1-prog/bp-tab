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
import { LoadingState, EmptyState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
              <Wallet className="size-3" /> Tokens
            </p>
            <p className="font-mono text-xl font-bold text-primary">
              {formatTokens(user.balance)}
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
              {formatSignedTokens(netProfit)}
            </p>
          </div>
        </div>
        <Button variant="outline" className="shrink-0" onClick={() => setSendOpen(true)}>
          <Send className="size-4" /> Enviar tokens
        </Button>
      </div>

      <SendTokensDialog open={sendOpen} onOpenChange={setSendOpen} />

      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-heading text-base font-bold">
          <Send className="size-4 text-primary" /> Transferencias
        </h2>
        {transfersLoading && <LoadingState label="Cargando transferencias…" />}
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
