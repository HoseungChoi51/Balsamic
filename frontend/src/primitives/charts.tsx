/** Hand-written SVG: a score curve over evaluations or seconds. */
export function Curve({ points, height = 120, label }: { points: { x: number; y: number }[]; height?: number; label?: string }) {
  if (!points.length) return <div className="faint small">No points yet.</div>;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1, y0 = Math.min(...ys), y1 = Math.max(...ys);
  const w = 600, h = height, pad = 6;
  const sx = (x: number) => pad + (x1 === x0 ? 0 : (x - x0) / (x1 - x0)) * (w - 2 * pad);
  const sy = (y: number) => h - pad - (y1 === y0 ? .5 : (y - y0) / (y1 - y0)) * (h - 2 * pad);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ');
  return (
    <svg className="curve" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={label || 'curve'}>
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      <text x={pad} y={12} fontSize="10" fill="var(--ink-3)">{y1.toPrecision(4)}</text>
      <text x={pad} y={h - 2} fontSize="10" fill="var(--ink-3)">{y0.toPrecision(4)}</text>
    </svg>
  );
}
