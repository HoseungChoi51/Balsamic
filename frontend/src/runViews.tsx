import { useEffect, useRef, useState } from 'react';
import { api, errorText, objectiveValue } from './api';
import type { Json, Trial } from './api';
import { Design } from './ui';

/** The presentation a campaign's experiment rules set: what the list of runs and a run's entry show. */
export type Presentation = {
  list_columns: string[]; entry_sections: string[]; curve_x: 'evaluations' | 'elapsed_seconds'; objectives: string[]; rationale?: string;
  design: { render: 'mask' | 'strip' | 'table' | 'none'; rows?: number | null; cols?: number | null; on_label?: string; off_label?: string };
};
export const fallbackPresentation: Presentation = { list_columns: ['name', 'method', 'status', 'best', 'evaluations', 'time'],
  entry_sections: ['curve', 'objectives', 'numbers', 'settings', 'files', 'question'], curve_x: 'evaluations', objectives: [], design: { render: 'none' } };

/** A run's best design so far. */
export function bestDesign(trial: Trial): number[] | undefined {
  const measured = { ...trial.result, ...trial.progress };
  const values = measured.best_design || measured.best_candidate;
  return Array.isArray(values) ? values : undefined;
}

/**
 * A binary design drawn as an image of rows x cols cells, stored row by row. Drawn by the page itself, pixel by pixel:
 * nothing of the run's own content is rendered as markup.
 */
export function MaskImage({ values, rows, cols, width, onLabel = '1', offLabel = '0', legend = false }: {
  values: number[]; rows: number; cols: number; width: number; onLabel?: string; offLabel?: string; legend?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const fits = values.length === rows * cols;
  const filled = fits ? values.reduce((sum, value) => sum + (value ? 1 : 0), 0) / values.length : 0;
  useEffect(() => {
    const context = canvas.current?.getContext('2d');
    if (!context || !fits) return;
    const image = context.createImageData(cols, rows);
    const style = getComputedStyle(canvas.current!);
    const [on, off] = [style.getPropertyValue('--mask-on') || '#24453a', style.getPropertyValue('--mask-off') || '#eef2e6'].map(hex);
    values.forEach((value, index) => { const color = value ? on : off; image.data.set([color[0], color[1], color[2], 255], index * 4); });
    context.putImageData(image, 0, 0);
  }, [values, rows, cols, fits]);
  if (!fits) return <p className="muted">The design has {values.length} values, not {rows} × {cols}.</p>;
  const label = `${rows} × ${cols} design: ${(filled * 100).toFixed(0)}% ${onLabel}`;
  return <figure className="mask-image"><canvas ref={canvas} width={cols} height={rows} role="img" aria-label={label}
    style={{ width, maxWidth: '100%', aspectRatio: `${cols} / ${rows}` }} />
    {legend && <figcaption><span><i className="on" />{onLabel}</span><span><i className="off" />{offLabel}</span><span>{rows} × {cols} cells · {(filled * 100).toFixed(1)}% {onLabel}</span></figcaption>}</figure>;
}
function hex(value: string): number[] {
  const text = value.trim().replace('#', '');
  const full = text.length === 3 ? text.split('').map(c => c + c).join('') : text.padEnd(6, '0');
  return [0, 2, 4].map(at => parseInt(full.slice(at, at + 2), 16) || 0);
}

/** A design as the presentation says to draw it. */
export function DesignView({ trial, presentation, width, legend = false }: { trial: Trial; presentation: Presentation; width: number; legend?: boolean }) {
  const values = bestDesign(trial), view = presentation.design;
  if (!values?.length) return <p className="muted design-missing">No design yet</p>;
  if (view.render === 'mask' && view.rows && view.cols)
    return <MaskImage values={values} rows={view.rows} cols={view.cols} width={width} onLabel={view.on_label} offLabel={view.off_label} legend={legend} />;
  if (view.render === 'strip') return <Design cells={values} small={!legend} />;
  if (view.render === 'table' && values.length <= 200) return <div className="table-scroll"><table className="data-table"><thead><tr><th>Coordinate</th><th>Value</th></tr></thead>
    <tbody>{values.map((value, index) => <tr key={index}><td>x{index + 1}</td><td>{value.toPrecision(7)}</td></tr>)}</tbody></table></div>;
  return <p className="muted">{values.length} values; not drawn.</p>;
}

/** The best score against evaluations (or time), read as a few hundred points of the run's metrics. */
export function RunCurve({ trial, x, live }: { trial: Trial; x: 'evaluations' | 'elapsed_seconds'; live: boolean }) {
  const [rows, setRows] = useState<Json[] | null>(null), [error, setError] = useState('');
  const progress = { ...trial.result, ...trial.progress };
  useEffect(() => {
    let current = true;
    api<Json[]>(`/api/trials/${trial.id}/metrics?fields=evaluations,elapsed_seconds,best_objective&points=400`)
      .then(result => { if (current) { setRows(result); setError(''); } }).catch(failure => { if (current) setError(errorText(failure)); });
    return () => { current = false; };
  }, [trial.id, live ? progress.step : 0]);
  if (error) return <p className="muted">The learning curve is unavailable: {error}</p>;
  const points = (rows || []).filter(row => Number.isFinite(row[x]) && Number.isFinite(row.best_objective));
  if (!rows) return <p className="muted">Reading the learning curve…</p>;
  if (points.length < 2) return <p className="muted">Not enough measurements for a curve yet.</p>;
  const width = 640, height = 220, left = 56, right = 14, top = 12, bottom = 36;
  const xs = points.map(row => row[x] as number), ys = points.map(row => row.best_objective as number);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)], [low, high] = [Math.min(...ys), Math.max(...ys)];
  const pad = (high - low) * 0.08 || Math.abs(high) * 0.05 || 1;
  const [y0, y1] = [low - pad, high + pad];
  const sx = (value: number) => left + (value - x0) / ((x1 - x0) || 1) * (width - left - right);
  const sy = (value: number) => top + (1 - (value - y0) / (y1 - y0)) * (height - top - bottom);
  const path = points.map((row, index) => `${index ? 'L' : 'M'}${sx(row[x]).toFixed(1)},${sy(row.best_objective).toFixed(1)}`).join('');
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const definition = trial.problem?.primary_objective;
  const xLabel = x === 'evaluations' ? 'evaluations' : 'worker time (s)';
  return <figure className="run-curve"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Best ${definition?.name || 'objective'} against ${xLabel}`}>
    {ticks.map(f => { const value = y0 + f * (y1 - y0); return <g key={`y${f}`}><line x1={left} x2={width - right} y1={sy(value)} y2={sy(value)} className="grid" />
      <text x={left - 6} y={sy(value) + 4} textAnchor="end">{objectiveValue(value, definition)}</text></g>; })}
    {ticks.map(f => { const value = x0 + f * (x1 - x0); return <text key={`x${f}`} x={sx(value)} y={height - bottom + 16} textAnchor="middle">
      {value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : value.toFixed(0)}</text>; })}
    <text x={(left + width - right) / 2} y={height - 4} textAnchor="middle" className="axis-label">{xLabel}</text>
    <path d={path} className="line" />
  </svg></figure>;
}
