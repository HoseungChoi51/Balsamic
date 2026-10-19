/** The lead's text: Markdown with math, record ids and page links turned into chips that open the page in this thread. */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { formatHash, navigate, parseHash, withThread } from '../../router/routes';
import { track } from '../../telemetry/events';

// One pass over the text: existing links and code are left alone; page addresses, bare record ids and H-labels become links.
const PAGE_FOR: Record<string, string> = { hypothesis: 'hypotheses', ph: 'hypotheses', trial: 'experiments', report: 'files/reports', draft: 'experiments/drafts', race: 'evolution/races',
  decision: 'inbox', approval: 'inbox', extension: 'inbox', compaction: 'inbox', finding: 'files/assets', asset: 'files/assets', thread: 'branches', study: 'evolution/races' };
const TOKEN = /(\[[^\]]*\]\([^)]*\))|(`[^`]*`)|((?<![\w\/#])#(?:note|hypotheses|experiments|evolution|files|inbox|monitor|library|branches)(?:\/[A-Za-z0-9_.-]+)*)|(\b(?:hypothesis|ph|trial|report|draft|race|decision|approval|extension|compaction|finding|asset|thread|study)_[A-Za-z0-9_-]+)|(\bH\d{2}\b)/g;

export function linkIds(text: string, aliases: Record<string, string> = {}) {
  return text.replace(TOKEN, (match, link: string, code: string, address: string, id: string, label: string) => {
    if (link || code) return match;
    if (address) return `[${address}](${address})`;
    if (id) return `[${id}](#${PAGE_FOR[id.split('_')[0]]}/${id})`;
    if (label) return aliases[label] ? `[${label}](#hypotheses/${aliases[label]})` : match;
    return match;
  });
}

export function Markdown({ text, thread, aliases, className = 'md' }: { text: string; thread: string | null; aliases?: Record<string, string>; className?: string }) {
  const prepared = linkIds(text, aliases);
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={{
        a: ({ href, children }) => {
          if (href && href.startsWith('#')) {
            const id = href.split('/').pop() || null;
            const route = parseHash(withThread(href, thread));
            const target = formatHash({ ...route, sel: id && /_/.test(id) ? id : route.sel });
            return <a href={target} className="chip" onClick={event => { event.preventDefault(); track('chip.open', { href }); navigate(target); }}>{children}</a>;
          }
          return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
        },
      }}>{prepared}</ReactMarkdown>
    </div>
  );
}
