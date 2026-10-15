import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, useReactFlow } from '@xyflow/react';
import type { Edge, Node, NodeProps } from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import '@xyflow/react/dist/style.css';
import { when } from './api';
import { Badge } from './ui';
import { TextContent } from './textContent';
import { currentStep, roleName } from './agentLive';
import type { LiveAgent } from './agentLive';
import { Excerpt, SavedDocuments, Verdicts, verdictTone } from './discussions';
import type { Assistant, Discussions, Proposal, Revision, Round, Turn } from './discussions';
import './discussionGraph.css';

type Kind = 'request' | 'round' | 'assistant' | 'response' | 'proposal';
type Card = { kind: Kind; eyebrow: string; title: string; chips: { text: string; tone?: string }[]; active?: boolean; step?: string; dimmed?: boolean };
type Detail = { kind: 'request'; round: Round } | { kind: 'round'; round: Round } | { kind: 'assistant'; assistant: Assistant; round: Round }
  | { kind: 'response'; turn: Turn; owner: string } | { kind: 'proposal'; revision: Revision; proposal: Proposal };
type Graph = { nodes: (Node<Card> & { detail: Detail })[]; edges: Edge[] };

const SIZE: Record<Kind, [number, number]> = { request: [210, 66], round: [180, 58], assistant: [230, 84], response: [210, 66], proposal: [230, 70] };
const line = (text?: string | null, length = 90) => { const plain = (text || '').replace(/\s+/g, ' ').trim(); return plain.length > length ? plain.slice(0, length - 1) + '…' : plain; };
const atWork = (status: string) => ['queued', 'running'].includes(status);
const toneColor: Record<string, string> = { green: '#3f8a5c', amber: '#b6874c', red: '#b5604a' };

/**
 * The review rounds as one graph, from the same saved records the list shows: what set each round off, who was asked,
 * what they answered, their verdicts on proposals, the response, and how proposals were created and revised.
 */
