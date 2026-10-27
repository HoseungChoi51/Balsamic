/** The lineage forest as hand-written SVG: rounds as columns, lanes as rows, typed edges, stage as colour. */
import { FAMILY, type Evolution } from '../api/evolution';

const COLOUR: Record<string, string> = { proposed: 'var(--ink-3)', reviewed: 'var(--info)', screening: 'var(--agent)', extended: 'var(--accent)', finalist: 'var(--good)', confirmed: 'var(--good)', stopped: 'var(--warn)' };
const DASH: Record<string, string> = { revision: '', variant: '4 3', hybrid: '1 3', inspired_by: '8 4' };

/** A label that fits a node: the housekeeper's short title, or the title cut at a word. */
function nodeText(text: string, chars: number) {
  if (text.length <= chars + 1) return text;
  const head = text.slice(0, chars);
  return (head.includes(' ') ? head.slice(0, head.lastIndexOf(' ')) : head).replace(/[\s,;:-]+$/, '') + '…';
}

const EDGE_KINDS: [keyof typeof DASH, string][] = [['revision', 'revision'], ['variant', 'variant'], ['hybrid', 'hybrid'], ['inspired_by', 'from the library']];
const STAGES = ['proposed', 'reviewed', 'screening', 'extended', 'finalist', 'stopped'];

function Legend() {
  return (
    <div className="legend row wrap" data-testid="lineage-legend">
      {EDGE_KINDS.map(([kind, name]) => <span key={kind} className="legend-item"><svg width={34} height={10} viewBox="0 0 34 10" aria-hidden="true"><path d="M1,5 L33,5" stroke="var(--ink-2)" strokeWidth="1.5" fill="none" strokeDasharray={DASH[kind]} /></svg>{name}</span>)}
      <span className="legend-gap" />
      {STAGES.map(stage => <span key={stage} className="legend-item"><svg width={12} height={12} viewBox="0 0 12 12" aria-hidden="true"><circle cx={6} cy={6} r={5} fill={COLOUR[stage]} /></svg>{stage}</span>)}
      <span className="legend-item faint">double-click opens the card</span>
    </div>
  );
}

export function LineageTree({ data, selectedId, onSelect, onOpen }: { data: Evolution; selectedId: string | null; onSelect: (id: string) => void; onOpen: (id: string) => void }) {
  if (!data.layout.length) return <div className="empty">No lineage yet.</div>;
  const colW = 230, nodeW = 156, rowH = 44, pad = 20;
  const width = pad * 2 + (data.rounds + 1) * colW, height = pad * 2 + data.layout.length * rowH;
  const pos = Object.fromEntries(data.layout.map(n => [n.id, { x: pad + n.round * colW + nodeW / 2, y: pad + n.lane * rowH + 16 }]));
  return (
    <div className="card" style={{ overflow: 'auto' }} data-testid="lineage">
      <svg width={width} height={height} role="img" aria-label="lineage">
        {Array.from({ length: data.rounds + 1 }, (_, r) => <text key={r} x={pad + r * colW + nodeW / 2} y={12} fontSize="10" fill="var(--ink-3)" textAnchor="middle">round {r}</text>)}
        {data.edges.filter(e => !e.external).map((e, i) => { const a = pos[e.from], b = pos[e.to]; if (!a || !b) return null;
          return <path key={i} d={`M${a.x + nodeW / 2},${a.y} C${a.x + nodeW / 2 + 40},${a.y} ${b.x - nodeW / 2 - 40},${b.y} ${b.x - nodeW / 2},${b.y}`} fill="none" stroke="var(--line-2)" strokeWidth="1.5" strokeDasharray={DASH[e.kind]} data-kind={e.kind} />; })}
        {data.layout.map(n => { const p = pos[n.id]; const row = data.nodes.find(r => r.id === n.id);
          return <g key={n.id} transform={`translate(${p.x - nodeW / 2},${p.y - 14})`} style={{ cursor: 'pointer' }} data-record-id={n.id} data-stage={n.stage} onClick={() => onSelect(n.id)} onDoubleClick={() => onOpen(n.id)}>
            <rect width={nodeW} height={28} rx={6} fill="var(--panel)" stroke={selectedId === n.id ? 'var(--accent)' : COLOUR[n.stage]} strokeWidth={selectedId === n.id ? 2.5 : 1.5} />
            <circle cx={12} cy={14} r={5} fill={COLOUR[n.stage]} />
            <text x={22} y={18} fontSize="11" fill="var(--ink)">{n.label ? <tspan fontWeight={600}>{n.label} </tspan> : null}{nodeText(n.short_title || n.title, n.label ? 17 : 22)}</text>
            {n.family || n.autonomous ? <text x={nodeW - 8} y={10} fontSize="8" textAnchor="end" data-testid="lineage-family">{n.family ? <tspan fill="var(--ink-3)">{FAMILY[n.family] || n.family}</tspan> : null}{n.autonomous ? <tspan fill="var(--agent)">{n.family ? ' · ' : ''}auto</tspan> : null}</text> : null}
            <title>{`${n.title}${n.family ? ` (${FAMILY[n.family] || n.family})` : ''}\n${n.stop_label || n.stage}${n.stop_reason ? ': ' + n.stop_reason : ''}${row?.best.score != null ? `\nbest ${row.best.score}` : ''}`}</title>
          </g>; })}
      </svg>
      <Legend />
    </div>
  );
}
