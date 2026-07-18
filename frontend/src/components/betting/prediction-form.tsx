"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
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
 * docs/api_contract.md). All of them share the same submit plumbing: build a payload,
 * POST it via api.betMarkets.createPrediction, then invalidate the "my prediction" +
 * dashboard queries so the rest of the UI reflects it immediately.
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

  const mutation = useMutation({
    mutationFn: (payload: object) => api.betMarkets.createPrediction(market.id, payload),
    onSuccess: () => {
      toast.success("Predicción guardada");
      queryClient.invalidateQueries({ queryKey: queryKeys.myPrediction(market.id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard(tournamentId) });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "No se pudo guardar la predicción");
    },
  });

  const commonProps = {
    teams,
    speakers,
    institutions,
    tournamentId,
    existingPayload: existing?.payload,
    isSaving: mutation.isPending,
    onSubmit: (payload: object) => mutation.mutate(payload),
  };

  switch (market.bet_type as BetType) {
    case "champion":
    case "breakout_team":
      return <TeamPickForm {...commonProps} />;
    case "best_institution":
      return <InstitutionPickForm {...commonProps} />;
    case "top_n_break":
      return <OrderedTeamsForm {...commonProps} label="equipos" />;
    case "top_n_speakers":
      return <OrderedSpeakersForm {...commonProps} />;
    case "head_to_head":
      return <HeadToHeadForm {...commonProps} />;
    case "round_winner":
      return <RoundWinnerForm {...commonProps} />;
    default:
      return null;
  }
}

interface BaseFormProps {
  teams: Team[];
  speakers: Speaker[];
  institutions: Institution[];
  tournamentId: string;
  existingPayload: Record<string, unknown> | undefined;
  isSaving: boolean;
  onSubmit: (payload: object) => void;
}

function TeamPickForm({ teams, existingPayload, isSaving, onSubmit }: BaseFormProps) {
  const [teamId, setTeamId] = useState<string>(
    existingPayload?.team_id ? String(existingPayload.team_id) : ""
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={teamId} onValueChange={(v) => setTeamId(v ?? "")}>
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
      <Button
        size="sm"
        disabled={!teamId || isSaving}
        onClick={() => onSubmit({ team_id: Number(teamId) })}
      >
        {isSaving && <Loader2 className="size-3.5 animate-spin" />}
        Guardar
      </Button>
    </div>
  );
}

function InstitutionPickForm({ institutions, existingPayload, isSaving, onSubmit }: BaseFormProps) {
  const [code, setCode] = useState<string>(
    typeof existingPayload?.institution_code === "string" ? existingPayload.institution_code : ""
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={code} onValueChange={(v) => setCode(v ?? "")}>
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
      <Button size="sm" disabled={!code || isSaving} onClick={() => onSubmit({ institution_code: code })}>
        {isSaving && <Loader2 className="size-3.5 animate-spin" />}
        Guardar
      </Button>
    </div>
  );
}

const RANK_LABELS = ["1º", "2º", "3º"];

function OrderedTeamsForm({ teams, existingPayload, isSaving, onSubmit, label }: BaseFormProps & { label: string }) {
  const existingIds = Array.isArray(existingPayload?.team_ids)
    ? (existingPayload.team_ids as number[]).map(String)
    : [];
  const [picks, setPicks] = useState<string[]>([
    existingIds[0] ?? "",
    existingIds[1] ?? "",
    existingIds[2] ?? "",
  ]);

  function setPick(index: number, value: string) {
    setPicks((prev) => prev.map((p, i) => (i === index ? value : p)));
  }

  const complete = picks.every(Boolean);

  return (
    <div className="flex flex-col gap-2">
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
      <div>
        <Button
          size="sm"
          disabled={!complete || isSaving}
          onClick={() => onSubmit({ team_ids: picks.map(Number) })}
        >
          {isSaving && <Loader2 className="size-3.5 animate-spin" />}
          Guardar top 3
        </Button>
      </div>
    </div>
  );
}

function OrderedSpeakersForm({ speakers, existingPayload, isSaving, onSubmit }: BaseFormProps) {
  const existingIds = Array.isArray(existingPayload?.speaker_ids)
    ? (existingPayload.speaker_ids as number[]).map(String)
    : [];
  const [picks, setPicks] = useState<string[]>([
    existingIds[0] ?? "",
    existingIds[1] ?? "",
    existingIds[2] ?? "",
  ]);

  function setPick(index: number, value: string) {
    setPicks((prev) => prev.map((p, i) => (i === index ? value : p)));
  }

  const complete = picks.every(Boolean);

  return (
    <div className="flex flex-col gap-2">
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
      <div>
        <Button
          size="sm"
          disabled={!complete || isSaving}
          onClick={() => onSubmit({ speaker_ids: picks.map(Number) })}
        >
          {isSaving && <Loader2 className="size-3.5 animate-spin" />}
          Guardar top 3
        </Button>
      </div>
    </div>
  );
}

function HeadToHeadForm({ teams, existingPayload, isSaving, onSubmit }: BaseFormProps) {
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
  const complete = canPickWinner && winner && (winner === teamA || winner === teamB);

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
            if (winner && winner !== next && winner !== teamB) setWinner("");
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
        <Select value={teamB} onValueChange={(v) => setTeamB(v ?? "")}>
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
            onClick={() => setWinner(teamA)}
          >
            {teamAOption?.name}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={winner === teamB ? "default" : "outline"}
            onClick={() => setWinner(teamB)}
          >
            {teamBOption?.name}
          </Button>
        </div>
      )}

      <div>
        <Button
          size="sm"
          disabled={!complete || isSaving}
          onClick={() =>
            onSubmit({
              team_a_id: Number(teamA),
              team_b_id: Number(teamB),
              predicted_winner_id: Number(winner),
            })
          }
        >
          {isSaving && <Loader2 className="size-3.5 animate-spin" />}
          Guardar
        </Button>
      </div>
    </div>
  );
}

function RoundWinnerForm({ tournamentId, teams, existingPayload, isSaving, onSubmit }: BaseFormProps) {
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

  const complete = roundId && debateId && teamId;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={roundId}
          onValueChange={(v) => {
            setRoundId(v ?? "");
            setDebateId("");
            setTeamId("");
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
            setDebateId(v ?? "");
            setTeamId("");
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

        <Select value={teamId} onValueChange={(v) => setTeamId(v ?? "")}>
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
      <div>
        <Button
          size="sm"
          disabled={!complete || isSaving}
          onClick={() => onSubmit({ debate_id: Number(debateId), team_id: Number(teamId) })}
        >
          {isSaving && <Loader2 className="size-3.5 animate-spin" />}
          Guardar
        </Button>
      </div>
    </div>
  );
}
