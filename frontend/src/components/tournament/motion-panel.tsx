"use client";

import { useState } from "react";
import { ChevronDown, ScrollText } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * La moción de una ronda (y su info slide) mostradas inline.
 *
 * Existe para que nadie tenga que abrir el tab en otra pestaña para saber qué se está
 * debatiendo antes de apostar. El info slide arranca colapsado porque suele ser largo — la
 * moción es lo que se lee de un vistazo; el contexto se pide sólo si hace falta.
 */
export function MotionPanel({
  motionText,
  infoSlide,
  roundName,
  className,
}: {
  motionText: string | null | undefined;
  infoSlide?: string | null;
  roundName?: string;
  className?: string;
}) {
  const [slideOpen, setSlideOpen] = useState(false);

  if (!motionText) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground",
          className
        )}
      >
        <ScrollText className="size-3.5 shrink-0" />
        La moción de {roundName ?? "esta ronda"} todavía no se publicó en el tab.
      </div>
    );
  }

  // El info slide llega como texto plano con saltos de línea (ver backend parse_motions: se
  // aplana a propósito para no meter HTML de terceros en la página).
  const slideParagraphs = (infoSlide ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-primary/25 bg-primary/[0.04]",
        className
      )}
    >
      <div className="flex gap-2.5 px-3.5 py-3">
        <ScrollText className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="text-[0.65rem] font-semibold uppercase tracking-widest text-primary/80">
            Moción{roundName ? ` · ${roundName}` : ""}
          </p>
          <p className="mt-1 text-pretty text-sm font-medium leading-relaxed text-foreground">
            {motionText}
          </p>
        </div>
      </div>

      {slideParagraphs.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setSlideOpen((open) => !open)}
            className="flex w-full items-center gap-1.5 border-t border-primary/15 px-3.5 py-2 text-left text-xs font-medium text-primary transition-colors hover:bg-primary/[0.06]"
          >
            <ChevronDown
              className={cn("size-3.5 transition-transform", slideOpen && "rotate-180")}
            />
            {slideOpen ? "Ocultar info slide" : "Ver info slide"}
          </button>
          {slideOpen && (
            <div className="flex flex-col gap-2 border-t border-primary/15 bg-background/40 px-3.5 py-3">
              {slideParagraphs.map((paragraph, i) => (
                <p
                  key={i}
                  className="text-pretty text-xs leading-relaxed text-muted-foreground"
                >
                  {paragraph}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
