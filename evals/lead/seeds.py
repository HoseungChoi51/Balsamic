"""Deterministic set-ups for the lead evals. Each takes the scenario's context (scripts/run_lead_evals.py Context) and returns
values the later steps may name as {key}. Seeds act as the researcher does (commands through the bus) where the interface
offers it, and write records directly only where the real path would start a model (the formulator after Adopt)."""
from optimization_framework.contracts.requests import TrialInput
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


def two_small_runs(ctx):
    """Two short runs of the installed random search, started by the researcher; S8 lets them finish before it asks."""
    task = ctx.workspace.current_tasks(ctx.campaign_id)[0]
    ids = []
    for seed in (1, 2):
        trial = ctx.workspace.create_trial(TrialInput(campaign_id=ctx.campaign_id, task_id=task["id"], algorithm="random", seed=seed,
                                                      max_steps=400, wall_seconds=30, question=f"Screen · random · seed {seed}"))
        ids.append(trial["id"])
    return {"trial_ids": ", ".join(ids)}
