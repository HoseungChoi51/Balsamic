"""A mandate: what one researcher request allows (roadmap Phase 3, decision 10). For that request, the classes of work allowed,
the proposals, coding workspaces and runs it names, a compute and model-spend envelope, a deadline and a stop condition.
The records and their templates are in campaigns/mandates.py."""
from typing import Literal

from pydantic import Field, model_validator

from .base import Contract
from .commands import PlannedRun, StopCondition

MandateClass = Literal["answer", "propose", "review", "reuse", "implement", "run", "validate", "decide", "record", "configure", "ask"]
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


class MessageMandate(Contract):
    """The mandate the researcher grants with a message (R7, the dial in the chat): the request the message opens works under it.
    Answer and Explore take their template's envelope; Screen and Run the campaign are the researcher's go-ahead, with an envelope
    (worker time, coding workspaces, model spend) and optionally a deadline and the proposals it is for."""
    template: TemplateName
    worker_seconds: float | None = Field(default=None, gt=0, le=2419200, description="screen, run_campaign: the worker time it may use in all")
    coding_workspaces: int = Field(default=0, ge=0, le=10, description="screen, run_campaign: coding workspaces it may open")
    model_usd: float | None = Field(default=None, ge=0, le=10000, description="screen, run_campaign: the model-spend envelope; none sets none")
    deadline_minutes: float | None = Field(default=None, gt=0, le=40320, description="screen, run_campaign: minutes from the message to its deadline")
    hypothesis_ids: list[str] = Field(default_factory=list, max_length=50, description="screen, run_campaign: the proposals it is for; none names no limit")

    @model_validator(mode="after")
    def envelope(self):
        if self.template in {"screen", "run_campaign"}:
            if self.worker_seconds is None:
                raise ValueError("A Screen or Run the campaign mandate states the worker time of its envelope")
        elif self.worker_seconds is not None or self.coding_workspaces or self.model_usd is not None or self.deadline_minutes is not None or self.hypothesis_ids:
            raise ValueError("Answer and Explore take their template's envelope: give no worker time, coding workspaces, model spend, "
                             "deadline or proposals")
        return self


class MandateCloseInput(Contract):
    """The researcher closes a mandate (R7): new work under it is refused, work already running goes on."""
    mandate_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="Closed by the researcher", min_length=1, max_length=2000)
