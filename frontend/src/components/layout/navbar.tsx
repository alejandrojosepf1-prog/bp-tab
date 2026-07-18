"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, Menu, ShieldCheck, LogOut, User as UserIcon } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="ghost" className="gap-2 px-2" />}>
                <span className="hidden sm:inline text-sm font-medium">
                  {user?.display_name}
                </span>
                <UserIcon className="size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuLabel className="truncate">{user?.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem render={<Link href="/profile" />}>
                  <UserIcon className="size-4" /> Perfil
                </DropdownMenuItem>
                {isAdmin && (
                  <DropdownMenuItem render={<Link href="/admin" />}>
                    <ShieldCheck className="size-4" /> Admin
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() => {
                    logout();
                    router.push("/login");
                  }}
                >
                  <LogOut className="size-4" /> Cerrar sesión
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
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
