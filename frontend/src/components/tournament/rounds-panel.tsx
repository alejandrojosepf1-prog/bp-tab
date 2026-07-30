"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, DoorOpen, Swords } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { MotionPanel } from "@/components/tournament/motion-panel";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { DebateSummary, Round } from "@/lib/api/types";

const ROUND_STATUS_LABEL: Record<string, string> = {
  draft: "Sin sortear",
  released: "En curso",
  completed: "Completada",
};

const ROUND_STATUS_CLASS: Record<string, string> = {
  draft: "bg-muted text-muted-foreground border-transparent",
  released: "bg-primary/15 text-primary border-primary/30",
  completed: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

const POSITION_ORDER = ["OG", "OO", "CG", "CO"] as const;
const RANK_LABEL: Record<number, string> = { 1: "1º", 2: "2º", 3: "3º", 4: "4º" };

export function RoundStatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={cn("shrink-0", ROUND_STATUS_CLASS[status] ?? "")}>
      {ROUND_STATUS_LABEL[status] ?? status}
    </Badge>
  );
}

/** Resultados de un debate, renderizados inline (sin navegación a otra página). */
function DebateResultRow({ debate }: { debate: DebateSummary }) {
  const ordered = POSITION_ORDER.map((pos) => ({
    pos,
    entry: debate.teams.find((t) => t.position === pos) ?? null,
  }));
  return (
    <div className="rounded-lg border border-border/60 bg-background/50 p-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <DoorOpen className="size-3.5" />
        {debate.room?.name ? `Sala ${debate.room.name}` : "Sala por definir"}
      </div>
      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {ordered.map(({ pos, entry }) => (
          <div
            key={pos}
            className={cn(
              "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
              entry?.rank_in_debate === 1 ? "bg-primary/10" : "bg-muted/40"
            )}
          >
            <span className="w-7 shrink-0 text-[0.65rem] font-semibold uppercase text-muted-foreground">
              {pos}
            </span>
            {entry ? (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {entry.team.emoji} {entry.team.name}
                  </span>
                  <span className="block truncate text-[0.7rem] text-muted-foreground">
                    {entry.team.speakers.map((s) => s.name).join(" · ") || "Integrantes por confirmar"}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  {entry.rank_in_debate ? (
                    <span
                      className={cn(
                        "font-mono text-sm font-semibold",
                        entry.rank_in_debate === 1 ? "text-primary" : "text-foreground/80"
                      )}
                    >
                      {RANK_LABEL[entry.rank_in_debate] ?? `#${entry.rank_in_debate}`}
                      {entry.team_points !== null && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          {entry.team_points} pts
                        </span>
                      )}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">por jugar</span>
                  )}
                </span>
              </>
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function RoundDebates({ tournamentId, roundId }: { tournamentId: string; roundId: number }) {
  const { data: debates, isLoading, error } = useQuery({
    queryKey: queryKeys.roundDebates(tournamentId, roundId),
    queryFn: () => api.rounds.debates(tournamentId, roundId),
    staleTime: 20_000,
  });

  if (isLoading) return <LoadingState label="Cargando debates…" />;
  if (error) return <ErrorState error={error} />;
  if (!debates?.length) return <EmptyState title="Sin debates registrados para esta ronda" />;

  return (
    <div className="flex flex-col gap-2">
      {debates.map((debate) => (
        <DebateResultRow key={debate.id} debate={debate} />
      ))}
    </div>
  );
}

const ELIMINATION_HINT =
  "Ronda eliminatoria: no hay 1º-4º, sólo qué equipos avanzan.";

/**
 * Todas las rondas del torneo como filas expandibles: click en una ronda (pasada o actual)
 * despliega sus debates y resultados AHÍ MISMO — sin navegar y sin páginas en blanco.
 */
export function RoundsPanel({
  tournamentId,
  rounds,
  defaultOpenRoundId,
}: {
  tournamentId: string;
  rounds: Round[];
  defaultOpenRoundId?: number | null;
}) {
  const [openIds, setOpenIds] = useState<Set<number>>(
    () => new Set(defaultOpenRoundId ? [defaultOpenRoundId] : [])
  );

  const toggle = (id: number) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (!rounds.length) return <EmptyState title="Sin rondas todavía" />;

  return (
    <div className="flex flex-col gap-2">
      {rounds
        .slice()
        .sort((a, b) => a.seq - b.seq)
        .map((round) => {
          const open = openIds.has(round.id);
          const expandable = round.status !== "draft";
          return (
            <div
              key={round.id}
              className={cn(
                "rounded-xl border transition-colors",
                open ? "border-primary/30 bg-card" : "border-border bg-card/60"
              )}
            >
              <button
                type="button"
                disabled={!expandable}
                onClick={() => toggle(round.id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left",
                  expandable ? "cursor-pointer hover:bg-accent/40" : "opacity-60"
                )}
              >
                <Swords className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{round.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    #{round.seq} · {round.stage === "preliminary" ? "Preliminar" : "Eliminatoria"}
                    {round.motion_text ? ` · ${round.motion_text}` : ""}
                  </span>
                </span>
                <RoundStatusBadge status={round.status} />
                {expandable && (
                  <ChevronDown
                    className={cn(
                      "size-4 shrink-0 text-muted-foreground transition-transform",
                      open && "rotate-180"
                    )}
                  />
                )}
              </button>
              {open && expandable && (
                <div className="flex flex-col gap-3 border-t border-border/60 p-3">
                  <MotionPanel
                    motionText={round.motion_text}
                    infoSlide={round.info_slide}
                    roundName={round.name}
                  />
                  {round.stage === "elimination" && (
                    <p className="text-xs text-muted-foreground">{ELIMINATION_HINT}</p>
                  )}
                  <RoundDebates tournamentId={tournamentId} roundId={round.id} />
                </div>
              )}
            </div>
          );
        })}
    </div>
  );
}
