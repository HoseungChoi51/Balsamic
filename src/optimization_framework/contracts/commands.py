"""Durable application commands; actor authority is supplied by the caller boundary."""
from typing import Any, Literal
import re
from pydantic import Field, model_validator, field_validator

from .base import Contract
from .requests import CampaignUpdate, ControlInput, ValidationInput, ReviewInput, DecisionInput
from optimization_framework.implementations.models import EvaluatorSpec, EvaluatorPackage, EvaluatorCheckSpec, OptimizerCheckSpec
from optimization_framework.agents.development_ticket import TicketInput

Operation = Literal["agent.activate", "agent.message", "agent.control", "agent.rollback", "agent.configure", "agent.question_dismiss", "agent.ui_respond", "fixed_mask.run", "campaign.create", "campaign.update", "campaign.adopt_problem", "context.edit", "issue.resolve", "issue.reopen", "trial.create", "trial.control", "trial.extension_request", "trial.validate", "draft.save", "draft.launch", "reproduction.draft", "reproduction.compare", "study.create", "study.nominate", "finalist.set", "study.freeze_template", "study.activate", "study.race.create", "study.race.control", "study.race.decide", "validation.run", "validation.require", "validation.execute", "validation.waive",
    "asset.snapshot",
    "validation.revoke_waiver", "inference.run", "asset.reuse", "asset.import_reference_set", "cost.reconcile", "comparison.report", "finding.record", "implementation.commission",
    "implementation.reference", "implementation.bind_builtin", "implementation.attach", "evaluator.commission", "evaluator.attach", "implementation.control", "implementation.revalidate", "implementation.reuse", "implementation.resolve_runtime", "bundle.export", "bundle.inspect", "bundle.publish", "decision.resolve", "source.record", "source.ingest", "hypothesis.create", "hypothesis.review", "hypothesis.status", "hypothesis.nominate", "literature.search", "confirmation.schedule", "confirmation.validate", "confirmation.release",
    "runtime.profile", "evaluator.equivalence", "trial.continue", "journal.compact", "journal.compaction_request", "approval.request", "workers.set", "experiments.rules", "trial.hide", "resources.plan", "resources.estimate",
    # The chat-centred workspace (docs/ui-workspace.md): threads, the problem note, graph interventions, autopilot, the library.
    "thread.fork", "thread.rename", "thread.park", "thread.unpark", "thread.pin", "thread.merge_draft", "thread.merge",
    "hypothesis.allocate", "hypothesis.edit", "intervention.batch", "research.generate", "problem_note.revise", "problem_note.adopt", "problem_note.skip", "problem_note.unskip", "note.ask", "note.resolve",
    "autopilot.set", "library.publish", "library.apply", "campaign.stage_pin",
    # The researcher closes a request's mandate from the chat (roadmap R7).
    "mandate.close"]


class CommandOrigin(Contract):
    """Where a command came from: the thread and message of the conversation, and who acted. Shown on every page.
    balsamic is Balsamic's own system actor (decision 6), acting after an install or, for a planned run, under the compute
    consent it names (consent_id) and the mandate that consent is the compute part of (mandate_id, R3)."""
    thread_id: str | None = None
    message_id: str | None = None
    actor: Literal["researcher", "lead", "page_agent", "autopilot", "balsamic"] = "researcher"
    agent_id: str | None = None
    run_id: str | None = None
    rationale: str | None = Field(default=None, max_length=5000)
    consent_id: str | None = None
    mandate_id: str | None = None


class Command(Contract):
    id: str = Field(min_length=1, max_length=160, pattern=r"^[a-zA-Z0-9_-]+$")
    campaign_id: str
    operation: Operation
    expected_revision: int = Field(ge=0)
    expected_guidance_revision: int | None = Field(default=None, ge=0)
    expected_authority_hash: str | None = None
    proposal_digest: str | None = None
    # The thread whose guidance this command was prepared under (M1): a message in another thread does not stale it.
    expected_thread_revision: int | None = Field(default=None, ge=0)
    origin: CommandOrigin | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def campaign_precondition(self):
        if self.operation == "campaign.create":
            if self.expected_revision != 0:
                raise ValueError("Campaign creation requires revision zero (the campaign must be absent)")
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", self.campaign_id):
                raise ValueError("Choose a stable campaign identity using letters, digits, hyphens or underscores")
            if self.expected_guidance_revision is not None or self.expected_authority_hash is not None:
                raise ValueError("A new campaign has no existing guidance or delegated authority")
        elif self.expected_revision < 1:
            raise ValueError("This command requires an existing campaign revision")
        return self


