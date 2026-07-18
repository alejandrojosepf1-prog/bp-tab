"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/** Animated horizontal probability gauge used on the Break Predictor screen. */
export function BreakGauge({
  probability,
  className,
  colorClass,
}: {
  probability: number;
  className?: string;
  colorClass?: string;
}) {
  const pct = Math.max(0, Math.min(1, probability)) * 100;

  return (
    <div className={cn("h-2.5 w-full overflow-hidden rounded-full bg-muted", className)}>
      <motion.div
        className={cn("h-full rounded-full", colorClass ?? "bg-primary")}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.7, ease: "easeOut" }}
      />
    </div>
  );
}
