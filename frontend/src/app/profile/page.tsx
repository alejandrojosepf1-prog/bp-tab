"use client";

import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import { CalendarDays, Mail, ShieldCheck, User as UserIcon, Wallet } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { RequireAuth } from "@/components/auth/require-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { PageTransition } from "@/components/motion";

export default function ProfilePage() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-4 py-6">
      <RequireAuth>
        <PageTransition>
          <ProfileContent />
        </PageTransition>
      </RequireAuth>
    </div>
  );
}

function ProfileContent() {
  const { user } = useAuth();
  if (!user) return null;

  const initials = user.display_name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="flex flex-col gap-4">
      <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
        <UserIcon className="size-5" /> Perfil
      </h2>

      <Card>
        <CardContent className="flex items-center gap-4 pt-6">
          <Avatar className="size-14">
            <AvatarFallback className="text-lg">{initials}</AvatarFallback>
          </Avatar>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="text-lg font-semibold">{user.display_name}</span>
              {user.role === "admin" && (
                <Badge variant="secondary" className="gap-1">
                  <ShieldCheck className="size-3" /> Admin
                </Badge>
              )}
              {!user.is_active && <Badge variant="destructive">Inactivo</Badge>}
            </div>
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Mail className="size-3.5" /> {user.email}
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex items-center justify-between gap-3 pt-6">
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Wallet className="size-4" /> Saldo disponible
          </span>
          <span className="text-2xl font-semibold tabular-nums">
            ${user.balance.toLocaleString("es")}
          </span>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Detalles de la cuenta</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <CalendarDays className="size-4" /> Miembro desde
            </span>
            <span>
              {formatDistanceToNow(new Date(user.created_at), { addSuffix: true, locale: es })}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Rol</span>
            <span className="capitalize">{user.role}</span>
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Para ver tu historial de predicciones y el ranking, entra al torneo desde el selector de
        arriba y visita las secciones de Apuestas y Ranking.
      </p>
    </div>
  );
}