class CampaignUpdateInput(CampaignUpdate):
    rationale: str = Field(default="Researcher revised the campaign charter", min_length=1, max_length=5000)


class ProblemAdoptionInput(Contract):
    """The campaign's tasks adopt the problem an installed library provides for its charter's declared problem (roadmap E4)."""
    install_id: str = Field(min_length=1, max_length=200, description="The library install that provides the charter's declared problem")
    rationale: str = Field(default="The installed library provides the charter's declared problem", min_length=1, max_length=5000)


class FinalistSetInput(Contract):
    """A revisable researcher shortlist, separate from a frozen nomination."""
    study_id: str
    trial_ids: list[str] = Field(default_factory=list, max_length=500)
    label: str | None = Field(default=None, max_length=200)
    expected_revision: int | None = Field(default=None, ge=0)
    expected_procedure_ids: dict[str, str] = Field(default_factory=dict)


class TrialControlInput(ControlInput):
    trial_id: str
    expected_control_revision: int = Field(ge=0)


class TrialExtensionRequestInput(Contract):
    """The lead's request for more trial budget; only the researcher can approve it."""
    trial_id: str
    additional_seconds: float = Field(gt=0, le=86400)
    additional_evaluations: int = Field(default=0, ge=0, le=10000000)
    rationale: str = Field(min_length=1, max_length=5000, description="Why the extra budget would change a decision")


class TrialValidationInput(ValidationInput):
    trial_id: str


class ResearchControlInput(Contract):
    run_id: str
    action: Literal["stop", "resume"]
    expected_control_revision: int = Field(ge=0)


class ResearchRetryInput(Contract):
    """Retry the exact saved question only when no model run was dispatched."""
    manager_command_id: str = Field(min_length=1, max_length=200)


class DecisionResolveInput(DecisionInput):
    decision_id: str
    expected_resolution_revision: int = Field(ge=0)


class DecisionRefreshItem(Contract):
    decision_id: str
    expected_resolution_revision: int = Field(ge=0)
    desired_choice: str | None = Field(default=None, min_length=1, max_length=200)
    comment: str = Field(default="", max_length=20000)


class DecisionRefreshInput(Contract):
    decisions: list[DecisionRefreshItem] = Field(min_length=1, max_length=50)
    comment: str = Field(default="", max_length=20000)
    max_parallel_reviews: int = Field(default=3, ge=1, le=8)
    retry_run_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def distinct_decisions(self):
        if len({item.decision_id for item in self.decisions}) != len(self.decisions):
            raise ValueError("Select each decision only once")
        return self


class SourceRecordInput(Contract):
    title: str = Field(min_length=1, max_length=1000)
    url: str = Field(min_length=1, max_length=2000)
    excerpt: str = Field(default="", max_length=20000)
    supports: str = Field(default="", max_length=5000)

    @field_validator("url")
    @classmethod
    def http_source(cls, value):
        from urllib.parse import urlparse
        if urlparse(value).scheme not in {"https", "http"}:
            raise ValueError("Source URL must use HTTP or HTTPS")
        return value


class SourceIngestInput(Contract):
    identifier: str = Field(min_length=1, max_length=2000)


class InferenceRunInput(Contract):
    trial_id: str
    asset_id: str
    adapter_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+:v[1-9][0-9]*$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int = Field(ge=0, lt=2**32)
    reuse_decision_ids: list[str] = Field(min_length=1)
    wall_seconds: float = Field(default=120, gt=0, le=86400)


