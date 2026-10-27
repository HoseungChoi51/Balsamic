"""Approved runs start by themselves (roadmap B5): once a planned run's proposal can run, Balsamic's system actor starts one trial
per planned seed under the consent that approved it, never a run the plan does not list and never one twice; the lead is told
when the consent's worker time stops the launching, and woken once when every planned run has ended. The installs are faked as
in test_library_install; the delivered methods are the lab's own, so they are installed."""
import pytest

from optimization_framework.campaigns.compute_consent import grant
from optimization_framework.campaigns.plan_runs import command_id, launch_ready
from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.commands import Command, CommandOrigin
from test_automatic_binding import deliver, install, proposal
from test_library_install import installer, lab  # noqa: F401  (lab is a fixture)

ROOT = {"thread_id": "thread_ask", "message_id": "message_ask", "run_id": "agent_run_ask"}
PROPOSALS = ["hypothesis_a", "hypothesis_b", "hypothesis_c", "hypothesis_d"]


def approve(lab, *, worker_seconds=80.0, hypotheses=PROPOSALS, seeds=(0, 1), wall=10.0):
    """The researcher's go-ahead for a plan of one run per proposal, with these seeds."""
    workspace, cid = lab[0], lab[1]
    task = workspace.current_tasks(cid)[0]
    runs = [{"task_id": task["id"], "hypothesis_id": h, "seeds": list(seeds), "wall_seconds": wall} for h in hypotheses]
    return grant(workspace, {"id": "decision_plan", "campaign_id": cid, "request_root": ROOT},
                 {"plan": "Implement and compare four orders", "worker_seconds": worker_seconds, "wall_seconds": 60, "runs": runs})


def setup(lab, monkeypatch, **plan):
    workspace, cid = lab[0], lab[1]
    for identity in PROPOSALS:
        proposal(workspace, cid, identity)
    notices = []
    monkeypatch.setattr(workspace.pi, "configuration", lambda campaign_id: {"enabled": True, "lead_id": "agent_lead"})
    workspace.store.put("agent_session", {"id": "agent_lead", "campaign_id": cid, "role": "lead", "status": "idle"})
    monkeypatch.setattr(workspace.pi, "enqueue", lambda agent, identity, text, root=None, **_: notices.append((agent["id"], identity, text, root)))
    return approve(lab, **plan), notices


def second_install(lab, monkeypatch, methods):
    """The same library delivered again for the other proposals, and installed."""
    workspace, cid, development, root, submission = lab
    report = {**submission["report"], "methods": [{"method_id": m, "hypothesis_id": h, "state": "implemented", "conformance": "passed"}
                                                 for m, h in methods]}
    later = workspace.store.put("development_submission", {**submission, "id": "development_submission_2", "report": report,
                                                           "created_at": "2026-10-27T04:00:00+00:00"})
    monkeypatch.setattr(development, "notify", lambda *args, **kwargs: None)
    return installer(lab)[0].automatic(cid, "development_bakery", later, background=False)


def trials(workspace, cid):
    return sorted(((t["hypothesis_id"], t["seed"]) for t in workspace.store.list("trial", cid)))


