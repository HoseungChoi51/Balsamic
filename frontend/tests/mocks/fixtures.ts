/** Records a mocked workspace answers with. One campaign in its generate stage, one main thread, a few messages and runs. */
export const CAMPAIGN_ID = 'demo';
export const THREAD_ID = `thread_main_${CAMPAIGN_ID}`;
export const workspace = { workspace_id: 'ws_test', max_workers: 2, dev_mode: true, provider: { configured: true, providers: { 'openai-codex': {} } }, level: 'balanced', service: 'balsamic' };
export const campaignRow = { next_step: null, id: CAMPAIGN_ID, name: 'Demo campaign', version: 3, objective: 'Find a better deflector', autonomy: 'delegated', stage: 'generate', stage_pinned: false,
  stage_basis: 'strategies are being proposed and screened', autopilot: { enabled: false }, problem_note_id: null, active_thread_id: THREAD_ID, created_at: '2026-10-19T08:00:00Z' };
export const campaign = { id: CAMPAIGN_ID, name: 'Demo campaign', version: 3, objective: 'Find a better deflector', autonomy: 'delegated', compute_budget_seconds: 3600, llm_budget_usd: 5,
  delegated_trial_seconds: 60, validation_reserve_seconds: 120, implementation_compute_budget_seconds: 0, active_study_id: 'study_1' };
export const summary = { campaign, row: campaignRow, tasks: [{ id: 'task_1', name: 'Quadratic', problem_id: 'bounded_continuous', split: 'development' }], charter: null, budget: { allocated_seconds: 120, budget_seconds: 3600 },
  stage: { stage: 'generate', pinned: false, basis: 'strategies are being proposed and screened' }, counts: { task: 1, hypothesis: 2, trial: 2, study: 1, adaptive_race: 0, decision: 1, thread: 1, message: 2 },
  studies: [{ id: 'study_1', goal: 'Find a better deflector' }], trials: [] };
export const thread = { id: THREAD_ID, campaign_id: CAMPAIGN_ID, name: 'main', title: 'Demo campaign', parent_thread_id: null, fork_message_id: null, status: 'active', merged_into: null, pinned_ids: [], excluded_ids: [],
  summary: null, guidance_revision: 2, message_count: 2, last_message_id: 'message_2', last_activity_at: '2026-10-19T08:05:00Z', busy: false, queued: 0, created_at: '2026-10-19T08:00:00Z' };
export const threads = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, threads: [thread], lead: { id: 'lead_demo', status: 'waiting' }, request_open: false, active_run: null };
export const BRANCH_ID = `thread_ab12cd34ef_${CAMPAIGN_ID}`;
export const branch = { ...thread, id: BRANCH_ID, name: 'Second coupling', title: 'Second coupling', parent_thread_id: THREAD_ID, fork_message_id: 'message_2', fork_entry_id: 'e2', status: 'active', message_count: 1,
  last_message_id: 'message_b1', busy: false, queued: 0, unread: true, summary: null, strip: [{ at: '2026-10-19T08:10:00Z', glyph: 'message', id: 'message_b1', who: 'you' }] };
export const parked = { ...branch, id: `thread_parked00_${CAMPAIGN_ID}`, title: 'Annealing side quest', name: 'Annealing side quest', status: 'parked', unread: false,
  summary: { text: '1 message from you, 1 from the lead. Last from the lead: Annealing is slower.', strip: [{ at: '2026-10-19T08:11:00Z', glyph: 'message', id: 'x', who: 'you' }, { at: '2026-10-19T08:12:00Z', glyph: 'run', id: 'y' }], as_of_message_id: 'x', written_by: 'activity_only', stale: false, edited: false } };
export const branchMessages = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, thread_id: BRANCH_ID, truncated: false, parent_path: [{ thread_id: THREAD_ID, title: 'Demo campaign', fork_message_id: 'message_2' }],
  inherited: [{ thread_id: THREAD_ID, title: 'Demo campaign', count: 2, from: 'message_1', to: 'message_2' }], fork_message_id: 'message_2', questions: [], placeholders: [], status: 'active', merged_into: null, summary: null,
  inherited_messages: [] as unknown[], messages: [{ id: 'message_b1', campaign_id: CAMPAIGN_ID, role: 'user', origin: 'researcher', thread_id: BRANCH_ID, content: 'What about the second coupling?', created_at: '2026-10-19T08:10:00Z' }] };
