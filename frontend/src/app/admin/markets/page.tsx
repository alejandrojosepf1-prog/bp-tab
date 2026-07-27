"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { toast } from "sonner";
import {
  AlertCircle,
  Award,
  CheckCircle2,
  Coins,
  Eye,
  Loader2,
  Mic2,
  PlusCircle,
  Swords,
  Trophy,
  Users,
} from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { TournamentChips } from "@/components/admin/tournament-chips";
import { LoadingState, EmptyState } from "@/components/query-state";
import { BET_TYPE_LABELS } from "@/components/betting/market-card";
import { cn } from "@/lib/utils";
import type { BetType } from "@/lib/api/types";

interface BetTypeOption {
  value: BetType;
  label: string;
  hint: string;
  icon: typeof Trophy;
  needsRound?: boolean;
  needsBreakCategory?: boolean;
  requiresUpcoming?: boolean;
}

const BET_TYPES: BetTypeOption[] = [
  {
    value: "champion",
    label: "Campeón del torneo",
    hint: "Quién sale campeón — solo se puede abrir antes de que arranque el torneo",
    icon: Trophy,
    requiresUpcoming: true,
  },
  {
    value: "round_winner",
    label: "Ganador de debate (por ronda)",
    hint: "Quién gana una sala concreta",
    icon: Swords,
    needsRound: true,
  },
  {
    value: "round_full_call",
    label: "Call completo (por ronda)",
    hint: "Orden exacto 1º-2º-3º-4º de una sala",
    icon: Swords,
    needsRound: true,
  },
  {
    value: "top_speaker_position",
    label: "Tabla de oradores",
    hint: "Un orador, en qué puesto del top 3 termina",
    icon: Mic2,
  },
  {
    value: "team_break",
    label: "Equipos que hacen break",
    hint: "Apuesta independiente por equipo (varios pueden romper a la vez)",
    icon: Award,
    needsBreakCategory: true,
  },
];

interface MarketForm {
  bet_type: BetType;
  label: string;
  description: string;
  opens_at: string;
  closes_at: string;
  target_round_id: string;
  target_break_category_id: string;
}

const EMPTY_FORM: MarketForm = {
  bet_type: "champion",
  label: "",
  description: "",
  opens_at: "",
  closes_at: "",
  target_round_id: "",
  target_break_category_id: "",
};

function validate(form: MarketForm, tournamentStatus: string | undefined): Record<string, string> {
  const errors: Record<string, string> = {};
  const selected = BET_TYPES.find((bt) => bt.value === form.bet_type);
  if (form.label.trim().length < 5) {
    errors.label = "La etiqueta necesita al menos 5 caracteres.";
  }
  if (!form.opens_at) errors.opens_at = "Definí cuándo abre.";
  if (!form.closes_at) errors.closes_at = "Definí cuándo cierra.";
  if (form.opens_at && form.closes_at && new Date(form.closes_at) <= new Date(form.opens_at)) {
    errors.closes_at = "Debe cerrar después de abrir.";
  }
  if (form.closes_at && new Date(form.closes_at) <= new Date()) {
    errors.closes_at = "El cierre tiene que estar en el futuro.";
  }
  if (selected?.requiresUpcoming && tournamentStatus !== "upcoming") {
    errors.bet_type = "El torneo ya arrancó — este mercado solo se puede abrir antes.";
  }
  if (selected?.needsRound && !form.target_round_id) {
    errors.target_round_id = "Elegí una ronda.";
  }
  if (selected?.needsBreakCategory && !form.target_break_category_id) {
    errors.target_break_category_id = "Elegí una categoría de break.";
  }
  return errors;
}

function Field({
  label,
  error,
  children,
  className,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label>{label}</Label>
      {children}
      {error && (
        <p className="flex items-center gap-1 text-xs text-destructive">
          <AlertCircle className="size-3" /> {error}
        </p>
      )}
    </div>
  );
}

function MarketPreview({
  form,
  roundName,
  categoryName,
}: {
  form: MarketForm;
  roundName?: string;
  categoryName?: string;
}) {
  const closes = form.closes_at ? new Date(form.closes_at) : null;
  const scope = roundName ? `Ronda: ${roundName}` : categoryName ? `Categoría: ${categoryName}` : null;
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-dashed border-primary/40 bg-primary/4 p-4">
      <p className="flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-widest text-primary/80">
        <Eye className="size-3.5" /> Así lo van a ver los apostadores
      </p>
      <div className="rounded-xl border border-border bg-card/80 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-heading text-sm font-semibold">
              {form.label.trim() || "Etiqueta del mercado…"}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {BET_TYPE_LABELS[form.bet_type]}
              {scope ? ` · ${scope}` : ""}
              {form.description.trim() ? ` · ${form.description.trim()}` : ""}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {closes && !Number.isNaN(closes.getTime()) && (
              <span className="text-xs text-muted-foreground">
                cierra {formatDistanceToNow(closes, { addSuffix: true, locale: es })}
              </span>
            )}
            <Badge variant="outline" className="border-primary/40 bg-primary/10 text-primary">
              Abierto
            </Badge>
          </div>
        </div>
        <div className="mt-2 flex gap-2 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-primary">
            <Coins className="size-3" /> Pool $0
          </span>
          <span className="flex items-center gap-1 rounded-md bg-muted px-2 py-1">
            <Users className="size-3" /> 0 apostadores
          </span>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Las cuotas arrancan desde el modelo de fuerza (pari-mutuel sembrado) y se mueven con el
        pool real. Cuota justa, sin comisión: la casa no se lleva nada. Rango 1.01x – 50x.{" "}
        {form.bet_type === "team_break" &&
          "Excepción: equipos que rompen se cotiza directo desde su probabilidad de break, sin pool compartido — romper no es excluyente entre equipos."}
      </p>
    </div>
  );
}

