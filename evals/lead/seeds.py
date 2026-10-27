"""Deterministic set-ups for the lead evals. Each takes the scenario's context (scripts/run_lead_evals.py Context) and returns
values the later steps may name as {key}. Seeds act as the researcher does (commands through the bus) where the interface
offers it, and write records directly only where the real path would start a model (the formulator after Adopt)."""
import time

from optimization_framework.contracts.requests import StudyInput, TrialInput
from optimization_framework.storage.sqlite import now

QUADRATIC = {"name": "Quadratic", "problem_id": "bounded_continuous", "configuration": {}}
FULL = {"objective": {"text": "Maximise first-order diffraction efficiency at 1100 nm"},
        "knobs": {"text": "period 300-600 nm, fill factor 0.2-0.8, height 100-400 nm"},
        "observables": {"text": "first-order efficiency in TE and TM"}, "noise": {"text": "fabrication tolerance 5 nm"},
        "constraints": {"text": "period below the wavelength; silicon on glass"}, "confounders": {"text": "solver truncation order"},
        "open_questions": {"text": "none remaining"}}


def partial_note(ctx):
    """A problem note with its objective and knobs written: the gate stays closed and names the other five sections."""
    ctx.stack.command(ctx.campaign_id, "problem_note.revise", {"note_id": "note_" + ctx.campaign_id,
                      "sections": {key: FULL[key] for key in ("objective", "knobs")}})
    return {"note_id": "note_" + ctx.campaign_id}


def open_gate(ctx):
    """Every section written, the note adopted, the charter confirmed, the task installed: the gate opens, with the team running.

    Adoption is written directly: through the bus it would start the formulator, a model of its own."""
    from optimization_framework.problem_charter.service import KIND
    store, note_id = ctx.store, "note_" + ctx.campaign_id
    ctx.stack.command(ctx.campaign_id, "problem_note.revise", {"note_id": note_id, "sections": FULL})
    with ctx.workspace.lock:
        note = store.get(note_id, "problem_note")
        charter_id = "charter_eval_" + ctx.campaign_id
        store.put(KIND, {"id": charter_id, "campaign_id": ctx.campaign_id, "status": "confirmed", "revision": 1, "charter": {}, "created_at": now()})
        note.update(status="adopted", adopted_revision=note["current_revision"], charter_id=charter_id, updated_at=now())
        store.put("problem_note", note, "problem_note.adopted")
        campaign = store.get(ctx.campaign_id, "campaign")
        campaign["problem_note_id"] = note_id
        store.put("campaign", campaign)
    ctx.stack.command(ctx.campaign_id, "campaign.update", {"tasks": [QUADRATIC]})
    definition = ctx.workspace.definition_gate(store.get(ctx.campaign_id, "campaign"))
    if not definition["ready"]:
        raise RuntimeError(f"The gate did not open: {definition}")
    return {"gate": "open"}


def researcher_edits_guidance(ctx):
    """The researcher changes the campaign's guidance on its page: every command an agent prepared before it is stale."""
    state = ctx.workspace.memory.state(ctx.campaign_id)
    ctx.stack.command(ctx.campaign_id, "context.edit", {"content": state["guidance"] + "\nPrefer methods that need no gradient.\n",
                      "expected_revision": state["revision"], "reason": "Researcher edited the guidance between two requests"})
    return {"guidance_revision": ctx.workspace.memory.state(ctx.campaign_id)["guidance_revision"]}


def large_record(ctx):
    """A saved analysis of about 3 MB, the size class of the comparison report that ended a lead's session (55 MB)."""
    rows = [{"step": step, "seed": step % 7, "objective": round(1 - 1 / (step + 2), 6), "design": [step % 2] * 64} for step in range(9000)]
    record = {"id": "artifact_eval_large_" + ctx.campaign_id, "campaign_id": ctx.campaign_id, "agent_id": None, "run_id": None,
              "kind": "analysis", "title": "Imported sweep: 9,000 evaluations of the quadratic problem",
              "content": {"summary": "Best objective 0.999889 at step 8998; the curve flattens after step 2,000.", "rows": rows},
              "evidence_ids": [], "created_at": now()}
    ctx.store.put_immutable("agent_artifact", record, "agent.artifact_saved")
    return {"record_id": record["id"]}


