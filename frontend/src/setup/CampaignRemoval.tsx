/** Removing a campaign: the researcher's alone; the plan says what would go and what can be kept. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useRead } from '../api/queries';
import { Kv, Pill, Section } from '../primitives/ui';
import { navigate } from '../router/routes';

export function CampaignRemoval({ campaignId }: { campaignId: string }) {
  const [open, setOpen] = useState(false);
  const [keep, setKeep] = useState<'nothing' | 'summary' | 'records'>('summary');
  const [error, setError] = useState<string | null>(null);
  const plan = useRead<{ campaign: { name: string }; blockers: { reason: string }[] | Record<string, unknown>[]; options: { keep: string; kept_bytes: number | null }[]; counts?: Record<string, unknown> }>(['removal', campaignId], open ? `/api/v1/campaigns/${campaignId}/removal` : null);
  const queryClient = useQueryClient();
  const remove = async () => {
    setError(null);
    try {
      await api(`/api/v1/campaigns/${campaignId}/removal`, { method: 'POST', body: JSON.stringify({ keep }) });
      await queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      try { localStorage.removeItem('balsamic.lastThread'); } catch { /* private mode */ }
      navigate('#new');
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  const blockers = (plan.data?.blockers || []) as { reason?: string; message?: string }[];
  return (
    <Section title="Remove this campaign" right={!open ? <button className="btn small" onClick={() => setOpen(true)} data-testid="remove-campaign">Remove…</button> : null}>
      {!open ? <p className="small muted">Abandon a campaign that was set up wrongly, or one that is finished. Only you can do this; what is kept is your choice.</p> : (
        <div className="col" data-testid="removal-plan">
          {plan.isPending ? <p className="small faint">Planning…</p> : plan.error ? <Pill tone="bad">{String((plan.error as Error).message)}</Pill> : <>
            {blockers.length ? <div className="pill attention">Blocked: {blockers.map(b => b.reason || b.message || JSON.stringify(b)).join('; ')}</div> : null}
            <Kv rows={(plan.data?.options || []).map(o => [o.keep, <label key={o.keep} className="row"><input type="radio" name="keep" checked={keep === o.keep} onChange={() => setKeep(o.keep as typeof keep)} /> keep {o.keep}{o.kept_bytes != null ? ` (${(o.kept_bytes / 1e6).toFixed(1)} MB)` : ''}</label>])} />
            <div className="row"><button className="btn primary small" disabled={blockers.length > 0} onClick={remove} data-testid="confirm-removal">Remove the campaign</button><button className="btn small" onClick={() => setOpen(false)}>Cancel</button></div>
            <p className="why">Removal is final for what is not kept; the commands go with the campaign. Nothing is removed until you confirm.</p>
          </>}
          {error ? <div className="pill bad">{error}</div> : null}
        </div>)}
    </Section>
  );
}
