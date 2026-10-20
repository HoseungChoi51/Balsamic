/** The problem note: sections with math, annotations by tier (Define, Explain, Challenge, Visualize), revisions, Adopt, the charter it becomes. */
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useRead, useSummary } from '../api/queries';
import { api } from '../api/client';
import { send } from '../commands/bus';
import { CharterPanel } from './CharterPanel';
import { Markdown } from '../chat/render/Markdown';
import { VisualFrame } from '../chat/render/VisualFrame';
import { Empty, Failed, Kv, Loading, Pill, Section, when } from '../primitives/ui';
import { formatHash } from '../router/routes';
import { track } from '../telemetry/events';
import { useSelection } from '../stores/selection';

interface SectionData { text: string; items: string[]; latex: string[] }
interface Revision { id: string; revision: number; sections: Record<string, SectionData>; glossary: { term: string; definition: string }[]; title: string; author: string; reason: string; created_at: string }
interface Annotation { id: string; anchor: { revision: number; section: string; item_index?: number | null; start: number; end: number; quote: string }; kind: string; question: string; tier: string;
  escalated_from_tier?: string | null; escalation_reason?: string; answer: { text: string; answered_by: string; cost_usd?: number | null } | null; proposed_edit: Record<string, unknown> | null; visual_id?: string | null; status: string; created_at: string }
interface NoteView { note: { id: string; title: string; current_revision: number; adopted_revision: number | null; charter_id: string | null; import_id: string | null; status: string }; revision: Revision | null;
  revisions: { id: string; revision: number; author: string; reason: string; created_at: string }[]; annotations: Annotation[]; charter: { import_id?: string; status?: string; error?: string | null; charter_id?: string | null; reply?: string | null; charter?: Record<string, unknown> } | null; sections: string[]; titles: Record<string, string> }

const KINDS = [['define', 'Define'], ['explain', 'Explain'], ['challenge', 'Challenge'], ['visualize', 'Visualize']] as const;