export const context = { thread_id: THREAD_ID, layers: { project: { items: [{ id: CAMPAIGN_ID, kind: 'campaign', title: 'Demo campaign', bytes: 120 }, { id: 'task_1', kind: 'task', title: 'Quadratic', bytes: 400 }], bytes: 520 },
  branch: { entries_since_fork: 2, summary_entries: 0, bytes: 2048, leaf_entry_id: 'e4', measured: false, basis: 'estimated' }, live: { items: [{ id: 'hypothesis_a', kind: 'hypothesis', title: 'Random restarts', status: 'proposed', revision: null, excluded: false }] } },
  pinned_ids: ['hypothesis_a'], excluded_ids: [], lab_events_since_last_turn: 1 };
export const noteView = { note: { id: `note_${CAMPAIGN_ID}`, title: 'Demo campaign', current_revision: 2, adopted_revision: null, charter_id: null, import_id: null, status: 'drafting' },
  revision: { id: `note_${CAMPAIGN_ID}_r2`, revision: 2, title: 'Demo campaign', author: 'lead', reason: 'first draft', created_at: '2026-10-19T08:20:00Z', glossary: [{ term: 'efficiency', definition: 'power in the target order over incident power' }],
    sections: { objective: { text: 'Maximize the first-order **efficiency** $\\eta$ of a binary grating.', items: [], latex: ['\\eta = P_1 / P_0'] }, knobs: { text: '', items: ['period p', 'fill factor f'], latex: [] }, observables: { text: 'Measured efficiency per design.', items: [], latex: [] },
      noise: { text: '', items: [], latex: [] }, constraints: { text: '', items: ['0 < f < 1'], latex: [] }, confounders: { text: '', items: [], latex: [] }, open_questions: { text: '', items: ['Which wavelength?'], latex: [] } } },
  revisions: [{ id: 'r1', revision: 1, author: 'researcher', reason: 'the campaign question', created_at: '2026-10-19T08:00:00Z' }, { id: 'r2', revision: 2, author: 'lead', reason: 'first draft', created_at: '2026-10-19T08:20:00Z' }],
  annotations: [{ id: 'annotation_1', anchor: { revision: 2, section: 'knobs', start: 0, end: 8, quote: 'period p' }, kind: 'challenge', question: 'Why not the depth too?', tier: 'lead', escalated_from_tier: null, status: 'answered', created_at: '2026-10-19T08:30:00Z',
    answer: { text: 'Depth is fixed by the process; it is a constraint, not a knob.', answered_by: 'lead' }, proposed_edit: { sections: { constraints: { items: ['0 < f < 1', 'depth fixed at 300 nm'] } } }, visual_id: null }],
  charter: null, sections: ['objective', 'knobs', 'observables', 'noise', 'constraints', 'confounders', 'open_questions'],
  titles: { objective: 'Objective', knobs: 'Knobs', observables: 'Observables', noise: 'Noise', constraints: 'Constraints', confounders: 'Confounders', open_questions: 'Open questions' } };
export const messages = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, thread_id: THREAD_ID, truncated: false, inherited: [], inherited_messages: [], parent_path: [], fork_message_id: null, questions: [], placeholders: [], status: 'active', merged_into: null, summary: null,
  messages: [
    { id: 'message_1', campaign_id: CAMPAIGN_ID, role: 'user', origin: 'researcher', content: 'What do we know about the deflector so far?', created_at: '2026-10-19T08:01:00Z' },
    { id: 'message_2', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lead', content: 'Two proposals exist: hypothesis_a (H01) and hypothesis_b. The first run is trial_1; see #experiments/trial_1 and the inbox at #inbox.', created_at: '2026-10-19T08:05:00Z' },
  ] };
