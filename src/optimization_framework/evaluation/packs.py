"""The problem packs a campaign works with: those of the installed problems its current tasks are on."""
from __future__ import annotations

from importlib import import_module

from optimization_framework.contracts.packs import PackRacing, ProblemPack


class CampaignPacks:
    def __init__(self, workspace, registry=None):
        self.workspace = workspace
        self._registry = registry

    @property
    def registry(self):
        if self._registry is None:
            from optimization_framework.evaluation.registry import problems
            return problems
        return self._registry

    def for_campaign(self, campaign_id) -> list[ProblemPack]:
        """Each pack once, in the order of the campaign's tasks. A task on a generated evaluator, or on a problem that is
        no longer installed, brings none."""
        installed, result = set(self.registry.ids()), []
        for task in self.workspace.current_tasks(campaign_id):
            problem = task.get("problem") or {}
            if task.get("evaluator_manifest") or problem.get("definition_id") not in installed:
                continue
            pack = self.registry.pack(problem["definition_id"])
            if pack is not None and pack not in result:
                result.append(pack)
        return result


def problem_pack(definition_id, registry=None) -> ProblemPack | None:
    """The pack of an installed problem; none for a problem without one or that is not installed."""
    if registry is None:
        from optimization_framework.evaluation.registry import problems as registry
    if not definition_id or definition_id not in set(registry.ids()):
        return None
    return registry.pack(definition_id)


def racing_for(definition_id, fidelity) -> PackRacing | None:
    """The racing section that applies to a task on this problem at this fidelity: its pack's, when it names the
    fidelity's keys; none otherwise, and the race then runs at the task's declared fidelity with no ladder."""
    pack = problem_pack(definition_id)
    racing = pack.racing if pack is not None else None
    return racing if racing is not None and racing.applies_to(fidelity) else None


def task_racing(task) -> PackRacing | None:
    problem = (task or {}).get("problem") or {}
    return None if (task or {}).get("evaluator_manifest") else racing_for(problem.get("definition_id"), problem.get("fidelity"))


def hook(name: str):
    """The callable a pack's ``module:attribute`` hook names."""
    module, attribute = name.split(":", 1)
    value = import_module(module)
    for part in attribute.split("."):
        value = getattr(value, part)
    return value
