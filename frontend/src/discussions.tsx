import { lazy, Suspense, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, errorText, when } from './api';
import type { Json, State } from './api';
import { Badge, Empty, ErrorNotice } from './ui';
import { TextContent } from './textContent';
import { currentStep, roleName, useAgentLive } from './agentLive';
import type { LiveAgent } from './agentLive';
import './discussions.css';

// The graph and its drawing library load only when the graph is opened.
const DiscussionGraph = lazy(() => import('./discussionGraph'));
const graphMode = () => location.hash === '#hypotheses/rounds/graph';

export type Verdict = { artifact_id: string; created_at: string; hypothesis_id?: string; title?: string; verdict: string; rationale?: string; required_changes: string[]; suggested_tests: string[] };
export type SavedDocument = { id: string; kind: string; title?: string; created_at: string };
export type Turn = {
  run_id: string; created_at: string; status: string; kind: 'assignment' | 'follow_up' | 'notice'; asked?: string | null; delivered_while_working: boolean;
  summary?: string | null; reply: string; error?: string | null;
  response?: { run_id: string; created_at: string; status: string; summary?: string | null; text: string } | null;
};
export type Assistant = { agent_id: string; role: string; model?: string; status: string; created_at: string; assignment: string; turns: Turn[]; verdicts: Verdict[]; documents: SavedDocument[] };
/** A round: the assistants that the lead agent or the discussion moderator (its owner) asked in one turn, and what set that turn off. */
export type Round = { number: number; started_at: string; owner?: string; trigger: { kind: 'request' | 'lead' | 'continued' | 'unknown'; text?: string; round?: number | null }; active: boolean; assistants: Assistant[]; owner_documents: SavedDocument[] };
export type Revision = { id: string; title?: string; status?: string; parent_ids?: string[]; created_in_round?: number | null; created_by?: string | null;
  verdicts: { verdict: string; round?: number | null }[] };
export type Proposal = { id: string; title?: string; status?: string; reviewed?: boolean; revisions: Revision[] };
export type Discussions = { rounds: Round[]; earlier_rounds: number; proposals: Proposal[]; unreviewed_proposals: number };

export const verdictTone: Record<string, string> = { test: 'green', revise: 'amber', reject: 'red' };
function plain(text?: string | null): string { return (text || '').replace(/\s+/g, ' ').trim(); }