export const AGENTS_THREAD_ID = 'thread_agents_0123456789_' + CAMPAIGN_ID;
export const agentsThread = { ...thread, id: AGENTS_THREAD_ID, name: 'Review of the proposals', title: 'Review of the proposals', kind: 'agents', parent_thread_id: THREAD_ID, fork_message_id: 'message_5', root_run_id: 'pi_run_5', message_count: 2, strip: [] };
export const foldedMessages = { ...messages, messages: [
  { id: 'message_1', campaign_id: CAMPAIGN_ID, role: 'user', origin: 'researcher', content: 'What do we know about the deflector so far? Give me the short version.', fold_title: 'Asked what is known; two proposals and one run exist', created_at: '2026-10-19T08:01:00Z' },
  { id: 'message_2', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lead', content: 'Two proposals exist: hypothesis_a (H01) and hypothesis_b. The first run is trial_1.', created_at: '2026-10-19T08:05:00Z' },
  { id: 'message_3', campaign_id: CAMPAIGN_ID, role: 'user', origin: 'researcher', content: 'Try the second one with a warm start.', created_at: '2026-10-19T08:06:00Z' },
  { id: 'message_4', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lead', content: 'Started trial_2 on hypothesis_b.', created_at: '2026-10-19T08:07:00Z' },
  { id: 'message_5', campaign_id: CAMPAIGN_ID, role: 'user', origin: 'researcher', content: 'Let the agents review the proposals.', created_at: '2026-10-19T08:08:00Z' },
  { id: 'message_agents_link_' + AGENTS_THREAD_ID, campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lab_event', kind: 'agents_link', link_thread_id: AGENTS_THREAD_ID, content: 'Agents are working on this request in a side conversation: Review of the proposals', created_at: '2026-10-19T08:08:30Z' },
  { id: 'message_6', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lead', content: 'The moderator is reviewing them; the result comes back here.', created_at: '2026-10-19T08:09:00Z' },
  { id: 'message_7', campaign_id: CAMPAIGN_ID, role: 'user', origin: 'researcher', content: 'How long will that take?', created_at: '2026-10-19T08:10:00Z' },
  { id: 'message_8', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lead', content: 'A few minutes.', created_at: '2026-10-19T08:11:00Z' },
] };
export const agentsMessages = { ...messages, thread_id: AGENTS_THREAD_ID, parent_path: [{ thread_id: THREAD_ID, title: 'Demo', fork_message_id: 'message_5' }], messages: [
  { id: 'message_page_request_1', campaign_id: CAMPAIGN_ID, role: 'lead', origin: 'lead', agent_role: 'lead', to_agent_id: 'agent_mod', thread_id: AGENTS_THREAD_ID, content: 'Run a review round on the five proposals.', created_at: '2026-10-19T08:08:40Z' },
  { id: 'message_assignment_1', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'page_agent', agent_role: 'proposal_reviewer', agent_id: 'agent_rev', thread_id: AGENTS_THREAD_ID, content: 'Recorded verdicts on all five.', created_at: '2026-10-19T08:09:10Z' },
] };
export const monitor = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, rows: { problem: { name: 'Demo campaign', objective: 'Find a better deflector', tasks: 1 },
  budget: { worker: { allocated_seconds: 120, actual_seconds: 54, forecast_seconds: 160, forecast_basis: 'measured use plus the remaining allotment of live runs', budget_seconds: 3600, exhausted: false }, llm: { cap_usd: 5, agent_charged_usd: 0.42, implementation_committed_usd: 0, spent_usd: 0.42, exhausted: false } },
  compute: { busy: 1, limit: 2, queued: 0, level: 'balanced', gpu: { reported: true, measured: true, devices: 1, busy: false, utilization_percent: 3, memory_used_bytes: 1073741824, memory_total_bytes: 25769803776, basis: 'measured by nvidia-smi' } }, autopilot: { enabled: false, reason: 'autopilot is off', can_start: false },
  agents: { status: 'waiting', headline: 'Lead agent is waiting for your request', active: false }, needs_you: { decisions: 1, issues: 0, questions: 0 } }, pill: { state: 'attention', text: '1 waiting for you', row: 'needs_you' }, digest_id: null };
export const inbox = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, issues: [], questions: [], resolved: [],
  decisions: [{ id: 'extension_1', title: 'Extend trial trial_1 by 120 s?', proposal: 'The lead agent asks for 120 s more on trial trial_1.', rationale: 'The curve is still improving.', status: 'pending', resolution_revision: 0, requested_by: 'lead',
    options: [{ id: '0', label: 'Extend by 120 s', description: 'Runs under your authority.' }, { id: '1', label: 'Keep the current allocation', description: 'The requester is told.' }], recommendation: '0', created_at: '2026-10-19T08:06:00Z',
    freshness: { state: 'ready', reason: '', blocked_choice_ids: [] }, presentation: {} }] };
export const experiments = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, drafts: [], profiles: [], rules: { revision: 0, long_run_threshold_seconds: 600 }, checks: [],
  short: [{ id: 'trial_1', campaign_id: CAMPAIGN_ID, task_id: 'task_1', algorithm: 'random_search', status: 'running', seed: 0, max_steps: 200, wall_seconds: 60, created_at: '2026-10-19T08:03:00Z', progress: { best_objective: 0.41, evaluations: 80 }, hypothesis_id: 'hypothesis_a' }],
  long: [{ id: 'trial_2', campaign_id: CAMPAIGN_ID, task_id: 'task_1', algorithm: 'cma_es', status: 'stopped', seed: 1, max_steps: 5000, wall_seconds: 1200, created_at: '2026-10-19T07:00:00Z', result: { best_objective: 0.52, evaluations: 2100 }, stopped_by: 'researcher', hypothesis_id: 'hypothesis_b' }] };
export const hypotheses = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, aliases: [{ record_id: 'hypothesis_a', label: 'H01' }, { record_id: 'hypothesis_b', label: 'H02' }], rounds: { rounds: [] },
  hypotheses: [{ id: 'hypothesis_a', title: 'Random restarts', status: 'proposed', mechanism: 'Restart from the best of a random batch.', rationale: 'Cheap baseline.', algorithm: 'random_search', origin: 'pi', reviews: [], readiness: { state: 'testable', eligible: true, reason: '' }, created_at: '2026-10-19T08:02:00Z' },
    { id: 'hypothesis_b', title: 'CMA-ES with warm start', status: 'investigating', mechanism: 'Covariance adaptation from the previous best.', rationale: 'Smooth landscape.', algorithm: 'cma_es', origin: 'pi', reviews: [{ id: 'review_1', author: 'proposal_reviewer', verdict: 'test', text: 'Plausible; test it.', created_at: '2026-10-19T08:03:00Z' }], readiness: { state: 'testable', eligible: true, reason: '' }, created_at: '2026-10-19T08:02:30Z' }] };
export const files = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, assets: [], findings: [], reports: [], report_jobs: [], sources: [], artifacts: [] };
export const agents = { configuration: { enabled: true, status: 'running', control_revision: 0, provider: { configured: true } }, agents: [{ id: 'lead_demo', role: 'lead', status: 'waiting', activity: 'Waiting for your request', model: 'gpt-5', last_activity_at: '2026-10-19T08:05:00Z' }], questions: [], aliases: [], development: {} };