function ManageMarkets({ tournamentId }: { tournamentId: string }) {
  const queryClient = useQueryClient();
  const { data: markets, isLoading } = useQuery({
    queryKey: queryKeys.betMarkets(tournamentId),
    queryFn: () => api.betMarkets.list(tournamentId),
  });

  const patchMutation = useMutation({
    mutationFn: (vars: { id: number; status: "open" | "closed" }) =>
      api.betMarkets.update(vars.id, { status: vars.status }),
    onSuccess: () => {
      toast.success("Mercado actualizado");
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId) });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const settleMutation = useMutation({
    mutationFn: (id: number) => api.betMarkets.settle(id),
    onSuccess: (res) => {
      toast(
        res.settled
          ? "Mercado liquidado y pagos acreditados"
          : "Todavía no hay resultado para liquidar — se reintenta con cada scrape"
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al liquidar"),
  });

  if (isLoading) return <LoadingState label="Cargando mercados…" />;
  if (!markets?.length) return <EmptyState title="Este torneo no tiene mercados todavía" />;

  return (
    <div className="flex flex-col gap-2">
      {markets.map((m) => (
        <div
          key={m.id}
          className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card/60 px-4 py-3"
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{m.label}</p>
            <p className="text-xs text-muted-foreground">
              {BET_TYPE_LABELS[m.bet_type] ?? m.bet_type} · pool $
              {m.pool_total.toLocaleString("es")} · {m.bettors_count}{" "}
              {m.bettors_count === 1 ? "apostador" : "apostadores"}
            </p>
          </div>
          <Badge
            variant="outline"
            className={cn(
              m.status === "open"
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border bg-muted text-muted-foreground"
            )}
          >
            {m.status === "open" ? "Abierto" : m.status === "closed" ? "Cerrado" : "Liquidado"}
          </Badge>
          {m.status === "open" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => patchMutation.mutate({ id: m.id, status: "closed" })}
            >
              Cerrar
            </Button>
          )}
          {m.status === "closed" && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => patchMutation.mutate({ id: m.id, status: "open" })}
              >
                Reabrir
              </Button>
              <Button
                size="sm"
                disabled={settleMutation.isPending}
                onClick={() => settleMutation.mutate(m.id)}
              >
                {settleMutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
                Liquidar
              </Button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

export default function AdminMarketsPage() {
  const queryClient = useQueryClient();
  const [tournamentId, setTournamentId] = useState<string | null>(null);
  const [form, setForm] = useState<MarketForm>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const { data: tournament } = useQuery({
    queryKey: queryKeys.tournament(tournamentId ?? "none"),
    queryFn: () => api.tournaments.get(tournamentId!),
    enabled: !!tournamentId,
  });
  const { data: rounds } = useQuery({
    queryKey: queryKeys.rounds(tournamentId ?? "none"),
    queryFn: () => api.rounds.list(tournamentId!),
    enabled: !!tournamentId,
  });
  const { data: breakCategories } = useQuery({
    queryKey: queryKeys.breakCategories(tournamentId ?? "none"),
    queryFn: () => api.breakCategories.list(tournamentId!),
    enabled: !!tournamentId,
  });

  const selectedType = BET_TYPES.find((bt) => bt.value === form.bet_type);
  const errors = useMemo(
    () => validate(form, tournament?.status),
    [form, tournament?.status]
  );
  const isValid = Object.keys(errors).length === 0;

  const createMutation = useMutation({
    mutationFn: () =>
      api.betMarkets.create(tournamentId!, {
        bet_type: form.bet_type,
        label: form.label.trim(),
        description: form.description.trim() || undefined,
        opens_at: new Date(form.opens_at).toISOString(),
        closes_at: new Date(form.closes_at).toISOString(),
        target_round_id: form.target_round_id ? Number(form.target_round_id) : undefined,
        target_break_category_id: form.target_break_category_id
          ? Number(form.target_break_category_id)
          : undefined,
      }),
    onSuccess: () => {
      toast.success("Mercado publicado");
      setForm(EMPTY_FORM);
      setTouched(false);
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId!) });
      queryClient.invalidateQueries({ queryKey: queryKeys.tournaments });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Error al crear el mercado"),
  });

  const set = (patch: Partial<MarketForm>) => {
    setTouched(true);
    setForm((f) => ({ ...f, ...patch }));
  };

  const roundName = rounds?.find((r) => String(r.id) === form.target_round_id)?.name;
  const categoryName = breakCategories?.find(
    (c) => String(c.id) === form.target_break_category_id
  )?.name;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Label>Torneo</Label>
        <TournamentChips value={tournamentId} onChange={setTournamentId} />
      </div>

      {tournamentId && (
        <>
          <form
            className="flex flex-col gap-4 rounded-2xl border border-border bg-card/60 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              setTouched(true);
              if (isValid) createMutation.mutate();
            }}
          >
            <h2 className="flex items-center gap-2 font-heading text-base font-bold">
              <PlusCircle className="size-4 text-primary" /> Nuevo mercado
            </h2>

            <Field label="Tipo de apuesta" error={touched ? errors.bet_type : undefined}>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {BET_TYPES.map((bt) => {
                  const disabled = bt.requiresUpcoming && tournament?.status !== "upcoming";
                  const Icon = bt.icon;
                  return (
                    <button
                      key={bt.value}
                      type="button"
                      disabled={disabled}
                      onClick={() =>
                        set({
                          bet_type: bt.value,
                          target_round_id: "",
                          target_break_category_id: "",
                        })
                      }
                      className={cn(
                        "flex flex-col rounded-lg border px-3 py-2 text-left transition-colors",
                        disabled && "cursor-not-allowed opacity-50",
                        !disabled && form.bet_type === bt.value
                          ? "border-primary/50 bg-primary/10"
                          : "border-border bg-background/40",
                        !disabled && form.bet_type !== bt.value && "hover:bg-accent"
                      )}
                    >
                      <span
                        className={cn(
                          "flex items-center gap-1.5 text-sm font-medium",
                          !disabled && form.bet_type === bt.value && "text-primary"
                        )}
                      >
                        <Icon className="size-3.5" /> {bt.label}
                      </span>
                      <span className="text-xs text-muted-foreground">{bt.hint}</span>
                    </button>
                  );
                })}
              </div>
            </Field>

            {selectedType?.needsRound && (
              <Field label="Ronda" error={touched ? errors.target_round_id : undefined}>
                <div className="flex flex-wrap gap-1.5">
                  {(rounds ?? []).map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => set({ target_round_id: String(r.id) })}
                      className={cn(
                        "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                        form.target_round_id === String(r.id)
                          ? "border-primary/50 bg-primary/10 text-primary"
                          : "border-border bg-card hover:bg-accent"
                      )}
                    >
                      {r.name}
                    </button>
                  ))}
                  {!rounds?.length && (
                    <p className="text-xs text-muted-foreground">
                      Este torneo todavía no tiene rondas.
                    </p>
                  )}
                </div>
              </Field>
            )}

            {selectedType?.needsBreakCategory && (
              <Field
                label="Categoría de break"
                error={touched ? errors.target_break_category_id : undefined}
              >
                <div className="flex flex-wrap gap-1.5">
                  {(breakCategories ?? []).map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => set({ target_break_category_id: String(c.id) })}
                      className={cn(
                        "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                        form.target_break_category_id === String(c.id)
                          ? "border-primary/50 bg-primary/10 text-primary"
                          : "border-border bg-card hover:bg-accent"
                      )}
                    >
                      {c.name}
                    </button>
                  ))}
                  {!breakCategories?.length && (
                    <p className="text-xs text-muted-foreground">
                      Este torneo todavía no tiene categorías de break.
                    </p>
                  )}
                </div>
              </Field>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Etiqueta" error={touched ? errors.label : undefined}>
                <Input
                  value={form.label}
                  onChange={(e) => set({ label: e.target.value })}
                  placeholder="¿Quién se lleva el PreCMUDE?"
                />
              </Field>
              <Field label="Descripción (opcional)">
                <Textarea
                  rows={1}
                  value={form.description}
                  onChange={(e) => set({ description: e.target.value })}
                  placeholder="Reglas o contexto extra"
                />
              </Field>
              <Field label="Abre" error={touched ? errors.opens_at : undefined}>
                <Input
                  type="datetime-local"
                  value={form.opens_at}
                  onChange={(e) => set({ opens_at: e.target.value })}
                />
              </Field>
              <Field label="Cierra" error={touched ? errors.closes_at : undefined}>
                <Input
                  type="datetime-local"
                  value={form.closes_at}
                  onChange={(e) => set({ closes_at: e.target.value })}
                />
              </Field>
            </div>

            <MarketPreview form={form} roundName={roundName} categoryName={categoryName} />

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={createMutation.isPending || (touched && !isValid)}>
                {createMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                Publicar mercado
              </Button>
              {touched && isValid && (
                <span className="flex items-center gap-1 text-xs text-primary">
                  <CheckCircle2 className="size-3.5" /> Listo para publicar
                </span>
              )}
            </div>
          </form>

          <section className="flex flex-col gap-3">
            <h2 className="font-heading text-base font-bold">Mercados existentes</h2>
            <ManageMarkets tournamentId={tournamentId} />
          </section>
        </>
      )}
    </div>
  );
}