function build(data: Discussions, live: LiveAgent[]): Graph {
  const nodes: Graph['nodes'] = [], edges: Edge[] = [];
  const rounds = new Map(data.rounds.map(round => [round.number, round]));
  const revisions = new Map(data.proposals.flatMap(proposal => proposal.revisions.map(revision => [revision.id, { revision, proposal }] as const)));
  const add = (id: string, card: Card, detail: Detail) => nodes.push({ id, type: 'discussion', position: { x: 0, y: 0 }, data: card, detail,
    ariaLabel: `${card.eyebrow}: ${card.title}`, width: SIZE[card.kind][0], height: SIZE[card.kind][1] });
  const link = (source: string, target: string, label?: string, tone?: string, dashed = false) => edges.push({
    id: `${source}->${target}`, source, target, label, className: dashed ? 'dashed' : undefined,
    style: { stroke: tone ? toneColor[tone] : undefined, strokeWidth: tone ? 2 : 1.3 },
    labelStyle: tone ? { fill: toneColor[tone], fontWeight: 600 } : undefined,
    markerEnd: { type: MarkerType.ArrowClosed, color: tone ? toneColor[tone] : '#9aa58e', width: 14, height: 14 } });
  for (const round of [...data.rounds].sort((a, b) => a.number - b.number)) {
    const owner = roleName(round.owner || 'lead');
    add(`round-${round.number}`, { kind: 'round', eyebrow: when(round.started_at), title: `Round ${round.number} · ${owner.toLowerCase()}`,
      chips: round.active ? [{ text: 'in progress', tone: 'green' }] : [], active: round.active }, { kind: 'round', round });
    if (round.trigger.kind === 'request' || round.trigger.kind === 'lead') {
      add(`request-${round.number}`, { kind: 'request', eyebrow: round.trigger.kind === 'lead' ? 'The lead agent asked' : 'Your message', title: line(round.trigger.text, 110), chips: [] },
        { kind: 'request', round });
      link(`request-${round.number}`, `round-${round.number}`);
    } else if (round.trigger.kind === 'continued' && round.trigger.round && rounds.has(round.trigger.round)) {
      link(`round-${round.trigger.round}`, `round-${round.number}`, 'continued', undefined, true);
    }
    for (const assistant of round.assistants) {
      const now = live.find(agent => agent.agent_id === assistant.agent_id);
      const summary = [...assistant.turns].reverse().find(turn => turn.summary || turn.reply);
      add(`assistant-${assistant.agent_id}`, { kind: 'assistant', eyebrow: roleName(assistant.role), title: line(summary?.summary || summary?.reply || assistant.assignment),
        chips: assistant.verdicts.map(item => ({ text: item.verdict, tone: verdictTone[item.verdict] })).slice(0, 4),
        active: atWork(assistant.status), step: atWork(assistant.status) ? currentStep(now) || 'at work' : undefined }, { kind: 'assistant', assistant, round });
      link(`round-${round.number}`, `assistant-${assistant.agent_id}`);
      for (const turn of assistant.turns.filter(item => item.response && (item.response.summary || item.response.text))) {
        add(`response-${turn.response!.run_id}`, { kind: 'response', eyebrow: `${owner} responded`, title: line(turn.response!.summary || turn.response!.text), chips: [] },
          { kind: 'response', turn, owner });
        link(`assistant-${assistant.agent_id}`, `response-${turn.response!.run_id}`);
      }
      for (const verdict of assistant.verdicts)
        if (verdict.hypothesis_id && revisions.has(verdict.hypothesis_id))
          link(`assistant-${assistant.agent_id}`, `proposal-${verdict.hypothesis_id}`, verdict.verdict, verdictTone[verdict.verdict]);
    }
  }
  for (const proposal of data.proposals) for (const revision of proposal.revisions) {
    add(`proposal-${revision.id}`, { kind: 'proposal', eyebrow: revision.parent_ids?.length ? 'Revised proposal' : 'Proposal', title: line(revision.title || revision.id, 100),
      chips: revision.status ? [{ text: revision.status, tone: revision.status === 'finalist' ? 'green' : revision.status === 'archived' || revision.status === 'rejected' ? 'red' : undefined }] : [] },
      { kind: 'proposal', revision, proposal });
    for (const parent of revision.parent_ids || []) if (revisions.has(parent)) link(`proposal-${parent}`, `proposal-${revision.id}`, 'revised', undefined, true);
    if (revision.created_in_round && rounds.has(revision.created_in_round)) link(`round-${revision.created_in_round}`, `proposal-${revision.id}`, 'proposed', undefined, true);
  }
  // Duplicate edges (one assistant's two verdicts on one revision) are drawn once.
  return { nodes, edges: [...new Map(edges.map(edge => [edge.id, edge])).values()] };
}

/** Left to right, in the order things happened; computed again only when nodes appear or go, so live updates keep the picture still. */
function layout(graph: Graph): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 18, ranksep: 64, marginx: 12, marginy: 12 });
  g.setDefaultEdgeLabel(() => ({}));
  graph.nodes.forEach(node => g.setNode(node.id, { width: node.width!, height: node.height! }));
  graph.edges.forEach(edge => g.setEdge(edge.source, edge.target));
  dagre.layout(g);
  return new Map(graph.nodes.map(node => { const point = g.node(node.id); return [node.id, { x: point.x - node.width! / 2, y: point.y - node.height! / 2 }]; }));
}

/** The nodes that belong to one proposal's story: its revisions, who reviewed them, the rounds that produced or reviewed them,
    and what set those rounds off. */
function related(graph: Graph, proposal: Proposal): Set<string> {
  const keep = new Set(proposal.revisions.map(revision => `proposal-${revision.id}`));
  for (const edge of graph.edges) if (keep.has(edge.target) && /^(assistant|round)-/.test(edge.source)) keep.add(edge.source);
  for (const node of graph.nodes) if (node.detail.kind === 'assistant' && keep.has(node.id)) keep.add(`round-${node.detail.round.number}`);
  for (const edge of graph.edges) if (edge.source.startsWith('request-') && keep.has(edge.target)) keep.add(edge.source);
  return keep;
}