export const evolution = { campaign_id: CAMPAIGN_ID, event_cursor: 10, unchanged: false, rounds: 1, races: [], finalists: [], confirmations: [], interventions: [],
  stage: { stage: 'generate', pinned: false, basis: 'strategies are being proposed and screened' },
  progress: { best_so_far: 0.52, live_trials: [{ id: 'trial_1', hypothesis_id: 'hypothesis_a', status: 'running' }], finalist_rungs: [] },
  nodes: [
    { id: 'hypothesis_a', label: 'H01', title: 'Random restarts', status: 'proposed', origin: 'pi', actor: 'lead', autonomous: false, round: 0, parent_links: [], algorithm: 'random_search', worker_seconds: 54, allotted_seconds: 60, evaluations: 80,
      best: { score: 0.41, basis: 'measured', source: 'progress', trial_id: 'trial_1', interval: null }, highest_rung_seconds: 60, race: null, review: { verdict: null, count: 0, readiness: { state: 'testable', eligible: true } },
      implementation_readiness: { runnable: true }, trial_ids: ['trial_1'], live_trials: 1, finalist: false, confirmation: null, stop_reason: null, created_at: '2026-10-19T08:02:00Z', stage: 'screening', curve: [{ x: 10, y: .2 }, { x: 80, y: .41 }] },
    { id: 'hypothesis_b', label: 'H02', title: 'CMA-ES with warm start', status: 'investigating', origin: 'pi', actor: 'lead', autonomous: false, round: 1, parent_links: [{ id: 'hypothesis_a', kind: 'variant' }], algorithm: 'cma_es', worker_seconds: 1100, allotted_seconds: 1200, evaluations: 2100,
      best: { score: 0.52, basis: 'measured', source: 'result', trial_id: 'trial_2', interval: null }, highest_rung_seconds: 1200, race: null, review: { verdict: 'test', count: 1, readiness: { state: 'testable', eligible: true } },
      implementation_readiness: { runnable: true }, trial_ids: ['trial_2'], live_trials: 0, finalist: false, confirmation: null, stop_reason: null, created_at: '2026-10-19T08:02:30Z', stage: 'extended', curve: [{ x: 100, y: .3 }, { x: 2100, y: .52 }] },
    { id: 'hypothesis_c', label: 'H03', title: 'Annealing', status: 'archived', origin: 'pi', actor: 'autopilot', autonomous: true, round: 1, parent_links: [{ id: 'hypothesis_a', kind: 'revision' }], algorithm: 'anneal', worker_seconds: 30, allotted_seconds: 30, evaluations: 10,
      best: { score: 0.1, basis: 'measured', source: 'result', trial_id: 'trial_3', interval: null }, highest_rung_seconds: 30, race: null, review: { verdict: null, count: 0, readiness: { state: 'not_required', eligible: true } },
      implementation_readiness: { runnable: true }, trial_ids: ['trial_3'], live_trials: 0, finalist: false, confirmation: null, stop_reason: 'worse than the baseline at every rung', created_at: '2026-10-19T08:03:00Z', stage: 'stopped' },
  ],
  layout: [{ id: 'hypothesis_a', round: 0, lane: 0, stage: 'screening', label: 'H01', title: 'Random restarts', autonomous: false, stop_reason: null }, { id: 'hypothesis_b', round: 1, lane: 1, stage: 'extended', label: 'H02', title: 'CMA-ES with warm start', short_title: 'Warm-start CMA-ES', autonomous: false, stop_reason: null },
    { id: 'hypothesis_c', round: 1, lane: 2, stage: 'stopped', label: 'H03', title: 'Annealing', autonomous: true, stop_reason: 'worse than the baseline at every rung' }],
  edges: [{ from: 'hypothesis_a', to: 'hypothesis_b', kind: 'variant', external: false }, { from: 'hypothesis_a', to: 'hypothesis_c', kind: 'revision', external: false }] };
