"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MapPin, Trophy, Users } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";

export default function CircuitInstitutionPage() {
  const { slug } = useParams<{ slug: string }>();

  const { data: institution, isLoading, error } = useQuery({
    queryKey: queryKeys.archiveInstitution(slug),
    queryFn: () => api.archive.institution(slug),
  });

  if (isLoading) return <LoadingState label="Cargando institución…" />;
  if (error || !institution) return <ErrorState error={error ?? new Error("No encontrada")} />;

  return (
    <div className="flex flex-col gap-8">
      <Link
        href="/circuito"
        className="flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="size-3.5" /> Todo el circuito
      </Link>

      <div className="flex flex-col gap-2">
        <h1 className="font-heading text-3xl font-bold tracking-tight">{institution.name}</h1>
        {institution.region && (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <MapPin className="size-4" /> {institution.region}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 font-heading text-lg font-bold">
          <Users className="size-4.5 text-primary" /> Historial
        </h2>
        {institution.appearances.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Sin apariciones registradas en los torneos que Claim sigue todavía.
          </p>
        ) : (
          <div className="flex flex-col gap-2.5">
            {institution.appearances.map((a) => (
              <Link
                key={a.tournament_slug}
                href={`/torneos/${a.tournament_slug}`}
                className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{a.tournament_name}</span>
                  {a.tournament_year && (
                    <span className="text-sm text-muted-foreground">{a.tournament_year}</span>
                  )}
                  {a.was_champion && (
                    <Badge variant="secondary">
                      <Trophy className="size-3" /> Campeón
                    </Badge>
                  )}
                </div>
                <span className="text-sm text-muted-foreground">
                  {a.team_names.join(", ")}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
