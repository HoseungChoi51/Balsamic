import { useEffect, useRef, useState } from 'react';
import type { MandateTemplate, MessageMandate } from '../api/types';

/** The digit of Ctrl+1 … Ctrl+9 (Cmd on a Mac), or null for any other key. */
export function shortcutDigit(e: { key: string; code: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean }) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return null;
  const digit = /^[1-9]$/.test(e.key) ? e.key : /^(?:Digit|Numpad)([1-9])$/.exec(e.code)?.[1];
  return digit ? Number(digit) : null;
}

/** The four mandate templates (decision 10) the dial beside Send offers: what the request the message opens may do (roadmap R7). */
export const TEMPLATES: { id: MandateTemplate; label: string; help: string }[] = [
  { id: 'answer', label: 'Answer', help: 'The lead reads and answers; it starts nothing.' },
  { id: 'explore', label: 'Explore', help: 'Proposals, reviews and runs up to your go-ahead threshold in total; no coding workspace.' },
  { id: 'screen', label: 'Screen', help: 'Your go-ahead for this request: runs, coding workspaces, stops and nominations within the envelope you set.' },
  { id: 'run_campaign', label: 'Run the campaign', help: 'Your go-ahead for every stage, within the envelope and deadline you set.' },
];
const GO_AHEAD: Partial<Record<MandateTemplate, { minutes: number; coding: number; hours: number }>> = {
  // What the envelope form starts with; the researcher changes it before granting.
  screen: { minutes: 30, coding: 0, hours: 2 }, run_campaign: { minutes: 120, coding: 1, hours: 24 },
};
interface Envelope { minutes: string; coding: string; usd: string; hours: string }

/** The dial's setting: where it starts (the campaign's default template) and which texts open a request (not a slash command). */
export interface Dial { initial: MandateTemplate; applies?: (text: string) => boolean }

