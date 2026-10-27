/** During Optimize: the best so far, the live runs and the finalists' rungs, in one line under the top bar. */
import { useEvolution } from './EvolutionPage';
import { num, duration } from '../primitives/ui';

export function IterationProgress({ campaignId }: { campaignId: string }) {
  const evolution = useEvolution(campaignId);
  const progress = evolution.data?.progress;
  if (!progress) return null;
  return (
    <div className="row small" data-testid="iteration-progress" style={{ padding: '4px 18px', borderBottom: '1px solid var(--line)', background: 'var(--panel-2)' }}>
      <span>best so far <strong>{num(progress.best_so_far, 4)}</strong> (measured)</span>
      <span>· {progress.live_trials.length} live run{progress.live_trials.length === 1 ? '' : 's'}</span>
      {progress.finalist_rungs.length ? <span>· finalists at {progress.finalist_rungs.map(f => duration(f.rung)).join(', ')}</span> : null}
      <span className="faint">· round {evolution.data?.rounds}</span>
    </div>
  );
}
