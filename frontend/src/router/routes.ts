/** Hash routes: #t/<thread>/<page>[/<sub>][/<id>]?sel=<id>&tab=<name>. #new starts a campaign; the bare address is #home. Old addresses canonicalize (legacy.ts). */
import catalog from './pages.json';
import { canonicalHash } from './legacy';

export type PageName = keyof typeof catalog.pages;
export interface Route { thread: string | null; page: PageName; sub: string | null; id: string | null; sel: string | null; tab: string | null; raw: string }

export const PAGES = catalog.pages as Record<string, { title: string; description: string; subs?: Record<string, string>; agent?: string }>;
export const RAIL = catalog.rail as PageName[];

export function parseHash(hash: string): Route {
  const canonical = hash ? canonicalHash(hash) : '#home';
  const [pathPart, queryPart] = canonical.replace(/^#/, '').split('?');
  const query = new URLSearchParams(queryPart || '');
  const parts = pathPart.split('/').filter(Boolean);
  let thread: string | null = null;
  if (parts[0] === 't' && parts[1]) { thread = parts[1]; parts.splice(0, 2); }
  const page = (parts[0] && parts[0] in PAGES ? parts[0] : 'monitor') as PageName;
  if (page === 'new' || page === 'home') return { thread: null, page, sub: null, id: parts[1] || null, sel: query.get('sel'), tab: query.get('tab'), raw: canonical };
  const subs = PAGES[page].subs || {};
  let sub: string | null = null; let id: string | null = null;
  if (parts[1] && parts[1] in subs) { sub = parts[1]; id = parts[2] || null; } else id = parts[1] || null;
  return { thread, page, sub, id, sel: query.get('sel'), tab: query.get('tab'), raw: canonical };
}

export function formatHash(route: Partial<Route> & { page: string }, thread?: string | null): string {
  const t = thread === undefined ? route.thread : thread;
  const parts = [t ? `t/${t}` : null, route.page, route.sub || null, route.id || null].filter(Boolean);
  const query = new URLSearchParams();
  if (route.sel) query.set('sel', route.sel);
  if (route.tab) query.set('tab', route.tab);
  return '#' + parts.join('/') + (query.toString() ? '?' + query.toString() : '');
}

export const CHAT_WINDOW = 'balsamic-chat';
let channel: BroadcastChannel | null = null;
/** The channel between the main window and a detached chat window (navigate, reattach, closed). */
export function chatChannel(): BroadcastChannel | null {
  if (channel) return channel;
  try { channel = new BroadcastChannel('balsamic.chat'); } catch { channel = null; }
  return channel;
}
export function isDetachedWindow() { return typeof window !== 'undefined' && window.name === CHAT_WINDOW; }

export function navigate(hash: string) {
  if (isDetachedWindow()) {
    // The detached chat keeps showing the chat; the page it links to opens in the main window.
    const target = parseHash(hash);
    if (target.page !== 'chat') { chatChannel()?.postMessage({ type: 'navigate', hash }); return; }
  }
  if (location.hash !== hash) location.hash = hash;
}

/** A page link written by the lead (#experiments/trial_x) opened in the current thread. */
export function withThread(hash: string, thread: string | null) {
  const route = parseHash(hash);
  return formatHash(route, route.thread || thread);
}

export function pageTitle(page: string, sub: string | null) {
  const entry = PAGES[page];
  if (!entry) return page;
  return sub && entry.subs?.[sub] ? `${entry.title} · ${entry.subs[sub]}` : entry.title;
}
