/** Ctrl+K: pages, threads and messages of this campaign; arrows and Enter navigate. */
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useThreads } from '../api/queries';
import { PAGES, RAIL, formatHash, navigate, type Route } from '../router/routes';
import { track } from '../telemetry/events';

interface Hit { kind: 'page' | 'thread' | 'message'; label: string; detail?: string; hash: string }

export function SearchPalette({ campaignId, route, onClose }: { campaignId: string; route: Route; onClose: () => void }) {
  const [q, setQ] = useState('');
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const threads = useThreads(campaignId);
  const search = useQuery({ queryKey: ['thread-search', campaignId, q], enabled: q.trim().length >= 2, staleTime: 5000,
    queryFn: () => api<{ threads: { thread_id: string; thread_title: string }[]; messages: { thread_id: string; thread_title: string; message_id: string; excerpt: string; role: string }[] }>(`/api/v1/campaigns/${campaignId}/threads?q=${encodeURIComponent(q.trim())}`) });
  useEffect(() => { input.current?.focus(); track('search.open', {}); }, []);
  const words = q.trim().toLowerCase();
  const hits: Hit[] = [
    ...RAIL.filter(p => !words || PAGES[p].title.toLowerCase().includes(words) || p.includes(words)).map(p => ({ kind: 'page' as const, label: PAGES[p].title, detail: PAGES[p].description.slice(0, 80), hash: formatHash({ page: p }, route.thread) })),
    ...(threads.data?.threads || []).filter(t => !words || t.title.toLowerCase().includes(words)).map(t => ({ kind: 'thread' as const, label: t.title, detail: `${t.status} · ${t.message_count} turns`, hash: formatHash({ page: route.page, sub: route.sub }, t.id) })),
    ...(search.data?.messages || []).map(m => ({ kind: 'message' as const, label: m.excerpt, detail: `${m.role} in ${m.thread_title}`, hash: formatHash({ page: route.page, sub: route.sub, sel: m.message_id }, m.thread_id) })),
  ].slice(0, 30);
  const go = (hit: Hit) => { navigate(hit.hash); onClose(); };
  return (
    <div className="palette-backdrop" onClick={onClose} data-testid="search-palette">
      <div className="palette" onClick={e => e.stopPropagation()}>
        <input ref={input} value={q} onChange={e => { setQ(e.target.value); setIndex(0); }} placeholder="Pages, threads, messages…" aria-label="Search"
          onKeyDown={e => { if (e.key === 'ArrowDown') { e.preventDefault(); setIndex(i => Math.min(hits.length - 1, i + 1)); } else if (e.key === 'ArrowUp') { e.preventDefault(); setIndex(i => Math.max(0, i - 1)); } else if (e.key === 'Enter' && hits[index]) go(hits[index]); else if (e.key === 'Escape') onClose(); }} />
        <ul>{hits.map((hit, i) => <li key={hit.kind + hit.hash + i} className={i === index ? 'active' : ''} onMouseEnter={() => setIndex(i)} onClick={() => go(hit)} data-testid="palette-hit"><span className="pill">{hit.kind}</span> <span>{hit.label}</span>{hit.detail ? <span className="faint small"> · {hit.detail}</span> : null}</li>)}
          {!hits.length ? <li className="faint">Nothing matches.</li> : null}</ul>
        <p className="why">↑↓ to move, Enter to open, Esc to close. g then a letter jumps to a page (n note, h hypotheses, e experiments, v evolution, f files, i inbox, m monitor, l library, b branches).</p>
      </div>
    </div>
  );
}