class ComparisonReportInput(Contract):
    study_id: str | None = None
    trial_ids: list[str] | None = Field(default=None, min_length=1, max_length=200, description="Compare only these experiments. "
        "Methods are compared at the largest cost every compared run reached, so name the long runs to compare them with each other: "
        "a short run in the same study would otherwise set that cost. A continued run is named by its last experiment.")
    cost_axis: Literal["worker_seconds", "full_worker_seconds", "evaluation_requests", "solver_executions"] | None = None
    cost_view: Literal["full_attributed_cost", "actual_expenditure"] = "full_attributed_cost"


class HypothesisReviewInput(ReviewInput):
    hypothesis_id: str


StopOutcome = Literal["implementation_invalid", "assumptions_incompatible", "configuration_unpromising", "under_evaluated",
                      "unaffordable_within_allocation", "adequately_assessed_deprioritized"]
STOP_OUTCOMES = StopOutcome.__args__
# The words a page shows for a stop. researcher_decision: the researcher stopped without an outcome; unspecified: stopped before outcomes existed.
STOP_WORDS = {"implementation_invalid": "implementation invalid", "assumptions_incompatible": "assumptions incompatible",
              "configuration_unpromising": "configuration unpromising", "under_evaluated": "under-evaluated",
              "unaffordable_within_allocation": "unaffordable within the allocation",
              "adequately_assessed_deprioritized": "adequately assessed, deprioritized",
              "researcher_decision": "researcher's decision", "unspecified": "no outcome recorded"}


class HypothesisStatusInput(Contract):
    hypothesis_id: str
    status: Literal["proposed", "investigating", "archived", "finalist"]
    expected_status_revision: int = Field(ge=0)
    # Why a strategy is stopped (archived): shown on the graph; stopped never reads as failed.
    stop_reason: str | None = Field(default=None, max_length=2000)
    outcome: StopOutcome | None = Field(default=None, description="archived: what the stop concludes. An agent's stop needs one, with evidence_ids")
    evidence_ids: list[str] = Field(default_factory=list, max_length=50, description="archived: the campaign's records the stop rests on "
        "(trials, comparisons, validation results, reviews)")

    @model_validator(mode="after")
    def stop_fields_only_on_stop(self):
        if self.status != "archived" and (self.outcome or self.evidence_ids):
            raise ValueError("A stop outcome and its evidence go with status archived only")
        return self


class HypothesisNominateInput(Contract):
    hypothesis_id: str
    expected_status_revision: int | None = Field(default=None, ge=0)


class ContextEditInput(Contract):
    content: str = Field(min_length=1, max_length=49152)
    expected_revision: int = Field(ge=0)
    reason: str = Field(default="Researcher edited campaign memory", min_length=1, max_length=2000)


class IssueResolveInput(Contract):
    issue_id: str
    expected_revision: int = Field(ge=1)
    choice: Literal["resolved", "deferred", "action"] = Field(description="resolved and deferred only mark the issue; action carries out one the issue offers. "
        "An agent chooses resolved only, for an issue whose condition no longer holds")
    action: str | None = Field(default=None, max_length=100, description="action: the id of one of the issue's actions")
    comment: str = Field(default="", max_length=20000, description="An agent says here what superseded or fixed the issue; the researcher reads it and can reopen the issue")

    @model_validator(mode="after")
    def action_named(self):
        if (self.choice == "action") != (self.action is not None):
            raise ValueError("Name an action exactly when choosing action")
        return self


class IssueReopenInput(Contract):
    issue_id: str


class ReuseInput(Contract):
    asset_id: str
    study_id: str
    decision: Literal["reuse", "decline", "reference"]
    intended_use: Literal["optimizer_input", "manager_evidence", "procedure"]
    rationale: str = Field(min_length=1)
    consequences: dict[str, Any] = Field(default_factory=dict)


class AssetSnapshotInput(Contract):
    trial_id: str
    observation_id: str


class RuntimeProfileInput(Contract):
    """Measure a task's evaluator on this host: short random-search probes at 1, 2, 4... workers."""
    task_id: str
    probe_seconds: float = Field(default=30, ge=5, le=600)
    max_evaluations: int = Field(default=2000, ge=10, le=100000)
    warmup_evaluations: int = Field(default=2, ge=0, le=100)


