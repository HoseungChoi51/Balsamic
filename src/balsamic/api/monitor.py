"""The monitor: resources, model usage, the agent team, the inbox. Reads only; the resource level is the one write."""
from fastapi import HTTPException, Query

from balsamic import housekeeping
from pydantic import Field
from typing import Literal

from optimization_framework.contracts.requests import Model

from balsamic.api.threads import scoped
from balsamic.monitor.rows import acknowledge, monitor_view, inbox_view


class ResourceLevelInput(Model):
    level: Literal["cautious", "balanced", "aggressive"]
    reason: str = Field(default="", max_length=2000)


class SlotsInput(Model):
    workers: int = Field(ge=1, le=64)
    gpu_workers: int = Field(ge=0, le=63)
    reason: str = Field(default="", max_length=2000)


class InboxAcknowledgeInput(Model):
    keys: list[str] = Field(min_length=1, max_length=500)


def install(app, workspace):
    @app.get("/api/v1/campaigns/{campaign_id}/monitor")
    def monitor(campaign_id: str, after: int = Query(0, ge=0)):
        workspace.store.get(campaign_id, "campaign")
        return scoped(workspace, campaign_id, after, lambda: monitor_view(workspace, campaign_id))

    @app.get("/api/v1/campaigns/{campaign_id}/inbox")
    def inbox(campaign_id: str, after: int = Query(0, ge=0)):
        workspace.store.get(campaign_id, "campaign")
        return scoped(workspace, campaign_id, after, lambda: inbox_view(workspace, campaign_id))

    @app.post("/api/v1/campaigns/{campaign_id}/inbox/acknowledge")
    def inbox_acknowledge(campaign_id: str, body: InboxAcknowledgeInput):
        # HTTP is the researcher's boundary: an agent cannot acknowledge what waits for the researcher.
        workspace.store.get(campaign_id, "campaign")
        acknowledge(workspace, campaign_id, body.keys)
        return {"unacknowledged": inbox_view(workspace, campaign_id)["unacknowledged"]}

    @app.get("/api/v1/campaigns/{campaign_id}/away-digest")
    def away_digest(campaign_id: str, since: int | None = None):
        from balsamic.monitor.digest import compute, open_digest
        workspace.store.get(campaign_id, "campaign")
        if since is not None:
            return compute(workspace, campaign_id, since)
        digest = open_digest(workspace, campaign_id)
        history = workspace.store.list("away_digest", campaign_id)[-10:]
        return {"digest": digest, "history": [{key: row.get(key) for key in ("id", "from_event", "to_event", "rounds_completed", "away_minutes", "written_at", "seen_at")} for row in history]}

    @app.post("/api/v1/campaigns/{campaign_id}/away-digest/{digest_id}/seen")
    def digest_seen(campaign_id: str, digest_id: str):
        from balsamic.monitor.digest import mark_seen
        record = workspace.store.get(digest_id, "away_digest")
        if record["campaign_id"] != campaign_id:
            raise HTTPException(404, "Unknown digest")
        return mark_seen(workspace, digest_id)

    @app.get("/api/v1/resources")
    def resource_observations(campaign_id: str | None = None):
        from optimization_framework.execution.observability import get_observer
        return {**get_observer(workspace).snapshot(campaign_id), "slots": workspace.slots_view()}

    @app.put("/api/v1/resources/slots")
    def resource_slots(body: SlotsInput):
        # HTTP is the researcher's boundary: an agent asks with approval.request (worker_ceiling).
        try:
            workspace.set_slots(body.workers, body.gpu_workers, authority="researcher", reason=body.reason)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return workspace.slots_view()

    @app.put("/api/v1/resources/level")
    def resource_level(body: ResourceLevelInput):
        # HTTP is the researcher's boundary: agents never reach this route.
        return workspace.admission.set_level(body.level, authority="researcher", reason=body.reason)

    @app.get("/api/v1/campaigns/{campaign_id}/agents")
    def agents(campaign_id: str):
        workspace.store.get(campaign_id, "campaign")
        return workspace.pi.view(campaign_id)

    @app.get("/api/v1/campaigns/{campaign_id}/desks/{role}")
    def desk(campaign_id: str, role: str, limit: int = Query(default=60, ge=1, le=400)):
        """The desk of the agent in charge of a page: the researcher's requests on that page and the agent's replies."""
        from optimization_framework.agents.models import PAGE_AGENTS
        from balsamic.threads.service import event_cursor
        workspace.store.get(campaign_id, "campaign")
        if role not in PAGE_AGENTS:
            raise HTTPException(404, f"No page agent named {role}")
        agent = next((a for a in workspace.store.list("agent_session", campaign_id) if a["role"] == role), None)
        rows = [m for m in workspace.store.list("message", campaign_id) if m.get("desk") == role and not m.get("thread_id")]
        rows.sort(key=lambda m: m.get("created_at") or "")
        # Dialogs its session's extensions opened: answered here, on the agent's own page.
        dialogs = [q for q in workspace.store.list("agent_question", campaign_id) if agent and q.get("agent_id") == agent["id"]
                   and q.get("kind") == "extension_dialog" and q["status"] == "pending"]
        return {"campaign_id": campaign_id, "role": role, "page": "#" + PAGE_AGENTS[role], "event_cursor": event_cursor(workspace, campaign_id),
                "agent": {k: v for k, v in agent.items() if k not in {"output_schema", "output"}} if agent else None,
                "messages": rows[-limit:], "truncated": len(rows) > limit, "dialogs": dialogs}

    @app.get("/api/v1/campaigns/{campaign_id}/agents/live")
    def agents_live(campaign_id: str):
        return workspace.pi.live(campaign_id)

    @app.get("/api/v1/campaigns/{campaign_id}/discussions")
    def discussions(campaign_id: str):
        from optimization_framework.agents.discussions import view
        return view(workspace, campaign_id)

    def harness_models():
        from optimization_framework.agents.families import family_of
        try:
            status = workspace.pi.client.status() or {}
            workspace.pi.harness_status = status
        except (ValueError, OSError):
            status = workspace.pi.harness_status or {}
        models = [{**model, "family": family_of(model["provider"], model["id"])} for model in status.get("models", []) if isinstance(model, dict)]
        return status, models

    @app.get("/api/v1/campaigns/{campaign_id}/agents/models")
    def agent_models(campaign_id: str):
        """Models a researcher may choose in dev mode. An agent may switch only within its own family."""
        from optimization_framework.agents.controller import dev_profile
        workspace.store.get(campaign_id, "campaign")
        status, models = harness_models()
        config = workspace.pi.configuration(campaign_id) or {}
        return {"mode": "dev" if dev_profile() else "locked", "default": (config.get("models") or {}).get("default"),
                "providers": status.get("providers", {}), "models": models}

    def tier_view(status=None, models=None):
        from optimization_framework.agents.controller import dev_profile, profile_defaults
        from optimization_framework.agents.tiers import ASSIGNABLE, load
        if models is None:
            status, models = harness_models()
        return {"mode": "dev" if dev_profile() else "locked", **load(workspace.store, profile_defaults()),
                "assignable": list(ASSIGNABLE), "providers": (status or {}).get("providers", {}), "models": models,
                "housekeeping": housekeeping.status(workspace)}

    @app.post("/api/v1/providers/login")
    def provider_login():
        """Start the harness's device sign-in to OpenAI (the ChatGPT subscription, provider openai-codex): a URL and a code; tokens stay on the host."""
        started = workspace.pi.client.request("POST", "/v1/auth/start", {})
        workspace.pi.harness_status = None   # the next status read sees the new sign-in
        return started

    @app.get("/api/v1/model-tiers")
    def model_tiers():
        return tier_view()

    @app.put("/api/v1/model-tiers")
    def save_model_tiers(values: dict):
        from optimization_framework.agents.controller import dev_profile
        from optimization_framework.agents.tiers import TierSettings, save
        if not dev_profile():
            raise ValueError("Model tiers can be changed only when the Pi harness runs a dev profile")
        settings = TierSettings.model_validate(values)
        status, models = harness_models()
        workspace.pi.harness_status = status
        for tier in settings.tiers:
            workspace.pi._check_available(tier.model.model_dump(exclude={"schema_version"}))
        with workspace.lock, workspace.store.transaction():
            record = save(workspace.store, settings)
            applied = workspace.pi.apply_tiers(record)
        return {**tier_view(status, models), "applied": applied}

    @app.get("/api/v1/llm-usage")
    def llm_usage(campaign_id: str, since: str | None = None, bucket: str = "hour"):
        from optimization_framework.agents import usage
        campaign = workspace.store.get(campaign_id, "campaign")
        if bucket not in usage.BUCKETS:
            raise HTTPException(422, "bucket must be hour or day")
        config = workspace.pi.configuration(campaign_id) or {}
        summary = usage.summary(workspace.store, campaign_id, since=since, bucket=bucket)
        agent_charged = usage.charged(workspace.store, campaign_id)
        implementation = workspace.implementations.api_committed(campaign_id)
        summary["budget"] = {"cap_usd": campaign.get("llm_budget_usd"), "agent_charged_usd": agent_charged,
            "implementation_committed_usd": implementation, "spent_usd": agent_charged + implementation}
        summary["family"] = config.get("llm_family")
        summary["agents"] = {a["id"]: {"role": a["role"], "status": a["status"], "provider": a.get("provider"),
            "model": a["model"], "effort": a.get("reasoning_effort")} for a in workspace.store.list("agent_session", campaign_id)}
        return summary

    @app.get("/api/v1/campaigns/{campaign_id}/agents/records/{record_id}")
    def agent_record(campaign_id: str, record_id: str):
        from optimization_framework.agents.tools import READ_KINDS
        entry = workspace.store.get_entry(record_id)
        if entry["kind"] not in READ_KINDS or entry["data"].get("campaign_id") != campaign_id:
            raise HTTPException(404, "Agent evidence is not in this campaign")
        return entry

    @app.post("/api/v1/campaigns/{campaign_id}/agents/login")
    def login(campaign_id: str):
        workspace.store.get(campaign_id, "campaign")
        return workspace.pi.client.request("POST", "/v1/auth/start", {})

    @app.get("/api/v1/campaigns/{campaign_id}/guidance")
    def guidance(campaign_id: str):
        return {"state": workspace.memory.state(campaign_id), "notes": workspace.store.list("manager_note", campaign_id)[-50:]}

    @app.get("/api/v1/campaigns/{campaign_id}/models")
    def campaign_models(campaign_id: str):
        return workspace.models.view(campaign_id)
