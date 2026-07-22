"use client";

import { usePathname } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { RequireAdmin } from "@/components/auth/require-admin";

const TITLES: Record<string, string> = {
  "/admin/markets": "Mercados de apuestas",
  "/admin/tournaments": "Torneos",
  "/admin/results": "Resultados manuales",
  "/admin/users": "Usuarios",
  "/admin/scraping": "Scraping",
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const title = TITLES[pathname] ?? "Panel de administración";

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-5 px-4 py-8">
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-widest text-primary">
          <ShieldCheck className="size-3.5" /> Admin
        </p>
        <h1 className="font-heading text-2xl font-bold tracking-tight">{title}</h1>
      </div>
      <RequireAdmin>{children}</RequireAdmin>
    </div>
  );
}
