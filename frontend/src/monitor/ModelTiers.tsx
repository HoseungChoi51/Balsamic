/** Which model each agent role runs on: tiers (a model and thinking level each) and the role → tier assignment. Dev mode only; a change applies at the agent's next turn. */
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useRead } from '../api/queries';
import { Empty, Failed, Loading, Pill, Section } from '../primitives/ui';

interface ModelChoice { provider: string | null; model: string | null; effort?: string | null }
interface Tier { id: string; label: string; model: ModelChoice }
/** Every role by the name the pages use, what it does, and whether the researcher talks with it directly. */
const ROLE_INFO: Record<string, { label: string; does: string; direct?: boolean }> = {
  lead: { label: 'Lead', does: 'your conversation; writes the problem note, records proposals, runs the campaign on your requests', direct: true },
  formulator: { label: 'Formulator', does: 'writes the charter from the adopted note; asks you its questions on the Charter tab', direct: true },
  discussion_moderator: { label: 'Discussion moderator', does: 'reviews proposals in rounds on Hypotheses when you or the lead ask', direct: true },
  experiment_operator: { label: 'Experiment operator', does: 'designs, starts and watches runs on Experiments when you or the lead ask', direct: true },
  implementation_lead: { label: 'Implementation lead', does: 'builds and attaches optimizer and evaluator code on Implementations', direct: true },
  resource_planner: { label: 'Resource planner', does: 'plans machine use within your resource level, on Monitor', direct: true },
  housekeeper: { label: 'Housekeeper', does: 'one-shot calls: branch titles, strategy labels, summaries, the suggested next requests' },
  literature_specialist: { label: 'Literature specialist', does: 'what the sources say, for the lead and the moderator' },
  methodology_specialist: { label: 'Methodology specialist', does: 'methods and their fit, for the lead and the moderator' },
  cross_domain_explorer: { label: 'Cross-domain explorer', does: 'ideas from other fields, for the lead and the moderator' },
  skeptical_domain_analyst: { label: 'Skeptical analyst', does: 'what could go wrong, for the lead and the moderator' },
  empirical_assessor: { label: 'Empirical assessor', does: 'what the evidence supports, for the lead and the moderator' },
  proposal_reviewer: { label: 'Proposal reviewer', does: 'verdicts on proposals in a review round' },
  implementation_builder: { label: 'Implementation builder', does: 'writes code for the implementation lead' },
  implementation_test_designer: { label: 'Test designer', does: 'tests for the implementation lead' },
  implementation_validator: { label: 'Implementation validator', does: 'checks the code before it is attached' },
  results_analyst: { label: 'Results analyst', does: 'reads run results for the lead' },
};
const info = (role: string) => ROLE_INFO[role] || { label: role.replaceAll('_', ' '), does: '' };
interface View { mode: 'dev' | 'locked'; revision: number; saved: boolean; tiers: Tier[]; roles: Record<string, string>; assignable: string[]; providers: Record<string, { auth?: string; billing?: string }>; housekeeping?: { enabled: boolean; model: { provider: string; model: string } | null; waiting: number; last_error: { text: string | null; at: string | null } };
  models: { provider: string; id: string; name?: string; reasoning?: boolean; thinking_levels?: string[]; thinking_default?: string; family?: string }[]; updated_at?: string | null }

