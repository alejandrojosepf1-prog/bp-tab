/**
 * Routes that render full-bleed, without the arcade Sidebar or its `claim-glow`/padding
 * reservation on the shared root `<main>` -- shared between Sidebar and MainShell so the two
 * never drift apart on what counts as "no chrome".
 */
export function isFullBleedRoute(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname === "/activate" ||
    pathname.startsWith("/access-request") ||
    pathname === "/circuito" ||
    pathname.startsWith("/circuito/") ||
    pathname === "/torneos" ||
    pathname.startsWith("/torneos/") ||
    pathname === "/mociones"
  );
}
