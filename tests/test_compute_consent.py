"""Compute is the researcher's to start, at any step, under two thresholds they set per campaign: an agent's work up to the first
starts freely, up to the second with a notice in their inbox, and anything longer waits for their go-ahead. The agent asks with
approval.request (kind compute), the researcher's approval covers that plan's worker time, and nothing beyond it."""
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


def test_an_agent_starts_nothing_over_the_go_ahead_threshold_without_the_researchers_go_ahead(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    with pytest.raises(ValueError, match="approval.request with kind compute") as refused:
        send(workspace, cid, "screen_1", "trial.create", run(task, 590))
    assert "about 10 min" in str(refused.value) and "more than 5 min (the researcher's go-ahead threshold)" in str(refused.value)
    assert "even when a request implies the work" in str(refused.value)
    send(workspace, cid, "short_probe", "trial.create", run(task, 30))           # up to the go-ahead threshold needs no go-ahead
    send(workspace, cid, "researcher_run", "trial.create", run(task, 590), actor="researcher")   # the researcher's own run
    with pytest.raises(ValueError, match="approval.request with kind compute"):
        send(workspace, cid, "profile", "runtime.profile", {"task_id": task["id"], "probe_seconds": 300})   # every step, not only experiments

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


def test_work_between_the_thresholds_starts_with_a_notice_that_stays_until_the_researcher_acknowledges_it(lab):
    from balsamic.monitor.rows import acknowledge, inbox_view
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "probe", "trial.create", run(task, 30))              # up to the notice threshold: nothing to say
    assert workspace.store.list("compute_notice", cid) == []
    receipt = send(workspace, cid, "screen", "trial.create", run(task, 240))  # four minutes: it starts, with a notice
    [notice] = workspace.store.list("compute_notice", cid)
    assert notice["what"] == "a run" and notice["seconds"] == 240 and notice["subjects"] == [receipt["outcome"]["trial_id"]]
    [item] = inbox_view(workspace, cid)["unacknowledged"]
    assert item["kind"] == "notice" and item["title"] == "An agent started a run, about 4 min of compute"
    acknowledge(workspace, cid, [item["key"]])
    view = inbox_view(workspace, cid)
    assert view["unacknowledged"] == [] and [row["id"] for row in view["notices"]] == [notice["id"]]   # seen, still listed
    assert view["thresholds"] == {"notice_seconds": 60.0, "gate_seconds": 300.0}
    send(workspace, cid, "mine", "trial.create", run(task, 240), actor="researcher")   # the researcher's own run: no notice
    assert len(workspace.store.list("compute_notice", cid)) == 1


def test_work_an_approved_plan_covers_is_charged_to_it_without_a_notice(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "ask", "approval.request", {"kind": "compute", "plan": "Four short screening runs", "rationale": "Screen H13",
        "wall_seconds": 240, "worker_seconds": 960, "meanwhile": "Read the H12 results"})
    decision = workspace.store.list("decision", cid)[-1]
    send(workspace, cid, "approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "",
        "expected_resolution_revision": 0}, actor="researcher")
    send(workspace, cid, "screen", "trial.create", run(task, 240))
    [consent] = workspace.store.list("compute_consent", cid)
    assert consent["used_seconds"] == 240 and workspace.store.list("compute_notice", cid) == []


def test_the_researcher_sets_the_two_thresholds_for_the_campaign(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "tighten", "campaign.update", {"compute_notice_seconds": 0, "compute_gate_seconds": 120,
        "rationale": "An expensive problem: tell me about every run"}, actor="researcher")
    with pytest.raises(ValueError, match=r"more than 2 min \(the researcher's go-ahead threshold\)"):
        send(workspace, cid, "screen", "trial.create", run(task, 240))
    send(workspace, cid, "probe", "trial.create", run(task, 30))   # a notice threshold of zero: every run comes with a notice
    assert [row["seconds"] for row in workspace.store.list("compute_notice", cid)] == [30]
    [amendment] = workspace.store.list("campaign_budget_amendment", cid)
    assert amendment["limits"] == {"compute_notice_seconds": 0, "compute_gate_seconds": 120} and amendment["authority"] == "researcher"
    with pytest.raises(ValueError, match="at most the go-ahead threshold"):
        send(workspace, cid, "inverted", "campaign.update", {"compute_notice_seconds": 600, "rationale": "Inverted"}, actor="researcher")
    with pytest.raises(ValueError):   # an agent asks for a change with approval.request; it cannot make one
        send(workspace, cid, "loosen", "campaign.update", {"compute_gate_seconds": 3600, "rationale": "Fewer interruptions"})
    assert workspace.store.get(cid, "campaign")["compute_gate_seconds"] == 120


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


