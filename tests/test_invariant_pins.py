"""Guarantees of docs/invariants.md that code held but no test pinned: each test here is named by a `code` row."""
from pathlib import Path

import pytest

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Pins", autonomy="delegated", compute_budget_seconds=20000,
        validation_reserve_seconds=0, delegated_trial_seconds=1500, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    return workspace, campaign, workspace.current_tasks(campaign["id"])[0]


def send(workspace, campaign_id, identity, operation, payload, actor="manager"):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, **pins), actor=actor)


def run(task, hypothesis_id=None):
    return {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": 30,
            **({"hypothesis_id": hypothesis_id} if hypothesis_id else {})}


def test_an_agents_own_proposal_does_not_run_before_an_independent_concept_review(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "own", "hypothesis.create", {"title": "The agent's idea", "mechanism": "One step", "rationale": "r"})
    own = workspace.store.get("hypothesis_own", "hypothesis")
    assert own["requires_concept_review"] is True
    with pytest.raises(ValueError, match="independent conceptual review is required"):
        send(workspace, cid, "own_run", "trial.create", run(task, own["id"]))
    with pytest.raises(ValueError, match="independent conceptual review is required"):   # the researcher's go does not skip it either
        send(workspace, cid, "own_run_by_researcher", "trial.create", run(task, own["id"]), actor="researcher")
    send(workspace, cid, "asked", "hypothesis.create", {"title": "The researcher's idea", "mechanism": "m", "rationale": "r"}, actor="researcher")
    assert not workspace.store.get("hypothesis_asked", "hypothesis").get("requires_concept_review")
    send(workspace, cid, "asked_run", "trial.create", run(task, "hypothesis_asked"))


def test_only_the_researcher_endorses_a_finding_and_a_finding_cites_only_visible_evidence(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "probe", "trial.create", run(task))
    [trial] = workspace.store.list("trial", cid)
    finding = {"content": "Coordinate search reached its best design early.", "source_ids": [trial["id"]]}
    with pytest.raises(ValueError, match="Only the researcher can endorse"):
        send(workspace, cid, "endorsed", "finding.record", {**finding, "interpretation": "researcher_endorsed"})
    with pytest.raises(ValueError, match="outside the visible context"):
        send(workspace, cid, "unseen", "finding.record", {**finding, "source_ids": [trial["id"], "trial_of_another_campaign"]})
    send(workspace, cid, "observed", "finding.record", {**finding, "interpretation": "observation"})
    send(workspace, cid, "endorsed_by_researcher", "finding.record", {**finding, "interpretation": "researcher_endorsed"}, actor="researcher")
    assert {row["author"] for row in workspace.store.list("manager_note", cid) if row.get("kind") == "finding"} == {"manager", "researcher"}


def test_the_coding_box_rejects_private_networks_and_drops_its_capabilities_before_the_agent_starts():
    folder = ROOT / "deploy" / "implementation-workspace"
    assert 'ENTRYPOINT ["bash", "/opt/workspace/network.sh"]' in (folder / "Dockerfile").read_text()
    script = (folder / "network.sh").read_text()
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        assert network in script
    assert 'iptables -A OUTPUT -d "$network" -j REJECT' in script and "ip6tables -A OUTPUT -j REJECT" in script
    *_, last = [line for line in script.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert "start.sh" in last
    assert "exec setpriv" in script and "--bounding-set=-all" in script and "--ambient-caps=-all" in script
