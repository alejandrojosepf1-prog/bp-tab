"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { Check, Copy, Loader2, Mail, Phone, ShieldQuestion, Ticket, X } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";
import type { AccessPass, AccessPassStatus } from "@/lib/api/types";

const STATUS_FILTERS: { value: AccessPassStatus; label: string }[] = [
  { value: "pending", label: "Pendientes" },
  { value: "approved", label: "Aprobados" },
  { value: "rejected", label: "Rechazados" },
];

function MatchHintBadge({ pass }: { pass: AccessPass }) {
  if (!pass.match_hint) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        <ShieldQuestion className="size-3" /> Sin coincidencia
      </Badge>
    );
  }
  const kindLabel = pass.match_hint.kind === "speaker" ? "orador" : "juez";
  return (
    <Badge variant="outline" className="border-primary/40 bg-primary/10 text-primary">
      Coincide con {pass.match_hint.name} ({kindLabel})
    </Badge>
  );
}

function AccessPassRow({ pass }: { pass: AccessPass }) {
  const queryClient = useQueryClient();
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.adminAccessPasses(pass.tournament_id) });

  const approveMutation = useMutation({
    mutationFn: () => api.accessPasses.approve(pass.id),
    onSuccess: () => {
      toast.success(`Pase de ${pass.full_name} aprobado — se le mandó el correo de activación`);
      invalidate();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al aprobar"),
  });

  const rejectMutation = useMutation({
    mutationFn: () => api.accessPasses.reject(pass.id),
    onSuccess: () => {
      toast.success(`Pase de ${pass.full_name} rechazado`);
      invalidate();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al rechazar"),
  });

  const isPending = approveMutation.isPending || rejectMutation.isPending;

  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-border bg-card/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{pass.full_name}</span>
          <MatchHintBadge pass={pass} />
        </div>
        <span className="text-xs text-muted-foreground">
          {format(new Date(pass.created_at), "d MMM HH:mm", { locale: es })}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <Mail className="size-3" /> {pass.email}
        </span>
        <span className="flex items-center gap-1">
          <Phone className="size-3" /> {pass.phone}
        </span>
      </div>
      {pass.status === "pending" && (
        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            disabled={isPending}
            onClick={() => approveMutation.mutate()}
            className="flex-1 sm:flex-none"
          >
            {approveMutation.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Check className="size-3.5" />
            )}
            Aprobar
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={isPending}
            onClick={() => rejectMutation.mutate()}
            className="flex-1 sm:flex-none"
          >
            {rejectMutation.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <X className="size-3.5" />
            )}
            Rechazar
          </Button>
        </div>
      )}
    </div>
  );
}

export default function AdminAccessPassesPage() {
  const [tournamentId, setTournamentId] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<AccessPassStatus>("pending");

  const { data: tournaments } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
  });

  const { data: passes, isLoading } = useQuery({
    queryKey: queryKeys.adminAccessPasses(tournamentId, statusFilter),
    queryFn: () => api.accessPasses.list(tournamentId, statusFilter),
    enabled: !!tournamentId,
  });

  const requestUrl =
    tournamentId && typeof window !== "undefined"
      ? `${window.location.origin}/access-request/${tournamentId}`
      : "";

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card/60 p-5">
        <h2 className="flex items-center gap-2 font-heading text-base font-bold">
          <Ticket className="size-4 text-primary" /> Pases de acceso
        </h2>
        <p className="text-xs text-muted-foreground">
          Solo aplica a torneos con &quot;requiere pase&quot; activado (togglealo en Torneos). El
          bloqueo de participantes se revisa en vivo en cada apuesta, no acá.
        </p>
        <Select value={tournamentId} onValueChange={(value) => setTournamentId(value ?? "")}>
          <SelectTrigger className="w-full sm:w-72">
            <SelectValue placeholder="Elegí un torneo" />
          </SelectTrigger>
          <SelectContent>
            {tournaments
              ?.filter((t) => t.requires_access_pass)
              .map((t) => (
                <SelectItem key={t.id} value={String(t.id)}>
                  {t.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>

        {tournamentId && requestUrl && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs">
            <span className="truncate text-muted-foreground">{requestUrl}</span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="ml-auto h-7 px-2"
              onClick={() => {
                navigator.clipboard.writeText(requestUrl);
                toast.success("Link copiado");
              }}
            >
              <Copy className="size-3.5" /> Copiar
            </Button>
          </div>
        )}
      </div>

      {tournamentId && (
        <>
          <div className="flex gap-1.5">
            {STATUS_FILTERS.map((f) => (
              <Button
                key={f.value}
                size="sm"
                variant={statusFilter === f.value ? "secondary" : "outline"}
                className={cn(statusFilter === f.value && "border-primary/40")}
                onClick={() => setStatusFilter(f.value)}
              >
                {f.label}
              </Button>
            ))}
          </div>

          <div className="flex flex-col gap-3">
            {isLoading && <LoadingState label="Cargando pases…" />}
            {passes?.length === 0 && (
              <EmptyState
                title="Nada acá"
                description={`No hay pases ${STATUS_FILTERS.find((f) => f.value === statusFilter)?.label.toLowerCase()}.`}
              />
            )}
            {passes?.map((pass) => <AccessPassRow key={pass.id} pass={pass} />)}
          </div>
        </>
      )}
    </div>
  );
}
