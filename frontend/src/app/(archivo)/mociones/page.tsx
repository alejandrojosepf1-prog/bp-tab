"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Quote } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MOTION_CATEGORY_OPTIONS } from "@/components/betting/market-card";
import type { MotionCategory } from "@/lib/api/types";

const CATEGORY_LABEL = Object.fromEntries(
  MOTION_CATEGORY_OPTIONS.map((o) => [o.value, o.label])
);

export default function MocionesPage() {
  const [category, setCategory] = useState<string>("");
  const [year, setYear] = useState<string>("");

  const params = {
    category: (category || undefined) as MotionCategory | undefined,
    year: year ? Number(year) : undefined,
  };

  const { data: motions, isLoading, error } = useQuery({
    queryKey: queryKeys.archiveMotions(params),
    queryFn: () => api.archive.motions(params),
  });

  const years = Array.from(
    new Set((motions ?? []).map((m) => m.tournament_year).filter((y): y is number => y != null))
  ).sort((a, b) => b - a);

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <h1 className="font-heading text-3xl font-bold tracking-tight">Archivo de mociones</h1>
        <p className="max-w-2xl text-muted-foreground">
          Todas las mociones de torneos ya cerrados, buscables por tipo y por año.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Select value={category} onValueChange={(v) => setCategory(v ?? "")}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Cualquier tipo" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">Cualquier tipo</SelectItem>
            {MOTION_CATEGORY_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={year} onValueChange={(v) => setYear(v ?? "")}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Cualquier año" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">Cualquier año</SelectItem>
            {years.map((y) => (
              <SelectItem key={y} value={String(y)}>
                {y}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading && <LoadingState label="Cargando mociones…" />}
      {error && <ErrorState error={error} />}
      {motions?.length === 0 && (
        <EmptyState
          title="Sin mociones para este filtro"
          description="Probá con otro tipo o año, o mirá el archivo completo."
        />
      )}

      {motions && motions.length > 0 && (
        <div className="flex flex-col gap-3">
          {motions.map((m, i) => (
            <div
              key={`${m.tournament_slug}-${m.round_name}-${i}`}
              className="flex flex-col gap-2 rounded-xl border border-border bg-card p-5"
            >
              <div className="flex items-start gap-3">
                <Quote className="mt-0.5 size-4 shrink-0 text-primary" />
                <p className="text-base leading-snug">{m.motion_text}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2 pl-7 text-xs text-muted-foreground">
                <Link
                  href={`/torneos/${m.tournament_slug}`}
                  className="font-medium text-foreground hover:text-primary"
                >
                  {m.tournament_name}
                </Link>
                {m.tournament_year && <span>{m.tournament_year}</span>}
                <span>· {m.round_name}</span>
                {m.motion_category && (
                  <Badge variant="outline">{CATEGORY_LABEL[m.motion_category]}</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
