# H12 self-contained frozen mechanism — compatibility revision

Normative record: artifact_pi_tool_86f8269f855f5ffdb0b6c927c295bc7c
Parent content hash: a57cae655d72686a0d5f884a21eb4b0d5b254125985317bdf274d8aab9c5270b

## Verbatim common_contract
Every candidate is a full 128-row by 256-column row-major binary mask. Score at RCWA(10,5); maximize actual J=(TE+TM)/2, log TE/TM/min separately. Archive completed finite actual binary scores only. One seeded RNG; exact full-mask cache: hits require no new solve but all time charged. Check externally supplied worker deadline at every outer/generation/cache/init/restart loop and before calls; stop with best valid archive or no solution if none, without completing interrupted phases. Individual blocking calls require supervisor timeout. Failure/nonfinite call is charged, not cached/archived, and terminates cleanly. Log requests/cache hits/attempted/completed uncached dual-polarization calls/failures/exposed physical forward work and optimizer counters; backward count zero. Include generation/hash/cache/bookkeeping in full-worker time. No scored seed sharing absent declaration. All rule counts are algorithm specifications, not allocations. All three are custom/unattached; evaluator readiness does not make these custom procedures runnable. Partial initialization always returns best available valid mask at expiry; initial score ties and global archive ties use earliest completed first insertion. No symmetry/fill/min-feature constraints introduced.

## Verbatim coarse_draw_definition
Each coarse draw independently samples Bernoulli(0.5) on 8 rows by 16 columns, expanding each bit into a 16-row by 16-column pixel block. This is only initialization/restart bias, not a geometry constraint on subsequent full-mask operators.

## Verbatim proposal_fields R4-A
{
  "draft_id": "R4-A",
  "title": "Cyclic variable-neighborhood descent with geometric displacement",
  "short_title": "Cyclic geometric descent",
  "round": 4,
  "algorithm": "custom",
  "algorithm_config": {},
  "parent_links": [
    {
      "hypothesis_id": "hypothesis_pi_command_05168199173b518f937915724a8eb34b",
      "relation": "revision"
    }
  ],
  "mechanism": "Apply common contract and coarse-draw definition verbatim. Initialize up to four coarse draws and start current at best valid completed score. Separate global archive survives all restarts. Three neighborhoods in order: 0 square inversion, side uniform {1,2,4,8,16}; 1 rectangle content displacement, height/width independently uniform {4,8,16,32}, extract toroidal rectangle, cyclically rotate its INTERNAL contents one pixel along uniform x/y axis with uniform sign and paste into same rectangle; 2 paired-square inversion, side uniform {1,2,4,8}, independent uniform origins, XOR both regions so overlap cancels. Every origin uniform full-grid cell. Start index0; accept J gain>1e-12 relative current, resetting index and rejection counter to zero. Rejection increments counter; at 16 rejections advance index modulo3 and clear rejection counter. All evaluation requests, including cache hits and proposals identical to current, count once as requests; identical-current score comes from cache. Global no-gain request counter resets on archive improvement, otherwise increments once. At 96 no-gain requests restart current from ONE coarse draw regardless of quality, retaining archive; reset index/rejection/no-gain counters. Restart draw is logged but does not count toward the 96-request stall counter. Do not additionally retry duplicates or make hidden duplicate counters: each loop generates exactly one proposal, checks deadline and cache, then accepts/rejects once. If neighborhood switch and restart thresholds coincide, restart takes precedence. Expiry during any initialization/restart returns existing archive.",
  "rationale": "Cyclic neighborhoods retain local refinement, geometry-preserving displacement and separated coordinated edits without H09's nonstationary gain-credit arrays/warmup. One-request proposals keep control overhead small; accepting a new restart state permits basin changes while only the true best is returned.",
  "assumptions": [
    "Different geometries expose complementary improving directions.",
    "Coarse restarts reach useful basins often enough to justify their cost."
  ],
  "risks": [
    "Strict ascent between restarts still traps on barriers.",
    "Fixed 16/96-request schedule is uncalibrated; cache hits can accelerate restarts.",
    "Geometry-preserving displacement and paired edits may often be unproductive."
  ],
  "sources": []
}

