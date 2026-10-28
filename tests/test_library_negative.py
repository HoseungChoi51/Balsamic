"""Roadmap K4: a method stopped after a fair assessment goes to the library as a negative entry another campaign can find."""
import pytest

from optimization_framework.contracts.requests import CampaignInput, TaskInput

from balsamic.library.service import PublishInput, publish, register, search
from test_assessment_gate import prepare as prepare_campaign, run, stop, stopped, trials
from test_mandates import granted


def prepare(path):
    workspace, campaign, target = prepare_campaign(path)
    register(workspace)   # library.publish and library.apply, as the app registers them
    return workspace, campaign, target


def publish_negative(workspace, campaign, target, identity="entry"):
    return run(workspace, campaign, "publish_" + identity, "library.publish", {"hypothesis_id": target["id"], "kind": "negative", "notes": "tried it properly"},
               actor="researcher")["outcome"]


def second_campaign(workspace):
    campaign = workspace.create_campaign(CampaignInput(name="Again", autonomy="delegated", compute_budget_seconds=100000, validation_reserve_seconds=0,
                                                       tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    granted(workspace, campaign["id"])
    return campaign


def test_an_adequately_assessed_unpromising_stop_publishes_as_negative_and_under_evaluated_is_refused(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 3, [0, 1])
    stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs[:2])
    entry = publish_negative(workspace, campaign, target)["entry"]
    assert entry["kind"] == "negative" and entry["origin_campaign_id"] == campaign["id"]
    assert entry["stop"]["outcome"] == "configuration_unpromising" and entry["stop"]["evidence_ids"] == runs[:2]
    assert entry["stop"]["reason"] == "worse than the others" and entry["stop"]["by"] == "manager"
    assessment = entry["assessment"]
    assert assessment["basis"] == "adequate" and assessment["words"] == "3 of 3 configurations, 2 seeds each"
    assert [item["seeds"] for item in assessment["configurations_run"]] == [[0, 1]] * 3
    assert sorted(round(item["algorithm_config"]["radius"], 2) for item in assessment["configurations_run"]) == [0.1, 0.2, 0.3]
    assert entry["evidence"]["best_score"] == 0.5 and entry["evidence"]["best_basis"] == "measured" and set(entry["evidence"]["trial_ids"]) == set(runs)
    assert entry["signature"]["problem_id"] == "bounded_continuous" and entry["signature"]["representation"] == "continuous"
    assert stopped(workspace, target)["library_entry_id"] == entry["id"]
    with pytest.raises(ValueError, match="immutable"):
        workspace.store.put("library_entry", {**entry, "notes": "edited"})

    other = run(workspace, campaign, "other", "hypothesis.create", {"title": "Tabu", "mechanism": "m", "rationale": "r", "algorithm": "coordinate"},
                actor="researcher")["outcome"]["hypothesis"]
    few = trials(workspace, campaign, other, 1, [0], prefix="u")
    stop(workspace, campaign, other, "honest", "under_evaluated", few)
    with pytest.raises(ValueError, match="its stop outcome is under-evaluated, which says nothing about the method"):
        publish_negative(workspace, campaign, other, "publish_other")
    assert len(workspace.store.list("library_entry")) == 1 and not stopped(workspace, other).get("library_entry_id")


def test_stops_that_say_nothing_about_the_method_are_refused_with_the_reason(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    with pytest.raises(ValueError, match="Only a stopped strategy goes to the library as a negative entry"):
        publish_negative(workspace, campaign, target, "running")
    stop(workspace, campaign, target, "unaffordable", "unaffordable_within_allocation", runs)
    with pytest.raises(ValueError, match="unaffordable within the allocation, which says nothing about the method"):
        publish_negative(workspace, campaign, target, "unaffordable")
    # The researcher's stop without an outcome records researcher_decision: no verdict on the method either.
    run(workspace, campaign, "again", "hypothesis.status", {"hypothesis_id": target["id"], "status": "investigating",
        "expected_status_revision": stopped(workspace, target)["status_revision"]}, actor="researcher")
    run(workspace, campaign, "mine", "hypothesis.status", {"hypothesis_id": target["id"], "status": "archived",
        "expected_status_revision": stopped(workspace, target)["status_revision"], "stop_reason": "enough"}, actor="researcher")
    with pytest.raises(ValueError, match="the stop names no outcome, which says nothing about the method"):
        publish_negative(workspace, campaign, target, "no_outcome")
    # A stop recorded before typed outcomes reads as unspecified.
    old = {**stopped(workspace, target)}
    old.pop("stop")
    workspace.store.put("hypothesis", old)
    with pytest.raises(ValueError, match="the stop names no outcome"):
        publish_negative(workspace, campaign, target, "old")
    assert workspace.store.list("library_entry") == []


def test_a_performance_stop_on_fewer_runs_needs_the_researchers_waiver(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    # The researcher's own stop is not gated, but a verdict in the library is.
    stop(workspace, campaign, target, "mine", "configuration_unpromising", runs, actor="researcher")
    with pytest.raises(ValueError, match=r"only after an adequate assessment or your waiver .*1 of 3 configurations; 1 of 2 seeds"):
        publish_negative(workspace, campaign, target, "early")
    run(workspace, campaign, "ask", "approval.request", {"kind": "waiver", "tuning_hypothesis_id": target["id"], "evidence_ids": runs,
        "rationale": "The default configuration is the only one the paper reports"})
    decision = workspace.store.list("decision", campaign["id"])[-1]
    run(workspace, campaign, "approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "the paper's setting",
        "expected_resolution_revision": 0}, actor="researcher")
    [waiver] = workspace.store.list("waiver", campaign["id"])
    entry = publish_negative(workspace, campaign, target, "waived")["entry"]
    assert entry["assessment"]["basis"] == "waiver" and entry["assessment"]["waiver_id"] == waiver["id"] and entry["assessment"]["adequate"] is False


def test_an_invalid_implementation_needs_its_evidence(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    run(workspace, campaign, "bare", "hypothesis.status", {"hypothesis_id": target["id"], "status": "archived", "expected_status_revision": 0,
        "outcome": "implementation_invalid", "stop_reason": "it crashes"}, actor="researcher")
    with pytest.raises(ValueError, match="goes to the library only with its evidence"):
        publish_negative(workspace, campaign, target, "bare")
    run(workspace, campaign, "again", "hypothesis.status", {"hypothesis_id": target["id"], "status": "investigating",
        "expected_status_revision": stopped(workspace, target)["status_revision"]}, actor="researcher")
    stop(workspace, campaign, target, "invalid", "implementation_invalid", runs)
    entry = publish_negative(workspace, campaign, target, "invalid")["entry"]
    assert entry["stop"]["outcome"] == "implementation_invalid" and entry["stop"]["evidence_ids"] == runs and entry["assessment"]["basis"] == "not required"


def test_only_the_researcher_publishes_a_negative_entry(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 3, [0, 1])
    stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs[:1])
    for actor in ("manager", "autopilot"):
        with pytest.raises(ValueError, match="Only the researcher publishes"):
            publish(workspace, campaign["id"], PublishInput(hypothesis_id=target["id"], kind="negative"), command_id="by_" + actor, actor=actor)
    assert workspace.store.list("library_entry") == []


def test_search_labels_a_negative_entry_and_apply_says_why_it_was_stopped(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 3, [0, 1])
    stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs[:2])
    entry_id = publish_negative(workspace, campaign, target)["entry_id"]
    again = second_campaign(workspace)
    [row] = search(workspace, campaign_id=again["id"])["entries"]
    assert row["entry"]["id"] == entry_id and row["kind"] == "negative" and row["label"] == "assessed and stopped: configuration unpromising"
    assert "same problem" in row["match"]["reasons"] and row["match"]["score"] >= 6
    assert search(workspace, campaign_id=again["id"], q="others")["entries"][0]["entry"]["id"] == entry_id   # the stop's reason is searchable
    from balsamic.lead.state import library_line
    [line] = library_line(workspace, workspace.store.get(again["id"], "campaign"))
    assert line.startswith("Library, assessed and stopped elsewhere") and "Annealing" in line and "configuration unpromising" in line
    applied = run(workspace, again, "apply", "library.apply", {"entry_id": entry_id, "note": "try it with restarts"}, actor="researcher")["outcome"]
    rationale = workspace.store.get(applied["hypothesis_id"], "hypothesis")["rationale"]
    assert ("It was assessed and stopped as configuration unpromising: worse than the others, after an adequate assessment "
            "(3 of 3 configurations, 2 seeds each), in campaign " + campaign["id"] + " on bounded_continuous") in rationale
    assert "same problem" in rationale and "try it with restarts" in rationale


def test_old_entries_read_as_positive(tmp_path):
    workspace, campaign, _ = prepare(tmp_path)
    workspace.store.put_immutable("library_entry", {"id": "library_old", "origin_campaign_id": "earlier", "hypothesis_id": "h_old",
        "strategy": {"title": "Restart"}, "signature": {"problem_id": "bounded_continuous"}, "evidence": {"best_score": 0.1}, "graph": {}, "notes": "",
        "published_by": "researcher", "created_at": "2026-01-01T00:00:00Z"}, "library.published")
    [row] = search(workspace, campaign_id=campaign["id"])["entries"]
    assert row["kind"] == "positive" and row["label"] is None
    from balsamic.lead.state import library_line
    [line] = library_line(workspace, workspace.store.get(campaign["id"], "campaign"))
    assert line.startswith("Library (strategies that won earlier campaigns of this problem): Restart")
