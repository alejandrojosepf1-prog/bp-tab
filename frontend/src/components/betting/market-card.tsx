"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronDown, Coins, Loader2, Users } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { OptionPicker } from "@/components/ui/option-picker";
import { CountdownBadge } from "@/components/ui/countdown-badge";
import { LoadingState } from "@/components/query-state";
import { MotionPanel } from "@/components/tournament/motion-panel";
import { cn } from "@/lib/utils";
import { formatTokens } from "@/lib/format";
import type {
  BetMarket,
  BetType,
  Institution,
  Prediction,
  Round,
  Speaker,
  Team,
  TeamStanding,
} from "@/lib/api/types";

export const BET_TYPE_LABELS: Record<string, string> = {
  champion: "Campeón del torneo",
  round_winner: "Ganador de debate",
  round_full_call: "Call completo de un debate",
  top_speaker_position: "Posición en el top 3 de oradores",
  team_break: "Equipo que hace break",
  round_head_to_head: "Enfrentamiento directo en sala",
  round_advancing_pair: "Par exacto que avanza (eliminatorias)",
  // Retirados de la creación de mercados, pero un mercado viejo todavía podría existir.
  top_n_break: "Top 3 equipos que rompen (en orden)",
  top_n_speakers: "Top 3 speakers (en orden)",
  head_to_head: "Cara a cara entre equipos",
  breakout_team: "Equipo revelación",
  best_institution: "Mejor institución",
};

const MARKET_STATUS_LABEL: Record<string, string> = {
  open: "Abierto",
  closed: "Cerrado",
  settled: "Liquidado",
};

/** Mirrors the backend's `app.services.betting_service._entity_key` exactly: a user can hold
 * one OPEN prediction per entity within a market (one per debate/slot/team), not one per
 * market. Used to match the currently-configured payload against the user's existing
 * predictions on this market, e.g. "did I already bet on THIS debate / THIS position". */
function entityKeyForPayload(
  betType: BetType,
  payload: Record<string, unknown> | null | undefined
): string | null {
  if (!payload) return null;
  switch (betType) {
    case "round_winner":
    case "round_full_call":
    case "round_advancing_pair":
      return payload.debate_id != null ? `debate:${payload.debate_id}` : null;
    case "top_speaker_position":
      return payload.position != null ? `position:${payload.position}` : null;
    case "team_break":
      return payload.team_id != null ? `team:${payload.team_id}` : null;
    case "head_to_head": {
      const a = payload.team_a_id as number | undefined;
      const b = payload.team_b_id as number | undefined;
      if (a == null || b == null) return null;
      const [x, y] = [Number(a), Number(b)].sort((m, n) => m - n);
      return `pair:${x}:${y}`;
    }
    case "round_head_to_head": {
      const a = payload.team_a_id as number | undefined;
      const b = payload.team_b_id as number | undefined;
      if (payload.debate_id == null || a == null || b == null) return null;
      const [x, y] = [Number(a), Number(b)].sort((m, n) => m - n);
      return `debate:${payload.debate_id}:pair:${x}:${y}`;
    }
    default:
      return "__market__";
  }
}

/* ------------------------------------------------------------------------------------ */
/* Board en vivo: pool, apostadores, cuotas y pagos por opción                           */
/* ------------------------------------------------------------------------------------ */

