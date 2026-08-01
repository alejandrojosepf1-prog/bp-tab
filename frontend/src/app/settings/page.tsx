"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Check,
  Globe,
  Info,
  LogOut,
  Palette,
  Pencil,
  Settings,
  Target,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatSignedTokens, formatTokens } from "@/lib/format";

function Row({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: typeof Settings;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card/60 px-4 py-3">
      <Icon className="size-4 shrink-0 text-primary" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  );
}

/** El nombre visible es lo que ve todo el mundo en el ranking, en el selector de transferencias
 * y en los premios -- el único campo de la cuenta que el propio usuario necesita controlar (ver
 * MeUpdate en el backend para por qué no se puede editar nada más desde acá). */
function DisplayNameRow({ currentName }: { currentName: string }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(currentName);

  const mutation = useMutation({
    mutationFn: () => api.auth.updateMe({ display_name: draft.trim() }),
    onSuccess: (updated) => {
      toast.success("Nombre actualizado");
      queryClient.setQueryData(queryKeys.me, updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.globalLeaderboard });
      setEditing(false);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "No se pudo cambiar el nombre"),
  });

  const trimmed = draft.trim();
  const canSave = trimmed.length >= 2 && trimmed !== currentName && !mutation.isPending;

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card/60 px-4 py-3">
      <Pencil className="size-4 shrink-0 text-primary" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Nombre visible</p>
        <p className="text-xs text-muted-foreground">
          Así te ven los demás en el ranking, al recibir tokens y en los premios.
        </p>
      </div>
      {editing ? (
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Input
            autoFocus
            value={draft}
            maxLength={100}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && canSave) mutation.mutate();
              if (e.key === "Escape") {
                setDraft(currentName);
                setEditing(false);
              }
            }}
            className="h-9 flex-1 sm:w-52"
            aria-label="Nombre visible"
          />
          <Button
            size="icon"
            className="size-11 shrink-0 sm:size-9"
            disabled={!canSave}
            onClick={() => mutation.mutate()}
            aria-label="Guardar nombre"
          >
            <Check className="size-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="size-11 shrink-0 sm:size-9"
            onClick={() => {
              setDraft(currentName);
              setEditing(false);
            }}
            aria-label="Cancelar"
          >
            <X className="size-4" />
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="max-w-[12rem] truncate text-sm font-medium">{currentName}</span>
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            Cambiar
          </Button>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative";
}) {
  return (
    <div className="rounded-xl bg-muted/50 px-3 py-2">
      <p className="truncate text-[0.7rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "truncate font-mono text-lg font-bold tabular-nums",
          tone === "positive" && "text-primary",
          tone === "negative" && "text-destructive"
        )}
      >
        {value}
      </p>
    </div>
  );
}

/** Tus números, derivados del historial que ya se descarga -- sin endpoint nuevo. Es la parte de
 * "acertadas vs. falladas y win-rate" que hasta ahora no existía en ninguna pantalla. */
function MyStats() {
  const { data: history, isLoading } = useQuery({
    queryKey: ["me", "predictions"],
    queryFn: api.auth.myPredictions,
    staleTime: 15_000,
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[62px] rounded-xl" />
        ))}
      </div>
    );
  }
  if (!history) return null;

  const settled = history.filter((p) => p.status === "settled");
  const won = settled.filter((p) => (p.points_awarded ?? 0) > 0);
  const lost = settled.length - won.length;
  const winRate = settled.length ? Math.round((won.length / settled.length) * 100) : 0;
  const net = settled.reduce((acc, p) => acc + ((p.points_awarded ?? 0) - p.stake_amount), 0);
  const staked = history.reduce((acc, p) => acc + p.stake_amount, 0);

  if (settled.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border px-4 py-3 text-xs text-muted-foreground">
        Todavía no tenés apuestas liquidadas — tus estadísticas aparecen acá en cuanto se
        resuelva la primera.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Acertadas" value={String(won.length)} tone="positive" />
        <Stat label="Falladas" value={String(lost)} tone={lost > 0 ? "negative" : undefined} />
        <Stat label="Win rate" value={`${winRate}%`} />
        <Stat
          label="Neto"
          value={formatSignedTokens(net)}
          tone={net >= 0 ? "positive" : "negative"}
        />
      </div>
      {/* Barra de acierto: el mismo dato que el % de arriba, leíble de un vistazo y sin depender
          solo del color (el porcentaje va escrito al lado, y la barra lleva aria-label). */}
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-destructive/30"
        role="img"
        aria-label={`Win rate ${winRate} por ciento: ${won.length} acertadas de ${settled.length} liquidadas`}
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-500 motion-reduce:transition-none"
          style={{ width: `${winRate}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {settled.length} liquidadas · {formatTokens(staked)} apostados en total
      </p>
    </div>
  );
}

export default function SettingsPage() {
  const { user, logout } = useAuth();

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-8">
      <h1 className="font-heading text-2xl font-bold tracking-tight">Configuración</h1>

      {user && (
        <>
          <section className="flex flex-col gap-2">
            <h2 className="flex items-center gap-2 font-heading text-base font-bold">
              <Target className="size-4 text-primary" /> Tus números
            </h2>
            <MyStats />
          </section>

          <DisplayNameRow currentName={user.display_name} />
        </>
      )}

      <Row
        icon={Palette}
        title="Tema"
        description="Claim usa tema oscuro fijo — es parte de la identidad visual."
      >
        <span className="rounded-md bg-muted px-2.5 py-1 text-xs text-muted-foreground">
          Oscuro
        </span>
      </Row>

      <Row
        icon={Globe}
        title="Idioma"
        description="Interfaz en español (es). Otros idiomas no están disponibles todavía."
      >
        <span className="rounded-md bg-muted px-2.5 py-1 text-xs text-muted-foreground">ES</span>
      </Row>

      {user && (
        <Row
          icon={Settings}
          title="Sesión"
          description={`Conectado como ${user.email}. La sesión se guarda localmente en este navegador.`}
        >
          <Button
            variant="outline"
            size="sm"
            className="min-h-11 sm:min-h-0"
            onClick={logout}
          >
            <LogOut className="size-4" /> Cerrar sesión
          </Button>
        </Row>
      )}

      <Row
        icon={Info}
        title="Acerca de Claim"
        description="Mercados de predicción sobre torneos de debate BP. Cada cuenta arranca con 100 tokens de juego: no se compran, no se retiran y no existe dinero real en ninguna parte del sistema. Los datos del torneo se sincronizan automáticamente desde el tab público (CalicoTab)."
      />
    </div>
  );
}
