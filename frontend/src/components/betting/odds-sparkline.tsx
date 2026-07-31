import type { OddsHistoryPoint } from "@/lib/api/types";

/** Tiny inline trend line for one option's odds history -- no charting library, just a hand-rolled
 * SVG polyline, since this is the only place the app needs one. Green (--primary, same token the
 * leaderboard uses for positive net points) when the price has drifted up since the window
 * started, red (--destructive, same "loss" token) when it's drifted down. */
export function OddsSparkline({ points }: { points: OddsHistoryPoint[] }) {
  if (points.length < 2) {
    return <span className="text-[0.65rem] text-muted-foreground">—</span>;
  }
  const width = 56;
  const height = 20;
  const values = points.map((p) => p.odds);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = width / (values.length - 1);
  const coords = values.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const trendUp = values[values.length - 1] >= values[0];
  const stroke = trendUp ? "var(--primary)" : "var(--destructive)";
  const lastY = height - ((values[values.length - 1] - min) / range) * height;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="inline-block overflow-visible align-middle"
      aria-hidden="true"
    >
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={width} cy={lastY} r={1.8} fill={stroke} />
    </svg>
  );
}
