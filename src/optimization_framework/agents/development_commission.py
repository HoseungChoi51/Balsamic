"""Commissions run as headless coding boxes (roadmap H7), the one route that builds code (H8).

A commission (`implementation.commission` for a proposal's method, `evaluator.commission` for a task's evaluator) is a coding
workspace that Balsamic opens for the command bus once the bus has checked it against the request's go-ahead and mandate. Pi
runs in it headless (H2's adapter), on a work ticket (H4) that holds the commission's frozen specification, behind the walls of
any box (H5: the egress allowlist, the limits, and a deadline of the commission's compute time). What it delivers is a
submission like any other: Balsamic validates the exact commit outside the box (H6), installs it, binds the proposal to its
method or has the task adopt the problem the library provides (E5), and starts the approved runs.

The test designer's job survives as the author of the protected acceptance tests, written outside the box: the commission's
own (`ticket.protected_tests`, which its commissioner writes), and for an evaluator the independent numerical fixtures of its
specification (`correctness_cases`), which Balsamic writes as a pytest file. A commission needs at least one. They are kept on
the host with the box (`library_validation.protect`), run on every delivery, and the box sees their names only.

One log, one cost ledger, one contract: the box's timeline is the commission's history; its compute is the commission's
`compute_seconds`, which the bus charges to the go-ahead once (`campaigns/compute_consent.py`), and the box's wall time and its
validation are counted against it on the box, not charged again; and what it builds is a library.

A commission that cannot open a box is refused, saying what to do instead (refusal()): while coding workspaces are off (the
researcher turns them on), one that imports a package (deliver the code as a library from one's own coding session, or give it to
a coding workspace as reference code), and an evaluator for a task no charter declares (nothing would have the task adopt the
problem; attach a validated evaluator version instead). Since H8 nothing builds code in the implementation service: its jobs and
grants recorded before stay as they are, readable."""
from __future__ import annotations

import json

KINDS = {"implementation.commission": "implementation", "evaluator.commission": "evaluator"}
# The protected test Balsamic writes from an evaluator's independent fixtures.
FIXTURES = "test_commission_fixtures.py"
NEEDS_PROTECTED = ("A commission needs at least one protected acceptance test: the test designer's job, done outside the box. Write it "
                   "in ticket.protected_tests (a pytest file test_<name>.py and its source): it runs outside the box on every delivery, "
                   "and the coding agent sees its name and outcome only. The specification's behaviour, mechanism and diagnostic checks "
                   "are part of what the coding agent reads; they are not run as protected tests.")


PACKAGE = ("A commission builds its method in a coding box and imports no package (roadmap H8). To bring code you have, deliver it "
           "as a library from your own coding agent (Deliver from your own coding agent, on the workspace's card), or record it as "
           "reference code (implementation.reference) and open a coding workspace with it among its evidence_ids.")
UNDECLARED = ("This task's evaluator cannot be commissioned: only a problem the campaign's charter declares is built as a library and "
              "adopted by its tasks once installed, and this campaign's charter does not declare this task's. Attach a validated "
              "evaluator version (evaluator.attach), or make the campaign from a charter that declares the problem.")


def refusal(workspace, operation, payload):
    """Why a commission cannot open a coding box, as the text that says what to do instead; None when it can: coding workspaces on,
    a build (not a package import), and for an evaluator a task whose problem the campaign's charter declares."""
    payload = payload if isinstance(payload, dict) else {}
    development = workspace.pi.development
    if not development.enabled():
        return development.disabled()
    if payload.get("package"):
        return PACKAGE
    if operation == "evaluator.commission" and declared(workspace, payload.get("task_id")) is None:
        return UNDECLARED
    return None


def declared(workspace, task_id):
    """The task when the problem of its evaluator requirement is the one its campaign's charter declares: the library generated from
    the charter provides it, and Balsamic has the task adopt it once the library is installed. None otherwise."""
    try:
        task = workspace.store.get(task_id, "task")
        campaign = workspace.store.get(task["campaign_id"], "campaign")
    except (KeyError, TypeError):
        return None
    reference, manifest = campaign.get("charter"), task.get("evaluator_manifest") or {}
    if not reference or not manifest.get("id"):
        return None
    binding = workspace.charters.revision(reference["id"], reference["revision"])["charter"].get("evaluator") or {}
    return task if binding.get("kind") == "declared" and binding.get("problem_id") == manifest["id"] else None


def public(spec):
    """The frozen specification as the coding agent reads it: without its provenance (records it cannot read), the conditions the
    old service exposed, and an evaluator's independent fixtures, which stay outside the box."""
    hidden = {"provenance", "exposed_conditions", "correctness_cases", "schema_version"}
    return {key: value for key, value in spec.model_dump(mode="json").items() if key not in hidden}


def fixtures_test(spec):
    """An evaluator's independent numerical fixtures (`correctness_cases`) as a protected pytest file: each case's candidate is
    evaluated with the problem the library provides, and every objective it states must agree within the case's tolerances.
    None when the specification has none."""
    cases = [case.model_dump(mode="json") for case in getattr(spec, "correctness_cases", None) or []]
    if not cases:
        return None
    return FIXTURE_TEST.replace("__PROBLEM__", repr(spec.manifest.id)).replace("__CASES__", repr(json.dumps(cases)))


