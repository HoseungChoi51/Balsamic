/** A visual the lead drew, in a sandboxed frame: no network, no navigation; the frame may only ask to open a page or draft text. */
import { useEffect, useRef } from 'react';
import { navigate, withThread } from '../../router/routes';
import { track } from '../../telemetry/events';

export function VisualFrame({ html, title, thread, onDraft }: { html: string; title: string; thread: string | null; onDraft?: (text: string) => void }) {
  const ref = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== ref.current?.contentWindow || !event.data || typeof event.data !== 'object') return;
      if (typeof event.data.open === 'string' && event.data.open.startsWith('#')) navigate(withThread(event.data.open, thread));
      else if (typeof event.data.draft === 'string' && onDraft) onDraft(event.data.draft.slice(0, 4000));
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [thread, onDraft]);
  useEffect(() => { track('visual.open', {}); }, []);
  return <iframe ref={ref} className="visual" title={title} sandbox="allow-scripts" srcDoc={html} referrerPolicy="no-referrer" style={{ width: '100%', minHeight: 240, border: '1px solid var(--line)', borderRadius: 8, background: 'white' }} data-testid="visual-frame" />;
}
