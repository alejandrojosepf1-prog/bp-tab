"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Landmark, MapPin } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";

export default function CircuitoPage() {
  const { data: institutions, isLoading, error } = useQuery({
    queryKey: queryKeys.archiveInstitutions,
    queryFn: api.archive.institutions,
  });

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <h1 className="font-heading text-3xl font-bold tracking-tight">El circuito</h1>
        <p className="max-w-2xl text-muted-foreground">
          Instituciones que han competido en los torneos que Claim sigue, con su historial a
          través de los años unificado — más allá de cómo se haya llamado su equipo en cada
          edición.
        </p>
      </div>

      {isLoading && <LoadingState label="Cargando instituciones…" />}
      {error && <ErrorState error={error} />}
      {institutions?.length === 0 && <EmptyState title="Todavía no hay instituciones cargadas" />}

      {institutions && institutions.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {institutions.map((inst) => (
            <Link
              key={inst.id}
              href={`/circuito/instituciones/${inst.slug}`}
              className="group flex flex-col gap-2 rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/40"
            >
              <div className="flex items-start gap-2.5">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Landmark className="size-4" />
                </span>
                <span className="font-medium leading-snug group-hover:text-primary">
                  {inst.name}
                </span>
              </div>
              {inst.region && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <MapPin className="size-3" /> {inst.region}
                </span>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
