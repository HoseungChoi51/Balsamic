"""Authenticated callbacks of the Pi harness: tool manifests, each turn's state block, tool calls, extension receipts and dialogs,
and run notices. (The implementation-grant assignments went with their roles in roadmap H8.)"""
import hmac

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

from optimization_framework.agents.client import service_token
from optimization_framework.agents.tools import PiTools
from optimization_framework.problem_import.service import is_import_agent


class Context(BaseModel):
    agent_id: str
    run_id: str


class ToolCall(Context):
    call_id: str
    name: str
    arguments: dict = Field(default_factory=dict)


class ExternalReceipt(Context):
    call_id: str
    tool: str = Field(max_length=200)
    extension: str = Field(default="", max_length=200)
    arguments: dict = Field(default_factory=dict)
    result_excerpt: str = ""
    result_bytes: int = Field(default=0, ge=0)
    is_error: bool = False
    annotations: dict | None = None


class UiRequest(Context):
    request_id: str = Field(min_length=1, max_length=200)
    method: str
    title: str = ""
    message: str | None = None
    options: list[str] | None = None
    placeholder: str | None = None
    prefill: str | None = None
    timeout_ms: float | None = Field(default=None, ge=0)


class Notice(BaseModel):
    agent_ids: list[str] = Field(max_length=1000)


def install(app, workspace):
    gateway = PiTools(workspace.pi)
    workspace.pi_tools = gateway

    def authenticate(authorization: str = Header(default="")):
        try:
            expected = "Bearer " + service_token()
        except (ValueError, OSError):
            raise HTTPException(503, "Pi connection is not configured") from None
        if not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "Pi service authentication required")

    @app.post("/api/internal/pi/manifest", dependencies=[Depends(authenticate)])
    def manifest(body: Context):
        # Formulators are Pi agents without a campaign; they have their own tools.
        if is_import_agent(body.agent_id):
            return workspace.problem_imports.manifest(body.agent_id, body.run_id)
        return gateway.manifest(body.agent_id, body.run_id)

    @app.post("/api/internal/pi/turn_state", dependencies=[Depends(authenticate)])
    def turn_state(body: Context):
        # Asked right before each prompt; formulators have no campaign state to tell.
        if is_import_agent(body.agent_id):
            return {"text": ""}
        return gateway.turn_state(body.agent_id, body.run_id)

    @app.post("/api/internal/pi/external_receipt", dependencies=[Depends(authenticate)])
    def external_receipt(body: ExternalReceipt):
        # What an extension tool did, receipted like a gateway call (agent-harness/src/gateway-extension.ts).
        return gateway.external_receipt(**body.model_dump())

    @app.post("/api/internal/pi/ui_request", dependencies=[Depends(authenticate)])
    def ui_request(body: UiRequest):
        # An extension's dialog becomes a question to the researcher; the harness polls the route below for the answer.
        return gateway.ui_request(**body.model_dump())

    @app.api_route("/api/internal/pi/ui_request/{question_id}", methods=["GET", "POST"], dependencies=[Depends(authenticate)])
    def ui_state(question_id: str, agent_id: str | None = None, body: Context | None = None):
        return gateway.ui_state(body.agent_id if body else agent_id, question_id)

    @app.post("/api/internal/pi/notify", dependencies=[Depends(authenticate)])
    def notify(body: Notice):
        # A hint only: the controller pulls the agents' authoritative state.
        imports = [agent_id for agent_id in body.agent_ids if is_import_agent(agent_id)]
        if imports:
            workspace.problem_imports.notify(imports)
        return workspace.pi.notify([agent_id for agent_id in body.agent_ids if not is_import_agent(agent_id)])

    @app.post("/api/internal/pi/tool", dependencies=[Depends(authenticate)])
    def tool(body: ToolCall):
        if is_import_agent(body.agent_id):
            return workspace.problem_imports.call(**body.model_dump())
        return gateway.call(**body.model_dump())
