"""A plain function ``(problem, evaluate, rng)`` runs as a method: returning finishes it, the run's caps stop it, a pause
and resume replay its journal, and a method that is not deterministic for its seed is refused on resume."""
import json
import time

import pytest

from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, TaskInput, TrialInput
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.worker import read_journal, run
from optimization_framework.optimizers.finish import MethodFinished
from optimization_framework.optimizers.functions import FunctionMethod, StopSearch


def one_shot(problem, evaluate, rng):
    """Three evaluations, then returns."""
    bounds = problem["candidate_schema"]["bounds"]
    for _ in range(3):
        evaluate([float(rng.uniform(low, high)) for low, high in bounds])


def endless(problem, evaluate, rng):
    bounds = problem["candidate_schema"]["bounds"]
    while True:
        evaluate(rng.uniform([low for low, _ in bounds], [high for _, high in bounds]))


def swallowing(problem, evaluate, rng):
    """Wraps evaluate in ``except Exception`` and never returns; StopSearch still ends it."""
    while True:
        try:
            evaluate([float(rng.uniform(-1, 1)), 0.0])
        except Exception:
            pass


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Functions", compute_budget_seconds=200, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})]))
    return workspace, campaign["id"], workspace.current_tasks(campaign["id"])[0]


def trial_of(lab, *, max_steps=20, wall_seconds=20, seed=0):
    workspace, campaign_id, task = lab
    return workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm="random",
                                             max_steps=max_steps, wall_seconds=wall_seconds, seed=seed))


def execute(lab, trial, fn, **kwargs):
    method = FunctionMethod(fn, ProblemInstance(**trial["problem"]), {}, trial["seed"])
    result = run(lab[0].job_dir(trial["id"]), optimizer=method, **kwargs)
    return result, method


def candidates(lab, trial):
    return [row["candidate"] for row in read_journal(lab[0].job_dir(trial["id"]) / "observations.jsonl")]


def test_a_one_shot_method_finishes_with_its_best(lab):
    trial = trial_of(lab)
    result, method = execute(lab, trial, one_shot)
    assert result["status"] == "completed" and result["reason"] == "method_finished"
    assert result["method_finished"] and result["scientific_complete"] and result["evaluations"] == 3
    observations = read_journal(lab[0].job_dir(trial["id"]) / "observations.jsonl")
    assert result["best_objective"] == min(row["objectives"]["value"] for row in observations)
    assert not method.thread.is_alive()


def test_a_returned_string_is_the_methods_reason():
    instance = ProblemInstance(**problems.resolve("bounded_continuous", {"dimensions": 2}).model_dump())
    method = FunctionMethod(lambda problem, evaluate, rng: "nothing left to try", instance, {}, 0)
    try:
        with pytest.raises(MethodFinished) as finished:
            method.propose(1)
        assert finished.value.reason == "nothing left to try"
    finally:
        method.close()


def test_an_endless_method_is_stopped_by_the_evaluation_cap(lab):
    trial = trial_of(lab, max_steps=5)
    result, method = execute(lab, trial, endless)
    assert result["status"] == "completed" and result["reason"] == "step_budget_exhausted"
    assert result["evaluations"] == 5 and not result["method_finished"]
    assert not method.thread.is_alive()


def test_an_endless_method_is_stopped_by_the_wall_cap(lab):
    def slow(problem, evaluate, rng):
        while True:
            time.sleep(0.02)
            evaluate([float(rng.uniform(-1, 1)), 0.0])

    trial = trial_of(lab, max_steps=100000, wall_seconds=0.5)
    result, method = execute(lab, trial, slow)
    assert result["status"] == "completed" and result["reason"] == "wall_budget_exhausted"
    assert 0 < result["evaluations"] < 100000
    assert not method.thread.is_alive()


def test_a_method_that_swallows_exceptions_still_stops(lab):
    trial = trial_of(lab, max_steps=4)
    result, method = execute(lab, trial, swallowing)
    assert result["status"] == "completed" and result["evaluations"] == 4
    assert not method.thread.is_alive()


