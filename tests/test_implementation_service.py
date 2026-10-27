"""The implementation library's own API since roadmap H8: it builds nothing and calls no model. A package supplied to it is checked
against its specification's frozen checks, once, and published as an immutable artifact; a job without a package is blocked; jobs
recorded before (an uncertain model call at a restart) stay as they were, conservatively charged."""
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from dqn_meent.implementations.api import create_app
from dqn_meent.implementations.models import ImplementationSpec, JobRequest, Package
from dqn_meent.implementations.runtime import PackageOptimizer, prepare_runtime, write_package
from dqn_meent.implementations.service import NO_BUILDING, NO_CHECKS, ImplementationService


REFERENCE = (Path(__file__).resolve().parents[1] / "examples/implementation-reference/optimizer.py").read_text()


def specification(**changes):
    return ImplementationSpec.model_validate({"name": "Reference seeded one-bit search", "problem_id": "meent_grating",
        "mechanism": "Start from a seeded random binary design. Propose exactly one bit flip from the best observed design; accept only strictly improving observations.",
        "acceptance_criteria": ["Propose one bit from the best observed incumbent", "Preserve RNG and incumbent on checkpoint restoration"],
        "dependencies": {"numpy": "2.5.3"}, "n_cells_max": 16,
        "behavior_checks": [{"name": "Reject deteriorating observations", "assertion": "one_bit_from_incumbent", "efficiencies": [.5, .2, .1, .9, .3]}], **changes})


def package(source=REFERENCE):
    return Package(files=[{"path": "optimizer.py", "content": source}])


def request(**changes):
    return JobRequest.model_validate({"workspace_id": "workspace_one", "campaign_id": "campaign_one", "idempotency_key": "build-one",
        "grant_id": "grant_one", "spec": specification().model_dump(), "compute_seconds": 120, **changes})


def test_a_job_without_a_package_is_blocked_and_calls_no_model(tmp_path):
    service = ImplementationService(tmp_path)
    result = service.run_job(service.submit(request())["id"])
    assert result["status"] == "blocked" and result["error"] == NO_BUILDING
    assert not result["usage"] and not result["attempts"] and not service.store.list("implementation_version")


def test_a_package_whose_specification_has_no_frozen_checks_is_blocked(tmp_path):
    service = ImplementationService(tmp_path)
    result = service.run_job(service.submit(request(spec=specification(behavior_checks=[]).model_dump(), package=package().model_dump()))["id"])
    assert result["status"] == "blocked" and result["error"] == NO_CHECKS
    assert not result["attempts"] and not service.store.list("implementation_version")


def test_a_supplied_package_that_fails_its_checks_fails_once_without_a_rebuild(tmp_path):
    service = ImplementationService(tmp_path)
    invalid = REFERENCE.replace("efficiency > self.score", "True")
    result = service.run_job(service.submit(request(package=package(invalid).model_dump(), accounting_mode="execution_v1"))["id"])
    assert result["status"] == "failed"
    assert len(result["attempts"]) == 1 and result["attempts"][0]["report"]["passed"] is False
    assert not result["usage"].get("calls") and not service.store.list("implementation_version")


def test_service_auth_idempotency_and_capabilities(tmp_path):
    app = create_app(tmp_path, token="secret", start_workers=False)
    with TestClient(app) as client:
        assert client.get("/v1/versions").status_code == 401
        headers = {"Authorization": "Bearer secret"}
        payload = request(spec=specification(capabilities=["gradients"]).model_dump(), package=package().model_dump()).model_dump()
        first = client.post("/v1/jobs", json=payload, headers=headers)
        assert first.status_code == 202
        assert client.post("/v1/jobs", json=payload, headers=headers).json()["id"] == first.json()["id"]
        payload["compute_seconds"] = 10
        assert client.post("/v1/jobs", json=payload, headers=headers).status_code == 409
        result = app.state.service.run_job(first.json()["id"])
        assert result["status"] == "blocked" and "gradients" in result["error"]
        assert not result["usage"]


@pytest.mark.meent
def test_a_supplied_package_is_published_as_an_immutable_artifact(tmp_path):
    service = ImplementationService(tmp_path)
    began = time.monotonic()
    result = service.run_job(service.submit(request(package=package().model_dump()))["id"])
    assert result["status"] == "completed", result
    assert len(result["attempts"]) == 1 and 0 < result["compute_seconds"] <= time.monotonic() - began
    bundle = service.artifact(result["version_id"])
    assert bundle["version"]["validation_report"]["kind"] == "implementation_correctness"
    assert bundle["version"]["validation_report"]["review"] is None   # no model reviewed it
    assert bundle["version"]["exposed_conditions"]
    path = tmp_path / "artifacts" / bundle["version"]["artifact_digest"] / "package/optimizer.py"
    path.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        service.artifact(result["version_id"])


