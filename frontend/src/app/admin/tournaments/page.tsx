"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, PlusCircle, RefreshCw, Power, Ticket } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/lib/api/types";

function TournamentRow({ tournament }: { tournament: Tournament }) {
  const queryClient = useQueryClient();
  const [tabUrl, setTabUrl] = useState(
    `${tournament.source_base_url}/${tournament.source_slug}/`
  );

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.tournaments });

  const updateMutation = useMutation({
    mutationFn: () => api.tournaments.update(tournament.id, { tab_url: tabUrl }),
    onSuccess: () => {
      toast.success("Torneo actualizado");
      invalidate();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const toggleActiveMutation = useMutation({
    mutationFn: () =>
      api.tournaments.update(tournament.id, { is_active: !tournament.is_active }),
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const toggleAccessPassMutation = useMutation({
    mutationFn: () =>
      api.tournaments.update(tournament.id, {
        requires_access_pass: !tournament.requires_access_pass,
      }),
    onSuccess: () => {
      toast.success(
        tournament.requires_access_pass
          ? "Ya no requiere pase de acceso"
          : "Ahora requiere pase de acceso — gestionalo en Pases"
      );
      invalidate();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  const scrapeMutation = useMutation({
    mutationFn: () => api.tournaments.scrape(tournament.id),
    onSuccess: () => toast.success("Scraping en cola — tarda unos segundos"),
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "No se pudo forzar el scraping"),
  });

  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-border bg-card/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-medium">{tournament.name}</span>
          <Badge
            variant="outline"
            className={cn(
              tournament.status === "completed"
                ? "border-border bg-muted text-muted-foreground"
                : "border-primary/40 bg-primary/10 text-primary"
            )}
          >
            {tournament.status}
          </Badge>
          {tournament.current_round && (
            <span className="text-xs text-muted-foreground">
              · {tournament.current_round.name}
            </span>
          )}
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
          <Button
            size="sm"
            variant={tournament.is_active ? "secondary" : "outline"}
            onClick={() => toggleActiveMutation.mutate()}
          >
            <Power className="size-3.5" />
            {tournament.is_active ? "Activo" : "Inactivo"}
          </Button>
          <Button
            size="sm"
            variant={tournament.requires_access_pass ? "secondary" : "outline"}
            disabled={toggleAccessPassMutation.isPending}
            onClick={() => toggleAccessPassMutation.mutate()}
            title="Solo quien tenga un pase aprobado puede apostar en este torneo"
          >
            <Ticket className="size-3.5" />
            {tournament.requires_access_pass ? "Requiere pase" : "Libre"}
          </Button>
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

export default function AdminTournamentsPage() {
  const queryClient = useQueryClient();
  const { data: tournaments, isLoading } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
  });

  const [form, setForm] = useState({ name: "", tab_url: "", timezone: "America/Guayaquil" });

  const createMutation = useMutation({
    mutationFn: () => api.tournaments.create(form),
    onSuccess: () => {
      toast.success("Torneo creado — arrancó el primer scraping automáticamente");
      setForm({ name: "", tab_url: "", timezone: "America/Guayaquil" });
      queryClient.invalidateQueries({ queryKey: queryKeys.tournaments });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Error al crear el torneo"),
  });

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate();
        }}
        className="grid grid-cols-1 gap-3 rounded-2xl border border-border bg-card/60 p-5 sm:grid-cols-2"
      >
        <h2 className="flex items-center gap-2 font-heading text-base font-bold sm:col-span-2">
          <PlusCircle className="size-4 text-primary" /> Agregar torneo
        </h2>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="name">Nombre</Label>
          <Input
            id="name"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="PreCMUDE Quito 2026"
            required
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="timezone">Zona horaria</Label>
          <Input
            id="timezone"
            value={form.timezone}
            onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
            placeholder="America/Guayaquil"
            required
          />
        </div>
        <div className="flex flex-col gap-1.5 sm:col-span-2">
          <Label htmlFor="tab_url">URL del tab (CalicoTab)</Label>
          <Input
            id="tab_url"
            value={form.tab_url}
            onChange={(e) => setForm((f) => ({ ...f, tab_url: e.target.value }))}
            placeholder="https://torneo.calicotab.com/slug/"
            required
          />
          <p className="text-xs text-muted-foreground">
            Pegá cualquier link del tab del torneo — el sitio y el slug se detectan solos.
          </p>
        </div>
        <div className="sm:col-span-2">
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending && <Loader2 className="size-4 animate-spin" />}
            Crear torneo
          </Button>
        </div>
      </form>

      <section className="flex flex-col gap-3">
        <h2 className="font-heading text-base font-bold">Torneos registrados</h2>
        {isLoading && <LoadingState label="Cargando torneos…" />}
        {tournaments?.length === 0 && <EmptyState title="Sin torneos todavía" />}
        {tournaments?.map((t) => <TournamentRow key={t.id} tournament={t} />)}
      </section>
    </div>
  );
}
