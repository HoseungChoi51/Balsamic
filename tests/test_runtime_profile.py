"""A runtime profile measures any evaluator the same way and names the symptoms a long run should not start with."""
from datetime import datetime, timedelta, timezone
import json
import time

import pytest

from optimization_framework.contracts.commands import RuntimeProfileInput
from optimization_framework.contracts.requests import CampaignInput, ControlInput, StudyInput, TaskInput, TrialInput
from optimization_framework.contracts.validation import Waiver
from optimization_framework.execution import runtime_profile
from optimization_framework.execution.runtime_profile import derive, probe, rung, rungs
from optimization_framework.execution.service import ACTIVE, Workspace, alive
from optimization_framework.storage.sqlite import identifier, now


def level(workers, rate, gpu=None, cpu=5., **extra):
    return {"workers": workers, "status": "measured", "evaluations_per_second": rate, "gpu_percent": gpu, "cpu_percent": cpu,
            "overhead_share": .1, "bytes_per_evaluation": 140000., "solver_executions_per_evaluation": 1., **extra}


def flags(summary):
    return [flag["id"] for flag in summary["flags"]]


def test_levels_double_up_to_the_ceiling():
    assert [rungs(ceiling) for ceiling in (1, 2, 4, 6, 8)] == [[1], [1, 2], [1, 2, 4], [1, 2, 4, 6], [1, 2, 4, 8]]


def test_flags_name_the_symptoms_measured_on_a_time_sliced_device():
    # Measured on the 2D deflector evaluator before its GPU was shared: more workers, no more designs.
    summary = derive([level(1, 2.49, gpu=45), level(2, 2.46, gpu=46), level(4, 2.59, gpu=47)], ceiling=4, candidate_bytes=65537)
    assert summary["verdict"] == "failed" and flags(summary) == ["no_scaling"] and summary["recommended_workers"] == 1
    # The same evaluator with the device shared: still growing at the ceiling, a note about the ceiling that holds no run.
    shared = derive([level(1, 4.92, gpu=50), level(2, 7.71, gpu=75), level(4, 10.45, gpu=88)], ceiling=4, candidate_bytes=65537)
    assert flags(shared) == ["unsaturated"] and shared["recommended_workers"] == 4 and shared["evaluations_per_hour"] == pytest.approx(37620)
    assert shared["verdict"] == "passed"
    # Saturated: nothing to say, and the smallest level within a tenth of the best is recommended.
    saturated = derive([level(1, 5., gpu=60), level(2, 9., gpu=93), level(4, 9.5, gpu=97)], ceiling=4, candidate_bytes=65537)
    assert saturated["verdict"] == "passed" and saturated["recommended_workers"] == 2
    # Throughput stops growing though the device is mostly idle.
    assert flags(derive([level(1, 5., gpu=20), level(2, 9., gpu=38), level(4, 9.2, gpu=40)], ceiling=4, candidate_bytes=65537)) == ["idle_device"]
    # One worker that already fills the host is not asked to scale.
    assert derive([level(1, 5., cpu=97), level(2, 5.1, cpu=99)], ceiling=2, candidate_bytes=65537)["verdict"] == "passed"


def test_flags_for_the_platforms_share_storage_and_repeated_solves():
    summary = derive([level(1, 2.5, gpu=90, overhead_share=.31, bytes_per_evaluation=1580000., solver_executions_per_evaluation=2.)],
                     ceiling=1, candidate_bytes=65537)
    assert flags(summary) == ["platform_overhead", "storage_heavy", "repeated_solves"]
    assert "2 times" in summary["flags"][2]["message"] and "31%" in summary["flags"][0]["message"]
    # Limits are defaults a study may change.
    assert flags(derive([level(1, 2.5, gpu=90, overhead_share=.31)], ceiling=1, candidate_bytes=65537, thresholds={"overhead_share": .5})) == []
    unmeasured = derive([level(1, 2.5), {"workers": 2, "status": "inconclusive", "reason": "too short"}], ceiling=2)
    assert unmeasured == {"verdict": "inconclusive", "flags": [], "reason": "too short"}


