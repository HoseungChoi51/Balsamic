/** The lineage forest as hand-written SVG: rounds as columns, lanes as rows, typed edges, stage as colour. */
import type { Evolution } from '../api/evolution';

const COLOUR: Record<string, string> = { proposed: 'var(--ink-3)', reviewed: 'var(--info)', screening: 'var(--agent)', extended: 'var(--accent)', finalist: 'var(--good)', confirmed: 'var(--good)', stopped: 'var(--warn)' };
const DASH: Record<string, string> = { revision: '', variant: '4 3', hybrid: '1 3', inspired_by: '8 4' };

export function LineageTree({ data, selectedId, onSelect, onOpen }: { data: Evolution; selectedId: string | null; onSelect: (id: string) => void; onOpen: (id: string) => void }) {
  if (!data.layout.length) return <div className="empty">No lineage yet.</div>;
  const colW = 190, rowH = 44, pad = 20;
  const width = pad * 2 + (data.rounds + 1) * colW, height = pad * 2 + data.layout.length * rowH;
  const pos = Object.fromEntries(data.layout.map(n => [n.id, { x: pad + n.round * colW + 70, y: pad + n.lane * rowH + 16 }]));
  return (
    <div className="card" style={{ overflow: 'auto' }} data-testid="lineage">
      <svg width={width} height={height} role="img" aria-label="lineage">
        {Array.from({ length: data.rounds + 1 }, (_, r) => <text key={r} x={pad + r * colW + 70} y={12} fontSize="10" fill="var(--ink-3)" textAnchor="middle">round {r}</text>)}
        {data.edges.filter(e => !e.external).map((e, i) => { const a = pos[e.from], b = pos[e.to]; if (!a || !b) return null;
          return <path key={i} d={`M${a.x + 60},${a.y} C${a.x + 100},${a.y} ${b.x - 100},${b.y} ${b.x - 60},${b.y}`} fill="none" stroke="var(--line-2)" strokeWidth="1.5" strokeDasharray={DASH[e.kind]} data-kind={e.kind} />; })}
        {data.layout.map(n => { const p = pos[n.id]; const row = data.nodes.find(r => r.id === n.id);
          return <g key={n.id} transform={`translate(${p.x - 60},${p.y - 14})`} style={{ cursor: 'pointer' }} data-record-id={n.id} data-stage={n.stage} onClick={() => onSelect(n.id)} onDoubleClick={() => onOpen(n.id)}>
            <rect width={120} height={28} rx={6} fill="var(--panel)" stroke={selectedId === n.id ? 'var(--accent)' : COLOUR[n.stage]} strokeWidth={selectedId === n.id ? 2.5 : 1.5} />
            <circle cx={12} cy={14} r={5} fill={COLOUR[n.stage]} />
            <text x={22} y={18} fontSize="11" fill="var(--ink)">{(n.label ? n.label + ' ' : '') + n.title.slice(0, 14)}</text>
            {n.autonomous ? <text x={112} y={10} fontSize="8" fill="var(--agent)" textAnchor="end">auto</text> : null}
            <title>{`${n.title}\n${n.stage}${n.stop_reason ? ': ' + n.stop_reason : ''}${row?.best.score != null ? `\nbest ${row.best.score}` : ''}`}</title>
          </g>; })}
      </svg>
      <p className="why">Solid: revision · dashed: variant · dotted: hybrid · long dash: inspired by a library entry. Double-click opens the card.</p>
    </div>
  );
}
