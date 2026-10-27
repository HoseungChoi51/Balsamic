"""Findings say what they state (a promise, evidence or a decision) and link earlier findings by type (roadmap K3)."""
import pytest

from optimization_framework.campaigns.findings import view
from optimization_framework.reports.evidence import freeze
from test_invariant_pins import lab, run, send  # noqa: F401  (the fixture and the command helper)


@pytest.fixture
def campaign(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "probe", "trial.create", run(task))
    [trial] = workspace.store.list("trial", cid)
    send(workspace, cid, "idea", "hypothesis.create", {"title": "Restarts", "mechanism": "Restart when stalled", "rationale": "Escapes plateaus"})
    review = workspace.store.put_immutable("agent_artifact", {"id": "artifact_review", "campaign_id": cid, "agent_id": "agent_reviewer",
        "run_id": "run_review", "kind": "proposal_review", "content": {"verdict": "test", "rationale": "Plausible."}})
    decision = workspace.store.put("decision", {"id": "decision_go", "campaign_id": cid, "title": "Run restarts", "status": "approved"})
    return workspace, cid, trial["id"], "hypothesis_idea", review["id"], decision["id"]


def record(workspace, cid, identity, statement, sources, actor="manager", **extra):
    payload = {"content": f"Finding {identity}.", "source_ids": sources, **({"statement": statement} if statement else {}), **extra}
    return send(workspace, cid, identity, "finding.record", payload, actor=actor)["outcome"]["finding_id"]


def note(workspace, finding_id):
    return workspace.store.get(finding_id, "manager_note")


def test_an_agents_evidence_finding_needs_a_measurement_and_a_rationale_is_a_promise(campaign):
    workspace, cid, trial, proposal, review, _ = campaign
    with pytest.raises(ValueError, match="evidence finding cites at least one measurement.*record what they argue as a promise"):
        record(workspace, cid, "claimed", "evidence", [proposal, review])
    assert note(workspace, record(workspace, cid, "measured", "evidence", [trial, review]))["statement"] == "evidence"
    assert note(workspace, record(workspace, cid, "argued", "promise", [proposal, review]))["statement"] == "promise"


def test_an_agent_says_what_its_finding_states_and_the_researchers_findings_may_not(campaign):
    workspace, cid, trial, *_ = campaign
    with pytest.raises(ValueError, match="Say what the finding states"):
        record(workspace, cid, "untyped", None, [trial])
    assert note(workspace, record(workspace, cid, "researchers", None, [trial], actor="researcher"))["statement"] == "unspecified"


def test_a_decision_finding_cites_the_decision_record(campaign):
    workspace, cid, trial, proposal, _, decision = campaign
    with pytest.raises(ValueError, match="decision finding cites the record of the decision"):
        record(workspace, cid, "chose", "decision", [trial, proposal])
    assert note(workspace, record(workspace, cid, "chose_with_record", "decision", [decision, trial]))["statement"] == "decision"


def test_counterevidence_for_is_stored_as_a_contradicts_link_and_old_findings_load(campaign):
    workspace, cid, trial, *_ = campaign
    first = record(workspace, cid, "first", "evidence", [trial])
    second = record(workspace, cid, "second", "evidence", [trial], interpretation="counterevidence", counterevidence_for=[first])
    assert note(workspace, second)["links"] == [{"id": first, "relation": "contradicts"}]
    with pytest.raises(ValueError, match="A link names an earlier finding"):
        record(workspace, cid, "bad_link", "evidence", [trial], links=[{"id": trial, "relation": "supports"}])
    # A finding recorded before K3 has neither a statement nor links.
    old = workspace.store.put_immutable("manager_note", {"id": "finding_old", "campaign_id": cid, "kind": "counterevidence", "content": "Before K3.",
        "source_ids": [trial], "interpretation": "counterevidence", "counterevidence_for": [first], "author": "manager", "created_at": "2026-10-01T00:00:00Z"})
    [loaded] = [row for row in view(workspace.store, cid)["findings"] if row["id"] == old["id"]]
    assert loaded["statement"] == "unspecified" and loaded["links"] == [{"id": first, "relation": "contradicts"}]


def test_a_superseded_finding_leaves_the_default_view_and_is_still_readable_by_id(campaign):
    workspace, cid, trial, *_ = campaign
    first = record(workspace, cid, "early", "evidence", [trial])
    later = record(workspace, cid, "late", "evidence", [trial], links=[{"id": first, "relation": "supersedes"}])
    shown = view(workspace.store, cid)
    assert [row["id"] for row in shown["findings"]] == [later]
    assert [(row["id"], row["superseded_by"]) for row in shown["superseded_findings"]] == [(first, [later])]
    assert note(workspace, first)["content"] == "Finding early."


def test_three_findings_citing_the_same_trial_count_as_one_distinct_measurement(campaign):
    workspace, cid, trial, *_ = campaign
    claim = record(workspace, cid, "claim", "evidence", [trial])
    echoes = [record(workspace, cid, f"echo_{n}", "evidence", [trial], links=[{"id": claim, "relation": "supports"}]) for n in (1, 2)]
    send(workspace, cid, "probe_2", "trial.create", run(workspace.current_tasks(cid)[0]))
    other = next(row["id"] for row in workspace.store.list("trial", cid) if row["id"] != trial)
    adds = record(workspace, cid, "adds", "evidence", [other], links=[{"id": echoes[0], "relation": "supports"}])
    shown = {row["id"]: row for row in view(workspace.store, cid)["findings"]}
    support = shown[claim]["support"]
    # The two echoes add nothing; the second-level supporter adds a second experiment.
    assert [(item["id"], item["depth"], item["restates"]) for item in support["supporters"]] == [
        (echoes[0], 1, True), (echoes[1], 1, True), (adds, 2, False)]
    assert support["measurement_ids"] == [trial, other]
    assert shown[echoes[0]]["restates"] == [claim] and shown[adds]["restates"] == []


def test_the_report_writers_evidence_keeps_a_promise_apart_from_a_result(campaign):
    workspace, cid, trial, proposal, *_ = campaign
    result = record(workspace, cid, "result", "evidence", [trial])
    promise = record(workspace, cid, "hope", "promise", [proposal], links=[{"id": result, "relation": "qualifies"}])
    snapshot = freeze(workspace, "k3", cid, {}, [promise])
    assert snapshot["kinds"][promise] == "finding" and snapshot["records"][promise]["statement"] == "promise"
    assert snapshot["records"][promise]["links"] == [{"id": result, "relation": "qualifies"}]
    assert snapshot["records"][result]["statement"] == "evidence"
    assert '"statement": "promise"' in next(row["summary"] for row in snapshot["records"]["inventory"] if row["id"] == promise)
