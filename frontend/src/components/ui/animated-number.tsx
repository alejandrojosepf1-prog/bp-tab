"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { formatTokens } from "@/lib/format";

const DURATION_MS = 600;

/** Tokens that count up/down to their new value instead of snapping, so a settled bet or an
 * incoming transfer is something you SEE happen rather than something you'd only notice by
 * comparing numbers. The balance query already polls every 30s (see auth-context), so this fires
 * on its own whenever a market settles server-side.
 *
 * Honors `prefers-reduced-motion`: that isn't decorative-motion politeness here, a counter is
 * exactly the kind of continuous movement the setting exists to suppress -- those users get the
 * final value immediately, with the same color flash for the direction cue. */
export function AnimatedTokens({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  const [displayed, setDisplayed] = useState(value);
  const [direction, setDirection] = useState<"up" | "down" | null>(null);
  const previous = useRef(value);
  const frame = useRef<number | undefined>(undefined);

  useEffect(() => {
    const from = previous.current;
    previous.current = value;
    if (from === value) return;

    setDirection(value > from ? "up" : "down");
    const flash = window.setTimeout(() => setDirection(null), DURATION_MS + 400);

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setDisplayed(value);
      return () => window.clearTimeout(flash);
    }

    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min((now - start) / DURATION_MS, 1);
      // easeOutCubic -- fast at first, settles gently, so the final digits are readable
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayed(from + (value - from) * eased);
      if (progress < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
      window.clearTimeout(flash);
    };
  }, [value]);

  return (
    <span
      className={cn(
        "font-mono tabular-nums transition-colors duration-300",
        direction === "up" && "text-primary",
        direction === "down" && "text-destructive",
        className
      )}
    >
      {formatTokens(displayed)}
    </span>
  );
}
