"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { format } from "date-fns";
import { Loader2, PlusCircle, RefreshCw, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { RequireAdmin } from "@/components/auth/require-admin";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHeader, TableRow, TableHead } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/status-badge";
import { PageTransition } from "@/components/motion";
import { LoadingState, EmptyState } from "@/components/query-state";
import { AlertTriangle } from "lucide-react";
import type { BetType, PendingEliminationDebate, ScrapeStatus, Tournament } from "@/lib/api/types";

export default function AdminPage() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 px-4 py-6">
      <RequireAdmin>
        <PageTransition>
          <AdminContent />
        </PageTransition>
      </RequireAdmin>
    </div>
  );
}

function AdminContent() {
  const { data: pending } = useQuery({
    queryKey: queryKeys.adminPendingEliminationResults(),
    queryFn: () => api.admin.pendingEliminationResults(),
    refetchInterval: 60_000,
  });
  const pendingCount = pending?.length ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <ShieldCheck className="size-5" /> Panel de administración
      </h2>

      <Tabs defaultValue="tournaments">
        <TabsList>
          <TabsTrigger value="tournaments">Torneos</TabsTrigger>
          <TabsTrigger value="logs">Scrape logs</TabsTrigger>
          <TabsTrigger value="bets">Apuestas</TabsTrigger>
          <TabsTrigger value="results" className="gap-1.5">
            Resultados manuales
            {pendingCount > 0 && (
              <Badge variant="destructive" className="h-4.5 px-1.5">
                {pendingCount}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="users">Usuarios</TabsTrigger>
        </TabsList>

        <TabsContent value="tournaments" className="mt-4">
          <TournamentsTab />
        </TabsContent>
        <TabsContent value="logs" className="mt-4">
          <ScrapeLogsTab />
        </TabsContent>
        <TabsContent value="bets" className="mt-4">
          <BetMarketsTab />
        </TabsContent>
        <TabsContent value="results" className="mt-4">
          <ManualResultsTab pending={pending ?? []} />
        </TabsContent>
        <TabsContent value="users" className="mt-4">
          <UsersTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Torneos: crear + editar URL/slug + forzar scraping
// ---------------------------------------------------------------------------

function TournamentsTab() {
  const queryClient = useQueryClient();
  const { data: tournaments, isLoading } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
  });

  const [form, setForm] = useState({ name: "", tab_url: "", timezone: "UTC" });

  const createMutation = useMutation({
    mutationFn: () => api.tournaments.create(form),
    onSuccess: () => {
      toast.success("Torneo creado — arrancó el primer scraping automáticamente");
      setForm({ name: "", tab_url: "", timezone: "UTC" });
      queryClient.invalidateQueries({ queryKey: queryKeys.tournaments });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al crear el torneo"),
  });

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <PlusCircle className="size-4" /> Agregar torneo
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
            className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="name">Nombre</Label>
              <Input
                id="name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="CMUDE 2025"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="timezone">Zona horaria</Label>
              <Input
                id="timezone"
                value={form.timezone}
                onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
                placeholder="America/Lima"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <Label htmlFor="tab_url">URL del tab de CalicoTab</Label>
              <Input
                id="tab_url"
                value={form.tab_url}
                onChange={(e) => setForm((f) => ({ ...f, tab_url: e.target.value }))}
                placeholder="https://cmude2025.calicotab.com/open/participants/list/"
                required
              />
              <p className="text-xs text-muted-foreground">
                Pegá cualquier link del tab del torneo (participantes, resultados, lo que sea) —
                se detecta automáticamente el sitio y el torneo.
              </p>
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                Crear torneo
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Torneos existentes</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {isLoading && <LoadingState label="Cargando torneos…" />}
          {tournaments?.map((t) => <TournamentRow key={t.id} tournament={t} />)}
          {tournaments?.length === 0 && <EmptyState title="Sin torneos todavía" />}
        </CardContent>
      </Card>
    </div>
  );
}

function TournamentRow({ tournament }: { tournament: Tournament }) {
  const queryClient = useQueryClient();
  const [tabUrl, setTabUrl] = useState(
    `${tournament.source_base_url}/${tournament.source_slug}/`
  );

  const updateMutation = useMutation({
    mutationFn: () => api.tournaments.update(tournament.id, { tab_url: tabUrl }),
    onSuccess: () => {
      toast.success("Torneo actualizado");
      queryClient.invalidateQueries({ queryKey: queryKeys.tournaments });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const toggleActiveMutation = useMutation({
    mutationFn: () => api.tournaments.update(tournament.id, { is_active: !tournament.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.tournaments }),
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const scrapeMutation = useMutation({
    mutationFn: () => api.tournaments.scrape(tournament.id),
    onSuccess: () => toast.success("Scraping en cola — puede tardar unos segundos"),
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "No se pudo forzar el scraping"),
  });

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-medium">{tournament.name}</span>
          <StatusBadge status={tournament.status} />
          {!tournament.is_active && <span className="text-xs text-muted-foreground">(inactivo)</span>}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={scrapeMutation.isPending}
            onClick={() => scrapeMutation.mutate()}
          >
            {scrapeMutation.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
            Forzar scraping
          </Button>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Checkbox
              checked={tournament.is_active}
              onCheckedChange={() => toggleActiveMutation.mutate()}
            />
            Activo
          </label>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto]">
        <Input value={tabUrl} onChange={(e) => setTabUrl(e.target.value)} className="text-xs" />
        <Button
          size="sm"
          variant="secondary"
          disabled={updateMutation.isPending}
          onClick={() => updateMutation.mutate()}
        >
          {updateMutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
          Guardar URL
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scrape logs
// ---------------------------------------------------------------------------

const SCRAPE_STATUS_MAP: Record<ScrapeStatus, string> = {
  success: "success",
  partial: "partial",
  failed: "failed",
  running: "running",
};

function ScrapeLogsTab() {
  const { data: tournaments } = useQuery({ queryKey: queryKeys.tournaments, queryFn: api.tournaments.list });
  const [tournamentId, setTournamentId] = useState<string>("");

  const { data: logs, isLoading } = useQuery({
    queryKey: queryKeys.adminScrapeLogs(tournamentId || undefined),
    queryFn: () => api.admin.scrapeLogs(tournamentId || undefined),
  });

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Logs de scraping</CardTitle>
        <Select
          value={tournamentId}
          onValueChange={(v) => setTournamentId(v ?? "")}
          items={(tournaments ?? []).map((t) => ({ value: String(t.id), label: t.name }))}
        >
          <SelectTrigger className="w-[220px]">
            <SelectValue placeholder="Todos los torneos" />
          </SelectTrigger>
          <SelectContent>
            {tournaments?.map((t) => (
              <SelectItem key={t.id} value={String(t.id)}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && <LoadingState label="Cargando logs…" />}
        {logs && logs.length === 0 && <EmptyState title="Sin corridas de scraping todavía" />}
        {logs && logs.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Inicio</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Estrategia</TableHead>
                <TableHead className="text-right">Creados</TableHead>
                <TableHead className="text-right">Actualizados</TableHead>
                <TableHead>Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell className="text-xs">
                    {format(new Date(log.started_at), "dd/MM HH:mm:ss")}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={SCRAPE_STATUS_MAP[log.status]} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{log.strategy_used ?? "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{log.entities_created ?? 0}</TableCell>
                  <TableCell className="text-right tabular-nums">{log.entities_updated ?? 0}</TableCell>
                  <TableCell className="max-w-[200px] truncate text-xs text-destructive">
                    {log.error_message ?? ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Resultados manuales: eliminatorias/final sin ballot publicado en Tabbycat
// ---------------------------------------------------------------------------

function ManualResultsTab({ pending }: { pending: PendingEliminationDebate[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="size-4 text-destructive" /> Resultados pendientes de confirmar
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">
          Rondas eliminatorias (incluida la Gran Final) cuyo cruce ya se conoce pero cuyo
          resultado todavía no aparece en Tabbycat. Muchos torneos nunca suben ese ballot porque
          no afecta el tab — acá lo confirmás vos como admin. Si Tabbycat después sí publica el
          resultado oficial, el próximo scraping lo sobreescribe automáticamente.
        </p>
        {pending.length === 0 && <EmptyState title="No hay resultados pendientes" />}
        {pending.map((debate) => (
          <PendingResultRow key={debate.debate_id} debate={debate} />
        ))}
      </CardContent>
    </Card>
  );
}

function PendingResultRow({ debate }: { debate: PendingEliminationDebate }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);

  const submitMutation = useMutation({
    mutationFn: () =>
      debate.is_final
        ? api.admin.submitManualResult(debate.debate_id, { champion_team_id: selected[0] })
        : api.admin.submitManualResult(debate.debate_id, { advancing_team_ids: selected }),
    onSuccess: () => {
      toast.success("Resultado confirmado");
      setOpen(false);
      setSelected([]);
      queryClient.invalidateQueries({ queryKey: queryKeys.adminPendingEliminationResults() });
      queryClient.invalidateQueries({ queryKey: queryKeys.tournament(debate.tournament_id) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al confirmar el resultado"),
  });

  const toggleTeam = (teamId: number) => {
    if (debate.is_final) {
      setSelected([teamId]);
      return;
    }
    setSelected((prev) =>
      prev.includes(teamId) ? prev.filter((id) => id !== teamId) : [...prev, teamId]
    );
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium">
          {debate.round_name} {debate.is_final && "🏆"}
        </span>
        <span className="text-xs text-muted-foreground">
          {debate.teams.map((t) => t.team_name).join(" vs. ")}
        </span>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger render={<Button size="sm" variant="outline" />}>
          {debate.is_final ? "Confirmar campeón" : "Confirmar avance"}
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{debate.round_name}</DialogTitle>
            <DialogDescription>
              {debate.is_final
                ? "Seleccioná el equipo campeón del torneo."
                : "Seleccioná los equipos que avanzaron a la siguiente ronda."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            {debate.teams.map((t) => (
              <label
                key={t.team_id}
                className="flex items-center gap-2 rounded-md border border-border p-2 text-sm"
              >
                <Checkbox
                  checked={selected.includes(t.team_id)}
                  onCheckedChange={() => toggleTeam(t.team_id)}
                />
                {t.team_name}
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button
              disabled={selected.length === 0 || submitMutation.isPending}
              onClick={() => submitMutation.mutate()}
            >
              {submitMutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
              Confirmar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Apuestas: abrir/cerrar mercados + crear nuevos
// ---------------------------------------------------------------------------

const BET_TYPES: { value: BetType; label: string }[] = [
  { value: "champion", label: "Campeón" },
  { value: "top_n_break", label: "Top 3 equipos que rompen" },
  { value: "top_n_speakers", label: "Top 3 speakers" },
  { value: "round_winner", label: "Ganador de un debate" },
  { value: "head_to_head", label: "Cara a cara" },
  { value: "breakout_team", label: "Equipo revelación" },
  { value: "best_institution", label: "Mejor institución" },
];

function BetMarketsTab() {
  const queryClient = useQueryClient();
  const { data: tournaments } = useQuery({ queryKey: queryKeys.tournaments, queryFn: api.tournaments.list });
  const [tournamentId, setTournamentId] = useState<string>("");

  const { data: markets, isLoading } = useQuery({
    queryKey: queryKeys.betMarkets(tournamentId || "none"),
    queryFn: () => api.betMarkets.list(tournamentId),
    enabled: !!tournamentId,
  });

  const [form, setForm] = useState({
    bet_type: "champion" as BetType,
    label: "",
    description: "",
    opens_at: "",
    closes_at: "",
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.betMarkets.create(tournamentId, {
        bet_type: form.bet_type,
        label: form.label,
        description: form.description || undefined,
        opens_at: new Date(form.opens_at).toISOString(),
        closes_at: new Date(form.closes_at).toISOString(),
      }),
    onSuccess: () => {
      toast.success("Mercado creado");
      setForm({ bet_type: "champion", label: "", description: "", opens_at: "", closes_at: "" });
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al crear el mercado"),
  });

  return (
    <div className="flex flex-col gap-4">
      <Select
        value={tournamentId}
        onValueChange={(v) => setTournamentId(v ?? "")}
        items={(tournaments ?? []).map((t) => ({ value: String(t.id), label: t.name }))}
      >
        <SelectTrigger className="w-[240px]">
          <SelectValue placeholder="Seleccionar torneo" />
        </SelectTrigger>
        <SelectContent>
          {tournaments?.map((t) => (
            <SelectItem key={t.id} value={String(t.id)}>
              {t.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {tournamentId && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Crear mercado</CardTitle>
            </CardHeader>
            <CardContent>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  createMutation.mutate();
                }}
                className="grid grid-cols-1 gap-3 sm:grid-cols-2"
              >
                <div className="flex flex-col gap-1.5">
                  <Label>Tipo de apuesta</Label>
                  <Select
                    value={form.bet_type}
                    onValueChange={(v) => setForm((f) => ({ ...f, bet_type: v as BetType }))}
                    items={BET_TYPES}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {BET_TYPES.map((bt) => (
                        <SelectItem key={bt.value} value={bt.value}>
                          {bt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="label">Etiqueta</Label>
                  <Input
                    id="label"
                    value={form.label}
                    onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))}
                    placeholder="¿Quién gana el torneo?"
                    required
                  />
                </div>
                <div className="flex flex-col gap-1.5 sm:col-span-2">
                  <Label htmlFor="description">Descripción (opcional)</Label>
                  <Textarea
                    id="description"
                    value={form.description}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                    rows={2}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="opens_at">Abre</Label>
                  <Input
                    id="opens_at"
                    type="datetime-local"
                    value={form.opens_at}
                    onChange={(e) => setForm((f) => ({ ...f, opens_at: e.target.value }))}
                    required
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="closes_at">Cierra</Label>
                  <Input
                    id="closes_at"
                    type="datetime-local"
                    value={form.closes_at}
                    onChange={(e) => setForm((f) => ({ ...f, closes_at: e.target.value }))}
                    required
                  />
                </div>
                <div className="sm:col-span-2">
                  <Button type="submit" disabled={createMutation.isPending}>
                    {createMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                    Crear mercado
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Mercados de este torneo</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {isLoading && <LoadingState label="Cargando mercados…" />}
              {markets?.length === 0 && <EmptyState title="Sin mercados todavía" />}
              {markets?.map((m) => (
                <BetMarketAdminRow key={m.id} tournamentId={tournamentId} marketId={m.id} label={m.label} status={m.status} />
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function BetMarketAdminRow({
  tournamentId,
  marketId,
  label,
  status,
}: {
  tournamentId: string;
  marketId: number;
  label: string;
  status: string;
}) {
  const queryClient = useQueryClient();

  const patchMutation = useMutation({
    mutationFn: (next: "open" | "closed") => api.betMarkets.update(marketId, { status: next }),
    onSuccess: () => {
      toast.success("Mercado actualizado");
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const settleMutation = useMutation({
    mutationFn: () => api.betMarkets.settle(marketId),
    onSuccess: (res) => {
      toast(res.settled ? "Mercado liquidado" : "Todavía no se puede liquidar (falta resultado)");
      queryClient.invalidateQueries({ queryKey: queryKeys.betMarkets(tournamentId) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al liquidar"),
  });

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{label}</span>
        <StatusBadge status={status} />
      </div>
      <div className="flex items-center gap-2">
        {status === "open" && (
          <Button size="sm" variant="outline" onClick={() => patchMutation.mutate("closed")}>
            Cerrar
          </Button>
        )}
        {status === "closed" && (
          <>
            <Button size="sm" variant="outline" onClick={() => patchMutation.mutate("open")}>
              Reabrir
            </Button>
            <Button size="sm" disabled={settleMutation.isPending} onClick={() => settleMutation.mutate()}>
              {settleMutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
              Liquidar
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Usuarios
// ---------------------------------------------------------------------------

function UsersTab() {
  const queryClient = useQueryClient();
  const { data: users, isLoading } = useQuery({ queryKey: queryKeys.adminUsers, queryFn: api.admin.users });

  const toggleRole = useMutation({
    mutationFn: (vars: { id: number; role: "admin" | "user" }) =>
      api.admin.updateUser(vars.id, { role: vars.role }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const toggleActive = useMutation({
    mutationFn: (vars: { id: number; is_active: boolean }) =>
      api.admin.updateUser(vars.id, { is_active: vars.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Usuarios</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && <LoadingState label="Cargando usuarios…" />}
        {users && users.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nombre</TableHead>
                <TableHead>Correo</TableHead>
                <TableHead>Rol</TableHead>
                <TableHead>Activo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.display_name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{u.email}</TableCell>
                  <TableCell>
                    <Select
                      value={u.role}
                      onValueChange={(v) => toggleRole.mutate({ id: u.id, role: v as "admin" | "user" })}
                      items={[
                        { value: "user", label: "Usuario" },
                        { value: "admin", label: "Admin" },
                      ]}
                    >
                      <SelectTrigger size="sm" className="w-[110px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="user">Usuario</SelectItem>
                        <SelectItem value="admin">Admin</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Checkbox
                      checked={u.is_active}
                      onCheckedChange={(checked) =>
                        toggleActive.mutate({ id: u.id, is_active: !!checked })
                      }
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
