"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ChevronDown, Lock, Ticket, Unlock } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { ErrorState, EmptyState } from "@/components/query-state";
import { MarketCard } from "@/components/betting/market-card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { BetMarket, Tournament } from "@/lib/api/types";

/** Misma forma que una MarketCard colapsada (borde redondeado, título + subtítulo + badge a la
 * derecha) para que no haya salto de layout al pasar de esqueleto a mercados reales. */
function MarketCardSkeleton() {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-card/70 px-4 py-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-56" />
      </div>
      <Skeleton className="h-5 w-16 shrink-0 rounded-full" />
    </div>
  );
}

function MarketsSectionSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <Skeleton className="h-4 w-40" />
      <div className="flex flex-col gap-3">
        <MarketCardSkeleton />
        <MarketCardSkeleton />
      </div>
    </div>
  );
}

/** Un torneo's markets filtered to just `statusFilter`, as MarketCard blocks -- reused by both
 * accordion sections (Abiertos/Cerrados) below; TanStack Query dedupes the underlying fetch. */
function TournamentMarketsGroup({
  tournament,
  statusFilter,
  onCount,
}: {
  tournament: Tournament;
  statusFilter: "open" | "closed";
  /** Reports this tournament's filtered market count up to the accordion header, so "Mercados
   * cerrados" can show a total without a separate query -- reuses the same cached
   * queryKeys.betMarkets(id) fetch both accordion sections already share. */
  onCount?: (tournamentId: number, count: number) => void;
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

  const filtered = (markets ?? []).filter((m: BetMarket) =>
    statusFilter === "open" ? m.status === "open" : m.status !== "open"
  );

  useEffect(() => {
    if (markets) onCount?.(tournament.id, filtered.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markets, filtered.length, tournament.id]);

  if (isLoading) return <MarketsSectionSkeleton />;
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
  count,
  icon: Icon,
  defaultOpen,
  children,
}: {
  title: string;
  count: number | null;
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
        <h2 className="flex-1 font-heading text-lg font-bold">
          {title}
          {count !== null && (
            <span className="ml-2 font-mono text-sm font-normal text-muted-foreground">
              · {count}
            </span>
          )}
        </h2>
        <ChevronDown
          className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      {/* `children` stay mounted even while collapsed (just visually hidden, not unmounted) --
          they're what reports counts via onCount and keeps refetching live, so "Mercados
          cerrados" gets an accurate, ever-updating count without needing the section expanded
          first. Each TournamentMarketsGroup already renders null when it has nothing to show, so
          rendering them unconditionally alongside the empty-state message is harmless. */}
      <div className={cn("flex flex-col gap-6", !open && "hidden")}>
        {count === 0 && (
          <EmptyState
            title={`Sin ${title.toLowerCase()}`}
            description="No hay nada acá por ahora."
          />
        )}
        {children}
      </div>
    </section>
  );
}

/** Sums per-tournament counts reported by `TournamentMarketsGroup.onCount` into a section total,
 * or null while any tournament hasn't reported yet (so the header doesn't flash "· 0"). */
function useSectionCount(tournamentIds: number[]) {
  const [counts, setCounts] = useState<Record<number, number>>({});
  const onCount = (tournamentId: number, count: number) =>
    setCounts((prev) =>
      prev[tournamentId] === count ? prev : { ...prev, [tournamentId]: count }
    );
  const total = tournamentIds.every((id) => id in counts)
    ? tournamentIds.reduce((sum, id) => sum + (counts[id] ?? 0), 0)
    : null;
  return { total, onCount };
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
  const tournamentIds = withMarkets.map((t) => t.id);
  const openCount = useSectionCount(tournamentIds);
  const closedCount = useSectionCount(tournamentIds);

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="flex items-center gap-2 font-heading text-2xl font-bold tracking-tight">
          <Ticket className="size-6 text-primary" /> Apuestas
        </h1>
        <p className="text-sm text-muted-foreground">
          Pool total, apostadores, cuotas y pagos en tiempo real. Se juega con tokens — nunca hay
          dinero real de por medio.
        </p>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card/40 p-4">
          <Skeleton className="h-6 w-40" />
          <MarketsSectionSkeleton />
        </div>
      )}
      {error && <ErrorState error={error} />}
      {tournaments && withMarkets.length === 0 && (
        <EmptyState
          title="No hay mercados todavía"
          description="Cuando un admin abra un mercado, aparecerá aquí."
        />
      )}

      {withMarkets.length > 0 && (
        <>
          <AccordionSection
            title="Mercados abiertos"
            count={openCount.total}
            icon={Unlock}
            defaultOpen
          >
            {withMarkets.map((t) => (
              <TournamentMarketsGroup
                key={t.id}
                tournament={t}
                statusFilter="open"
                onCount={openCount.onCount}
              />
            ))}
          </AccordionSection>
          <AccordionSection
            title="Mercados cerrados"
            count={closedCount.total}
            icon={Lock}
            defaultOpen={false}
          >
            {withMarkets.map((t) => (
              <TournamentMarketsGroup
                key={t.id}
                tournament={t}
                statusFilter="closed"
                onCount={closedCount.onCount}
              />
            ))}
          </AccordionSection>
        </>
      )}
    </div>
  );
}
