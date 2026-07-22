"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ChevronDown, Lock, Ticket, Unlock } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { MarketCard } from "@/components/betting/market-card";
import { cn } from "@/lib/utils";
import type { BetMarket, Tournament } from "@/lib/api/types";

/** Un torneo's markets filtered to just `statusFilter`, as MarketCard blocks -- reused by both
 * accordion sections (Abiertos/Cerrados) below; TanStack Query dedupes the underlying fetch. */
function TournamentMarketsGroup({
  tournament,
  statusFilter,
}: {
  tournament: Tournament;
  statusFilter: "open" | "closed";
}) {
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

  const filtered = (markets ?? []).filter((m: BetMarket) =>
    statusFilter === "open" ? m.status === "open" : m.status !== "open"
  );
  if (!filtered.length) return null;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-heading text-sm font-bold text-muted-foreground">
          {tournament.name}
        </h3>
        <Link
          href={`/tournaments/${tournament.id}`}
          className="text-xs font-medium text-primary hover:underline"
        >
          Ver torneo →
        </Link>
      </div>
      <div className="flex flex-col gap-3">
        {filtered.map((market) => (
          <MarketCard
            key={market.id}
            tournamentId={id}
            market={market}
            teams={teams ?? []}
            speakers={speakers ?? []}
            institutions={institutions ?? []}
            defaultExpanded={statusFilter === "open" && filtered.length === 1}
          />
        ))}
      </div>
    </section>
  );
}

function AccordionSection({
  title,
  icon: Icon,
  defaultOpen,
  children,
}: {
  title: string;
  icon: typeof Unlock;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border bg-card/40 p-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 text-left"
      >
        <Icon className="size-4 text-primary" />
        <h2 className="flex-1 font-heading text-lg font-bold">{title}</h2>
        <ChevronDown
          className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      {open && <div className="flex flex-col gap-6">{children}</div>}
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

      {withMarkets.length > 0 && (
        <>
          <AccordionSection title="Mercados abiertos" icon={Unlock} defaultOpen>
            {withMarkets.map((t) => (
              <TournamentMarketsGroup key={t.id} tournament={t} statusFilter="open" />
            ))}
          </AccordionSection>
          <AccordionSection title="Mercados cerrados" icon={Lock} defaultOpen={false}>
            {withMarkets.map((t) => (
              <TournamentMarketsGroup key={t.id} tournament={t} statusFilter="closed" />
            ))}
          </AccordionSection>
        </>
      )}
    </div>
  );
}
