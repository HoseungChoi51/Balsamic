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

/** A horizontal meter: segments drawn in order over a track that stands for `total`; a marker for a cap or a forecast. */
export function Meter({ total, segments, markers = [], height = 10, label }: { total: number | null | undefined; segments: { value: number | null | undefined; tone: string; title?: string }[]; markers?: { value: number | null | undefined; tone: string; title?: string }[]; height?: number; label?: string }) {
  const max = Math.max(Number(total) || 0, ...segments.map(s => Number(s.value) || 0), ...markers.map(m => Number(m.value) || 0)) || 1;
  const w = 600;
  const x = (v: number | null | undefined) => Math.max(0, Math.min(w, (Number(v) || 0) / max * w));
  const sorted = segments.filter(s => s.value != null).slice().sort((a, b) => Number(b.value) - Number(a.value));
  return (
    <svg className="meter" viewBox={`0 0 ${w} ${height + 4}`} preserveAspectRatio="none" role="img" aria-label={label || 'meter'} style={{ height: height + 4 }}>
      <rect x={0} y={2} width={w} height={height} rx={height / 2} fill="var(--panel-2)" stroke="var(--line)" vectorEffect="non-scaling-stroke" />
      {sorted.map((s, i) => <rect key={i} x={0} y={2} width={x(s.value)} height={height} rx={height / 2} fill={`var(--${s.tone})`} opacity={0.9}><title>{s.title}</title></rect>)}
      {markers.filter(m => m.value != null).map((m, i) => <rect key={'m' + i} x={x(m.value) - 1.5} y={0} width={3} height={height + 4} fill={`var(--${m.tone})`}><title>{m.title}</title></rect>)}
    </svg>
  );
}

/** A ring showing a share of a whole, with the value in the middle. */
export function Ring({ percent, tone = 'accent', size = 64, text, label }: { percent: number | null | undefined; tone?: string; size?: number; text?: string; label?: string }) {
  const r = size / 2 - 5, c = 2 * Math.PI * r;
  const share = percent == null || Number.isNaN(Number(percent)) ? null : Math.max(0, Math.min(100, Number(percent)));
  return (
    <svg className="ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label || 'ring'}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--panel-2)" strokeWidth={6} />
      {share != null ? <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`var(--${tone})`} strokeWidth={6} strokeLinecap="round" strokeDasharray={`${c * share / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} /> : null}
      <text x={size / 2} y={size / 2 + 4} fontSize={size / 5} textAnchor="middle" fill="var(--ink)">{text ?? (share == null ? '?' : `${Math.round(share)}%`)}</text>
    </svg>
  );
}

/** Worker slots as blocks: busy, queued beyond the limit, idle. */
export function Slots({ busy, limit, queued = 0, label }: { busy: number | null | undefined; limit: number | null | undefined; queued?: number | null | undefined; label?: string }) {
  const n = Math.max(0, Number(limit) || 0), b = Math.max(0, Math.min(n, Number(busy) || 0)), q = Math.max(0, Number(queued) || 0);
  if (!n && !q) return <span className="faint small">no workers</span>;
  const size = 14, gap = 4, w = (n + q) * (size + gap);
  return (
    <svg className="slots" width={w} height={size} viewBox={`0 0 ${w} ${size}`} role="img" aria-label={label || 'worker slots'}>
      {Array.from({ length: n }, (_, i) => <rect key={i} x={i * (size + gap)} y={0} width={size} height={size} rx={3} fill={i < b ? 'var(--accent)' : 'var(--panel-2)'} stroke={i < b ? 'var(--accent)' : 'var(--line-2)'}><title>{i < b ? 'running' : 'idle'}</title></rect>)}
      {Array.from({ length: q }, (_, i) => <rect key={'q' + i} x={(n + i) * (size + gap)} y={0} width={size} height={size} rx={3} fill="var(--warn-soft)" stroke="var(--warn)" strokeDasharray="2 2"><title>queued</title></rect>)}
    </svg>
  );
}

/** Horizontal bars for a ranked list; the longest fills the width. */
export function Bars({ rows, format, tone = 'info', label }: { rows: { name: string; value: number; title?: string }[]; format?: (v: number) => string; tone?: string; label?: string }) {
  if (!rows.length) return <div className="faint small">Nothing yet.</div>;
  const max = Math.max(...rows.map(r => r.value)) || 1;
  return (
    <div className="bars" role="img" aria-label={label || 'bars'}>
      {rows.map((r, i) => <div key={i} className="bar-row" title={r.title}><span className="bar-name">{r.name}</span>
        <svg viewBox="0 0 300 10" preserveAspectRatio="none" className="bar"><rect x={0} y={0} width={Math.max(1.5, r.value / max * 300)} height={10} rx={3} fill={`var(--${tone})`} /></svg>
        <span className="bar-value mono small">{format ? format(r.value) : String(r.value)}</span></div>)}
    </div>
  );
}

/** Vertical bars over time buckets. */
export function Columns({ points, height = 60, label, format }: { points: { x: string; y: number }[]; height?: number; label?: string; format?: (v: number) => string }) {
  if (!points.length) return <div className="faint small">Nothing yet.</div>;
  const max = Math.max(...points.map(p => p.y)) || 1, w = 600, gap = 2, bw = Math.max(2, w / points.length - gap);
  return (
    <svg className="columns" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" role="img" aria-label={label || 'columns'} style={{ height }}>
      {points.map((p, i) => <rect key={i} x={i * (bw + gap)} y={height - p.y / max * (height - 4)} width={bw} height={p.y / max * (height - 4)} fill="var(--info)"><title>{`${p.x}: ${format ? format(p.y) : p.y}`}</title></rect>)}
    </svg>
  );
}
