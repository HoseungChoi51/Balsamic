"""A method that stops on its own (it returns no proposal) completes as method_finished, keeps its best, and holds its
final value in a comparison instead of shrinking every method's matched cost; any other exception still fails the run."""
from types import SimpleNamespace

import pytest

from optimization_framework.analysis.general import report
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, TaskInput, TrialInput
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.worker import read_journal, run
from optimization_framework.optimizers.finish import MethodFinished
from optimization_framework.optimizers.lifecycle import AskTellAdapter
from optimization_framework.optimizers.packaged import PackagedOptimizer


class Three:
    """An optimizer_v1 module's optimizer that proposes three fixed points, then finishes (returns [] or raises)."""

    def __init__(self, context, ending="empty"):
        self.ending = ending

    def initialize(self, problem, parameters, seed, assets):
        self.bounds = problem["candidate_schema"]["bounds"]
        self.count = 0

    def propose(self, max_candidates=1):
        if self.count >= 3:
            if self.ending == "empty":
                return []
            if self.ending == "stop":
                raise StopIteration("enumeration exhausted")
            raise RuntimeError("the method broke")
        self.count += 1
        point = [low + (high - low) * self.count / 4 for low, high in self.bounds]
        return [{"id": f"p{self.count}", "candidate": point}]

    def observe(self, observations):
        pass

    def checkpoint(self):
        return str(self.count).encode()

    def restore(self, raw):
        self.count = int(raw)

    def inspect(self):
        return {"proposals": self.count}


def module(ending="empty"):
    return SimpleNamespace(create_optimizer=lambda context: Three(context, ending))


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Finishing", compute_budget_seconds=200, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})]))
    return workspace, campaign["id"], workspace.current_tasks(campaign["id"])[0]


def experiment(lab, algorithm, *, max_steps, ending=None, seed=0):
    workspace, campaign_id, task = lab
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm=algorithm,
                                              max_steps=max_steps, wall_seconds=20, seed=seed))
    optimizer = None
    if ending:
        optimizer = PackagedOptimizer(module(ending), ProblemInstance(**trial["problem"]), {}, seed)
    result = run(workspace.job_dir(trial["id"]), optimizer=optimizer)
    trial.update(result=result, progress=result, attempt=1, status=result["status"])
    workspace.store.put("trial", trial)
    workspace.capture_evidence(trial)
    return trial


@pytest.mark.parametrize("ending", ["empty", "stop"])
def test_a_method_that_returns_no_proposal_completes_with_its_best_kept(lab, ending):
    trial = experiment(lab, "random", max_steps=10, ending=ending)
    result = trial["result"]
    assert result["status"] == "completed" and result["reason"] == "method_finished"
    assert result["method_finished"] and result["scientific_complete"] and result["process_exit"] == 0
    assert result["evaluations"] == 3 and result["allocation_stop"] is None
    observations = read_journal(lab[0].job_dir(trial["id"]) / "observations.jsonl")
    assert len(observations) == 3 and result["best_objective"] == min(row["objectives"]["value"] for row in observations)
    assert result.get("finish_reason") == ("enumeration exhausted" if ending == "stop" else None)
    assert (lab[0].job_dir(trial["id"]) / "outputs.json").exists()


def test_a_resumed_finished_run_finishes_at_once(lab):
    workspace, _, _ = lab
    trial = experiment(lab, "random", max_steps=10, ending="empty")
    directory = workspace.job_dir(trial["id"])
    again = run(directory, optimizer=PackagedOptimizer(module(), ProblemInstance(**trial["problem"]), {}, 0))
    assert again["status"] == "completed" and again["reason"] == "method_finished" and again["evaluations"] == 3
    assert len(read_journal(directory / "requests.jsonl")) == 3


def test_any_other_exception_still_fails_the_run(lab):
    result = experiment(lab, "random", max_steps=10, ending="broken")["result"]
    assert result["status"] == "failed" and "RuntimeError: the method broke" in result["reason"]
    assert not result["method_finished"] and not result["scientific_complete"]


