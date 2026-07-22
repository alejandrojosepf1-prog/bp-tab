"use client";

import { Settings, Globe, Palette, Info } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";

function Row({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: typeof Settings;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card/60 px-4 py-3">
      <Icon className="size-4 shrink-0 text-primary" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-8">
      <h1 className="font-heading text-2xl font-bold tracking-tight">Configuración</h1>

      <Row
        icon={Palette}
        title="Tema"
        description="Claim usa tema oscuro fijo — es parte de la identidad visual."
      >
        <span className="rounded-md bg-muted px-2.5 py-1 text-xs text-muted-foreground">
          Oscuro
        </span>
      </Row>

      <Row
        icon={Globe}
        title="Idioma"
        description="Interfaz en español (es). Otros idiomas no están disponibles todavía."
      >
        <span className="rounded-md bg-muted px-2.5 py-1 text-xs text-muted-foreground">ES</span>
      </Row>

      {user && (
        <Row
          icon={Settings}
          title="Sesión"
          description={`Conectado como ${user.email}. La sesión se guarda localmente en este navegador.`}
        />
      )}

      <Row
        icon={Info}
        title="Acerca de Claim"
        description="Mercados de predicción sobre torneos de debate BP con dólares 100% ficticios. Los datos del torneo se sincronizan automáticamente desde el tab público (CalicoTab). No existe dinero real en ninguna parte del sistema."
      />
    </div>
  );
}
