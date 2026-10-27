/** What waits for the researcher: approvals and choices, issues, the lead's questions. Resolving is a command of your own. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useInbox, useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { Empty, Failed, Loading, Pill, Section, duration, when } from '../primitives/ui';
import type { ComputeNotice, ComputeThresholds, Decision, Issue, Question } from '../api/types';
import { formatHash } from '../router/routes';
import { ExtensionDialog, isExtensionDialog } from '../chat/ExtensionDialog';
import { Composer } from '../chat/Composer';
import { Markdown } from '../chat/render/Markdown';
import { acknowledge } from '../shell/InboxNotice';
import { PlanCard } from '../experiments/PlanCard';

const NEW = <Pill tone="attention" title="You have not acknowledged this yet">new</Pill>;

export default function InboxPage({ campaignId, route }: PageProps) {
  const inbox = useInbox(campaignId);
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const version = summary.data?.campaign.version;
  const after = () => queryClient.invalidateQueries({ queryKey: ['inbox', campaignId] });
  if (inbox.isPending) return <Loading what="Loading the inbox" />;
  if (inbox.error) return <Failed error={inbox.error} />;
  const { decisions, issues, questions, resolved } = inbox.data;
  const closed = inbox.data.closed_by_lead || [];
  const notices = inbox.data.notices || [];
  const unseen = inbox.data.unacknowledged || [];
  const fresh = new Set(unseen.map(item => item.id));
  return (
    <div className="col">
      <div className="stage-head"><h1>Inbox</h1><span className="muted small">{decisions.length + issues.length + questions.length} waiting for you</span>
        {unseen.length && campaignId ? <button className="btn small" onClick={() => void acknowledge(campaignId, unseen, after)} data-testid="mark-all-seen">Mark all as seen</button> : null}</div>
      <Section title={`Decisions (${decisions.length})`}>
        {decisions.length ? decisions.map(d => <DecisionCard key={d.id} decision={d} version={version} campaignId={campaignId} selected={route.id === d.id} onDone={after} isNew={fresh.has(d.id)} thread={route.thread} />) : <Empty>No approval or choice is waiting.</Empty>}
      </Section>
      <Section title={`Issues (${issues.length})`}>
        {issues.length ? issues.map(i => <IssueCard key={i.id} issue={i} version={version} campaignId={campaignId} onDone={after} isNew={fresh.has(i.id)} thread={route.thread} />) : <Empty>No operational issue is open.</Empty>}
      </Section>
      <Section title={`Questions from the lead (${questions.length})`}>
        {questions.length ? questions.map(q => <QuestionCard key={q.id} question={q} version={version} campaignId={campaignId} threadId={route.thread} onDone={after} isNew={fresh.has(q.id)} />) : <Empty>The lead has no open question.</Empty>}
      </Section>
      {closed.length ? <Section title={`Closed by the lead (${closed.length})`}>
        <p className="why">Issues the lead found no longer hold, with its reason. Reopen one if you disagree.</p>
        {closed.slice().reverse().map(i => <ClosedIssue key={i.id} issue={i} version={version} campaignId={campaignId} onDone={after} isNew={fresh.has(i.id)} thread={route.thread} />)}</Section> : null}
      {notices.length ? <Section title={`Started with a notice (${notices.length})`}>
        <Thresholds thresholds={inbox.data.thresholds} thread={route.thread} />
        {notices.slice().reverse().map(n => <NoticeRow key={n.id} notice={n} isNew={fresh.has(n.id)} thread={route.thread} />)}</Section> : null}
      {resolved.length ? <Section title="Recently resolved">{resolved.slice(-10).reverse().map(d => <div key={d.id} className="row small"><span className="grow">{d.title}</span><Pill>{String(d.choice ?? d.status)}</Pill><span className="faint">{when(d.resolved_at)}</span></div>)}</Section> : null}
    </div>
  );
}

function DecisionCard({ decision, version, campaignId, selected, onDone, isNew, thread }: { decision: Decision; version?: number; campaignId: string; selected: boolean; onDone: () => unknown; isNew: boolean; thread: string | null }) {
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const choose = async (choice: string) => {
    if (version === undefined) return;
    setError(null);
    try {
      await send({ operation: 'decision.resolve', campaignId, expectedRevision: version, payload: { decision_id: decision.id, choice, comment, expected_resolution_revision: decision.resolution_revision || 0 } });
      await onDone();
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  const blocked = new Set(decision.freshness?.blocked_choice_ids || []);
  return (
    <article className={'card' + (selected ? ' selected' : '')} data-testid="decision" data-record-id={decision.id}>
      <div className="row"><strong className="grow">{decision.title}</strong>{isNew ? NEW : null}{decision.requested_by ? <Pill tone="agent">asked by the {decision.requested_by}</Pill> : null}<span className="faint small">{when(decision.created_at)}</span></div>
      {decision.proposal ? <Markdown text={decision.proposal} thread={thread} /> : null}
      {decision.rationale && decision.rationale !== decision.proposal ? <Markdown text={decision.rationale} thread={thread} className="md muted small" /> : null}
      {decision.plan ? <PlanCard plan={decision.plan} /> : null}
      {decision.freshness?.reason ? <p className="why">{decision.freshness.reason}</p> : null}
      <textarea placeholder="A note with your choice (optional)" value={comment} onChange={e => setComment(e.target.value)} style={{ width: '100%', minHeight: 40 }} />
      <div className="row wrap" style={{ marginTop: 6 }}>
        {decision.options.map(option => (
          <button key={option.id} className={'btn' + (option.id === decision.recommendation ? ' primary' : '')} disabled={decision.status !== 'pending' || blocked.has(option.id)} title={option.description} onClick={() => choose(option.id)}>{option.label}</button>
        ))}
        {decision.status === 'executing' ? <Pill tone="agent">applying your choice…</Pill> : null}
      </div>
      {error ? <div className="pill bad" style={{ marginTop: 6 }}>{error}</div> : null}
    </article>
  );
}

function IssueCard({ issue, version, campaignId, onDone, isNew, thread }: { issue: Issue; version?: number; campaignId: string; onDone: () => unknown; isNew: boolean; thread: string | null }) {
  const [error, setError] = useState<string | null>(null);
  const resolve = async (choice: 'resolved' | 'deferred' | 'action', action?: string) => {
    if (version === undefined) return;
    try { await send({ operation: 'issue.resolve', campaignId, expectedRevision: version, payload: { issue_id: issue.id, choice, ...(action ? { action } : {}), comment: '', expected_revision: issue.revision } }); await onDone(); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  const actions = issue.actions || [];
  return (
    <article className="card" data-testid="issue">
      <div className="row"><Pill tone="attention">{issue.code.replaceAll('_', ' ')}</Pill>{isNew ? NEW : null}<span className="faint small">{when(issue.created_at)}</span>{issue.affected ? <span className="mono small faint">{issue.affected}</span> : null}</div>
      <Markdown text={issue.message} thread={thread} />
      <div className="row wrap">
        {actions.map((item, i) => <button key={item.id} className={`btn small${i === 0 ? ' primary' : ''}`} title={item.description} data-testid="issue-action" onClick={() => resolve('action', item.id)}>{item.label}</button>)}
        <button className="btn small" title="Records that you dealt with it; it changes nothing by itself" onClick={() => resolve('resolved')}>Mark as handled</button>
        <button className="btn small" onClick={() => resolve('deferred')}>Defer</button></div>
      {actions.length ? <div className="faint small">{actions.map(item => `${item.label}: ${item.description}`).join(' ')}</div> : null}
      {error ? <div className="pill bad">{error}</div> : null}
    </article>
  );
}

/** The researcher's two thresholds, said where their effect shows; they change them on Monitor, Resources. */
function Thresholds({ thresholds, thread }: { thresholds?: ComputeThresholds; thread: string | null }) {
  if (!thresholds) return null;
  return (
    <p className="why" data-testid="compute-thresholds">Agents start work of up to {duration(thresholds.gate_seconds)} without waiting for you; whatever is longer than {duration(thresholds.notice_seconds)} is listed here.
      Longer than {duration(thresholds.gate_seconds)}, and any coding workspace, waits for your go-ahead. <a href={formatHash({ page: 'monitor', sub: 'resources' }, thread)}>Change the thresholds</a></p>
  );
}