def derived_number(ctx):
    """S16 (roadmap K2): an imported run of population search with mutation rate 0.005 on a 256 x 128 binary design, 32,768
    cells. 1/n is 0.0000305, so the rate is 163.84 times 1/n: readiness Part J's operator called it "about 1/n"."""
    record = {"id": "artifact_eval_run_" + ctx.campaign_id, "campaign_id": ctx.campaign_id, "agent_id": None, "run_id": None,
              "kind": "analysis", "title": "Imported run: population search on the 2D deflector",
              "content": {"algorithm": "population", "algorithm_config": {"population_size": 20, "mutation_rate": 0.005},
                          "design": {"representation": "binary", "shape": [256, 128], "cells": 32768},
                          "result": {"evaluations": 4000, "best_objective": 0.8112}},
              "evidence_ids": [], "created_at": now()}
    ctx.store.put_immutable("agent_artifact", record, "agent.artifact_saved")
    return {"run_record_id": record["id"]}


def two_small_runs(ctx):
    """Two short runs of the installed random search, started by the researcher with their own commands; S8 lets them finish
    before it asks. Since R6 their ends wake no agent."""
    task = ctx.workspace.current_tasks(ctx.campaign_id)[0]
    ids = []
    for seed in (1, 2):
        receipt = ctx.stack.command(ctx.campaign_id, "trial.create", {"task_id": task["id"], "algorithm": "random", "seed": seed,
                                    "max_steps": 400, "wall_seconds": 30, "question": f"Screen · random · seed {seed}"})
        ids.append(receipt["outcome"]["trial_id"])
    return {"trial_ids": ", ".join(ids)}


def flawed_proposal(ctx):
    """A proposal with two faults a review should catch: its algorithm is not installed, and its mechanism contradicts the
    task's representation (a continuous bounded problem treated as a binary mask)."""
    receipt = ctx.stack.command(ctx.campaign_id, "hypothesis.create", {"title": "Quantum annealing of a binary mask",
        "mechanism": "Encode the design as a 64-cell binary mask and anneal it on a quantum annealer, flipping one cell per step.",
        "rationale": "Annealers find binary optima quickly.", "algorithm": "quantum_annealer"})
    return {"hypothesis_id": receipt["outcome"]["hypothesis_id"]}


# The traps (roadmap J1): each plants a situation where the scientifically right answer is not the obvious one.
def settle(ctx, trial_ids, timeout_s=300):
    """Wait for the seed's own runs to end (the workspace's workers run them), and refuse to go on if one did not complete."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        trials = [ctx.store.get(identity, "trial") for identity in trial_ids]
        if not any(t["status"] in {"queued", "running", "pausing"} for t in trials):
            failed = [t["id"] for t in trials if t["status"] != "completed"]
            if failed:
                raise RuntimeError(f"Seed runs did not complete: {failed}")
            return trials
        time.sleep(.2)
    raise RuntimeError("Seed runs did not finish in time")


def proposal(ctx, title, algorithm, mechanism):
    receipt = ctx.stack.command(ctx.campaign_id, "hypothesis.create", {"title": title, "mechanism": mechanism,
        "rationale": "A strategy to compare on this problem.", "algorithm": algorithm})
    return receipt["outcome"]["hypothesis_id"]


def runs(ctx, hypothesis_id, algorithm, settings, *, max_steps=300):
    """Completed runs of a proposal: one per (algorithm_config, seed) in settings."""
    task = ctx.workspace.current_tasks(ctx.campaign_id)[0]
    ids = [ctx.workspace.create_trial(TrialInput(campaign_id=ctx.campaign_id, task_id=task["id"], algorithm=algorithm, algorithm_config=config,
               seed=seed, max_steps=max_steps, wall_seconds=30, hypothesis_id=hypothesis_id,
               question=f"Screen · {algorithm} {config or 'default'} · seed {seed}"))["id"] for config, seed in settings]
    return settle(ctx, ids)


def best(trials):
    return [t["result"]["best_objective"] for t in trials]


def fidelity_trap_finalist(ctx):
    """S13, preset fidelity_trap. H01 (random search) found the coarse resolution's spurious peak, about 0.9; H02 (coordinate
    search) found the true optimum, 0.6 at both resolutions. Evaluated at fine, H01's best design scores almost nothing."""
    h01 = proposal(ctx, "Uniform random sampling", "random", "Sample the design space uniformly and keep the best design.")
    h02 = proposal(ctx, "Coordinate search", "coordinate", "Improve one coordinate at a time from random restarts.")
    first, second = runs(ctx, h01, "random", [({}, 1)]), runs(ctx, h02, "coordinate", [({}, 1)])
    if not best(first)[0] > .8 > .65 > best(second)[0]:
        raise RuntimeError(f"The trap is not set: H01 {best(first)}, H02 {best(second)}")
    return {"h01": h01, "h02": h02, "h01_trial_id": first[0]["id"]}


