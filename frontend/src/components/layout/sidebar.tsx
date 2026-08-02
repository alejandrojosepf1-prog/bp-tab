"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  Ticket,
  UserRound,
  Settings,
  ShieldCheck,
  Trophy,
  ClipboardCheck,
  Users,
  Radar,
  LogOut,
  Menu,
  X,
  Gem,
  Landmark,
  Gift,
  GitMerge,
} from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";
import { formatTokens } from "@/lib/format";

const MAIN_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/bets", label: "Apuestas", icon: Ticket },
  { href: "/prizes", label: "Premios", icon: Gift },
  { href: "/ranking", label: "Ranking", icon: Trophy },
  { href: "/account", label: "Cuenta", icon: UserRound },
  { href: "/settings", label: "Configuración", icon: Settings },
];

const ADMIN_ITEMS = [
  { href: "/admin/markets", label: "Mercados", icon: Ticket },
  { href: "/admin/prizes", label: "Premios", icon: Gift },
  { href: "/admin/tournaments", label: "Torneos", icon: Trophy },
  { href: "/admin/results", label: "Resultados", icon: ClipboardCheck },
  { href: "/admin/users", label: "Usuarios", icon: Users },
  { href: "/admin/scraping", label: "Scraping", icon: Radar },
  { href: "/admin/finance", label: "Economía", icon: Landmark },
  { href: "/admin/circuit", label: "Instituciones", icon: GitMerge },
];

function Wordmark() {
  return (
    <Link href="/dashboard" className="flex items-center gap-2 px-2">
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Gem className="size-4.5" strokeWidth={2.4} />
      </span>
      <span className="font-heading text-lg font-bold uppercase tracking-[0.18em]">
        Claim
      </span>
    </Link>
  );
}

/** Flashea el balance cuando cambia -- verde si sube (ganó una apuesta, cobró un premio), rojo
 * si baja (apostó). `null` en el primer render y cada vez que el flash termina, así el balance
 * inicial nunca "flashea" solo por montar. */
function useBalanceFlash(balance: number | undefined) {
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prevRef = useRef(balance);

  useEffect(() => {
    if (balance === undefined || prevRef.current === undefined) {
      prevRef.current = balance;
      return;
    }
    if (balance !== prevRef.current) {
      setFlash(balance > prevRef.current ? "up" : "down");
      prevRef.current = balance;
      const timeout = setTimeout(() => setFlash(null), 900);
      return () => clearTimeout(timeout);
    }
  }, [balance]);

  return flash;
}

function NavLink({
  href,
  label,
  icon: Icon,
  active,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  active: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-primary/12 text-primary"
          : "text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-foreground"
      )}
    >
      <Icon className="size-4" />
      {label}
    </Link>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, isAdmin, logout } = useAuth();
  const balanceFlash = useBalanceFlash(user?.balance);

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <Wordmark />

      <nav className="flex flex-col gap-1">
        {MAIN_ITEMS.map((item) => (
          <NavLink
            key={item.href}
            {...item}
            active={isActive(item.href) || (item.href === "/dashboard" && pathname.startsWith("/tournaments"))}
            onNavigate={onNavigate}
          />
        ))}
      </nav>

      {isAdmin && (
        <div className="flex flex-col gap-1 rounded-xl border border-primary/20 bg-primary/4 p-2 pt-1.5">
          <span className="flex items-center gap-1.5 px-2 py-1.5 text-[0.7rem] font-semibold uppercase tracking-widest text-primary/90">
            <ShieldCheck className="size-3.5" /> Admin
          </span>
          {ADMIN_ITEMS.map((item) => (
            <NavLink
              key={item.href}
              {...item}
              active={isActive(item.href)}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      )}

      <div className="mt-auto flex flex-col gap-2">
        <p className="px-2 text-[0.65rem] leading-snug text-muted-foreground">
          Se juega con tokens. Nunca hay dinero real en juego.
        </p>
        {isAuthenticated ? (
          <div className="flex flex-col gap-2 rounded-xl border border-border bg-card/60 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{user?.display_name}</p>
                <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
              </div>
              <button
                type="button"
                title="Cerrar sesión"
                onClick={() => {
                  logout();
                  onNavigate?.();
                  router.push("/login");
                }}
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
              >
                <LogOut className="size-4" />
              </button>
            </div>
            <div
              className={cn(
                "flex items-baseline justify-between rounded-lg px-2.5 py-1.5 transition-colors duration-500",
                balanceFlash === "up" && "bg-emerald-500/20",
                balanceFlash === "down" && "bg-destructive/15",
                !balanceFlash && "bg-primary/10"
              )}
            >
              <span className="text-[0.7rem] uppercase tracking-wider text-primary/80">
                Tokens
              </span>
              <span
                className={cn(
                  "font-mono text-sm font-semibold transition-transform duration-300",
                  balanceFlash && "scale-110",
                  balanceFlash === "up" && "text-emerald-400",
                  balanceFlash === "down" && "text-destructive",
                  !balanceFlash && "text-primary"
                )}
              >
                {formatTokens(user?.balance ?? 0)}
              </span>
            </div>
          </div>
        ) : (
          <Link
            href="/login"
            onClick={onNavigate}
            className="rounded-lg bg-primary px-3 py-2 text-center text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            Iniciar sesión
          </Link>
        )}
      </div>
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  if (pathname === "/login") return null;

  return (
    <>
      {/* Escritorio: fijo a la izquierda */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 border-r border-sidebar-border bg-sidebar lg:block">
        <SidebarBody />
      </aside>

      {/* Móvil: barra superior + panel deslizable */}
      <div className="fixed inset-x-0 top-0 z-40 flex items-center justify-between border-b border-sidebar-border bg-sidebar/95 px-4 py-2.5 backdrop-blur lg:hidden">
        <Wordmark />
        <button
          type="button"
          aria-label="Abrir menú"
          onClick={() => setMobileOpen((open) => !open)}
          className="rounded-md p-2 hover:bg-sidebar-accent"
        >
          {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>
      {mobileOpen && (
        <div className="fixed inset-0 z-30 lg:hidden">
          <div
            className="absolute inset-0 bg-background/70 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-sidebar-border bg-sidebar pt-14">
            <SidebarBody onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
    </>
  );
}
