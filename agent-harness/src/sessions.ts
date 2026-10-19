import { SessionManager } from '@earendil-works/pi-coding-agent';

// One Pi session per lead agent; a conversation thread is a branch of its tree (docs/ui-workspace.md, D).
// These views read the tree; setLeaf moves it between turns. The supervisor positions the leaf before a prompt.
const PREVIEW = 160;

function text(entry: any) {
  if (entry.type === 'message') {
    const content = entry.message?.content;
    const value = typeof content === 'string' ? content : Array.isArray(content) ? content.filter((p: any) => p.type === 'text').map((p: any) => p.text).join(' ') : '';
    return value.replace(/\s+/g, ' ').trim();
  }
  if (entry.type === 'branch_summary') return String(entry.summary || '');
  return '';
}

export function describe(entry: any) {
  return {id: entry.id, parent_id: entry.parentId, type: entry.type, timestamp: entry.timestamp,
    ...(entry.type === 'message' ? {role: entry.message?.role, tool_calls: Array.isArray(entry.message?.content) ? entry.message.content.filter((p: any) => p.type === 'toolCall').length : 0} : {}),
    ...(entry.type === 'branch_summary' ? {from_id: entry.fromId} : {}),
    preview: text(entry).slice(0, PREVIEW), bytes: Buffer.byteLength(JSON.stringify(entry))};
}

export function open(file: string | null | undefined): any {
  if (!file) return null;
  return SessionManager.open(file);
}

/** The whole tree, each node described without hidden reasoning; the current leaf marked. */
export function tree(sm: any) {
  const leaf = sm.getLeafId();
  const walk = (nodes: any[]): any[] => nodes.map(node => ({...describe(node.entry), label: node.label, leaf: node.entry.id === leaf, children: walk(node.children)}));
  return {session_id: sm.getSessionId(), session_file: sm.getSessionFile(), leaf_id: leaf, entries: sm.getEntryCount(), tree: walk(sm.getTree())};
}

/** The path from the root to a leaf (the current one by default), oldest first; `after` skips through that entry. */
export function entries(sm: any, options: {after?: string | null, leaf?: string | null} = {}) {
  const leaf = options.leaf || sm.getLeafId();
  if (leaf && !sm.getEntry(leaf)) throw new Error('Unknown session entry');
  let path = sm.getBranch(leaf || undefined).map(describe);
  if (options.after) {
    const index = path.findIndex((entry: any) => entry.id === options.after);
    path = index >= 0 ? path.slice(index + 1) : path;
  }
  return {leaf_id: leaf, entries: path};
}

/** What the model would see from a leaf: the entries Pi keeps after compaction and branch summaries, with their sizes. */
export function context(sm: any, leaf?: string | null) {
  const current = sm.getLeafId();
  if (leaf && !sm.getEntry(leaf)) throw new Error('Unknown session entry');
  const moved = Boolean(leaf && leaf !== current);
  if (moved) sm.branch(leaf);
  try {
    const items = sm.buildContextEntries().map(describe);
    const bytes = items.reduce((sum: number, item: any) => sum + item.bytes, 0);
    return {leaf_id: sm.getLeafId(), entries: items.length, bytes, messages: items.filter((i: any) => i.type === 'message').length,
      summaries: items.filter((i: any) => i.type === 'branch_summary').length, compactions: items.filter((i: any) => i.type === 'compaction').length, items};
  } finally { if (moved && current) sm.branch(current); }
}

/**
 * Move the leaf to an entry. With a summary, Pi records what the branch being left concluded as a branch_summary under
 * the destination, so the model carries it; without one the destination branch continues exactly where it was.
 */
export function setLeaf(sm: any, entryId: string, summary?: string | null) {
  if (!sm.getEntry(entryId)) throw new Error('Unknown session entry');
  const previous = sm.getLeafId();
  if (summary) {
    const id = sm.branchWithSummary(entryId, summary);
    return {previous_leaf_id: previous, leaf_id: sm.getLeafId(), summary_entry_id: id};
  }
  sm.branch(entryId);
  return {previous_leaf_id: previous, leaf_id: sm.getLeafId(), summary_entry_id: null};
}

/** One branch as its own session file (an export, or the fallback of one session per thread). */
export function exportBranch(sm: any, leaf?: string | null) {
  const target = leaf || sm.getLeafId();
  if (!target || !sm.getEntry(target)) throw new Error('Unknown session entry');
  return {leaf_id: target, session_file: sm.createBranchedSession(target)};
}
