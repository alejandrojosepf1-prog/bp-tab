"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  ExternalLink,
  Medal,
  Swords,
  Ticket,
  Users,
} from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { RoundsPanel, RoundStatusBadge } from "@/components/tournament/rounds-panel";
import { TeamsPanel } from "@/components/tournament/teams-panel";
import { MarketCard } from "@/components/betting/market-card";
import { cn } from "@/lib/utils";

const TOURNAMENT_STATUS_LABEL: Record<string, string> = {
  upcoming: "Próximo",
  in_progress: "En curso",
  break_pending: "Break pendiente",
  eliminations: "Eliminatorias",
  completed: "Completado",
};

function Section({
  icon: Icon,
  title,
  children,
  id,
}: {
  icon: typeof Swords;
  title: string;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className="flex flex-col gap-3">
      <h2 className="flex items-center gap-2 font-heading text-base font-bold">
        <Icon className="size-4 text-primary" /> {title}
      </h2>
      {children}
    </section>
  );
}

export default function TournamentPage() {
  const { id } = useParams<{ id: string }>();

  const { data: tournament, isLoading, error } = useQuery({
    queryKey: queryKeys.tournament(id),
    queryFn: () => api.tournaments.get(id),
    staleTime: 30_000,
  });

  const { data: dashboard } = useQuery({
    queryKey: queryKeys.dashboard(id),
    queryFn: () => api.dashboard.get(id),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const { data: standings } = useQuery({
    queryKey: queryKeys.standings(id),
    queryFn: () => api.standings.list(id),
    staleTime: 15_000,
  });

  const { data: markets } = useQuery({
    queryKey: queryKeys.betMarkets(id),
    queryFn: () => api.betMarkets.list(id),
    staleTime: 15_000,
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
  const { data: leaderboard } = useQuery({
    queryKey: queryKeys.leaderboard(id),
    queryFn: () => api.leaderboard.list(id),
    staleTime: 30_000,
  });

  if (isLoading) return <LoadingState label="Cargando torneo…" />;
  if (error) return <ErrorState error={error} />;
  if (!tournament) return null;

  const sourceUrl = `${tournament.source_base_url}/${tournament.source_slug}/`;
  const openMarkets = (markets ?? []).filter((m) => m.status === "open");
  const otherMarkets = (markets ?? []).filter((m) => m.status !== "open");

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-4 py-8">
      {/* Hero */}
      <div className="flex flex-col gap-3">
        <Link
          href="/dashboard"
          className="flex w-fit items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Dashboard
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-heading text-2xl font-bold tracking-tight">{tournament.name}</h1>
          <Badge
            variant="outline"
            className={cn(
              tournament.status === "completed"
                ? "border-border bg-muted text-muted-foreground"
                : "border-primary/40 bg-primary/10 text-primary"
            )}
          >
            {TOURNAMENT_STATUS_LABEL[tournament.status] ?? tournament.status}
          </Badge>
          {tournament.current_round && (
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Swords className="size-4" />
              {tournament.current_round.name}
              <RoundStatusBadge status={tournament.current_round.status} />
            </span>
          )}
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Tab oficial <ExternalLink className="size-3" />
          </a>
        </div>
      </div>

      {/* Rondas: la actual abierta por defecto, las pasadas expandibles inline */}
      <Section icon={Swords} title="Rondas" id="rondas">
        {dashboard ? (
          <RoundsPanel
            tournamentId={id}
            rounds={dashboard.rounds}
            defaultOpenRoundId={dashboard.current_round?.id ?? null}
          />
        ) : (
          <LoadingState label="Cargando rondas…" />
        )}
      </Section>

      {/* Mercados */}
      <Section icon={Ticket} title="Mercados de apuestas" id="mercados">
        {!markets && <LoadingState label="Cargando mercados…" />}
        {markets && markets.length === 0 && (
          <EmptyState title="Sin mercados en este torneo todavía" />
        )}
        <div className="flex flex-col gap-3">
          {openMarkets.map((market) => (
            <MarketCard
              key={market.id}
              tournamentId={id}
              market={market}
              teams={teams ?? []}
              speakers={speakers ?? []}
              institutions={institutions ?? []}
              defaultExpanded={openMarkets.length === 1}
            />
          ))}
          {otherMarkets.map((market) => (
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
      </Section>

      {/* Standings */}
      <Section icon={BarChart3} title="Standings" id="standings">
        {!standings && <LoadingState label="Cargando standings…" />}
        {standings && standings.length === 0 && <EmptyState title="Sin resultados todavía" />}
        {standings && standings.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-border/70">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 bg-muted/40 text-left text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                  <th className="px-3 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">Equipo</th>
                  <th className="px-3 py-2 text-right font-medium">Pts</th>
                  <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">
                    1º/2º/3º/4º
                  </th>
                  <th className="px-3 py-2 text-right font-medium">Debates</th>
                </tr>
              </thead>
              <tbody>
                {standings.map((s) => (
                  <tr key={s.team.id} className="border-b border-border/40 last:border-b-0">
                    <td className="px-3 py-2 font-mono text-muted-foreground">{s.rank}</td>
                    <td className="max-w-0 truncate px-3 py-2" style={{ width: "55%" }}>
                      <span className="font-medium">
                        {s.team.emoji} {s.team.name}
                      </span>
                      <span className="ml-2 hidden text-xs text-muted-foreground md:inline">
                        {s.team.speakers.map((sp) => sp.name).join(" · ")}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono font-semibold">
                      {s.team_points}
                    </td>
                    <td className="hidden px-3 py-2 text-right font-mono text-xs text-muted-foreground sm:table-cell">
                      {s.firsts}/{s.seconds}/{s.thirds}/{s.fourths}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                      {s.debates_played}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Equipos */}
      <Section icon={Users} title="Equipos" id="equipos">
        <TeamsPanel tournamentId={id} />
      </Section>

      {/* Ranking de apostadores */}
      <Section icon={Medal} title="Ranking de apostadores" id="apostadores">
        {leaderboard && leaderboard.length === 0 && (
          <EmptyState title="Nadie ha cobrado una apuesta todavía" />
        )}
        {leaderboard && leaderboard.length > 0 && (
          <div className="flex flex-col divide-y divide-border/50 rounded-xl border border-border/70">
            {leaderboard.map((entry) => (
              <div
                key={entry.user.id}
                className="flex items-center gap-3 px-4 py-2.5 text-sm"
              >
                <span className="w-6 font-mono text-muted-foreground">#{entry.rank}</span>
                <span className="flex-1 font-medium">{entry.user.display_name}</span>
                <span
                  className={cn(
                    "font-mono font-semibold",
                    entry.total_points >= 0 ? "text-primary" : "text-destructive"
                  )}
                >
                  {entry.total_points >= 0 ? "+" : "−"}$
                  {Math.abs(entry.total_points).toLocaleString("es")}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
