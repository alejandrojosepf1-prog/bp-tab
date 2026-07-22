"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

function formatRemaining(ms: number): string {
  if (ms <= 0) return "00:00";
  const totalMinutes = Math.floor(ms / 60_000);
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  const hh = String(hours).padStart(2, "0");
  const mm = String(minutes).padStart(2, "0");
  return days > 0 ? `${days}d ${hh}:${mm}` : `${hh}:${mm}`;
}

/**
 * Live-ticking "time until close" readout (HH:MM, or "Dd HH:MM" past 24h), updating client-side
 * every second with no page refresh needed. Purely a display of time-until `target` -- the
 * authoritative open/closed state still comes from the server (`market.status`), since this
 * can't know about scrape-cycle latency on the backend's own auto-close.
 */
export function CountdownBadge({
  target,
  className,
  prefix,
}: {
  target: string;
  className?: string;
  /** e.g. "cierra" -> "cierra en 23:04" / "closed" styling once it hits zero */
  prefix?: string;
}) {
  const targetMs = new Date(target).getTime();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const remaining = targetMs - now;
  const isPast = remaining <= 0;

  return (
    <span
      className={cn(
        "font-mono tabular-nums",
        isPast ? "text-muted-foreground" : "text-foreground",
        className
      )}
    >
      {prefix && `${isPast ? "cerró" : prefix} `}
      {formatRemaining(remaining)}
    </span>
  );
}