export default function ProblemNotePage({ campaignId, route, threadId }: PageProps) {
  const view = useRead<NoteView>(['note', campaignId], `/api/v1/campaigns/${campaignId}/problem-note`, { refetchInterval: 8000 });
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const selection = useSelection();
  const [menu, setMenu] = useState<{ section: string; quote: string; start: number; end: number } | null>(null);
  const [question, setQuestion] = useState('');
  const [kind, setKind] = useState<typeof KINDS[number][0]>('explain');
  const [error, setError] = useState<string | null>(null);
  const [shownRevision, setShownRevision] = useState<number | null>(null);
  const other = useRead<NoteView>(['note', campaignId, shownRevision], shownRevision ? `/api/v1/problem-notes/note_${campaignId}?revision=${shownRevision}` : null);
  useEffect(() => { setShownRevision(null); }, [campaignId]);
  if (view.isPending) return <Loading what="Loading the problem note" />;
  if (view.error) return <Failed error={view.error} />;
  const data = view.data;
  const revision = (shownRevision && other.data?.revision) || data.revision;
  const sub = route.sub;
  const version = summary.data?.campaign.version;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['note', campaignId] });

  const capture = (section: string, event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest('[data-testid="annotation-menu"], [data-testid="annotation"], button, input')) return;
    const sel = window.getSelection();
    const text = sel?.toString().trim() || '';
    if (!text) return;
    setMenu({ section, quote: text.slice(0, 500), start: 0, end: text.length });
  };
  const ask = async () => {
    if (!menu || !revision || !question.trim() || version === undefined) return;
    setError(null);
    const anchor = { revision: revision.revision, section: menu.section, start: menu.start, end: menu.end, quote: menu.quote };
    try {
      if (kind === 'define' || kind === 'explain') {
        const answered = await api<Annotation>(`/api/v1/problem-notes/${data.note.id}/ask`, { method: 'POST', body: JSON.stringify({ note_id: data.note.id, anchor, question: question.trim(), kind }) });
        track('note.ask', { tier: answered.tier, escalated: !!answered.escalated_from_tier });
      } else {
        const receipt = await send({ operation: 'note.ask', campaignId, expectedRevision: version, payload: { note_id: data.note.id, anchor, question: question.trim(), kind }, origin: { thread_id: threadId } });
        track('note.ask', { tier: String(receipt.outcome.tier), escalated: false });
      }
      setMenu(null); setQuestion(''); await refresh();
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  const resolve = async (annotation: Annotation, choice: 'accept' | 'reject' | 'resolve') => {
    if (version === undefined) return;
    setError(null);
    try { await send({ operation: 'note.resolve', campaignId, expectedRevision: version, payload: { annotation_id: annotation.id, choice } }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  const adopt = async () => {
    if (version === undefined || !data.revision) return;
    setError(null);
    try { await send({ operation: 'problem_note.adopt', campaignId, expectedRevision: version, payload: { note_id: data.note.id, revision: data.revision.revision }, origin: { thread_id: threadId } }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  const tabs = [['', 'Note'], ['charter', 'Charter'], ['revisions', 'Revisions']] as const;
  const open = data.annotations.filter(a => a.status !== 'rejected');
  return (
    <div className="col">
      <div className="stage-head"><h1>{data.note.title}</h1><Pill tone={data.note.status === 'confirmed' ? 'clear' : data.note.status === 'adopted' ? 'agent' : ''}>{data.note.status}</Pill>
        <span className="muted small">revision {revision?.revision ?? 0}{shownRevision ? ' (viewing an older one)' : ''}</span>
        {data.note.status === 'drafting' && data.revision ? <button className="btn primary small" onClick={adopt} data-testid="adopt" title="Hand the note to the formulator, which writes the charter you then confirm">Adopt</button> : null}</div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'note', sub: key || null }, route.thread)} className={(sub || '') === key ? 'active' : ''}>{label}</a>)}</nav>
      {error ? <div className="pill bad">{error}</div> : null}
      {!sub ? <>
        {!revision ? <Empty>No note yet. Describe the problem to the lead in the conversation, or type /note.</Empty> : data.sections.map(name => {
          const section = revision.sections[name];
          const anns = open.filter(a => a.anchor.section === name);
          return (
            <section key={name} className="card" data-testid={`section-${name}`} onMouseUp={e => capture(name, e)}>
              <div className="row"><h2 className="grow">{data.titles[name]}</h2>{anns.length ? <Pill>{anns.length} notes</Pill> : null}</div>
              {section?.text ? <Markdown text={section.text} thread={route.thread} /> : <p className="faint small">Not written yet.</p>}
              {section?.items?.length ? <ul>{section.items.map((item, i) => <li key={i}><Markdown text={item} thread={route.thread} className="md inline" /></li>)}</ul> : null}
              {section?.latex?.map((formula, i) => <Markdown key={i} text={'$$' + formula + '$$'} thread={route.thread} />)}
              {menu?.section === name ? <div className="card" data-testid="annotation-menu"><div className="row wrap"><span className="small faint">“{menu.quote.slice(0, 80)}”</span>
                {KINDS.map(([k, label]) => <button key={k} className={'btn small' + (kind === k ? ' primary' : '')} onClick={() => setKind(k)}>{label}</button>)}</div>
                <div className="row" style={{ marginTop: 6 }}><input className="grow" placeholder={kind === 'define' ? 'What is …?' : kind === 'visualize' ? 'What should the lead draw?' : 'Your question'} value={question} onChange={e => setQuestion(e.target.value)} data-testid="annotation-question" />
                  <button className="btn primary small" onClick={ask} disabled={!question.trim()}>Ask</button><button className="btn quiet small" onClick={() => setMenu(null)}>cancel</button></div>
                <p className="why">Define and Explain answer here from the glossary or one cheap model call; Challenge and Visualize take a turn of the lead and come back as proposed edits.</p></div> : null}
              {anns.map(a => <AnnotationCard key={a.id} annotation={a} campaignId={campaignId} selected={selection.id === a.id} thread={route.thread} onResolve={resolve} />)}
            </section>);
        })}
        {revision?.glossary?.length ? <Section title="Glossary"><Kv rows={revision.glossary.map(g => [g.term, g.definition])} /></Section> : null}
      </> : null}
      {sub === 'charter' ? <CharterTab data={data} campaignId={campaignId} version={version} onChanged={refresh} /> : null}
      {sub === 'revisions' ? <Section title="Revisions">{data.revisions.slice().reverse().map(r => <div key={r.id} className="row small" style={{ padding: '3px 0' }}>
        <button className={'btn small' + ((shownRevision || data.note.current_revision) === r.revision ? ' primary' : '')} onClick={() => setShownRevision(r.revision === data.note.current_revision ? null : r.revision)}>r{r.revision}</button>
        <Pill tone={r.author === 'lead' ? 'agent' : 'you'}>{r.author}</Pill><span className="grow">{r.reason || 'no reason recorded'}</span><span className="faint">{when(r.created_at)}</span></div>)}</Section> : null}
    </div>
  );
}

function AnnotationCard({ annotation: a, campaignId, selected, thread, onResolve }: { annotation: Annotation; campaignId: string; selected: boolean; thread: string | null; onResolve: (a: Annotation, c: 'accept' | 'reject' | 'resolve') => void }) {
  const visual = useRead<{ data: { content: { html: string }; title: string } } | Record<string, unknown>>(['artifact', a.visual_id], a.visual_id ? `/api/v1/campaigns/${campaignId}/agents/records/${a.visual_id}` : null);
  const html = (visual.data as { data?: { content?: { html?: string } } } | undefined)?.data?.content?.html;
  return (
    <article className={'card' + (selected ? ' selected' : '')} data-testid="annotation" data-record-id={a.id}>
      <div className="row"><Pill tone="you">{a.kind}</Pill><Pill title={a.escalated_from_tier ? `escalated from ${a.escalated_from_tier}: ${a.escalation_reason || ''}` : 'tier'}>{a.tier}{a.escalated_from_tier ? ` ← ${a.escalated_from_tier}` : ''}</Pill>
        <span className="grow small">“{a.anchor.quote}” — {a.question}</span><Pill>{a.status}</Pill></div>
      {a.answer ? <div className="small" style={{ marginTop: 4 }}><Markdown text={a.answer.text} thread={thread} /> <span className="faint">by {a.answer.answered_by}{a.answer.cost_usd ? `, $${a.answer.cost_usd.toFixed(3)}` : ''}</span></div>
        : a.status === 'open' ? <p className="small faint">{a.tier === 'lead' || a.tier === 'visual' ? 'Waiting for the lead\'s turn.' : 'Not answered.'}</p> : null}
      {html ? <VisualFrame html={html} title={a.question} thread={thread} /> : null}
      {a.proposed_edit ? <div className="card" data-testid="proposed-edit"><h4>Proposed edit</h4><pre>{JSON.stringify(a.proposed_edit, null, 1).slice(0, 2000)}</pre>
        {a.status === 'answered' ? <div className="row"><button className="btn primary small" onClick={() => onResolve(a, 'accept')}>Accept into the note</button><button className="btn small" onClick={() => onResolve(a, 'reject')}>Reject</button></div> : null}</div> : null}
      {a.status === 'answered' && !a.proposed_edit ? <button className="btn quiet small" onClick={() => onResolve(a, 'resolve')}>Done</button> : null}
    </article>
  );
}

function CharterTab({ data, campaignId, version, onChanged }: { data: NoteView; campaignId: string; version?: number; onChanged: () => unknown }) {
  const charterId = data.charter?.charter_id || data.note.charter_id;
  if (data.note.status === 'drafting' && !charterId) return <Empty>Adopt the note first: the formulator writes the charter from it, and you confirm the charter here.</Empty>;
  if (!charterId) return <div className="card"><Pill tone="agent">formulator {data.charter?.status || 'starting'}</Pill> {data.charter?.error ? <span className="pill bad">{data.charter.error}</span> : <span className="small muted">The formulator is writing the charter from the adopted note.</span>}</div>;
  return <CharterPanel charterId={charterId} campaignId={campaignId} version={version} onChanged={onChanged} />;
}
