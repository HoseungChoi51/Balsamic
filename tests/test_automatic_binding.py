"""After an install, Balsamic binds each proposal the delivery serves to its method by itself (roadmap B4): through the bus as
its system actor `balsamic` (decision 6), citing the install, only when exactly one of the proposal's methods is installed and
runnable; a proposal someone bound and an incompatible method are skipped with the reason, and a binding keeps the proposal's
concept review. uv is faked as in test_library_install; the delivered methods are the lab's own, so they are installed."""
import pytest

from optimization_framework.agents.library_install import bind_served
from optimization_framework.campaigns.proposals import hypothesis_revision, readiness
from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.commands import Command, CommandOrigin
from test_library_install import installer, lab  # noqa: F401  (lab is a fixture)


def proposal(workspace, cid, identity, **fields):
    return workspace.store.put("hypothesis", {"id": identity, "campaign_id": cid, "title": f"Proposal {identity}", "mechanism": "m",
        "rationale": "r", "parent_ids": [], "algorithm": "custom", "algorithm_config": {"design_note": "as proposed"},
        "algorithm_chosen": True, "status": "proposed", "executable": False, **fields})


def deliver(lab, methods):
    """The submission reports these (method, proposal) pairs."""
    workspace, cid, development, root, submission = lab
    report = {**submission["report"], "methods": [{"method_id": m, "hypothesis_id": h, "state": "implemented", "conformance": "passed"}
                                                 for m, h in methods]}
    return workspace.store.put("development_submission", {**submission, "report": report})


def install(lab, monkeypatch):
    workspace, cid, development, root, submission = lab
    notices = []
    monkeypatch.setattr(development, "notify", lambda record, key, text, read="": notices.append(text))
    done = installer(lab)[0].automatic(cid, "development_bakery", workspace.store.get(submission["id"], "development_submission"), background=False)
    return done, notices