def proposal(workspace, campaign_id, identity):
    return workspace.store.put("hypothesis", {"id": identity, "campaign_id": campaign_id, "title": identity, "status": "proposed",
                                              "mechanism": "A coordinate search", "algorithm": "coordinate", "algorithm_config": {}})


def approve(workspace, campaign_id, identity, request, origin=None):
    campaign = workspace.store.get(campaign_id, "campaign")
    workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"], operation="approval.request",
        expected_guidance_revision=workspace.memory.state(campaign_id)["guidance_revision"],
        expected_authority_hash=workspace.commands.authority_hash(campaign), origin=origin,
        payload={"kind": "compute", "rationale": "Screen the proposals", "meanwhile": "Read the charter", **request}), actor="manager")
    decision = workspace.store.get("approval_" + identity, "decision")
    send(workspace, campaign_id, "approve_" + identity, "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "",
         "expected_resolution_revision": 0}, actor="researcher")
    return workspace.store.get(workspace.store.get(decision["id"], "decision")["outcome"]["consent_id"], "compute_consent")


def test_a_plan_for_some_proposals_covers_only_their_work_and_the_refusal_says_which_plan_does(lab):
    from optimization_framework.campaigns import compute_consent
    workspace, campaign, task = lab
    cid = campaign["id"]
    for identity in ("H1", "H2", "H3", "H4", "H5"):
        proposal(workspace, cid, identity)
    with pytest.raises(ValueError, match="No proposal H9"):
        approve(workspace, cid, "unknown", {"plan": "Screen H9", "wall_seconds": 600, "worker_seconds": 600, "hypothesis_ids": ["H9"]})
    consent = approve(workspace, cid, "four", {"plan": "Screen H1 to H4", "wall_seconds": 600, "worker_seconds": 4800,
        "hypothesis_ids": ["H1", "H2", "H3"], "runs": [{"task_id": task["id"], "hypothesis_id": "H4", "seeds": [0], "wall_seconds": 600}]})
    assert consent["hypothesis_ids"] == ["H1", "H2", "H3", "H4"] and consent["runs"][0]["hypothesis_id"] == "H4"
    assert consent["workspace_ids"] == [] and consent["launched"] == []
    decision = workspace.store.get(consent["decision_id"], "decision")
    assert decision["approval_request"]["hypothesis_ids"] == ["H1", "H2", "H3"] and "covers only the work for H1, H2, H3, H4" in decision["proposal"]

    with pytest.raises(ValueError, match="No approved plan covers work for H5") as refused:
        send(workspace, cid, "run_h5", "trial.create", {**run(task, 590), "hypothesis_id": "H5"})
    assert '"Screen H1 to H4" (for H1, H2, H3, H4)' in str(refused.value)
    with pytest.raises(ValueError, match="No approved plan covers this work"):   # work for no proposal, from no request of the plan
        send(workspace, cid, "unnamed", "trial.create", run(task, 590))
    assert compute_consent.require(workspace, cid, "A run", 590, hypothesis_ids=["H2"])["id"] == consent["id"]
    assert compute_consent.require(workspace, cid, "A run", 590, hypothesis_ids=["H1", "H4"])["id"] == consent["id"]
    receipt = send(workspace, cid, "run_h1", "trial.create", {**run(task, 590), "hypothesis_id": "H1"})
    assert workspace.store.get(consent["id"], "compute_consent")["launched"] == [receipt["outcome"]["trial_id"]]
    with pytest.raises(ValueError, match="No approved plan covers work for H1, H5"):
        compute_consent.require(workspace, cid, "A coding workspace", 590, hypothesis_ids=["H1", "H5"])
    # A second plan, for H5, covers it; the refusal of work no plan covers names both.
    second = approve(workspace, cid, "fifth", {"plan": "Screen H5", "wall_seconds": 600, "worker_seconds": 600, "hypothesis_ids": ["H5"]})
    assert compute_consent.require(workspace, cid, "A run", 590, hypothesis_ids=["H5"])["id"] == second["id"]
    with pytest.raises(ValueError, match="Approved and unused: 10 min of worker time and 0 coding workspaces for \"Screen H5\" \\(for H5\\)"):
        compute_consent.require(workspace, cid, "A run", 1200, hypothesis_ids=["H5"])