def test_an_ask_tell_method_finishes_by_raising_stop_iteration():
    class Two:
        count = 0

        def ask(self):
            if self.count == 2:
                raise StopIteration
            return [0.5, 0.5]

        def tell(self, candidate, utility):
            self.count += 1

    descriptor = {"candidate_schema": {"representation": "continuous", "dimensions": 2, "bounds": [[0, 1], [0, 1]]},
                  "primary_objective": {"name": "value", "direction": "minimize"}}
    adapter = AskTellAdapter(lambda *args: Two())
    adapter.initialize(descriptor, {}, 0, [])
    adapter.optimizer.count = 2
    with pytest.raises(MethodFinished):
        adapter.propose(1)
    assert adapter.sequence == 0 and adapter.pending == []


def test_a_comparison_holds_a_finished_value_and_matches_at_the_long_runs_cost(lab):
    workspace, campaign_id, _ = lab
    short = experiment(lab, "random", max_steps=10, ending="empty")
    long = experiment(lab, "coordinate", max_steps=8, seed=1)
    group = report(workspace, campaign_id, cost_axis="evaluation_requests")["groups"][0]
    rows = {trial["id"]: trial for trial in group["trials"]}
    assert rows[short["id"]]["held_after_finish"] and not rows[short["id"]]["censored"]
    assert not rows[long["id"]]["held_after_finish"]
    assert rows[short["id"]]["curve"][-1]["cost"] < rows[long["id"]]["curve"][-1]["cost"]
    assert group["common_observed_cost"] == rows[long["id"]]["curve"][-1]["cost"]
    summaries = {summary["algorithm"]: summary for summary in group["method_summaries"]}
    assert summaries["random"]["observed_count"] == 1 and summaries["random"]["mean"] == short["result"]["best_objective"]
    assert summaries["coordinate"]["mean"] == long["result"]["best_objective"]


def test_when_every_run_finished_the_comparison_is_at_the_shortest(lab):
    workspace, campaign_id, _ = lab
    trials = [experiment(lab, "random", max_steps=10, ending="empty", seed=seed) for seed in (0, 1)]
    group = report(workspace, campaign_id, cost_axis="evaluation_requests")["groups"][0]
    assert group["common_observed_cost"] == min(trial["curve"][-1]["cost"] for trial in group["trials"])
    assert group["method_summaries"][0]["observed_count"] == len(trials)


LIBRARY = '''
import json
from optimization_framework.optimizers.packaged import PackagedPlugin


class Two:
    """Proposes two designs, then finishes; with UNEVEN the second replay of seed 7 finishes a step early, on purpose."""
    def __init__(self, context):
        CREATED.append(context["seed"])
        self.limit = 1 if UNEVEN and CREATED.count(7) == 2 else 2

    def initialize(self, problem, parameters, seed, assets):
        self.n, self.count = problem["candidate_schema"]["dimensions"], 0

    def propose(self, max_candidates=1):
        if self.count >= self.limit:
            return []
        self.count += 1
        return [{"id": f"p{self.count}", "candidate": [self.count % 2] * self.n}]

    def observe(self, observations):
        pass

    def checkpoint(self):
        return json.dumps(self.count).encode()

    def restore(self, raw):
        self.count = json.loads(raw)

    def inspect(self):
        return {"proposals": self.count}


UNEVEN = False
CREATED = []


def create_optimizer(context):
    return Two(context)


class Plugin(PackagedPlugin):
    METHODS = {"two": {"module": __import__(__name__), "name": "Two designs", "description": "Test library."}}
'''


def test_the_contract_checks_accept_a_method_that_finishes_alike_on_every_replay(tmp_path, monkeypatch):
    import textwrap
    from optimization_framework.evaluation.registry import problems
    from optimization_framework.optimizers import conformance
    from optimization_framework.optimizers.plugins import OptimizerPlugins
    (tmp_path / "two_library.py").write_text(textwrap.dedent(LIBRARY))
    monkeypatch.syspath_prepend(str(tmp_path))
    plugins = OptimizerPlugins({"two": "two_library:Plugin"})
    instance = problems.get("meent_grating").implementation_fixture({}, 16)
    assert conformance.check("two", instance, optimizer_plugins=plugins)["finished_at_step"] == {0: 2, 7: 2}
    import two_library
    monkeypatch.setattr(two_library, "UNEVEN", True)
    monkeypatch.setattr(two_library, "CREATED", [])
    with pytest.raises(AssertionError, match="finished in one replay and not the other"):
        conformance.check("two", instance, optimizer_plugins=plugins)