function MarketBoardTable({ marketId }: { marketId: number }) {
  const { data: board, isLoading } = useQuery({
    queryKey: queryKeys.marketBoard(marketId),
    queryFn: () => api.betMarkets.board(marketId),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });

  if (isLoading) return <LoadingState label="Cargando mercado…" />;
  if (!board) return null;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 font-medium text-primary">
          <Coins className="size-3.5" /> Pool ${board.pool_total.toLocaleString("es")}
        </span>
        <span className="flex items-center gap-1 rounded-md bg-muted px-2 py-1">
          <Users className="size-3.5" /> {board.bettors}{" "}
          {board.bettors === 1 ? "apostador" : "apostadores"}
        </span>
      </div>
      {board.options.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border/60">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 bg-muted/40 text-left text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                <th className="px-2.5 py-1.5 font-medium">Opción</th>
                <th className="hidden px-2.5 py-1.5 text-right font-medium sm:table-cell">
                  Prob. implícita
                </th>
                <th className="px-2.5 py-1.5 text-right font-medium">Apostado</th>
                <th className="px-2.5 py-1.5 text-right font-medium">Cuota</th>
                <th className="hidden px-2.5 py-1.5 text-right font-medium sm:table-cell">
                  100 tokens pagan
                </th>
              </tr>
            </thead>
            <tbody>
              {board.options.slice(0, 10).map((option, i) => (
                <tr
                  key={option.key}
                  className={cn(
                    "border-b border-border/40 last:border-b-0",
                    // La opción más cara del board (favorita) resalta un poco -- de un vistazo
                    // se ve a quién le está creyendo la plata, sin tener que leer cada fila.
                    i === 0 && "bg-primary/[0.03]"
                  )}
                >
                  <td className="max-w-0 truncate px-2.5 py-1.5" style={{ width: "40%" }}>
                    {option.emoji && <span className="mr-1">{option.emoji}</span>}
                    {option.label}
                  </td>
                  <td className="hidden px-2.5 py-1.5 text-right font-mono text-xs text-muted-foreground sm:table-cell">
                    {Math.round((1 / option.odds) * 100)}%
                  </td>
                  <td className="px-2.5 py-1.5 text-right font-mono text-xs">
                    {formatTokens(option.stake)}
                    {option.backers > 0 && (
                      <span className="ml-1 text-muted-foreground">({option.backers})</span>
                    )}
                  </td>
                  <td className="px-2.5 py-1.5 text-right font-mono font-semibold text-primary">
                    {option.odds.toFixed(2)}x
                  </td>
                  <td className="hidden px-2.5 py-1.5 text-right font-mono text-xs text-muted-foreground sm:table-cell">
                    {formatTokens(option.odds * 100)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------------------ */
/* Pickers por tipo de apuesta — listas clicables, cero dropdowns                        */
/* ------------------------------------------------------------------------------------ */

interface PickerProps {
  tournamentId: string;
  market: BetMarket;
  teams: Team[];
  speakers: Speaker[];
  institutions: Institution[];
  /** Standings al momento, por team id -- para dar contexto (posición/puntos) al elegir un
   * equipo, en vez de que el usuario tenga que adivinar quién es fuerte por el nombre solo. */
  standingsByTeamId: Map<number, TeamStanding>;
  /** The single existing prediction's payload, for single-entity bet types where a user can
   * only ever hold one (champion, best_institution, head_to_head, ...). */
  existingPayload: Record<string, unknown> | undefined;
  /** Every OPEN-or-settled prediction this user holds on this market -- for multi-entity bet
   * types (round_winner, round_full_call, top_speaker_position, team_break) where a user can
   * hold one per debate/slot/team, so a picker can mark "ya apostado" per entity. */
  myPredictions: Prediction[];
  onPayloadChange: (payload: Record<string, unknown> | null) => void;
}

/** "#3 · 18 pts", o undefined si el equipo todavía no tiene standing (antes de la ronda 1). */
function standingLabel(standingsByTeamId: Map<number, TeamStanding>, teamId: number) {
  const s = standingsByTeamId.get(teamId);
  return s ? `#${s.rank} · ${s.team_points} pts` : undefined;
}

/** Badge compacto de standing, reusado en cada botón de equipo de los pickers por sala --
 * contexto rápido (posición, puntos) para decidir sin tener que abrir standings aparte. */
function TeamStandingBadge({
  standingsByTeamId,
  teamId,
}: {
  standingsByTeamId: Map<number, TeamStanding>;
  teamId: number;
}) {
  const label = standingLabel(standingsByTeamId, teamId);
  if (!label) return null;
  return <span className="font-mono text-[0.65rem] text-muted-foreground">{label}</span>;
}

const teamOptions = (teams: Team[], standingsByTeamId: Map<number, TeamStanding>) =>
  teams.map((t) => {
    const roster = t.speakers.map((s) => s.name).join(" · ");
    const standing = standingLabel(standingsByTeamId, t.id);
    return {
      value: String(t.id),
      label: t.name,
      emoji: t.emoji,
      hint: [standing, roster].filter(Boolean).join(" · ") || undefined,
    };
  });

function TeamPick({ teams, standingsByTeamId, existingPayload, onPayloadChange }: PickerProps) {
  const [teamId, setTeamId] = useState<string | null>(
    existingPayload?.team_id ? String(existingPayload.team_id) : null
  );
  return (
    <OptionPicker
      options={teamOptions(teams, standingsByTeamId)}
      value={teamId}
      onChange={(v) => {
        setTeamId(v);
        onPayloadChange({ team_id: Number(v) });
      }}
      placeholder="Buscar equipo…"
      columns={2}
    />
  );
}

function InstitutionPick({ institutions, existingPayload, onPayloadChange }: PickerProps) {
  const [code, setCode] = useState<string | null>(
    typeof existingPayload?.institution_code === "string"
      ? existingPayload.institution_code
      : null
  );
  if (!institutions.length) {
    return (
      <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
        Este torneo no publica instituciones, así que este mercado no se puede jugar.
      </p>
    );
  }
  return (
    <OptionPicker
      options={institutions.map((i) => ({
        value: i.code,
        label: i.name,
        hint: i.code,
      }))}
      value={code}
      onChange={(v) => {
        setCode(v);
        onPayloadChange({ institution_code: v });
      }}
      placeholder="Buscar institución…"
    />
  );
}

const RANK_LABELS = ["1º", "2º", "3º"];
const FULL_CALL_RANK_LABELS = ["1º", "2º", "3º", "4º"];

function OrderedPick({
  options,
  existingIds,
  onChange,
  itemLabel,
  labels = RANK_LABELS,
}: {
  options: { value: string; label: string; emoji?: string | null; hint?: string }[];
  existingIds: string[];
  onChange: (ids: string[] | null) => void;
  itemLabel: string;
  labels?: string[];
}) {
  const [picks, setPicks] = useState<string[]>(labels.map((_, i) => existingIds[i] ?? ""));
  const [slot, setSlot] = useState(0);

  function setPick(value: string) {
    const next = picks.map((p, i) => (i === slot ? value : p));
    setPicks(next);
    onChange(next.every(Boolean) ? next : null);
    if (slot < labels.length - 1) setSlot(slot + 1);
  }

  const available = options.filter(
    (o) => !picks.includes(o.value) || picks[slot] === o.value
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {labels.map((label, i) => {
          const picked = options.find((o) => o.value === picks[i]);
          return (
            <button
              key={label}
              type="button"
              onClick={() => setSlot(i)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm transition-colors",
                slot === i
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card hover:bg-accent"
              )}
            >
              <span className="text-xs font-semibold text-muted-foreground">{label}</span>
              {picked ? (
                <span className="max-w-40 truncate">
                  {picked.emoji} {picked.label}
                </span>
              ) : (
                <span className="text-muted-foreground">elegir {itemLabel}</span>
              )}
            </button>
          );
        })}
      </div>
      <OptionPicker
        options={available}
        value={picks[slot] || null}
        onChange={setPick}
        placeholder={`Buscar ${itemLabel} para el puesto ${labels[slot]}…`}
        columns={2}
      />
    </div>
  );
}

function TopTeamsPick({ teams, standingsByTeamId, existingPayload, onPayloadChange }: PickerProps) {
  const existing = Array.isArray(existingPayload?.team_ids)
    ? (existingPayload.team_ids as number[]).map(String)
    : [];
  return (
    <OrderedPick
      options={teamOptions(teams, standingsByTeamId)}
      existingIds={existing}
      itemLabel="equipo"
      onChange={(ids) => onPayloadChange(ids ? { team_ids: ids.map(Number) } : null)}
    />
  );
}

function TopSpeakersPick({ speakers, existingPayload, onPayloadChange }: PickerProps) {
  const existing = Array.isArray(existingPayload?.speaker_ids)
    ? (existingPayload.speaker_ids as number[]).map(String)
    : [];
  return (
    <OrderedPick
      options={speakers.map((s) => ({ value: String(s.id), label: s.name }))}
      existingIds={existing}
      itemLabel="speaker"
      onChange={(ids) => onPayloadChange(ids ? { speaker_ids: ids.map(Number) } : null)}
    />
  );
}

function HeadToHeadPick({ teams, standingsByTeamId, existingPayload, onPayloadChange }: PickerProps) {
  const [teamA, setTeamA] = useState<string | null>(
    existingPayload?.team_a_id ? String(existingPayload.team_a_id) : null
  );
  const [teamB, setTeamB] = useState<string | null>(
    existingPayload?.team_b_id ? String(existingPayload.team_b_id) : null
  );
  const [winner, setWinner] = useState<string | null>(
    existingPayload?.predicted_winner_id ? String(existingPayload.predicted_winner_id) : null
  );

  function emit(a: string | null, b: string | null, w: string | null) {
    const complete = a && b && a !== b && w && (w === a || w === b);
    onPayloadChange(
      complete
        ? { team_a_id: Number(a), team_b_id: Number(b), predicted_winner_id: Number(w) }
        : null
    );
  }

  const nameOf = (id: string | null) => teams.find((t) => String(t.id) === id)?.name ?? "";

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">Equipo A</span>
          <OptionPicker
            options={teamOptions(teams, standingsByTeamId)}
            value={teamA}
            onChange={(v) => {
              setTeamA(v);
              const nextWinner = winner === teamA ? null : winner;
              setWinner(nextWinner);
              emit(v, teamB, nextWinner);
            }}
            maxHeight="max-h-40"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">Equipo B</span>
          <OptionPicker
            options={teamOptions(teams, standingsByTeamId).filter((o) => o.value !== teamA)}
            value={teamB}
            onChange={(v) => {
              setTeamB(v);
              const nextWinner = winner === teamB ? null : winner;
              setWinner(nextWinner);
              emit(teamA, v, nextWinner);
            }}
            maxHeight="max-h-40"
          />
        </div>
      </div>
      {teamA && teamB && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">¿Quién termina mejor rankeado?</span>
          {[teamA, teamB].map((id) => (
            <Button
              key={id}
              type="button"
              size="sm"
              variant={winner === id ? "default" : "outline"}
              onClick={() => {
                setWinner(id);
                emit(teamA, teamB, id);
              }}
            >
              {nameOf(id)}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Shared by RoundWinnerPick/RoundFullCallPick: a round market is always scoped to ONE round
 * via market.target_round_id (required at creation), so betting UI jumps straight to that
 * round's debates instead of letting the user free-pick any round. */
function useRoundDebates(tournamentId: string, market: BetMarket) {
  const roundId = market.target_round_id ? String(market.target_round_id) : null;
  const { data: round } = useQuery({
    queryKey: queryKeys.rounds(tournamentId),
    queryFn: () => api.rounds.list(tournamentId),
    staleTime: 60_000,
    select: (rounds: Round[]) => rounds.find((r) => String(r.id) === roundId),
  });
  const { data: debates } = useQuery({
    queryKey: queryKeys.roundDebates(tournamentId, roundId ?? "none"),
    queryFn: () => api.rounds.debates(tournamentId, roundId!),
    enabled: !!roundId,
    staleTime: 30_000,
  });
  return { round, debates: debates ?? [], isElimination: round?.stage === "elimination" };
}

/** La moción de la ronda del mercado, arriba del picker. Comparte queryKey con
 * `useRoundDebates`, así que React Query lo deduplica: no agrega ni un request. */
function RoundMotionBanner({
  tournamentId,
  market,
}: {
  tournamentId: string;
  market: BetMarket;
}) {
  const { round } = useRoundDebates(tournamentId, market);
  if (!market.target_round_id) return null;
  return (
    <MotionPanel
      motionText={round?.motion_text}
      infoSlide={round?.info_slide}
      roundName={round?.name}
    />
  );
}

/** For multi-entity bet types, look up whether the user already has an OPEN/settled
 * prediction matching a given entity_key -- used to show "ya apostado $X" hints and, for
 * top_speaker_position, to actually lock an already-assigned slot. */
function findByEntityKey(
  myPredictions: Prediction[],
  betType: BetType,
  key: string
): Prediction | undefined {
  return myPredictions.find((p) => entityKeyForPayload(betType, p.payload) === key);
}

function RoundWinnerPick({
  tournamentId,
  market,
  standingsByTeamId,
  myPredictions,
  onPayloadChange,
}: PickerProps) {
  const [debateId, setDebateId] = useState<string | null>(null);
  const [teamId, setTeamId] = useState<number | null>(null);
  const [subBetOpen, setSubBetOpen] = useState(false);
  const [speakerPoints, setSpeakerPoints] = useState<Record<number, string>>({});
  const { round, debates, isElimination } = useRoundDebates(tournamentId, market);
  const selectedDebate = debates.find((d) => String(d.id) === debateId);
  const selectedTeam = selectedDebate?.teams.find((dt) => dt.team.id === teamId)?.team;
  const existingForDebate = debateId
    ? findByEntityKey(myPredictions, "round_winner", `debate:${debateId}`)
    : undefined;

  if (!market.target_round_id) {
    return <p className="text-xs text-muted-foreground">Este mercado no tiene ronda asignada.</p>;
  }

  function emit(
    debate: string | null,
    team: number | null,
    open: boolean,
    points: Record<number, string>
  ) {
    if (!debate || !team) {
      onPayloadChange(null);
      return;
    }
    const payload: Record<string, unknown> = { debate_id: Number(debate), team_id: team };
    if (open && selectedTeam) {
      const entries = selectedTeam.speakers.map((s) => {
        const raw = points[s.id];
        const value = raw !== undefined && raw !== "" ? Number(raw) : null;
        return { speaker_id: s.id, points: value };
      });
      if (entries.length === 2 && entries.every((e) => e.points !== null && Number.isFinite(e.points))) {
        payload.sub_bet = { speaker_scores: entries };
      }
    }
    onPayloadChange(payload);
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Elegí el debate de <span className="font-medium text-foreground">{round?.name ?? "esta ronda"}</span> —
        podés apostar en varias salas de esta ronda, una apuesta por sala.
      </p>
      {isElimination && (
        // En eliminatorias el tab nunca publica el 1º-4º, sólo quién avanza -- y avanzan 2 de 4
        // (1 en la final). El backend ya cotiza esto como top-N; acá se explicita para que nadie
        // lea "ganador" como "salió primero".
        <p className="rounded-lg border border-dashed border-primary/30 bg-primary/[0.04] px-3 py-2 text-xs text-muted-foreground">
          Ronda eliminatoria: apostás a que el equipo{" "}
          <span className="font-medium text-foreground">avanza</span> de su sala, no a que sale
          primero. Avanzan 2 de 4 equipos (en la final, 1), y la cuota ya está calculada así.
        </p>
      )}
      <OptionPicker
        options={debates.map((d) => {
          const existing = findByEntityKey(myPredictions, "round_winner", `debate:${d.id}`);
          return {
            value: String(d.id),
            label: d.room?.name ? `Sala ${d.room.name}` : `Debate #${d.id}`,
            hint:
              d.teams.map((t) => t.team.name).join(" · ") +
              (existing ? ` · ya apostaste ${formatTokens(existing.stake_amount)}` : ""),
          };
        })}
        value={debateId}
        onChange={(v) => {
          setDebateId(v);
          setTeamId(null);
          setSubBetOpen(false);
          setSpeakerPoints({});
          onPayloadChange(null);
        }}
        placeholder="Buscar sala o equipo…"
        maxHeight="max-h-40"
      />

      {existingForDebate && (
        <p className="text-xs text-muted-foreground">
          Ya tenés {formatTokens(existingForDebate.stake_amount)} apostados en esta sala — elegir
          de nuevo reemplaza esa apuesta.
        </p>
      )}

      {selectedDebate && (
        <div className="flex flex-wrap items-stretch gap-2">
          <span className="self-center text-xs text-muted-foreground">
            {isElimination ? "Avanza:" : "Ganador:"}
          </span>
          {selectedDebate.teams.map((dt) => (
            <button
              key={dt.team.id}
              type="button"
              onClick={() => {
                setTeamId(dt.team.id);
                setSubBetOpen(false);
                setSpeakerPoints({});
                onPayloadChange({ debate_id: Number(debateId), team_id: dt.team.id });
              }}
              className={cn(
                "flex flex-col items-start rounded-lg border px-3 py-1.5 text-sm transition-colors",
                teamId === dt.team.id
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card hover:border-primary/50 hover:bg-primary/10"
              )}
            >
              <span>
                {dt.team.emoji} {dt.team.name}
              </span>
              <TeamStandingBadge standingsByTeamId={standingsByTeamId} teamId={dt.team.id} />
              {dt.team.speakers.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  {dt.team.speakers.map((s) => s.name).join(" · ")}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {selectedTeam && selectedTeam.speakers.length === 2 && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border px-3 py-2">
          <button
            type="button"
            onClick={() => {
              const next = !subBetOpen;
              setSubBetOpen(next);
              emit(debateId, teamId, next, speakerPoints);
            }}
            className="w-fit text-xs font-medium text-primary hover:underline"
          >
            {subBetOpen ? "− Quitar apuesta específica" : "+ Añadir apuesta específica"}
          </button>
          {subBetOpen && (
            <>
              <p className="text-xs text-muted-foreground">
                Bono si además acertás los puntos EXACTOS de los dos oradores de{" "}
                {selectedTeam.name} en este debate. La apuesta base se cobra apenas se sabe quién
                ganó la ronda, sin esperar esto — el bono se liquida aparte, más adelante (a
                veces recién al final del torneo, cuando el tab libera los puntajes), y solo
                SUMA: nunca te quita lo que ya cobraste.
              </p>
              <div className="flex flex-wrap items-end gap-3">
                {selectedTeam.speakers.map((speaker) => (
                  <div key={speaker.id} className="flex flex-col gap-1">
                    <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                      {speaker.name}
                    </span>
                    <Input
                      type="number"
                      step="0.1"
                      placeholder="76.5"
                      className="h-8 w-24 font-mono"
                      value={speakerPoints[speaker.id] ?? ""}
                      onChange={(e) => {
                        const next = { ...speakerPoints, [speaker.id]: e.target.value };
                        setSpeakerPoints(next);
                        emit(debateId, teamId, subBetOpen, next);
                      }}
                    />
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function RoundFullCallPick({
  tournamentId,
  market,
  standingsByTeamId,
  myPredictions,
  onPayloadChange,
}: PickerProps) {
  const [debateId, setDebateId] = useState<string | null>(null);
  const { round, debates } = useRoundDebates(tournamentId, market);
  const selectedDebate = debates.find((d) => String(d.id) === debateId);
  const existingForDebate = debateId
    ? findByEntityKey(myPredictions, "round_full_call", `debate:${debateId}`)
    : undefined;

  if (!market.target_round_id) {
    return <p className="text-xs text-muted-foreground">Este mercado no tiene ronda asignada.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Elegí el debate de <span className="font-medium text-foreground">{round?.name ?? "esta ronda"}</span>{" "}
        y ordená los 4 equipos de 1º a 4º — podés apostar en varias salas, una apuesta por sala.
      </p>
      <OptionPicker
        options={debates.map((d) => {
          const existing = findByEntityKey(myPredictions, "round_full_call", `debate:${d.id}`);
          return {
            value: String(d.id),
            label: d.room?.name ? `Sala ${d.room.name}` : `Debate #${d.id}`,
            hint:
              d.teams.map((t) => t.team.name).join(" · ") +
              (existing ? ` · ya apostaste ${formatTokens(existing.stake_amount)}` : ""),
          };
        })}
        value={debateId}
        onChange={(v) => {
          setDebateId(v);
          onPayloadChange(null);
        }}
        placeholder="Buscar sala o equipo…"
        maxHeight="max-h-40"
      />

      {existingForDebate && (
        <p className="text-xs text-muted-foreground">
          Ya tenés {formatTokens(existingForDebate.stake_amount)} apostados en esta sala — elegir
          de nuevo reemplaza esa apuesta.
        </p>
      )}

      {selectedDebate && (
        <OrderedPick
          key={debateId}
          options={selectedDebate.teams.map((dt) => ({
            value: String(dt.team.id),
            label: dt.team.name,
            emoji: dt.team.emoji,
            hint:
              [
                standingLabel(standingsByTeamId, dt.team.id),
                dt.team.speakers.map((s) => s.name).join(" · ") || undefined,
              ]
                .filter(Boolean)
                .join(" · ") || undefined,
          }))}
          existingIds={[]}
          itemLabel="equipo"
          labels={FULL_CALL_RANK_LABELS}
          onChange={(ids) =>
            onPayloadChange(ids ? { debate_id: Number(debateId), team_ids: ids.map(Number) } : null)
          }
        />
      )}
    </div>
  );
}

const RANK_GAP_OPTIONS = [1, 2, 3];

function HeadToHeadRoomPick({
  tournamentId,
  market,
  standingsByTeamId,
  myPredictions,
  onPayloadChange,
}: PickerProps) {
  const [debateId, setDebateId] = useState<string | null>(null);
  const [teamA, setTeamA] = useState<string | null>(null);
  const [teamB, setTeamB] = useState<string | null>(null);
  const [higherId, setHigherId] = useState<string | null>(null);
  const [subBetOpen, setSubBetOpen] = useState(false);
  const [rankGap, setRankGap] = useState<number | null>(null);
  const { round, debates } = useRoundDebates(tournamentId, market);
  const selectedDebate = debates.find((d) => String(d.id) === debateId);
  const existingForDebate = debateId
    ? findByEntityKey(myPredictions, "round_head_to_head", `debate:${debateId}`)
    : undefined;

  if (!market.target_round_id) {
    return <p className="text-xs text-muted-foreground">Este mercado no tiene ronda asignada.</p>;
  }

  function emit(a: string | null, b: string | null, higher: string | null, gap: number | null) {
    const complete = debateId && a && b && a !== b && higher && (higher === a || higher === b);
    if (!complete) {
      onPayloadChange(null);
      return;
    }
    const payload: Record<string, unknown> = {
      debate_id: Number(debateId),
      team_a_id: Number(a),
      team_b_id: Number(b),
      predicted_higher_id: Number(higher),
    };
    if (subBetOpen && gap != null) payload.sub_bet = { rank_gap: gap };
    onPayloadChange(payload);
  }

  const debateTeamOptions = (exclude: string | null) =>
    (selectedDebate?.teams ?? [])
      .filter((dt) => String(dt.team.id) !== exclude)
      .map((dt) => ({
        value: String(dt.team.id),
        label: dt.team.name,
        emoji: dt.team.emoji,
        hint:
          [
            standingLabel(standingsByTeamId, dt.team.id),
            dt.team.speakers.map((s) => s.name).join(" · ") || undefined,
          ]
            .filter(Boolean)
            .join(" · ") || undefined,
      }));

  const nameOf = (id: string | null) =>
    selectedDebate?.teams.find((dt) => String(dt.team.id) === id)?.team.name ?? "";

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Elegí el debate de{" "}
        <span className="font-medium text-foreground">{round?.name ?? "esta ronda"}</span> y los
        dos equipos a comparar — podés apostar en varias salas, una apuesta por par de equipos.
      </p>
      <OptionPicker
        options={debates.map((d) => ({
          value: String(d.id),
          label: d.room?.name ? `Sala ${d.room.name}` : `Debate #${d.id}`,
          hint: d.teams.map((t) => t.team.name).join(" · "),
        }))}
        value={debateId}
        onChange={(v) => {
          setDebateId(v);
          setTeamA(null);
          setTeamB(null);
          setHigherId(null);
          setRankGap(null);
          onPayloadChange(null);
        }}
        placeholder="Buscar sala…"
        maxHeight="max-h-40"
      />

      {existingForDebate && (
        <p className="text-xs text-muted-foreground">
          Ya tenés {formatTokens(existingForDebate.stake_amount)} apostados en esta sala — elegir
          de nuevo reemplaza esa apuesta.
        </p>
      )}

      {selectedDebate && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Equipo 1</span>
            <OptionPicker
              options={debateTeamOptions(teamB)}
              value={teamA}
              onChange={(v) => {
                setTeamA(v);
                const nextHigher = higherId === teamA ? null : higherId;
                setHigherId(nextHigher);
                emit(v, teamB, nextHigher, rankGap);
              }}
              maxHeight="max-h-40"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Equipo 2</span>
            <OptionPicker
              options={debateTeamOptions(teamA)}
              value={teamB}
              onChange={(v) => {
                setTeamB(v);
                const nextHigher = higherId === teamB ? null : higherId;
                setHigherId(nextHigher);
                emit(teamA, v, nextHigher, rankGap);
              }}
              maxHeight="max-h-40"
            />
          </div>
        </div>
      )}

      {teamA && teamB && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">¿Cuál queda más arriba?</span>
          {[teamA, teamB].map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => {
                setHigherId(id);
                emit(teamA, teamB, id, rankGap);
              }}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                higherId === id
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card hover:border-primary/50 hover:bg-primary/10"
              )}
            >
              {nameOf(id)}
            </button>
          ))}
        </div>
      )}

      {higherId && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border px-3 py-2">
          <button
            type="button"
            onClick={() => {
              const next = !subBetOpen;
              setSubBetOpen(next);
              const nextGap = next ? rankGap : null;
              if (!next) setRankGap(null);
              emit(teamA, teamB, higherId, nextGap);
            }}
            className="w-fit text-xs font-medium text-primary hover:underline"
          >
            {subBetOpen ? "− Quitar apuesta específica" : "+ Añadir apuesta específica"}
          </button>
          {subBetOpen && (
            <>
              <p className="text-xs text-muted-foreground">
                Bono si además acertás la diferencia EXACTA de puestos entre los dos equipos —
                si fallás esto, se pierde toda la apuesta, incluso si acertaste quién queda
                arriba.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {RANK_GAP_OPTIONS.map((gap) => (
                  <button
                    key={gap}
                    type="button"
                    onClick={() => {
                      setRankGap(gap);
                      emit(teamA, teamB, higherId, gap);
                    }}
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                      rankGap === gap
                        ? "border-primary/50 bg-primary/10 text-primary"
                        : "border-border bg-card hover:bg-accent"
                    )}
                  >
                    {gap} puesto{gap > 1 ? "s" : ""}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Eliminatorias, "par exacto que avanza": elegí la sala y los 2 EQUIPOS EXACTOS (no importa el
 * orden) que pasan a la siguiente ronda -- distinto de RoundWinnerPick (un equipo, gana/avanza
 * solo) y de RoundFullCallPick (los 4 equipos EN ORDEN). El backend ya valida que esta sala
 * tenga exactamente 2 cupos de avance (no aplica a la final, donde avanza 1). */
function AdvancingPairPick({
  tournamentId,
  market,
  standingsByTeamId,
  myPredictions,
  onPayloadChange,
}: PickerProps) {
  const [debateId, setDebateId] = useState<string | null>(null);
  const [teamIds, setTeamIds] = useState<number[]>([]);
  const { round, debates } = useRoundDebates(tournamentId, market);
  const selectedDebate = debates.find((d) => String(d.id) === debateId);
  const existingForDebate = debateId
    ? findByEntityKey(myPredictions, "round_advancing_pair", `debate:${debateId}`)
    : undefined;

  if (!market.target_round_id) {
    return <p className="text-xs text-muted-foreground">Este mercado no tiene ronda asignada.</p>;
  }

  function toggleTeam(teamId: number) {
    setTeamIds((prev) => {
      // Elegir un 3er equipo reemplaza al primero elegido -- una pareja siempre tiene 2, nunca
      // más, así que no hace falta destildar a mano antes de cambiar de opinión.
      const next = prev.includes(teamId)
        ? prev.filter((id) => id !== teamId)
        : prev.length < 2
          ? [...prev, teamId]
          : [prev[1], teamId];
      onPayloadChange(
        debateId && next.length === 2 ? { debate_id: Number(debateId), team_ids: next } : null
      );
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Elegí el debate de{" "}
        <span className="font-medium text-foreground">{round?.name ?? "esta ronda"}</span> y los
        2 equipos EXACTOS que avanzan de esa sala (el orden entre ellos no importa).
      </p>
      <OptionPicker
        options={debates.map((d) => {
          const existing = findByEntityKey(
            myPredictions,
            "round_advancing_pair",
            `debate:${d.id}`
          );
          return {
            value: String(d.id),
            label: d.room?.name ? `Sala ${d.room.name}` : `Debate #${d.id}`,
            hint:
              d.teams.map((t) => t.team.name).join(" · ") +
              (existing ? ` · ya apostaste ${formatTokens(existing.stake_amount)}` : ""),
          };
        })}
        value={debateId}
        onChange={(v) => {
          setDebateId(v);
          setTeamIds([]);
          onPayloadChange(null);
        }}
        placeholder="Buscar sala…"
        maxHeight="max-h-40"
      />

      {existingForDebate && (
        <p className="text-xs text-muted-foreground">
          Ya tenés {formatTokens(existingForDebate.stake_amount)} apostados en esta sala — elegir
          de nuevo reemplaza esa apuesta.
        </p>
      )}

      {selectedDebate && (
        <div className="flex flex-wrap items-stretch gap-2">
          <span className="self-center text-xs text-muted-foreground">
            Avanzan ({teamIds.length}/2):
          </span>
          {selectedDebate.teams.map((dt) => {
            const picked = teamIds.includes(dt.team.id);
            return (
              <button
                key={dt.team.id}
                type="button"
                onClick={() => toggleTeam(dt.team.id)}
                className={cn(
                  "flex flex-col items-start rounded-lg border px-3 py-1.5 text-sm transition-colors",
                  picked
                    ? "border-primary/50 bg-primary/10 text-primary"
                    : "border-border bg-card hover:border-primary/50 hover:bg-primary/10"
                )}
              >
                <span>
                  {dt.team.emoji} {dt.team.name}
                </span>
                <TeamStandingBadge standingsByTeamId={standingsByTeamId} teamId={dt.team.id} />
                {dt.team.speakers.length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {dt.team.speakers.map((s) => s.name).join(" · ")}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SpeakerPositionPick({ speakers, myPredictions, onPayloadChange }: PickerProps) {
  const [speakerId, setSpeakerId] = useState<string | null>(null);
  const [position, setPosition] = useState<number | null>(null);

  const usedByPosition = new Map(
    [1, 2, 3].map((p) => [
      p,
      findByEntityKey(myPredictions, "top_speaker_position", `position:${p}`),
    ])
  );

  function emit(nextSpeakerId: string | null, nextPosition: number | null) {
    onPayloadChange(
      nextSpeakerId && nextPosition
        ? { speaker_id: Number(nextSpeakerId), position: nextPosition }
        : null
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <OptionPicker
        options={speakers.map((s) => ({ value: String(s.id), label: s.name }))}
        value={speakerId}
        onChange={(v) => {
          setSpeakerId(v);
          emit(v, position);
        }}
        placeholder="Buscar orador…"
        columns={2}
      />
      {speakerId && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-muted-foreground">
            ¿En qué puesto del top 3 termina? Cada puesto se asigna una sola vez.
          </span>
          <div className="flex flex-wrap items-center gap-2">
            {[1, 2, 3].map((p) => {
              const usedBy = usedByPosition.get(p);
              const usedByName = speakers.find(
                (s) => s.id === (usedBy?.payload.speaker_id as number | undefined)
              )?.name;
              return (
                <Button
                  key={p}
                  type="button"
                  size="sm"
                  disabled={!!usedBy}
                  variant={position === p ? "default" : "outline"}
                  onClick={() => {
                    setPosition(p);
                    emit(speakerId, p);
                  }}
                  title={usedBy ? `Ya asignaste ${usedByName ?? "un orador"} a ${p}º` : undefined}
                >
                  {p}º{usedBy ? ` — ${usedByName ?? "asignado"}` : ""}
                </Button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function TeamBreakPick({ tournamentId, market, myPredictions, onPayloadChange }: PickerProps) {
  const [teamId, setTeamId] = useState<string | null>(null);
  const [subBetOpen, setSubBetOpen] = useState(false);
  const [exactRank, setExactRank] = useState("");
  const [exactPoints, setExactPoints] = useState("");
  const categoryId = market.target_break_category_id;
  const { data: predictions } = useQuery({
    queryKey: queryKeys.breakPredictions(tournamentId, categoryId ?? "none"),
    queryFn: () => api.breakCategories.predictions(tournamentId, categoryId!),
    enabled: !!categoryId,
    staleTime: 30_000,
  });

  if (!categoryId) {
    return (
      <p className="text-xs text-muted-foreground">
        Este mercado no tiene categoría de break asignada.
      </p>
    );
  }

  const existingForTeam = teamId
    ? findByEntityKey(myPredictions, "team_break", `team:${teamId}`)
    : undefined;

  function emit(team: string | null, open: boolean, rank: string, points: string) {
    if (!team) {
      onPayloadChange(null);
      return;
    }
    const payload: Record<string, unknown> = { team_id: Number(team) };
    const rankNum = Number(rank);
    if (open && rank !== "" && Number.isInteger(rankNum) && rankNum > 0) {
      const subBet: Record<string, unknown> = { exact_rank: rankNum };
      const pointsNum = Number(points);
      if (points !== "" && Number.isFinite(pointsNum)) {
        subBet.exact_points = pointsNum;
      }
      payload.sub_bet = subBet;
    }
    onPayloadChange(payload);
  }

  const options = (predictions ?? []).map((p) => {
    const existing = findByEntityKey(myPredictions, "team_break", `team:${p.team.id}`);
    const speakerNames = p.team.speakers.map((s) => s.name).join(" · ");
    return {
      value: String(p.team.id),
      label: p.team.name,
      emoji: p.team.emoji,
      hint:
        (speakerNames ? `${speakerNames} · ` : "") +
        `${Math.round(p.probability * 100)}% de romper ahora mismo` +
        (existing ? ` · ya apostaste ${formatTokens(existing.stake_amount)}` : ""),
    };
  });

  return (
    <div className="flex flex-col gap-2">
      <OptionPicker
        options={options}
        value={teamId}
        onChange={(v) => {
          setTeamId(v);
          emit(v, subBetOpen, exactRank, exactPoints);
        }}
        placeholder="Buscar equipo…"
        emptyLabel="Sin equipos registrados en esta categoría todavía"
        columns={2}
      />
      {existingForTeam && (
        <p className="text-xs text-muted-foreground">
          Ya tenés {formatTokens(existingForTeam.stake_amount)} apostados a este equipo — apostar
          de nuevo reemplaza esa apuesta.
        </p>
      )}

      {teamId && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border px-3 py-2">
          <button
            type="button"
            onClick={() => {
              const next = !subBetOpen;
              setSubBetOpen(next);
              emit(teamId, next, exactRank, exactPoints);
            }}
            className="w-fit text-xs font-medium text-primary hover:underline"
          >
            {subBetOpen ? "− Quitar apuesta específica" : "+ Añadir apuesta específica"}
          </button>
          {subBetOpen && (
            <>
              <p className="text-xs text-muted-foreground">
                Bono si además acertás el puesto EXACTO de ruptura (y, opcional, los puntos
                exactos) — es todo o nada: si esta parte falla, se pierde la apuesta completa
                aunque el equipo sí haya roto.
              </p>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1">
                  <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                    Puesto exacto
                  </span>
                  <Input
                    type="number"
                    min="1"
                    step="1"
                    placeholder="1"
                    className="h-8 w-20 font-mono"
                    value={exactRank}
                    onChange={(e) => {
                      setExactRank(e.target.value);
                      emit(teamId, subBetOpen, e.target.value, exactPoints);
                    }}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                    Puntos exactos (opcional)
                  </span>
                  <Input
                    type="number"
                    step="1"
                    placeholder="ej. 24"
                    className="h-8 w-24 font-mono"
                    value={exactPoints}
                    onChange={(e) => {
                      setExactPoints(e.target.value);
                      emit(teamId, subBetOpen, exactRank, e.target.value);
                    }}
                  />
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------------------ */
/* Boleta: monto + cuota en vivo + enviar                                                */
/* ------------------------------------------------------------------------------------ */

function StakeSlip({
  marketId,
  payload,
  existing,
  isSaving,
  onSubmit,
}: {
  marketId: number;
  payload: Record<string, unknown> | null;
  existing: Prediction | null | undefined;
  isSaving: boolean;
  onSubmit: (stakeAmount: number) => void;
}) {
  const { user } = useAuth();
  const [stake, setStake] = useState<string>(existing ? String(existing.stake_amount) : "");

  const payloadKey = payload ? JSON.stringify(payload) : null;
  const { data: quote, isFetching: isQuoting } = useQuery({
    queryKey: ["odds-quote", marketId, payloadKey],
    queryFn: () => api.betMarkets.quoteOdds(marketId, payload as object),
    enabled: payload !== null,
    staleTime: 15_000,
    retry: false,
  });

  const stakeNumber = Number(stake);
  const stakeValid = stake !== "" && stakeNumber > 0;
  const overBalance = user != null && stakeValid && stakeNumber > user.balance + (existing?.status === "open" ? existing.stake_amount : 0);
  const odds = payload ? quote?.odds ?? null : null;
  // Present only when payload has a "sub_bet" key AND this bet_type prices one (see backend
  // odds_service.quote_sub_bet_odds) -- the combined price is all-or-nothing (see
  // betting_service._settle_prediction_payout): miss the modifier and the WHOLE payout is
  // lost, not just the bonus, so it's shown as one combined number, not base + extra.
  const subBetOdds = payload?.sub_bet ? quote?.sub_bet_odds ?? null : null;
  const combinedOdds = odds && subBetOdds ? odds * subBetOdds : odds;
  const potentialPayout =
    combinedOdds && stakeValid ? Math.round(stakeNumber * combinedOdds * 100) / 100 : null;
  const canSubmit = payload !== null && stakeValid && odds !== null && !isQuoting && !overBalance;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-primary/20 bg-primary/4 p-3">
      {existing && (
        <p className="text-xs text-muted-foreground">
          Ya tenés {formatTokens(existing.stake_amount)} a cuota {existing.odds}x en este
          mercado — apostar de nuevo reemplaza esa jugada (se te devuelve el monto anterior).
        </p>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Monto
          </span>
          <div className="flex items-center gap-1.5">
            <Coins className="size-3.5 text-muted-foreground" />
            <Input
              type="number"
              min="1"
              step="1"
              placeholder="100"
              className={cn("w-28 font-mono", overBalance && "border-destructive")}
              value={stake}
              onChange={(e) => setStake(e.target.value)}
            />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Cuota
          </span>
          <span className="font-mono text-lg font-semibold text-primary">
            {payload === null
              ? "—"
              : isQuoting
                ? "…"
                : combinedOdds !== null
                  ? `${combinedOdds.toFixed(2)}x`
                  : "n/d"}
          </span>
          {subBetOdds !== null && odds !== null && (
            <span className="text-[0.65rem] text-muted-foreground">
              {odds.toFixed(2)}x base × {subBetOdds.toFixed(2)}x específica
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Pago si acertás
          </span>
          <span className="font-mono text-lg font-semibold">
            {potentialPayout !== null ? formatTokens(potentialPayout) : "—"}
          </span>
        </div>
        <Button
          className="ml-auto"
          disabled={!canSubmit || isSaving}
          onClick={() => onSubmit(stakeNumber)}
        >
          {isSaving && <Loader2 className="size-4 animate-spin" />}
          {existing ? "Reemplazar apuesta" : "Apostar"}
        </Button>
      </div>
      {payload === null && (
        <p className="text-xs text-muted-foreground">Elegí tu pronóstico arriba para ver la cuota.</p>
      )}
      {overBalance && (
        <p className="text-xs text-destructive">
          No te alcanzan los tokens ({formatTokens(user?.balance ?? 0)}).
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------------------ */
/* Tarjeta completa de mercado                                                           */
/* ------------------------------------------------------------------------------------ */

export function MarketCard({
  tournamentId,
  market,
  teams,
  speakers,
  institutions,
  defaultExpanded = false,
}: {
  tournamentId: string;
  market: BetMarket;
  teams: Team[];
  speakers: Speaker[];
  institutions: Institution[];
  defaultExpanded?: boolean;
}) {
  const queryClient = useQueryClient();
  const { isAuthenticated } = useAuth();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);

  const { data: myPredictions = [] } = useQuery({
    queryKey: queryKeys.myPrediction(market.id),
    queryFn: () => api.betMarkets.myPredictions(market.id),
    enabled: isAuthenticated,
    staleTime: 10_000,
  });

  // Mismo queryKey/queryFn que la tabla de standings de la página del torneo -- React Query
  // dedupea el fetch entre ahí y cada MarketCard abierta, así que esto no agrega requests.
  const { data: standings = [] } = useQuery({
    queryKey: queryKeys.standings(tournamentId),
    queryFn: () => api.standings.list(tournamentId),
    staleTime: 15_000,
  });
  const standingsByTeamId = useMemo(
    () => new Map(standings.map((s) => [s.team.id, s])),
    [standings]
  );

  const mutation = useMutation({
    mutationFn: (stakeAmount: number) => {
      if (!payload) throw new Error("no payload");
      return api.betMarkets.createPrediction(market.id, payload, stakeAmount);
    },
    onSuccess: () => {
      toast.success("Apuesta guardada");
      queryClient.invalidateQueries({ queryKey: queryKeys.myPrediction(market.id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.marketBoard(market.id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard(tournamentId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.me });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "No se pudo guardar la apuesta");
    },
  });

  const [now] = useState(() => Date.now());
  const closesAt = new Date(market.closes_at);
  const isPastClose = closesAt.getTime() < now;
  const isOpen = market.status === "open" && !isPastClose;

  // Single-entity bet types (champion, best_institution, ...) still only ever hold one
  // prediction, so pickers for those pre-fill from it directly.
  const singleExistingPayload = myPredictions[0]?.payload;
  // The prediction matching whatever entity the user is CURRENTLY configuring (a specific
  // debate/position/team), so the stake slip shows "ya tenés X acá" for THAT entity, not just
  // whichever prediction happens to be first.
  const currentEntityKey = payload ? entityKeyForPayload(market.bet_type, payload) : null;
  const existingForCurrentSelection = currentEntityKey
    ? myPredictions.find(
        (p) => entityKeyForPayload(market.bet_type, p.payload) === currentEntityKey
      )
    : undefined;

  const pickerProps = useMemo(
    () => ({
      tournamentId,
      market,
      teams,
      speakers,
      institutions,
      standingsByTeamId,
      existingPayload: singleExistingPayload,
      myPredictions,
      onPayloadChange: setPayload,
    }),
    [
      tournamentId,
      market,
      teams,
      speakers,
      institutions,
      standingsByTeamId,
      singleExistingPayload,
      myPredictions,
    ]
  );

  let picker: React.ReactNode = null;
  switch (market.bet_type as BetType) {
    case "champion":
    case "breakout_team":
      picker = <TeamPick {...pickerProps} />;
      break;
    case "best_institution":
      picker = <InstitutionPick {...pickerProps} />;
      break;
    case "top_n_break":
      picker = <TopTeamsPick {...pickerProps} />;
      break;
    case "top_n_speakers":
      picker = <TopSpeakersPick {...pickerProps} />;
      break;
    case "head_to_head":
      picker = <HeadToHeadPick {...pickerProps} />;
      break;
    case "round_winner":
      picker = <RoundWinnerPick {...pickerProps} />;
      break;
    case "round_full_call":
      picker = <RoundFullCallPick {...pickerProps} />;
      break;
    case "top_speaker_position":
      picker = <SpeakerPositionPick {...pickerProps} />;
      break;
    case "team_break":
      picker = <TeamBreakPick {...pickerProps} />;
      break;
    case "round_head_to_head":
      picker = <HeadToHeadRoomPick {...pickerProps} />;
      break;
    case "round_advancing_pair":
      picker = <AdvancingPairPick {...pickerProps} />;
      break;
  }

  return (
    <div
      className={cn(
        "rounded-xl border bg-card/70 transition-all",
        expanded
          ? "border-primary/30"
          : // Colapsado, un mercado cerrado/liquidado se atenúa para que los abiertos dominen
            // la vista -- al expandirlo vuelve a opacidad completa, para que revisarlo no sea
            // incómodo de leer.
            isOpen
            ? "border-border"
            : "border-border/50 opacity-70 hover:opacity-100"
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left hover:bg-accent/30"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-heading text-sm font-semibold">{market.label}</p>
          <p className="truncate text-xs text-muted-foreground">
            {BET_TYPE_LABELS[market.bet_type] ?? market.bet_type}
            {market.description ? ` · ${market.description}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <CountdownBadge
            target={market.closes_at}
            prefix="cierra"
            className="hidden text-xs sm:block"
          />
          <Badge
            variant="outline"
            className={cn(
              isOpen
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border bg-muted text-muted-foreground"
            )}
          >
            {MARKET_STATUS_LABEL[market.status] ?? market.status}
          </Badge>
          <ChevronDown
            className={cn(
              "size-4 text-muted-foreground transition-transform",
              expanded && "rotate-180"
            )}
          />
        </div>
      </button>

      {expanded && (
        <div className="flex flex-col gap-4 border-t border-border/60 p-4">
          {/* Qué se debate, antes que cualquier número: sin esto había que abrir el tab en otra
              pestaña para poder decidir una apuesta con criterio. */}
          <RoundMotionBanner tournamentId={tournamentId} market={market} />
          <MarketBoardTable marketId={market.id} />

          {myPredictions.length > 0 && (
            <div className="flex flex-col gap-1 rounded-lg bg-muted/30 p-2.5">
              <span className="text-[0.7rem] font-medium uppercase tracking-wider text-muted-foreground">
                {myPredictions.length > 1 ? "Tus jugadas en este mercado" : "Tu jugada"}
              </span>
              {myPredictions.map((p) => (
                <p key={p.id} className="text-xs text-muted-foreground">
                  {formatTokens(p.stake_amount)} a cuota {p.odds}x
                  {p.points_awarded !== null &&
                    (p.points_awarded > 0 ? (
                      <span className="ml-1 font-medium text-primary">
                        → cobraste {formatTokens(p.points_awarded)}
                      </span>
                    ) : (
                      <span className="ml-1 font-medium text-destructive">→ perdida</span>
                    ))}
                  {p.payload.sub_bet != null && p.sub_bet_odds != null && (
                    <span className="ml-1">
                      · apuesta específica ({p.sub_bet_odds}x)
                      {p.sub_bet_status === "settled" ? (
                        (p.sub_bet_points_awarded ?? 0) > 0 ? (
                          <span className="ml-1 font-medium text-primary">acertada</span>
                        ) : (
                          <span className="ml-1 font-medium text-destructive">fallada</span>
                        )
                      ) : (
                        <span className="ml-1">pendiente</span>
                      )}
                    </span>
                  )}
                </p>
              ))}
            </div>
          )}

          {isOpen && isAuthenticated && (
            <>
              {picker}
              <StakeSlip
                // Remounts (resetting the stake input) whenever the selected entity changes,
                // e.g. switching from a debate that already has a bet to one that doesn't --
                // otherwise the input would keep showing the PREVIOUS entity's stake.
                key={currentEntityKey ?? "none"}
                marketId={market.id}
                payload={payload}
                existing={existingForCurrentSelection ?? null}
                isSaving={mutation.isPending}
                onSubmit={(stakeAmount) => mutation.mutate(stakeAmount)}
              />
            </>
          )}
          {isOpen && !isAuthenticated && (
            <p className="rounded-lg border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
              Iniciá sesión para apostar en este mercado.
            </p>
          )}
          {!isOpen && (
            <p className="text-xs text-muted-foreground">
              Este mercado ya no acepta apuestas.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
