"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, Menu, ShieldCheck, LogOut, User as UserIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const params = useParams<{ id?: string }>();
  const { user, isAuthenticated, isAdmin, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // Hand-rolled instead of the shared DropdownMenu/@base-ui Menu primitive: that primitive's
  // click-to-open interaction doesn't toggle in this app's exact Next.js 16 / React 19 / Base UI
  // 1.6 combination (reproduced with a bare, unmodified Menu.Root/Menu.Trigger, in both dev and
  // production builds), and forcing it open via controlled `open` state crashed the tab when a
  // `Menu.Item` was composed with `next/link`'s `Link` via `render`. A plain click-outside-close
  // div sidesteps both issues for this simple "profile menu" use case.
  useEffect(() => {
    if (!userMenuOpen) return;
    function handlePointerDown(event: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setUserMenuOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [userMenuOpen]);

  const { data: tournaments } = useQuery({
    queryKey: queryKeys.tournaments,
    queryFn: api.tournaments.list,
    staleTime: 60_000,
  });

  const currentTournamentId = params?.id;

  function goToTournament(id: string | null) {
    if (id) router.push(`/tournaments/${id}`);
  }

  const isLoginPage = pathname === "/login";

  const navLinks = currentTournamentId
    ? [
        { href: `/tournaments/${currentTournamentId}`, label: "Overview" },
        { href: `/tournaments/${currentTournamentId}/teams`, label: "Equipos" },
        { href: `/tournaments/${currentTournamentId}/speakers`, label: "Speakers" },
        { href: `/tournaments/${currentTournamentId}/institutions`, label: "Instituciones" },
        { href: `/tournaments/${currentTournamentId}/rounds`, label: "Rondas" },
        { href: `/tournaments/${currentTournamentId}/break`, label: "Break" },
        { href: `/tournaments/${currentTournamentId}/bets`, label: "Apuestas" },
        { href: `/tournaments/${currentTournamentId}/leaderboard`, label: "Ranking" },
      ]
    : [];

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-backdrop-filter:bg-background/60">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4">
        <Link href="/dashboard" className="flex items-center gap-1.5 font-semibold tracking-tight">
          <span className="text-lg">BP$</span>
        </Link>

        {!isLoginPage && (
          <>
            <div className="hidden md:flex items-center gap-2 ml-2">
              <Select
                value={currentTournamentId ?? ""}
                onValueChange={goToTournament}
              >
                <SelectTrigger size="sm" className="w-[220px]">
                  <SelectValue placeholder="Seleccionar torneo" />
                </SelectTrigger>
                <SelectContent>
                  {tournaments?.map((t) => (
                    <SelectItem key={t.id} value={String(t.id)}>
                      {t.name}
                    </SelectItem>
                  ))}
                  {!tournaments?.length && (
                    <div className="px-2 py-1.5 text-sm text-muted-foreground">
                      Sin torneos
                    </div>
                  )}
                </SelectContent>
              </Select>
            </div>

            <nav className="hidden lg:flex items-center gap-1 ml-2 overflow-x-auto">
              <Link
                href="/dashboard"
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors",
                  pathname === "/dashboard" && "bg-accent text-accent-foreground"
                )}
              >
                <LayoutDashboard className="size-4" />
                Dashboard
              </Link>
              {navLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors whitespace-nowrap",
                    pathname === link.href && "bg-accent text-accent-foreground"
                  )}
                >
                  {link.label}
                </Link>
              ))}
            </nav>
          </>
        )}

        <div className="ml-auto flex items-center gap-2">
          {!isLoginPage && (
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
              <SheetTrigger
                render={<Button variant="ghost" size="icon" className="lg:hidden" />}
              >
                <Menu className="size-5" />
              </SheetTrigger>
              <SheetContent side="left" className="w-72">
                <div className="flex flex-col gap-4 p-4">
                  <Select value={currentTournamentId ?? ""} onValueChange={goToTournament}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Seleccionar torneo" />
                    </SelectTrigger>
                    <SelectContent>
                      {tournaments?.map((t) => (
                        <SelectItem key={t.id} value={String(t.id)}>
                          {t.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <nav className="flex flex-col gap-1">
                    <Link
                      href="/dashboard"
                      onClick={() => setMobileOpen(false)}
                      className="rounded-md px-2.5 py-2 text-sm font-medium hover:bg-accent"
                    >
                      Dashboard
                    </Link>
                    {navLinks.map((link) => (
                      <Link
                        key={link.href}
                        href={link.href}
                        onClick={() => setMobileOpen(false)}
                        className="rounded-md px-2.5 py-2 text-sm font-medium hover:bg-accent"
                      >
                        {link.label}
                      </Link>
                    ))}
                  </nav>
                </div>
              </SheetContent>
            </Sheet>
          )}

          {isAuthenticated ? (
            <div className="relative" ref={userMenuRef}>
              <Button
                variant="ghost"
                className="gap-2 px-2"
                aria-haspopup="menu"
                aria-expanded={userMenuOpen}
                onClick={() => setUserMenuOpen((open) => !open)}
              >
                <span className="hidden sm:inline text-sm font-medium">
                  {user?.display_name}
                </span>
                <UserIcon className="size-4" />
              </Button>
              {userMenuOpen && (
                <div
                  role="menu"
                  className="absolute right-0 top-full z-50 mt-1 w-48 rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10"
                >
                  <div className="truncate px-1.5 py-1 text-xs font-medium text-muted-foreground">
                    {user?.email}
                  </div>
                  <div className="-mx-1 my-1 h-px bg-border" />
                  <Link
                    href="/profile"
                    role="menuitem"
                    onClick={() => setUserMenuOpen(false)}
                    className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-sm hover:bg-accent hover:text-accent-foreground"
                  >
                    <UserIcon className="size-4" /> Perfil
                  </Link>
                  {isAdmin && (
                    <Link
                      href="/admin"
                      role="menuitem"
                      onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-sm hover:bg-accent hover:text-accent-foreground"
                    >
                      <ShieldCheck className="size-4" /> Admin
                    </Link>
                  )}
                  <div className="-mx-1 my-1 h-px bg-border" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setUserMenuOpen(false);
                      logout();
                      router.push("/login");
                    }}
                    className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm text-destructive hover:bg-destructive/10"
                  >
                    <LogOut className="size-4" /> Cerrar sesión
                  </button>
                </div>
              )}
            </div>
          ) : (
            !isLoginPage && (
              <Button size="sm" render={<Link href="/login" />}>
                Iniciar sesión
              </Button>
            )
          )}
        </div>
      </div>
    </header>
  );
}
