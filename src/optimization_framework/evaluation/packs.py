"""The problem packs a campaign works with: those of the installed problems its current tasks are on."""
from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path

from optimization_framework.contracts.packs import PackReference, ProblemPack


def reference_source(pack: ProblemPack, reference: PackReference) -> Path | None:
    """Where a reference's material is on this host, or None when it is absent: the environment variable's folder when
    it is set, else the reference's default, else its folder in the pack's package."""
    if reference.environment:
        value = os.environ.get(reference.environment) or reference.default
        found = Path(value).expanduser() if value else None
    else:
        spec = find_spec(pack.package)
        found = Path(next(iter(spec.submodule_search_locations))) / reference.folder if spec and spec.submodule_search_locations else None
    return found if found is not None and found.is_dir() else None


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

    def references(self, campaign_id) -> list[dict]:
        """The reference material of the campaign's packs that is present on this host, by name; when two packs use one
        name, the first task's pack keeps it."""
        result = {}
        for pack in self.for_campaign(campaign_id):
            for reference in pack.references:
                source = reference_source(pack, reference)
                if source is not None and reference.name not in result:
                    result[reference.name] = {"name": reference.name, "source": str(source), "package": pack.package,
                                              "description": reference.description}
        return list(result.values())
