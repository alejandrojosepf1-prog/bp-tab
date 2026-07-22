"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

/**
 * Selector de torneo del panel admin: chips clicables siempre visibles (nunca un dropdown).
 * `allowAll` agrega un chip "Todos" que emite null.
 */
export function TournamentChips({
  value,
  onChange,
  allowAll = false,
}: {
  value: string | null;
  onChange: (id: string | null) => void;
  allowAll?: boolean;
}) {
  const { data: tournaments } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
    staleTime: 30_000,
  });

  if (!tournaments?.length) {
    return (
      <p className="text-xs text-muted-foreground">
        No hay torneos registrados todavía — creá uno en Admin → Torneos.
      </p>
    );
  }

  const chip = (label: string, id: string | null) => {
    const selected = value === id;
    return (
      <button
        key={id ?? "all"}
        type="button"
        onClick={() => onChange(id)}
        className={cn(
          "rounded-lg border px-3 py-1.5 text-sm transition-colors",
          selected
            ? "border-primary/50 bg-primary/10 font-medium text-primary"
            : "border-border bg-card hover:bg-accent"
        )}
      >
        {label}
      </button>
    );
  };

  return (
    <div className="flex flex-wrap gap-1.5">
      {allowAll && chip("Todos", null)}
      {tournaments.map((t) => chip(t.name, String(t.id)))}
    </div>
  );
}
