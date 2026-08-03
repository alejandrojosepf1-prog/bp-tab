"use client";

import { usePathname } from "next/navigation";
import { isFullBleedRoute } from "@/lib/route-zones";

/** The `claim-glow` gradient and sidebar-width padding are arcade-zone-only -- full-bleed
 * routes (login, activate, access-request, the archive zone) render without either, since
 * Sidebar already returns null for them and dragging that dark glow under a light editorial
 * page would look broken. */
export function MainShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (isFullBleedRoute(pathname)) {
    return <main className="flex min-w-0 flex-1 flex-col">{children}</main>;
  }

  return (
    <main className="claim-glow flex min-w-0 flex-1 flex-col pt-14 lg:pt-0 lg:pl-60">
      {children}
    </main>
  );
}
