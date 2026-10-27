"""Admission starts a queued run only when what it is expected to use fits beside what runs, at the researcher's level."""
from types import SimpleNamespace
import json
import threading
import time

import pytest

from optimization_framework.execution.admission import GIB, LEVELS, MARGIN, SETTLING_SECONDS, Admission, kind, tree_rss
from optimization_framework.implementations.service import ImplementationService
from optimization_framework.storage.sqlite import Store, now

LIVE = {"running", "pausing", "stopping"}


def process(root, pid, rss_kib, children=()):
    (root / str(pid) / "task" / str(pid)).mkdir(parents=True)
    (root / str(pid) / "status").write_text(f"Name:\tworker\nVmRSS:\t{rss_kib} kB\n")
    (root / str(pid) / "task" / str(pid) / "children").write_text(" ".join(map(str, children)))


def test_a_runs_memory_is_its_whole_process_tree(tmp_path):
    process(tmp_path, 10, 1024, children=[11])
    process(tmp_path, 11, 2048, children=[12])
    process(tmp_path, 12, 512)
    assert tree_rss(10, tmp_path) == (1024 + 2048 + 512) * 1024
    assert tree_rss(99, tmp_path) is None


class Clock:
    def __init__(self):
        self.now = 1000.

    def __call__(self):
        return self.now


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "store")
    store.put("task", {"id": "task_a", "campaign_id": "c", "name": "Reactor", "problem": {"definition_id": "reactor", "volume": 2}})
    host = {"memory": {"capacity_bytes": 64 * GIB, "effective_available_bytes": 48 * GIB},
            "gpu": {"devices": [{"memory_total_bytes": 32 * GIB, "memory_used_bytes": 4 * GIB}]}}
    jobs = tmp_path / "jobs"
    workspace = SimpleNamespace(store=store, max_workers=8, job_dir=lambda identity: jobs / identity)
    clock = Clock()
    admission = Admission(workspace, proc_root=tmp_path / "proc", clock=clock, host=lambda: host)
    return SimpleNamespace(store=store, host=host, admission=admission, clock=clock, jobs=jobs, proc=tmp_path / "proc")


def trial(identity, status="queued", **extra):
    return {"id": identity, "campaign_id": "c", "task_id": "task_a", "algorithm": "random", "status": status, "created_at": now(), **extra}


def measured(setup, identity, memory, device=None, **extra):
    """A finished run of the default kind that used this much."""
    row = trial(identity)
    setup.store.put("job_usage", {"id": "usage_" + identity, "campaign_id": "c", "subject": "trial", "subject_id": identity,
        "kind": kind({**row, **extra}, setup.store.get("task_a")), "label": "Reactor · random", "memory_peak_bytes": memory,
        "device_peak_bytes": device, "out_of_memory": False})


def run(setup, identity, rss_kib, **extra):
    """Start a run as the scheduler would and give it a live process of this size."""
    row = trial(identity, "running", pid=int(identity.split("_")[1]), **extra)
    process(setup.proc, row["pid"], rss_kib)
    setup.admission.started(row)
    return row


def test_the_level_is_the_researchers_and_balanced_by_default(setup):
    assert setup.admission.level()["level"] == "balanced"
    view = setup.admission.set_level("cautious", authority="researcher", reason="Another job shares the GPU today")
    assert view["level"] == "cautious" and view["set_by"] == "researcher"
    assert setup.store.get("resource_policy", "resource_policy")["previous"] == "balanced"
    with pytest.raises(ValueError, match="cautious, balanced or aggressive"):
        setup.admission.set_level("reckless", authority="researcher")
    assert [level["id"] for level in view["levels"]] == list(LEVELS)


def test_a_kind_never_measured_starts_while_no_other_such_run_is_starting(setup):
    admission = setup.admission
    assert admission.fits(trial("t_1"), []) is None
    first = run(setup, "t_1", 1024)
    # Until it shows what it uses, another run of a kind never measured waits; its own kind's next seed too.
    assert "never measured" in admission.fits(trial("t_2"), [first])
    assert "never measured" in admission.fits(trial("t_2", algorithm_config={"new": True}), [first])
    # A measured kind goes ahead, counting the new run at what it uses so far.
    measured(setup, "t_0", 2 * GIB, algorithm_config={"other": 1})
    assert admission.fits(trial("t_3", algorithm_config={"other": 1}), [first]) is None
    # A few evaluations are enough to count it by its own use.
    admission.observe([{**first, "progress": {"evaluations": 3}}], LIVE)
    assert admission.live["t_1"]["peak"] == 1024 * 1024
    assert admission.fits(trial("t_2"), [first]) is None
    # At the cautious level a kind never measured waits until nothing runs.
    admission.set_level("cautious", authority="researcher")
    assert "starts only when nothing else runs" in admission.fits(trial("t_4", algorithm_config={"new": True}), [first])
    assert admission.view()["waiting"] == [{"trial_id": "t_4", "reason": admission.waiting["t_4"]}]
    setup.clock.now += SETTLING_SECONDS


