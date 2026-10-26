"""Both domains share one worker; recovery retains physical expenditure."""
import json

import pytest

from optimization_framework.contracts.problems import Proposal
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.worker import ExperimentWorker, append_json, read_journal, run
from optimization_framework.storage.artifacts import atomic_json


def prepare(directory, *, problem_id="bounded_continuous", algorithm="coordinate", max_steps=12, wall=60, config=None):
    directory.mkdir(parents=True, exist_ok=True)
    config = config or ({"n_cells": 4, "fourier_order": 1} if problem_id == "meent_grating" else {"dimensions": 2})
    problem = problems.resolve(problem_id, config)
    spec = {"id": "experiment_test", "campaign_id": "campaign_test", "study_id": "study_test", "seed": 42,
            "algorithm": algorithm, "algorithm_config": {}, "problem": problem.model_dump(mode="json"),
            "max_steps": max_steps, "wall_seconds": wall, "schedule_steps": 30,
            "recovery": {"every_observations": 5, "every_seconds": 30}}
    atomic_json(directory / "spec.json", spec)
    return spec


@pytest.mark.parametrize("problem,algorithm", [("bounded_continuous", "coordinate"), pytest.param("meent_grating", "hillclimb", marks=pytest.mark.meent)])
def test_common_lifecycle_and_cooperative_continuation(tmp_path, problem, algorithm):
    full, split = tmp_path / "full", tmp_path / "split"
    prepare(full, problem_id=problem, algorithm=algorithm)
    prepare(split, problem_id=problem, algorithm=algorithm, max_steps=6)
    expected = run(full)
    first = run(split)
    assert first["status"] == expected["status"] == "completed"
    atomic_json(split / "control.json", {"command": "run", "max_steps": 12, "revision": 1})
    second = run(split)
    assert second["status"] == "completed", second
    assert second["best_objective"] == expected["best_objective"]
    assert second["best_candidate"] == expected["best_candidate"]
    keys = ("candidate", "objectives", "status")
    assert [{k: o[k] for k in keys} for o in read_journal(full / "observations.jsonl")] == [
        {k: o[k] for k in keys} for o in read_journal(split / "observations.jsonl")]
    assert second["elapsed_seconds"] > first["elapsed_seconds"]


@pytest.mark.meent
def test_metrics_journal_names_the_best_design_by_its_observation(tmp_path):
    prepare(tmp_path, problem_id="meent_grating", algorithm="hillclimb")
    result = run(tmp_path)
    rows = read_journal(tmp_path / "metrics.jsonl")
    assert len(rows) == result["step"] == 12
    assert not any(key in row for row in rows for key in ("archive", "best_candidate", "best_design"))
    designs = {row["id"]: row["candidate"] for row in read_journal(tmp_path / "observations.jsonl")}
    assert all(row["best_observation_id"] in designs for row in rows)
    for previous, row in zip(rows, rows[1:]):
        assert row["best_observation_id"] == previous["best_observation_id"] or row["best_objective"] != previous["best_objective"]
    assert designs[rows[-1]["best_observation_id"]] == result["best_candidate"]
    # The current archive stays in the progress record, and a new attempt names its best design too.
    assert json.loads((tmp_path / "progress.json").read_text())["archive"] == result["archive"]
    atomic_json(tmp_path / "control.json", {"command": "run", "max_steps": 13, "revision": 1})
    run(tmp_path)
    assert read_journal(tmp_path / "metrics.jsonl")[12]["best_observation_id"] in {row["id"] for row in read_journal(tmp_path / "observations.jsonl")}


def test_forced_rollback_retains_suffix_and_repeats_from_checkpoint(tmp_path):
    prepare(tmp_path, max_steps=8)
    first = ExperimentWorker(tmp_path)
    first.one_step()
    first.one_step()
    suffix = read_journal(tmp_path / "observations.jsonl")
    # Simulate a process disappearing after two observations, before its next checkpoint.
    recovered = ExperimentWorker(tmp_path)
    assert recovered.step == 0
    assert recovered.recovered_suffix == 2
    recovered.one_step()
    evidence = read_journal(tmp_path / "observations.jsonl")
    assert evidence[:2] == suffix
    assert evidence[2]["candidate"] == suffix[0]["candidate"]
    assert evidence[2]["attempt_id"] != suffix[0]["attempt_id"]
    result = recovered.run()
    assert result["evaluations"] == 8
    assert result["step"] == 6
    assert not result["scientific_complete"]
    assert result["solver_calls"] >= 6


