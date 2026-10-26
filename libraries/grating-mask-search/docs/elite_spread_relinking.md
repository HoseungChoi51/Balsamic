# H14 compatibility revision

Researcher-authorized responsibility rescope: optimizer_v1 proposes and observes;
trusted worker owns evaluator identity/fidelity, exact cache, deadlines, blocking-call
supervision, failure charging and full-worker accounting. No host edits or direct solves.
Original revision 99de6eb is preserved in history. Independent service is authorized
for four physical integration evaluations; this source handoff itself runs only mocks.

Factory h14.optimizer:create_optimizer(context). initialize takes normal published
problem descriptor, empty parameters {}, seed, empty declared_assets []. Required:
candidate_schema.dimensions=32768; primary_objective.name and optional direction
(defaults maximize). Grid keys may be top-level or in configuration/public/
public_descriptor. Missing grid keys use fixed R4-C shape128x256; any explicitly
contradicting grid key is rejected. No mandatory
context deadline, fidelity or evaluation_identity. No mock-control parameters.

Every candidate request, including duplicates/endpoints, is proposed to worker.
Worker returns cached or fresh actual observations; every successful request offers
the mask to E/R and advances its phase. Internal mask registry retains first actual
successful insertion metadata, not evaluator authority; no hit suppresses a proposal.
Distinct ties use earliest first successful insertion. E/R and global best remain
separate. Frozen corridor and latest-best local mechanisms unchanged.

observe accepts matching proposal_id, status, objectives dictionary, optional costs.
Scalar objective fixtures are supported. Actual TE/TM/min are preserved when supplied;
missing polarizations are never synthesized. Nonfinite/failure result is not archived.
Worker owns normal failure/termination handling. Checkpoints preserve RNG, registry,
archives, parents/order, phases, counters, pending state; canonical descriptor scope
must match. No artifact exports or diagnostic callbacks. Pickle is trusted-host-only.

Actual inspect fields:
requests, cache_hits, attempted, completed, failures, physical_forward, backward,
decisions, episodes, injections, phase, index, episode, stalls, terminal, elite,
spread, best_candidate, best_objectives, full_optimizer_seconds,
physical_forward_unknown, scope_sha256.
Elite/spread are insertion-ordinal lists, NOT exposed mask pools. best_objectives
contains only received metrics. requests counts proposals; decisions counts valid
observations; attempted/completed count observed non-worker-cache calls; pending
work and unknown failure costs remain worker authority. cache_hits comes from
costs.cache_hits, physical_forward from exposed solver_executions; backward=0.
full_optimizer_seconds is source elapsed including callback wait, not full-worker
measurement. scope_sha256 identifies canonical descriptor, not per-mask cache keys.

`python -m unittest h14.test_optimizer -v`: eight standard-library mock tests, including six-step scalar seeded replay and
checkpoint continuation across optional published grid layouts.
No effectiveness claims or physical validation claimed. designer-context.md contains
self-contained verbatim normative material and explicit superseding responsibility
interpretation; independent designer owns expected references. Generic scalar replay
and checkpoint next-proposal checks are supported. Current plan schema cannot fully
express geometric E/R/corridor or deadline/failure terminal invariants; worker duties
are no longer package acceptance requirements. No candidate oracle/test backdoors.
