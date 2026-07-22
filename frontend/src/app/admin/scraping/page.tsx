"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Badge } from "@/components/ui/badge";
import { TournamentChips } from "@/components/admin/tournament-chips";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";

const STATUS_CLASS: Record<string, string> = {
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  partial: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  running: "border-primary/40 bg-primary/10 text-primary",
};

export default function AdminScrapingPage() {
  const [tournamentId, setTournamentId] = useState<string | null>(null);

  const { data: logs, isLoading } = useQuery({
    queryKey: queryKeys.adminScrapeLogs(tournamentId ?? undefined),
    queryFn: () => api.admin.scrapeLogs(tournamentId ?? undefined),
    refetchInterval: 30_000,
  });

  return (
    <div className="flex flex-col gap-4">
      <TournamentChips value={tournamentId} onChange={setTournamentId} allowAll />

      {isLoading && <LoadingState label="Cargando corridas…" />}
      {logs && logs.length === 0 && <EmptyState title="Sin corridas de scraping todavía" />}

      {logs && logs.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border/70">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 bg-muted/40 text-left text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2 font-medium">Inicio</th>
                <th className="px-3 py-2 font-medium">Estado</th>
                <th className="hidden px-3 py-2 font-medium sm:table-cell">Estrategia</th>
                <th className="px-3 py-2 text-right font-medium">Creados</th>
                <th className="px-3 py-2 text-right font-medium">Actualizados</th>
                <th className="hidden px-3 py-2 font-medium md:table-cell">Error</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-b border-border/40 last:border-b-0">
                  <td className="px-3 py-2 font-mono text-xs">
                    {format(new Date(log.started_at), "dd/MM HH:mm:ss")}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant="outline" className={cn(STATUS_CLASS[log.status] ?? "")}>
                      {log.status}
                    </Badge>
                  </td>
                  <td className="hidden px-3 py-2 text-xs text-muted-foreground sm:table-cell">
                    {log.strategy_used ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">{log.entities_created ?? 0}</td>
                  <td className="px-3 py-2 text-right font-mono">{log.entities_updated ?? 0}</td>
                  <td className="hidden max-w-[220px] truncate px-3 py-2 text-xs text-destructive md:table-cell">
                    {log.error_message ?? ""}
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
