export interface StopRecord { outcome: string; words: string; label: string; evidence_ids: string[]; reason: string | null; by: string | null; at: string | null }
/** A proposal's algorithm family (hypothesis.create's family), as the cards and the lineage graph name it. */
export const FAMILY: Record<string, string> = { exact: 'exact', solver: 'solver', constructive: 'constructive', local_search: 'local search', learning: 'learning', hybrid: 'hybrid' };
export type Direction = 'minimize' | 'maximize';
export interface ParentLink { id: string; kind: 'revision' | 'variant' | 'hybrid' | 'inspired_by' }
export interface LedgerRow { id: string; label: string | null; title: string; short_title?: string | null; status: string; origin?: string; actor?: string | null; autonomous: boolean; round: number | null; parent_links: ParentLink[];
  family?: string | null; algorithm?: string; worker_seconds: number; allotted_seconds: number; evaluations: number | null; best: { score: number | null; basis: string | null; source: string | null; trial_id: string | null; interval: unknown; direction?: Direction | null };
  highest_rung_seconds: number | null; race: { race_id: string; configuration_id: string; status: string; race_status: string; highest_rung_seconds?: number | null; mean_score?: number | null; seeds?: number; latest_decision: { action: string; rationale: string; at: string } | null } | null;
  review: { verdict: string | null; count: number; readiness: { state: string; eligible: boolean; reason?: string } }; implementation_readiness: { state?: string; runnable: boolean; reason?: string };
  trial_ids: string[]; live_trials: number; finalist: boolean; confirmation: { protocol_id: string; status: string; promising: boolean | null; seeds_won?: number } | null; stop_reason: string | null; stopped_at?: string | null; stop?: StopRecord | null;
  created_at?: string; stage: 'proposed' | 'reviewed' | 'screening' | 'extended' | 'finalist' | 'confirmed' | 'stopped'; curve?: { x: number; y: number; t?: number }[] }
export interface LayoutNode { id: string; round: number; lane: number; stage: LedgerRow['stage']; label: string | null; title: string; short_title?: string | null; family?: string | null; autonomous: boolean; stop_reason: string | null; stop_label?: string | null }
export interface Edge { from: string; to: string; kind: ParentLink['kind']; external: boolean }
export interface RaceView { id: string; study_id: string; status: string; stage?: string; started_at?: number; deadline_at?: number; elapsed_seconds?: number; total_seconds?: number; running_workers?: number;
  worker_seconds_spent?: number; worker_seconds_cap?: number; configurations: { id: string; algorithm: string; status: string; mean_score: number | null; sample_standard_deviation?: number | null; seeds: number; rung_seconds: number; maturity: { eligible: boolean; reasons: string[] }; trial_ids: string[] }[];
  decisions: { action: string; rationale?: string; configuration_ids?: string[]; created_at?: string }[] }
export interface Evolution { campaign_id: string; event_cursor: number; unchanged?: boolean; nodes: LedgerRow[]; layout: LayoutNode[]; edges: Edge[]; rounds: number; races: RaceView[]; finalists: Record<string, unknown>[];
  confirmations: Record<string, unknown>[]; stage: { stage: string; pinned: boolean; basis: string }; interventions: Record<string, unknown>[]; progress?: { best_so_far: number | null; direction?: Direction | null; live_trials: { id: string; hypothesis_id: string | null; status: string }[]; finalist_rungs: { id: string; rung: number | null }[] } }
export interface Hop { hop: string; record: { id: string; kind: string; title: string; created_at?: string; content_hash?: string; status?: string }; via: string; page: string | null }
export interface HypothesisCard { hypothesis: Record<string, unknown>; ledger_row: LedgerRow | null; parents: { id: string; title: string; status: string }[]; children: { id: string; title: string; status: string }[];
  reviews: { id: string; author: string; verdict?: string; text: string; created_at: string }[]; rounds: Record<string, unknown>[]; implementation: { state?: string; runnable: boolean; reason?: string };
  validations: Record<string, unknown>[]; trials: { id: string; status: string; algorithm: string; seed?: number; wall_seconds?: number; execution_seconds?: number; created_at?: string; stopped_by?: string | null; race_phase?: string | null }[];
  race_cells: LedgerRow['race']; provenance: Hop[] }
