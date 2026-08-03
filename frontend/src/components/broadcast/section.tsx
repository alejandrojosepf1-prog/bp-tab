import { cn } from "@/lib/utils";

/**
 * Encabezado de sección con regla horizontal que llena el espacio sobrante.
 *
 * Su función es dar RITMO: el diseño anterior era un stack de tarjetas todas del mismo
 * ancho y peso, sin ninguna marca de "acá empieza otra cosa". La regla corta la página
 * horizontalmente y crea la retícula de placa de transmisión.
 */
export function SectionRule({
  title,
  meta,
  className,
}: {
  title: React.ReactNode;
  /** Contenido al extremo derecho: conteo, filtro, acción. */
  meta?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <h2 className="label-broadcast shrink-0 text-foreground">{title}</h2>
      <span className="h-px flex-1 bg-border" />
      {meta && <span className="shrink-0 text-xs text-muted-foreground">{meta}</span>}
    </div>
  );
}