def test_work_for_no_proposal_is_covered_by_a_plan_of_the_same_request(lab):
    from optimization_framework.contracts.commands import CommandOrigin
    workspace, campaign, task = lab
    cid = campaign["id"]
    proposal(workspace, cid, "H1")
    workspace.store.put("agent_session", {"id": "agent_lead", "campaign_id": cid, "role": "lead"})
    for identity, message in (("run_asked", "message_ask"), ("run_other", "message_other")):
        workspace.store.put("agent_run", {"id": identity, "campaign_id": cid, "agent_id": "agent_lead", "status": "running",
                                          "origin": {"thread_id": "thread_main", "message_id": message, "actor": "researcher"}})
    asked = CommandOrigin(thread_id="thread_main", message_id="message_ask", actor="lead", agent_id="agent_lead", run_id="run_asked")
    consent = approve(workspace, cid, "profile_plan", {"plan": "Profile, then screen H1", "wall_seconds": 3000, "worker_seconds": 6000,
                                                       "hypothesis_ids": ["H1"]}, origin=asked)
    assert consent["request_root"] == {"thread_id": "thread_main", "message_id": "message_ask", "run_id": "run_asked"}

    def profile(identity, origin):
        campaign_now = workspace.store.get(cid, "campaign")
        return workspace.commands.execute(Command(id=identity, campaign_id=cid, expected_revision=campaign_now["version"], operation="runtime.profile",
            expected_guidance_revision=workspace.memory.state(cid)["guidance_revision"], expected_authority_hash=workspace.commands.authority_hash(campaign_now),
            origin=origin, payload={"task_id": task["id"], "probe_seconds": 300}), actor="manager")

    with pytest.raises(ValueError, match="No approved plan covers this work"):   # another request of the researcher's
        profile("profile_other", CommandOrigin(thread_id="thread_main", message_id="message_other", actor="lead", agent_id="agent_lead", run_id="run_other"))
    # A notice turn continuing the asked request has the same root, and so does an assistant the lead gave it to.
    workspace.store.put("agent_run", {"id": "run_notice", "campaign_id": cid, "agent_id": "agent_lead", "status": "running",
        "origin": {"thread_id": "thread_main", "actor": "lab", "root": consent["request_root"]}})
    workspace.store.put("agent_session", {"id": "agent_helper", "campaign_id": cid, "role": "analyst", "assignment_origin": consent["request_root"]})
    workspace.store.put("agent_run", {"id": "run_helper", "campaign_id": cid, "agent_id": "agent_helper", "status": "running", "origin": {}})
    from optimization_framework.campaigns import compute_consent
    for run_id in ("run_notice", "run_helper"):
        root = compute_consent.request_root(workspace, {"run_id": run_id})
        assert compute_consent.require(workspace, cid, "A runtime profile", 600, root=root)["id"] == consent["id"]
    profile("profile_asked", asked)
    assert workspace.store.get(consent["id"], "compute_consent")["used_seconds"] > 0


