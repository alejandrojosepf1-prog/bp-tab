"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type {
  BetMarket,
  BetType,
  Institution,
  Prediction,
  Round,
  Speaker,
  Team,
} from "@/lib/api/types";

/**
 * One distinct mini-form per bet_type, since each has a different payload shape (see
 * docs/api_contract.md). Each sub-form only owns its "pick" UI and reports the current payload
 * (or null while incomplete) up to the shared `<StakeSlip>`, which owns the stake input, the
 * live odds/payout preview (via POST .../quote), and the actual submit button -- so the
 * stake/odds plumbing is written once instead of six times.
 */
export function PredictionForm({
  tournamentId,
  market,
  existing,
  teams,
  speakers,
  institutions,
}: {
  tournamentId: string;
  market: BetMarket;
  existing: Prediction | null;
  teams: Team[];
  speakers: Speaker[];
  institutions: Institution[];
}) {
  const queryClient = useQueryClient();
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);

  const mutation = useMutation({
    mutationFn: (stakeAmount: number) => {
      if (!payload) throw new Error("no payload");
      return api.betMarkets.createPrediction(market.id, payload, stakeAmount);
    },
    onSuccess: () => {
      toast.success("Apuesta guardada");
      queryClient.invalidateQueries({ queryKey: queryKeys.myPrediction(market.id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard(tournamentId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId) });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "No se pudo guardar la apuesta");
    },
  });

  const commonProps = {
    teams,
    speakers,
    institutions,
    tournamentId,
    existingPayload: existing?.payload,
    onPayloadChange: setPayload,
  };

  let picker: React.ReactNode;
  switch (market.bet_type as BetType) {
    case "champion":
    case "breakout_team":
      picker = <TeamPickForm {...commonProps} />;
      break;
    case "best_institution":
      picker = <InstitutionPickForm {...commonProps} />;
      break;
    case "top_n_break":
      picker = <OrderedTeamsForm {...commonProps} label="equipos" />;
      break;
    case "top_n_speakers":
      picker = <OrderedSpeakersForm {...commonProps} />;
      break;
    case "head_to_head":
      picker = <HeadToHeadForm {...commonProps} />;
      break;
    case "round_winner":
      picker = <RoundWinnerForm {...commonProps} />;
      break;
    default:
      picker = null;
  }

  return (
    <div className="flex flex-col gap-3">
      {picker}
      <StakeSlip
        marketId={market.id}
        payload={payload}
        existing={existing}
        isSaving={mutation.isPending}
        onSubmit={(stakeAmount) => mutation.mutate(stakeAmount)}
      />
    </div>
  );
}

/** Live odds preview + stake input + submit, shared by every bet_type's picker above. */
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
  const odds = quote?.odds ?? (payload ? null : existing?.odds ?? null);
  const potentialPayout = odds && stakeValid ? Math.round(stakeNumber * odds * 100) / 100 : null;
  const canSubmit = payload !== null && stakeValid && odds !== null && !isQuoting;

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border/60 bg-muted/30 p-3">
      {existing && (
        <p className="text-xs text-muted-foreground">
          Ya tenés ${existing.stake_amount} apostados a cuota {existing.odds}x en este mercado
          (reemplaza la apuesta anterior).
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5">
          <span className="text-sm text-muted-foreground">$</span>
          <Input
            type="number"
            min="1"
            step="1"
            placeholder="Monto a apostar"
            className="w-32"
            value={stake}
            onChange={(e) => setStake(e.target.value)}
          />
        </div>
        <span className="text-sm text-muted-foreground">
          {payload === null
            ? "Elegí tu pronóstico"
            : isQuoting
              ? "Calculando cuota…"
              : odds !== null
                ? `Cuota: ${odds}x`
                : "No se pudo calcular la cuota todavía"}
        </span>
      </div>
      {potentialPayout !== null && (
        <p className="text-sm">
          Si acertás, ganás <span className="font-semibold text-emerald-500">${potentialPayout}</span>
        </p>
      )}
      <div>
        <Button
          size="sm"
          disabled={!canSubmit || isSaving}
          onClick={() => onSubmit(stakeNumber)}
        >
          {isSaving && <Loader2 className="size-3.5 animate-spin" />}
          Apostar
        </Button>
      </div>
    </div>
  );
}

interface BaseFormProps {
  teams: Team[];
  speakers: Speaker[];
  institutions: Institution[];
  tournamentId: string;
  existingPayload: Record<string, unknown> | undefined;
  onPayloadChange: (payload: Record<string, unknown> | null) => void;
}