def test_a_library_serving_two_proposals_binds_both_with_receipts_by_balsamic(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    proposal(workspace, cid, "hypothesis_dp")
    proposal(workspace, cid, "hypothesis_two")
    deliver(lab, [("coordinate", "hypothesis_dp"), ("random", "hypothesis_two")])
    done, notices = install(lab, monkeypatch)
    assert done["status"] == "installed" and done["skipped"] == []
    assert {(row["hypothesis_id"], row["method"]) for row in done["bindings"]} == {("hypothesis_dp", "coordinate"), ("hypothesis_two", "random")}
    for row in done["bindings"]:
        hypothesis = workspace.store.get(row["hypothesis_id"], "hypothesis")
        assert hypothesis["algorithm"] == row["method"] and hypothesis["builtin_binding_id"] == row["binding_id"]
        assert workspace.implementations.readiness(hypothesis)["runnable"]
        receipt = workspace.store.get(row["command_id"], "work_command")
        assert receipt["actor"] == "balsamic" and receipt["origin"]["actor"] == "balsamic" and done["id"] in receipt["origin"]["rationale"]
        binding = workspace.store.get(row["binding_id"], "builtin_binding")
        assert binding["authority"] == "balsamic" and binding["install_id"] == done["id"] and binding["previous_algorithm"] == "custom"
    # The notice names what was bound and no longer asks the lead to bind.
    assert len(notices) == 1 and "Balsamic bound hypothesis_dp to coordinate; hypothesis_two to random." in notices[0]
    assert "implementation.bind_builtin" not in notices[0]
    # Doing it again binds nothing twice.
    again = bind_served(workspace, done)
    assert again["bindings"] == [] and all("Already bound" in row["reason"] and "by Balsamic" in row["reason"] for row in again["skipped"])


def test_a_proposal_the_researcher_bound_is_untouched_and_an_incompatible_method_is_skipped_with_its_reason(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    proposal(workspace, cid, "hypothesis_dp")
    proposal(workspace, cid, "hypothesis_ppo")
    proposal(workspace, cid, "hypothesis_both")
    proposal(workspace, cid, "hypothesis_chosen", algorithm="annealing")
    task = workspace.current_tasks(cid)[0]
    campaign = workspace.store.get(cid, "campaign")
    workspace.commands.execute(Command(id="researcher_binds", campaign_id=cid, expected_revision=campaign["version"],
        operation="implementation.bind_builtin", payload={"hypothesis_id": "hypothesis_dp", "task_id": task["id"], "algorithm": "random",
        "parameters": {}, "expected_algorithm": "custom", "expected_configuration_hash": content_hash({"design_note": "as proposed"}),
        "reason": "The researcher picks random"}))
    deliver(lab, [("coordinate", "hypothesis_dp"), ("flrl_ppo", "hypothesis_ppo"), ("coordinate", "hypothesis_both"),
                  ("random", "hypothesis_both"), ("coordinate", "hypothesis_chosen")])
    done, notices = install(lab, monkeypatch)
    assert done["bindings"] == []
    reasons = {row["hypothesis_id"]: row["reason"] for row in done["skipped"]}
    assert reasons["hypothesis_dp"] == "Already bound to random by the researcher"
    assert "runs only on meent_2d_dual_polarization_deflector" in reasons["hypothesis_ppo"]
    assert reasons["hypothesis_both"].startswith("Several methods could serve it (coordinate, random)")
    assert reasons["hypothesis_chosen"] == "It uses annealing, another method"
    assert workspace.store.get("hypothesis_dp", "hypothesis")["algorithm"] == "random"
    assert all(workspace.store.get(h, "hypothesis")["algorithm"] == a for h, a in
               [("hypothesis_ppo", "custom"), ("hypothesis_both", "custom"), ("hypothesis_chosen", "annealing")])
    assert "Balsamic bound no proposal. Not bound: " in notices[0] and "hypothesis_ppo (" in notices[0]


def test_a_review_recorded_before_the_binding_stays_valid_after_it(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    hypothesis = proposal(workspace, cid, "hypothesis_dp", requires_concept_review=True)
    revision = hypothesis_revision(hypothesis)
    workspace.store.put("agent_artifact", {"id": "review_dp", "campaign_id": cid, "kind": "proposal_review", "agent_id": "reviewer",
        "created_at": "2026-10-27T03:00:00+00:00", "content": {"hypothesis_id": "hypothesis_dp", "hypothesis_hash": revision, "verdict": "test"}})
    assert readiness(workspace.store, hypothesis)["state"] == "testable"
    deliver(lab, [("coordinate", "hypothesis_dp")])
    done, _ = install(lab, monkeypatch)
    bound = workspace.store.get("hypothesis_dp", "hypothesis")
    assert done["bindings"][0]["method"] == "coordinate" and bound["algorithm_config"] == {}
    assert bound["pre_binding_config"] == {"design_note": "as proposed"} and hypothesis_revision(bound) == revision
    assert readiness(workspace.store, bound) == {"state": "testable", "eligible": True, "review_ids": ["review_dp"],
                                                 "reason": "Independently judged plausible enough for quick tests; effectiveness remains unmeasured."}
    # A change to what was proposed is still a new revision.
    assert hypothesis_revision({**bound, "mechanism": "other"}) != revision


@pytest.mark.parametrize("operation,payload", [
    ("trial.create", {"hypothesis_id": "hypothesis_dp", "task_id": "x", "wall_seconds": 10}),
    ("hypothesis.status", {"hypothesis_id": "hypothesis_dp", "status": "archived"}),
    ("campaign.update", {}),
    ("approval.request", {}),
])
def test_balsamic_runs_no_other_operation(lab, operation, payload):
    workspace, cid = lab[0], lab[1]
    proposal(workspace, cid, "hypothesis_dp")
    campaign = workspace.store.get(cid, "campaign")
    command = Command(id="balsamic_" + operation.replace(".", "_"), campaign_id=cid, expected_revision=campaign["version"],
                      operation=operation, origin=CommandOrigin(actor="balsamic"), payload=payload)
    with pytest.raises(ValueError, match="Balsamic's system actor runs only implementation.bind_builtin"):
        workspace.commands.execute(command, actor="balsamic")
    assert workspace.store.list("command_rejection")[-1]["actor"] == "balsamic"


def test_balsamic_binds_only_what_an_install_it_cites_delivered(lab, monkeypatch):
    workspace, cid = lab[0], lab[1]
    proposal(workspace, cid, "hypothesis_dp")
    proposal(workspace, cid, "hypothesis_other")
    deliver(lab, [("bakery_dp", "hypothesis_dp")])   # not a method of the lab: nothing to bind
    done, _ = install(lab, monkeypatch)
    assert done["bindings"] == [] and done["skipped"] == [{"hypothesis_id": "hypothesis_dp", "reason": "bakery_dp is not installed"}]
    task, campaign = workspace.current_tasks(cid)[0], workspace.store.get(cid, "campaign")
    base = {"task_id": task["id"], "algorithm": "random", "parameters": {}, "expected_algorithm": "custom",
            "expected_configuration_hash": content_hash({"design_note": "as proposed"}), "reason": "r"}
    cases = [("no_origin", None, {**base, "hypothesis_id": "hypothesis_dp", "install_id": done["id"]}, "names it as its origin"),
             ("no_install", CommandOrigin(actor="balsamic"), {**base, "hypothesis_id": "hypothesis_dp"}, "cites the library install"),
             ("not_delivered", CommandOrigin(actor="balsamic"), {**base, "hypothesis_id": "hypothesis_dp", "install_id": done["id"]}, "does not deliver random"),
             ("not_served", CommandOrigin(actor="balsamic"), {**base, "hypothesis_id": "hypothesis_other", "install_id": done["id"]}, "does not deliver")]
    for key, origin, payload, message in cases:
        with pytest.raises(ValueError, match=message):
            workspace.commands.execute(Command(id="forged_" + key, campaign_id=cid, expected_revision=campaign["version"],
                operation="implementation.bind_builtin", origin=origin, payload=payload), actor="balsamic")
    assert workspace.store.list("builtin_binding") == []