def test_unconfirmed_request_is_uncertain_once_and_never_fabricated_as_zero(tmp_path):
    prepare(tmp_path, max_steps=4)
    first = ExperimentWorker(tmp_path)
    append_json(tmp_path / "requests.jsonl", {"id": "lost", "attempt_id": first.attempt_id,
        "proposal_id": "proposal_lost", "candidate": [0., 0.]})
    second = ExperimentWorker(tmp_path)
    third = ExperimentWorker(tmp_path)
    assert len(second.observations) == len(third.observations) == 1
    assert third.observations[0]["status"] == "uncertain"
    assert third.observations[0]["objectives"] == {}
    result = third.run()
    assert result["evaluations"] == 4 and result["interrupted_requests"] == 1
    assert result["unknown_solver_cost"]
    assert not result["scientific_complete"]


def test_bad_candidate_is_a_typed_failure_with_no_fake_score(tmp_path):
    prepare(tmp_path)
    worker = ExperimentWorker(tmp_path)
    worker.optimizer.propose = lambda _: [Proposal(id="outside", candidate=[99., 99.])]
    result = worker.run()
    observations = read_journal(tmp_path / "observations.jsonl")
    assert observations[0]["status"] == "invalid_candidate"
    assert observations[0]["objectives"] == {}
    assert result["status"] == "failed" and result["solver_calls"] == 0


def test_clean_exit_at_wall_limit_does_not_claim_scientific_completion(tmp_path):
    prepare(tmp_path, wall=1e-9)
    result = run(tmp_path)
    assert result["process_exit"] == 0
    assert result["allocation_stop"] == "wall_budget_exhausted"
    assert result["scientific_complete"] is False


def test_changed_science_cannot_restore_old_state(tmp_path):
    spec = prepare(tmp_path, max_steps=2)
    run(tmp_path)
    spec["seed"] += 1
    atomic_json(tmp_path / "spec.json", spec)
    result = run(tmp_path)
    assert result["status"] == "failed"
    assert "incompatible" in result["reason"]


def test_nonfinite_proposal_retains_invalid_request_evidence(tmp_path):
    prepare(tmp_path)
    worker = ExperimentWorker(tmp_path)
    worker.optimizer.propose = lambda _: [Proposal(id="nonfinite", candidate=[float("nan"), 0.])]
    result = worker.run()
    assert result["status"] == "failed" and result["budget_requests"] == 1
    observation = read_journal(tmp_path / "observations.jsonl")[0]
    assert observation["status"] == "invalid_candidate" and observation["objectives"] == {}
    assert "invalid_representation" in observation["candidate"]


@pytest.mark.meent
def test_result_gives_every_objective_of_the_best_design(tmp_path):
    prepare(tmp_path, problem_id="meent_grating", algorithm="random", max_steps=6)
    result = run(tmp_path)
    best = next(row for row in read_journal(tmp_path / "observations.jsonl") if row["candidate"] == result["best_candidate"])
    assert result["best_objectives"] == best["objectives"]
    assert result["best_objectives"][result["objective_definition"]["name"]] == result["best_objective"]


@pytest.mark.meent
def test_journals_pack_a_long_binary_design_and_read_either_form(tmp_path):
    from optimization_framework.execution.metrics import PACK_FROM, full_row, scalar_rows
    prepare(tmp_path, problem_id="meent_grating", algorithm="random", max_steps=4, config={"n_cells": 160, "fourier_order": 1})
    result = run(tmp_path)
    for name in ("requests.jsonl", "observations.jsonl"):
        written = [json.loads(line) for line in (tmp_path / name).read_text().splitlines()]
        assert all(set(row["candidate"]) == {"packed_bits", "cells"} and row["candidate"]["cells"] == 160 >= PACK_FROM for row in written)
        read = read_journal(tmp_path / name)
        assert all(len(row["candidate"]) == 160 and set(row["candidate"]) <= {0, 1} for row in read)
        assert [full_row(tmp_path / name, offset) for offset, _, _ in scalar_rows(tmp_path / name)] == read
        assert all(row["candidate"] == [] for _, _, row in scalar_rows(tmp_path / name))
    observations = read_journal(tmp_path / "observations.jsonl")
    assert [row["candidate"] for row in read_journal(tmp_path / "requests.jsonl")] == [row["candidate"] for row in observations]
    assert result["best_candidate"] in [row["candidate"] for row in observations]
    # A journal written before packing holds lists, and reads the same.
    old = tmp_path / "old.jsonl"
    old.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in observations))
    assert read_journal(old) == observations and [full_row(old, offset) for offset, _, _ in scalar_rows(old)] == observations