def test_a_consent_recorded_before_plans_named_proposals_covers_the_whole_campaign(lab):
    from optimization_framework.campaigns import compute_consent
    from datetime import datetime, timedelta, timezone
    workspace, campaign, task = lab
    cid = campaign["id"]
    proposal(workspace, cid, "H5")
    workspace.store.put("compute_consent", {"id": "compute_consent_old", "campaign_id": cid, "decision_id": "decision_old", "plan": "Old plan",
        "worker_seconds": 1200, "wall_seconds": 600, "coding_workspaces": 1, "used_seconds": 0.0, "used_workspaces": 0, "granted_at": "2026-10-20T00:00:00+00:00",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    for names, root in (([], None), (["H5"], None), ([], {"thread_id": "t", "message_id": "m", "run_id": "r"})):
        assert compute_consent.require(workspace, cid, "Work", 590, coding=1, hypothesis_ids=names, root=root)["id"] == "compute_consent_old"
    send(workspace, cid, "old_run", "trial.create", {**run(task, 590)})
    consent = workspace.store.get("compute_consent_old", "compute_consent")
    assert consent["used_seconds"] == 590 and consent["launched"] == [workspace.store.get("old_run", "work_command")["outcome"]["trial_id"]]


def test_charge_records_the_coding_workspaces_and_the_runs_it_paid_for(lab):
    from optimization_framework.campaigns import compute_consent
    workspace, campaign, task = lab
    cid = campaign["id"]
    proposal(workspace, cid, "H1")
    consent = approve(workspace, cid, "build", {"plan": "Build and screen H1", "wall_seconds": 600, "worker_seconds": 2400,
                                                "coding_workspaces": 1, "hypothesis_ids": ["H1"]})
    compute_consent.charge(workspace, cid, coding=1, what="a coding workspace", subjects=["development_h1"], hypothesis_ids=["H1"])
    compute_consent.charge(workspace, cid, 590, what="a run", subjects=["trial_a"], hypothesis_ids=["H1"], trial_ids=["trial_a"])
    compute_consent.charge(workspace, cid, 590, what="a run", subjects=["trial_b"], hypothesis_ids=["H1"], trial_ids=["trial_b", "trial_a"])
    saved = workspace.store.get(consent["id"], "compute_consent")
    assert saved["workspace_ids"] == ["development_h1"] and saved["launched"] == ["trial_a", "trial_b"]
    assert saved["used_workspaces"] == 1 and saved["used_seconds"] == 1180


def test_a_consent_stays_in_force_while_its_workspace_builds_and_for_three_wall_times_after(lab):
    from optimization_framework.campaigns import compute_consent
    from datetime import datetime, timedelta, timezone
    workspace, campaign, task = lab
    cid = campaign["id"]
    proposal(workspace, cid, "H1")
    consent = approve(workspace, cid, "build", {"plan": "Build H1", "wall_seconds": 600, "worker_seconds": 2400, "coding_workspaces": 1,
                                                "hypothesis_ids": ["H1"]})
    current = datetime.now(timezone.utc)
    workspace.store.put("development_workspace", {"id": "development_h1", "campaign_id": cid, "hypothesis_id": "H1", "desired_status": "running",
                                                  "created_at": (current - timedelta(hours=5)).isoformat()})
    compute_consent.charge(workspace, cid, coding=1, what="a coding workspace", subjects=["development_h1"], hypothesis_ids=["H1"])
    saved = workspace.store.get(consent["id"], "compute_consent")
    saved["expires_at"] = (current - timedelta(hours=1)).isoformat()   # past the old expiry, max(1 h, 3 x wall)
    workspace.store.put("compute_consent", saved)
    assert [row["id"] for row in compute_consent.consents(workspace, cid)] == [consent["id"]]   # still building
    assert compute_consent.require(workspace, cid, "A run", 590, hypothesis_ids=["H1"])["id"] == consent["id"]
    stopped = workspace.store.get("development_h1", "development_workspace")
    stopped.update(desired_status="stopped", control_requested_at=(current - timedelta(minutes=20)).isoformat())
    workspace.store.put("development_workspace", stopped)
    assert compute_consent.consents(workspace, cid) != []   # 20 min after it stopped, within 3 x 10 min
    stopped["control_requested_at"] = (current - timedelta(minutes=31)).isoformat()
    workspace.store.put("development_workspace", stopped)
    assert compute_consent.consents(workspace, cid) == []
    with pytest.raises(ValueError, match="No approved plan has time left"):
        compute_consent.require(workspace, cid, "A run", 590, hypothesis_ids=["H1"])


def test_the_hosts_a_coding_workspace_reaches_beyond_its_model_and_index_are_approved_with_the_plan(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    ask = {"kind": "compute", "plan": "A coding workspace for H13", "rationale": "Build H13", "wall_seconds": 3600,
           "worker_seconds": 600, "coding_workspaces": 1, "meanwhile": "Read the results", "egress_hosts": ["github.com"]}
    with pytest.raises(ValueError, match="egress_hosts are for the coding workspaces"):
        send(workspace, cid, "ask_none", "approval.request", {**ask, "coding_workspaces": 0})
    with pytest.raises(ValueError, match="lowercase DNS name"):
        send(workspace, cid, "ask_url", "approval.request", {**ask, "egress_hosts": ["https://github.com/x"]})
    send(workspace, cid, "ask", "approval.request", ask)
    decision = workspace.store.list("decision", cid)[-1]
    assert "Its coding workspaces may also reach github.com, beyond their model and the package index." in decision["proposal"]
    send(workspace, cid, "approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "",
        "expected_resolution_revision": 0}, actor="researcher")
    [consent] = workspace.store.list("compute_consent", cid)
    assert consent["egress_hosts"] == ["github.com"] and consent["used_wall_seconds"] == 0
