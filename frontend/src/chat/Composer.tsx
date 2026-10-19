import { useState } from 'react';

export function Composer({ onSend, disabled, why, placeholder }: { onSend: (text: string) => Promise<void>; disabled?: boolean; why?: string; placeholder?: string }) {
  const [text, setText] = useState('');
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
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder={placeholder || 'Ask the lead, or type / for commands'} disabled={disabled || busy}
        data-testid="composer" onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void submit(); } }} />
      <div className="row">
        <span className="why grow">{disabled && why ? why : error ? <span className="pill bad">{error}</span> : 'Ctrl+Enter sends'}</span>
        <button className="btn primary" type="submit" disabled={disabled || busy || !text.trim()} data-testid="send">{busy ? 'Sending…' : 'Send'}</button>
      </div>
    </form>
  );
}