function NoticeRow({ notice, isNew, thread }: { notice: ComputeNotice; isNew: boolean; thread: string | null }) {
  const trial = notice.subjects.find(id => id.startsWith('trial_'));
  return (
    <div className="row small" data-testid="compute-notice">
      {isNew ? NEW : null}
      <span className="grow">{notice.title}
        {trial ? <> · <a href={formatHash({ page: 'experiments', id: trial, sel: trial }, thread)} className="mono">{trial}</a></> : null}</span>
      <span className="faint">{when(notice.created_at)}</span>
    </div>
  );
}

function ClosedIssue({ issue, version, campaignId, onDone, isNew, thread }: { issue: Issue; version?: number; campaignId: string; onDone: () => unknown; isNew: boolean; thread: string | null }) {
  const [error, setError] = useState<string | null>(null);
  const reopen = async () => {
    if (version === undefined) return;
    try { await send({ operation: 'issue.reopen', campaignId, expectedRevision: version, payload: { issue_id: issue.id } }); await onDone(); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <details className="card" data-testid="closed-issue">
      <summary className="row small"><Pill>{issue.code.replaceAll('_', ' ')}</Pill>{isNew ? NEW : null}<span className="grow">{issue.comment}</span><span className="faint">{when(issue.resolved_at)}</span></summary>
      <Markdown text={issue.message} thread={thread} className="md small" />
      <div className="row"><button className="btn small" onClick={reopen} data-testid="reopen-issue">Reopen</button>{issue.affected ? <span className="mono small faint">{issue.affected}</span> : null}</div>
      {error ? <div className="pill bad">{error}</div> : null}
    </details>
  );
}

function QuestionCard({ question, version, campaignId, threadId, onDone, isNew }: { question: Question; version?: number; campaignId: string; threadId: string | null; onDone: () => unknown; isNew: boolean }) {
  if (isExtensionDialog(question)) return <ExtensionDialog question={question} campaignId={campaignId} version={version} who="An agent" onDone={onDone} />;
  return <AnswerCard question={question} version={version} campaignId={campaignId} threadId={threadId} onDone={onDone} isNew={isNew} />;
}

function AnswerCard({ question, version, campaignId, threadId, onDone, isNew }: { question: Question; version?: number; campaignId: string; threadId: string | null; onDone: () => unknown; isNew: boolean }) {
  const answer = async (text: string) => {
    if (version === undefined) throw new Error('The campaign is still loading');
    await send({ operation: 'agent.message', campaignId, expectedRevision: version, payload: { message: text, question_id: question.id, thread_id: threadId }, origin: { thread_id: threadId } });
    await onDone();
  };
  return (
    <article className="card" data-testid="question">
      <div className="row"><Pill tone="agent">the lead asks</Pill>{isNew ? NEW : null}<span className="faint small">{when(question.created_at)}</span></div>
      <Markdown text={question.question} thread={threadId} />
      {question.suggestion ? <div className="small" data-testid="question-suggestion"><strong>The lead suggests:</strong> <Markdown text={String(question.suggestion)} thread={threadId} className="md inline" /></div> : null}
      {(question.options as string[] | undefined)?.length ? <div className="row wrap">{(question.options as string[]).map((option, i) =>
        <button key={option} className={`btn small${i === 0 ? ' primary' : ''}`} data-testid="question-option" onClick={() => void answer(option)}>{option}</button>)}</div> : null}
      <Composer onSend={answer} placeholder="Your answer goes to the lead as a message" testId="answer-composer" />
    </article>
  );
}
