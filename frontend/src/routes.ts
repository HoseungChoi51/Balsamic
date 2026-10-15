import { useEffect, useState } from 'react';

/** The current address of an older page: pages merged into others keep their links, as saved in the agents' messages. */
export function canonicalHash(hash: string): string {
  const [first, ...rest] = hash.replace(/^#/, '').split('/');
  if (first === 'discussions') return ['hypotheses', 'rounds', ...rest].join('/');
  if (first === 'drafts') return 'experiments';
  if (first === 'models') return 'agents/models';
  if (first === 'llm-usage') return 'agents/usage';
  if (first === 'memory') return 'agents/guidance';
  if (first === 'notebook' && rest[0] === 'agent-log') return 'agents/log';
  return hash.replace(/^#/, '');
}

/** The tab of a page with tabs, from the address `#page/tab`; the first tab has no segment of its own. */
export function useSubpage(page: string, tabs: readonly string[]): [string, (tab: string) => void] {
  const read = () => {
    const [first, second] = canonicalHash(location.hash).split('/');
    return first === page && tabs.includes(second) ? second : tabs[0];
  };
  const [tab, setTab] = useState(read);
  useEffect(() => {
    const change = () => setTab(read());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  return [tab, next => { location.hash = next === tabs[0] ? page : `${page}/${next}`; }];
}
