import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  // tournaments
  upcoming: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  in_progress: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  eliminations: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  completed: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  draft: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  // bet markets
  open: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  closed: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  settled: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  // predictions
  locked: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  // break status
  safe: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  alive: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  eliminated: "bg-red-500/15 text-red-400 border-red-500/30",
  // scrape logs
  success: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  partial: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  failed: "bg-red-500/15 text-red-400 border-red-500/30",
  running: "bg-blue-500/15 text-blue-400 border-blue-500/30",
};

const STATUS_LABELS: Record<string, string> = {
  upcoming: "Próximo",
  in_progress: "En curso",
  eliminations: "Eliminatorias",
  completed: "Completado",
  draft: "Borrador",
  open: "Abierto",
  closed: "Cerrado",
  settled: "Liquidado",
  locked: "Bloqueado",
  safe: "Safe",
  alive: "Alive",
  eliminated: "Eliminado",
  success: "Éxito",
  partial: "Parcial",
  failed: "Fallido",
  running: "En proceso",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", STATUS_STYLES[status] ?? "", className)}
    >
      {STATUS_LABELS[status] ?? status}
    </Badge>
  );
}
