"""MEENT's hooks for what the core keeps only for old records and the legacy provenance path (roadmap N7).

Before problems were declared, every task and trial was a 1D grating described by its ``physics`` alone; ``problem``
resolves such a record as ``meent_grating``. ``runtime`` adds MEENT's version (and, for the lab's fork, its commit) to
the runtime identity the legacy confirmation path records.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def problem(record):
    """The problem a stored task or trial without one was on, or None when it is not a grating record."""
    physics = record.get("physics")
    if not isinstance(physics, dict) or "n_cells" not in physics:
        return None
    from optimization_framework.evaluation.registry import problems
    return problems.resolve("meent_grating", physics)


def runtime():
    from optimization_framework.execution.source import installed_source
    try:
        result = {"meent": version("meent")}
    except PackageNotFoundError:
        result = {"meent": None}
    # The lab's MEENT is a fork that reports the release's version: the commit says which build it is.
    if installed_source("meent"):
        result["meent_source"] = installed_source("meent")
    return result