class EquivalenceInput(Contract):
    """Replay a sample of a finished experiment's recorded candidates under the current source and compare the results."""
    trial_id: str
    sample: int = Field(default=12, ge=1, le=64)
    absolute_tolerance: float = Field(default=1e-9, ge=0, le=1)
    relative_tolerance: float = Field(default=1e-9, ge=0, le=1)
    wall_seconds: float = Field(default=120, gt=0, le=86400)


class TrialContinueInput(Contract):
    """Go on from where a finished experiment stopped, as a new experiment under the current source."""
    trial_id: str
    wall_seconds: float = Field(gt=0, le=86400)
    max_steps: int | None = Field(default=None, ge=1, le=10000000)
    accept_unverified: bool = False
    device: Literal["cuda", "cpu"] | None = Field(default=None, description="where the new experiment computes; the stopped one's device when omitted")


class JournalCompactInput(Contract):
    """Remove the evaluated designs from finished experiments' journals. Rows and numbers stay; what is removed cannot be brought back."""
    trial_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)
    study_id: str | None = Field(default=None, description="Without trial_ids: every finished experiment of this study, or of the campaign when omitted.")


class JournalCompactionRequestInput(JournalCompactInput):
    """Ask the researcher to approve a compaction, once the experiments' results have been analysed and recorded."""
    rationale: str = Field(min_length=1, max_length=4000)


LIMITS = ("compute_budget_seconds", "llm_budget_usd", "delegated_trial_seconds", "implementation_compute_budget_seconds", "validation_reserve_seconds",
          "compute_notice_seconds", "compute_gate_seconds")


class PlannedRun(Contract):
    """One planned experiment of a compute request: the researcher sees its speed, outputs and disk use measured on earlier
    runs of the same problem (campaigns/experiment_plan.py)."""
    task_id: str
    hypothesis_id: str | None = None
    algorithm: str | None = Field(default=None, max_length=200, description="the method id, when no hypothesis names it")
    seeds: list[int] = Field(min_length=1, max_length=64)
    wall_seconds: float = Field(gt=0, le=604800, description="each run's wall time")
    max_evaluations: int | None = Field(default=None, ge=1, le=100000000)
    device: Literal["cuda", "cpu"] | None = None


# A host a coding workspace may reach (agents/development.py), as a lowercase DNS name.
HOSTNAME = r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"


class StopCondition(Contract):
    """When a request's work is done: in words, and optionally a condition the code can check (a mandate's, contracts/mandates.py)."""
    text: str = Field(min_length=1, max_length=2000)
    machine: Literal["all_runs_terminal"] | None = None