export const hypothesisCard = { hypothesis: { id: 'hypothesis_b', title: 'CMA-ES with warm start', status: 'investigating', mechanism: 'Covariance adaptation from the previous best.', rationale: 'Smooth landscape.', algorithm: 'cma_es', origin: 'pi', status_revision: 1 },
  ledger_row: evolution.nodes[1], parents: [{ id: 'hypothesis_a', title: 'Random restarts', status: 'proposed' }], children: [], reviews: [{ id: 'review_1', author: 'proposal_reviewer', verdict: 'test', text: 'Plausible; test it.', created_at: '2026-10-19T08:03:00Z' }],
  rounds: [], implementation: { runnable: true }, validations: [], trials: [{ id: 'trial_2', status: 'stopped', algorithm: 'cma_es', seed: 1, wall_seconds: 1200, execution_seconds: 1100, created_at: '2026-10-19T07:00:00Z', stopped_by: 'researcher', race_phase: null }],
  race_cells: null, provenance: [{ hop: 'hypothesis', record: { id: 'hypothesis_b', kind: 'hypothesis', title: 'CMA-ES with warm start', created_at: '2026-10-19T08:02:30Z' }, via: 'the record', page: null },
    { hop: 'work_command', record: { id: 'pi_command_1', kind: 'work_command', title: 'hypothesis.create', created_at: '2026-10-19T08:02:30Z' }, via: 'manager ran hypothesis.create', page: '#hypotheses' },
    { hop: 'agent_run', record: { id: 'pi_run_1', kind: 'agent_run', title: 'Generate two strategies', created_at: '2026-10-19T08:02:00Z' }, via: 'a turn of lead_demo', page: null },
    { hop: 'agent_session', record: { id: 'lead_demo', kind: 'agent_session', title: 'lead on gpt-5' }, via: 'the agent and its model', page: '#monitor/agents' },
    { hop: 'message', record: { id: 'message_1', kind: 'message', title: 'What do we know about the deflector so far?', created_at: '2026-10-19T08:01:00Z' }, via: 'the message that asked', page: '#branches' },
    { hop: 'thread', record: { id: THREAD_ID, kind: 'thread', title: 'Demo campaign' }, via: 'the conversation thread', page: '#branches' }] };