def test_cancel_is_terminal_and_does_not_spend_again(tmp_path):
    service = ImplementationService(tmp_path)
    job = service.submit(request(package=package().model_dump()))
    assert service.control(job["id"], "cancel")["status"] == "cancelled"
    assert service.run_job(job["id"])["status"] == "cancelled"
    with pytest.raises(ValueError, match="Only interrupted"):
        service.control(job["id"], "resume")


def test_control_receipt_lookup_is_authenticated_and_never_reissues_control(tmp_path):
    app = create_app(tmp_path, token="secret", start_workers=False)
    job = app.state.service.submit(request(package=package().model_dump()))
    path = f"/v1/jobs/{job['id']}/control-receipt?idempotency_key=cancel_once"
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers).json() is None
        response = client.post(f"/v1/jobs/{job['id']}/control", json={"action": "cancel", "idempotency_key": "cancel_once"}, headers=headers)
        assert response.status_code == 200
        receipt = client.get(path, headers=headers).json()
        assert receipt["job_id"] == job["id"] and receipt["action"] == "cancel" and receipt["outcome_status"] == "cancelled"
        assert client.get(path, headers=headers).json() == receipt
        assert len(app.state.service.store.list("implementation_control")) == 1


def test_package_isolation_and_checkpoint(tmp_path):
    root, runtime = prepare_runtime(tmp_path / "runtimes", {"numpy": "2.5.3"})
    source = REFERENCE.replace("self.n = context[\"n_cells\"]", """import os, socket
        assert 'OPENAI_API_KEY' not in os.environ
        assert not os.path.exists('/home/chs/Work/dqn-meent-latest')
        try:
            import meent
        except ImportError:
            pass
        else:
            raise RuntimeError('Evaluator accessible')
        self.n = context['n_cells']""")
    package_dir = write_package(tmp_path / "package", package(source))
    optimizer = PackageOptimizer(package_dir, root, runtime, "optimizer:create_optimizer", {"n_cells": 8, "seed": 3, "parameters": {}})
    try:
        design = optimizer.ask()
        optimizer.tell(design, .5)
        checkpoint = optimizer.state_dict()
        expected = optimizer.ask().tolist()
        optimizer.load_state_dict(checkpoint)
        assert optimizer.ask().tolist() == expected
    finally:
        optimizer.close()


@pytest.mark.meent
def test_validation_profile_change_requires_revalidation(tmp_path, monkeypatch):
    service = ImplementationService(tmp_path)
    result = service.run_job(service.submit(request(package=package().model_dump()))["id"])
    assert result["status"] == "completed", result
    monkeypatch.setattr("dqn_meent.implementations.service.profile_identity", lambda: "different")
    with pytest.raises(ValueError, match="requires validation"):
        service.artifact(result["version_id"])


def test_a_job_in_flight_before_h8_with_an_uncertain_model_call_is_conservatively_charged_at_restart(tmp_path):
    """A job the library's builder or reviewer was running when the lab was upgraded (a model call reserved, its outcome unknown)
    is not resumed: at the restart it needs reconciliation, its unobserved time charged within its grant."""
    service = ImplementationService(tmp_path)
    job = service.submit(request())
    service.update_job(job["id"], status="reviewing", execution_started_at=time.time()-10,
        prior_compute_seconds=2, compute_seconds=3, usage={"calls": 1, "pending_reservation": {"id": "uncertain"}})
    service.start()
    try:
        interrupted = service.store.get(job["id"])
        assert interrupted["status"] == "needs_reconciliation"
        assert interrupted["compute_seconds"] >= 12
        with pytest.raises(ValueError, match="Only interrupted"):
            service.control(job["id"], "resume")
        with pytest.raises(ValueError, match="uncertain"):
            service.control(job["id"], "cancel")
        closed = service.control(job["id"], "close_uncertain")
        assert closed["usage"]["pending_reservation"]["id"] == "uncertain"
    finally:
        service.close()


@pytest.mark.meent
def test_revalidation_retains_version_and_history_without_rebuilding(tmp_path):
    service = ImplementationService(tmp_path)
    first = service.run_job(service.submit(request(package=package().model_dump()))["id"])
    second = service.run_job(service.submit(request(package=package().model_dump(), grant_id="grant_two", idempotency_key="second"))["id"])
    assert second["status"] == "completed", second.get("error")
    assert second["version_id"] == first["version_id"]
    version = service.version(first["version_id"])
    assert len(version["validation_history"]) == 1
    assert version["validation_history"][0]["id"] != version["validation_report"]["id"]
