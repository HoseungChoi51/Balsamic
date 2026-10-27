"""A mandate: what one researcher request allows (roadmap Phase 3, decision 10). For that request, the classes of work allowed,
the proposals, coding workspaces and runs it names, a compute and model-spend envelope, a deadline and a stop condition.
The records and their templates are in campaigns/mandates.py."""
from typing import Literal

from pydantic import Field

from .base import Contract
from .commands import PlannedRun, StopCondition

MandateClass = Literal["answer", "propose", "review", "implement", "run", "validate", "decide", "record", "configure", "ask"]
TemplateName = Literal["answer", "explore", "screen", "run_campaign"]
MandateStatus = Literal["proposed", "active", "exhausted", "expired", "closed"]


class RequestRoot(Contract):
    """The researcher's request a mandate serves, as the controller's request_root() gives it."""
    thread_id: str
    message_id: str | None = None
    run_id: str | None = None


class MandateCompute(Contract):
    worker_seconds: float = Field(ge=0)
    coding_workspaces: int = Field(default=0, ge=0)


class MandateUse(Contract):
    worker_seconds: float = Field(default=0.0, ge=0)
    coding_workspaces: int = Field(default=0, ge=0)
    model_usd: float = Field(default=0.0, ge=0)


class Mandate(Contract):
    id: str
    campaign_id: str
    root: RequestRoot | None = Field(default=None, description="None: a standing mandate, for every request of the campaign")
    template: TemplateName
    classes: list[MandateClass]
    plan: str | None = Field(default=None, max_length=5000, description="What the request's work is, in words")
    hypothesis_ids: list[str] = Field(default_factory=list, description="The proposals it names; none names no limit on proposals")
    workspace_ids: list[str] = Field(default_factory=list)
    runs: list[PlannedRun] = Field(default_factory=list)
    compute: MandateCompute
    model_usd: float | None = Field(default=None, ge=0, description="The model-spend envelope; None sets none")
    deadline_at: str | None = None
    stop_when: StopCondition | None = None
    status: MandateStatus
    granted_by: str = Field(description="automatic, or the id of the researcher's decision")
    used: MandateUse = Field(default_factory=MandateUse)
    consent_id: str | None = Field(default=None, description="The compute consent that is its compute part, if any")
    created_at: str