export const digest = { digest: { id: 'digest_1', from_event: 3, to_event: 10, rounds_completed: 2, away_minutes: 95, written_at: '2026-10-19T10:00:00Z', seen_at: null,
  stopped: [{ hypothesis_id: 'hypothesis_c', reason: 'worse than the baseline at every rung', by: 'autopilot' }], promoted: [{ hypothesis_id: 'hypothesis_b', by: 'autopilot' }], started: [{ operation: 'hypothesis.allocate', trial_id: 'trial_4', by: 'autopilot' }],
  finished_trial_ids: ['trial_2'], decisions_waiting: [{ id: 'extension_1', title: 'Extend trial trial_1 by 120 s?' }], questions_waiting: [], commands: [{ id: 'c1', operation: 'intervention.batch', by: 'autopilot' }] }, history: [] };

export const library = { signature: { problem_id: 'bounded_continuous', basis: "the first development task's problem instance" }, entries: [
  { entry: { id: 'library_1', origin_campaign_id: 'earlier', hypothesis_id: 'hypothesis_old', strategy: { title: 'Restart hill climbing', mechanism: 'Restart from the best of a batch.', algorithm: 'random' }, signature: { problem_id: 'bounded_continuous', objective: { name: 'f', direction: 'minimize' }, representation: 'continuous' },
    evidence: { best_score: 0.12, best_basis: 'measured', worker_seconds: 1800, seeds_won: 4, confirmation_protocol_id: 'protocol_1',
      fidelity: { state: 'passed', trial_id: 'trial_1', checks: [{ recipe_id: 'meent_2d_order_convergence:v1', state: 'passed', validation_result_id: 'validation_1', waiver_id: null }] } }, notes: '', created_at: '2026-10-01T00:00:00Z' }, match: { score: 6, reasons: ['same problem', 'same objective and direction', 'same representation'] } },
  { entry: { id: 'library_2', origin_campaign_id: 'other', hypothesis_id: 'hypothesis_g', strategy: { title: 'Grating hill climb', algorithm: 'hillclimb' }, signature: { problem_id: 'meent_grating', objective: { name: 'efficiency', direction: 'maximize' }, representation: 'binary' },
    evidence: { best_score: 0.5, best_basis: 'measured', worker_seconds: 60 }, notes: '', created_at: '2026-09-01T00:00:00Z' }, match: { score: 0, reasons: [] } }] };
export const threadSearch = { campaign_id: CAMPAIGN_ID, q: 'deflector', threads: [], messages: [{ thread_id: THREAD_ID, thread_title: 'Demo campaign', message_id: 'message_1', role: 'user', excerpt: 'What do we know about the deflector so far?', created_at: '2026-10-19T08:01:00Z' }] };

export const setupSteps = {
  name: { field: 'name', question: 'What shall we call the campaign?', choices: [], free_text: true, placeholder: 'Grating deflector, round 3' },
  objective: { field: 'objective', question: 'What do you want to find out?', choices: [{ id: 'later', label: 'Let the lead draft it with me', patch: { objective: '' } }], free_text: true },
  problem: { field: 'problem', question: 'Which problem does it run on?', choices: [{ id: 'formulate', label: 'Formulate it with the lead first', patch: {} }, { id: 'bounded_continuous', label: 'Bounded continuous', patch: { problem_id: 'bounded_continuous' } }], free_text: true },
  budget: { field: 'budget', question: 'How much may it spend?', choices: [{ id: 'small', label: 'Small', patch: {} }], free_text: true },
  ready: { field: 'ready', question: 'That is everything. Create the campaign, or change something.', choices: [{ id: 'create', label: 'Create the campaign', patch: {} }, { id: 'edit:name', label: 'Change the name', patch: {} }], free_text: true },
};
export const setupStart = { id: 'setup_1', status: 'asking', mode: 'scripted', model: null, cost_usd: 0, draft: { name: null, identity: null, objective: null, problem_id: null, decided: [] },
  transcript: [{ role: 'assistant', text: "Let's set up a campaign. First: What shall we call the campaign?", field: 'name', choices: [] }], step: setupSteps.name, campaign_id: null };