/** A long text shown as its first lines; the whole text opens in place. */
export function Excerpt({ text, lines = 3, more = 'Show full text' }: { text?: string | null; lines?: number; more?: string }) {
  const [open, setOpen] = useState(false);
  if (!plain(text)) return null;
  const long = plain(text).length > lines * 110;
  return <div className="discussion-excerpt">
    {open ? <TextContent text={text} /> : <p style={{ WebkitLineClamp: lines }}>{plain(text)}</p>}
    {long && <button type="button" className="text-button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Show less' : more}</button>}
  </div>;
}

/** A saved value as an outline: texts as written, lists as lists, named parts under their names. */
function Outline({ value }: { value: unknown }): ReactNode {
  if (value == null || value === '') return null;
  if (typeof value === 'string') return <TextContent text={value} />;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  if (Array.isArray(value)) return <ul>{value.map((item, index) => <li key={index}><Outline value={item} /></li>)}</ul>;
  return <dl>{Object.entries(value as Json).map(([name, item]) => <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd><Outline value={item} /></dd></div>)}</dl>;
}

export function SavedDocuments({ campaignId, documents }: { campaignId: string; documents: SavedDocument[] }) {
  const [open, setOpen] = useState<Record<string, Json | string>>({});
  async function toggle(id: string) {
    if (open[id] !== undefined) { setOpen(({ [id]: _closed, ...rest }) => rest); return; }
    try { const entry = await api<Json>(`/api/campaigns/${encodeURIComponent(campaignId)}/agents/records/${encodeURIComponent(id)}`); setOpen(old => ({ ...old, [id]: entry.data?.content ?? '' })); }
    catch (failure) { setOpen(old => ({ ...old, [id]: `Could not open this document: ${errorText(failure)}` })); }
  }
  if (!documents.length) return null;
  return <div className="discussion-documents">{documents.map(doc => <div key={doc.id}>
    <button type="button" className="text-button" aria-expanded={open[doc.id] !== undefined} onClick={() => void toggle(doc.id)}>{open[doc.id] !== undefined ? '▾' : '▸'} Saved {doc.kind}: {doc.title || doc.id}</button>
    {open[doc.id] !== undefined && <div className="discussion-outline"><Outline value={open[doc.id]} /></div>}
  </div>)}</div>;
}

export function Verdicts({ verdicts }: { verdicts: Verdict[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!verdicts.length) return null;
  return <ul className="discussion-verdicts" aria-label="Verdicts">{verdicts.map(item => <li key={item.artifact_id}>
    <button type="button" aria-expanded={open === item.artifact_id} onClick={() => setOpen(open === item.artifact_id ? null : item.artifact_id)}>
      <Badge tone={verdictTone[item.verdict] || ''}>{item.verdict}</Badge><span>{item.title || item.hypothesis_id}</span>
    </button>
    {open !== item.artifact_id && item.required_changes.length > 0 && <p className="discussion-required">Asked for: {plain(item.required_changes[0])}{item.required_changes.length > 1 && ` (+${item.required_changes.length - 1} more)`}</p>}
    {open === item.artifact_id && <div className="discussion-outline">
      <TextContent text={item.rationale} />
      {item.required_changes.length > 0 && <><strong>Required changes</strong><ul>{item.required_changes.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
      {item.suggested_tests.length > 0 && <><strong>Suggested tests</strong><ul>{item.suggested_tests.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
    </div>}
  </li>)}</ul>;
}

function AssistantEntry({ campaignId, assistant, live, owner }: { campaignId: string; assistant: Assistant; live?: LiveAgent; owner: string }) {
  const working = ['queued', 'running'].includes(assistant.status);
  // Who asked: the lead agent, or the discussion moderator.
  const asker = owner === 'lead' ? 'Lead' : 'Moderator', askerName = roleName(owner);
  return <article className="discussion-assistant" aria-label={roleName(assistant.role)}>
    <header><strong>{roleName(assistant.role)}</strong>{assistant.model && <span>{assistant.model}</span>}
      {working ? <Badge tone="green"><i className="pulse" />at work{currentStep(live) && `: ${currentStep(live)}`}</Badge> : assistant.status !== 'completed' && <Badge tone={assistant.status === 'failed' ? 'red' : 'amber'}>{assistant.status}</Badge>}</header>
    <div className="discussion-line"><span>{asker} asked</span><Excerpt text={assistant.assignment} lines={2} more="Show the full assignment" /></div>
    {assistant.turns.map(turn => <div className="discussion-turn" key={turn.run_id}>
      {turn.kind === 'follow_up' && <div className="discussion-line"><span>{asker} added</span><Excerpt text={turn.asked} lines={2} />
        {turn.delivered_while_working && <small>Delivered while the assistant was working; its answer is part of that turn.</small>}</div>}
      {(turn.summary || turn.reply || turn.error) && <div className="discussion-line reply"><span>Answered<time>{when(turn.created_at)}</time></span>
        {turn.summary ? <Excerpt text={turn.summary} lines={4} more="Show the whole summary" /> : turn.reply ? <Excerpt text={turn.reply} lines={4} /> : <p className="discussion-error">{turn.error}</p>}
        {turn.summary && turn.reply && <details><summary>Full reply</summary><TextContent text={turn.reply} /></details>}</div>}
    </div>)}
    <Verdicts verdicts={assistant.verdicts} />
    <SavedDocuments campaignId={campaignId} documents={assistant.documents} />
    {assistant.turns.filter(turn => turn.response && (turn.response.summary || turn.response.text)).map(turn => <div className="discussion-line lead" key={turn.run_id}><span>{askerName}<time>{when(turn.response!.created_at)}</time></span>
      {turn.response!.summary ? <Excerpt text={turn.response!.summary} lines={3} more="Show the whole summary" /> : <Excerpt text={turn.response!.text} lines={3} />}
      {turn.response!.summary && turn.response!.text && <details><summary>What the {askerName.toLowerCase()} wrote</summary><TextContent text={turn.response!.text} /></details>}</div>)}
  </article>;
}

/** What the moderator (earlier, the lead agent) asked its assistants, what they answered and decided, and what was done with it. */
export function DiscussionsView({ state }: { state: State }) {
  const campaignId = state.campaign?.id;
  const [data, setData] = useState<Discussions | null>(null), [error, setError] = useState('');
  const team: Json[] = state.agent_runtime?.agents || [];
  // Reloaded when an assistant is created or changes state, and when a reply or a review is saved.
  const stamp = `${state.event_cursor}:${team.map(agent => agent.status).join(',')}`;
  useEffect(() => {
    if (!campaignId) { setData(null); return; }
    let current = true;
    api<Discussions>(`/api/v1/campaigns/${encodeURIComponent(campaignId)}/discussions`)
      .then(result => { if (current) { setData(result); setError(''); } }).catch(failure => { if (current) setError(errorText(failure)); });
    return () => { current = false; };
  }, [campaignId, stamp]);
  const live = useAgentLive(campaignId, Boolean(data?.rounds.some(round => round.active)));
  const reviewed = (data?.proposals || []).filter(proposal => proposal.reviewed !== false);
  const loaded = Boolean(data);
  const [graph, setGraph] = useState(graphMode);
  useEffect(() => { const change = () => setGraph(graphMode()); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  useEffect(() => {
    const show = () => { const target = location.hash.startsWith('#hypotheses/rounds/') ? location.hash.split('/')[2] : ''; if (target) document.getElementById(target)?.scrollIntoView({ block: 'start' }); };
    show(); window.addEventListener('hashchange', show); return () => window.removeEventListener('hashchange', show);
  }, [loaded]);
  return <section aria-label="Review rounds">
    <div className="page-heading"><div><span className="eyebrow">Review rounds</span><h1>What the agents said to each other.</h1>
      <p>Each round is the assistants that the discussion moderator, or earlier the lead agent, asked in one turn: the assignment, every answer in the assistant's own summary, the verdicts, and what was done next. The texts are the agents' own, as saved.</p></div></div>
    <div className="segment-tabs discussion-mode" role="tablist" aria-label="How the rounds are shown">
      {([['list', 'List'], ['graph', 'Graph']] as const).map(([mode, name]) => <button key={mode} type="button" role="tab" aria-selected={graph === (mode === 'graph')}
        className={graph === (mode === 'graph') ? 'selected' : ''} onClick={() => { location.hash = mode === 'graph' ? 'hypotheses/rounds/graph' : 'hypotheses/rounds'; }}>{name}</button>)}
    </div>
    <ErrorNotice text={error} />
    {graph ? (data && campaignId ? <Suspense fallback={<p className="help-text">Drawing the graph…</p>}><DiscussionGraph data={data} campaignId={campaignId} live={live} /></Suspense>
      : !error && <p className="help-text">Reading the rounds…</p>) : <>
    {data && !data.rounds.length && <section className="panel"><Empty icon="chat" title="No discussion yet">When the discussion moderator or the lead agent asks specialists or reviewers for their view, the exchange appears here.</Empty></section>}
    {data && reviewed.length > 0 && <section className="panel discussion-proposals"><div className="panel-heading"><div><span className="eyebrow">Reviews</span><h2>How each proposal fared</h2></div></div>
      <div className="markdown-table"><table className="data-table"><thead><tr><th>Proposal</th><th>Verdicts, in order</th><th>Now</th></tr></thead>
        <tbody>{reviewed.map(proposal => <tr key={proposal.id}><td>{proposal.title}</td>
          <td><span className="verdict-chain">{proposal.revisions.filter(revision => revision.verdicts.length).flatMap((revision, index) => [
            ...(index > 0 ? [<i key={`${revision.id}-revised`} title="The proposal was revised before this review">revised</i>] : []),
            ...revision.verdicts.map((item, position) => <a key={`${revision.id}-${position}`} href={item.round ? `#hypotheses/rounds/round-${item.round}` : undefined} title={item.round ? `Round ${item.round}` : undefined}><Badge tone={verdictTone[item.verdict] || ''}>{item.verdict}</Badge></a>)])}</span></td>
          <td><Badge>{proposal.status || 'proposed'}</Badge></td></tr>)}</tbody></table></div>
      {data.unreviewed_proposals > 0 && <p className="help-text discussion-footnote">{data.unreviewed_proposals} {data.unreviewed_proposals === 1 ? 'proposal has' : 'proposals have'} no review. All proposals are in the <a href="#hypotheses">Proposals</a> tab.</p>}
    </section>}
    {data?.rounds.map(round => <section className="panel discussion-round" id={`round-${round.number}`} key={round.number} aria-label={`Round ${round.number}`}>
      <div className="panel-heading"><div><span className="eyebrow">{when(round.started_at)}</span><h2>Round {round.number} · {[...new Set(round.assistants.map(assistant => roleName(assistant.role)))].join(', ')}</h2></div>
        {round.active && <Badge tone="green"><i className="pulse" />in progress</Badge>}</div>
      <div className="discussion-trigger">{round.trigger.kind === 'request' ? <><span>{round.owner && round.owner !== 'lead' ? `Your message to the ${roleName(round.owner).toLowerCase()}` : 'Your message'}</span><Excerpt text={round.trigger.text} lines={2} /></>
        : round.trigger.kind === 'lead' ? <><span>The lead agent asked</span><Excerpt text={round.trigger.text} lines={2} /></>
        : round.trigger.kind === 'continued' && round.trigger.round ? <><span>Started by</span><p>the {roleName(round.owner || 'lead').toLowerCase()}, after the answers of <a href={`#hypotheses/rounds/round-${round.trigger.round}`}>round {round.trigger.round}</a></p></>
        : <><span>Started by</span><p>the {roleName(round.owner || 'lead').toLowerCase()}, while work for a request was running</p></>}</div>
      {round.assistants.map(assistant => <AssistantEntry key={assistant.agent_id} campaignId={campaignId!} assistant={assistant} live={live.find(agent => agent.agent_id === assistant.agent_id)} owner={round.owner || 'lead'} />)}
      {(round.owner_documents || []).length > 0 && <div className="discussion-lead-documents"><span>The {roleName(round.owner || 'lead').toLowerCase()} saved</span><SavedDocuments campaignId={campaignId!} documents={round.owner_documents} /></div>}
    </section>)}
    {data && data.earlier_rounds > 0 && <p className="help-text">{data.earlier_rounds} earlier rounds are in the agent log.</p>}</>}
  </section>;
}
