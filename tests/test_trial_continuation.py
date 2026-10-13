"""A changed evaluator must reproduce recorded results before a finished run is carried on under it."""
import json
import time

import pytest

from optimization_framework.contracts.commands import EquivalenceInput, TrialContinueInput
from optimization_framework.contracts.requests import CampaignInput, ControlInput, TaskInput, TrialInput
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.equivalence import compare, sample
from optimization_framework.execution.service import ACTIVE, Workspace, alive
from optimization_framework.execution.worker import read_journal
from optimization_framework.optimizers.registry import create


def test_replay_evaluates_the_listed_candidates_in_order():
    from optimization_framework.optimizers.reference import Replay
    instance = problems.resolve("bounded_continuous", {"dimensions": 2})
    assert create("replay", instance, {"candidates": [[1., 2.], [0., 0.]]}, 0, 2).propose()[0].candidate == [1., 2.]
    replay, proposed = Replay([[1., 2.], [0., 0.]]), []
    for _ in range(2):
        proposed.append(replay.ask())
        replay.tell(proposed[-1], 0.)
    assert proposed == [[1., 2.], [0., 0.]] and replay.state_dict() == {"count": 2}
    with pytest.raises(ValueError, match="Every listed candidate"):
        replay.ask()
    with pytest.raises(ValueError, match="at least one candidate"):
        create("replay", instance, {}, 0, 1)