def journal(directory, start, period, count, evaluation=.2, solves=1):
    directory.mkdir(parents=True)
    rows = [{"request_ordinal": index, "created_at": (start + timedelta(seconds=period * (index + 1))).isoformat(), "status": "measured",
             "quantities": {"evaluation_requests": 1, "solver_executions": solves, "evaluation_seconds": evaluation, "worker_seconds": period}}
            for index in range(count)]
    (directory / "costs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (directory / "observations.jsonl").write_text(json.dumps({"candidate": [0, 1] * 50}) + "\n")
    (directory / "requests.jsonl").write_text("x" * 1000)
    return directory


def test_a_level_is_measured_while_all_its_workers_overlap(tmp_path):
    start = datetime(2026, 10, 12, tzinfo=timezone.utc)
    first = probe(journal(tmp_path / "a", start, .5, 20), warmup=2)
    late = probe(journal(tmp_path / "b", start + timedelta(seconds=2), .5, 20), warmup=2)
    assert first["evaluations"] == 20 and len(first["times"]) == 18 and first["candidate_bytes"] == 201
    alone = rung(1, [first])
    assert alone["evaluations_per_second"] == pytest.approx(2.) and alone["overhead_share"] == pytest.approx(.6)
    # Two workers at two evaluations per second each; only the eight seconds both were measuring count.
    samples = [{"at": start.timestamp() + second, "cpu_percent": 10., "gpu_percent": 30. + second} for second in range(0, 14)]
    both = rung(2, [first, late], samples)
    assert both["evaluations_per_second"] == pytest.approx(4., rel=.07) and both["solver_executions_per_evaluation"] == 1
    assert both["device_samples"] == 7 and both["gpu_percent"] == pytest.approx(37.)
    assert both["bytes_per_evaluation"] == pytest.approx(2 * (first["bytes"]) / 40)
    assert rung(2, [first])["status"] == "inconclusive"
    assert rung(1, [probe(journal(tmp_path / "c", start, .5, 4), warmup=2)])["status"] == "inconclusive"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    instance = Workspace(tmp_path / "workspace", max_workers=2)
    yield instance
    for trial in instance.store.list("trial"):
        if trial["status"] in ACTIVE:
            instance.control(trial["id"], ControlInput(action="stop"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(alive(trial) for trial in instance.store.list("trial")):
        instance.reconcile()
        time.sleep(.05)
    instance.close()


def campaign(workspace):
    created = workspace.create_campaign(CampaignInput(name="Runtime", compute_budget_seconds=600, validation_reserve_seconds=30, llm_budget_usd=0,
        tasks=[TaskInput(name="Small grating", physics={"n_cells": 6, "fourier_order": 1})]))
    return created, workspace.current_tasks(created["id"])[0]


@pytest.mark.meent
def test_a_profile_runs_probes_level_by_level_and_gates_long_runs(workspace, monkeypatch):
    monkeypatch.setenv("GRATING_RUNTIME_GATE_SECONDS", "100")
    created, task = campaign(workspace)
    study = workspace.create_study(created["id"], StudyInput(goal="How fast does it run?", task_ids=[task["id"]]))
    long_run = TrialInput(campaign_id=created["id"], task_id=task["id"], algorithm="random", max_steps=5, wall_seconds=120)
    with pytest.raises(ValueError, match="no runtime profile"):
        workspace.create_trial(long_run)
    short = workspace.create_trial(long_run.model_copy(update={"wall_seconds": 20}))   # below the gate
    with pytest.raises(ValueError, match="idle workspace"):
        workspace.runtime.start(created["id"], RuntimeProfileInput(task_id=task["id"], probe_seconds=5))
    workspace.control(short["id"], ControlInput(action="stop"))
    workspace.start()
    profile = workspace.runtime.start(created["id"], RuntimeProfileInput(task_id=task["id"], probe_seconds=5, max_evaluations=100000))
    assert [len(item["trial_ids"]) for item in profile["levels"]] == [1]
    assert workspace.runtime.start(created["id"], RuntimeProfileInput(task_id=task["id"]))["id"] == profile["id"]   # asked again: the same measurement
    waiting = workspace.create_trial(long_run.model_copy(update={"wall_seconds": 20}))
    deadline = time.monotonic() + 90
    while workspace.store.get(profile["id"], "runtime_profile")["status"] == "running" and time.monotonic() < deadline:
        # Nothing but the probes runs while a profile is measuring.
        assert workspace.store.get(waiting["id"], "trial")["status"] == "queued"
        time.sleep(.2)
    profile = workspace.store.get(profile["id"], "runtime_profile")
    assert profile["status"] == "completed", profile.get("reason")
    assert [(item["workers"], len(item["trial_ids"]), item["status"]) for item in profile["levels"]] == [(1, 1, "measured"), (2, 2, "measured")]
    one = profile["levels"][0]
    assert one["evaluations_per_second"] > 1 and 0 <= one["overhead_share"] <= 1 and one["bytes_per_evaluation"] > 0
    assert one["device_samples"] >= 1 and one["cpu_percent"] is not None
    summary = profile["summary"]
    assert summary["verdict"] in {"passed", "failed"} and summary["recommended_workers"] in {1, 2} and summary["evaluations_per_hour"] > 3600
    workspace.control(waiting["id"], ControlInput(action="stop"))
    # The profile answers for the source digest that its probes, and any experiment created now, record.
    probes = [workspace.store.get(trial_id, "trial") for item in profile["levels"] for trial_id in item["trial_ids"]]
    assert {trial["scientific_source_hash"] for trial in probes} == {workspace.store.get(profile["subject_id"], "runtime_subject")["source"]}
    # The resource view the dashboard and the agents read shows it without writing anything.
    from optimization_framework.execution.observability import get_observer
    records = len(workspace.store.list("validation_requirement")) + len(workspace.store.list("runtime_subject"))
    shown = get_observer(workspace).snapshot(created["id"])["runtime"]
    assert [(row["task_id"], row["profile"]["id"], row["flags"]) for row in shown] == [(task["id"], profile["id"], [flag["id"] for flag in summary["flags"]])]
    assert len(workspace.store.list("validation_requirement")) + len(workspace.store.list("runtime_subject")) == records
    view = workspace.runtime.view(task, study["id"])
    assert view["profile"]["id"] == profile["id"] and view["gate_seconds"] == 100
    if holding := [flag for flag in summary["flags"] if runtime_profile.blocks(flag)]:
        # A flagged profile blocks until the researcher waives exactly these flags, citing the profile.
        with pytest.raises(ValueError, match=holding[0]["id"]):
            workspace.create_trial(long_run)
        requirement = workspace.store.get(view["requirement_id"], "validation_requirement")
        workspace.validations.waive(Waiver(id="waiver_runtime", campaign_id=created["id"], study_id=study["id"], requirement_id=requirement["id"],
            subject_digest=requirement["subject_digest"], recipe_id=requirement["recipe_id"], rationale="Accepted for this exploration.",
            evidence_ids=[profile["id"]], authority="researcher", authority_kind="researcher", created_at=now()))
        assert workspace.runtime.view(task, study["id"])["blocker"] is None
    assert workspace.create_trial(long_run)["status"] == "queued"
    # A change of the deployment's resource settings is a new subject: the old profile no longer answers for it.
    monkeypatch.setenv("GRATING_RESOURCE_SETTINGS", '{"workers": 8}')
    with pytest.raises(ValueError, match="no runtime profile"):
        workspace.create_trial(long_run)
    # What was required, measured and waived for the earlier settings is stale, not an open failure.
    assert workspace.validations.assess(view["requirement_id"])["status"] == "stale"
    assert len(workspace.store.list("runtime_subject")) == 1 and len(workspace.store.list("validation_requirement")) == 2
    # Back on the measured settings the profile answers again.
    monkeypatch.delenv("GRATING_RESOURCE_SETTINGS")
    assert workspace.create_trial(long_run)["status"] == "queued"
    assert workspace.validations.assess(view["requirement_id"])["status"] != "stale"
    monkeypatch.setenv("GRATING_RESOURCE_SETTINGS", '{"workers": 8}')
    monkeypatch.delenv("GRATING_RUNTIME_GATE_SECONDS")
    assert workspace.create_trial(long_run)["status"] == "queued"   # no gate is set in this deployment


def measured(workspace, task, *raised, verdict=None):
    """A completed profile of the task's current state that raised these flags, as the store keeps one."""
    subject = workspace.runtime.subject(task)
    profile = {"id": identifier("runtime_profile"), "campaign_id": task["campaign_id"], "task_id": task["id"], "subject_id": subject["id"],
               "subject_digest": subject["digest"], "status": "completed", "ceiling": 2, "parameters": {}, "levels": [], "created_at": now(),
               "summary": {"verdict": verdict or runtime_profile.judged({"verdict": "", "flags": [{"id": name} for name in raised]}),
                           "flags": [{"id": name, "message": f"{name} was measured.", "evidence": {}} for name in raised],
                           "recommended_workers": 2, "evaluations_per_hour": 36000.}}
    workspace.store.put("runtime_profile", profile, "runtime.profile_completed")
    return profile


@pytest.mark.meent
def test_a_note_holds_no_run_even_on_a_profile_judged_before_it_was_one(workspace, monkeypatch):
    monkeypatch.setenv("GRATING_RUNTIME_GATE_SECONDS", "100")
    created, task = campaign(workspace)
    study = workspace.create_study(created["id"], StudyInput(goal="How fast does it run?", task_ids=[task["id"]]))
    long_run = TrialInput(campaign_id=created["id"], task_id=task["id"], algorithm="random", max_steps=5, wall_seconds=120)
    # Measured and judged while speed rising at the ceiling still held runs.
    notes = runtime_profile.NOTES
    monkeypatch.setattr(runtime_profile, "NOTES", set())
    measured(workspace, task, "unsaturated", verdict="failed")
    view = workspace.runtime.view(task, study["id"])
    assert "[unsaturated]" in view["blocker"] and view["note_flags"] == []
    monkeypatch.setattr(runtime_profile, "NOTES", notes)
    # Now it is a note: shown, holding nothing, and the requirement it failed passes on the same measurement.
    view = workspace.runtime.view(task, study["id"])
    assert view["blocker"] is None and view["flags"] == view["note_flags"] == ["unsaturated"]
    assessment = workspace.validations.assess(view["requirement_id"])
    assert [row["verdict"] for row in assessment["results"]] == ["failed", "passed"] and assessment["status"] == "passed"
    assert assessment["results"][-1]["rationale"] == "unsaturated was measured."
    assert workspace.create_trial(long_run)["status"] == "queued"
    workspace.runtime.view(task, study["id"])
    assert len(workspace.validations.assess(view["requirement_id"])["results"]) == 2   # judged again once, not on every read


def test_a_waiver_outlasts_a_recheck_that_names_only_the_flags_it_waived(workspace, monkeypatch):
    monkeypatch.setenv("GRATING_RUNTIME_GATE_SECONDS", "100")
    created, task = campaign(workspace)
    study = workspace.create_study(created["id"], StudyInput(goal="How fast does it run?", task_ids=[task["id"]]))
    first = measured(workspace, task, "repeated_solves")
    view = workspace.runtime.view(task, study["id"])
    assert "[repeated_solves]" in view["blocker"]
    requirement = workspace.store.get(view["requirement_id"], "validation_requirement")
    workspace.validations.waive(Waiver(id="waiver_runtime", campaign_id=created["id"], study_id=study["id"], requirement_id=requirement["id"],
        subject_digest=requirement["subject_digest"], recipe_id=requirement["recipe_id"], rationale="Two solves are part of the method.",
        evidence_ids=[first["id"]], authority="researcher", authority_kind="researcher", created_at=now()))
    assert workspace.runtime.view(task, study["id"])["blocker"] is None
    # Measured again with the same flag: the waiver still answers for it.
    measured(workspace, task, "repeated_solves")
    assert workspace.runtime.view(task, study["id"])["blocker"] is None
    assert workspace.validations.assess(requirement["id"])["status"] == "waived"
    # A flag the researcher has not seen ends the waiver, and both hold runs again.
    measured(workspace, task, "repeated_solves", "storage_heavy")
    blocker = workspace.runtime.view(task, study["id"])["blocker"]
    assert "[repeated_solves]" in blocker and "[storage_heavy]" in blocker
    assert workspace.validations.assess(requirement["id"])["status"] == "failed"