/** The newest round and those it asked: where the graph opens, at a size the cards can be read. */
function newest(graph: Graph): string[] {
  const rounds = graph.nodes.filter(node => node.detail.kind === 'round').map(node => (node.detail as { round: Round }).round.number);
  if (!rounds.length) return graph.nodes.map(node => node.id);
  const last = Math.max(...rounds);
  const asked = graph.edges.filter(edge => edge.source === `round-${last}` && edge.target.startsWith('assistant-')).map(edge => edge.target);
  return [`round-${last}`, `request-${last}`, ...asked].filter(id => graph.nodes.some(node => node.id === id));
}

/** Moves the view to the given cards when they change: the newest round at first, a followed proposal's story after. */
function Frame({ ids }: { ids: string[] }) {
  const flow = useReactFlow();
  const key = ids.join('|');
  useEffect(() => {
    const timer = window.setTimeout(() => void flow.fitView({ nodes: ids.map(id => ({ id })), padding: 0.25, minZoom: 0.45, maxZoom: 1.1, duration: 300 }), 60);
    return () => window.clearTimeout(timer);
  }, [key]);
  return null;
}

function DiscussionNode({ data }: NodeProps<Node<Card>>) {
  return <div className={`graph-card kind-${data.kind} ${data.active ? 'active' : ''} ${data.dimmed ? 'dimmed' : ''}`}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <span className="graph-eyebrow">{data.active && <i className="graph-pulse" />}{data.eyebrow}</span>
    <strong className="graph-title">{data.title}</strong>
    {(data.chips.length > 0 || data.step) && <span className="graph-chips">{data.step && <em>{data.step}</em>}
      {data.chips.map((chip, index) => <Badge key={index} tone={chip.tone || ''}>{chip.text}</Badge>)}</span>}
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>;
}
const nodeTypes = { discussion: DiscussionNode };

function DetailPanel({ detail, campaignId, onClose }: { detail: Detail; campaignId: string; onClose: () => void }) {
  let body: ReactNode;
  if (detail.kind === 'request') body = <><h3>{detail.round.trigger.kind === 'lead' ? 'The lead agent asked' : 'Your message'}</h3><TextContent text={detail.round.trigger.text} /></>;
  else if (detail.kind === 'round') body = <><h3>Round {detail.round.number}</h3>
    <p className="help-text">Run by the {roleName(detail.round.owner || 'lead').toLowerCase()} · {when(detail.round.started_at)} · {detail.round.assistants.length} {detail.round.assistants.length === 1 ? 'assistant' : 'assistants'}</p>
    <SavedDocuments campaignId={campaignId} documents={detail.round.owner_documents || []} /></>;
  else if (detail.kind === 'assistant') {
    const { assistant } = detail;
    body = <><h3>{roleName(assistant.role)}</h3><p className="help-text">{[assistant.model, assistant.status, when(assistant.created_at)].filter(Boolean).join(' · ')}</p>
      <h4>Asked</h4><Excerpt text={assistant.assignment} lines={4} more="Show the full assignment" />
      {assistant.turns.map(turn => <div key={turn.run_id} className="graph-turn">
        {turn.kind === 'follow_up' && <><h4>Asked again</h4><Excerpt text={turn.asked} lines={3} /></>}
        {(turn.summary || turn.reply || turn.error) && <><h4>Answered · {when(turn.created_at)}</h4>{turn.summary && <p>{turn.summary}</p>}
          {turn.reply ? <details open={!turn.summary}><summary>Full reply</summary><TextContent text={turn.reply} /></details> : turn.error && <p className="discussion-error">{turn.error}</p>}</>}
      </div>)}
      {assistant.verdicts.length > 0 && <h4>Verdicts</h4>}<Verdicts verdicts={assistant.verdicts} />
      <SavedDocuments campaignId={campaignId} documents={assistant.documents} /></>;
  } else if (detail.kind === 'response') {
    const response = detail.turn.response!;
    body = <><h3>{detail.owner} responded</h3><p className="help-text">{when(response.created_at)}</p>{response.summary && <p>{response.summary}</p>}
      {response.text && <details open={!response.summary}><summary>What it wrote</summary><TextContent text={response.text} /></details>}</>;
  } else {
    const { revision, proposal } = detail;
    body = <><h3>{revision.title || revision.id}</h3>
      <p className="help-text">{[revision.status, revision.created_by ? `proposed by the ${roleName(revision.created_by).toLowerCase()}${revision.created_in_round ? ` in round ${revision.created_in_round}` : ''}` : 'put in by hand',
        proposal.revisions.length > 1 ? `revision ${proposal.revisions.indexOf(revision) + 1} of ${proposal.revisions.length}` : ''].filter(Boolean).join(' · ')}</p>
      {revision.verdicts.length > 0 ? <ul className="graph-verdict-list">{revision.verdicts.map((item, index) => <li key={index}><Badge tone={verdictTone[item.verdict] || ''}>{item.verdict}</Badge>{item.round ? ` round ${item.round}` : ''}</li>)}</ul>
        : <p>No review yet.</p>}
      <a href="#hypotheses">Open the proposals</a></>;
  }
  return <aside className="graph-detail" aria-label="Selected part of the discussion"><button type="button" className="icon-button graph-close" aria-label="Close the details" onClick={onClose}>×</button>{body}</aside>;
}

