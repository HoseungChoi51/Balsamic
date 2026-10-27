"""The problem packs a campaign works with: those of the installed problems its current tasks are on."""
from __future__ import annotations

from optimization_framework.contracts.packs import ProblemPack


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
