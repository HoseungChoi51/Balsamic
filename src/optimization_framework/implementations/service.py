"""Independent library owner: versions, their validation and revalidation, runtimes, and the jobs that put them there.

Since roadmap H8 the library builds nothing and calls no model. Code is built in coding boxes (agents/development_commission.py,
H7), and a library delivered there is validated outside the box and installed into the lab. What remains here is mechanical:
revalidating a published version against its frozen checks (implementations/revalidation.py), resolving runtimes, and checking
and publishing a package someone supplies to this library's own API against its specification's frozen checks (an import: no
builder, no test designer, no model review). Jobs and versions recorded before stay readable, as they were."""
from __future__ import annotations

import copy
import fcntl
import json
from pathlib import Path
import threading
import time

from optimization_framework.implementations.models import (BehaviorCheck, MechanismCheck, DiagnosticCheck, BoundOptimizerSpec, EvaluatorSpec, JobRequest,
                     RevalidationRequest, CapabilityUnavailable, digest, parse_job_request)
from optimization_framework.implementations.runtime import prepare_runtime, tree_hashes, write_package
from optimization_framework.implementations.validation import evaluator_identity, profile_identity, validate_package
from optimization_framework.storage.sqlite import Store, atomic_json, now


ACTIVE = {"queued", "building", "validating", "reviewing", "repairing", "stopping"}
TERMINAL = {"completed", "failed", "cancelled", "closed_uncertain"}
# Why a job without a package is not run (roadmap H8): building moved to the coding box.
NO_BUILDING = ("The implementation library builds nothing since roadmap H8: a commission runs in a coding box, whose library is "
               "validated outside the box and installed. Supply a package to check and publish here, or commission the method.")
# Why an optimizer package without frozen checks is not run: the test designer that wrote them is retired with the builder.
NO_CHECKS = ("A package is checked against its specification's frozen checks, and this specification has none: name behavior_checks "
             "or diagnostic_checks. Nothing designs them here since roadmap H8.")


class JobInterrupted(Exception):
    pass