function TeamPickForm({ teams, existingPayload, onPayloadChange }: BaseFormProps) {
  const [teamId, setTeamId] = useState<string>(
    existingPayload?.team_id ? String(existingPayload.team_id) : ""
  );

  function pick(value: string) {
    setTeamId(value);
    onPayloadChange(value ? { team_id: Number(value) } : null);
  }

  return (
    <Select value={teamId} onValueChange={(v) => pick(v ?? "")}>
      <SelectTrigger className="w-[220px]">
        <SelectValue placeholder="Elegir equipo" />
      </SelectTrigger>
      <SelectContent>
        {teams.map((t) => (
          <SelectItem key={t.id} value={String(t.id)}>
            {t.emoji} {t.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function InstitutionPickForm({ institutions, existingPayload, onPayloadChange }: BaseFormProps) {
  const [code, setCode] = useState<string>(
    typeof existingPayload?.institution_code === "string" ? existingPayload.institution_code : ""
  );

  function pick(value: string) {
    setCode(value);
    onPayloadChange(value ? { institution_code: value } : null);
  }

  return (
    <Select value={code} onValueChange={(v) => pick(v ?? "")}>
      <SelectTrigger className="w-[220px]">
        <SelectValue placeholder="Elegir institución" />
      </SelectTrigger>
      <SelectContent>
        {institutions.map((inst) => (
          <SelectItem key={inst.id} value={inst.code}>
            {inst.name} ({inst.code})
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

const RANK_LABELS = ["1º", "2º", "3º"];

function OrderedTeamsForm({
  teams,
  existingPayload,
  onPayloadChange,
  label,
}: BaseFormProps & { label: string }) {
  const existingIds = Array.isArray(existingPayload?.team_ids)
    ? (existingPayload.team_ids as number[]).map(String)
    : [];
  const [picks, setPicks] = useState<string[]>([
    existingIds[0] ?? "",
    existingIds[1] ?? "",
    existingIds[2] ?? "",
  ]);

  function setPick(index: number, value: string) {
    const next = picks.map((p, i) => (i === index ? value : p));
    setPicks(next);
    onPayloadChange(next.every(Boolean) ? { team_ids: next.map(Number) } : null);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {RANK_LABELS.map((rankLabel, i) => (
        <Select key={i} value={picks[i]} onValueChange={(v) => setPick(i, v ?? "")}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder={`${rankLabel} ${label}`} />
          </SelectTrigger>
          <SelectContent>
            {teams
              .filter((t) => !picks.includes(String(t.id)) || picks[i] === String(t.id))
              .map((t) => (
                <SelectItem key={t.id} value={String(t.id)}>
                  {t.emoji} {t.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      ))}
    </div>
  );
}

function OrderedSpeakersForm({ speakers, existingPayload, onPayloadChange }: BaseFormProps) {
  const existingIds = Array.isArray(existingPayload?.speaker_ids)
    ? (existingPayload.speaker_ids as number[]).map(String)
    : [];
  const [picks, setPicks] = useState<string[]>([
    existingIds[0] ?? "",
    existingIds[1] ?? "",
    existingIds[2] ?? "",
  ]);

  function setPick(index: number, value: string) {
    const next = picks.map((p, i) => (i === index ? value : p));
    setPicks(next);
    onPayloadChange(next.every(Boolean) ? { speaker_ids: next.map(Number) } : null);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {RANK_LABELS.map((rankLabel, i) => (
        <Select key={i} value={picks[i]} onValueChange={(v) => setPick(i, v ?? "")}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder={`${rankLabel} speaker`} />
          </SelectTrigger>
          <SelectContent>
            {speakers
              .filter((s) => !picks.includes(String(s.id)) || picks[i] === String(s.id))
              .map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  {s.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      ))}
    </div>
  );
}

function HeadToHeadForm({ teams, existingPayload, onPayloadChange }: BaseFormProps) {
  const [teamA, setTeamA] = useState<string>(
    existingPayload?.team_a_id ? String(existingPayload.team_a_id) : ""
  );
  const [teamB, setTeamB] = useState<string>(
    existingPayload?.team_b_id ? String(existingPayload.team_b_id) : ""
  );
  const [winner, setWinner] = useState<string>(
    existingPayload?.predicted_winner_id ? String(existingPayload.predicted_winner_id) : ""
  );

  const canPickWinner = teamA && teamB && teamA !== teamB;

  function emit(a: string, b: string, w: string) {
    const complete = a && b && a !== b && w && (w === a || w === b);
    onPayloadChange(
      complete
        ? { team_a_id: Number(a), team_b_id: Number(b), predicted_winner_id: Number(w) }
        : null
    );
  }

  const teamAOption = teams.find((t) => String(t.id) === teamA);
  const teamBOption = teams.find((t) => String(t.id) === teamB);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={teamA}
          onValueChange={(v) => {
            const next = v ?? "";
            setTeamA(next);
            const nextWinner = winner && winner !== next && winner !== teamB ? "" : winner;
            setWinner(nextWinner);
            emit(next, teamB, nextWinner);
          }}
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Equipo A" />
          </SelectTrigger>
          <SelectContent>
            {teams.map((t) => (
              <SelectItem key={t.id} value={String(t.id)}>
                {t.emoji} {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">vs.</span>
        <Select
          value={teamB}
          onValueChange={(v) => {
            const next = v ?? "";
            setTeamB(next);
            emit(teamA, next, winner);
          }}
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Equipo B" />
          </SelectTrigger>
          <SelectContent>
            {teams
              .filter((t) => String(t.id) !== teamA)
              .map((t) => (
                <SelectItem key={t.id} value={String(t.id)}>
                  {t.emoji} {t.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>

      {canPickWinner && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">¿Quién termina arriba?</span>
          <Button
            type="button"
            size="sm"
            variant={winner === teamA ? "default" : "outline"}
            onClick={() => {
              setWinner(teamA);
              emit(teamA, teamB, teamA);
            }}
          >
            {teamAOption?.name}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={winner === teamB ? "default" : "outline"}
            onClick={() => {
              setWinner(teamB);
              emit(teamA, teamB, teamB);
            }}
          >
            {teamBOption?.name}
          </Button>
        </div>
      )}
    </div>
  );
}

function RoundWinnerForm({ tournamentId, teams, existingPayload, onPayloadChange }: BaseFormProps) {
  const [roundId, setRoundId] = useState<string>("");
  const [debateId, setDebateId] = useState<string>(
    existingPayload?.debate_id ? String(existingPayload.debate_id) : ""
  );
  const [teamId, setTeamId] = useState<string>(
    existingPayload?.team_id ? String(existingPayload.team_id) : ""
  );

  const { data: rounds } = useQuery({
    queryKey: queryKeys.rounds(tournamentId),
    queryFn: () => api.rounds.list(tournamentId),
    staleTime: 60_000,
  });

  const { data: debates } = useQuery({
    queryKey: queryKeys.roundDebates(tournamentId, roundId || "none"),
    queryFn: () => api.rounds.debates(tournamentId, roundId),
    enabled: !!roundId,
    staleTime: 30_000,
  });

  const selectedDebate = debates?.find((d) => String(d.id) === debateId);
  const debateTeamOptions = useMemo(
    () =>
      selectedDebate?.teams
        .map((dt) => teams.find((t) => t.id === dt.team.id) ?? dt.team)
        .filter(Boolean) ?? [],
    [selectedDebate, teams]
  );

  function emitTeam(nextDebateId: string, nextTeamId: string) {
    onPayloadChange(
      nextDebateId && nextTeamId
        ? { debate_id: Number(nextDebateId), team_id: Number(nextTeamId) }
        : null
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={roundId}
        onValueChange={(v) => {
          setRoundId(v ?? "");
          setDebateId("");
          setTeamId("");
          onPayloadChange(null);
        }}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Ronda" />
        </SelectTrigger>
        <SelectContent>
          {rounds?.map((r: Round) => (
            <SelectItem key={r.id} value={String(r.id)}>
              {r.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={debateId}
        onValueChange={(v) => {
          const next = v ?? "";
          setDebateId(next);
          setTeamId("");
          onPayloadChange(null);
        }}
      >
        <SelectTrigger className="w-[160px]" disabled={!roundId}>
          <SelectValue placeholder="Debate / sala" />
        </SelectTrigger>
        <SelectContent>
          {debates?.map((d) => (
            <SelectItem key={d.id} value={String(d.id)}>
              {d.room?.name ?? `Debate #${d.id}`}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={teamId}
        onValueChange={(v) => {
          const next = v ?? "";
          setTeamId(next);
          emitTeam(debateId, next);
        }}
      >
        <SelectTrigger className="w-[180px]" disabled={!debateId}>
          <SelectValue placeholder="Equipo ganador" />
        </SelectTrigger>
        <SelectContent>
          {debateTeamOptions.map(
            (t) =>
              t && (
                <SelectItem key={t.id} value={String(t.id)}>
                  {t.emoji} {t.name}
                </SelectItem>
              )
          )}
        </SelectContent>
      </Select>
    </div>
  );
}