def test_a_plan_of_four_runs_starts_exactly_the_runs_of_the_bound_proposals_then_the_others_after_their_install(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    consent, _ = setup(lab, monkeypatch)
    assert launch_ready(workspace, cid)["launched"] == []   # nothing is bound yet
    deliver(lab, [("coordinate", "hypothesis_a"), ("random", "hypothesis_b")])
    done, notices = install(lab, monkeypatch)
    assert {row["hypothesis_id"] for row in done["bindings"]} == {"hypothesis_a", "hypothesis_b"}
    assert trials(workspace, cid) == [("hypothesis_a", 0), ("hypothesis_a", 1), ("hypothesis_b", 0), ("hypothesis_b", 1)]
    assert len(done["launched"]) == 4 and "Balsamic started 4 approved runs" in notices[0]
    for row in done["launched"]:
        receipt = workspace.store.get(row["command_id"], "work_command")
        assert receipt["actor"] == "balsamic" and receipt["origin"]["consent_id"] == consent["id"]
        assert receipt["origin"]["thread_id"] == "thread_ask" and receipt["origin"]["message_id"] == "message_ask"
        trial = workspace.store.get(row["trial_id"], "trial")
        assert trial["wall_seconds"] == 10 and trial["algorithm"] == workspace.store.get(row["hypothesis_id"], "hypothesis")["algorithm"]
    charged = workspace.store.get(consent["id"], "compute_consent")
    assert charged["used_seconds"] == 40 and set(charged["launched"]) == {row["trial_id"] for row in done["launched"]}
    # Another sync starts none, and a replay of a launch is the same receipt.
    assert launch_ready(workspace, cid)["launched"] == [] and len(workspace.store.list("trial", cid)) == 4
    # The other four start once their library is installed.
    later = second_install(lab, monkeypatch, [("coordinate", "hypothesis_c"), ("random", "hypothesis_d")])
    assert len(later["bindings"]) == 2 and len(later["launched"]) == 4
    assert trials(workspace, cid) == sorted((h, s) for h in PROPOSALS for s in (0, 1))
    assert workspace.store.get(consent["id"], "compute_consent")["used_seconds"] == 80
    assert launch_ready(workspace, cid)["launched"] == []


def test_an_unbound_proposal_never_starts_and_a_run_outside_the_plan_is_never_created(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    consent, _ = setup(lab, monkeypatch)
    proposal(workspace, cid, "hypothesis_e", algorithm="random")   # runnable, but not in the plan
    deliver(lab, [("coordinate", "hypothesis_a")])
    install(lab, monkeypatch)
    assert trials(workspace, cid) == [("hypothesis_a", 0), ("hypothesis_a", 1)]
    waiting = launch_ready(workspace, cid)["waiting"]
    assert {row["hypothesis_id"] for row in waiting} == {"hypothesis_b", "hypothesis_c", "hypothesis_d"}
    task, campaign = workspace.current_tasks(cid)[0], workspace.store.get(cid, "campaign")
    base = {"task_id": task["id"], "algorithm": "coordinate", "wall_seconds": 10}
    forged = [("unplanned_proposal", consent["id"], {**base, "hypothesis_id": "hypothesis_e", "algorithm": "random"}, 0, "lists no such run"),
              ("unplanned_seed", consent["id"], {**base, "hypothesis_id": "hypothesis_a", "seed": 7}, 0, "lists no such run"),
              ("longer", consent["id"], {**base, "hypothesis_id": "hypothesis_a", "seed": 1, "wall_seconds": 30}, 1, "lists no such run"),
              ("again", consent["id"], {**base, "hypothesis_id": "hypothesis_a", "seed": 1}, 1, "Command identity already belongs"),
              ("no_consent", None, {**base, "hypothesis_id": "hypothesis_a", "seed": 1}, 1, "under a compute go-ahead in force")]
    for key, consent_id, payload, seed, message in forged:
        with pytest.raises(ValueError, match=message):
            workspace.commands.execute(Command(id=command_id(consent["id"], 0, seed) if key == "again" else "forged_" + key,
                campaign_id=cid, expected_revision=campaign["version"], operation="trial.create", payload=payload,
                origin=CommandOrigin(actor="balsamic", consent_id=consent_id)), actor="balsamic")
    assert trials(workspace, cid) == [("hypothesis_a", 0), ("hypothesis_a", 1)]


def test_a_seed_someone_already_ran_since_the_go_ahead_is_not_run_again_and_the_lead_cannot_repeat_balsamic(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    setup(lab, monkeypatch, hypotheses=["hypothesis_a"])
    task, campaign = workspace.current_tasks(cid)[0], workspace.store.get(cid, "campaign")
    workspace.commands.execute(Command(id="researcher_binds", campaign_id=cid, expected_revision=campaign["version"],
        operation="implementation.bind_builtin", payload={"hypothesis_id": "hypothesis_a", "task_id": task["id"], "algorithm": "random",
        "parameters": {}, "expected_algorithm": "custom", "expected_configuration_hash": content_hash({"design_note": "as proposed"}),
        "reason": "The researcher picks random"}))
    campaign = workspace.store.get(cid, "campaign")
    workspace.commands.execute(Command(id="researcher_runs", campaign_id=cid, expected_revision=campaign["version"], operation="trial.create",
        payload={"task_id": task["id"], "hypothesis_id": "hypothesis_a", "algorithm": "random", "seed": 0, "wall_seconds": 10}))
    consent = workspace.store.list("compute_consent", cid)[0]
    campaign = workspace.store.get(cid, "campaign")
    with pytest.raises(ValueError, match="already ran since the go-ahead"):
        workspace.commands.execute(Command(id=command_id(consent["id"], 0, 0), campaign_id=cid, expected_revision=campaign["version"],
            operation="trial.create", payload={"task_id": task["id"], "hypothesis_id": "hypothesis_a", "algorithm": "random", "seed": 0,
            "wall_seconds": 10}, origin=CommandOrigin(actor="balsamic", consent_id=consent["id"])), actor="balsamic")
    launched = launch_ready(workspace, cid)["launched"]
    assert [(row["hypothesis_id"], row["seed"]) for row in launched] == [("hypothesis_a", 1)]
    assert trials(workspace, cid) == [("hypothesis_a", 0), ("hypothesis_a", 1)]
    # An agent's run of the same seed would repeat Balsamic's.
    campaign = workspace.store.get(cid, "campaign")
    agent = Command(id="lead_repeats", campaign_id=cid, expected_revision=campaign["version"], operation="trial.create",
                    payload={"task_id": task["id"], "hypothesis_id": "hypothesis_a", "algorithm": "random", "seed": 1, "wall_seconds": 10})
    with pytest.raises(ValueError, match="Balsamic already started this approved run"):
        for guard in workspace.commands.guards:
            guard(agent, "manager", campaign)


def test_a_superseded_planned_task_runs_on_its_successor(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    setup(lab, monkeypatch, hypotheses=["hypothesis_a"], seeds=(0,))
    old = workspace.current_tasks(cid)[0]
    raw = workspace.store.get(old["id"], "task")
    workspace.store.put("task", {**raw, "id": raw["id"] + "_v2"})
    workspace.store.put("task", {**raw, "archived": True, "superseded_by_task_id": raw["id"] + "_v2"})
    deliver(lab, [("coordinate", "hypothesis_a")])
    done, _ = install(lab, monkeypatch)
    assert [row["task_id"] for row in done["launched"]] == [raw["id"] + "_v2"]
    assert launch_ready(workspace, cid)["launched"] == []


def test_when_the_worker_time_is_spent_launching_stops_and_the_lead_is_told_once(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    consent, notices = setup(lab, monkeypatch, worker_seconds=30.0)
    deliver(lab, [("coordinate", "hypothesis_a"), ("random", "hypothesis_b")])
    done, _ = install(lab, monkeypatch)
    assert len(done["launched"]) == 3 and len(workspace.store.list("trial", cid)) == 3
    launch_ready(workspace, cid)
    spent = [row for row in notices if "no worker time left" in row[2]]
    assert len(spent) == 1 and spent[0][0] == "agent_lead" and spent[0][3] == ROOT
    assert "started 3 of its 8 approved runs" in spent[0][2]
    assert len(workspace.store.list("trial", cid)) == 3


def test_when_all_planned_runs_end_the_lead_gets_exactly_one_notice(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    _, notices = setup(lab, monkeypatch, hypotheses=["hypothesis_a", "hypothesis_b"])
    deliver(lab, [("coordinate", "hypothesis_a"), ("random", "hypothesis_b")])
    install(lab, monkeypatch)
    started = workspace.store.list("trial", cid)
    for trial in started[:3]:
        workspace.store.put("trial", {**workspace.store.get(trial["id"], "trial"), "status": "completed"})
    launch_ready(workspace, cid)
    finished = lambda: [row for row in notices if "approved runs of the go-ahead" in row[2]]
    assert finished() == []
    workspace.store.put("trial", {**workspace.store.get(started[3]["id"], "trial"), "status": "stopped"})
    launch_ready(workspace, cid)
    launch_ready(workspace, cid)
    assert len(finished()) == 1 and finished()[0][3] == ROOT and "Write the comparison (comparison.report)" in finished()[0][2]
    assert "All 4 approved runs" in finished()[0][2]