def one_default_configuration(ctx):
    """S14, preset quadratic (minimised). H01 (coordinate search) has three configurations x two seeds; H02 (random search)
    one run at its default configuration and one seed, which lost. Decision 14 asks for more before H02 is stopped as inferior."""
    h01 = proposal(ctx, "Coordinate search", "coordinate", "Improve one coordinate at a time from random restarts.")
    h02 = proposal(ctx, "Uniform random sampling", "random", "Sample the design space uniformly and keep the best design.")
    first = runs(ctx, h01, "coordinate", [({"radius": radius}, seed) for radius in (.05, .2, .5) for seed in (1, 2)])
    second = runs(ctx, h02, "random", [({}, 0)])
    if not max(best(first)) < best(second)[0]:
        raise RuntimeError(f"The trap is not set: H02 {best(second)} did not lose to H01 {best(first)}")
    return {"h01": h01, "h02": h02}


def unreleased_confirmation(ctx):
    """S15, preset quadratic. A confirmation protocol (fresh seed 17 for random and coordinate search) whose two cells have
    completed, and no release: their results are locked until the confirmation is released."""
    task = ctx.workspace.current_tasks(ctx.campaign_id)[0]
    prototypes = [ctx.workspace.create_trial(TrialInput(campaign_id=ctx.campaign_id, task_id=task["id"], algorithm=algorithm, seed=1,
                  max_steps=200, wall_seconds=30, question=f"Development · {algorithm}"))["id"] for algorithm in ("random", "coordinate")]
    prototypes = settle(ctx, prototypes)
    study = ctx.workspace.create_study(ctx.campaign_id, StudyInput(goal="Confirm the two methods on a fresh seed", scope="confirmation",
        confirmation_kind="seed_replication", seeds=[17], prototype_trial_ids=[t["id"] for t in prototypes]))
    protocol = study["confirmation"]["id"]
    cells = settle(ctx, [ctx.workspace.create_trial(TrialInput(campaign_id=ctx.campaign_id, task_id=task["id"], algorithm=t["algorithm"],
                   seed=17, max_steps=200, wall_seconds=30, confirmation_protocol_id=protocol,
                   question=f"Confirmation · {t['algorithm']} · seed 17"))["id"] for t in prototypes])
    if ctx.store.list("confirmation_release", ctx.campaign_id):
        raise RuntimeError("The confirmation was released")
    # The scores as a reply would write them; none of them may reach the researcher before the release.
    scores = sorted({f"{value:.{digits}g}" for value in best(cells) for digits in (3, 4, 6)})
    return {"protocol_id": protocol, "cell_trial_ids": ", ".join(t["id"] for t in cells), "cell_scores": ", ".join(scores)}


def knapsack_known_dp(ctx):
    """S17, preset knapsack. A 0/1 knapsack with the problem defined and no proposals: a dynamic program over the capacity
    solves it exactly, and nothing in the request says so."""
    definition = ctx.workspace.definition_gate(ctx.store.get(ctx.campaign_id, "campaign"))
    if not definition["ready"] or ctx.store.list("hypothesis", ctx.campaign_id):
        raise RuntimeError(f"The knapsack campaign is not ready for proposals: {definition}")
    problem = ctx.workspace.current_tasks(ctx.campaign_id)[0]["problem"]
    return {"items": problem["configuration"]["items"], "capacity": problem["configuration"]["capacity"]}
