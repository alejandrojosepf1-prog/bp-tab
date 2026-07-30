"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Dice5, Gift, Loader2, Megaphone, Ticket, Trophy, Users2 } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";
import { formatTokens } from "@/lib/format";
import type { PrizeEvent, PrizeEventType, Tournament } from "@/lib/api/types";

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

/** Botón para comprar tickets de un sorteo abierto -- la única acción que un usuario (no
 * admin) puede tomar sobre un evento de premio; los otros dos tipos se resuelven solos o a
 * mano por el admin, sin nada que el usuario tenga que hacer. */
function RaffleEntryForm({ event }: { event: PrizeEvent }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [tickets, setTickets] = useState("1");
  const ticketCost = event.config.ticket_cost ?? 0;
  const totalCost = (Number(tickets) || 0) * ticketCost;
  const overBalance = user != null && totalCost > user.balance;

  const mutation = useMutation({
    mutationFn: () => api.prizeEvents.enter(event.id, Number(tickets)),
    onSuccess: () => {
      toast.success("Entraste al sorteo");
      queryClient.invalidateQueries({ queryKey: queryKeys.prizeEvents(String(event.tournament_id)) });
      queryClient.invalidateQueries({ queryKey: queryKeys.me });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "No se pudo entrar al sorteo"),
  });

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-primary/30 bg-primary/[0.03] p-3">
      <div className="flex flex-col gap-1">
        <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          Tickets
        </span>
        <Input
          type="number"
          min="1"
          step="1"
          className={cn("w-24", overBalance && "border-destructive")}
          value={tickets}
          onChange={(e) => setTickets(e.target.value)}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {ticketCost > 0 ? `Costo total: ${formatTokens(totalCost)}` : "Entrada gratis"}
      </p>
      <Button
        size="sm"
        className="ml-auto"
        disabled={!tickets || Number(tickets) < 1 || overBalance || mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
        <Ticket className="size-3.5" /> Entrar
      </Button>
      {overBalance && (
        <p className="w-full text-xs text-destructive">
          No te alcanzan los tokens ({formatTokens(user?.balance ?? 0)}).
        </p>
      )}
    </div>
  );
}

function PrizeEventRow({ event }: { event: PrizeEvent }) {
  const { user, isAuthenticated } = useAuth();
  const { data: detail } = useQuery({
    queryKey: queryKeys.prizeEvent(event.id),
    queryFn: () => api.prizeEvents.get(event.id),
    staleTime: 10_000,
  });
  const myEntry = detail?.entries.find((e) => user && e.user.id === user.id);
  const isResolved = event.status === "resolved";
  const Icon = TYPE_ICONS[event.type];

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-xl border bg-card/70 p-4",
        isResolved ? "border-border/60 opacity-90" : "border-primary/25"
      )}
    >
      <div className="flex items-start gap-2.5">
        <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="font-heading text-sm font-semibold">{event.title}</p>
          <p className="text-xs text-muted-foreground">
            {TYPE_LABELS[event.type]}
            {event.type === "raffle" &&
              ` · ${event.config.num_winners ?? 1} ganador(es) · ${formatTokens(
                event.config.prize_per_winner ?? 0
              )} c/u${event.config.ticket_cost ? ` · ticket ${formatTokens(event.config.ticket_cost)}` : " · gratis"}`}
            {event.type === "activity_bonus" &&
              ` · ${formatTokens(event.config.bonus_amount ?? 0)} por apostar en la ventana`}
          </p>
          {event.description && (
            <p className="mt-1 text-sm text-muted-foreground">{event.description}</p>
          )}
        </div>
        {isResolved && (
          <span className="shrink-0 rounded-md bg-muted px-2 py-1 text-[0.7rem] font-medium text-muted-foreground">
            Resuelto
          </span>
        )}
      </div>

      {myEntry && (
        <p className="text-xs text-muted-foreground">
          {event.type === "raffle" && `Entraste con ${myEntry.tickets} ticket(s). `}
          {myEntry.awarded_amount == null && "Esperando resolución."}
          {myEntry.awarded_amount != null && myEntry.awarded_amount > 0 && (
            <span className="font-semibold text-primary">
              ¡Ganaste {formatTokens(myEntry.awarded_amount)}!
            </span>
          )}
          {myEntry.awarded_amount === 0 && "No te tocó esta vez."}
        </p>
      )}

      {!isResolved && event.type === "raffle" && isAuthenticated && !myEntry && (
        <RaffleEntryForm event={event} />
      )}
      {!isResolved && event.type === "raffle" && !isAuthenticated && (
        <p className="text-xs text-muted-foreground">Iniciá sesión para entrar al sorteo.</p>
      )}
    </div>
  );
}

function TournamentPrizeEvents({ tournament }: { tournament: Tournament }) {
  const { data: events } = useQuery({
    queryKey: queryKeys.prizeEvents(tournament.id),
    queryFn: () => api.prizeEvents.list(tournament.id),
    staleTime: 15_000,
  });
  if (!events || events.length === 0) return null;

  const open = events.filter((e) => e.status === "open");
  const resolved = events.filter((e) => e.status !== "open");

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-heading text-base font-semibold">{tournament.name}</h2>
      <div className="flex flex-col gap-2">
        {open.map((e) => (
          <PrizeEventRow key={e.id} event={e} />
        ))}
        {resolved.map((e) => (
          <PrizeEventRow key={e.id} event={e} />
        ))}
      </div>
    </div>
  );
}

export default function PrizesPage() {
  const { data: tournaments, isLoading } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
    staleTime: 30_000,
  });
  const activeTournaments = (tournaments ?? []).filter((t) => t.is_active);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="flex items-center gap-2 font-heading text-2xl font-bold tracking-tight">
          <Trophy className="size-6 text-primary" /> Premios
        </h1>
        <p className="text-sm text-muted-foreground">
          Sorteos, bonos y premios sorpresa que el admin arma aparte de las apuestas.
        </p>
      </div>

      {isLoading && <LoadingState label="Cargando premios…" />}
      {tournaments && activeTournaments.length === 0 && (
        <EmptyState title="No hay torneos activos con premios todavía" />
      )}
      <div className="flex flex-col gap-6">
        {activeTournaments.map((t) => (
          <TournamentPrizeEvents key={t.id} tournament={t} />
        ))}
      </div>
    </div>
  );
}
