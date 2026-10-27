"""After an install that provides the problem its campaign's charter declares, Balsamic has the declared tasks adopt it by
itself (roadmap E5): first in the post-install step, through the bus as its system actor citing the install, only when no such
task has a bound evaluator or live runs. Otherwise it is skipped with the reason and the lead is told to use
campaign.adopt_problem. The install record lists what was adopted or why not; replaying the install adopts nothing more."""
import pytest

from optimization_framework.agents.library_install import adopt_provided, adoption_text, after_install
from optimization_framework.contracts.commands import Command, CommandOrigin
from optimization_framework.contracts.requests import CampaignUpdate
from test_library_install import deliver, installer, lab, request as install  # noqa: F401  (lab is a fixture)
from test_problem_adoption import declared, library_install, provided  # noqa: F401  (fixtures)
from test_mandates import granted


def submission(workspace, cid):
    return workspace.store.put("development_submission", {"id": "submission_reactor", "campaign_id": cid,
        "workspace_id": "development_reactor", "hypothesis_id": "hypothesis_none", "commit": "abc1234def", "report": {"methods": []}})


def live_run(workspace, task, status="running"):
    return workspace.store.put("trial", {"id": "trial_live", "campaign_id": task["campaign_id"], "task_id": task["id"], "status": status})


def test_an_install_adopts_a_task_with_no_evaluator_and_no_live_runs(declared, provided):
    workspace, cid = declared
    old, = workspace.current_tasks(cid)
    submission(workspace, cid)
    install = library_install(workspace, cid)
    done = after_install(workspace, install)
    new, = workspace.current_tasks(cid)
    assert done["adopted"] == [{"old_task_id": old["id"], "new_task_id": new["id"]}] and done["adoption_skipped"] is None
    assert new["provided_by"]["install_id"] == install["id"] and not new.get("evaluator_manifest")
    # Through the bus, as Balsamic's system actor citing the install.
    receipt, = [row for row in workspace.store.list("work_command", cid) if row["request"]["operation"] == "campaign.adopt_problem"]
    assert receipt["actor"] == "balsamic" and receipt["origin"]["actor"] == "balsamic" and install["id"] in receipt["origin"]["rationale"]
    assert workspace.store.list("evaluator_requirement_satisfaction", cid)[0]["authority"] == "balsamic"
    assert adoption_text({**install, **done}) == "Balsamic had 1 task adopt its problem."
    # Replaying the install adopts nothing more.
    version = workspace.store.get(cid, "campaign")["version"]
    assert adopt_provided(workspace, install) == {"adopted": [], "adoption_skipped": None}
    assert workspace.store.get(cid, "campaign")["version"] == version and [t["id"] for t in workspace.current_tasks(cid)] == [new["id"]]


@pytest.mark.parametrize("status", ["queued", "running", "paused"])
def test_a_task_with_live_runs_is_not_adopted_the_lead_is_told_and_campaign_adopt_problem_then_adopts_it(declared, provided, status):
    workspace, cid = declared
    old, = workspace.current_tasks(cid)
    live_run(workspace, old, status)
    submission(workspace, cid)
    install = library_install(workspace, cid)
    done = after_install(workspace, install)
    assert done["adopted"] == []
    assert done["adoption_skipped"] == {"problem_id": "flow_reactor_yield", "reason": f"the task {old['name']} has 1 live run"}
    assert workspace.current_tasks(cid)[0]["id"] == old["id"] and workspace.store.get(cid, "campaign")["version"] == 1
    text = adoption_text({**install, **done})
    assert "did not adopt flow_reactor_yield" in text and "1 live run" in text and "campaign.adopt_problem" in text and install["id"] in text
    # The lead adopts it with the command, live runs or not.
    campaign = workspace.store.get(cid, "campaign")
    workspace.store.put("campaign", {**campaign, "autonomy": "delegated"})
    granted(workspace, cid, "screen")   # adopting is implement work: the lead's request needs a Screen mandate (R3)
    receipt = workspace.commands.execute(Command(id="lead_adopts", campaign_id=cid, expected_revision=campaign["version"],
        expected_guidance_revision=workspace.memory.state(cid)["guidance_revision"],
        expected_authority_hash=workspace.commands.authority_hash(workspace.store.get(cid, "campaign")),
        operation="campaign.adopt_problem", payload={"install_id": install["id"]}), actor="manager")
    assert receipt["outcome"]["adopted"][0]["old_task_id"] == old["id"]
    assert workspace.store.get("trial_live", "trial")["task_id"] == old["id"]   # the run goes on where it was


