"use client";

import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/query-state";

export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isAdmin, isLoading } = useAuth();

  if (isLoading) return <LoadingState />;

  if (!isAuthenticated || !isAdmin) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 py-24 text-center">
        <ShieldAlert className="size-8 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Acceso restringido</h2>
        <p className="max-w-sm text-sm text-muted-foreground">
          Esta sección es solo para administradores.
        </p>
        <Button
          variant="secondary"
          render={<Link href={isAuthenticated ? "/dashboard" : "/login"} />}
        >
          {isAuthenticated ? "Volver al dashboard" : "Iniciar sesión"}
        </Button>
      </div>
    );
  }

  return <>{children}</>;
}
