"use client";

import { useMemo, useState } from "react";
import { Check, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

export interface PickerOption {
  value: string;
  label: string;
  hint?: string;
  emoji?: string | null;
}

/**
 * Reemplazo de los <Select>/dropdowns de BP$: una lista SIEMPRE visible de opciones
 * clicables con filtro por texto. Nada se esconde detrás de un popup — el criterio de
 * rediseño de Claim es "sin cajas de selección múltiple / dropdowns" en todo el dashboard.
 */
export function OptionPicker({
  options,
  value,
  onChange,
  placeholder = "Buscar…",
  emptyLabel = "Sin opciones",
  maxHeight = "max-h-56",
  searchable,
  columns = 1,
}: {
  options: PickerOption[];
  value: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  emptyLabel?: string;
  maxHeight?: string;
  /** default: sólo muestra buscador con >7 opciones */
  searchable?: boolean;
  columns?: 1 | 2;
}) {
  const [query, setQuery] = useState("");
  const showSearch = searchable ?? options.length > 7;

  const filtered = useMemo(() => {
    if (!query.trim()) return options;
    const q = query.trim().toLowerCase();
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(q) || o.hint?.toLowerCase().includes(q)
    );
  }, [options, query]);

  return (
    <div className="flex w-full flex-col gap-2">
      {showSearch && (
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className="h-8 pl-8 text-sm"
          />
        </div>
      )}
      <div
        role="listbox"
        className={cn(
          "grid gap-1 overflow-y-auto rounded-lg border border-border/70 bg-background/40 p-1",
          maxHeight,
          columns === 2 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1"
        )}
      >
        {filtered.length === 0 && (
          <p className="px-2 py-3 text-center text-xs text-muted-foreground">{emptyLabel}</p>
        )}
        {filtered.map((option) => {
          const selected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={selected}
              onClick={() => onChange(option.value)}
              className={cn(
                "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors",
                selected
                  ? "bg-primary/15 text-primary ring-1 ring-primary/40"
                  : "hover:bg-accent"
              )}
            >
              {option.emoji && <span className="shrink-0 text-base leading-none">{option.emoji}</span>}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{option.label}</span>
                {option.hint && (
                  <span className="block truncate text-xs text-muted-foreground">
                    {option.hint}
                  </span>
                )}
              </span>
              {selected && <Check className="size-4 shrink-0 text-primary" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
