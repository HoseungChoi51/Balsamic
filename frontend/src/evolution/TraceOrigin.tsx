/** Trace origin: the trail from a record back through the command, the run, the message, the thread and the model. */
import { useRead } from '../api/queries';
import type { Hop } from '../api/evolution';
import { Failed, Loading, Pill, when } from '../primitives/ui';
import { formatHash } from '../router/routes';
import { track } from '../telemetry/events';
import { useEffect } from 'react';

export function TraceOrigin({ recordId, thread, onClose }: { recordId: string; thread: string | null; onClose: () => void }) {
  const trail = useRead<{ record_id: string; trail: Hop[] }>(['provenance', recordId], `/api/v1/records/${recordId}/provenance`, { staleTime: 30000 });
  useEffect(() => { track('trace.open', { kind: recordId.split('_')[0] }); }, [recordId]);
  useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  return (
    <aside className="drawer" data-testid="trace-origin" aria-label="Trace origin">
      <div className="row" style={{ marginBottom: 10 }}><h2 className="grow">Where it came from</h2><button className="btn quiet small" onClick={onClose}>Close</button></div>
      {trail.isPending ? <Loading /> : trail.error ? <Failed error={trail.error} /> : (
        <ol className="col" style={{ paddingLeft: 18 }}>
          {trail.data.trail.map((hop, i) => (
            <li key={i} className="small" data-testid="hop">
              <Pill>{hop.hop.replaceAll('_', ' ')}</Pill> <strong>{hop.record.title}</strong> <span className="muted">· {hop.via}</span>
              {hop.record.created_at ? <span className="faint"> · {when(hop.record.created_at)}</span> : null}
              {hop.record.status ? <span className="faint"> · {hop.record.status}</span> : null}
              {hop.page ? <> · <a href={formatHash({ page: hop.page.replace(/^#/, '').split('/')[0] as 'monitor', sub: hop.page.replace(/^#/, '').split('/')[1] || null, id: hop.page.replace(/^#/, '').split('/')[2] || null }, thread)}>open</a></> : null}
              {hop.record.content_hash ? <div className="mono faint" style={{ fontSize: 10 }}>{hop.record.content_hash.slice(0, 16)}…</div> : null}
            </li>))}
        </ol>)}
    </aside>
  );
}
