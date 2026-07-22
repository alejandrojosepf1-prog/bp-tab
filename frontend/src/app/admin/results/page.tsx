"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Loader2, Trophy } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";
import type { PendingEliminationDebate } from "@/lib/api/types";

/**
 * Resultado de eliminatoria a mano: botones clicables por equipo (final: uno solo;
 * semis/cuartos: los que avanzan). Sin diálogos ni checkboxes escondidos.
 */
function PendingResultCard({ debate }: { debate: PendingEliminationDebate }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number[]>([]);

  const submitMutation = useMutation({
    mutationFn: () =>
      debate.is_final
        ? api.admin.submitManualResult(debate.debate_id, { champion_team_id: selected[0] })
        : api.admin.submitManualResult(debate.debate_id, { advancing_team_ids: selected }),
    onSuccess: () => {
      toast.success("Resultado confirmado");
      setSelected([]);
      queryClient.invalidateQueries({ queryKey: queryKeys.adminPendingEliminationResults() });
      queryClient.invalidateQueries({ queryKey: queryKeys.tournament(debate.tournament_id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.tournaments });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Error al confirmar el resultado"),
  });

  const toggleTeam = (teamId: number) => {
    if (debate.is_final) {
      setSelected((prev) => (prev[0] === teamId ? [] : [teamId]));
      return;
    }
    setSelected((prev) =>
      prev.includes(teamId) ? prev.filter((id) => id !== teamId) : [...prev, teamId]
    );
  };

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card/60 p-4">
      <div className="flex items-center gap-2">
        <span className="font-medium">{debate.round_name}</span>
        {debate.is_final && <Trophy className="size-4 text-primary" />}
        <span className="ml-auto text-xs text-muted-foreground">
          {debate.is_final ? "Elegí al campeón" : "Marcá quiénes avanzan"}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {debate.teams.map((t) => {
          const isSelected = selected.includes(t.team_id);
          return (
            <button
              key={t.team_id}
              type="button"
              onClick={() => toggleTeam(t.team_id)}
              className={cn(
                "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                isSelected
                  ? "border-primary/50 bg-primary/10 font-medium text-primary"
                  : "border-border bg-background/40 hover:bg-accent"
              )}
            >
              {t.team_name}
              {isSelected && debate.is_final && " 🏆"}
            </button>
          );
        })}
      </div>
      <Button
        className="w-fit"
        disabled={selected.length === 0 || submitMutation.isPending}
        onClick={() => submitMutation.mutate()}
      >
        {submitMutation.isPending && <Loader2 className="size-3.5 animate-spin" />}
        Confirmar resultado
      </Button>
    </div>
  );
}

export default function AdminResultsPage() {
  const { data: pending, isLoading } = useQuery({
    queryKey: queryKeys.adminPendingEliminationResults(),
    queryFn: () => api.admin.pendingEliminationResults(),
    refetchInterval: 60_000,
  });

  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-muted-foreground">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-400" />
        Rondas eliminatorias cuyo cruce ya se conoce pero cuyo resultado no aparece en el tab.
        Confirmalo acá; si el tab después publica el resultado oficial, el próximo scraping lo
        sobreescribe automáticamente.
      </p>
      {isLoading && <LoadingState label="Buscando resultados pendientes…" />}
      {pending && pending.length === 0 && (
        <EmptyState title="No hay resultados pendientes de confirmar" />
      )}
      {pending?.map((debate) => (
        <PendingResultCard key={debate.debate_id} debate={debate} />
      ))}
    </div>
  );
}
