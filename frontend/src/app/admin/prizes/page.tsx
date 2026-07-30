"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Dice5, Gift, Loader2, Megaphone, PlusCircle, Users2 } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { OptionPicker } from "@/components/ui/option-picker";
import { TournamentChips } from "@/components/admin/tournament-chips";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";
import { formatTokens } from "@/lib/format";
import type { PrizeEvent, PrizeEventType } from "@/lib/api/types";

const TYPE_LABELS: Record<PrizeEventType, string> = {
  manual_award: "Premio manual",
  raffle: "Sorteo",
  activity_bonus: "Bono de participación",
};

const TYPE_ICONS: Record<PrizeEventType, typeof Gift> = {
  manual_award: Megaphone,
  raffle: Dice5,
  activity_bonus: Users2,
};

const STATUS_LABEL: Record<string, string> = { open: "Abierto", resolved: "Resuelto" };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------------------------ */
/* Crear evento                                                                          */
/* ------------------------------------------------------------------------------------ */

function CreateEventForm({ tournamentId }: { tournamentId: string }) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<PrizeEventType>("manual_award");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [closesAt, setClosesAt] = useState("");
  const [numWinners, setNumWinners] = useState("1");
  const [prizePerWinner, setPrizePerWinner] = useState("");
  const [ticketCost, setTicketCost] = useState("");
  const [bonusAmount, setBonusAmount] = useState("");

  const mutation = useMutation({
    mutationFn: () => {
      const config: Record<string, number> = {};
      if (type === "raffle") {
        config.num_winners = Number(numWinners) || 1;
        config.prize_per_winner = Number(prizePerWinner) || 0;
        if (ticketCost) config.ticket_cost = Number(ticketCost);
      } else if (type === "activity_bonus") {
        config.bonus_amount = Number(bonusAmount) || 0;
      }
      return api.prizeEvents.create(tournamentId, {
        type,
        title: title.trim(),
        description: description.trim() || undefined,
        config,
        closes_at: closesAt ? new Date(closesAt).toISOString() : undefined,
      });
    },
    onSuccess: () => {
      toast.success("Evento de premio creado");
      setTitle("");
      setDescription("");
      setClosesAt("");
      setNumWinners("1");
      setPrizePerWinner("");
      setTicketCost("");
      setBonusAmount("");
      queryClient.invalidateQueries({ queryKey: queryKeys.prizeEvents(tournamentId) });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Error al crear el evento"),
  });

  const canSubmit =
    title.trim().length >= 3 &&
    (type !== "raffle" || Number(prizePerWinner) > 0) &&
    (type !== "activity_bonus" || Number(bonusAmount) > 0);

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card/70 p-4">
      <div className="flex flex-wrap gap-1.5">
        {(Object.keys(TYPE_LABELS) as PrizeEventType[]).map((t) => {
          const Icon = TYPE_ICONS[t];
          return (
            <button
              key={t}
              type="button"
              onClick={() => setType(t)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors",
                type === t
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card hover:bg-accent"
              )}
            >
              <Icon className="size-3.5" /> {TYPE_LABELS[t]}
            </button>
          );
        })}
      </div>

      <Field label="Título">
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Trivia de la Gran Final"
        />
      </Field>
      <Field label="Descripción (opcional)">
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          placeholder="Qué es, cómo se gana…"
        />
      </Field>

      {type === "raffle" && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Nº de ganadores">
            <Input
              type="number"
              min="1"
              step="1"
              value={numWinners}
              onChange={(e) => setNumWinners(e.target.value)}
            />
          </Field>
          <Field label="Premio por ganador">
            <Input
              type="number"
              min="1"
              step="1"
              value={prizePerWinner}
              onChange={(e) => setPrizePerWinner(e.target.value)}
              placeholder="tokens"
            />
          </Field>
          <Field label="Costo del ticket (opcional)">
            <Input
              type="number"
              min="0"
              step="1"
              value={ticketCost}
              onChange={(e) => setTicketCost(e.target.value)}
              placeholder="gratis si se deja vacío"
            />
          </Field>
        </div>
      )}

      {type === "activity_bonus" && (
        <Field label="Bono por participar">
          <Input
            type="number"
            min="1"
            step="1"
            value={bonusAmount}
            onChange={(e) => setBonusAmount(e.target.value)}
            placeholder="tokens"
          />
        </Field>
      )}

      <Field
        label={
          type === "activity_bonus"
            ? "Fin de la ventana de participación"
            : type === "raffle"
              ? "Cierra (opcional)"
              : "Cierra (no aplica, se resuelve a mano)"
        }
      >
        <Input
          type="datetime-local"
          value={closesAt}
          onChange={(e) => setClosesAt(e.target.value)}
          disabled={type === "manual_award"}
        />
      </Field>

      <Button
        disabled={!canSubmit || mutation.isPending}
        onClick={() => mutation.mutate()}
        className="w-fit"
      >
        {mutation.isPending && <Loader2 className="size-4 animate-spin" />}
        <PlusCircle className="size-4" /> Crear evento
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------------------------ */
/* Cola de premios manuales                                                              */
/* ------------------------------------------------------------------------------------ */