FIXTURE_TEST = '''"""The commission's independent numerical fixtures, written by Balsamic from its frozen specification (roadmap H7): a protected
acceptance test, run outside the coding box on every delivery."""
import json
import math
import tomllib
from importlib import import_module
from pathlib import Path

import pytest

PROBLEM = __PROBLEM__
CASES = json.loads(__CASES__)


def registry():
    """The lab's problems, with the ones this library provides (its pyproject's problem entry points)."""
    from optimization_framework.evaluation.registry import problems
    project = tomllib.loads((Path.cwd() / "pyproject.toml").read_text()).get("project") or {}
    found = problems
    for value in ((project.get("entry-points") or {}).get("optimization_framework.problems") or {}).values():
        module, factory = value.split(":", 1)
        found = found.extended(getattr(import_module(module), factory)())
    return found


@pytest.mark.parametrize("case", CASES, ids=[f"fixture_{index + 1}" for index in range(len(CASES))])
def test_the_evaluator_agrees_with_each_independent_fixture(case):
    found = registry()
    instance = found.resolve(PROBLEM, case["configuration"], case["fidelity"] or None)
    result = found.evaluator(instance).evaluate(case["candidate"])
    for name, expected in case["objectives"].items():
        assert math.isclose(float(result.objectives[name]), expected, rel_tol=case["relative_tolerance"],
                            abs_tol=case["absolute_tolerance"]), name
'''


def commission(workspace, command, actor):
    """Open the commission's headless box (the bus's implementation.commission and evaluator.commission, through
    ImplementationBridge.commission()), or refuse with refusal()'s reason. The outcome names the box and its ticket."""
    from optimization_framework.campaigns.compute_consent import request_root
    from optimization_framework.contracts.commands import CommissionInput, EvaluatorCommissionInput
    from optimization_framework.implementations.models import BoundOptimizerSpec, ImplementationSpec, digest
    from .development_ticket import TicketInput
    store, kind = workspace.store, KINDS[command.operation]
    if (why := refusal(workspace, command.operation, command.payload)) is not None:
        raise ValueError(why)
    task = hypothesis = None
    if kind == "evaluator":
        values = EvaluatorCommissionInput(**command.payload)
        spec, task = values.spec, store.get(values.task_id, "task")
        if task.get("archived") or not task.get("evaluator_requirement_id"):
            raise ValueError("Commission an evaluator against a current problem requirement")
        if spec.manifest.model_dump(mode="json") != store.get(task["evaluator_requirement_id"], "evaluator_requirement")["manifest"]:
            raise ValueError("Commissioned evaluator differs from the declared problem requirement")
        key = command.id
    else:
        values = CommissionInput(**command.payload)
        hypothesis = store.get(values.hypothesis_id, "hypothesis")
        if hypothesis["status"] in {"archived", "finalist"}:
            raise ValueError("Revive or fork this idea before commissioning implementation work")
        spec = (BoundOptimizerSpec if values.spec.get("evaluator_version_id") else ImplementationSpec).model_validate(values.spec)
        key = values.service_idempotency_key or command.id
    frozen = spec.model_dump(mode="json")
    workspace.implementations.check_self_contained(frozen)
    campaign = store.get(command.campaign_id, "campaign")
    if workspace.implementations.over_ceiling(campaign, values.compute_seconds):
        raise ValueError(f"This job would exceed the implementation ceiling the researcher set ({campaign['implementation_compute_budget_seconds']:g}s)")
    given = values.ticket or TicketInput()
    protected = {test.name: test.content for test in given.protected_tests}
    written = fixtures_test(spec)
    if written:
        if FIXTURES in protected:
            raise ValueError(f"{FIXTURES} is the protected test Balsamic writes from the specification's fixtures: name yours otherwise")
        protected[FIXTURES] = written
    if not protected:
        raise ValueError(NEEDS_PROTECTED)
    origin = command.origin
    asked = request_root(workspace, origin) if origin is not None else None
    opener = None
    if origin is not None and origin.agent_id:
        try:
            agent = store.get(origin.agent_id, "agent_session")
            opener = {"agent_id": agent["id"], "role": agent["role"]}
        except KeyError:
            pass
    entry = {"kind": kind, "operation": command.operation, "command_id": command.id, "key": key, "name": spec.name,
             "hypothesis_id": hypothesis["id"] if hypothesis else None, "task_id": task["id"] if task else None,
             "compute_seconds": values.compute_seconds, "max_calls": values.max_calls, "api_budget_usd": values.api_budget_usd,
             "spec_digest": digest(frozen), "spec": public(spec), "fixtures": len(getattr(spec, "correctness_cases", None) or []),
             "protected_tests": sorted(protected)}
    record = workspace.pi.development.open_commission(command.campaign_id, entry, TicketInput(acceptance_tests=given.acceptance_tests),
        protected, actor="researcher" if actor == "researcher" else "lead", opener=opener, asked=asked)
    return {"workspace_id": record["id"], "ticket_id": record["ticket_id"],
            **({"task_id": task["id"]} if task else {"hypothesis_id": hypothesis["id"]})}
