import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/api/client";

export function LoadingState({ label = "Cargando…" }: { label?: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
      <Loader2 className="size-6 animate-spin" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.detail
      : error instanceof Error
        ? error.message
        : "Ocurrió un error inesperado.";

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-16 text-center">
      <AlertCircle className="size-6 text-destructive" />
      <p className="text-sm font-medium">No se pudo cargar la información</p>
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

export function EmptyState({
  title = "Nada por aquí todavía",
  description,
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground">
      <Inbox className="size-6" />
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="max-w-sm text-sm">{description}</p>}
    </div>
  );
}
