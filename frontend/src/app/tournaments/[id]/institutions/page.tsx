"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Landmark } from "lucide-react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { LoadingState, ErrorState, EmptyState } from "@/components/query-state";
import { Card, CardContent } from "@/components/ui/card";
import { MotionList, MotionItem } from "@/components/motion";

export default function InstitutionsPage() {
  const { id: tournamentId } = useParams<{ id: string }>();

  const { data: institutions, isLoading, error } = useQuery({
    queryKey: queryKeys.institutions(tournamentId),
    queryFn: () => api.institutions.list(tournamentId),
    staleTime: 60_000,
  });

  return (
    <div className="flex flex-col gap-4">
      <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <Landmark className="size-5" /> Instituciones
      </h2>

      {isLoading && <LoadingState label="Cargando instituciones…" />}
      {error && <ErrorState error={error} />}
      {institutions && institutions.length === 0 && (
        <EmptyState title="Sin instituciones registradas" />
      )}

      {institutions && institutions.length > 0 && (
        <MotionList className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {institutions.map((inst) => (
            <MotionItem key={inst.id}>
              <Card>
                <CardContent className="flex flex-col gap-1 pt-6">
                  <span className="text-base font-medium">{inst.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {inst.code} {inst.region ? `· ${inst.region}` : ""}
                  </span>
                </CardContent>
              </Card>
            </MotionItem>
          ))}
        </MotionList>
      )}
    </div>
  );
}
