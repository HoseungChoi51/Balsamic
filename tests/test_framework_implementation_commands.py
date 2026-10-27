"""Implementation commands on the bus are durable and dispatch only after commit; a grant recorded before roadmap H8 stays
controllable through them."""
from framework_fixtures import grant_before_h8, researcher_idea
from fastapi.testclient import TestClient

from balsamic.app import create_app
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.storage.sqlite import now
from optimization_framework.execution.service import Workspace
from optimization_framework.implementations.models import ImplementationSpec


class Library:
    def __init__(self):
        self.jobs = {}
        self.controls = {}
        self.deliveries = []
        self.lose_control_reply = False

    def versions(self):
        return []

    def submit(self, request):
        assert not self.workspace.store.in_transaction
        self.workspace.store.get(request["grant_id"], "implementation_grant")
        return self.jobs.setdefault(request["idempotency_key"], {"id": "job_" + request["idempotency_key"], "status": "queued"})

    def control(self, identity, action, *, idempotency_key):
        assert not self.workspace.store.in_transaction
        self.deliveries.append(idempotency_key)
        result = self.controls.setdefault(idempotency_key, {"id": identity, "status": "interrupted"})
        if self.lose_control_reply:
            self.lose_control_reply = False
            raise ValueError("Lost acknowledgement after accepting control")
        return result


def prepare(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    library = Library()
    app = create_app(tmp_path, start_workers=False, implementation_client=library)
    workspace = library.workspace = app.state.workspace
    campaign = workspace.create_campaign(CampaignInput(name="Implementation commands", implementation_compute_budget_seconds=40,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    hypothesis = researcher_idea(workspace, campaign["id"])
    return app, workspace, library, campaign, hypothesis


def command(workspace, campaign, operation, payload, identity):
    return Command(id=identity, campaign_id=campaign["id"], operation=operation, payload=payload,
                   expected_revision=workspace.store.get(campaign["id"], "campaign")["version"]).model_dump(mode="json")


def running_grant(workspace, library, campaign, hypothesis, key):
    """A grant a commission recorded before roadmap H8, its library job still running when the lab was upgraded."""
    spec = ImplementationSpec(name="Coordinate variant", mechanism="Bounded coordinate search", problem_id="bounded_continuous",
        capabilities=["continuous"], acceptance_criteria=["Feasible candidates"]).model_dump(mode="json")
    job = library.jobs.setdefault(key, {"id": "job_" + key, "status": "running", "campaign_id": campaign["id"], "created_at": now(),
        "request": {"grant_id": "grant_" + key, "idempotency_key": key, "hypothesis_id": hypothesis["id"], "spec": spec,
                    "compute_seconds": 10, "api_budget_usd": 0}})
    return grant_before_h8(workspace, job)


def test_a_grant_recorded_before_h8_stays_controllable_and_recovers_a_lost_control(tmp_path, monkeypatch):
    app, workspace, library, campaign, hypothesis = prepare(tmp_path, monkeypatch)
    original = running_grant(workspace, library, campaign, hypothesis, "legacy_job")
    with TestClient(app) as client:
        assert workspace.implementations.compute_committed(campaign["id"]) == 10   # its reservation still counts
        library.lose_control_reply = True
        control = command(workspace, campaign, "implementation.control", {"grant_id": original["id"], "action": "cancel"}, "cancel_once")
        controlled = client.post("/api/v1/commands", json=control)
        assert controlled.status_code == 200, controlled.text
        receipt = client.get("/api/v1/commands/cancel_once").json()
        effect = workspace.store.get(receipt["outcome"]["effect_id"], "outbox")
        assert effect["status"] == "pending" and len(library.controls) == 1
        restarted = Workspace(tmp_path, implementation_client=library)
        library.workspace = restarted
        restarted.dispatch_outbox()
        assert restarted.commands.execute(receipt["request"]) == receipt
        assert restarted.store.get(effect["id"], "outbox")["status"] == "completed"
        replay = client.post("/api/v1/commands", json=control)
        assert replay.json()["outcome"] == receipt["outcome"]
        assert len(library.controls) == 1 and library.deliveries == [effect["id"], effect["id"]]
        assert len(library.jobs) == 1


def test_attachment_returns_receipt_and_dispatches_only_after_commit(tmp_path, monkeypatch):
    app, workspace, library, campaign, hypothesis = prepare(tmp_path, monkeypatch)
    calls = []
    def decide(bridge, *, identity, hypothesis_id, version_id, **kwargs):
        assert not workspace.store.in_transaction
        assert workspace.store.get(identity.removeprefix("reuse_"), "outbox")["status"] == "pending"
        calls.append((hypothesis_id, version_id))
        value = workspace.store.get(hypothesis_id, "hypothesis")
        value["implementation_version_id"] = version_id
        workspace.store.put("hypothesis", value)
        return value
    monkeypatch.setattr("optimization_framework.implementations.reuse.decide", decide)
    with TestClient(app) as client:
        attach = command(workspace, campaign, "implementation.attach", {"hypothesis_id": hypothesis["id"], "version_id": "version_validated"}, "attach_once")
        first = client.post("/api/v1/commands", json=attach)
        assert first.status_code == 200, first.text
        assert first.json()["outcome"]["implementation_version_id"] == "version_validated"
        assert workspace.store.get(first.json()["outcome"]["effect_id"], "outbox")["status"] == "completed"
        assert workspace.store.get(hypothesis["id"], "hypothesis")["implementation_version_id"] == "version_validated"
        assert client.post("/api/v1/commands", json=attach).json() == first.json()
        assert client.post("/api/v1/commands", json={**attach, "payload": {**attach["payload"], "version_id": "version_other"}}).status_code == 409
    assert calls == [(hypothesis["id"], "version_validated")]


def test_accepted_implementation_control_reconciles_before_new_guidance(tmp_path, monkeypatch):
    app, workspace, library, campaign, hypothesis = prepare(tmp_path, monkeypatch)
    grant = running_grant(workspace, library, campaign, hypothesis, "receipt_job")
    def lookup(identity, key):
        return {"id": "receipt_" + key, "job_id": identity, "action": "cancel"} if key in library.controls else None
    monkeypatch.setattr(library, "control_receipt", lookup, raising=False)
    monkeypatch.setattr(library, "job", lambda identity: {"id": identity, "status": "cancelled"}, raising=False)
    library.lose_control_reply = True
    with TestClient(app) as client:
        accepted = client.post("/api/v1/commands", json=command(workspace, campaign, "implementation.control",
            {"grant_id": grant["id"], "action": "cancel"}, "accepted_control")).json()
    effect_id = accepted["outcome"]["effect_id"]
    assert workspace.store.get(effect_id, "outbox")["status"] == "pending"
    memory = workspace.memory.state(campaign["id"])
    memory["guidance_revision"] += 1
    workspace.store.put("manager_state", memory)
    restarted = Workspace(tmp_path, implementation_client=library)
    library.workspace = restarted
    restarted.dispatch_outbox()
    effect = restarted.store.get(effect_id, "outbox")
    assert effect["status"] == "completed" and effect["receipt_id"] == "receipt_" + effect_id
    assert library.deliveries == [effect_id]
    # An unaccepted old resume remains prohibited after the same guidance edit.
    old_resume = {**effect, "id": "unaccepted_old_resume", "action": "resume", "status": "pending"}
    restarted.store.put("outbox", old_resume)
    restarted.dispatch_outbox()
    assert library.deliveries == [effect_id]
    assert restarted.store.get(old_resume["id"], "outbox")["status"] == "pending"