export const deskMessages = [
  { id: 'message_desk_1', campaign_id: CAMPAIGN_ID, role: 'user', origin: 'researcher', desk: 'discussion_moderator', content: 'Which proposal looked weakest?', created_at: '2026-10-19T08:12:00Z' },
  { id: 'message_desk_2', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'page_agent', desk: 'discussion_moderator', content: 'The third: its mechanism is underspecified.', created_at: '2026-10-19T08:13:00Z' },
];
export const charterProposal = { id: 'charter_proposal_1', charter_id: 'charter_1', base_revision: 2, status: 'open', accepted_option: null, created_at: '2026-10-19T09:00:00Z',
  request: 'Resolve the weekly-limit request from the sources without inventing a number.', asked: 'Make the weekly limit follow from the monthly budget',
  options: [
    { label: 'Derive it from the monthly budget', reason: 'The monthly budget is the only sourced figure. Four weeks to the month is the working assumption the sources use.',
      changes: [{ op: 'set', path: 'quantities.weekly_limit_per_seat.expression', value: 'monthly_budget_tokens / n_seats / 4' }, { op: 'set', path: 'quantities.weekly_limit_per_seat.role', value: 'derived' }],
      blocking_reason: null, findings: [],
      diff: [{ part: 'quantity', name: 'weekly_limit_per_seat', change: 'changed', before: 2400000, after: 'monthly_budget_tokens / n_seats / 4' }, { part: 'quantity', name: 'weekly_limit_per_seat', change: 'changed', before: 'input', after: 'derived' }] },
    { label: 'Keep it as an input and ask for the figure', reason: 'If the weekly limit is a provider rule rather than a share of the budget, it should stay an input.',
      changes: [{ op: 'set', path: 'quantities.weekly_limit_per_seat.value', value: null }],
      blocking_reason: 'The sources give no weekly figure; the value has to come from the researcher.', findings: [{ message: 'weekly_limit_per_seat has no value. Give one, or state how it follows from others.' }],
      diff: [{ part: 'quantity', name: 'weekly_limit_per_seat', change: 'changed', before: 2400000, after: null }] },
  ] };
