import { cn } from "@/lib/utils";

/**
 * Barra de reparto de probabilidad implícita entre las opciones de un mercado.
 *
 * Es el elemento que más "transmisión en vivo" aporta: de un vistazo se ve quién es
 * favorito sin leer un solo número. Reemplaza a la lista de chips grises donde la opción
 * con 62% pesaba visualmente lo mismo que la de 8%.
 *
 * La transición de `width` es intencional pese a que animar `width` normalmente se evita
 * por layout thrashing: acá son pocos segmentos, en un contenedor de ancho fijo, y el
 * movimiento ES la información (la cuota se movió). Un `transform: scaleX` no serviría
 * porque deformaría el contenido y rompería el borde entre segmentos.
 */

export type ProbabilitySegment = {
  key: string;
  label: string;
  /** 0..1 */
  value: number;
  tone?: "primary" | "up" | "down" | "neutral";
};

const TONE_BG = {
  primary: "bg-primary",
  up: "bg-up",
  down: "bg-down",
  neutral: "bg-muted-foreground/50",
} as const;

export function ProbabilityBar({
  segments,
  showLegend = false,
  className,
}: {
  segments: ProbabilitySegment[];
  showLegend?: boolean;
  className?: string;
}) {
  const total = segments.reduce((sum, s) => sum + Math.max(0, s.value), 0);
  // Si el pool está vacío no hay nada que repartir -- una barra en blanco es más honesta
  // que repartir en partes iguales, que se leería como "todos empatados".
  const safeTotal = total > 0 ? total : 0;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div
        className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken"
        role="img"
        aria-label={
          safeTotal > 0
            ? segments
                .map((s) => `${s.label}: ${Math.round((s.value / safeTotal) * 100)}%`)
                .join(", ")
            : "Sin apuestas todavía"
        }
      >
        {safeTotal > 0 &&
          segments.map((s) => (
            <div
              key={s.key}
              className={cn(
                "h-full transition-[width] duration-500 ease-[var(--ease-broadcast)]",
                TONE_BG[s.tone ?? "neutral"]
              )}
              style={{ width: `${(s.value / safeTotal) * 100}%` }}
            />
          ))}
      </div>
      {showLegend && safeTotal > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {segments.map((s) => (
            <span
              key={s.key}
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <span
                className={cn("size-1.5 rounded-full", TONE_BG[s.tone ?? "neutral"])}
              />
              {s.label}
              <span data-stat className="font-medium text-foreground">
                {Math.round((s.value / safeTotal) * 100)}%
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
