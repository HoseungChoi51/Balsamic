"""A comparison ranks methods by the objective's direction: the lowest mean first when minimizing (roadmap A2)."""
from optimization_framework.analysis.general import rank, report
from optimization_framework.contracts.problems import Objective
from optimization_framework.contracts.requests import CampaignInput, TaskInput, TrialInput
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.worker import run


def summaries(*means):
    return [{"method_id": f"m{index}", "mean": mean} for index, mean in enumerate(means)]


def test_the_lowest_mean_ranks_first_when_minimizing_and_the_highest_when_maximizing():
    ranked = rank(summaries(0.3, 0.1, 0.2), Objective(name="loss", direction="minimize"))
    assert [s["rank"] for s in ranked] == [3, 1, 2]
    ranked = rank(summaries(0.3, 0.1, 0.2), Objective(name="efficiency", direction="maximize"))
    assert [s["rank"] for s in ranked] == [1, 3, 2]


def test_ties_share_a_rank_and_a_method_without_a_value_has_none():
    ranked = rank(summaries(0.5, None, 0.2, 0.2), Objective(name="loss", direction="minimize"))
    assert [s["rank"] for s in ranked] == [3, None, 1, 1]


def test_a_minimize_report_names_its_direction_and_ranks_the_lowest_mean_first(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Minimize", compute_budget_seconds=200, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})]))
    task = workspace.current_tasks(campaign["id"])[0]
    for seed, method in enumerate(["random", "coordinate"]):
        trial = workspace.create_trial(TrialInput(campaign_id=campaign["id"], task_id=task["id"], algorithm=method, max_steps=6, wall_seconds=20, seed=seed))
        result = run(workspace.job_dir(trial["id"]))
        trial.update(result=result, progress=result, attempt=1, status=result["status"])
        workspace.store.put("trial", trial)
        workspace.capture_evidence(trial)
    group = report(workspace, campaign["id"], cost_axis="evaluation_requests")["groups"][0]
    assert group["direction"] == "minimize"
    ordered = sorted(group["method_summaries"], key=lambda s: s["rank"])
    assert ordered[0]["rank"] == 1 and ordered[0]["mean"] <= ordered[-1]["mean"]
