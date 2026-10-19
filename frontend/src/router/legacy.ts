/** Every address of the previous workspace still opens: aliases come from pages.json, shared with the lead's page links. */
import catalog from './pages.json';

const ALIASES = catalog.aliases as Record<string, string>;

export function canonicalHash(hash: string): string {
  const value = (hash || '').replace(/^#/, '');
  const [path, query] = value.split('?');
  const suffix = query ? '?' + query : '';
  if (!path) return '#monitor' + suffix;
  if (path.startsWith('t/')) return '#' + path + suffix;
  if (path === 'new' || path.startsWith('new/')) return '#' + path + suffix;
  if (path in ALIASES) return '#' + ALIASES[path] + suffix;
  const [head, ...rest] = path.split('/');
  if (head in ALIASES) {
    const target = ALIASES[head];
    // #experiments/<trial> keeps its record; #agents/usage maps as a whole above.
    return '#' + [target, ...rest].join('/') + suffix;
  }
  return '#' + path + suffix;
}
