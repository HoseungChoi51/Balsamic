/** Start a campaign: a name, budgets, and either a problem instance now or nothing yet (the lead then drafts the problem note with you). */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useRead } from '../api/queries';
import { send } from '../commands/bus';
import { navigate } from '../router/routes';
import { Section } from '../primitives/ui';

export default function NewCampaign(_: PageProps) {
  const problems = useRead<{ problems: { id: string; name?: string; title?: string }[] }>(['problems'], '/api/v1/problems');
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ id: '', name: '', objective: '', compute: 3600, llm: 5, delegated: 60, problem: '', autonomy: 'delegated' });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const field = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm(f => ({ ...f, [key]: e.target.value }));
  const create = async (e: React.FormEvent) => {
    e.preventDefault(); setError(null); setBusy(true);
    const id = (form.id || form.name).trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'campaign';
    try {
      const receipt = await send({ operation: 'campaign.create', campaignId: id, expectedRevision: 0, payload: {
        name: form.name.trim(), objective: form.objective.trim() || 'Develop an effective optimizer for the chosen problem.', compute_budget_seconds: Number(form.compute), llm_budget_usd: Number(form.llm),
        delegated_trial_seconds: Number(form.delegated), autonomy: form.autonomy,
        ...(form.problem ? { tasks: [{ name: form.problem, problem_id: form.problem, configuration: {} }] } : {}) } });
      await queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      const campaign = receipt.outcome.campaign as { id: string };
      navigate(`#t/thread_main_${campaign.id}/${form.problem ? 'hypotheses' : 'note'}`);
    } catch (err) { setError(String((err as Error).message || err)); }
    finally { setBusy(false); }
  };
  return (
    <div className="col">
      <div className="stage-head"><h1>New campaign</h1></div>
      <Section title="What and how much">
        <form className="form" onSubmit={create} data-testid="new-campaign">
          <label htmlFor="nc-name">Name</label><input id="nc-name" required value={form.name} onChange={field('name')} placeholder="Grating deflector, round 3" />
          <label htmlFor="nc-id">Identity</label><input id="nc-id" value={form.id} onChange={field('id')} placeholder="(from the name) letters, digits, - and _" pattern="[A-Za-z0-9_-]*" />
          <label htmlFor="nc-objective">Question</label><textarea id="nc-objective" value={form.objective} onChange={field('objective')} placeholder="What you want to find out. Leave it rough: the lead drafts the problem note with you." />
          <label htmlFor="nc-problem">Problem</label>
          <select id="nc-problem" value={form.problem} onChange={field('problem')}>
            <option value="">Formulate it with the lead first</option>
            {(problems.data?.problems || []).map(p => <option key={p.id} value={p.id}>{p.title || p.name || p.id}</option>)}
          </select>
          <label htmlFor="nc-compute">Worker budget (s)</label><input id="nc-compute" type="number" min={1} value={form.compute} onChange={field('compute')} />
          <label htmlFor="nc-llm">Model budget ($)</label><input id="nc-llm" type="number" min={0} step="0.5" value={form.llm} onChange={field('llm')} />
          <label htmlFor="nc-delegated">Per-run cap for the lead (s)</label><input id="nc-delegated" type="number" min={1} value={form.delegated} onChange={field('delegated')} />
          <label htmlFor="nc-autonomy">Delegation</label>
          <select id="nc-autonomy" value={form.autonomy} onChange={field('autonomy')}><option value="delegated">Delegated: the lead runs experiments within the caps</option><option value="guided">Guided: the lead asks before each experiment</option><option value="manual">Manual: you run everything</option></select>
          <span /><div className="row"><button className="btn primary" type="submit" disabled={busy || !form.name.trim()}>{busy ? 'Creating…' : 'Create campaign'}</button>{error ? <span className="pill bad">{error}</span> : null}</div>
        </form>
        <p className="why" style={{ marginTop: 8 }}>Autopilot is off for a new campaign; the lead acts on your requests. Limits can be raised later only by you.</p>
      </Section>
    </div>
  );
}