export default function DiscussionGraph({ data, campaignId, live }: { data: Discussions; campaignId: string; live: LiveAgent[] }) {
  const graph = useMemo(() => build(data, live), [data, live]);
  const shape = graph.nodes.map(node => node.id).join('|') + '#' + graph.edges.map(edge => edge.id).join('|');
  const positions = useMemo(() => layout(graph), [shape]);
  const [selected, setSelected] = useState<string | null>(null), [focus, setFocus] = useState('');
  const proposal = data.proposals.find(item => item.id === focus);
  const keep = useMemo(() => proposal ? related(graph, proposal) : null, [shape, focus]);
  const start = useMemo(() => newest(graph), [shape]);
  useEffect(() => { if (selected && !graph.nodes.some(node => node.id === selected)) setSelected(null); }, [shape]);
  const nodes = graph.nodes.map(node => ({ ...node, position: positions.get(node.id) || { x: 0, y: 0 }, selected: node.id === selected,
    data: { ...node.data, dimmed: Boolean(keep && !keep.has(node.id)) } }));
  const edges = graph.edges.map(edge => keep && !(keep.has(edge.source) && keep.has(edge.target)) ? { ...edge, className: `${edge.className || ''} dimmed` } : edge);
  const detail = graph.nodes.find(node => node.id === selected)?.detail;
  if (!graph.nodes.length) return <p className="help-text">No rounds or proposals to draw yet.</p>;
  return <div className="discussion-graph">
    <div className="graph-toolbar">
      <label>Follow one proposal <select value={focus} onChange={event => setFocus(event.target.value)}>
        <option value="">All</option>{data.proposals.map(item => <option key={item.id} value={item.id}>{line(item.title || item.id, 70)}</option>)}</select></label>
      <span className="help-text">{data.rounds.length} rounds · {graph.nodes.filter(node => node.data.kind === 'assistant').length} assistants · {graph.nodes.filter(node => node.data.kind === 'proposal').length} proposals and revisions. It opens on the newest round; the fit button shows all of it. Click a card for its full text.</span>
    </div>
    <div className={`graph-stage ${detail ? 'with-detail' : ''}`}>
      <div className="graph-canvas" role="region" aria-label="Discussion graph">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} minZoom={0.15} maxZoom={1.6}
          nodesDraggable={false} nodesConnectable={false} edgesFocusable={false} onlyRenderVisibleElements={false}
          onNodeClick={(_, node) => setSelected(node.id)} onPaneClick={() => setSelected(null)}>
          <Background gap={22} size={1} /><Controls showInteractive={false} fitViewOptions={{ padding: 0.08 }} /><MiniMap pannable zoomable nodeStrokeWidth={2} />
          <Frame ids={keep ? [...keep] : start} />
        </ReactFlow>
      </div>
      {detail && <DetailPanel detail={detail} campaignId={campaignId} onClose={() => setSelected(null)} />}
    </div>
  </div>;
}
