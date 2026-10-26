"""Optimizer plug-ins: methods contributed by installed packages.

The framework never imports a project or optimizer library by name. A package
declares an entry point in the ``optimization_framework.optimizers`` group whose
value names a zero-argument factory (normally a class) for an ``OptimizerPlugin``.
See docs/optimizer-plugins.md for the design and a worked example.

Entries come from installed package metadata, or from a verified execution
manifest inside frozen hosts and workers. Model output selects method IDs,
never import paths. A package installed while the service runs is picked up at the
next listing, without a restart (at most RECHECK_SECONDS later).
"""
from __future__ import annotations

from importlib import import_module, invalidate_caches, metadata
from importlib.util import find_spec
import os
from pathlib import Path
import site
import sys
import threading
import time
from typing import Any, Protocol, runtime_checkable


GROUP = "optimization_framework.optimizers"
REQUIRED = ("id", "name", "description", "representations", "constraints", "parameters", "parameter_properties")
# How often the installed plug-ins are compared with what is installed now: reading entry points costs about a millisecond.
RECHECK_SECONDS = 1.0


def pick_up_installs():
    """Make packages installed since this process started importable, as they would be at the next start: the directories
    their .pth files name (an editable install) join sys.path. Import lines in .pth files are not run again."""
    added = False
    for directory in [*site.getsitepackages(), site.getusersitepackages()]:
        for pth in sorted(Path(directory).glob("*.pth")) if os.path.isdir(directory) else []:
            for line in pth.read_text().splitlines():
                line = line.strip()
                path = os.path.abspath(os.path.join(directory, line))
                if line and not line.startswith(("#", "import ", "import\t")) and os.path.isdir(path) and path not in sys.path:
                    sys.path.append(path)
                    added = True
    if added:
        invalidate_caches()
    return added


@runtime_checkable
class OptimizerPlugin(Protocol):
    def methods(self) -> list[dict]:
        """Method descriptors: REQUIRED keys, optional problem_ids and completion_units."""

    def unavailable_reason(self) -> str | None:
        """Why these methods cannot run on this host (for example a missing library), else None."""

    def validate(self, name: str, instance, parameters: dict) -> None:
        """Reject parameters beyond the declared JSON schema by raising ValueError."""

    def create(self, name: str, instance, parameters: dict, seed: int) -> Any:
        """Return an optimizer with propose/observe/checkpoint/restore/inspect/export_artifacts/close."""


class OptimizerPlugins:
    def __init__(self, entries=None):
        self._entries = None if entries is None else dict(entries)
        self._owners = None
        self._loaded = None   # what the owners were loaded from: entries, and for installed plug-ins their versions
        self._checked = 0.0
        self._lock = threading.RLock()
        self.generation = 0   # changes whenever the plug-ins are (re)loaded; the registry's descriptor cache follows it

    def entries(self):
        """Plug-in name -> "module:factory", as recorded in execution manifests."""
        if self._entries is not None:
            return dict(self._entries)
        entries = {}
        for entry in metadata.entry_points(group=GROUP):
            if entry.name in entries:
                raise ValueError(f"Duplicate optimizer plug-in {entry.name!r}")
            entries[entry.name] = entry.value
        return dict(sorted(entries.items()))

    def _installed(self):
        """Each installed entry with its distribution's version, so that an upgrade in place is noticed too."""
        return {entry.name: (entry.value, entry.dist.version if entry.dist else None) for entry in metadata.entry_points(group=GROUP)}

    def _load(self):
        with self._lock:
            return self._reload()

    def _reload(self):
        if self._entries is None and self._owners is not None and time.monotonic() - self._checked >= RECHECK_SECONDS:
            self._checked = time.monotonic()
            if self._installed() != self._loaded:
                self._forget_changed()
                self._owners = None
        if self._owners is None:
            installed = self._installed() if self._entries is None else None
            if self._entries is None:
                pick_up_installs()
            owners = {}
            for name, value in self.entries().items():
                module, factory = value.split(":", 1)
                plugin = getattr(import_module(module), factory)()
                if not isinstance(plugin, OptimizerPlugin):
                    raise ValueError(f"Optimizer plug-in {name!r} must provide methods, unavailable_reason, validate and create")
                for method in plugin.methods():
                    if missing := [key for key in REQUIRED if key not in method]:
                        raise ValueError(f"Optimizer plug-in {name!r} method lacks {', '.join(missing)}")
                    if method["id"] in owners:
                        raise ValueError(f"Optimizer method {method['id']!r} is registered twice")
                    owners[method["id"]] = (plugin, dict(method))
            self._owners, self._loaded, self._checked = owners, installed, time.monotonic()
            self.generation += 1
        return self._owners

    def _forget_changed(self):
        """Drop the imported modules of plug-ins whose entry or version changed, so that they import afresh. The lab's own
        packages are never dropped: they change only with a restart."""
        current, own = self._installed(), Path(__file__).resolve().parents[2]
        for name, (value, version) in (self._loaded or {}).items():
            if current.get(name) == (value, version):
                continue
            package = value.split(":")[0].split(".")[0]
            spec = find_spec(package)
            if spec is None or not spec.origin or Path(spec.origin).resolve().is_relative_to(own):
                continue
            for module in [module for module in sys.modules if module == package or module.startswith(package + ".")]:
                del sys.modules[module]

    def methods(self):
        return [dict(method) for _, method in self._load().values()]

    def get(self, method_id):
        """(plugin, descriptor) for a plug-in method, or None for any other ID."""
        return self._load().get(method_id)


# Installed plug-ins; frozen hosts replace this with their manifest's entries.
installed = OptimizerPlugins()
