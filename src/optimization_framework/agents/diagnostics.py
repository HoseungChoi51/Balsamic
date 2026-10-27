"""Bounded fixed-design evaluator diagnostics, separate from optimizer trials: the runner of ``fixed_mask_job`` records.

A problem pack's ``fixed_mask.run`` queues the jobs; the runner starts, bounds and reconciles them for any campaign, so
the jobs of earlier campaigns finish and read as before.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.evaluation.registry import problems
from optimization_framework.storage.sqlite import atomic_json, now


def reconcile(workspace):
    with workspace.lock:
        _reconcile(workspace)


def _reconcile(workspace):
    from optimization_framework.execution.devices import environment
    from optimization_framework.execution.service import process_identity
    for job in workspace.store.list("fixed_mask_job"):
        if job["status"] not in {"queued", "starting", "running"}:
            continue
        directory = workspace.directory / "fixed-masks" / job["id"]
        report_path = directory / "report.json"
        if job["status"] == "queued":
            if workspace.shutdown_event.is_set():
                return
            diagnostics = sum(j["status"] in {"starting", "running"} for j in workspace.store.list("fixed_mask_job"))
            # A fixed-mask job computes on CPU and takes one of its slots.
            used = workspace.devices.used(workspace.store.list_trials_in_status({"running", "pausing", "stopping"}), diagnostics)
            if diagnostics >= 1 or used["cpu"] >= workspace.devices.sizes()["cpu"]:
                return
            directory.mkdir(parents=True, exist_ok=True)
            job.update(status="starting", started_epoch=time.time())
            workspace.store.put("fixed_mask_job", job, "fixed_mask.launch_reserved")
            atomic_json(directory / "input.json", job)
            with (directory / "worker.log").open("ab") as log:
                child = subprocess.Popen([sys.executable, "-m", __name__, str(directory)], stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, start_new_session=True,
                    env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", **environment("cpu")})
            job.update(status="running", pid=child.pid, process_identity=process_identity(child.pid))
            workspace.store.put("fixed_mask_job", job, "fixed_mask.started")
            workspace.pi.diagnostic_processes[job["id"]] = child
            continue
        elapsed = time.time() - job["started_epoch"]
        owner = directory / "owner.json"
        if not job.get("pid") and owner.exists():
            job.update(json.loads(owner.read_text()), status="running")
            workspace.store.put("fixed_mask_job", job, "fixed_mask.launch_recovered")
        if not job.get("pid") and elapsed < job["wall_seconds"] + 5:
            continue  # Unknown launch outcome is never blindly replayed.
        alive = job.get("pid") and process_identity(job["pid"]) == job.get("process_identity") and job.get("process_identity")
        if alive and elapsed < job["wall_seconds"]:
            continue
        if alive:
            try:
                os.killpg(job["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        child = workspace.pi.diagnostic_processes.pop(job["id"], None)
        if child:
            child.wait(timeout=5)
        report = json.loads(report_path.read_text()) if report_path.exists() else {"checks": [], "complete": False}
        completed = bool(report.get("complete")) and not report.get("error")
        report.update(id="report_" + job["id"], campaign_id=job["campaign_id"], job_id=job["id"],
            completed=completed, created_at=now(), scope=job["scope"], fixture_identity=job["identity"],
            termination="completed" if completed else "wall_limit_or_interruption" if not report.get("error") else "failed")
        with workspace.store.transaction():
            workspace.store.put_immutable("fixed_mask_report", report, "fixed_mask.report_saved")
            job.update(status="completed" if completed else "interrupted", report_id=report["id"],
                execution_seconds=min(elapsed, job["wall_seconds"]), finished_at=now())
            workspace.store.put("fixed_mask_job", job, "fixed_mask.completed")


def worker(directory):
    from threadpoolctl import threadpool_limits
    threadpool_limits(limits=1)
    directory = Path(directory)
    job = json.loads((directory / "input.json").read_text())
    from optimization_framework.execution.service import process_identity
    atomic_json(directory / "owner.json", {"pid": os.getpid(), "process_identity": process_identity(os.getpid())})
    # The worker enforces the grant even while the workspace is restarting.
    remaining = job["wall_seconds"] - (time.time() - job["started_epoch"])
    if remaining <= 0:
        return
    signal.setitimer(signal.ITIMER_REAL, remaining)
    report = {"checks": [], "evaluation_requests": 0, "solver_executions": 0, "complete": False}
    started = time.monotonic()
    try:
        for raw in job["instances"]:
            instance = ProblemInstance.model_validate(raw)
            init = time.monotonic(); evaluator = problems.evaluator(instance)
            startup = time.monotonic() - init
            try:
                for fixture in job["fixtures"]:
                    for repeat in range(job["request"]["repeats"]):
                        before = time.monotonic()
                        value = evaluator.evaluate(fixture["candidate"])
                        report["checks"].append({"mask_artifact_id": fixture["artifact_id"], "repeat": repeat,
                            "fidelity": instance.fidelity, "evaluation_identity": instance.evaluation_identity,
                            "evaluator_version": instance.evaluator_version, "startup_seconds": startup,
                            "evaluation_seconds": time.monotonic() - before, "observation": value.model_dump(mode="json")})
                        report["evaluation_requests"] += 1
                        report["solver_executions"] += value.solver_executions
                        report["elapsed_seconds"] = time.monotonic() - started
                        atomic_json(directory / "report.json", report)
            finally:
                if hasattr(evaluator, "close"):
                    evaluator.close()
        report["complete"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"[:2000]
    report["elapsed_seconds"] = time.monotonic() - started
    atomic_json(directory / "report.json", report)


if __name__ == "__main__":
    worker(sys.argv[1])
