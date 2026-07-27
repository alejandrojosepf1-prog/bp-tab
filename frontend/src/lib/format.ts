/** Single source of truth for rendering token amounts -- Claim plays with tokens, never real
 * money, so nothing in the UI should print a literal "$" (see app/layout.tsx's metadata
 * description and the sidebar's "Se juega con tokens" note). Always round: stakes/balances are
 * floats internally but a fractional token reads as a bug to a user, not precision. */
export function formatTokens(n: number): string {
  return `${Math.round(n).toLocaleString("es")} tokens`;
}

/** Same as `formatTokens` but with an explicit +/− sign, for net profit/loss figures where the
 * sign carries meaning (e.g. "+50 tokens" / "−20 tokens"). */
export function formatSignedTokens(n: number): string {
  const sign = n >= 0 ? "+" : "−";
  return `${sign}${formatTokens(Math.abs(n))}`;
}
