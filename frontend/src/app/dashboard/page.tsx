"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronDown, Swords, Ticket, Trophy, Users } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { ErrorState, EmptyState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { RoundsPanel, RoundStatusBadge } from "@/components/tournament/rounds-panel";
import { TeamsPanel } from "@/components/tournament/teams-panel";
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

/** Misma forma que TournamentCard (borde redondeado, cabecera + fila de chips + tab bar) para
 * que no haya salto de layout cuando cambia de esqueleto a la tarjeta real. */
function TournamentCardSkeleton() {
  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-border bg-card/80">
      <div className="flex flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3 w-32" />
          </div>
          <Skeleton className="h-5 w-20 shrink-0 rounded-full" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton className="h-7 w-28 rounded-lg" />
          <Skeleton className="h-7 w-24 rounded-lg" />
          <Skeleton className="h-7 w-32 rounded-lg" />
        </div>
      </div>
      <div className="flex border-t border-border/60">
        <Skeleton className="m-2 h-7 flex-1 rounded-md" />
        <Skeleton className="m-2 h-7 flex-1 rounded-md" />
      </div>
    </div>
  );
}

function RoundsPanelSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-12 w-full rounded-xl" />
      ))}
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
        "flex flex-col overflow-hidden rounded-2xl border bg-card/80 transition-colors",
        live ? "border-primary/25" : "border-border"
      )}
    >
      {/* Cabecera clicable: navega directo a la vista del torneo */}
      <button
        type="button"
        onClick={() => router.push(`/tournaments/${tournament.id}`)}
        className="group flex flex-col gap-3 p-5 text-left transition-colors hover:bg-accent/30"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate font-heading text-lg font-bold">{tournament.name}</h3>
            <p className="text-xs text-muted-foreground">
              {tournament.source_base_url.replace("https://", "")}
            </p>
          </div>
          <Badge
            variant="outline"
            className={cn(
              live
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border bg-muted text-muted-foreground"
            )}
          >
            {live && (
              <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-primary" />
            )}
            {TOURNAMENT_STATUS_LABEL[tournament.status] ?? tournament.status}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="flex items-center gap-1.5 rounded-lg bg-muted/60 px-2.5 py-1.5">
            <Swords className="size-3.5 text-primary" />
            {tournament.current_round ? (
              <>
                <span className="font-medium">{tournament.current_round.name}</span>
                <RoundStatusBadge status={tournament.current_round.status} />
              </>
            ) : (
              <span className="text-muted-foreground">Sin rondas aún</span>
            )}
          </span>
          <span className="flex items-center gap-1.5 rounded-lg bg-muted/60 px-2.5 py-1.5 text-muted-foreground">
            <Users className="size-3.5" /> {tournament.teams_count} equipos
          </span>
          <span className="flex items-center gap-1.5 rounded-lg bg-muted/60 px-2.5 py-1.5 text-muted-foreground">
            <Ticket className="size-3.5" /> {tournament.open_markets_count}{" "}
            {tournament.open_markets_count === 1 ? "mercado abierto" : "mercados abiertos"}
          </span>
          <span className="ml-auto flex items-center gap-1 font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
            Ver torneo <ArrowRight className="size-3.5" />
          </span>
        </div>
      </button>

      {/* Expansores inline: rondas con resultados y equipos con integrantes, sin navegar */}
      <div className="flex border-t border-border/60">
        {(
          [
            ["rounds", "Rondas y resultados"],
            ["teams", "Equipos"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => toggleSection(key)}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors",
              openSection === key
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
            )}
          >
            {label}
            <ChevronDown
              className={cn("size-3.5 transition-transform", openSection === key && "rotate-180")}
            />
          </button>
        ))}
      </div>

      {openSection === "rounds" && (
        <div className="border-t border-border/60 p-4">
          {dashboard ? (
            <RoundsPanel
              tournamentId={String(tournament.id)}
              rounds={dashboard.rounds}
              defaultOpenRoundId={dashboard.current_round?.id ?? null}
            />
          ) : (
            <RoundsPanelSkeleton />
          )}
        </div>
      )}
      {openSection === "teams" && (
        <div className="border-t border-border/60 p-4">
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

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="font-heading text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Torneos en vivo, rondas y mercados — todo en un vistazo.
        </p>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-4">
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
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            <Trophy className="size-4 text-primary" /> En juego
          </h2>
          <div className="flex flex-col gap-4">
            {active.map((t) => (
              <TournamentCard key={t.id} tournament={t} />
            ))}
          </div>
        </section>
      )}

      {finished.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Terminados
          </h2>
          <div className="flex flex-col gap-4">
            {finished.map((t) => (
              <TournamentCard key={t.id} tournament={t} />
            ))}
          </div>
        </section>
      )}

      <p className="text-center text-xs text-muted-foreground">
        ¿Buscás apostar?{" "}
        <Link href="/bets" className="font-medium text-primary hover:underline">
          Ir a los mercados abiertos →
        </Link>
      </p>
    </div>
  );
}
