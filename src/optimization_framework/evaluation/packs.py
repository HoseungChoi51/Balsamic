"""The problem packs a campaign works with: those of the installed problems its current tasks are on."""
from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec
import os
from pathlib import Path
import threading

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


def resolve_hook(hook: str):
    """The callable a ``module:attribute`` hook names."""
    module, attribute = hook.split(":", 1)
    target = import_module(module)
    for part in attribute.split("."):
        target = getattr(target, part)
    return target


class CampaignPacks:
    def __init__(self, workspace, registry=None):
        self.workspace = workspace
        self._registry = registry
        self._activated: set[str] = set()   # the tool hooks already called in this workspace
        self._lock = threading.RLock()

    @property
    def registry(self):
        if self._registry is None:
            from optimization_framework.evaluation.registry import problems
            return problems
        return self._registry

    def for_campaign(self, campaign_id) -> list[ProblemPack]:
        """Each pack once, in the order of the campaign's tasks. A task on a generated evaluator, or on a problem that is
        no longer installed, brings none. The packs' tool hooks have run in this workspace when it returns."""
        installed, result = set(self.registry.ids()), []
        for task in self.workspace.current_tasks(campaign_id):
            problem = task.get("problem") or {}
            if task.get("evaluator_manifest") or problem.get("definition_id") not in installed:
                continue
            pack = self.registry.pack(problem["definition_id"])
            if pack is not None and pack not in result:
                result.append(pack)
        for pack in result:
            self.activate(pack)
        return result

    def references(self, campaign_id) -> list[dict]:
        """The reference material of the campaign's packs that is present on this host, by name; when two packs use one
        name, the first task's pack keeps it."""
        result = {}
        for pack in self.for_campaign(campaign_id):
            for reference in pack.references:
                source = reference_source(pack, reference)
                if source is not None and reference.name not in result:
                    result[reference.name] = {"name": reference.name, "source": str(source), "package": pack.package}
        return list(result.values())

    def packages(self, campaign_id) -> set[str]:
        """The packages of the campaign's packs: what a tool or operation a pack registered is keyed by (roadmap N4)."""
        try:
            return {pack.package for pack in self.for_campaign(campaign_id)}
        except KeyError:   # no such campaign (yet)
            return set()

    def activate(self, pack: ProblemPack):
        """Call the pack's tool and operation hooks, once each in this workspace: each registers what the pack's campaigns
        are offered, keyed by the pack's package, and other campaigns are not."""
        with self._lock:
            for hook in (*pack.tools.agent_tools, *pack.tools.operations):
                if hook not in self._activated:
                    resolve_hook(hook)(self.workspace)
                    self._activated.add(hook)
