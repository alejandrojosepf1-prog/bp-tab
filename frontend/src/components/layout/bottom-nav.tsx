"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Ticket, Gift, Trophy, UserRound } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";
import { isFullBleedRoute } from "@/lib/route-zones";

/**
 * Navegación primaria en el celular. Fase 3 del rediseño broadcast -- ver
 * `Rediseno UIX 2026 - Broadcast en vivo` en el vault.
 *
 * Antes de esto, la navegación principal era un sidebar de escritorio con una barra
 * superior + panel deslizable en móvil: pensamiento desktop-first en un producto que se
 * usa en el celular DURANTE el torneo. Esto es un problema de arquitectura de la
 * información, no cosmético -- así que tiene su propio componente, no un ajuste del
 * Sidebar existente.
 *
 * Máximo 5 destinos (regla de navegación móvil): los de más frecuencia de uso durante un
 * torneo en vivo. Configuración, admin y logout se quedan en el menú superior del
 * Sidebar como secundarios -- no compiten por el pulgar.
 */
const TABS = [
  { href: "/dashboard", label: "Inicio", icon: LayoutDashboard },
  { href: "/bets", label: "Apuestas", icon: Ticket },
  { href: "/prizes", label: "Premios", icon: Gift },
  { href: "/ranking", label: "Ranking", icon: Trophy },
  { href: "/account", label: "Cuenta", icon: UserRound },
] as const;

export function BottomNav() {
  const pathname = usePathname();
  const { isAuthenticated } = useAuth();

  if (isFullBleedRoute(pathname) || !isAuthenticated) return null;

  const isActive = (href: string) =>
    pathname === href ||
    pathname.startsWith(`${href}/`) ||
    (href === "/dashboard" && pathname.startsWith("/tournaments"));

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 flex border-t border-sidebar-border bg-sidebar/95 backdrop-blur lg:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {TABS.map(({ href, label, icon: Icon }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[0.65rem] font-medium"
            aria-current={active ? "page" : undefined}
          >
            <Icon
              className={cn(
                "size-5 transition-colors",
                active ? "text-primary" : "text-sidebar-foreground/60"
              )}
              strokeWidth={active ? 2.4 : 2}
            />
            <span className={cn(active ? "text-primary" : "text-sidebar-foreground/60")}>
              {label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