export function ModelTiers() {
  const view = useRead<View>(['model-tiers'], '/api/v1/model-tiers', { staleTime: 5000 });
  const queryClient = useQueryClient();
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => { if (view.data && !dirty) { setTiers(view.data.tiers); setRoles(view.data.roles); } }, [view.data, dirty]);
  if (view.isPending) return <Loading />;
  if (view.error) return <Failed error={view.error} />;
  const data = view.data;
  const models = data.models;
  const signedIn = Object.keys(data.providers);
  const key = (m: ModelChoice) => `${m.provider || ''}/${m.model || ''}`;
  const find = (m: ModelChoice) => models.find(x => x.provider === m.provider && x.id === m.model);
  // The levels Pi's /thinking offers for the model; "default" is the level a session runs at when none is chosen.
  const levels = (m: ModelChoice) => find(m)?.thinking_levels || ['off', 'low', 'medium', 'high'];
  const setTier = (i: number, patch: Partial<Tier> | { model: ModelChoice }) => { setTiers(ts => ts.map((t, j) => j === i ? { ...t, ...patch } : t)); setDirty(true); };
  const save = async () => {
    setError(null); setSaved(null);
    try {
      const next = await api<View & { applied?: { updated: string[]; blocked: { reason: string }[] } }>('/api/v1/model-tiers', { method: 'PUT', body: JSON.stringify({ tiers, roles, expected_revision: data.revision }) });
      queryClient.setQueryData(['model-tiers'], next); setDirty(false);
      setSaved(`Saved. ${next.applied?.updated.length || 0} running agents switched` + (next.applied?.blocked.length ? `; ${next.applied.blocked.length} kept their model (${next.applied.blocked.map(b => b.reason).join('; ')})` : '.'));
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <>
      <Section title="Signed-in providers" right={<Pill>{data.mode} mode</Pill>}>
        {signedIn.length ? <p className="small">{signedIn.map(p => `${p} (${data.providers[p].billing || data.providers[p].auth || 'signed in'})`).join(', ')} · {models.length} models</p>
          : <p className="small muted">No provider is signed in on the harness yet, so no model can run.</p>}
        <ProviderLogin signedIn={signedIn} onDone={() => queryClient.invalidateQueries({ queryKey: ['model-tiers'] })} />
        <p className="why">The harness offers the providers your own Pi offers: custom endpoints such as a LiteLLM proxy come from <code>~/.pi/agent/models.json</code> (or the profile's <code>models.json</code>) with their keys in <code>~/.pi/agent/auth.json</code>; key-based providers (DeepSeek, OpenAI API, Anthropic, …) also take their key from <code>~/.config/balsamic/secrets.env</code>. Restart the stack after a change. <code>scripts/pi-dev</code> then <code>/login</code> is the interactive way to add a sign-in.</p>
      </Section>
      {data.mode !== 'dev' ? <Empty>Models are locked by the harness profile; the dev profile (GRATING_PI_PROFILE) makes them configurable here.</Empty> : (
        <Section title="Tiers: the models agents run on" right={<div className="row">{dirty ? <Pill tone="attention">unsaved</Pill> : null}<button className="btn primary small" disabled={!dirty} onClick={save} data-testid="save-tiers">Save</button></div>}>
          <table><thead><tr><th>Tier</th><th>Model</th><th>Thinking</th><th></th></tr></thead><tbody>
            {tiers.map((tier, i) => <tr key={tier.id} data-testid="tier-row">
              <td><input value={tier.label} onChange={e => setTier(i, { label: e.target.value })} aria-label={`label of ${tier.id}`} style={{ width: 140 }} /><div className="faint mono small">{tier.id}</div></td>
              <td><select value={key(tier.model)} aria-label={`model of ${tier.id}`} onChange={e => { const [provider, ...rest] = e.target.value.split('/'); const chosen = models.find(m => m.provider === provider && m.id === rest.join('/')); setTier(i, { model: { provider: provider || null, model: rest.join('/') || null, effort: tier.model.effort && chosen?.thinking_levels?.includes(tier.model.effort) ? tier.model.effort : null } }); }}>
                <option value="/">— no model —</option>{models.map(m => <option key={`${m.provider}/${m.id}`} value={`${m.provider}/${m.id}`}>{m.provider} / {m.id}</option>)}
                {tier.model.model && !models.some(m => m.provider === tier.model.provider && m.id === tier.model.model) ? <option value={key(tier.model)}>{key(tier.model)} (not available now)</option> : null}</select></td>
              <td><select value={tier.model.effort || ''} aria-label={`thinking of ${tier.id}`} onChange={e => setTier(i, { model: { ...tier.model, effort: e.target.value || null } })}><option value="">{find(tier.model)?.thinking_default ? `default (${find(tier.model)?.thinking_default})` : 'default'}</option>{levels(tier.model).map(l => <option key={l} value={l}>{l}</option>)}</select></td>
              <td>{tiers.length > 1 ? <button className="btn quiet small" onClick={() => { setTiers(ts => ts.filter((_, j) => j !== i)); setRoles(r => Object.fromEntries(Object.entries(r).filter(([, t]) => t !== tier.id))); setDirty(true); }}>remove</button> : null}</td>
            </tr>)}</tbody></table>
          <button className="btn small" style={{ marginTop: 6 }} onClick={() => { const id = `tier-${tiers.length + 1}`; setTiers(ts => [...ts, { id, label: 'New tier', model: { provider: models[0]?.provider || null, model: models[0]?.id || null, effort: null } }]); setDirty(true); }}>Add a tier</button>
          <h3 style={{ marginTop: 12 }}>Which tier each role runs on</h3>
          {[true, false].map(direct => <div key={String(direct)} data-testid={direct ? 'roles-direct' : 'roles-behind'}>
            <h4 style={{ marginTop: 8 }}>{direct ? 'Talk with you' : 'Work behind the scenes'}</h4>
            <p className="why">{direct ? 'The agents you read and answer: slow or weak here, and you feel it on every page.' : 'Called by the lead or a page agent for one assignment each; you see their work through them.'}</p>
            <table><thead><tr><th>Role</th><th>Tier</th></tr></thead><tbody>
              {data.assignable.filter(role => !!info(role).direct === direct).map(role => <tr key={role} data-testid="role-row" data-role={role} data-direct={direct ? '1' : undefined} className={direct ? 'accent' : ''}>
                <td><strong>{info(role).label}</strong>{info(role).does ? <div className="small faint">{info(role).does}</div> : null}</td>
                <td><select value={roles[role] || ''} aria-label={`tier of ${role}`} onChange={e => { setRoles(r => ({ ...r, [role]: e.target.value })); setDirty(true); }}>
                  <option value="">(default tier)</option>{tiers.map(t => <option key={t.id} value={t.id}>{t.label} · {key(t.model)}</option>)}</select></td></tr>)}</tbody></table>
          </div>)}
          {error ? <div className="pill bad">{error}</div> : null}{saved ? <div className="pill clear">{saved}</div> : null}
          <p className="why">Thinking is the reasoning effort, as Pi's <code>/thinking</code> offers it for the model; a level the model refuses can be marked <code>null</code> in its <code>thinkingLevelMap</code> in <code>models.json</code>. A running agent switches only within its campaign's model family; others keep their model until their campaign ends. The formulator keeps its model for the lifetime of a charter: a change here reaches the next charter, not the one being written. The setup assistant uses the lead's tier (at low thinking), from its next answer on; the lead of a new campaign starts on it. The housekeeper is not an agent: it names branches, labels strategies and writes branch summaries in one-shot calls.</p>
          {data.housekeeping ? <div className="row wrap small" data-testid="housekeeping-status">
            <Pill tone={data.housekeeping.last_error?.text ? 'bad' : data.housekeeping.enabled ? 'clear' : ''}>housekeeper {data.housekeeping.model ? key(data.housekeeping.model) : 'no model'}</Pill>
            <span className="faint">{data.housekeeping.waiting} job{data.housekeeping.waiting === 1 ? '' : 's'} waiting</span>
            {data.housekeeping.last_error?.text ? <span className="pill bad" title={data.housekeeping.last_error.at || ''}>last call failed: {data.housekeeping.last_error.text}</span> : null}
          </div> : null}
        </Section>)}
    </>
  );
}


/** The ChatGPT subscription: Pi's openai-codex provider signs in with a device code; the tokens stay on the host. */
function ProviderLogin({ signedIn, onDone }: { signedIn: string[]; onDone: () => unknown }) {
  const [login, setLogin] = useState<{ status: string; url?: string; user_code?: string; expires_at?: number; reason?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const connected = signedIn.includes('openai-codex');
  useEffect(() => {
    if (login?.status !== 'pending') return;
    const timer = setInterval(() => { void onDone(); }, 5000);
    return () => clearInterval(timer);
  }, [login?.status, onDone]);
  useEffect(() => { if (connected && login?.status === 'pending') setLogin({ status: 'connected' }); }, [connected, login?.status]);
  const start = async () => {
    setError(null);
    try { setLogin(await api<{ status: string; url?: string; user_code?: string; expires_at?: number }>('/api/v1/providers/login', { method: 'POST' })); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <div className="row wrap" data-testid="provider-login">
      <span className="small">ChatGPT (OpenAI Codex, subscription): {connected ? <Pill tone="clear">signed in</Pill> : <Pill>not signed in</Pill>}</span>
      {!connected ? <button className="btn small" onClick={start} data-testid="login-openai">Sign in with a device code…</button> : null}
      {login?.status === 'pending' ? <span className="small">Open <a href={login.url} target="_blank" rel="noreferrer">{login.url}</a> and enter <strong className="mono" data-testid="login-code">{login.user_code}</strong>; this page updates when the sign-in completes.</span> : null}
      {login?.status === 'expired' ? <span className="pill bad">{login.reason}</span> : null}
      {error ? <span className="pill bad">{error}</span> : null}
    </div>
  );
}
