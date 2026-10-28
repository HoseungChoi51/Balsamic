/** The lab's code packages (roadmap L2): each library a coding workspace built, with its versions in its own repository, the
 *  methods and problems each version has, and the campaigns that use each method. A page of the lab, the same in every campaign;
 *  "Library" is the strategy library. */
import { useState } from 'react';
import type { PageProps } from '../shell/StagePanel';
import { useRead } from '../api/queries';
import { Empty, Failed, Loading, Pill, Section, when } from '../primitives/ui';

interface Summary { name: string; package: string; kind?: 'problem' | 'method'; latest: string; versions: number; methods: string[]; problems: string[];
  depends_on?: string[]; used_by?: string[]; updated_at: string }
interface Version { id: string; version: string; tag: string; commit: string; parent_version: string | null; methods: string[]; problems: string[];
  methods_added: string[]; methods_removed: string[]; problems_added: string[]; problems_removed: string[]; created_at: string;
  depends_on?: string[] | null; moved?: { package: string; methods: string[] } | null;
  source: { campaign_id?: string; workspace_id?: string; install_id?: string; commit?: string; imported?: string } }
interface Item { id: string; since: string; in_latest: boolean; campaigns: { id: string; name: string }[] }
interface Detail { name: string; package: string; latest: string; versions: Version[]; methods: Item[]; problems: Item[] }

function changes(v: Version) {
  const parts = [
    v.methods_added.length ? `adds ${v.methods_added.join(', ')}` : '', v.methods_removed.length ? `removes ${v.methods_removed.join(', ')}` : '',
    v.problems_added.length ? `adds problem ${v.problems_added.join(', ')}` : '', v.problems_removed.length ? `removes problem ${v.problems_removed.join(', ')}` : '',
    // A split (roadmap L6): the methods it moved into a method package, which this version depends on.
    v.moved ? `moves ${v.moved.methods.join(', ')} to ${v.moved.package}` : ''];
  return parts.filter(Boolean).join(' · ') || 'no new method or problem';
}

function Items({ items, what }: { items: Item[]; what: string }) {
  if (!items.length) return null;
  return <table className="table small" data-testid={`package-${what}`}><thead><tr><th>{what === 'methods' ? 'Method' : 'Problem'}</th><th>Since</th><th>Used by</th></tr></thead>
    <tbody>{items.map(i => <tr key={i.id} data-testid={`package-${what}-row`}><td><code>{i.id}</code>{i.in_latest ? null : <> <Pill>removed</Pill></>}</td><td>{i.since}</td>
      <td>{i.campaigns.length ? i.campaigns.map(c => c.name).join(', ') : <span className="faint">no campaign</span>}</td></tr>)}</tbody></table>;
}

function Package({ name }: { name: string }) {
  const detail = useRead<Detail>(['packages', name], `/api/libraries/${encodeURIComponent(name)}`);
  if (detail.isLoading) return <Loading />;
  if (detail.error) return <Failed error={detail.error} />;
  const d = detail.data!;
  return <div data-testid="package-detail">
    <Items items={d.methods} what="methods" />
    <Items items={d.problems} what="problems" />
    <h4>Versions</h4>
    <ol className="small" data-testid="package-versions">{d.versions.map(v => <li key={v.id} data-testid="package-version">
      <strong>{v.version}</strong> <code>{v.commit.slice(0, 7)}</code> · {changes(v)} · {v.source.imported ? `imported from ${v.source.imported}`
        : `from workspace ${v.source.workspace_id || '?'} of campaign ${v.source.campaign_id || '?'}`} · {when(v.created_at)}</li>)}</ol>
  </div>;
}

export default function PackagesPage(_: PageProps) {
  const list = useRead<{ libraries: Summary[] }>(['packages'], '/api/libraries');
  const [open, setOpen] = useState<string | null>(null);
  return <Section title="Packages">
    <p className="small faint">The code packages coding workspaces built, for every campaign of the lab. Each install is a new version; a version keeps
      every method and problem a campaign uses, and a workspace builds on the latest one.</p>
    {list.isLoading ? <Loading /> : list.error ? <Failed error={list.error} /> : !list.data?.libraries.length ? <Empty>No package yet: a coding workspace's first install makes one.</Empty> :
      list.data.libraries.map(p => <article key={p.name} className="card" data-testid="package" data-record-id={p.name}>
        <div className="row wrap"><strong className="grow">{p.package}</strong><Pill>{p.latest}</Pill>
          <span className="small faint">{p.versions} version{p.versions === 1 ? '' : 's'} · {p.methods.length} method{p.methods.length === 1 ? '' : 's'}
            {p.problems.length ? ` · problems ${p.problems.join(', ')}` : ''} · libraries/{p.name}</span>
          {p.kind === 'method' ? <Pill title="A method package: methods more than one problem's package needs (roadmap L6)">method package</Pill> : null}
          <button className="btn small" onClick={() => setOpen(open === p.name ? null : p.name)} data-testid="package-open">{open === p.name ? 'Hide' : 'Versions and methods'}</button></div>
        {p.depends_on?.length ? <div className="small" data-testid="package-depends">Depends on {p.depends_on.join(', ')}</div> : null}
        {p.used_by?.length ? <div className="small" data-testid="package-used-by">Used by {p.used_by.join(', ')}</div> : null}
        {open === p.name ? <Package name={p.name} /> : null}
      </article>)}
  </Section>;
}
