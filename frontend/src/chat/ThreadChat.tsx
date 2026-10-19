/** The conversation with the lead in one thread: saved turns, the live turn as it streams, and the composer. */
import { useEffect, useMemo, useReducer, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useHypotheses, useMessages, useSummary, useThreads } from '../api/queries';
import { send } from '../commands/bus';
import { initial, reduce } from './stream';
import { Turn } from './Turn';
import { LiveTurn } from './LiveTurn';
import { Composer } from './Composer';
import { Failed, Loading, Pill } from '../primitives/ui';
import { track } from '../telemetry/events';

export function ThreadChat({ campaignId, threadId }: { campaignId: string; threadId: string }) {
  const queryClient = useQueryClient();
  const summary = useSummary(campaignId);
  const threads = useThreads(campaignId);
  const messages = useMessages(threadId);
  const hypotheses = useHypotheses(campaignId);
  const [stream, dispatch] = useReducer(reduce, initial);
  const scroller = useRef<HTMLDivElement>(null);
  const aliases = useMemo(() => Object.fromEntries((hypotheses.data?.aliases || []).map(a => [a.label, a.record_id])), [hypotheses.data]);

  useEffect(() => {
    const source = new EventSource(`/api/v1/threads/${encodeURIComponent(threadId)}/stream`);
    source.onmessage = event => {
      let parsed: Record<string, unknown>; try { parsed = JSON.parse(event.data); } catch { return; }
      dispatch(parsed);
      if (parsed.type === 'MESSAGES_SNAPSHOT' || parsed.type === 'RUN_FINISHED' || parsed.type === 'RUN_ERROR') void queryClient.invalidateQueries({ queryKey: ['messages', threadId] });
    };
    return () => source.close();
  }, [threadId, queryClient]);
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [messages.data?.messages.length, stream.live.text, stream.live.steps.length]);

  const campaign = summary.data?.campaign;
  const thread = threads.data?.threads.find(t => t.id === threadId);
  const lead = threads.data?.lead;
  const busy = stream.live.status === 'running' || !!thread?.busy;

  const sendMessage = async (text: string) => {
    if (!campaign) throw new Error('The campaign is still loading');
    const base = { campaignId, expectedRevision: campaign.version, origin: { thread_id: threadId } };
    if (!lead) {
      // The lead is the only chat backend: the first message starts the team, then goes to it.
      await send({ ...base, operation: 'agent.activate', payload: {} });
      await queryClient.invalidateQueries({ queryKey: ['threads', campaignId] });
    }
    await send({ ...base, operation: 'agent.message', payload: { message: text, thread_id: threadId } });
    track('chat.send', { length: text.length });
    await queryClient.invalidateQueries({ queryKey: ['messages', threadId] });
  };

  return (
    <div className="chat" data-testid="thread-chat">
      <div className="thread-head">
        <strong className="grow">{thread?.title || campaign?.name || 'Conversation'}</strong>
        {thread?.name && thread.name !== 'main' ? <Pill>{thread.name}</Pill> : null}
        {lead ? <Pill tone={busy ? 'agent' : 'clear'} title="The lead agent's state">{busy ? 'Lead working' : lead.status === 'waiting' ? 'Lead waiting' : `Lead ${lead.status}`}</Pill> : <Pill title="No agent team yet; your first message starts it">No lead yet</Pill>}
      </div>
      <div className="turns" ref={scroller}>
        {messages.isPending ? <Loading what="Loading the conversation" /> : messages.error ? <Failed error={messages.error} /> : null}
        {messages.data?.messages.length === 0 && !busy ? <div className="empty">Nothing yet. Describe the problem or ask the lead what it sees; it starts nothing until you ask.</div> : null}
        {messages.data?.messages.map(message => <Turn key={message.id} message={message} thread={threadId} aliases={aliases} />)}
        {messages.data?.questions.length ? messages.data.questions.map(q => <div key={q.id} className="turn lab" data-testid="question">The lead asks: {q.question}</div>) : null}
        <LiveTurn live={stream.live} thread={threadId} />
      </div>
      <Composer onSend={sendMessage} disabled={!campaign} why={!campaign ? 'Waiting for the campaign to load' : undefined} />
    </div>
  );
}
