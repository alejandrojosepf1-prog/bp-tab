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
import { cn } from "@/lib/utils";
import type {
  BetMarket,
  BetType,
  Institution,
  Prediction,
  Round,
  Speaker,
  Team,
} from "@/lib/api/types";

export const BET_TYPE_LABELS: Record<string, string> = {
  champion: "Campeón del torneo",
  round_winner: "Ganador de debate",
  round_full_call: "Call completo de un debate",
  top_speaker_position: "Posición en el top 3 de oradores",
  team_break: "Equipo que hace break",
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
                <th className="px-2.5 py-1.5 text-right font-medium">Apostado</th>
                <th className="px-2.5 py-1.5 text-right font-medium">Cuota</th>
                <th className="hidden px-2.5 py-1.5 text-right font-medium sm:table-cell">
                  $100 pagan
                </th>
              </tr>
            </thead>
            <tbody>
              {board.options.slice(0, 10).map((option) => (
                <tr key={option.key} className="border-b border-border/40 last:border-b-0">
                  <td className="max-w-0 truncate px-2.5 py-1.5" style={{ width: "50%" }}>
                    {option.emoji && <span className="mr-1">{option.emoji}</span>}
                    {option.label}
                  </td>
                  <td className="px-2.5 py-1.5 text-right font-mono text-xs">
                    ${option.stake.toLocaleString("es")}
                    {option.backers > 0 && (
                      <span className="ml-1 text-muted-foreground">({option.backers})</span>
                    )}
                  </td>
                  <td className="px-2.5 py-1.5 text-right font-mono font-semibold text-primary">
                    {option.odds.toFixed(2)}x
                  </td>
                  <td className="hidden px-2.5 py-1.5 text-right font-mono text-xs text-muted-foreground sm:table-cell">
                    ${Math.round(option.odds * 100).toLocaleString("es")}
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
  /** The single existing prediction's payload, for single-entity bet types where a user can
   * only ever hold one (champion, best_institution, head_to_head, ...). */
  existingPayload: Record<string, unknown> | undefined;
  /** Every OPEN-or-settled prediction this user holds on this market -- for multi-entity bet
   * types (round_winner, round_full_call, top_speaker_position, team_break) where a user can
   * hold one per debate/slot/team, so a picker can mark "ya apostado" per entity. */
  myPredictions: Prediction[];
  onPayloadChange: (payload: Record<string, unknown> | null) => void;
}

const teamOptions = (teams: Team[]) =>
  teams.map((t) => ({
    value: String(t.id),
    label: t.name,
    emoji: t.emoji,
    hint: t.speakers.map((s) => s.name).join(" · ") || undefined,
  }));

function TeamPick({ teams, existingPayload, onPayloadChange }: PickerProps) {
  const [teamId, setTeamId] = useState<string | null>(
    existingPayload?.team_id ? String(existingPayload.team_id) : null
  );
  return (
    <OptionPicker
      options={teamOptions(teams)}
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

function TopTeamsPick({ teams, existingPayload, onPayloadChange }: PickerProps) {
  const existing = Array.isArray(existingPayload?.team_ids)
    ? (existingPayload.team_ids as number[]).map(String)
    : [];
  return (
    <OrderedPick
      options={teamOptions(teams)}
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

function HeadToHeadPick({ teams, existingPayload, onPayloadChange }: PickerProps) {
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
            options={teamOptions(teams)}
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
            options={teamOptions(teams).filter((o) => o.value !== teamA)}
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
  return { round, debates: debates ?? [] };
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
  myPredictions,
  onPayloadChange,
}: PickerProps) {
  const [debateId, setDebateId] = useState<string | null>(null);
  const [teamId, setTeamId] = useState<number | null>(null);
  const { round, debates } = useRoundDebates(tournamentId, market);
  const selectedDebate = debates.find((d) => String(d.id) === debateId);
  const existingForDebate = debateId
    ? findByEntityKey(myPredictions, "round_winner", `debate:${debateId}`)
    : undefined;

  if (!market.target_round_id) {
    return <p className="text-xs text-muted-foreground">Este mercado no tiene ronda asignada.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Elegí el debate de <span className="font-medium text-foreground">{round?.name ?? "esta ronda"}</span> —
        podés apostar en varias salas de esta ronda, una apuesta por sala.
      </p>
      <OptionPicker
        options={debates.map((d) => {
          const existing = findByEntityKey(myPredictions, "round_winner", `debate:${d.id}`);
          return {
            value: String(d.id),
            label: d.room?.name ? `Sala ${d.room.name}` : `Debate #${d.id}`,
            hint:
              d.teams.map((t) => t.team.name).join(" · ") +
              (existing ? ` · ya apostaste $${existing.stake_amount}` : ""),
          };
        })}
        value={debateId}
        onChange={(v) => {
          setDebateId(v);
          setTeamId(null);
          onPayloadChange(null);
        }}
        placeholder="Buscar sala o equipo…"
        maxHeight="max-h-40"
      />

      {existingForDebate && (
        <p className="text-xs text-muted-foreground">
          Ya tenés ${existingForDebate.stake_amount} apostados en esta sala — elegir de nuevo
          reemplaza esa apuesta.
        </p>
      )}

      {selectedDebate && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Ganador:</span>
          {selectedDebate.teams.map((dt) => (
            <button
              key={dt.team.id}
              type="button"
              onClick={() => {
                setTeamId(dt.team.id);
                onPayloadChange({ debate_id: Number(debateId), team_id: dt.team.id });
              }}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                teamId === dt.team.id
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-card hover:border-primary/50 hover:bg-primary/10"
              )}
            >
              {dt.team.emoji} {dt.team.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function RoundFullCallPick({
  tournamentId,
  market,
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
              (existing ? ` · ya apostaste $${existing.stake_amount}` : ""),
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
          Ya tenés ${existingForDebate.stake_amount} apostados en esta sala — elegir de nuevo
          reemplaza esa apuesta.
        </p>
      )}

      {selectedDebate && (
        <OrderedPick
          key={debateId}
          options={selectedDebate.teams.map((dt) => ({
            value: String(dt.team.id),
            label: dt.team.name,
            emoji: dt.team.emoji,
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

  const options = (predictions ?? []).map((p) => {
    const existing = findByEntityKey(myPredictions, "team_break", `team:${p.team.id}`);
    return {
      value: String(p.team.id),
      label: p.team.name,
      emoji: p.team.emoji,
      hint:
        `${Math.round(p.probability * 100)}% de romper ahora mismo` +
        (existing ? ` · ya apostaste $${existing.stake_amount}` : ""),
    };
  });

  return (
    <div className="flex flex-col gap-2">
      <OptionPicker
        options={options}
        value={teamId}
        onChange={(v) => {
          setTeamId(v);
          onPayloadChange(v ? { team_id: Number(v) } : null);
        }}
        placeholder="Buscar equipo…"
        emptyLabel="Sin equipos registrados en esta categoría todavía"
        columns={2}
      />
      {existingForTeam && (
        <p className="text-xs text-muted-foreground">
          Ya tenés ${existingForTeam.stake_amount} apostados a este equipo — apostar de nuevo
          reemplaza esa apuesta.
        </p>
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
  const potentialPayout =
    odds && stakeValid ? Math.round(stakeNumber * odds * 100) / 100 : null;
  const canSubmit = payload !== null && stakeValid && odds !== null && !isQuoting && !overBalance;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-primary/20 bg-primary/4 p-3">
      {existing && (
        <p className="text-xs text-muted-foreground">
          Ya tenés ${existing.stake_amount.toLocaleString("es")} a cuota {existing.odds}x en
          este mercado — apostar de nuevo reemplaza esa jugada (se te devuelve el monto
          anterior).
        </p>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Monto
          </span>
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-muted-foreground">$</span>
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
                : odds !== null
                  ? `${odds.toFixed(2)}x`
                  : "n/d"}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            Pago si acertás
          </span>
          <span className="font-mono text-lg font-semibold">
            {potentialPayout !== null ? `$${potentialPayout.toLocaleString("es")}` : "—"}
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
          No te alcanzan los tokens (${user?.balance.toLocaleString("es")}).
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
      existingPayload: singleExistingPayload,
      myPredictions,
      onPayloadChange: setPayload,
    }),
    [tournamentId, market, teams, speakers, institutions, singleExistingPayload, myPredictions]
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
  }

  return (
    <div
      className={cn(
        "rounded-xl border bg-card/70 transition-colors",
        expanded ? "border-primary/30" : "border-border"
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
          <MarketBoardTable marketId={market.id} />

          {myPredictions.length > 0 && (
            <div className="flex flex-col gap-1 rounded-lg bg-muted/30 p-2.5">
              <span className="text-[0.7rem] font-medium uppercase tracking-wider text-muted-foreground">
                {myPredictions.length > 1 ? "Tus jugadas en este mercado" : "Tu jugada"}
              </span>
              {myPredictions.map((p) => (
                <p key={p.id} className="text-xs text-muted-foreground">
                  ${p.stake_amount.toLocaleString("es")} a cuota {p.odds}x
                  {p.points_awarded !== null &&
                    (p.points_awarded > 0 ? (
                      <span className="ml-1 font-medium text-primary">
                        → cobraste ${p.points_awarded.toLocaleString("es")}
                      </span>
                    ) : (
                      <span className="ml-1 font-medium text-destructive">→ perdida</span>
                    ))}
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