class ImplementationService:
    def __init__(self, directory, *, allow_download=False):
        self.store = Store(directory)
        self.directory = self.store.directory
        from optimization_framework.research.log import AgentLog
        self.agent_log = AgentLog(self.store, scope_directory="jobs", origin_service="implementation")
        self.agent_log_thread = None
        self.allow_download = allow_download
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.thread = None
        self.jobs = {}   # job id -> the thread running it
        self.lease = None
        from optimization_framework.implementations.revalidation import migrate
        migrate(self)

    def start(self):
        self.lease = (self.directory / "implementations.lock").open("a+")
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close()
            raise RuntimeError("An implementation service already owns this library")
        for job in self.store.list("implementation_job"):
            if job["status"] in ACTIVE - {"queued"}:
                state = "needs_reconciliation" if (job.get("usage") or {}).get("pending_reservation") else "interrupted"
                elapsed = max(0, time.time() - job.get("execution_started_at", time.time()))
                charged = min(job["request"]["compute_seconds"], max(job["compute_seconds"], job.get("prior_compute_seconds", job["compute_seconds"]) + elapsed))
                self.update_job(job["id"], status=state, compute_seconds=charged,
                    compute_accounting="conservative_after_interruption", unknown_compute_cost=True, accounting_final=True,
                    error="Service restarted; completed artifacts and costs are retained. Unobserved execution time is conservatively charged within the grant.")
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, name="implementation-service", daemon=True)
        self.thread.start()
        self.agent_log_thread = threading.Thread(target=self._project_agent_logs, name="implementation-agent-logs", daemon=True)
        self.agent_log_thread.start()

    def _project_agent_logs(self):
        while not self.stopping.wait(.5):
            self.agent_log.project_pending()

    def close(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=5)
        for thread in list(self.jobs.values()):
            thread.join(timeout=5)
        if self.agent_log_thread:
            self.agent_log_thread.join(timeout=3)
        self.agent_log.project_pending()
        if self.lease and not (self.thread and self.thread.is_alive()) and not any(thread.is_alive() for thread in self.jobs.values()):
            fcntl.flock(self.lease, fcntl.LOCK_UN)
            self.lease.close()
            self.lease = None

    def submit(self, request: JobRequest | RevalidationRequest):
        request = parse_job_request(request)
        data = request.model_dump(mode="json")
        identity = "implementation_job_" + digest([request.workspace_id, request.idempotency_key])[:24]
        with self.lock:
            try:
                old = self.store.get(identity, "implementation_job")
            except KeyError:
                old = None
            if old:
                if old["request_digest"] != digest(data):
                    raise ValueError("Idempotency key was already used for a different implementation request")
                return old
            for existing in self.store.list("implementation_job"):
                if existing["request"]["workspace_id"] == request.workspace_id and existing["request"]["grant_id"] == request.grant_id:
                    raise ValueError("This budget grant is already assigned to another job")
            validation_plan = None
            if isinstance(request, RevalidationRequest):
                from optimization_framework.implementations.revalidation import plan
                version = self.artifact(request.version_id, ready=False)["version"]
                if version["status"] == "revoked":
                    raise ValueError("Revoked artifacts require a corrected version")
                validation_plan = plan(version, request.checks)
            job = {"id": identity, "campaign_id": request.campaign_id, "request": data,
                   "request_digest": digest(data), "revision": 1, "status": "queued", "created_at": now(),
                   "attempts": [], "usage": {}, "compute_seconds": 0., "error": None,
                   "version_id": request.version_id if isinstance(request, RevalidationRequest) else None,
                   "validation_plan": validation_plan}
            job["accounting_final"] = False
            return self.store.put("implementation_job", job, "implementation.queued")

    def update_job(self, job_id, **changes):
        with self.lock, self.store.transaction():
            job = self.store.get(job_id, "implementation_job")
            job.update(changes, updated_at=now(), revision=job.get("revision", 0) + 1)
            self.store.put("implementation_job", job, "implementation.progress")
            if set(changes) & {"status", "error", "attempts", "validation_plan", "version_id"}:
                self.agent_log.record(job_id, "implementation.progress", agent_id="implementation_service", role="implementation_service",
                    task_id=job_id, job_id=job_id, event_key=f"job:{job_id}:{job['revision']}",
                    summary=f"Implementation {job['status']}", payload=changes,
                    workspace_id=job.get("request", {}).get("workspace_id"), grant_id=job.get("request", {}).get("grant_id"))
            return job

    def control(self, job_id, action):
        return self.control_once(job_id, action)

    def control_receipt(self, job_id, idempotency_key):
        self.store.get(job_id, "implementation_job")
        try:
            return self.store.get("implementation_control_" + digest([job_id, idempotency_key]), "implementation_control")
        except KeyError:
            return None

    def control_once(self, job_id, action, idempotency_key=None):
        if idempotency_key is None:
            return self._control(job_id, action)
        identity = "implementation_control_" + digest([job_id, idempotency_key])
        with self.lock, self.store.transaction():
            try:
                previous = self.store.get(identity, "implementation_control")
            except KeyError:
                previous = None
            if previous:
                if previous["action"] != action:
                    raise ValueError("Control identity already belongs to a different action")
                return self.store.get(job_id, "implementation_job")
            result = self._control(job_id, action)
            self.store.put_immutable("implementation_control", {"id": identity, "job_id": job_id,
                "campaign_id": result["campaign_id"], "action": action, "outcome_status": result["status"], "created_at": now()}, "implementation.controlled")
            return result

    def _control(self, job_id, action):
        with self.lock:
            job = self.store.get(job_id, "implementation_job")
            if action == "cancel":
                if job["status"] in TERMINAL:
                    return job
                if job["status"] == "needs_reconciliation":
                    raise ValueError("An uncertain provider call must retain its usage; choose close_uncertain")
                running = job["status"] in ACTIVE - {"queued"}
                return self.update_job(job_id, status="stopping" if running else "cancelled", cancel_requested=True,
                                       error="Stop requested by researcher", finished_at=None if running else now(), accounting_final=not running)
            if action == "close_uncertain":
                if job["status"] != "needs_reconciliation":
                    raise ValueError("Job has no uncertain provider call")
                return self.update_job(job_id, status="closed_uncertain", finished_at=now(), accounting_final=True)
            if action == "resume":
                if job["status"] not in {"interrupted", "blocked"} or job.get("usage", {}).get("pending_reservation"):
                    raise ValueError("Only interrupted or blocked jobs without uncertain calls can resume")
                if job["compute_seconds"] >= job["request"]["compute_seconds"]:
                    raise ValueError("The job's fixed compute grant is exhausted; commission a new bounded job")
                return self.update_job(job_id, status="queued", error=None, cancel_requested=False, accounting_final=False)
            raise ValueError("Unknown implementation control")

    def concurrency(self):
        """How many jobs may run at once: the workspace sets it from the researcher's resource level."""
        try:
            return self.store.get("implementation_concurrency", "implementation_concurrency")["jobs"]
        except KeyError:
            return 1

    def set_concurrency(self, jobs, *, reason):
        if type(jobs) is not int or not 1 <= jobs <= 8:
            raise ValueError("Between 1 and 8 implementation jobs may run at once")
        if jobs != self.concurrency():
            self.store.put("implementation_concurrency", {"id": "implementation_concurrency", "jobs": jobs, "reason": reason,
                "updated_at": now()}, "implementation.concurrency_changed")
        return {"jobs": jobs, "running": sorted(job_id for job_id, thread in self.jobs.items() if thread.is_alive())}

    def _loop(self):
        # Jobs are written only by this process, so an unchanged write count and the same
        # number of running jobs mean nothing can start; avoid decoding MB-scale job records 5x/s.
        seen = None
        while not self.stopping.wait(.2):
            self.jobs = {job_id: thread for job_id, thread in self.jobs.items() if thread.is_alive()}
            state = (self.store.revision("implementation_job", "implementation_concurrency"), len(self.jobs))
            if state == seen:
                continue
            seen = state
            free = self.concurrency() - len(self.jobs)
            for job in self.store.list("implementation_job") if free > 0 else ():
                if job["status"] == "queued" and job["id"] not in self.jobs:
                    thread = threading.Thread(target=self.run_job, args=(job["id"],), name="implementation-job-" + job["id"][-8:], daemon=True)
                    self.jobs[job["id"]] = thread
                    thread.start()
                    free -= 1
                    if not free:
                        break

    def run_job(self, job_id):
        with self.lock:
            job = self.store.get(job_id, "implementation_job")
            if job["status"] != "queued":
                return job
            self.update_job(job_id, status="validating", execution_started_at=time.time(), prior_compute_seconds=job["compute_seconds"])
        if job["request"].get("operation") == "revalidation":
            from optimization_framework.implementations.revalidation import run
            return run(self, job)
        return self._import(job)

    def _import(self, job):
        """Check a supplied package against its specification's frozen checks, once, and publish it when they pass: no model
        is called. A job without a package (a build, as jobs were before roadmap H8) is blocked with NO_BUILDING."""
        job_id = job["id"]
        request = JobRequest.model_validate(job["request"])
        is_evaluator = isinstance(request.spec, EvaluatorSpec)
        started, spent, last_accounted = time.monotonic(), job["compute_seconds"], time.monotonic()

        def progress():
            nonlocal last_accounted
            current = self.store.get(job_id, "implementation_job")
            elapsed = time.monotonic() - started
            if time.monotonic() - last_accounted >= 1:
                self.update_job(job_id, compute_seconds=spent + elapsed)
                last_accounted = time.monotonic()
            if self.stopping.is_set() or current.get("cancel_requested"):
                raise JobInterrupted("Implementation work stopped")
            if spent + elapsed >= request.compute_seconds:
                raise JobInterrupted("Implementation compute allocation exhausted")

        try:
            registry, bound_evaluator_digest = None, None
            if is_evaluator:
                if request.spec.validation_mode == "numerical" and not request.spec.correctness_cases:
                    raise CapabilityUnavailable("Supply independent numerical fixtures for this evaluator before checking it; candidate-authored checks cannot establish correctness.")
            else:
                from optimization_framework.evaluation.registry import problems
                registry = problems
                if isinstance(request.spec, BoundOptimizerSpec):
                    from optimization_framework.evaluation.generated import PublishedEvaluator, evaluator_identity as bound_identity
                    evaluator_bundle = self.artifact(request.spec.evaluator_version_id)
                    directory = self.directory / "artifacts" / evaluator_bundle["version"]["artifact_digest"] / "package"
                    registry = problems.extended(PublishedEvaluator(evaluator_bundle, directory, progress=progress))
                    bound_evaluator_digest = bound_identity(evaluator_bundle["version"])
                definition = registry.get(request.spec.problem_id).describe()
                missing = set(request.spec.capabilities) - set(definition.capabilities)
                if missing:
                    raise CapabilityUnavailable("Evaluator capabilities are unavailable: " + ", ".join(sorted(missing)))
            if request.package is None:
                raise CapabilityUnavailable(NO_BUILDING)
            if is_evaluator:
                spec = request.spec
                if not job.get("validation_plan"):
                    job = self.update_job(job_id, validation_plan={"kind": "evaluator_correctness",
                        "cases": [case.model_dump() for case in spec.correctness_cases],
                        "rationale": "Independent fixtures frozen in the request"})
            else:
                if not job.get("validation_plan"):
                    if not (request.spec.behavior_checks or request.spec.diagnostic_checks):
                        raise CapabilityUnavailable(NO_CHECKS)
                    job = self.update_job(job_id, validation_plan={"checks": [check.model_dump() for check in request.spec.behavior_checks],
                        "mechanism_checks": [check.model_dump() for check in request.spec.mechanism_checks],
                        "diagnostic_checks": [check.model_dump() for check in request.spec.diagnostic_checks],
                        "rationale": "The specification's frozen checks", "blocker": None})
                spec = request.spec.model_copy(update={"behavior_checks": [BehaviorCheck.model_validate(c) for c in job["validation_plan"]["checks"]],
                    "mechanism_checks": [MechanismCheck.model_validate(c) for c in job["validation_plan"].get("mechanism_checks", [])],
                    "diagnostic_checks": [DiagnosticCheck.model_validate(c) for c in job["validation_plan"].get("diagnostic_checks", [])]})
                spec = type(request.spec).model_validate(spec.model_dump())
            progress()
            runtime_root, runtime = prepare_runtime(self.directory / "runtimes", spec.dependencies,
                allow_download=self.allow_download, timeout=max(1, request.compute_seconds - spent - (time.monotonic() - started)),
                kind="evaluator" if is_evaluator else "optimizer")
            progress()
            attempts = copy.deepcopy(job["attempts"])
            if attempts and attempts[-1].get("finished") and not attempts[-1].get("report", {}).get("passed"):
                # A job from before roadmap H8 whose last candidate failed: nothing repairs it here any more.
                raise ValueError("Its candidate failed its checks, and nothing builds a repair here since roadmap H8")
            if not attempts:
                attempts.append({"number": 1, "started_at": now(), "package": request.package.model_dump()})
                self.update_job(job_id, attempts=attempts)
            attempt = attempts[-1]
            attempt.setdefault("package", request.package.model_dump())
            artifact = {"schema_version": 2, "spec": spec.model_dump(), "package": attempt["package"],
                        "runtime": runtime, "protocol": runtime["protocol"]}
            artifact_digest = digest(artifact)
            version_id = "impl_" + artifact_digest[:32]
            artifact_dir = self.directory / "artifacts" / artifact_digest
            package_dir = write_package(artifact_dir / "package", attempt["package"])
            atomic_json(artifact_dir / "artifact.json", artifact)
            atomic_json(artifact_dir / "runtime-location.json", {"runtime_digest": runtime["digest"], "root": str(runtime_root)})
            if not attempt.get("report"):
                validator = validate_package
                if is_evaluator:
                    from optimization_framework.implementations.evaluator_validation import validate_package as validator
                attempt["report"] = validator(spec.model_dump(), attempt["package"], package_dir,
                    runtime_root, runtime, progress=progress, **({"registry": registry, "evaluator_digest": bound_evaluator_digest} if not is_evaluator else {}))
                progress()
            attempt.update(finished=True, finished_at=now(), version_id=version_id)
            self.update_job(job_id, attempts=attempts)
            if not attempt["report"]["passed"]:
                self.update_job(job_id, status="failed", error="The package failed its frozen checks; inspect the validation report.", finished_at=now())
                return self.store.get(job_id, "implementation_job")
            self._publish(job, spec, attempt, version_id, artifact_digest, runtime, package_dir, is_evaluator, progress)
        except JobInterrupted as exc:
            current = self.store.get(job_id, "implementation_job")
            if current["status"] != "cancelled":
                self.update_job(job_id, status="cancelled" if current.get("cancel_requested") else "interrupted", error=str(exc))
        except CapabilityUnavailable as exc:
            self.update_job(job_id, status="blocked", error=str(exc))
        except Exception as exc:
            current = self.store.get(job_id, "implementation_job")
            if current["status"] != "cancelled":
                self.update_job(job_id, status="failed", error=f"Implementation check failed ({type(exc).__name__}): {str(exc)[:1500]}")
        finally:
            changes = {"compute_seconds": spent + time.monotonic() - started, "accounting_final": True}
            current = self.store.get(job_id, "implementation_job")
            if current.get("cancel_requested") and current["status"] != "completed":
                changes["status"] = "cancelled"
            self.update_job(job_id, **changes)
        return self.store.get(job_id, "implementation_job")

    def _publish(self, job, spec, attempt, version_id, artifact_digest, runtime, package_dir, is_evaluator, progress):
        """Publish a package that passed its frozen checks as an immutable version. A version recorded before roadmap H8 carries
        its model review; one published since carries none (review: null)."""
        job_id = job["id"]
        version = {"id": version_id, "name": spec.name, "status": "validated", "created_at": now(),
            "artifact_digest": artifact_digest, "spec": spec.model_dump(), "runtime_digest": runtime["digest"],
            "validation_report": {**attempt["report"], "review": attempt.get("review")},
            "job_id": job_id, "exposed_conditions": sorted(set(spec.exposed_conditions + attempt["report"]["exposed_conditions"])),
            "package_hashes": tree_hashes(package_dir)}
        if is_evaluator:
            version["kind"] = "evaluator"
            if spec.validation_mode == "contract_only":
                version["status"] = "contract_validated"
        with self.lock, self.store.transaction():
            progress()
            try:
                existing = self.store.get(version_id, "implementation_version")
            except KeyError:
                existing = None
            if existing and existing["status"] in {"revoked", "validation_failed"}:
                raise ValueError("This exact implementation was revoked or failed revalidation; inspect its evidence before further use")
            if existing:
                version["created_at"] = existing["created_at"]
                version["validation_history"] = existing.get("validation_history", []) + [existing["validation_report"]]
                if any(report.get("revalidation") for report in version["validation_history"]):
                    raise ValueError("This executable has appended validation evidence; use standalone revalidation to retain its expanded checks")
            version["production_job_ids"] = list(dict.fromkeys([*(existing or {}).get("production_job_ids", [(existing or {}).get("job_id")]), job_id]))
            version["production_job_ids"] = [identity for identity in version["production_job_ids"] if identity]
            self.store.put("implementation_version", version, "implementation.published")
            self.store.put_immutable("implementation_validation", {
                "id": version["validation_report"]["id"], "version_id": version_id,
                "campaign_id": job["campaign_id"], "job_id": job_id, "report": version["validation_report"],
            }, "implementation.validation_recorded")
            self.update_job(job_id, version_id=version_id, status="completed", finished_at=now())

    def version(self, version_id, *, ready=False):
        version = self.store.get(version_id, "implementation_version")
        if ready:
            allowed = {"validated", "contract_validated"} if version.get("kind") == "evaluator" else {"validated"}
            if version["status"] not in allowed:
                raise ValueError("Implementation is not available for new experiments")
            report = version["validation_report"]
            if version.get("kind") == "evaluator":
                from optimization_framework.implementations.evaluator_validation import current
                valid = current(version, numerical=False)
            else:
                if version["spec"].get("evaluator_version_id"):
                    from optimization_framework.evaluation.generated import evaluator_identity as bound_identity
                    expected = bound_identity(self.version(version["spec"]["evaluator_version_id"], ready=True))
                else:
                    expected = evaluator_identity()
                from optimization_framework.implementations.revalidation import report_matches
                valid = (report.get("passed") is True and report["profile_digest"] == profile_identity()
                    and report["evaluator_digest"] == expected and report.get("runtime_digest") == version["runtime_digest"]
                    and report_matches(version, report))
            if not valid:
                raise ValueError("Implementation requires validation against the current evaluator and validation profile")
        return version

    def artifact(self, version_id, *, ready=True):
        version = self.version(version_id, ready=ready)
        root = self.directory / "artifacts" / version["artifact_digest"]
        artifact = json.loads((root / "artifact.json").read_text())
        if digest(artifact) != version["artifact_digest"] or tree_hashes(root / "package") != version["package_hashes"]:
            raise ValueError("Implementation artifact changed after validation")
        production, missing_production = [], []
        for identity in version.get("production_job_ids", [version["job_id"]]):
            from optimization_framework.implementations.exchange import production_job, ProductionEvidenceUnavailable
            try:
                job = production_job(self, version, identity)
            except ProductionEvidenceUnavailable:
                missing_production.append(identity)
                continue
            production.append({key: job.get(key) for key in ("id", "campaign_id", "compute_seconds", "accounting_final", "usage", "created_at", "unknown_compute_cost", "execution_started_at")})
            production[-1]["attempts"] = [{"report": attempt.get("report")} for attempt in job.get("attempts", [])]
        location = root / "runtime-location.json"
        runtime_root = artifact.get("runtime_root")
        binding_error = None
        binding = {}
        if location.exists():
            try:
                binding = json.loads(location.read_text())
                if (not isinstance(binding, dict) or binding.get("runtime_digest") != version["runtime_digest"]
                        or not isinstance(binding.get("root"), str) or not Path(binding["root"]).is_absolute()):
                    raise ValueError("Implementation runtime binding refers to an invalid location or a different identity")
                runtime_root = binding["root"]
            except (OSError, ValueError) as exc:
                # Availability is local operational state; a damaged binding
                # must not hide otherwise intact source and historical evidence.
                runtime_root, binding_error = None, str(exc)
        resolution = None
        if isinstance(binding, dict) and binding.get("resolution_receipt_id"):
            try:
                resolution = self.store.get(binding["resolution_receipt_id"], "runtime_resolution_receipt")
            except KeyError:
                pass  # A process can stop after binding and before its receipt.
        return {"version": version, "artifact": artifact, "production_jobs": production,
                "missing_production_job_ids": missing_production,
                "runtime_resolution_receipt": resolution,
                "missing_runtime_resolution_receipt_id": binding.get("resolution_receipt_id") if isinstance(binding, dict) and resolution is None else None,
                "runtime_root": runtime_root, **({"runtime_binding_error": binding_error} if binding_error else {})}

    def revoke(self, version_id, reason):
        with self.lock:
            version = self.version(version_id)
            version.update(status="revoked", revocation_reason=reason, revoked_at=now())
            return self.store.put("implementation_version", version, "implementation.revoked")

    def events(self, after=0, limit=200):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM events WHERE id>? ORDER BY id ASC LIMIT ?", (after, limit)).fetchall()
        return [{**dict(row), "data": json.loads(row["data"])} for row in rows]
