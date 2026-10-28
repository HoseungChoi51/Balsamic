"""Graph interventions: allocate more time to a strategy; a batch of stops, promotions, allocations and rounds, all or nothing."""
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.racing import RaceDecisionInput
from optimization_framework.storage.sqlite import now

from balsamic.evolution.ledger import RACE_ACTIVE

BATCH_OPERATIONS = {"hypothesis.status", "hypothesis.nominate", "hypothesis.allocate", "hypothesis.create", "study.race.decide", "research.generate"}


class AllocateInput(Contract):
    hypothesis_id: str
    worker_seconds: float = Field(gt=0, le=604800)
    rationale: str = Field(min_length=1, max_length=5000)
    replicate: bool = False
    # A new run on this task (the next size of a method that finished, N14) instead of more time on the last one.
    task_id: str | None = None


class InterventionItem(Contract):
    operation: Literal["hypothesis.status", "hypothesis.nominate", "hypothesis.allocate", "hypothesis.create", "study.race.decide", "research.generate"]
    payload: dict


class InterventionInput(Contract):
    items: list[InterventionItem] = Field(min_length=1, max_length=40)
    rationale: str = Field(default="", max_length=5000)
    all_or_nothing: bool = True


def register(workspace):
    commands = workspace.commands

    def bound_configuration(campaign_id, hypothesis_id):
        for race in workspace.store.list("adaptive_race", campaign_id):
            if race.get("status") not in RACE_ACTIVE:
                continue
            for configuration in workspace.racing._protocol(race)["configurations"]:
                if configuration.get("hypothesis_id") == hypothesis_id:
                    return race, configuration["id"]
        return None, None

    def allocate(command, actor):
        values = AllocateInput(**command.payload)
        hypothesis = workspace.store.get(values.hypothesis_id, "hypothesis")
        if hypothesis["campaign_id"] != command.campaign_id:
            raise ValueError("The strategy belongs to another campaign")
        if hypothesis.get("status") == "archived":
            raise ValueError("A stopped strategy gets no more time; take it up again first")
        campaign = workspace.store.get(command.campaign_id, "campaign")
        if actor != "researcher" and values.worker_seconds > campaign["delegated_trial_seconds"]:
            raise ValueError("More time than the delegated per-experiment allowance needs researcher approval; file trial.extension_request")
        race, configuration_id = bound_configuration(command.campaign_id, values.hypothesis_id)
        if race and not values.task_id:
            decided = workspace.racing.decide(command.campaign_id, RaceDecisionInput(race_id=race["id"], action="replicate" if values.replicate else "extend",
                                              configuration_ids=[configuration_id], rationale=values.rationale), authority=actor)
            return {"hypothesis_id": values.hypothesis_id, "how": "race." + ("replicate" if values.replicate else "extend"), "race_id": decided["id"], "configuration_id": configuration_id}
        trials = [t for t in workspace.store.list("trial", command.campaign_id) if t.get("hypothesis_id") == values.hypothesis_id]
        finished = [t for t in trials if t.get("status") in {"completed", "stopped", "budget_exhausted"} and not t.get("recipe")]
        if finished and not values.replicate and not values.task_id:
            from optimization_framework.contracts.commands import TrialContinueInput
            latest = max(finished, key=lambda t: t.get("created_at") or "")
            try:
                trial = workspace.continue_trial(TrialContinueInput(trial_id=latest["id"], wall_seconds=values.worker_seconds))
                return {"hypothesis_id": values.hypothesis_id, "how": "trial.continue", "trial_id": trial["id"], "continued_from": latest["id"]}
            except ValueError as exc:
                if "no saved state" not in str(exc):
                    raise
                # Nothing to go on from: a fresh run of the same strategy, said so in the outcome.
        if hypothesis.get("algorithm") == "unchosen" and not hypothesis.get("implementation_version_id"):
            raise ValueError("No method is chosen for this strategy yet; choose one (hypothesis.edit) before running it")
        if not hypothesis.get("executable") and not hypothesis.get("implementation_version_id"):
            raise ValueError("This strategy has no runnable algorithm yet; ask for an implementation first")
        from optimization_framework.contracts.requests import TrialInput
        current = workspace.current_tasks(command.campaign_id)
        if values.task_id:
            task = next((t for t in current if t["id"] == values.task_id and t.get("split") != "test"), None)
            if task is None:
                raise ValueError("Not a current development or selection task of this campaign")
        else:
            task = next((t for t in current if t.get("split", "development") in {"development", "dev", "train", "training"}), None)
        if task is None:
            raise ValueError("The campaign has no development task to run on")
        seeds = {t.get("seed") for t in trials}
        seed = next(s for s in range(0, 100000) if s not in seeds)
        request = TrialInput(campaign_id=command.campaign_id, task_id=task["id"], algorithm=hypothesis.get("algorithm") or "", implementation_version_id=hypothesis.get("implementation_version_id"),
                             algorithm_config=hypothesis.get("algorithm_config") or {}, seed=seed, wall_seconds=values.worker_seconds, hypothesis_id=values.hypothesis_id,
                             question=f"{hypothesis['title']}: allocation of {values.worker_seconds:g} s"
                                      + (f" on {task['name']}" if values.task_id else "") + f" ({values.rationale[:120]})")
        trial = workspace.create_trial(request)
        return {"hypothesis_id": values.hypothesis_id, "how": "trial.create", "trial_id": trial["id"], "seed": seed,
                **({"not_continued": "the finished run saved no state to continue from"} if finished and not values.replicate else {})}

    def batch(command, actor):
        values = InterventionInput(**command.payload)
        campaign = workspace.store.get(command.campaign_id, "campaign")
        results = []
        commands._batch_depth = getattr(commands, "_batch_depth", 0) + 1
        try:
            for index, item in enumerate(values.items, 1):
                child = Command(id=f"{command.id}_i{index}", campaign_id=command.campaign_id, operation=item.operation, expected_revision=campaign["version"],
                                expected_guidance_revision=command.expected_guidance_revision, expected_authority_hash=command.expected_authority_hash,
                                expected_thread_revision=command.expected_thread_revision, origin=command.origin, payload=item.payload)
                receipt = commands.execute(child, actor=actor)
                results.append({"operation": item.operation, "command_id": receipt["id"], "outcome": receipt["outcome"]})
        finally:
            commands._batch_depth -= 1
        record = {"id": "intervention_" + command.id, "campaign_id": command.campaign_id, "origin": command.origin.model_dump(mode="json") if command.origin else None,
                  "actor": actor, "items": results, "rationale": values.rationale, "all_or_nothing": values.all_or_nothing, "created_at": now()}
        workspace.store.put_immutable("intervention", record, "intervention.applied")
        if actor == "researcher":
            workspace.memory.bump(command.campaign_id)
        return {"intervention_id": record["id"], "items": results}

    commands.register("hypothesis.allocate", allocate, model=AllocateInput, delegable=True)
    commands.register("intervention.batch", batch, model=InterventionInput, delegable=True)