def test_a_task_with_a_bound_evaluator_is_not_adopted_and_balsamic_cannot_force_it(declared, provided):
    workspace, cid = declared
    old, = workspace.current_tasks(cid)
    # A commissioned evaluator bound to the declared task (as evaluator.attach records it).
    workspace.store.put("evaluator_binding", {"id": "binding_" + old["evaluator_requirement_id"], "campaign_id": cid, "task_id": old["id"],
        "problem": old["problem"], "problem_instance_id": "instance_bound", "version_id": "implementation_version_x"})
    submission(workspace, cid)
    install = library_install(workspace, cid)
    done = after_install(workspace, install)
    assert done["adopted"] == [] and done["adoption_skipped"]["reason"] == f"the task {old['name']} has a bound evaluator"
    # The system actor itself is refused, whatever calls it.
    campaign = workspace.store.get(cid, "campaign")
    with pytest.raises(ValueError, match="only for tasks nothing ran yet: the task .* has a bound evaluator"):
        workspace.commands.execute(Command(id="balsamic_forces", campaign_id=cid, expected_revision=campaign["version"],
            origin=CommandOrigin(actor="balsamic"), operation="campaign.adopt_problem", payload={"install_id": install["id"]}), actor="balsamic")
    assert workspace.current_tasks(cid)[0]["id"] == old["id"]


def test_an_install_that_provides_no_declared_problem_adopts_nothing(declared, provided):
    workspace, cid = declared
    submission(workspace, cid)
    other = library_install(workspace, cid, "library_install_other", problem_entry_points={}, problems_added=[])
    assert after_install(workspace, other)["adopted"] == [] and after_install(workspace, other)["adoption_skipped"] is None
    assert adoption_text({**other, "adopted": [], "adoption_skipped": None}) == ""


def test_the_installer_adopts_first_and_the_notice_says_so(lab, monkeypatch, request):
    """The real install path: a problem library for the campaign's declared charter is installed, then adopted."""
    from test_problem_charter import reactor
    workspace, cid, development, root, submission_record = lab
    confirmed = workspace.charters.confirm(workspace.charters.create(reactor(), source={"kind": "test"})["id"])
    workspace.update_campaign(cid, CampaignUpdate(charter=confirmed["charter"]))
    old, = workspace.current_tasks(cid)
    assert old["evaluator_manifest"]["id"] == "flow_reactor_yield"
    request.getfixturevalue("provided")   # the library's problem reaches the lab's registry once it is installed
    notices = []
    monkeypatch.setattr(development, "notify", lambda record, identity, text, kind: notices.append(text))
    deliver(lab, '[project]\nname = "reactor-lab"\nversion = "0.2.0"\n\n'
                 '[project.entry-points."optimization_framework.problems"]\nflow_reactor_yield = "reactor.problem:Problem"\n')
    record = install(lab, installer(lab, provided=["flow_reactor_yield"])[0])
    new, = workspace.current_tasks(cid)
    assert record["status"] == "installed" and record["adopted"] == [{"old_task_id": old["id"], "new_task_id": new["id"]}]
    assert new["provided_by"]["package"] == "reactor-lab" and new["provided_by"]["commit"] == record["commit"]
    assert notices[-1].endswith("problems flow_reactor_yield. Balsamic had 1 task adopt its problem.")
