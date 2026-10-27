"""Packages installed while the service runs, shared by the problem registry and the optimizer plug-ins.

A registry compares a snapshot of its entry-point group with the one it loaded from, at most every RECHECK_SECONDS. For an
entry whose value or version changed it drops that package's imported modules, so that they import afresh. The lab's own
packages are never dropped: they change only with a restart.
"""
from __future__ import annotations

from importlib import invalidate_caches, metadata
from importlib.util import find_spec
import os
from pathlib import Path
import site
import sys


# How often a registry compares what it loaded with what is installed now: reading entry points costs about a millisecond.
RECHECK_SECONDS = 1.0
# The lab's own packages (optimization_framework, balsamic, dqn_meent, optimization_benchmarks) live under this directory.
OWN = Path(__file__).resolve().parents[1]


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


def snapshot(group):
    """Each installed entry of a group with its distribution's version, so that an upgrade in place is noticed too."""
    return {entry.name: (entry.value, entry.dist.version if entry.dist else None) for entry in metadata.entry_points(group=group)}


def package(value):
    """The top-level package an entry's "module:attribute" value imports."""
    return value.split(":")[0].split(".")[0]


def own(value):
    """Whether an entry's package is one of the lab's own (or cannot be found, so there is nothing to drop)."""
    spec = find_spec(package(value))
    return spec is None or not spec.origin or Path(spec.origin).resolve().is_relative_to(OWN)


def forget_changed(loaded, current):
    """Drop the imported modules of entries in ``loaded`` whose value or version differs in ``current`` (or that are gone),
    except the lab's own packages."""
    for name, (value, version) in (loaded or {}).items():
        if current.get(name) == (value, version) or own(value):
            continue
        top = package(value)
        for module in [module for module in sys.modules if module == top or module.startswith(top + ".")]:
            del sys.modules[module]
