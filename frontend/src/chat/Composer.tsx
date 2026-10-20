import { useState } from 'react';

export function Composer({ onSend, disabled, why, placeholder, initial, testId = 'composer', suggestions = [], suggestionsNote }: { onSend: (text: string) => Promise<void>; disabled?: boolean; why?: string; placeholder?: string; initial?: string; testId?: string; suggestions?: { label: string; text: string }[]; suggestionsNote?: string }) {
  const [text, setText] = useState(initial || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    const value = text.trim();
    if (!value || busy || disabled) return;
    setBusy(true); setError(null);
    try { await onSend(value); setText(''); }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  return (
    <form className="composer" onSubmit={e => { e.preventDefault(); void submit(); }}>
      {suggestions.length && !text ? <div className="row wrap" data-testid="suggestions" data-live={suggestionsNote ? '1' : undefined}>{suggestions.map(s => <button key={s.text} type="button" className="btn small" disabled={disabled || busy} onClick={() => setText(s.text)} title={s.text}>{s.label}</button>)}{suggestionsNote ? <span className="faint small">{suggestionsNote}</span> : null}</div> : null}
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder={placeholder || 'Ask the lead, or type / for commands'} disabled={disabled || busy}
        data-testid={testId} onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void submit(); } }} />
      <div className="row">
        <span className="why grow">{disabled && why ? why : error ? <span className="pill bad">{error}</span> : 'Ctrl+Enter sends'}</span>
        <button className="btn primary" type="submit" disabled={disabled || busy || !text.trim()} data-testid={testId === 'composer' ? 'send' : testId + '-send'}>{busy ? 'Sending…' : 'Send'}</button>
      </div>
    </form>
  );
}
