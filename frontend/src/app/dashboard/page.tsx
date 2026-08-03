"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronDown } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { ErrorState, EmptyState } from "@/components/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { RoundsPanel, RoundStatusBadge } from "@/components/tournament/rounds-panel";
import { TeamsPanel } from "@/components/tournament/teams-panel";
import { StatNumber, StatLabel } from "@/components/broadcast/stat";
import { LiveIndicator } from "@/components/broadcast/live-indicator";
import { SectionRule } from "@/components/broadcast/section";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/lib/api/types";

const TOURNAMENT_STATUS_LABEL: Record<string, string> = {
  upcoming: "Próximo",
  in_progress: "En curso",
  break_pending: "Break pendiente",
  eliminations: "Eliminatorias",
  completed: "Completado",
};

const LIVE_STATUSES = new Set(["in_progress", "break_pending", "eliminations"]);

function TournamentCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-col gap-4 p-4">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-56" />
        <div className="flex gap-6">
          <Skeleton className="h-12 w-20" />
          <Skeleton className="h-12 w-20" />
        </div>
      </div>
      <div className="flex gap-px border-t border-border bg-border">
        <Skeleton className="h-9 flex-1 rounded-none" />
        <Skeleton className="h-9 flex-1 rounded-none" />
      </div>
    </div>
  );
}

function TournamentCard({ tournament }: { tournament: Tournament }) {
  const router = useRouter();
  const [openSection, setOpenSection] = useState<"rounds" | "teams" | null>(null);

  const { data: dashboard } = useQuery({
    queryKey: queryKeys.dashboard(tournament.id),
    queryFn: () => api.dashboard.get(tournament.id),
    staleTime: 15_000,
    enabled: openSection === "rounds",
  });

  const live = LIVE_STATUSES.has(tournament.status);

  const toggleSection = (section: "rounds" | "teams") =>
    setOpenSection((current) => (current === section ? null : section));

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border bg-card transition-colors",
        live ? "border-primary/30" : "border-border"
      )}
    >
      {/* Franja de estado: lo primero que se lee, como el marcador de una transmisión */}
      <div
        className={cn(
          "flex items-center justify-between gap-3 border-b px-4 py-2",
          live ? "border-primary/20 bg-primary/5" : "border-border bg-surface-sunken"
        )}
      >
        {live ? (
          <LiveIndicator />
        ) : (
          <span className="label-broadcast">
            {TOURNAMENT_STATUS_LABEL[tournament.status] ?? tournament.status}
          </span>
        )}
        {tournament.current_round && (
          <span className="flex items-center gap-2">
            <span className="font-heading text-sm font-semibold uppercase tracking-wide">
              {tournament.current_round.name}
            </span>
            <RoundStatusBadge status={tournament.current_round.status} />
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={() => router.push(`/tournaments/${tournament.id}`)}
        className="group flex w-full flex-col gap-4 p-4 text-left transition-colors hover:bg-accent/30"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate font-heading display-md font-bold uppercase">
              {tournament.name}
            </h3>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {tournament.source_base_url.replace("https://", "")}
            </p>
          </div>
          <ArrowRight className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
        </div>

        {/* Los números mandan: es una app de datos, no una lista de texto */}
        <div className="flex items-end gap-6">
          <StatNumber
            value={tournament.teams_count}
            label="Equipos"
            size="md"
            tone={tournament.teams_count > 0 ? "default" : "muted"}
          />
          <StatNumber
            value={tournament.open_markets_count}
            label="Mercados"
            size="md"
            tone={tournament.open_markets_count > 0 ? "primary" : "muted"}
          />
        </div>
      </button>

      {/* Expansores: rondas y equipos sin salir de la página */}
      <div className="flex gap-px border-t border-border bg-border">
        {(
          [
            ["rounds", "Rondas"],
            ["teams", "Equipos"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => toggleSection(key)}
            className={cn(
              "label-broadcast flex flex-1 items-center justify-center gap-1.5 py-2.5 transition-colors",
              openSection === key
                ? "bg-primary/10 text-primary"
                : "bg-card hover:bg-accent/40 hover:text-foreground"
            )}
          >
            {label}
            <ChevronDown
              className={cn(
                "size-3 transition-transform",
                openSection === key && "rotate-180"
              )}
            />
          </button>
        ))}
      </div>

      {openSection === "rounds" && (
        <div className="border-t border-border bg-surface-sunken p-3">
          {dashboard ? (
            <RoundsPanel
              tournamentId={String(tournament.id)}
              rounds={dashboard.rounds}
              defaultOpenRoundId={dashboard.current_round?.id ?? null}
            />
          ) : (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-11 w-full rounded-lg" />
              ))}
            </div>
          )}
        </div>
      )}
      {openSection === "teams" && (
        <div className="border-t border-border bg-surface-sunken p-3">
          <TeamsPanel tournamentId={String(tournament.id)} />
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { data: tournaments, isLoading, error } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const active = (tournaments ?? []).filter((t) => t.status !== "completed");
  const finished = (tournaments ?? []).filter((t) => t.status === "completed");
  const openMarkets = (tournaments ?? []).reduce(
    (sum, t) => sum + t.open_markets_count,
    0
  );

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-5 px-4 py-6">
      {/* Cabecera de transmisión: el dato agregado arriba de todo, no un párrafo */}
      <header className="flex items-end justify-between gap-4 border-b border-border pb-4">
        <div>
          <StatLabel>Claim</StatLabel>
          <h1 className="font-heading display-lg font-bold uppercase">Dashboard</h1>
        </div>
        {tournaments && tournaments.length > 0 && (
          <StatNumber
            value={openMarkets}
            label="Mercados abiertos"
            size="lg"
            tone={openMarkets > 0 ? "primary" : "muted"}
            className="items-end text-right"
          />
        )}
      </header>

      {isLoading && (
        <div className="flex flex-col gap-3">
          <TournamentCardSkeleton />
          <TournamentCardSkeleton />
        </div>
      )}
      {error && <ErrorState error={error} />}
      {tournaments && tournaments.length === 0 && (
        <EmptyState
          title="Todavía no hay torneos"
          description="Cuando un admin agregue un torneo desde el panel, aparecerá aquí."
        />
      )}

      {active.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionRule title="En juego" meta={`${active.length}`} />
          <div className="flex flex-col gap-3">
            {active.map((t) => (
              <TournamentCard key={t.id} tournament={t} />
            ))}
          </div>
        </section>
      )}

      {finished.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionRule title="Terminados" meta={`${finished.length}`} />
          <div className="flex flex-col gap-3">
            {finished.map((t) => (
              <TournamentCard key={t.id} tournament={t} />
            ))}
          </div>
        </section>
      )}

      <Link
        href="/bets"
        className="group flex items-center justify-center gap-2 rounded-lg border border-border bg-card py-3 text-sm font-medium transition-colors hover:border-primary/40 hover:bg-primary/5"
      >
        Ir a los mercados abiertos
        <ArrowRight className="size-4 text-primary transition-transform group-hover:translate-x-0.5" />
      </Link>
    </div>
  );
}
