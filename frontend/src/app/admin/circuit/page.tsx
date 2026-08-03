"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, PlusCircle, Landmark, Users } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { LoadingState, EmptyState } from "@/components/query-state";
import type { CircuitInstitution, CircuitInstitutionResolvePayload } from "@/lib/api/types";

const NO_REGION = "Sin país registrado";

/**
 * Elegí una institución ya cargada (agrupada por país) o cargá una nueva -- reemplaza el
 * arrastrar-y-soltar que se había pedido originalmente por un selector con teclado accesible.
 * Mismo resultado (asignar la institución correcta), sin la complejidad de implementar drag&drop
 * a mano (foco, soporte táctil, navegación por teclado ya vienen gratis con un <select>).
 */
function InstitutionPicker({
  institutions,
  onAssign,
  isPending,
}: {
  institutions: CircuitInstitution[];
  onAssign: (payload: CircuitInstitutionResolvePayload) => void;
  isPending: boolean;
}) {
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [selectedId, setSelectedId] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [newRegion, setNewRegion] = useState("");

  const grouped = useMemo(() => {
    const byRegion = new Map<string, CircuitInstitution[]>();
    for (const inst of institutions) {
      const key = inst.region ?? NO_REGION;
      if (!byRegion.has(key)) byRegion.set(key, []);
      byRegion.get(key)!.push(inst);
    }
    return [...byRegion.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [institutions]);

  if (mode === "new") {
    return (
      <div className="flex flex-1 flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label className="text-xs">Nombre de la institución</Label>
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Universidad Nueva"
            className="h-8 text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-xs">País</Label>
          <Input
            value={newRegion}
            onChange={(e) => setNewRegion(e.target.value)}
            placeholder="Panamá"
            className="h-8 w-32 text-xs"
          />
        </div>
        <Button
          size="sm"
          disabled={!newName.trim() || isPending}
          onClick={() =>
            onAssign({
              new_institution_name: newName.trim(),
              new_institution_region: newRegion.trim() || undefined,
            })
          }
        >
          {isPending && <Loader2 className="size-3.5 animate-spin" />}
          Crear y asignar
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setMode("existing")}>
          Cancelar
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-wrap items-center gap-2">
      <Select value={selectedId} onValueChange={(value) => setSelectedId(value ?? "")}>
        <SelectTrigger className="h-8 min-w-56 text-xs">
          <SelectValue placeholder="Elegí una institución…" />
        </SelectTrigger>
        <SelectContent>
          {grouped.map(([region, insts]) => (
            <SelectGroup key={region}>
              <SelectLabel>{region}</SelectLabel>
              {insts.map((inst) => (
                <SelectItem key={inst.id} value={String(inst.id)}>
                  {inst.name}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
      <Button
        size="sm"
        disabled={!selectedId || isPending}
        onClick={() => onAssign({ circuit_institution_id: Number(selectedId) })}
      >
        {isPending && <Loader2 className="size-3.5 animate-spin" />}
        Asignar
      </Button>
      <Button size="sm" variant="outline" onClick={() => setMode("new")}>
        <PlusCircle className="size-3.5" /> Nueva institución
      </Button>
    </div>
  );
}

export default function AdminCircuitPage() {
  const queryClient = useQueryClient();

  const { data: institutions, isLoading: loadingInstitutions } = useQuery({
    queryKey: queryKeys.adminCircuitInstitutions,
    queryFn: api.admin.circuitInstitutions,
  });

  const { data: reviewQueue, isLoading: loadingReviewQueue } = useQuery({
    queryKey: queryKeys.adminCircuitReviewQueue,
    queryFn: api.admin.circuitReviewQueue,
  });

  const { data: unassignedTeams, isLoading: loadingTeams } = useQuery({
    queryKey: queryKeys.adminUnassignedTeams,
    queryFn: api.admin.unassignedTeams,
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.adminCircuitInstitutions });
    queryClient.invalidateQueries({ queryKey: queryKeys.adminCircuitReviewQueue });
    queryClient.invalidateQueries({ queryKey: queryKeys.adminUnassignedTeams });
  };

  const resolveMutation = useMutation({
    mutationFn: ({
      institutionId,
      payload,
    }: {
      institutionId: number;
      payload: CircuitInstitutionResolvePayload;
    }) => api.admin.resolveCircuitInstitution(institutionId, payload),
    onSuccess: () => {
      toast.success("Institución resuelta");
      invalidateAll();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al resolver"),
  });

  const assignTeamMutation = useMutation({
    mutationFn: ({
      teamId,
      payload,
    }: {
      teamId: number;
      payload: CircuitInstitutionResolvePayload;
    }) => api.admin.assignTeamInstitution(teamId, payload),
    onSuccess: () => {
      toast.success("Equipo asignado");
      invalidateAll();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al asignar"),
  });

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-heading text-base font-bold">
          <Landmark className="size-4 text-primary" /> Instituciones por revisar
          {reviewQueue && reviewQueue.length > 0 && (
            <Badge variant="outline">{reviewQueue.length}</Badge>
          )}
        </h2>
        <p className="text-xs text-muted-foreground">
          Coincidencias automáticas que no fueron exactas -- confirmá que la institución sugerida
          es la correcta, o corregila eligiendo otra.
        </p>
        {loadingReviewQueue && <LoadingState label="Cargando…" />}
        {reviewQueue?.length === 0 && (
          <EmptyState title="Nada pendiente" description="Todos los matches automáticos están confirmados." />
        )}
        {reviewQueue?.map((item) => (
          <div
            key={item.institution_id}
            className="flex flex-col gap-2 rounded-xl border border-border bg-card/60 p-4"
          >
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{item.institution_name}</span>
              <span className="text-xs text-muted-foreground">({item.institution_code})</span>
              <span className="text-muted-foreground">→ sugerido:</span>
              <Badge variant="outline" className="border-primary/40 bg-primary/10 text-primary">
                {item.matched_circuit_institution.name}
              </Badge>
            </div>
            <InstitutionPicker
              institutions={institutions ?? []}
              isPending={resolveMutation.isPending}
              onAssign={(payload) =>
                resolveMutation.mutate({ institutionId: item.institution_id, payload })
              }
            />
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-heading text-base font-bold">
          <Users className="size-4 text-primary" /> Equipos sin institución
          {unassignedTeams && unassignedTeams.length > 0 && (
            <Badge variant="outline">{unassignedTeams.length}</Badge>
          )}
        </h2>
        <p className="text-xs text-muted-foreground">
          El nombre del equipo no coincidió con ninguna institución de su propio torneo -- asignala
          a mano.
        </p>
        {loadingTeams && <LoadingState label="Cargando…" />}
        {unassignedTeams?.length === 0 && (
          <EmptyState title="Nada pendiente" description="Todos los equipos tienen institución." />
        )}
        {unassignedTeams?.map((team) => (
          <div
            key={team.team_id}
            className="flex flex-col gap-2 rounded-xl border border-border bg-card/60 p-4"
          >
            <span className="text-sm font-medium">{team.team_name}</span>
            <InstitutionPicker
              institutions={institutions ?? []}
              isPending={assignTeamMutation.isPending}
              onAssign={(payload) =>
                assignTeamMutation.mutate({ teamId: team.team_id, payload })
              }
            />
          </div>
        ))}
      </section>

      {loadingInstitutions && institutions === undefined && (
        <p className="text-xs text-muted-foreground">Cargando el listado de instituciones…</p>
      )}
    </div>
  );
}