export function Composer({ onSend, disabled, why, placeholder, initial, testId = 'composer', suggestions = [], suggestionsNote, autoFocus, dial }: { onSend: (text: string, mandate?: MessageMandate) => Promise<void>; disabled?: boolean; why?: string; placeholder?: string; initial?: string; testId?: string; suggestions?: { label: string; text: string }[]; suggestionsNote?: string; autoFocus?: boolean; dial?: Dial }) {
  const [text, setText] = useState(initial || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The mandate the next message grants: the campaign's default until the researcher turns the dial, and again after each send.
  const [template, setTemplate] = useState<MandateTemplate>(dial?.initial || 'explore');
  const [turned, setTurned] = useState(false);
  const [envelope, setEnvelope] = useState<Envelope | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (autoFocus && !disabled) area.current?.focus(); }, [autoFocus, disabled]);
  const start = dial?.initial;
  useEffect(() => { if (start && !turned) setTemplate(start); }, [start, turned]);
  const shown = suggestions.length && !text ? suggestions : [];
  const pick = (s: { text: string }) => { setText(s.text); area.current?.focus(); };
  const turn = (value: MandateTemplate) => { setTemplate(value); setTurned(true); if (!GO_AHEAD[value]) setEnvelope(null); };
  const granted = (): MessageMandate | null => {
    if (!GO_AHEAD[template]) return { template };
    if (!envelope) return null;
    const minutes = Number(envelope.minutes), coding = Number(envelope.coding || 0), hours = envelope.hours.trim() ? Number(envelope.hours) : null, usd = envelope.usd.trim() ? Number(envelope.usd) : null;
    if (!(minutes > 0) || !(coding >= 0) || (hours !== null && !(hours > 0)) || (usd !== null && !(usd >= 0))) throw new Error('Give the worker time in minutes, and a deadline and model spend above zero or none');
    return { template, worker_seconds: Math.round(minutes * 60), coding_workspaces: Math.round(coding), ...(usd !== null ? { model_usd: usd } : {}), ...(hours !== null ? { deadline_minutes: Math.round(hours * 60) } : {}) };
  };
  const submit = async () => {
    const value = text.trim();
    if (!value || busy || disabled) return;
    const dialed = !!dial && (dial.applies ? dial.applies(value) : true);
    setError(null);
    // Screen and Run the campaign ask for their envelope first: sending then grants it with the message.
    if (dialed && GO_AHEAD[template] && !envelope) { const start = GO_AHEAD[template]!; setEnvelope({ minutes: String(start.minutes), coding: String(start.coding), usd: '', hours: String(start.hours) }); return; }
    let mandate: MessageMandate | null = null;
    try { mandate = dialed ? granted() : null; } catch (e) { setError(String((e as Error).message || e)); return; }
    // Sending from the composer leaves the cursor in it, ready for the next message.
    const focused = !!form.current?.contains(document.activeElement);
    setBusy(true);
    try { await onSend(value, mandate || undefined); setText(''); setEnvelope(null); if (dial) { setTurned(false); setTemplate(dial.initial); } }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); if (focused) requestAnimationFrame(() => area.current?.focus()); }
  };
  const label = TEMPLATES.find(t => t.id === template);
  const field = (key: keyof Envelope) => ({ value: envelope?.[key] ?? '', onChange: (e: { target: { value: string } }) => setEnvelope(env => env && { ...env, [key]: e.target.value }) });
  return (
    <form ref={form} className="composer" onSubmit={e => { e.preventDefault(); void submit(); }}
      onKeyDown={e => { const n = shortcutDigit(e); if (n && shown[n - 1] && !disabled && !busy) { e.preventDefault(); pick(shown[n - 1]); } }}>
      {shown.length ? <div className="row wrap" data-testid="suggestions" data-live={suggestionsNote ? '1' : undefined}>{shown.map((s, i) => <button key={s.text} type="button" className="btn small" disabled={disabled || busy} onClick={() => pick(s)}
        title={s.text + (i < 9 ? `  (Ctrl+${i + 1})` : '')} data-shortcut={i < 9 ? i + 1 : undefined} aria-keyshortcuts={i < 9 ? `Control+${i + 1}` : undefined}>{s.label}</button>)}{suggestionsNote ? <span className="faint small">{suggestionsNote}</span> : null}</div> : null}
      {/* Read-only rather than disabled while sending: a disabled textarea drops the focus. */}
      <textarea ref={area} value={text} onChange={e => setText(e.target.value)} placeholder={placeholder || 'Ask the lead, or type / for commands'} disabled={disabled} readOnly={busy} aria-busy={busy || undefined}
        data-testid={testId} onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void submit(); } }} />
      {envelope && label ? <fieldset className="mandate-form" data-testid="mandate-form" disabled={busy}>
        <legend className="small"><strong>{label.label}</strong> for this request: your go-ahead, granted with the message, so the lead need not ask for it</legend>
        <div className="row wrap small">
          <label>Worker time <input type="number" min={1} step={1} {...field('minutes')} data-testid="mandate-minutes" /> min</label>
          <label>Coding workspaces <input type="number" min={0} max={10} step={1} {...field('coding')} data-testid="mandate-coding" /></label>
          <label>Model spend $<input type="number" min={0} step={0.5} placeholder="the campaign's cap" {...field('usd')} data-testid="mandate-usd" /></label>
          <label>Deadline in <input type="number" min={0.5} step={0.5} placeholder="none" {...field('hours')} data-testid="mandate-deadline" /> h</label>
        </div>
        <div className="row"><span className="why grow">New work stops at the envelope or the deadline; work already running goes on. You can close it above the chat.</span>
          <button type="button" className="btn small quiet" onClick={() => setEnvelope(null)} data-testid="mandate-cancel">Cancel</button></div>
      </fieldset> : null}
      <div className="row">
        <span className="why grow">{disabled && why ? why : error ? <span className="pill bad">{error}</span> : shown.length ? `Ctrl+Enter sends · Ctrl+1${shown.length > 1 ? '–' + Math.min(shown.length, 9) : ''} picks a suggestion` : 'Ctrl+Enter sends'}</span>
        {dial ? <select className="dial" aria-label="Mandate of the request this message opens" title={label ? `${label.label}: ${label.help}` : undefined} value={template} disabled={disabled || busy}
          onChange={e => turn(e.target.value as MandateTemplate)} data-testid="mandate-chip">
          {TEMPLATES.map(t => <option key={t.id} value={t.id} title={t.help}>{t.label}</option>)}
        </select> : null}
        <button className="btn primary" type="submit" disabled={disabled || busy || !text.trim()} data-testid={testId === 'composer' ? 'send' : testId + '-send'}>{busy ? 'Sending…' : envelope ? 'Grant and send' : 'Send'}</button>
      </div>
    </form>
  );
}