def test_a_method_that_raises_fails_with_its_message(lab):
    def broken(problem, evaluate, rng):
        evaluate([0.0, 0.0])
        raise ValueError("the idea did not work")

    result, _ = execute(lab, trial_of(lab), broken)
    assert result["status"] == "failed" and result["reason"] == "ValueError: the idea did not work"
    assert not result["method_finished"]


def test_an_invalid_candidate_is_a_value_error_the_method_may_catch(lab):
    seen = []

    def careful(problem, evaluate, rng):
        try:
            evaluate([99.0, 0.0])
        except ValueError as exc:
            seen.append(str(exc))
        evaluate([1.0, 1.0])
        return "done"

    result, _ = execute(lab, trial_of(lab), careful)
    assert result["status"] == "completed" and result["reason"] == "method_finished"
    assert result["evaluations"] == 2 and result["finish_reason"] == "done"
    assert seen and "bounds" in seen[0]


class PauseAfter:
    """The lab's evaluator, which asks the worker to pause once it has evaluated ``count`` candidates."""

    def __init__(self, inner, directory, count):
        self.inner, self.directory, self.count, self.done = inner, directory, count, 0

    def evaluate(self, candidate):
        evaluation = self.inner.evaluate(candidate)
        self.done += 1
        if self.done == self.count:
            (self.directory / "control.json").write_text(json.dumps({"revision": 0, "command": "pause"}))
        return evaluation

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_pause_and_resume_reproduce_the_journal(lab):
    straight = trial_of(lab, max_steps=6, seed=3)
    assert execute(lab, straight, endless)[0]["evaluations"] == 6

    paused = trial_of(lab, max_steps=6, seed=3)
    directory = lab[0].job_dir(paused["id"])
    instance = ProblemInstance(**paused["problem"])
    first, method = execute(lab, paused, endless, evaluator=PauseAfter(problems.evaluator(instance), directory, 3))
    assert first["status"] == "paused" and first["evaluations"] == 3
    assert not method.thread.is_alive()
    (directory / "control.json").write_text(json.dumps({"revision": 1, "command": "run"}))
    resumed, again = execute(lab, paused, endless)
    assert resumed["status"] == "completed" and resumed["evaluations"] == 6
    assert len(read_journal(directory / "requests.jsonl")) == 6
    assert candidates(lab, paused) == candidates(lab, straight)
    assert again.checkpoint()["log"][:3] == method.checkpoint()["log"]


def test_a_method_that_uses_the_clock_is_refused_on_resume(lab):
    def clocked(problem, evaluate, rng):
        while True:
            evaluate([(time.time_ns() % 1000) / 1000, 0.0])

    trial = trial_of(lab, max_steps=6)
    directory = lab[0].job_dir(trial["id"])
    instance = ProblemInstance(**trial["problem"])
    first, _ = execute(lab, trial, clocked, evaluator=PauseAfter(problems.evaluator(instance), directory, 2))
    assert first["status"] == "paused"
    (directory / "control.json").write_text(json.dumps({"revision": 1, "command": "run"}))
    resumed, method = execute(lab, trial, clocked)
    assert resumed["status"] == "failed" and "not deterministic for its seed" in resumed["reason"]
    assert len(read_journal(directory / "requests.jsonl")) == 2
    assert not method.thread.is_alive()


def test_the_problem_is_read_only_and_one_method_is_live_per_process():
    instance = ProblemInstance(**problems.resolve("bounded_continuous", {"dimensions": 2}).model_dump())
    method = FunctionMethod(one_shot, instance, {}, 0)
    try:
        with pytest.raises(TypeError):
            method.problem["public"] = {}
        assert method.problem["candidate_schema"]["dimensions"] == 2
        with pytest.raises(RuntimeError, match="Another function method is live"):
            FunctionMethod(one_shot, instance, {}, 1)
    finally:
        method.close()
    FunctionMethod(one_shot, instance, {}, 1).close()


def test_stop_search_is_not_an_exception():
    assert issubclass(StopSearch, BaseException) and not issubclass(StopSearch, Exception)
