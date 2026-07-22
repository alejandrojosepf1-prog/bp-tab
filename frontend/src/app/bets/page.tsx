"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Ticket } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { MarketCard } from "@/components/betting/market-card";
import type { Tournament } from "@/lib/api/types";

/** Mercados de un torneo, con su board (pool, apostadores, cuotas) y apuesta inline. */
function TournamentMarkets({ tournament }: { tournament: Tournament }) {
  const id = String(tournament.id);
  const { data: markets, isLoading } = useQuery({
    queryKey: queryKeys.betMarkets(id),
    queryFn: () => api.betMarkets.list(id),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const { data: teams } = useQuery({
    queryKey: queryKeys.teams(id),
    queryFn: () => api.teams.list(id),
    staleTime: 60_000,
  });
  const { data: speakers } = useQuery({
    queryKey: queryKeys.speakers(id),
    queryFn: () => api.speakers.list(id),
    staleTime: 60_000,
  });
  const { data: institutions } = useQuery({
    queryKey: queryKeys.institutions(id),
    queryFn: () => api.institutions.list(id),
    staleTime: 60_000,
  });

  if (isLoading) return <LoadingState label="Cargando mercados…" />;

  const open = (markets ?? []).filter((m) => m.status === "open");
  const closed = (markets ?? []).filter((m) => m.status !== "open");
  if (!open.length && !closed.length) return null;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-heading text-base font-bold">{tournament.name}</h2>
        <Link
          href={`/tournaments/${tournament.id}`}
          className="text-xs font-medium text-primary hover:underline"
        >
          Ver torneo →
        </Link>
      </div>
      <div className="flex flex-col gap-3">
        {open.map((market) => (
          <MarketCard
            key={market.id}
            tournamentId={id}
            market={market}
            teams={teams ?? []}
            speakers={speakers ?? []}
            institutions={institutions ?? []}
            defaultExpanded={open.length === 1}
          />
        ))}
        {closed.map((market) => (
          <MarketCard
            key={market.id}
            tournamentId={id}
            market={market}
            teams={teams ?? []}
            speakers={speakers ?? []}
            institutions={institutions ?? []}
          />
        ))}
      </div>
    </section>
  );
}

export default function BetsPage() {
  const { data: tournaments, isLoading, error } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
    staleTime: 30_000,
  });

  const withMarkets = (tournaments ?? []).filter(
    (t) => t.open_markets_count > 0 || t.status !== "upcoming"
  );

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="flex items-center gap-2 font-heading text-2xl font-bold tracking-tight">
          <Ticket className="size-6 text-primary" /> Apuestas
        </h1>
        <p className="text-sm text-muted-foreground">
          Pool total, apostadores, cuotas y pagos en tiempo real. Dólares ficticios — nunca hay
          dinero real de por medio.
        </p>
      </div>

      {isLoading && <LoadingState label="Cargando torneos…" />}
      {error && <ErrorState error={error} />}
      {tournaments && withMarkets.length === 0 && (
        <EmptyState
          title="No hay mercados todavía"
          description="Cuando un admin abra un mercado, aparecerá aquí."
        />
      )}

      {withMarkets.map((t) => (
        <TournamentMarkets key={t.id} tournament={t} />
      ))}
    </div>
  );
}
