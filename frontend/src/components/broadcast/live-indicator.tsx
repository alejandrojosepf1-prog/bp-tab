import { cn } from "@/lib/utils";

/**
 * Señal de "esto está pasando ahora". Punto pulsante + palabra, siempre juntos.
 *
 * El par punto+palabra no es redundancia: `--live` comparte el rojo con `--down`
 * (cuota bajando) porque "EN VIVO en rojo" es una convención de transmisión demasiado
 * fuerte para pelearla. Lo que evita la ambigüedad es que esto SIEMPRE aparece con la
 * etiqueta y nunca como color suelto sobre un número.
 *
 * Usa `.live-dot` (respira) y no `animate-pulse` de Tailwind, que es el mismo fade que
 * usan los skeletons de carga -- se leería como "cargando", no como "en vivo".
 */
export function LiveIndicator({
  label = "EN VIVO",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "label-broadcast inline-flex items-center gap-1.5 text-[color:var(--live)]",
        className
      )}
    >
      <span className="live-dot size-1.5 rounded-full bg-[color:var(--live)]" />
      {label}
    </span>
  );
}
