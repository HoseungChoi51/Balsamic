import type { ReactNode } from 'react';

export function Pill({ tone = '', children, title }: { tone?: string; children: ReactNode; title?: string }) {
  return <span className={'pill ' + tone} title={title}>{children}</span>;
}
/** A control that cannot be used says why, next to itself, instead of vanishing. */
export function Disabled({ why, children }: { why: string; children: ReactNode }) {
  return <span className="row" title={why}><span style={{ opacity: .55, pointerEvents: 'none' }}>{children}</span><span className="why">{why}</span></span>;
}
export function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div>; }
export function Loading({ what = 'Loading' }: { what?: string }) { return <div className="faint small" role="status">{what}…</div>; }
export function Failed({ error }: { error: unknown }) { return <div className="pill bad" role="alert">Could not load: {String((error as Error)?.message || error)}</div>; }
export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return <section className="card"><div className="row" style={{ marginBottom: 6 }}><h2 className="grow">{title}</h2>{right}</div>{children}</section>;
}
export function Kv({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return <dl className="kv">{rows.map(([k, v], i) => <div key={typeof k === 'string' ? k : i} style={{ display: 'contents' }}><dt>{k}</dt><dd>{v ?? <span className="faint">unknown</span>}</dd></div>)}</dl>;
}
/** Honest numbers: unknown is not zero. */
export function num(value: unknown, digits = 1, unit = ''): ReactNode {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return <span className="faint">unknown</span>;
  const n = Number(value);
  return (Math.abs(n) >= 1000 ? Math.round(n).toLocaleString() : n.toFixed(digits)) + unit;
}
export function duration(seconds: unknown): ReactNode {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return <span className="faint">unknown</span>;
  const s = Number(seconds);
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${(s / 60).toFixed(1)} min`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} d`;
}
export function when(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return date.toLocaleString();
}
/** Status words a researcher can trust: stopped is not failed; unknown is said. */
export function statusTone(status: string | undefined) {
  if (!status) return '';
  if (['failed', 'error'].includes(status)) return 'bad';
  if (['running', 'queued', 'submitted'].includes(status)) return 'agent';
  if (['completed', 'confirmed', 'finalist', 'ready'].includes(status)) return 'clear';
  if (['waiting', 'pending', 'paused'].includes(status)) return 'attention';
  return '';
}
