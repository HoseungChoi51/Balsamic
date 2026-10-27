/** The lead's text: Markdown with math, record ids and page links turned into chips that open the page in this thread, made readable. */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { formatHash, navigate, parseHash, withThread } from '../../router/routes';
import { track } from '../../telemetry/events';

// One pass over the text: existing links and code are left alone; page addresses, bare record ids and H-labels become links.
const PAGE_FOR: Record<string, string> = { hypothesis: 'hypotheses', ph: 'hypotheses', trial: 'experiments', report: 'files/reports', draft: 'experiments/drafts', race: 'evolution/races',
  decision: 'inbox', approval: 'inbox', extension: 'inbox', compaction: 'inbox', finding: 'files/assets', asset: 'files/assets', thread: 'branches', study: 'evolution/races' };
// Formulas are left alone too: an H-label or an id inside one is part of the math.
const TOKEN = /(\[[^\]]*\]\([^)]*\))|(`[^`]*`|\$\$[\s\S]*?\$\$|(?<!\\)\$[^$\n]+?(?<!\\)\$)|((?<![\w\/#])#(?:note|hypotheses|experiments|evolution|files|inbox|monitor|library|branches)(?:\/[A-Za-z0-9_.-]+)*)|(\b(?:hypothesis|ph|trial|report|draft|race|decision|approval|extension|compaction|finding|asset|thread|study)_[A-Za-z0-9_-]+)|(\bH\d{2}\b)/g;

export function linkIds(text: string, aliases: Record<string, string> = {}) {
  return text.replace(TOKEN, (match, link: string, code: string, address: string, id: string, label: string) => {
    if (link || code) return match;
    if (address) return `[${address}](${address})`;
    if (id) return `[${id}](#${PAGE_FOR[id.split('_')[0]]}/${id})`;
    if (label) return aliases[label] ? `[${label}](#hypotheses/${aliases[label]})` : match;
    return match;
  });
}

// Models also write LaTeX's own delimiters, \(…\) inline and \[…\] for a display; remark-math reads dollars only, so they become
// $…$ and a $$ block. Code is left alone.
const DELIMITERS = /(```[\s\S]*?(?:```|$))|(`[^`]*`)|\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]/g;

export function dollarMath(text: string) {
  return text.replace(DELIMITERS, (match, block: string, code: string, inline: string, display: string) =>
    block || code ? match : inline !== undefined ? `$${inline.trim()}$` : `\n$$\n${display.trim()}\n$$\n`);
}

const MATH = /\$\$[\s\S]*?\$\$|(?<!\\)\$[^$\n]+?(?<!\\)\$/g;

/** The start of a text for a list, cut near `limit` and never inside a formula. */
export function clip(text: string, limit = 240) {
  if (text.length <= limit) return text;
  let cut = limit;
  for (const m of text.matchAll(MATH)) {
    const start = m.index ?? 0, end = start + m[0].length;
    if (start < cut && cut < end) { cut = start > limit / 2 ? start : end; break; }
  }
  return text.slice(0, cut).trimEnd() + ' …';
}

// Dollars are math only in a pair (pandoc's rule): the opening one has no space after it, the closing one no space before it and no
// digit after it. Any other dollar is a price and is escaped, so "$20 and ... $20" never becomes one long formula. Code and $$ blocks are left alone.
const DOLLAR = /(```[\s\S]*?(?:```|$))|(`[^`]*`)|(\\[\s\S])|(\$\$[\s\S]*?\$\$)|(\$(?![\s$])(?:\\[\s\S]|\n(?![ \t]*\n)|[^$\\\n])*?(?<!\s)\$(?!\d))|\$/g;

export function escapeStrayDollars(text: string) {
  return text.replace(DOLLAR, (match, ...kept: (string | undefined)[]) => kept.slice(0, 5).some(Boolean) ? match : '\\$');
}

// Agents' text, the lead's included, often comes as one dense paragraph. A paragraph of more than a few sentences is split
// after every few of them, and a single line break is kept as one (a chat convention). Code, math, links, emphasis, lists,
// tables and headings are left as they are, and so is a sentence ending after an abbreviation.
const LONG_PARAGRAPH = 280;
const PARAGRAPH_SENTENCES = 3;
const PARAGRAPH_CHARS = 320;
const BLOCK = /^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|>|\||```|~~~|\$\$|<)/;
const KEPT = /`[^`\n]*`|\$[^$\n]+\$|\[[^\]\n]*\]\([^)\n]*\)|\*\*[^*\n]+\*\*|https?:\/\/\S+/g;
const ABBREVIATION = /(?:\b(?:e\.g|i\.e|vs|etc|cf|approx|Fig|Eq|No|al|resp)\.|(?:^|\s)[A-Z]\.)$/;

function paragraphs(line: string) {
  if (line.length <= LONG_PARAGRAPH || BLOCK.test(line)) return [line];
  const kept: string[] = [];
  const masked = line.replace(KEPT, match => `\u0000${kept.push(match) - 1}\u0000`);
  const sentences: string[] = [];
  for (const piece of masked.split(/(?<=[.!?])\s+(?=[A-Z0-9("“*_\u0000])/)) {
    if (sentences.length && ABBREVIATION.test(sentences[sentences.length - 1])) sentences[sentences.length - 1] += ' ' + piece;
    else sentences.push(piece);
  }
  if (sentences.length <= PARAGRAPH_SENTENCES + 1) return [line];
  const groups: string[][] = [[]];
  for (const sentence of sentences) {
    const group = groups[groups.length - 1];
    if (group.length && (group.length >= PARAGRAPH_SENTENCES || group.join(' ').length + sentence.length > PARAGRAPH_CHARS)) groups.push([sentence]);
    else group.push(sentence);
  }
  const last = groups[groups.length - 1];
  if (groups.length > 1 && last.length === 1 && last[0].length < 80) groups[groups.length - 2].push(...groups.pop()!);   // no stray short tail
  return groups.map(group => group.join(' ').replace(/\u0000(\d+)\u0000/g, (_, index: string) => kept[Number(index)]));
}

export function readable(text: string) {
  const lines = text.split('\n');
  const out: string[] = [];
  let code = false, math = false;
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (/^(```|~~~)/.test(trimmed)) code = !code;
    const verbatim = code || math || /^(```|~~~)/.test(trimmed);
    // A line that is one $$…$$ formula is a display; remark-math reads it as a display only with the $$ on lines of their own.
    const display = !verbatim && /^\$\$([^$]+)\$\$$/.exec(trimmed);
    if (display) { out.push('$$', display[1].trim(), '$$'); return; }
    if ((line.match(/\$\$/g) || []).length % 2) math = !math;
    if (verbatim || math || line.includes('$$')) { out.push(line); return; }
    const next = lines[index + 1];
    // A single line break inside prose is a line break, not a space.
    const breaks = trimmed && next !== undefined && next.trim() && !BLOCK.test(line) && !BLOCK.test(next) && !/^\s/.test(next);
    const parts = paragraphs(line);
    out.push(...parts.slice(0, -1).flatMap(part => [part, '']), parts[parts.length - 1] + (breaks ? '  ' : ''));
  });
  return out.join('\n');
}

export function Markdown({ text, thread, aliases, className = 'md' }: { text: string; thread: string | null; aliases?: Record<string, string>; className?: string }) {
  const prepared = linkIds(escapeStrayDollars(readable(dollarMath(text))), aliases);
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