export const charterView = { id: 'charter_1', title: 'Token sharing', status: 'draft', revision: 2, blocking: 3, question_rounds: 1, question_rounds_max: 2, proposals: [], history: [], values: { n_users: 10, n_agents: 2, n_seats: 12, working_days_per_month: 20, monthly_budget_tokens: null },
  errors: { monthly_budget_tokens: 'no value' }, rendered: { text: 'Share **120 M** tokens across 12 seats.' },
  findings: [
    { key: 'assumption.unaccepted:working_days_per_month', code: 'assumption.unaccepted', severity: 'blocking', message: 'working_days_per_month = 20 day is an assumption. Accept it, change it, or ask for a change.', about: ['working_days_per_month'], waivable: false },
    { key: 'quantity.no_value:monthly_budget_tokens', code: 'quantity.no_value', severity: 'blocking', message: 'monthly_budget_tokens has no value. Give one, or state how it follows from others.', about: ['monthly_budget_tokens'], waivable: false },
    { key: 'variable.bounds:daily_cap', code: 'variable.bounds', severity: 'blocking', message: 'daily_cap is continuous and needs a lower and an upper bound.', about: ['daily_cap'], waivable: false,
      suggestions: [{ label: 'Ask the formulator for the bounds of daily_cap', action: 'request', text: 'daily_cap needs a lower and an upper bound. Take them from the sources.' }] },
    { key: 'quantity.unused:weekly_limit_per_seat', code: 'quantity.unused', severity: 'warning', message: 'weekly_limit_per_seat reaches nothing.', about: ['weekly_limit_per_seat'], waivable: false },
  ],
  charter: { title: 'Token sharing', summary: 'Allocate a monthly token budget across seats.', text: 'Share {monthly_budget_tokens} tokens across {n_seats} seats.', assumptions: [], waivers: [],
    quantities: {
      n_users: { description: 'People on the team', kind: 'integer', role: 'input', value: 10, expression: null, units: '1', range: [1, null], origin: 'source', accepted: false },
      n_seats: { description: 'People plus agents', kind: 'integer', role: 'derived', value: null, expression: 'n_users + n_agents', units: '1', range: null, origin: 'computed', accepted: false },
      working_days_per_month: { description: 'Working days in the month', kind: 'integer', role: 'input', value: 20, expression: null, units: 'day', range: [1, 31], origin: 'assumed', accepted: false },
      monthly_budget_tokens: { description: 'Tokens per month', kind: 'integer', role: 'input', value: null, expression: null, units: 'token', range: [0, null], origin: 'source', accepted: false },
    },
    variables: [{ name: 'daily_cap', description: 'Daily token cap for each seat', representation: 'continuous', shape: ['n_seats'], lower: 0, upper: null, values: [], units: 'token/day' }],
    questions: [{ id: 'value_scoring', question: 'How is the value of work quantified?', options: ['Discrete 1-5 impact score', 'Continuous value in currency'], answer: null }, { id: 'granularity', question: 'Are caps set per day or per week?', options: ['Per day', 'Per week'], answer: null }] } };
export const adoptedNoteView = { ...noteView, note: { ...noteView.note, status: 'adopted', adopted_revision: 2, charter_id: 'charter_1' }, charter: { charter_id: 'charter_1', status: 'ready', import_id: 'import_1', error: null, model: { provider: 'centinels', model: 'gpt-6.1-sol', effort: null }, tier: 'strong', usage: { calls: 15, cost_usd: 0 } } };
export const panel = { id: 'panel_1', campaign_id: CAMPAIGN_ID, title: 'Seat budget', page: '#note/charter', placement: 'bottom', note: 'Type the budget; the per-user figure follows.', author: 'formulator', revision: 1, status: 'active',
  created_at: '2026-10-20T08:00:00Z', updated_at: '2026-10-20T08:00:00Z', resolved_at: '2026-10-20T08:00:00Z',
  components: [
    { type: 'markdown', text: 'Seats share one monthly budget.' },
    { type: 'number', id: 'budget', label: 'Monthly budget', bind: { charter: 'charter_1', path: 'quantities.monthly_budget_tokens.value' }, units: 'token', min: 0 },
    { type: 'kv', id: 'facts', rows: [{ label: 'Per user', bind: { charter: 'charter_1', value: 'per_user' } }] },
    { type: 'select', id: 'scoring', label: 'Value scoring', bind: { charter: 'charter_1', question: 'value_scoring' }, options: [{ value: 'Discrete' }, { value: 'Currency' }] },
    { type: 'table', id: 'proposals', title: 'Proposals', columns: [{ key: 'title', label: 'Title' }, { key: 'status' }], source: { kind: 'hypothesis' } },
    { type: 'chart', id: 'curve', title: 'Best run', source: { trial: 'trial_1' } },
    { type: 'section', title: 'Next', children: [{ type: 'button', id: 'gen', label: 'Three strategies', command: { operation: 'research.generate', payload: { count: 3 } } }, { type: 'link', label: 'Hypotheses', page: '#hypotheses' }] },
  ],
  data: { budget: { value: null, units: 'token', revision: 2 }, facts: { rows: [{ label: 'Per user', value: null, units: 'token' }] }, scoring: { value: null, options: ['Discrete', 'Currency'], revision: 2 },
    proposals: { rows: [{ title: 'Random restarts', status: 'proposed' }, { title: 'CMA-ES with warm start', status: 'investigating' }] }, curve: { points: [{ x: 10, y: 0.2 }, { x: 80, y: 0.41 }] } } };