class ApprovalRequestInput(Contract):
    """Ask the researcher for something only they grant. On approval it is applied as the researcher's own command; a mandate
    (an agent's, with mandate_propose) is the go-ahead for a request's work beyond Explore (campaigns/mandates.py). Kind compute,
    the go-ahead for a plan of work alone (campaigns/compute_consent.py), stays for requests filed before mandates."""
    kind: Literal["campaign_limits", "waiver", "worker_ceiling", "compute", "mandate"]
    rationale: str = Field(min_length=1, max_length=5000, description="What the change makes possible and the measurement behind it")
    limits: dict[str, float] = Field(default_factory=dict, description="campaign_limits: the new value of each limit to change, among " + ", ".join(LIMITS))
    requirement_id: str | None = Field(default=None, description="waiver: the validation requirement to waive")
    evidence_ids: list[str] = Field(default_factory=list, max_length=50, description="waiver: the measurements the researcher should judge it by")
    workers: int | None = Field(default=None, ge=1, le=64, description="worker_ceiling: experiments that may run at once on this server")
    gpu_workers: int | None = Field(default=None, ge=0, le=63, description="worker_ceiling: how many of them run on the GPU (unchanged when omitted)")
    plan: str | None = Field(default=None, min_length=1, max_length=5000, description="compute: what will run (each run, profile, job or coding workspace) and why")
    wall_seconds: float | None = Field(default=None, gt=0, le=604800, description="compute: how long until the researcher has the results")
    worker_seconds: float | None = Field(default=None, gt=0, le=2419200, description="compute: the worker time the plan may use in all")
    coding_workspaces: int = Field(default=0, ge=0, le=10, description="compute: coding workspaces the plan opens")
    hypothesis_ids: list[str] = Field(default_factory=list, max_length=50, description="compute: the proposals the plan is for. "
        "The go-ahead then covers only their workspaces, runs and commissions, with those its runs name; work for no proposal is "
        "covered in this request only. A plan that names none covers any work in the campaign")
    egress_hosts: list[str] = Field(default_factory=list, max_length=20, description="mandate, compute: hosts its coding workspaces may reach "
        "beyond their model and the package index (lowercase DNS names); the researcher approves them with the plan")
    meanwhile: str | None = Field(default=None, min_length=1, max_length=2000, description="compute: what the researcher can do while it runs")
    runs: list[PlannedRun] = Field(default_factory=list, max_length=50, description="compute for experiments: each planned experiment, "
        "so the researcher reads the plan (speed, evaluations, outputs and disk use, measured on earlier runs) before approving")
    template: Literal["screen", "run_campaign"] | None = Field(default=None, description="mandate: the template asked for")
    model_usd: float | None = Field(default=None, ge=0, le=10000, description="mandate: the model-spend envelope")
    deadline_minutes: float | None = Field(default=None, gt=0, le=40320, description="mandate: minutes from the approval to its deadline")
    stop_when: StopCondition | None = Field(default=None, description="mandate: when the request's work is done")

    @model_validator(mode="after")
    def one_request(self):
        given = {"campaign_limits": bool(self.limits), "waiver": self.requirement_id is not None, "worker_ceiling": self.workers is not None,
                 "compute": self.plan is not None and self.template is None, "mandate": self.template is not None}
        if not given[self.kind] or sum(given.values()) != 1:
            raise ValueError("Give exactly the fields of the chosen kind: limits, requirement_id with evidence_ids, workers, a compute plan, "
                             "or a mandate's template and plan")
        if self.kind == "compute" and (self.wall_seconds is None or self.worker_seconds is None or self.meanwhile is None):
            raise ValueError("A compute plan states wall_seconds, worker_seconds and what the researcher can do meanwhile")
        if self.kind == "mandate" and (self.plan is None or self.worker_seconds is None):
            raise ValueError("A mandate states its plan and the worker_seconds of its envelope")
        if (self.runs or self.hypothesis_ids or self.egress_hosts) and self.kind not in {"compute", "mandate"}:
            raise ValueError("Planned runs, the proposals a plan is for and the hosts its workspaces reach belong to a mandate or a compute request")
        if self.egress_hosts and not self.coding_workspaces:
            raise ValueError("egress_hosts are for the coding workspaces a plan opens: set coding_workspaces")
        import re
        bad = [host for host in self.egress_hosts if not re.fullmatch(HOSTNAME, host)]
        if bad:
            raise ValueError("egress_hosts: name each host by its lowercase DNS name, without scheme, port or path: " + ", ".join(bad))
        if (self.model_usd is not None or self.deadline_minutes is not None or self.stop_when is not None) and self.kind != "mandate":
            raise ValueError("A model-spend envelope, a deadline and a stop condition belong to a mandate")
        if set(self.limits) - set(LIMITS):
            raise ValueError("Unknown campaign limit: " + ", ".join(sorted(set(self.limits) - set(LIMITS))))
        if self.kind == "waiver" and not self.evidence_ids:
            raise ValueError("A waiver request names the measurements it rests on")
        return self


class WorkerCeilingInput(Contract):
    """How many experiments run at once on this server, and how many of them on the GPU (unchanged when omitted). Kept across
    restarts; the launcher's settings are only the defaults."""
    workers: int = Field(ge=1, le=64)
    gpu_workers: int | None = Field(default=None, ge=0, le=63)
    rationale: str = Field(min_length=1, max_length=5000)


