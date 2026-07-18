"use client";

import Link from "next/link";
import { LockKeyhole } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/query-state";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) return <LoadingState />;

  if (!isAuthenticated) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 py-24 text-center">
        <LockKeyhole className="size-8 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Inicia sesión para continuar</h2>
        <p className="max-w-sm text-sm text-muted-foreground">
          Esta sección requiere una cuenta para ver tus predicciones y apuestas.
        </p>
        <Button render={<Link href="/login" />}>Iniciar sesión</Button>
      </div>
    );
  }

  return <>{children}</>;
}
