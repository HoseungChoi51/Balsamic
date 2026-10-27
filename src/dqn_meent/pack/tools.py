"""MEENT's agent tools and commands (roadmap N4): test designs and their evaluation at several fidelities.

``mask_create`` makes a full-sized binary design without putting every cell in the model's context; ``fixed_mask.run``
evaluates saved designs at the fidelities asked for, outside optimizer runs. The pack registers them, and the core offers
them only in campaigns on MEENT's problems. Their records keep their kinds (``agent_artifact`` of kind ``mask``,
``fixed_mask_job``, ``fixed_mask_report``) and the core's diagnostics runner (``agents/diagnostics.py``) runs the jobs, so
earlier campaigns read as before.
"""
from pydantic import Field

from optimization_framework.agents.models import ROLES
from optimization_framework.agents.roles import ROLE_BRIEFS
from optimization_framework.agents.tools import EXTRA_TOOLS, S, obj, register_page_operation, register_tool
from optimization_framework.campaigns.compute_consent import declare
from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.evaluation.registry import problems
from optimization_framework.storage.sqlite import now

PACKAGE = __package__
# Every agent that had the tool before the pack held it: all but the specialists, whose role files list their tools.
ROLES_WITH_MASKS = tuple(role for role in ROLES if role not in ROLE_BRIEFS)
MASK_CREATE = ("Create a reproducible full-sized binary diagnostic mask without putting every cell in model context.",
               obj({"task_id": S, "pattern": {"enum": ["zeros", "ones", "stripes_x", "stripes_y", "seeded_random"]},
                    "seed": {"type": "integer", "minimum": 0}, "fill_fraction": {"type": "number", "minimum": 0, "maximum": 1}},
                   ["task_id", "pattern"]))


class FixedMaskInput(Contract):
    task_id: str
    mask_artifact_ids: list[str] = Field(min_length=1, max_length=20)
    fidelities: list[dict] = Field(min_length=1, max_length=8)
    repeats: int = Field(default=2, ge=1, le=4)
    wall_seconds: float = Field(default=60, gt=0, le=86400)
    rationale: str = Field(min_length=1, max_length=5000)


def register_agent_tools(workspace):
    """The pack's agent tools; process-wide, so a second workspace finds them registered."""
    if "mask_create" not in EXTRA_TOOLS:
        register_tool("mask_create", *MASK_CREATE, mask_create, roles=ROLES_WITH_MASKS, pack=PACKAGE, local=True)


def register_operations(workspace):
    """``fixed_mask.run`` on this workspace's command bus, run by the experiment operator."""
    workspace.commands.register("fixed_mask.run", lambda command, actor: reserve(workspace, command.campaign_id, dict(command.payload), command.id),
                                model=FixedMaskInput, delegable=True, pack=PACKAGE)
    register_page_operation("fixed_mask.run", "experiment_operator", pack=PACKAGE, purpose="fixed_mask_diagnostics")
    declare("fixed_mask.run", 60, "a fixed-mask run")


def mask_create(tools, agent, run, args, identity):
    import numpy as np
    task = tools.record(agent, args["task_id"])
    instance = ProblemInstance.model_validate(task["problem"])
    n = instance.candidate_schema.dimensions
    pattern = args["pattern"]
    fraction = args.get("fill_fraction", .5)
    if pattern in {"zeros", "ones"}:
        mask = np.full(n, int(pattern == "ones"))
    elif pattern == "seeded_random":
        mask = (np.random.default_rng(args.get("seed", 0)).random(n) < fraction).astype(int)
    else:
        x, y = instance.configuration.get("grid_x"), instance.configuration.get("grid_y")
        if not x or not y or x * y != n:
            raise ValueError("Stripe masks require a declared grid_x by grid_y binary problem")
        yy, xx = np.indices((y, x))
        mask = ((xx if pattern == "stripes_x" else yy) < round((x if pattern == "stripes_x" else y) * fraction)).astype(int).ravel()
    candidate = instance.candidate_schema.canonicalize(mask.tolist())
    result = tools._execute(agent, run, "artifact_save", {"title": "Fixed mask: " + pattern, "kind": "mask",
        "content": {"mask": candidate, "generator": args, "problem_identity": instance.evaluation_identity},
        "evidence_ids": [args["task_id"]]}, identity)
    return {**result, "dimensions": n, "ones": int(mask.sum()), "pattern": pattern}


def reserve(workspace, campaign_id, payload, command_id):
    values = FixedMaskInput.model_validate(payload)
    campaign = workspace.store.get(campaign_id, "campaign")
    if values.wall_seconds > campaign["delegated_trial_seconds"]:
        raise ValueError("Fixed-mask diagnostic exceeds the delegated per-job allowance")
    task = workspace.store.get(values.task_id, "task")
    if task["campaign_id"] != campaign_id or task.get("split", "development") != "development":
        raise ValueError("Fixed-mask diagnostics require a development task in this campaign")
    if not workspace.evaluators.readiness(task)["runnable"]:
        raise ValueError("The selected evaluator is not runnable")
    instance = ProblemInstance.model_validate(task["problem"])
    adapter = problems.get(instance.definition_id)
    fixtures = []
    for identity in values.mask_artifact_ids:
        artifact = workspace.store.get(identity, "agent_artifact")
        if artifact["campaign_id"] != campaign_id or artifact["kind"] != "mask":
            raise ValueError("Choose an immutable mask artifact in this campaign")
        content = artifact["content"]
        candidate = instance.candidate_schema.canonicalize(content["mask"] if isinstance(content, dict) else content)
        fixtures.append({"artifact_id": identity, "artifact_hash": artifact["content_hash"], "candidate": candidate})
    instances = [adapter.resolve(instance.configuration, fidelity).model_dump(mode="json") for fidelity in values.fidelities]
    workspace._check_allocation(campaign, values.wall_seconds)
    record = {"id": "fixed_mask_" + command_id, "campaign_id": campaign_id, "status": "queued", "created_at": now(),
        "task_id": task["id"], "request": values.model_dump(mode="json"), "instances": instances, "fixtures": fixtures,
        "wall_seconds": values.wall_seconds, "execution_seconds": 0,
        "identity": content_hash([instances, fixtures]), "scope": "Development evaluator diagnostics; no optimizer performance or independent-solver claim."}
    workspace.store.put("fixed_mask_job", record, "fixed_mask.queued")
    return {"job_id": record["id"], "status": "queued"}
