"""Lazy installed entry points. Model output can select IDs, never import paths.

The discovered registry picks up problem packages installed while the service runs, without a restart (at most
RECHECK_SECONDS later), as the optimizer plug-ins do.
"""
from __future__ import annotations

from importlib import import_module, invalidate_caches
from importlib.util import find_spec
from pathlib import Path
import threading
import time
from typing import Callable

from optimization_framework.contracts.packs import ProblemPack
from optimization_framework.contracts.problems import ProblemAdapter, ProblemInstance
from optimization_framework.installed import RECHECK_SECONDS, forget_changed, own, pick_up_installs, snapshot


GROUP = "optimization_framework.problems"


def _factory(value):
    module, _, attribute = value.partition(":")
    factory = import_module(module)
    for part in attribute.split(".") if attribute else []:
        factory = getattr(factory, part)
    return factory


def _installed(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):   # a missing parent package
        return False


def checked_pack(name: str, pack) -> ProblemPack:
    """A problem's pack as its adapter declared it, refused with the problem id when it names what is not there."""
    try:
        pack = ProblemPack.model_validate(pack.model_dump() if isinstance(pack, ProblemPack) else pack)
    except ValueError as exc:
        raise ValueError(f"Problem {name!r} declares an invalid pack: {exc}") from exc
    if name not in pack.problem_ids:
        raise ValueError(f"Problem {name!r} declares a pack for {', '.join(pack.problem_ids)}, not for itself")
    spec = find_spec(pack.package) if _installed(pack.package) else None
    if spec is None or not spec.submodule_search_locations:
        raise ValueError(f"Problem {name!r} declares a pack in {pack.package!r}, which is not an installed package")
    root = Path(next(iter(spec.submodule_search_locations)))
    missing = [hook for hook in pack.hooks() if not _installed(hook.split(":", 1)[0])]
    if missing:
        raise ValueError(f"Problem {name!r} declares a pack whose modules are not installed: {', '.join(missing)}")
    missing = [folder for folder in pack.folders() if not (root / folder).is_dir()]
    if missing:
        raise ValueError(f"Problem {name!r} declares a pack whose folders are missing from {pack.package}: {', '.join(missing)}")
    return pack


class ProblemRegistry:
    def __init__(self):
        self._loaders: dict[str, Callable] = {}
        self._adapters: dict[str, ProblemAdapter] = {}
        self._packs: dict[str, ProblemPack | None] = {}
        self._discovered = False   # only the discovered registry follows installs; frozen and extended ones never change
        self._installed = None     # the group's entries and versions when last compared
        self._entries = {}         # name -> (value, version) of each loader taken from an installed entry point
        self._checked = 0.0
        self._lock = threading.RLock()

    def discover(self):
        with self._lock:
            self._discovered = True
            self._sync(snapshot(GROUP))
        return self

    def _sync(self, current):
        """Bring the loaders in line with the installed entries, in place (other modules hold a reference to ``problems``):
        add new ones, and for a changed or removed entry drop its cached adapter and its package's modules. The lab's own
        problems stay as they are: they change only with a restart."""
        forget_changed(self._entries, current)
        for name, entry in list(self._entries.items()):
            if current.get(name) != entry and not own(entry[0]):
                del self._loaders[name], self._entries[name]
                self._adapters.pop(name, None)
                self._packs.pop(name, None)
        for name, entry in current.items():
            if name not in self._loaders:
                self._loaders[name] = lambda value=entry[0]: _factory(value)
                self._entries[name] = entry
        self._installed, self._checked = current, time.monotonic()

    def _recheck(self):
        if not self._discovered or time.monotonic() - self._checked < RECHECK_SECONDS:
            return
        with self._lock:
            current = snapshot(GROUP)
            if current == self._installed:
                self._checked = time.monotonic()
                return
            pick_up_installs()
            invalidate_caches()
            self._sync(current)

    def register(self, name: str, loader: Callable):
        """Application installation hook; intentionally absent from the HTTP API."""
        if name in self._loaders:
            raise ValueError(f"Duplicate problem registration: {name}")
        self._loaders[name] = loader

    @classmethod
    def from_entries(cls, entries):
        """Installed declarations from a verified source manifest, never an API input."""
        registry = cls()
        for name, value in entries.items():
            registry.register(name, lambda value=value: _factory(value))
        return registry

    def ids(self) -> list[str]:
        self._recheck()
        return sorted(self._loaders)

    def extended(self, adapter):
        """Bind this exact adapter in a caller's scope, including an existing name.

        Resolution still checks the complete definition/evaluator identity. The
        installed registry and other callers retain their original registration.
        """
        registry = ProblemRegistry()
        registry._loaders = self._loaders.copy()
        registry._adapters = self._adapters.copy()
        registry._packs = self._packs.copy()
        name = adapter.describe().id
        registry._loaders[name] = lambda: lambda: adapter
        registry._adapters[name] = adapter
        registry._packs.pop(name, None)
        return registry

    def get(self, name: str) -> ProblemAdapter:
        self._recheck()
        if name not in self._loaders:
            raise ValueError(f"Problem adapter {name!r} is not installed; commission and validate an adapter first")
        if name not in self._adapters:
            factory = self._loaders[name]()
            adapter = factory()
            if adapter.describe().id != name:
                raise ValueError("Problem entry point and manifest identifiers disagree")
            self._adapters[name] = adapter
        return self._adapters[name]

    def examples(self) -> list[dict]:
        """Starting setups that installed adapters publish through an optional ``examples()`` hook."""
        result = []
        for name in self.ids():
            hook = getattr(self.get(name), "examples", None)
            if hook is not None:
                result.extend(hook())
        return result

    def pack(self, name: str) -> ProblemPack | None:
        """What an installed problem brings besides its evaluator, from an optional ``pack()`` hook (decision 17)."""
        adapter = self.get(name)   # first, so a changed install drops the pack it held
        if name not in self._packs:
            hook = getattr(adapter, "pack", None)
            self._packs[name] = checked_pack(name, hook()) if hook is not None else None
        return self._packs[name]

    def packs(self) -> dict[str, ProblemPack]:
        """The packs of installed problems, by problem id; problems without one are left out."""
        return {name: pack for name in self.ids() if (pack := self.pack(name)) is not None}

    def devices(self, name: str) -> tuple[str, ...]:
        """Where an installed adapter's evaluator can compute, from an optional ``devices`` hook: CPU unless it says more."""
        return tuple(getattr(self.get(name), "devices", ("cpu",)))

    def resolve(self, name: str, configuration: dict, fidelity: dict | None = None) -> ProblemInstance:
        return self.get(name).resolve(configuration, fidelity)

    def evaluator(self, instance: ProblemInstance):
        adapter = self.get(instance.definition_id)
        resolved = adapter.resolve(instance.configuration, instance.fidelity)
        if resolved != instance:
            raise ValueError("Pinned problem/evaluator version is no longer available with the same identity")
        return adapter.evaluator(instance)


problems = ProblemRegistry().discover()
