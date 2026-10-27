/** What a coding workspace is, as the pages show it: its record's shape, which states mean it works, the coding agent's
 *  verdict in words, and its own estimate in words. Shared by the Implementations tab and the status strip. */
export interface Checkpoint { at: string; summary: string; next_steps?: string; blocker?: string; question?: string; done?: string[]; remaining?: string[] }
export interface Tests { passed: number; failed: number; skipped?: number; command?: string }
export interface Report {
  verdict: 'ready' | 'ready_with_limits' | 'not_ready'; summary: string; tests: Tests; limitations: string[];
  methods: { method_id: string; hypothesis_id?: string | null; state: string; conformance: string; tests?: Tests | null; note?: string }[];
  next_actions: { owner: 'researcher' | 'lead' | 'validator'; action: string }[];
}
export interface Install { id: string; submission_id: string; status: string; actor?: string; package: string; version: string; path: string; requested_at: string;
  finished_at?: string; methods_added: string[]; missing_methods: string[]; problems_added?: string[]; missing_problems?: string[]; problem_entry_points?: Record<string, string>; changes: { name: string; from: string; to: string | null }[]; error?: string; log_tail?: string;
  /** Files generated from the charter that the coding agent changed (its objective and methods aside). */
  changed_generated_files?: string[];
  /** What Balsamic bound after the install, and the proposals it left with why. */
  bindings?: { hypothesis_id: string; title?: string; method: string; task_id: string; binding_id: string }[]; skipped?: { hypothesis_id: string; reason: string }[];
  launched?: { hypothesis_id: string; seed: number; trial_id: string; task_id: string; consent_id: string }[] }
export interface Submission { id: string; commit: string; status: string; notes?: string; report?: Report | null; created_at: string; manifest?: { files?: string[] };
  /** own_session: the researcher delivered it from their own coding agent (roadmap H3); absent for the coding agent's. */
  source?: string;
  validation_outcome?: { status?: string; error?: string | null; findings?: Record<string, string>[] } }
export interface Outcome { state: string; verdict?: string; submission_id?: string; commit?: string; at: string; reason?: string }
export interface Workspace {
  id: string; campaign_id: string; title: string; hypothesis_id: string; hypothesis_ids?: string[]; status: string; desired_status: string; created_at: string;
  started_at?: string; last_activity_at?: string; cpu_budget_seconds?: number | null; usage?: { container_cpu_seconds?: number };
  error?: string; activity?: string; checkpoints?: Checkpoint[]; last_error_at?: string | null; ide_url?: string;
  opened_by?: { actor?: string; role?: string }; questions?: { id: string; question: string }[];
  phase?: string; tests?: Tests; estimate?: { remaining_minutes: number; given_at: string; source: string };
  outcome?: Outcome | null; finished_at?: string | null; submissions?: Submission[]; installs?: Install[];
  control_revision?: number; wall_seconds?: number | null; deadline_at?: string | null; limits?: { cpus: number; memory_gb: number; gpus: number };
  egress?: { model: string[]; package_index: string[]; named: string[] };
  /** The library generated from the charter it started from (roadmap F4). */
  library?: { name: string; package?: string; revision?: number } | null;
}
export const LIVE = new Set(['queued', 'starting', 'resuming', 'running', 'pausing', 'stopping']);
export const VERDICT: Record<string, [string, string]> = { ready: ['ready', 'clear'], ready_with_limits: ['ready, with limits', 'attention'],
  not_ready: ['not ready', 'bad'], unreported: ['no delivery report', ''] };
export const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

/** The coding agent's own estimate in words, for the status strip: minutes left, or that its time has passed. */
export function estimateWords(w: Pick<Workspace, 'estimate' | 'outcome'>) {
  const e = w.estimate;
  if (!e || (w.outcome && w.outcome.at > e.given_at)) return null;
  const due = new Date(e.given_at).getTime() + e.remaining_minutes * 60_000;
  return due > Date.now() ? `about ${Math.max(1, Math.round((due - Date.now()) / 60_000))} min left, by its own estimate`
    : `its estimate (${Math.round(e.remaining_minutes)} min at ${clock(e.given_at)}) has passed`;
}