def test_memory_decides_within_the_worker_maximum(setup):
    admission = setup.admission
    measured(setup, "t_0", 16 * GIB)   # expected: 20 GiB with the margin
    assert admission.expected(kind(trial("x"), setup.store.get("task_a")))["memory_bytes"] == 16 * GIB * MARGIN
    running = [run(setup, "t_1", 1024), run(setup, "t_2", 1024)]
    # Two runs expected at 20 GiB each and a third would be 60 GiB, above 80% of 64 GiB.
    reason = admission.fits(trial("t_3"), running)
    assert reason.startswith("Waits for memory: running work is expected to use 40.0 GiB and this run 20.0 GiB")
    admission.set_level("aggressive", authority="researcher")   # 92% of 64 GiB is 58.9 GiB: still too much
    assert admission.fits(trial("t_3"), running) is not None
    setup.host["memory"]["capacity_bytes"] = 128 * GIB
    admission.host_at = -float("inf")
    # Planned use fits, but the host has less free than the runs may still grow into plus what is kept free.
    setup.host["memory"]["effective_available_bytes"] = 50 * GIB
    assert "kept free" in admission.fits(trial("t_3"), running)
    setup.host["memory"]["effective_available_bytes"] = 100 * GIB
    admission.host_at = -float("inf")
    assert admission.fits(trial("t_3"), running) is None and "t_3" not in admission.waiting


def test_gpu_memory_counts_where_runs_reported_it(setup):
    admission = setup.admission
    measured(setup, "t_0", GIB, device=10 * GIB)   # 12.5 GiB with the margin
    running = [run(setup, "t_1", 1024), run(setup, "t_2", 1024)]
    assert "GPU memory" in admission.fits(trial("t_3"), running)   # 37.5 GiB is more than 80% of 32 GiB
    admission.live.pop("t_2")   # it ended
    assert admission.fits(trial("t_3"), running[:1]) is None
    setup.host["gpu"]["devices"][0]["memory_used_bytes"] = 30 * GIB   # another process now holds most of the card
    admission.host_at = -float("inf")
    assert "free on the GPU" in admission.fits(trial("t_3"), running[:1])


def test_what_a_run_used_is_recorded_when_it_ends(setup):
    admission = setup.admission
    row = trial("t_7", "running", pid=7)
    process(setup.proc, 7, 3 * 1024 * 1024)
    admission.observe([row], LIVE)
    (setup.jobs / "t_7").mkdir(parents=True)
    (setup.jobs / "t_7" / "result.json").write_text(json.dumps({"status": "failed", "device_peak_bytes": 6 * GIB,
        "reason": "OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB"}))
    setup.store.put("trial", {**row, "status": "failed", "reason": "OutOfMemoryError: CUDA out of memory."})
    setup.clock.now += 2
    admission.observe([], LIVE)
    usage = setup.store.get("usage_t_7", "job_usage")
    assert usage["memory_peak_bytes"] == 3 * GIB and usage["device_peak_bytes"] == 6 * GIB and usage["out_of_memory"] is True
    expected = admission.expected(usage["kind"])
    assert expected["device_bytes"] == 6 * GIB * MARGIN and expected["out_of_memory"] == 1 and expected["runs"] == 1


def test_implementation_jobs_run_as_many_at_once_as_the_level_allows(tmp_path, monkeypatch):
    service = ImplementationService(tmp_path / "library")
    release, started = threading.Event(), []
    def hold(job_id):
        started.append(job_id)
        release.wait(5)
        service.update_job(job_id, status="completed")
    monkeypatch.setattr(service, "run_job", hold)
    for index in range(3):
        service.store.put("implementation_job", {"id": f"implementation_job_{index}", "campaign_id": "c", "status": "queued",
            "request": {}, "created_at": now(), "compute_seconds": 0})
    assert service.concurrency() == 1
    with pytest.raises(ValueError, match="Between 1 and 8"):
        service.set_concurrency(0, reason="none")
    service.start()
    try:
        deadline = time.monotonic() + 5
        while len(started) < 1 and time.monotonic() < deadline:
            time.sleep(.05)
        time.sleep(.5)
        assert started == ["implementation_job_0"]   # one at a time until the workspace says otherwise
        service.set_concurrency(2, reason="Resource level balanced")
        while len(started) < 2 and time.monotonic() < deadline:
            time.sleep(.05)
        time.sleep(.5)
        assert started == ["implementation_job_0", "implementation_job_1"]
        release.set()
        while len(started) < 3 and time.monotonic() < deadline:
            time.sleep(.05)
        assert len(started) == 3
    finally:
        release.set()
        service.close()


def events(setup, kind=None):
    with setup.store.connection() as db:
        rows = db.execute("SELECT kind, data FROM events").fetchall()
    return [json.loads(row["data"]) | {"event": row["kind"]} for row in rows if kind is None or row["kind"] == kind]