def test_sample_takes_the_best_and_a_spread_and_compare_reports_every_disagreement():
    rows = [{"id": f"o{index}", "candidate": [index], "objectives": {"value": float(index % 7)}, "status": "ok"} for index in range(40)]
    chosen = sample(rows, 6, lambda row: row["objectives"]["value"])
    assert len(chosen) == 6 and [row["objectives"]["value"] for row in chosen[:3]] == [6., 6., 6.]
    assert len({row["id"] for row in chosen}) == 6 and len(sample(rows[:2], 6, lambda row: 0)) == 2
    # Chosen by scalar fields alone: only the rows that are considered are read whole.
    read = []
    light = [(index, row["objectives"]) for index, row in enumerate(rows)]
    assert sample(light, 6, lambda item: item[1]["value"], lambda item: read.append(item[0]) or rows[item[0]]) == chosen and len(read) <= 9
    assert compare(chosen, chosen, 1e-9, 1e-9) == (0., [])
    drifted = [{**row, "objectives": {"value": row["objectives"]["value"] + (1e-12 if index else 1e-3)}} for index, row in enumerate(chosen)]
    largest, failures = compare(chosen, drifted, 1e-9, 1e-9)
    assert largest == pytest.approx(1e-3) and [failure["index"] for failure in failures] == [0]
    assert compare(chosen, chosen[:4], 1e-9, 1e-9)[1][-1]["reason"].startswith("4 of 6")
    assert compare(chosen[:1], [{**chosen[0], "candidate": [99]}], 1e-9, 1e-9)[1][0]["reason"] == "The candidate was not evaluated again"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    instance = Workspace(tmp_path / "workspace", max_workers=2)
    instance.start()
    yield instance
    for trial in instance.store.list("trial"):
        if trial["status"] in ACTIVE:
            instance.control(trial["id"], ControlInput(action="stop"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(alive(trial) for trial in instance.store.list("trial")):
        time.sleep(.05)
    instance.close()


def finished(workspace, trial_id, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        trial = workspace.store.get(trial_id, "trial")
        if trial["status"] not in ACTIVE:
            assert trial["status"] == "completed", (trial["status"], trial.get("reason"))
            return trial
        time.sleep(.05)
    pytest.fail(f"Timed out waiting for {trial_id}")


def candidates(workspace, trial_id):
    return [row["candidate"] for row in read_journal(workspace.job_dir(trial_id) / "observations.jsonl")]


def test_a_finished_run_goes_on_as_a_new_experiment_and_a_changed_source_needs_equivalence_first(workspace):
    created = workspace.create_campaign(CampaignInput(name="Continuation", compute_budget_seconds=600, validation_reserve_seconds=30, llm_budget_usd=0,
        tasks=[TaskInput(name="Small grating", physics={"n_cells": 6, "fourier_order": 1})]))
    task = workspace.current_tasks(created["id"])[0]
    run = lambda steps: workspace.create_trial(TrialInput(campaign_id=created["id"], task_id=task["id"], algorithm="hillclimb", seed=3,
        max_steps=steps, schedule_steps=30, wall_seconds=30))
    whole, first = run(12), run(6)
    whole, first = finished(workspace, whole["id"]), finished(workspace, first["id"])
    second = workspace.continue_trial(TrialContinueInput(trial_id=first["id"], wall_seconds=30, max_steps=6))
    assert second["chain_id"] == first["id"] and second["continues"]["same_source"] and not second["continues"]["unverified"]
    second = finished(workspace, second["id"])
    # The search goes on exactly where it stopped, and the best design so far comes along.
    assert candidates(workspace, first["id"]) + candidates(workspace, second["id"]) == candidates(workspace, whole["id"])
    rows = read_journal(workspace.job_dir(second["id"]) / "metrics.jsonl")
    assert rows[0]["step"] == 1 and rows[0]["best_objective"] >= first["result"]["best_objective"]
    assert second["result"]["best_objective"] == whole["result"]["best_objective"] and second["result"]["evaluations"] == 6

    # The same run recorded under an older source: nothing shows yet that today's evaluator agrees with it.
    workspace.store.put("trial", {**first, "scientific_source_hash": "0" * 64})
    with pytest.raises(ValueError, match="Run evaluator.equivalence"):
        workspace.continue_trial(TrialContinueInput(trial_id=first["id"], wall_seconds=30))
    assert len(list(workspace.job_dir(first["id"]).parent.iterdir())) == len(workspace.store.list("trial"))   # the refused trial left nothing behind
    check = workspace.equivalence.start(created["id"], EquivalenceInput(trial_id=first["id"], sample=4))
    assert len(check["expected"]) == 4 and check["from_source"] == "0" * 64 and check["to_source"] == second["scientific_source_hash"]
    finished(workspace, check["replay_trial_id"])
    deadline = time.monotonic() + 10
    while workspace.store.get(check["id"], "evaluator_equivalence")["status"] == "running" and time.monotonic() < deadline:
        time.sleep(.05)
    check = workspace.store.get(check["id"], "evaluator_equivalence")
    assert (check["verdict"], check["largest_difference"], check["failures"], check["candidates"]) == ("passed", 0., [], 4)
    third = workspace.continue_trial(TrialContinueInput(trial_id=first["id"], wall_seconds=30, max_steps=6))
    assert third["continues"] | {"checkpoint_sha256": None} == {**second["continues"], "checkpoint_sha256": None, "same_source": False, "equivalence_id": check["id"]}
    assert candidates(workspace, finished(workspace, third["id"])["id"]) == candidates(workspace, second["id"])

    # Without a comparison only the researcher's explicit decision carries a run on, and the chain says so.
    workspace.store.put("trial", {**first, "scientific_source_hash": "1" * 64})
    unverified = workspace.continue_trial(TrialContinueInput(trial_id=first["id"], wall_seconds=30, max_steps=2, accept_unverified=True))
    assert unverified["continues"]["unverified"] and unverified["continues"]["equivalence_id"] is None
    finished(workspace, unverified["id"])
    with pytest.raises(ValueError, match="still running|Select an optimization experiment"):
        workspace.continue_trial(TrialContinueInput(trial_id=check["replay_trial_id"], wall_seconds=30))


def test_a_comparison_reads_a_continued_run_as_one_and_compares_the_runs_it_is_given(workspace):
    from optimization_framework.analysis.general import report
    created = workspace.create_campaign(CampaignInput(name="Compared", compute_budget_seconds=600, validation_reserve_seconds=30, llm_budget_usd=0,
        tasks=[TaskInput(name="Small grating", physics={"n_cells": 6, "fourier_order": 1})]))
    task = workspace.current_tasks(created["id"])[0]
    run = lambda steps, seed: workspace.create_trial(TrialInput(campaign_id=created["id"], task_id=task["id"], algorithm="hillclimb", seed=seed,
        max_steps=steps, schedule_steps=30, wall_seconds=30))
    whole, first, quick = run(12, 3), run(6, 3), run(2, 4)
    whole, first, quick = (finished(workspace, trial["id"]) for trial in (whole, first, quick))
    second = finished(workspace, workspace.continue_trial(TrialContinueInput(trial_id=first["id"], wall_seconds=30, max_steps=6))["id"])
    compared = lambda **options: report(workspace, created["id"], cost_axis="evaluation_requests", cost_view="actual_expenditure", **options)
    result = compared()
    rows = {row["id"]: row for group in result["groups"] for row in group["trials"]}
    # The continued run is one row, named by its last experiment, with the first six evaluations in front.
    assert set(rows) == {whole["id"], second["id"], quick["id"]} and rows[second["id"]]["chain_trial_ids"] == [first["id"], second["id"]]
    assert {"trial_id": first["id"], "reason": f"Continued by {second['id']}; reported as the beginning of that run"} in result["excluded"]
    joined, straight = rows[second["id"]]["curve"], rows[whole["id"]]["curve"]
    assert joined[0]["cost"] == 1 and joined[-1]["cost"] == straight[-1]["cost"] == 12
    assert [point["objective"] for point in joined] == [point["objective"] for point in straight]   # the same search, in two experiments
    assert "chain_trial_ids" not in rows[whole["id"]]
    # Every run is read at the cost the shortest reached: the two-evaluation run sets it for all.
    assert result["groups"][0]["common_observed_cost"] == 2
    # Naming the long runs compares them with each other.
    long = compared(trial_ids=[whole["id"], second["id"]])
    assert long["groups"][0]["common_observed_cost"] == 12
    assert [row["id"] for row in long["groups"][0]["trials"]] == [whole["id"], second["id"]]
    # Named alone, the first experiment is the run as it stood before it was continued.
    alone = compared(trial_ids=[first["id"]])["groups"][0]
    assert [(row["id"], row["curve"][-1]["cost"]) for row in alone["trials"]] == [(first["id"], 6)]
    with pytest.raises(ValueError, match="Not experiments of this campaign: trial_missing"):
        compared(trial_ids=["trial_missing"])
    # The same choice through the command, as the lead agent issues it.
    from optimization_framework.contracts.commands import Command
    receipt = workspace.commands.execute(Command(id="compare_long", campaign_id=created["id"], expected_revision=workspace.store.get(created["id"], "campaign")["version"],
        operation="comparison.report", payload={"cost_axis": "evaluation_requests", "cost_view": "actual_expenditure", "trial_ids": [whole["id"], second["id"]]}))
    assert receipt["outcome"]["groups"][0]["common_observed_cost"] == 12