class WaiverInput(Contract):
    requirement_id: str
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class WaiverRevocationInput(Contract):
    waiver_id: str
    rationale: str = Field(min_length=1)


class ExecuteValidationInput(Contract):
    requirement_id: str
    wall_seconds: float = Field(default=120, gt=0, le=86400)


class ConfirmationReleaseInput(Contract):
    protocol_id: str
    allow_incomplete: bool = False
    rationale: str = Field(default="The fixed protocol and required evidence are complete", min_length=1)


class ConfirmationScheduleInput(Contract):
    protocol_id: str
    reuse_decision_ids: list[str] = Field(default_factory=list)


class FindingLink(Contract):
    id: str = Field(min_length=1)
    relation: Literal["supports", "contradicts", "supersedes", "qualifies"]


class FindingInput(Contract):
    content: str = Field(min_length=1, max_length=20000)
    source_ids: list[str] = Field(min_length=1)
    # A promise says why something may work, evidence what was measured, a decision what was chosen and why.
    # Agents must say which; the researcher's findings without one read as unspecified.
    statement: Literal["promise", "evidence", "decision"] | None = None
    interpretation: Literal["observation", "interpretation", "researcher_endorsed", "counterevidence"] = "interpretation"
    problem_scope: str = Field(default="", max_length=4000)
    study_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    counterevidence_for: list[str] = Field(default_factory=list)
    links: list[FindingLink] = Field(default_factory=list, max_length=30)
    publish: bool = False

    @model_validator(mode="after")
    def reusable_scope(self):
        if self.publish and (not self.problem_scope.strip() or not self.limitations or not all(item.strip() for item in self.limitations)):
            raise ValueError("A reusable finding requires its problem scope and explicit limitations")
        if self.interpretation == "counterevidence" and not self.counterevidence_for and not any(link.relation == "contradicts" for link in self.links):
            raise ValueError("Counterevidence must name the earlier finding it qualifies")
        return self


class CommissionInput(Contract):
    hypothesis_id: str
    spec: dict[str, Any]
    compute_seconds: float = Field(gt=0, le=86400)
    max_calls: int = Field(default=12, ge=1, le=20)
    api_budget_usd: float = Field(default=0, ge=0, le=10000)
    package: dict[str, Any] | None = None
    service_idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    # A commission that opens a headless coding box (roadmap H7): acceptance tests the coding agent sees, and the protected ones
    # its commissioner writes outside the box, which it never does (agents/development_commission.py).
    ticket: TicketInput | None = None


class AttachInput(Contract):
    hypothesis_id: str
    version_id: str


class EvaluatorCommissionInput(Contract):
    task_id: str
    spec: EvaluatorSpec
    compute_seconds: float = Field(gt=0, le=86400)
    max_calls: int = Field(default=12, ge=1, le=20)
    api_budget_usd: float = Field(default=0, ge=0, le=10000)
    package: EvaluatorPackage | None = None
    ticket: TicketInput | None = None


class EvaluatorAttachInput(Contract):
    task_id: str
    version_id: str
    rationale: str = Field(min_length=1, max_length=5000)


class ImplementationControlInput(Contract):
    grant_id: str
    action: Literal["cancel", "resume", "close_uncertain"]


class RevalidationInput(Contract):
    version_id: str
    checks: EvaluatorCheckSpec | OptimizerCheckSpec
    compute_seconds: float = Field(default=120, gt=0, le=86400)


class RuntimeResolutionInput(Contract):
    version_id: str


class ExecutableReuseInput(Contract):
    version_id: str
    study_id: str
    hypothesis_id: str | None = None
    task_id: str | None = None
    decision: Literal["reuse", "decline"]
    rationale: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def target(self):
        if bool(self.hypothesis_id) == bool(self.task_id):
            raise ValueError("Select exactly one optimizer idea or evaluator problem for this decision")
        return self


class SearchInput(Contract):
    query: str = Field(min_length=2, max_length=500)
    provider: Literal["arxiv", "crossref"] = "crossref"
    limit: int = Field(default=5, ge=1, le=10)
