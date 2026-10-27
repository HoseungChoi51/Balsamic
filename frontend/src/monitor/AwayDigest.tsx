/** The away digest: what happened while you were away, counted from records; seen when you open it. */
import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRead } from '../api/queries';
import { api } from '../api/client';
import { Empty, Failed, Kv, Loading, Pill, Section, when } from '../primitives/ui';
import { track } from '../telemetry/events';

interface Digest { id: string; from_event: number; to_event: number; rounds_completed: number; away_minutes?: number; stopped: { hypothesis_id: string; reason: string | null; outcome_words?: string; by: string }[]; promoted: { hypothesis_id: string; by: string }[];
  started: { operation: string; trial_id: string | null; by: string }[]; finished_trial_ids: string[]; decisions_waiting: { id: string; title: string }[]; questions_waiting: { id: string; question: string }[]; commands: { id: string; operation: string; by: string }[]; written_at?: string; seen_at?: string | null }

export function AwayDigest({ campaignId }: { campaignId: string }) {
  const body = useRead<{ digest: Digest | null; history: Digest[] }>(['digest', campaignId], `/api/v1/campaigns/${campaignId}/away-digest`, { staleTime: 2000 });
  const queryClient = useQueryClient();
  const digest = body.data?.digest;
  useEffect(() => {
    if (!digest || digest.seen_at) return;
    track('digest.seen', { rounds: digest.rounds_completed });
    void api(`/api/v1/campaigns/${campaignId}/away-digest/${digest.id}/seen`, { method: 'POST' }).then(() => { void queryClient.invalidateQueries({ queryKey: ['monitor', campaignId] }); });
  }, [digest?.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (body.isPending) return <Loading />;
  if (body.error) return <Failed error={body.error} />;
  const show = digest || body.data!.history.at(-1);
  if (!show) return <Empty>No digest yet. One is written when an autopilot round completes after you have been away for half an hour.</Empty>;
  return (
    <Section title={digest ? 'While you were away' : 'Last digest'} right={<span className="small faint">{show.away_minutes ? `${show.away_minutes} min away · ` : ''}{when(show.written_at)}</span>}>
      <Kv rows={[['Rounds completed', String(show.rounds_completed)], ['Stopped', show.stopped.length ? show.stopped.map(s => `${s.hypothesis_id} (${s.outcome_words ? s.outcome_words + ': ' : ''}${s.reason || 'no reason'}; ${s.by})`).join('; ') : 'none'],
        ['Promoted', show.promoted.length ? show.promoted.map(p => `${p.hypothesis_id} (${p.by})`).join(', ') : 'none'], ['Runs started', String(show.started.length)], ['Runs finished', String(show.finished_trial_ids.length)],
        ['Waiting for you', `${show.decisions_waiting.length} decisions, ${show.questions_waiting.length} questions`]]} />
      {show.commands.length ? <details><summary className="small">{show.commands.length} commands</summary>{show.commands.map(c => <div key={c.id} className="small"><Pill tone={c.by === 'autopilot' ? 'agent' : 'you'}>{c.by}</Pill> {c.operation}</div>)}</details> : null}
    </Section>
  );
}
