import { useEffect, useState } from 'react';
import { api } from './api';
import './agentLive.css';

export type LiveAgent = {
  agent_id: string; role: string; parent_agent_id?: string | null; status: string; run_id?: string | null; phase: string;
  started_at?: string | null; updated_at?: string | null; steps: { label: string; done: boolean; failed: boolean }[]; thinking: string; text: string;
};

export function roleName(role: string): string {
  if (role === 'lead') return 'Lead agent';
  const words = role.replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The agent in charge of each page that has one: it takes requests there from the researcher, and from the lead agent. */
export const pageAgents = { hypotheses: 'discussion_moderator', experiments: 'experiment_operator', implementations: 'implementation_lead' } as const;
export const pageAgentRoles: readonly string[] = Object.values(pageAgents);
/** The page of a page agent's role. */
export function agentPage(role: string): string | undefined { return Object.entries(pageAgents).find(([, owner]) => owner === role)?.[0]; }

export type LiveReport ={ job_id: string; stage?: string | null; phase: string; started_at?: string | null; thinking: string; text: string };
type Live = { agents: LiveAgent[]; reports: LiveReport[] };
const nothing: Live = { agents: [], reports: [] };

/** What the campaign's agents and its report writer are doing right now. Asked for only while something is at work and this tab is visible. */
export function useLive(campaignId: string | undefined, active: boolean): Live {
  const [live, setLive] = useState<Live>(nothing);
  useEffect(() => {
    if (!campaignId || !active) { setLive(nothing); return; }
    let current = true, timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      if (document.visibilityState === 'visible') {
        try {
          const result = await api<Partial<Live>>(`/api/v1/campaigns/${encodeURIComponent(campaignId!)}/agents/live`);
          if (current) setLive({ agents: result.agents || [], reports: result.reports || [] });
        } catch { /* The next poll tries again; nothing else depends on this view. */ }
      }
      if (current) timer = setTimeout(poll, 1500);
    }
    void poll();
    return () => { current = false; clearTimeout(timer); };
  }, [campaignId, active]);
  return live;
}
export function useAgentLive(campaignId: string | undefined, active: boolean): LiveAgent[] { return useLive(campaignId, active).agents; }

function useSeconds(since?: string | null): string {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const started = since ? Date.parse(since) : NaN;
  if (Number.isNaN(started)) return '';
  const seconds = Math.max(0, Math.round((now - started) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** The end of a long text, starting at a word. */
function ending(text: string, length: number): string {
  const trimmed = text.trim();
  return trimmed.length > length ? '…' + trimmed.slice(-length).replace(/^\S*\s/, '') : trimmed;
}

/** The last lines of what a model is thinking, or of what it is writing. Shown while it is produced and not kept. */
export function LiveThought({ phase, thinking, text, length = 260 }: { phase: string; thinking: string; text: string; length?: number }) {
  const writing = phase === 'writing' && text.trim();
  const shown = ending(writing ? text : thinking, length);
  return shown ? <p className="working-thought"><span>{writing ? 'Writing' : 'Thinking'}</span>{shown}</p> : null;
}

/** The agent's current step; empty when its live view has not been read (hidden tab, first poll). */
export function currentStep(agent?: LiveAgent): string {
  if (!agent) return '';
  const open = [...agent.steps].reverse().find(step => !step.done);
  if (open) return open.label;
  return agent.phase === 'writing' ? 'writing' : agent.phase === 'queued' || agent.phase === 'starting' ? 'starting' : 'thinking';
}

/**
 * The steps of an agent's turn and the end of its reasoning, while the turn runs.
 * It is temporary: nothing of it is kept once the turn is over.
 */
export function WorkingNote({ agent, role, steps = 6 }: { agent?: LiveAgent; role: string; steps?: number }) {
  const elapsed = useSeconds(agent?.started_at);
  const shown = agent?.steps.slice(-steps) || [];
  const earlier = (agent?.steps.length || 0) - shown.length;
  const thought = Boolean(agent && (agent.thinking.trim() || (agent.phase === 'writing' && agent.text.trim())));
  return <div className="working-note" aria-label={`${roleName(role)} at work`}>
    <div className="working-head"><span className="working-dot" /><strong role="status">{roleName(role)} is working</strong>{elapsed && <time>{elapsed}</time>}</div>
    {earlier > 0 && <p className="working-earlier">{earlier} earlier {earlier === 1 ? 'step' : 'steps'}</p>}
    {shown.length > 0 && <ol className="working-steps">{shown.map((step, index) =>
      <li key={`${earlier + index}-${step.label}`} className={step.failed ? 'failed' : step.done ? 'done' : 'current'}>{step.label}{step.failed && ' (failed)'}</li>)}</ol>}
    {thought ? <LiveThought phase={agent!.phase} thinking={agent!.thinking} text={agent!.text} />
      : !shown.some(step => !step.done) && <p className="working-thought"><span>{agent && !['queued', 'starting'].includes(agent.phase) ? 'Thinking' : 'Starting'}</span></p>}
  </div>;
}