def test_the_planners_estimate_stands_until_a_run_is_measured(setup):
    from optimization_framework.execution.admission import UsageEstimateInput
    admission = setup.admission
    kind_id = kind(trial("x"), setup.store.get("task_a"))
    assert admission.fits(trial("t_1"), []) is None
    assert events(setup, "resources.unmeasured_kind")[0]["kind"] == kind_id   # the planner hears of the new kind, once
    admission.fits(trial("t_2"), [])
    assert len(events(setup, "resources.unmeasured_kind")) == 1
    admission.estimate("c", UsageEstimateInput(kind=kind_id, memory_bytes=10 * GIB, device_bytes=4 * GIB, rationale="Twice the CNN policy"), authority="manager")
    expected = admission.expected(kind_id)
    assert expected["basis"] == "estimated" and expected["memory_bytes"] == 15 * GIB and expected["device_bytes"] == 6 * GIB   # balanced: ×1.5
    admission.set_level("aggressive", authority="researcher")
    assert admission.expected(kind_id)["memory_bytes"] == 10 * GIB
    # With an estimate a new kind no longer waits for another to settle.
    first = run(setup, "t_1", 1024, algorithm_config={"never": "measured"})
    assert admission.fits(trial("t_2"), [first]) is None
    # A measurement replaces it; a GPU estimate stands until a run reports its GPU use.
    measured(setup, "t_0", 2 * GIB)
    assert admission.expected(kind_id)["basis"] == "measured" and admission.expected(kind_id)["memory_bytes"] == 2 * GIB * MARGIN
    assert admission.expected(kind_id)["device_bytes"] == 4 * GIB


def test_the_planners_plan_and_the_campaigns_share_hold_runs_back(setup):
    from optimization_framework.execution.admission import ResourcePlanInput
    admission = setup.admission
    measured(setup, "t_0", GIB)
    kind_id = kind(trial("x"), setup.store.get("task_a"))
    running = [run(setup, "t_1", 1024), run(setup, "t_2", 1024)]
    admission.plan("c", ResourcePlanInput(workers=2, rationale="The GPU is saturated at two"), authority="manager")
    assert admission.fits(trial("t_3"), running).startswith("Waits: the resource planner runs at most 2 of this campaign's runs")
    admission.plan("c", ResourcePlanInput(kinds={kind_id: 1}, rationale="One of these at a time"), authority="manager")
    assert "at most 1 of this kind" in admission.fits(trial("t_3"), running)
    with pytest.raises(ValueError, match="researcher"):
        admission.plan("c", ResourcePlanInput(workers=9, rationale="More"), authority="manager")
    admission.plan("c", ResourcePlanInput(rationale="No limit of the plan's own"), authority="manager")
    assert admission.fits(trial("t_3"), running) is None
    # With another campaign waiting, each gets half of the eight runs at once.
    running += [run(setup, "t_3", 1024), run(setup, "t_4", 1024)]
    reason = admission.fits(trial("t_5"), running, {"c", "other"})
    assert reason == "Waits: 1 other campaign also has runs waiting, and each campaign gets 4 of the 8 runs at once."
    assert admission.fits(trial("t_5"), running, {"c"}) is None


def test_a_run_that_ran_out_of_memory_is_queued_again_once(setup):
    admission, created = setup.admission, []
    def create_trial(values):
        record = {**values.model_dump(mode="json"), "id": f"t_{90 + len(created)}", "status": "queued"}
        created.append(record)
        setup.store.put("trial", record)
        return record
    admission.workspace.create_trial = create_trial
    def out_of_memory(identity, **extra):
        row = trial(identity, "running", pid=int(identity.split("_")[1]), seed=3, max_steps=50, question="Screen PPO", **extra)
        process(setup.proc, row["pid"], 1024 * 1024)
        setup.clock.now += 2   # the scheduler samples at most once a second
        admission.observe([row], LIVE)
        setup.store.put("trial", {**row, "status": "failed", "reason": "OutOfMemoryError: CUDA out of memory."})
        setup.clock.now += 2
        admission.observe([], LIVE)
    out_of_memory("t_7")
    assert [row["seed"] for row in created] == [3] and "ran out of memory" in created[0]["question"]
    assert setup.store.get("t_90", "trial")["oom_retry_of"] == "t_7"
    signal = events(setup, "resources.out_of_memory")[0]
    assert signal["trial_id"] == "t_7" and signal["retry"] == "t_90" and signal["memory_peak_bytes"] == GIB
    # The retry is not retried, and at the cautious level nothing is.
    out_of_memory("t_8", oom_retry_of="t_7")
    admission.set_level("cautious", authority="researcher")
    out_of_memory("t_9")
    assert len(created) == 1 and [row["retry"] for row in events(setup, "resources.out_of_memory")] == ["t_90", None, None]


def test_a_long_wait_is_brought_to_the_planner_once(setup):
    admission = setup.admission
    measured(setup, "t_0", 40 * GIB)
    running = [run(setup, "t_1", 1024)]
    assert admission.fits(trial("t_2"), running) is not None
    setup.clock.now += 601
    admission.fits(trial("t_2"), running)
    admission.fits(trial("t_2"), running)
    waits = events(setup, "resources.long_wait")
    assert len(waits) == 1 and waits[0]["trial_id"] == "t_2" and waits[0]["reason"].startswith("Waits for memory")
