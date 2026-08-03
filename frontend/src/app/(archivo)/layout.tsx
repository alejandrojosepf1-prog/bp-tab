import Link from "next/link";
import { Gem } from "lucide-react";

const NAV_ITEMS = [
  { href: "/circuito", label: "Circuito" },
  { href: "/mociones", label: "Mociones" },
];

/** Zona archivo (CNADE 2026 Roadmap Pieza 5) -- modo claro, editorial, sin Sidebar ni
 * claim-glow (ver globals.css `.archivo` y src/lib/route-zones.ts). Header propio en vez del
 * Sidebar de la zona de apuestas: esto es una publicación pública, no un panel de control. */
export default function ArchivoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="archivo min-h-screen bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <Link href="/circuito" className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Gem className="size-4.5" strokeWidth={2.4} />
            </span>
            <span className="font-heading text-lg font-bold tracking-tight">
              Claim <span className="font-normal text-muted-foreground">/ Archivo</span>
            </span>
          </Link>
          <nav className="flex items-center gap-6">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="text-sm font-medium text-foreground/80 transition-colors hover:text-primary"
              >
                {item.label}
              </Link>
            ))}
            <Link
              href="/dashboard"
              className="rounded-lg bg-primary px-3.5 py-1.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
            >
              Ir a apostar
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
    </div>
  );
}
