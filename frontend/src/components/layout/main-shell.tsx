"use client";

import { usePathname } from "next/navigation";
import { isFullBleedRoute } from "@/lib/route-zones";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";

/** The `claim-glow` gradient and sidebar-width padding are arcade-zone-only -- full-bleed
 * routes (login, activate, access-request, the archive zone) render without either, since
 * Sidebar already returns null for them and dragging that dark glow under a light editorial
 * page would look broken.
 *
 * `pb-16` on mobile reserves room for BottomNav (fixed, ~64px + safe-area) so it doesn't
 * cover the last bit of scrollable content -- only when it's actually rendering (logged
 * in), same condition BottomNav itself checks. */
export function MainShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated } = useAuth();

  if (isFullBleedRoute(pathname)) {
    return <main className="flex min-w-0 flex-1 flex-col">{children}</main>;
  }

  return (
    <main
      className={cn(
        "claim-glow flex min-w-0 flex-1 flex-col pt-14 lg:pt-0 lg:pl-60",
        isAuthenticated && "pb-16 lg:pb-0"
      )}
    >
      {children}
    </main>
  );
}
