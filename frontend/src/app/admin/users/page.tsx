"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ShieldCheck, UserRound } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoadingState, EmptyState } from "@/components/query-state";
import { cn } from "@/lib/utils";

export default function AdminUsersPage() {
  const queryClient = useQueryClient();
  const { user: me } = useAuth();
  const { data: users, isLoading } = useQuery({
    queryKey: queryKeys.adminUsers,
    queryFn: api.admin.users,
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: number; role?: "admin" | "user"; is_active?: boolean }) =>
      api.admin.updateUser(vars.id, {
        ...(vars.role !== undefined ? { role: vars.role } : {}),
        ...(vars.is_active !== undefined ? { is_active: vars.is_active } : {}),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
    onError: (err) => toast.error(err instanceof ApiError ? err.detail : "Error al actualizar"),
  });

  return (
    <div className="flex flex-col gap-3">
      {isLoading && <LoadingState label="Cargando usuarios…" />}
      {users && users.length === 0 && <EmptyState title="Sin usuarios" />}
      {users?.map((u) => {
        const isSelf = me?.id === u.id;
        return (
          <div
            key={u.id}
            className={cn(
              "flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card/60 px-4 py-3",
              !u.is_active && "opacity-60"
            )}
          >
            <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
              {u.role === "admin" ? (
                <ShieldCheck className="size-4 text-primary" />
              ) : (
                <UserRound className="size-4 text-muted-foreground" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {u.display_name}
                {isSelf && <span className="ml-1.5 text-xs text-muted-foreground">(vos)</span>}
              </p>
              <p className="truncate text-xs text-muted-foreground">{u.email}</p>
            </div>
            <Badge
              variant="outline"
              className={cn(
                u.role === "admin"
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-muted text-muted-foreground"
              )}
            >
              {u.role === "admin" ? "Admin" : "Usuario"}
            </Badge>
            <div className="flex gap-1.5">
              <Button
                size="sm"
                variant="outline"
                disabled={isSelf || updateMutation.isPending}
                onClick={() =>
                  updateMutation.mutate({
                    id: u.id,
                    role: u.role === "admin" ? "user" : "admin",
                  })
                }
              >
                {u.role === "admin" ? "Quitar admin" : "Hacer admin"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={isSelf || updateMutation.isPending}
                onClick={() => updateMutation.mutate({ id: u.id, is_active: !u.is_active })}
              >
                {u.is_active ? "Desactivar" : "Activar"}
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
