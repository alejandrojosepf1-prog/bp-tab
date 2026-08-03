import { cn } from "@/lib/utils";

/**
 * Número protagonista de una placa de transmisión: etiqueta chica arriba, número grande
 * abajo, delta opcional al costado.
 *
 * Existe porque en el diseño anterior un dato clave (una cuota, un balance, un conteo de
 * equipos) se renderizaba con el mismo `text-sm` que un texto de ayuda -- en una app cuyo
 * contenido SON los números. Acá el número manda y la etiqueta lo acompaña, no al revés.
 */

const SIZE_CLASS = {
  xl: "stat-xl",
  lg: "stat-lg",
  md: "stat-md",
  sm: "stat-sm",
} as const;

export type StatSize = keyof typeof SIZE_CLASS;

export function StatLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <span className={cn("label-broadcast block", className)}>{children}</span>;
}

export function StatNumber({
  value,
  label,
  size = "md",
  delta,
  suffix,
  tone = "default",
  className,
}: {
  value: React.ReactNode;
  label?: React.ReactNode;
  size?: StatSize;
  /** Variación respecto al valor anterior. Positivo pinta verde, negativo rojo. */
  delta?: number | null;
  suffix?: string;
  tone?: "default" | "primary" | "up" | "down" | "muted";
  className?: string;
}) {
  const toneClass = {
    default: "text-foreground",
    primary: "text-primary",
    up: "text-up",
    down: "text-down",
    muted: "text-muted-foreground",
  }[tone];

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {label && <StatLabel>{label}</StatLabel>}
      <div className="flex items-baseline gap-1.5">
        <span data-stat className={cn("stat", SIZE_CLASS[size], toneClass)}>
          {value}
        </span>
        {suffix && (
          <span className="stat stat-sm text-muted-foreground">{suffix}</span>
        )}
        {delta != null && delta !== 0 && <DeltaTag delta={delta} />}
      </div>
    </div>
  );
}

/**
 * Variación con flecha. La flecha es deliberada y no decorativa: el color solo no puede
 * cargar el significado (daltonismo, y además el rojo también se usa para "en vivo"), así
 * que el glifo lo desambigua -- regla de accesibilidad "no depender solo del color".
 */
export function DeltaTag({ delta, className }: { delta: number; className?: string }) {
  const up = delta > 0;
  return (
    <span
      className={cn(
        "stat inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-xs",
        up ? "bg-up-soft text-up" : "bg-down-soft text-down",
        className
      )}
    >
      <span aria-hidden>{up ? "▲" : "▼"}</span>
      <span className="sr-only">{up ? "subió" : "bajó"}</span>
      {Math.abs(delta).toFixed(2)}
    </span>
  );
}
