/** Renders a panel an agent composed from the catalog (balsamic/panels/schema.py): every component is one of ours, values come
 *  resolved from the server, fields write through the panel's set route (the charter service), buttons go through the bus. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useSummary } from '../api/queries';
import type { Panel, PanelComponent } from '../api/types';
import { send } from '../commands/bus';
import { Markdown } from '../chat/render/Markdown';
import { NumberField } from '../note/CharterPanel';
import { Curve } from '../primitives/charts';
import { Empty, Kv, Pill, num, when } from '../primitives/ui';
import { withThread } from '../router/routes';

const show = (v: unknown) => v == null ? '' : typeof v === 'number' ? num(v, Number.isInteger(v) ? 0 : 3) : typeof v === 'object' ? JSON.stringify(v) : String(v);

export function PanelView({ panel, threadId, compact = false }: { panel: Panel; threadId: string | null; compact?: boolean }) {
  const queryClient = useQueryClient();
  const summary = useSummary(panel.campaign_id);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ['panels', panel.campaign_id] }), queryClient.invalidateQueries({ queryKey: ['panel', panel.id] }),
    queryClient.invalidateQueries({ queryKey: ['charter'] }), queryClient.invalidateQueries({ queryKey: ['campaigns'] })]);
  const set = async (componentId: string, value: unknown) => {
    setError(null); setBusy(true);
    try { await api(`/api/v1/panels/${panel.id}/set`, { method: 'POST', body: JSON.stringify({ component_id: componentId, value }) }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); throw e; }
    finally { setBusy(false); }
  };
  const press = async (component: PanelComponent) => {
    const command = component.command as { operation: string; payload?: Record<string, unknown> };
    const campaign = summary.data?.campaign; if (!campaign) { setError('The campaign is still loading'); return; }
    if (component.confirm && !window.confirm(String(component.confirm))) return;
    setError(null); setBusy(true);
    try { await send({ operation: command.operation, campaignId: panel.campaign_id, expectedRevision: campaign.version, payload: command.payload || {}, origin: threadId ? { thread_id: threadId } : undefined }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  const render = (component: PanelComponent, index: number): React.ReactNode => {
    const id = component.id || `c${index}`;
    const data = component.id ? panel.data[component.id] || {} : {};
    switch (component.type) {
      case 'markdown': return <Markdown key={id} text={String(component.text)} thread={threadId} />;
      case 'kv': return <div key={id} data-testid="panel-kv">{component.title ? <h4>{String(component.title)}</h4> : null}
        <Kv rows={((data.rows as { label: string; value: unknown; units?: string }[]) || (component.rows as { label: string; value?: unknown; units?: string }[])).map(r => [r.label, <>{show(r.value) || <span className="faint">unknown</span>}{r.units && r.units !== '1' ? <span className="faint small"> {r.units}</span> : null}</>])} /></div>;
      case 'table': {
        const columns = component.columns as { key: string; label?: string }[];
        const rows = (data.rows as Record<string, unknown>[]) || (component.rows as Record<string, unknown>[]) || [];
        return <div key={id} data-testid="panel-table">{component.title ? <h4>{String(component.title)}</h4> : null}
          {rows.length ? <table><thead><tr>{columns.map(c => <th key={c.key}>{c.label || c.key}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={i}>{columns.map(c => <td key={c.key}>{c.key.endsWith('_at') ? when(r[c.key]) : show(r[c.key])}</td>)}</tr>)}</tbody></table> : <Empty>Nothing yet.</Empty>}</div>;
      }
      case 'number': return <div key={id} className="panel-field" data-testid="panel-number" data-component={id}>
        <label>{String(component.label)}{data.origin === 'assumed' && !data.accepted ? <Pill tone="attention">assumed</Pill> : null}</label>
        <NumberField key={String(data.revision ?? '')} initial={data.value as number | null} units={(component.units as string) || (data.units as string)} onSet={v => set(id, v)} busy={busy} testId={`panel-${id}`} />
        {component.help ? <span className="small faint">{String(component.help)}</span> : null}</div>;
      case 'select': return <div key={id} className="panel-field" data-testid="panel-select" data-component={id}>
        <label>{String(component.label)}</label>
        <select value={data.value == null ? '' : String(data.value)} disabled={busy} data-testid={`panel-${id}`} onChange={e => { const option = (component.options as { value: string | number; label?: string }[]).find(o => String(o.value) === e.target.value); if (option) void set(id, option.value).catch(() => undefined); }}>
          <option value="">choose…</option>{(component.options as { value: string | number; label?: string }[]).map(o => <option key={String(o.value)} value={String(o.value)}>{o.label || String(o.value)}</option>)}</select>
        {component.help ? <span className="small faint">{String(component.help)}</span> : null}</div>;
      case 'chart': { const points = (data.points as { x: number; y: number }[]) || (component.points as { x: number; y: number }[]) || [];
        return <div key={id} data-testid="panel-chart">{component.title ? <h4>{String(component.title)}</h4> : null}<Curve points={points} label={String(component.title || 'curve')} /></div>; }
      case 'button': return <button key={id} type="button" className={'btn small' + (component.tone === 'primary' ? ' primary' : '')} disabled={busy} onClick={() => press(component)} data-testid={`panel-${id}`}>{String(component.label)}</button>;
      case 'link': return <a key={id} className="btn small" href={withThread(String(component.page), threadId)}>{String(component.label)}</a>;
      case 'section': return <section key={id} className="panel-section"><h4>{String(component.title)}</h4><div className="col">{(component.children as PanelComponent[]).map(render)}</div></section>;
      default: return null;
    }
  };
  return (
    <section className={'panel' + (compact ? ' compact' : '')} data-testid="panel" data-panel-id={panel.id} aria-label={panel.title}>
      <header className="panel-head"><Pill tone="agent">{panel.author}</Pill><strong className="grow">{panel.title}</strong><span className="faint small">r{panel.revision}</span></header>
      {panel.note ? <p className="small muted">{panel.note}</p> : null}
      <div className="col">{panel.components.map(render)}</div>
      {error ? <div className="pill bad" role="alert" data-testid="panel-error">{error}</div> : null}
    </section>
  );
}
