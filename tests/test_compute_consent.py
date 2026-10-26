"""Nothing that computes for more than a minute starts from an agent without the researcher's go-ahead, at any step: the agent
asks with approval.request (kind compute), the researcher's approval covers that plan's worker time, and nothing beyond it."""
import pytest

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Consent", autonomy="delegated", compute_budget_seconds=20000,
        validation_reserve_seconds=0, delegated_trial_seconds=1500, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    return workspace, campaign, workspace.current_tasks(campaign["id"])[0]


def send(workspace, campaign_id, identity, operation, payload, actor="manager"):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, **pins), actor=actor)


def run(task, seconds):
    return {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": seconds}


def test_an_agent_starts_nothing_over_a_minute_without_the_researchers_go_ahead(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    with pytest.raises(ValueError, match="approval.request with kind compute") as refused:
        send(workspace, cid, "screen_1", "trial.create", run(task, 590))
    assert "about 10 min" in str(refused.value) and "even when a request implies the work" in str(refused.value)
    send(workspace, cid, "short_probe", "trial.create", run(task, 30))           # a minute or less needs no go-ahead
    send(workspace, cid, "researcher_run", "trial.create", run(task, 590), actor="researcher")   # the researcher's own run
    with pytest.raises(ValueError, match="approval.request with kind compute"):
        send(workspace, cid, "profile", "runtime.profile", {"task_id": task["id"]})   # every step, not only experiments

    send(workspace, cid, "ask", "approval.request", {"kind": "compute", "plan": "Two screening runs of H13, seeds 0 and 1",
        "rationale": "Screen H13 against H12 at matched cost", "wall_seconds": 600, "worker_seconds": 1200,
        "meanwhile": "Read the H12 results on the Experiments page"})
    decision = workspace.store.list("decision", cid)[-1]
    assert decision["title"] == "Start this work now? About 10 min until results"
    assert "Meanwhile: Read the H12 results" in decision["proposal"] and [o["label"] for o in decision["options"]] == ["Start now", "Not now"]
    send(workspace, cid, "approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "",
        "expected_resolution_revision": 0}, actor="researcher")
    [consent] = workspace.store.list("compute_consent", cid)
    assert consent["worker_seconds"] == 1200 and workspace.store.get(decision["id"], "decision")["outcome"] == {"consent_id": consent["id"]}

    send(workspace, cid, "screen_2", "trial.create", run(task, 590))
    send(workspace, cid, "screen_3", "trial.create", run(task, 590))
    assert workspace.store.get(consent["id"], "compute_consent")["used_seconds"] == 1180
    with pytest.raises(ValueError, match="Approved and unused: 20 s of worker time"):
        send(workspace, cid, "screen_4", "trial.create", run(task, 590))


def test_autopilot_runs_within_the_cap_the_researcher_set(lab):
    workspace, campaign, task = lab
    send(workspace, campaign["id"], "autopilot_run", "trial.create", run(task, 590), actor="autopilot")
    assert workspace.store.list("compute_consent", campaign["id"]) == []


def test_a_compute_plan_states_its_times_and_what_to_do_meanwhile(lab):
    workspace, campaign, task = lab
    with pytest.raises(ValueError, match="wall_seconds, worker_seconds and what the researcher can do meanwhile"):
        send(workspace, campaign["id"], "vague", "approval.request", {"kind": "compute", "plan": "Some runs", "rationale": "Screening"})


def test_a_compute_request_for_experiments_shows_their_plan_measured_on_earlier_runs(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    # An earlier run of the same problem: 100 evaluations in 50 s, with journals of known sizes.
    workspace.store.put("trial", {"id": "trial_earlier", "campaign_id": cid, "task_id": task["id"], "algorithm": "coordinate", "status": "completed",
                                  "created_at": "2026-10-26T00:00:00+00:00", "result": {"evaluations": 100, "elapsed_seconds": 50.0}})
    directory = workspace.job_dir("trial_earlier")
    directory.mkdir(parents=True)
    (directory / "observations.jsonl").write_bytes(b"o" * 100_000)
    (directory / "metrics.jsonl").write_bytes(b"m" * 50_000)
    (directory / "spec.json").write_bytes(b"s" * 1_000)
    send(workspace, cid, "ask_plan", "approval.request", {"kind": "compute", "plan": "Two seeds of the coordinate search", "rationale": "Compare seeds",
        "wall_seconds": 600, "worker_seconds": 1200, "meanwhile": "Read the earlier run",
        "runs": [{"task_id": task["id"], "algorithm": "coordinate", "seeds": [0, 1], "wall_seconds": 600, "max_evaluations": 1000}]})
    decision = workspace.store.list("decision", cid)[-1]
    [run] = decision["plan"]["runs"]
    assert run["speed"]["seconds_per_evaluation"] == 0.5 and "measured on trial_earlier (100 evaluations, coordinate" in run["speed"]["basis"]
    assert run["evaluations"] == {"expected": 1000, "ends_by": "the evaluation cap"}
    assert {row["file"]: row["bytes"] for row in run["outputs"]} == {"observations.jsonl": 1_000_000, "metrics.jsonl": 500_000}
    assert run["other_bytes"] == 1_000 and run["disk_bytes"] == 1_501_000 and decision["plan"]["totals"]["disk_bytes"] == 3_002_000
    assert decision["plan"]["warnings"] == ["coordinate: the cap of 1,000 evaluations ends each run after about 8 of its 10 minutes."]
    # A problem no earlier run measured: said, not guessed.
    from optimization_framework.campaigns.experiment_plan import plan
    workspace.store.put("trial", {**workspace.store.get("trial_earlier", "trial"), "task_id": "task_other"})
    unmeasured = plan(workspace, cid, [{"task_id": task["id"], "algorithm": "coordinate", "seeds": [0], "wall_seconds": 600}])
    assert unmeasured["runs"][0]["speed"]["seconds_per_evaluation"] is None and unmeasured["runs"][0]["disk_bytes"] is None
    assert "not measured on this problem" in unmeasured["warnings"][0]


def test_the_researcher_sets_the_run_slots_in_balsamic_and_they_hold_across_restarts(tmp_path):
    workspace = Workspace(tmp_path, max_workers=4, gpu_workers=1)
    with pytest.raises(ValueError, match="at least one slot on CPU"):
        workspace.set_slots(4, 4, authority="researcher")
    workspace.set_slots(6, 2, authority="researcher", reason="H13 joins H12 on the GPU")
    assert workspace.devices.sizes() == {"cuda": 2, "cpu": 4}
    restarted = Workspace(tmp_path, max_workers=4, gpu_workers=1)   # the launcher's settings are only defaults
    view = restarted.slots_view()
    assert (restarted.max_workers, restarted.gpu_workers) == (6, 2) and view["launcher"] == {"workers": 4, "gpu_workers": 1}
    assert view["chosen_by"] == "researcher" and view["reason"] == "H13 joins H12 on the GPU"


def test_a_queued_run_is_placed_on_a_device_until_it_starts(lab):
    from optimization_framework.contracts.requests import ControlInput
    workspace, campaign, task = lab
    trial = send(workspace, campaign["id"], "queued_run", "trial.create", run(task, 30), actor="researcher")["outcome"]["trial"]
    assert workspace.control(trial["id"], ControlInput(action="place", device="cpu"))["device"] == "cpu"
    with pytest.raises(ValueError):   # this problem's evaluator computes on CPU only
        workspace.control(trial["id"], ControlInput(action="place", device="cuda"))
    with pytest.raises(ValueError, match="Name the device"):
        workspace.control(trial["id"], ControlInput(action="place"))