function ManualAwardQueueForm({ eventId }: { eventId: number }) {
  const queryClient = useQueryClient();
  const { data: users } = useQuery({
    queryKey: queryKeys.adminUsers,
    queryFn: api.admin.users,
    staleTime: 30_000,
  });
  const [userId, setUserId] = useState<string | null>(null);
  const [amount, setAmount] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      api.prizeEvents.queueManualAward(eventId, {
        user_id: Number(userId),
        amount: Number(amount),
      }),
    onSuccess: () => {
      toast.success("Premio agregado a la cola");
      setUserId(null);
      setAmount("");
      queryClient.invalidateQueries({ queryKey: queryKeys.prizeEvent(eventId) });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Error al agregar el premio"),
  });

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border p-3">
      <div className="min-w-48 flex-1">
        <span className="mb-1 block text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          Usuario
        </span>
        <OptionPicker
          options={(users ?? []).map((u) => ({
            value: String(u.id),
            label: u.display_name,
            hint: u.email,
          }))}
          value={userId}
          onChange={setUserId}
          placeholder="Buscar usuario…"
          maxHeight="max-h-40"
        />
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          Monto
        </span>
        <Input
          type="number"
          min="1"
          step="1"
          placeholder="tokens"
          className="w-28"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </div>
      <Button
        size="sm"
        disabled={!userId || !amount || mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
        Agregar
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------------------------ */
/* Tarjeta de evento                                                                      */
/* ------------------------------------------------------------------------------------ */

function ConfigSummary({ event }: { event: PrizeEvent }) {
  if (event.type === "raffle") {
    const cost = event.config.ticket_cost;
    return (
      <p className="text-xs text-muted-foreground">
        {event.config.num_winners ?? 1} ganador(es) ·{" "}
        {formatTokens(event.config.prize_per_winner ?? 0)} c/u ·{" "}
        {cost ? `ticket ${formatTokens(cost)}` : "entrada gratis"}
      </p>
    );
  }
  if (event.type === "activity_bonus") {
    return (
      <p className="text-xs text-muted-foreground">
        Bono de {formatTokens(event.config.bonus_amount ?? 0)} por apostar al menos una vez en
        la ventana del evento
      </p>
    );
  }
  return <p className="text-xs text-muted-foreground">Premios individuales asignados a mano</p>;
}

function PrizeEventCard({
  event,
  tournamentId,
}: {
  event: PrizeEvent;
  tournamentId: string;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const { data: detail } = useQuery({
    queryKey: queryKeys.prizeEvent(event.id),
    queryFn: () => api.prizeEvents.get(event.id),
    enabled: expanded,
  });

  const resolveMutation = useMutation({
    mutationFn: () => api.prizeEvents.resolve(event.id),
    onSuccess: () => {
      toast.success("Evento resuelto — tokens acreditados");
      queryClient.invalidateQueries({ queryKey: queryKeys.prizeEvents(tournamentId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.prizeEvent(event.id) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al resolver"),
  });

  const Icon = TYPE_ICONS[event.type];
  const isOpen = event.status === "open";

  return (
    <div
      className={cn(
        "rounded-xl border bg-card/70 transition-colors",
        isOpen ? "border-border" : "border-border/60 opacity-90"
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left hover:bg-accent/30"
      >
        <Icon className="size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-heading text-sm font-semibold">{event.title}</p>
          <p className="truncate text-xs text-muted-foreground">
            {TYPE_LABELS[event.type]} · {event.entry_count}{" "}
            {event.entry_count === 1 ? "entrada" : "entradas"}
            {event.type === "raffle" ? ` · ${event.total_tickets} tickets` : ""}
          </p>
        </div>
        <Badge
          variant="outline"
          className={cn(
            isOpen
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border bg-muted text-muted-foreground"
          )}
        >
          {STATUS_LABEL[event.status]}
        </Badge>
      </button>

      {expanded && (
        <div className="flex flex-col gap-3 border-t border-border/60 p-4">
          <ConfigSummary event={event} />
          {event.description && (
            <p className="text-sm text-muted-foreground">{event.description}</p>
          )}

          {isOpen && event.type === "manual_award" && (
            <ManualAwardQueueForm eventId={event.id} />
          )}

          {detail && detail.entries.length > 0 && (
            <div className="flex flex-col divide-y divide-border/50 rounded-lg border border-border/60">
              {detail.entries.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm"
                >
                  <span className="truncate">{entry.user.display_name}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    {event.type === "raffle" && (
                      <span className="text-xs text-muted-foreground">
                        {entry.tickets} tickets
                      </span>
                    )}
                    {entry.awarded_amount == null ? (
                      <span className="text-xs text-muted-foreground">pendiente</span>
                    ) : entry.awarded_amount > 0 ? (
                      <span className="font-mono text-xs font-semibold text-primary">
                        +{formatTokens(entry.awarded_amount)}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">sin premio</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}
          {detail && detail.entries.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {event.type === "activity_bonus"
                ? "Los participantes se calculan recién al resolver."
                : "Todavía nadie entró a este evento."}
            </p>
          )}

          {isOpen && (
            <Button
              size="sm"
              variant="outline"
              className="w-fit"
              disabled={resolveMutation.isPending}
              onClick={() => resolveMutation.mutate()}
            >
              {resolveMutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
              <CheckCircle2 className="size-3.5" /> Resolver
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------------------ */
/* Página                                                                                 */
/* ------------------------------------------------------------------------------------ */

export default function AdminPrizesPage() {
  const [tournamentId, setTournamentId] = useState<string | null>(null);
  const { data: events, isLoading } = useQuery({
    queryKey: queryKeys.prizeEvents(tournamentId ?? "none"),
    queryFn: () => api.prizeEvents.list(tournamentId!),
    enabled: !!tournamentId,
  });

  return (
    <div className="flex flex-col gap-6">
      <TournamentChips value={tournamentId} onChange={setTournamentId} />

      {!tournamentId && <EmptyState title="Elegí un torneo para gestionar sus premios" />}

      {tournamentId && (
        <>
          <CreateEventForm tournamentId={tournamentId} />

          {isLoading && <LoadingState label="Cargando eventos…" />}
          {events && events.length === 0 && (
            <EmptyState title="Sin eventos de premio todavía" />
          )}
          <div className="flex flex-col gap-2">
            {events?.map((event) => (
              <PrizeEventCard key={event.id} event={event} tournamentId={tournamentId} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
