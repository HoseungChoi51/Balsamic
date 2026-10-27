import type { LiveTurn as Live } from './stream';
import { Markdown } from './render/Markdown';
import { Pill } from '../primitives/ui';
import { navigate, withThread } from '../router/routes';

export function LiveTurn({ live, thread }: { live: Live; thread: string | null }) {
  if (live.status === 'idle' || (live.status === 'finished' && !live.text && !live.steps.length)) return null;
  return (
    <article className="turn agent" data-testid="live-turn" aria-live="polite">
      <div className="meta"><Pill tone="agent">Lead</Pill><span>{live.status === 'running' ? 'working…' : live.status === 'error' ? 'the turn failed; its work is saved' : 'finished'}</span></div>
      {live.thinking && live.status === 'running' ? <div className="thinking" title="The lead's reasoning, while it runs">{live.thinking.slice(-600)}</div> : null}
      {live.steps.length ? <div className="steps">{live.steps.map(step => (
        <div key={step.id} className={'step' + (step.failed ? ' failed' : step.done ? ' done' : '')}>
          {step.label}{step.link ? <> · <a href={withThread(step.link, thread)} onClick={e => { e.preventDefault(); navigate(withThread(step.link as string, thread)); }}>open</a></> : null}
        </div>))}</div> : null}
      {live.text ? <Markdown text={live.text} thread={thread} /> : null}
      {live.error ? <div className="pill bad">{live.error}</div> : null}
    </article>
  );
}