## Explicit researcher responsibility interpretation (superseding package host-envelope gates)
Researcher explicitly respecified responsibility: canonical optimizer_v1 package proposes/observes only; WORKER owns physical evaluation, exact evaluation cache, deadlines, timeouts, failure charging and authoritative full-worker timing. No host changes required by this source revision. Worker evaluates physical masks at full128x256 RCWA(10,5) using actual mean TE/TM, separately retaining polarization metrics. No physical solves by author. Four real independent-service validation evaluations authorized; lead coordinates <=900 validation allocation per method including repairs.

All scientific schedules unchanged. Each propose produces exactly ONE request and returns it to worker including identical masks; no internal hit loop or cached-score evaluation bypass. One observe performs one acceptance/rejection/update. Worker-reported cache_hits increments package exposed hit counter; a cache hit still counts as a proposal request for rejection/no-gain/16/96 thresholds. Exact byte-score mapping retained solely for audit/checkpoint, immutable bytes/tuple entries. Separate global best retains earliest completion at equal actual objective; restart current replaced regardless of quality. Partial init best available at any completed request. Failure/nonfinite observation leaves existing best unchanged and marks failure termination; worker owns clean run termination/interruption and costs.

No mandatory deadline/evaluation_context/fidelity/evaluation_identity metadata on initialize or observe. Generic mock scalar objective supported without fabricated TE/TM: use descriptor primary_objective.name if present, otherwise first observation objective; metrics absent in scalar observations stored null. Actual TE/TM supplied => compute arithmetic mean, retain TE/TM/min; maximize that actual mean. No constraints or tunable scientific knobs introduced. No scored assets.

## Current canonical interface and schema
Factory h12_optimizer:create_optimizer(context). initialize(problem_descriptor, parameters, seed, declared_assets). Full candidate dimension32768; no declared assets. propose(max_candidates=1) -> [{id:string,candidate:32768 binary ints,metadata:{h12_kind:string,h12_neighborhood:int}}]. No batching. observe([observation]) matches proposal_id and candidate; observation.status='ok' with objectives mapping numeric finite scores. costs.solver_executions nonnegative numeric or absent/None unknown; optional costs.cache_hits integer/bool. No identity/fidelity fields required. checkpoint()->bytes; restore(bytes) reproduces RNG and state. export_artifacts()-> JSON-data best candidate/metrics when available and ordered request log including worker cache-hit reports. No diagnostic endpoint.

inspect() exact current keys:
requests, cache_hits, attempted_uncached_dual_calls, completed_uncached_dual_calls, failures, physical_forward_work, unknown_physical_forward_calls, backward_calls, proposal_requests, initialization_draws, restart_draws, restarts, accepts, rejects, neighborhood_switches, archive_improvements: numeric nonnegative counters. Attempts increment on physical proposal issuance, corrected downward when worker reports cache-hit; completions count successful non-hit observations. Unknown work separately counted. backward_calls always0.
phase: initialization/proposal/restart string.
neighborhood: int0..2.
rejection_count, no_gain_requests, initialization_completed, cache_entries: integer counts.
termination: null/evaluation_failure (deadline termination owned by worker).
has_solution: boolean.
best_objectives: null or {mean_plus1_transmission:number,te_plus1_transmission:number|null,tm_plus1_transmission:number|null,min_plus1_transmission:number|null}.
worker_seconds: numeric elapsed package diagnostic only.
worker_timing_scope: string stating worker owns full accounting/cache/deadline/failure/timeout envelope.

## Independent validation scope, not oracle answers
Source and author tests are supplied for inspection, not expected-reference oracle. Designer must derive independent checks from normative text. Use32768 cells, not unrelated tiny default fixture. Scalar-only generic fixture observations are acceptable; four actual physical validation evaluations should retain real polarization metrics. Seeded RNG is Python random.Random(seed), independent randrange(2) bits on8x16; uniform choices via choice/randrange and row/column origins. Exact source included plain text in h12_optimizer.py. No expected masks/scores supplied here.
Existing repository BehaviorCheck assertions binary/feasible/exact_designs can express parts of contract; unique_proposals/one_bit are NOT H12 invariants. MechanismCheck supports finite/nonnegative numeric inspect pointers; unit_norm/PSD/tangent/rank are unrelated to this algorithm. Existing diagnostic fixtures named h12_fourier_decoder/h12_covariance_refactor/h12_replay_context/h12_cache_identity concern a DIFFERENT historical method: do not select by label. Package has no Fourier/covariance state. Do not claim coverage for unexpressed transition/cache/tie/failure rules or physical effectiveness. No protected tests or host code modified.
