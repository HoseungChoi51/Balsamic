/** Files: assets and findings, report drafts, the notebook (findings in order), the sources read. */
import type { PageProps } from '../shell/StagePanel';
import { useFiles } from '../api/queries';
import { Empty, Failed, Loading, Pill, Section, when } from '../primitives/ui';
import { formatHash } from '../router/routes';

export default function FilesPage({ campaignId, route }: PageProps) {
  const files = useFiles(campaignId);
  const sub = route.sub || 'assets';
  if (files.isPending) return <Loading what="Loading files" />;
  if (files.error) return <Failed error={files.error} />;
  const data = files.data;
  const tabs = [['assets', 'Assets'], ['reports', 'Reports'], ['notebook', 'Notebook'], ['sources', 'Sources']] as const;
  return (
    <div className="col">
      <div className="stage-head"><h1>Files</h1></div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'files', sub: key }, route.thread)} className={sub === key ? 'active' : ''}>{label}</a>)}</nav>
      {sub === 'assets' ? <Section title={`Recorded findings and assets (${data.findings.length + data.assets.length})`}>
        {data.findings.length || data.assets.length ? <>
          {data.findings.map(f => <div key={String(f.id)} className={'card' + (route.id === f.id ? ' selected' : '')} data-record-id={String(f.id)}><div className="row"><Pill>{String(f.kind)}</Pill><strong className="grow">{String(f.title || f.claim || f.id)}</strong><span className="faint small">{when(f.created_at)}</span></div><p className="small">{String(f.content || f.summary || '')}</p></div>)}
          {data.assets.map(a => <div key={String(a.id)} className="card"><div className="row"><Pill>{String(a.kind)}</Pill><strong className="grow">{String(a.title)}</strong><Pill>{String(a.availability)}</Pill></div></div>)}
        </> : <Empty>No finding has been recorded yet. The lead records findings when you ask it to.</Empty>}
      </Section> : null}
      {sub === 'reports' ? <Section title="Reports">
        {data.report_jobs.length ? data.report_jobs.map(j => <div key={String(j.id)} className="card row"><strong className="grow">{String(j.title || j.id)}</strong><Pill>{String(j.status)}</Pill>{j.report_id ? <a href={`/reports/${j.report_id}`} target="_blank" rel="noreferrer">open draft</a> : null}</div>) : null}
        {data.reports.length ? data.reports.map(r => <div key={String(r.id)} className="card row"><strong className="grow">{String(r.title || r.id)}</strong><a href={`/reports/${r.id}`} target="_blank" rel="noreferrer">open</a></div>) : null}
        {!data.reports.length && !data.report_jobs.length ? <Empty>No report yet. Ask the lead to write one when the evidence is in.</Empty> : null}
      </Section> : null}
      {sub === 'notebook' ? <Section title="Notebook">
        {data.findings.length || data.artifacts.length ? [...data.findings, ...data.artifacts].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at))).map(f => <div key={String(f.id)} className="card"><div className="row"><Pill>{String(f.kind)}</Pill><span className="faint small">{when(f.created_at)}</span></div><p className="small">{String(f.title || f.summary || f.content || f.id)}</p></div>) : <Empty>The notebook fills with findings and the agents' saved analyses.</Empty>}
      </Section> : null}
      {sub === 'sources' ? <Section title={`Sources (${data.sources.length})`}>
        {data.sources.length ? data.sources.map(s => <div key={String(s.id)} className="card"><strong>{String(s.title)}</strong> <a href={String(s.url)} target="_blank" rel="noreferrer" className="small">{String(s.url)}</a><p className="small muted">{String(s.excerpt || '')}</p></div>) : <Empty>No source has been read yet.</Empty>}
      </Section> : null}
    </div>
  );
}
