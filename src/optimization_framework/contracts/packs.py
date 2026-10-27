"""What a problem brings besides its evaluator (decision 17): an adapter's optional ``pack()`` hook returns one.

Hooks are named as ``module:attribute`` (like entry points) and folders relative to the pack's ``package``. The
contract checks only their form; the registry refuses, with the problem id, a pack whose modules or folders are missing.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from pydantic import Field, field_validator, model_validator

from .base import Contract

HOOK = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*:[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*$")


def _hook(value: str | None) -> str | None:
    if value is not None and not HOOK.match(value):
        raise ValueError(f"{value!r} is not a hook of the form 'module:attribute'")
    return value


def _folder(value: str | None) -> str | None:
    if value is not None:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{value!r} must be a folder inside the pack's package")
    return value


class PackTools(Contract):
    """Registration hooks: each is called with the workspace and registers its agent tools or command operations."""
    agent_tools: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)

    @field_validator("agent_tools", "operations")
    @classmethod
    def hooks(cls, value):
        return [_hook(item) for item in value]


class PackEstimators(Contract):
    """``memory`` names ``estimate(fidelity, samples, *, configuration, available_memory_bytes, memory_headroom_bytes)``,
    returning at least ``predicted_peak_bytes`` for a worker on a task of that configuration at that fidelity, from the
    completed validation samples given (dicts with ``fidelity`` and ``peak_rss_bytes``)."""
    memory: str | None = None
    time: str | None = None

    @field_validator("memory", "time")
    @classmethod
    def hooks(cls, value):
        return _hook(value)


Fidelity = dict[str, int]


class PackRacing(Contract):
    """The race's fidelity ladder (cheapest first), the highest fidelity it may validate at (``limit``), how far above the
    search fidelity it validates when the ladder has nothing higher (``step``), the fidelities the race's memory plan
    forecasts besides its protocol's (``memory_checks``), its cost model and the methods it tries first.

    ``cost_model`` names ``growth(target, reference) -> float``: how much a worker's peak memory grows from the
    ``reference`` fidelity to the ``target``; it also orders fidelities. Every fidelity here names the same keys, and the
    section applies only to tasks whose fidelity names exactly those (a pack may serve problems of several fidelities)."""
    ladder: list[Fidelity] = Field(default_factory=list)
    limit: Fidelity = Field(default_factory=dict)
    step: Fidelity = Field(default_factory=dict)
    memory_checks: list[Fidelity] = Field(default_factory=list)
    cost_model: str | None = None
    preferred_methods: list[str] = Field(default_factory=list)

    @field_validator("cost_model")
    @classmethod
    def hooks(cls, value):
        return _hook(value)

    @model_validator(mode="after")
    def one_fidelity_shape(self):
        shapes = {frozenset(item) for item in [*self.ladder, self.limit, self.step, *self.memory_checks] if item}
        if len(shapes) > 1:
            raise ValueError("The racing section's fidelities must all name the same keys")
        if (self.ladder or self.limit) and not self.cost_model:
            raise ValueError("A fidelity ladder needs a cost model to order and scale its fidelities")
        return self

    def keys(self) -> frozenset[str]:
        return next((frozenset(item) for item in [*self.ladder, self.limit, self.step, *self.memory_checks] if item), frozenset())

    def applies_to(self, fidelity: dict | None) -> bool:
        """Whether a task at this fidelity races on this section: it names the section's fidelity keys, or the section
        has no fidelities at all."""
        keys = self.keys()
        return not keys or frozenset(fidelity or {}) == keys


class PackPresentation(Contract):
    """Labels and defaults beside ``ProblemDefinition.renderer`` (e.g. what a design's on and off cells are)."""
    labels: dict[str, str] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)


class PackReference(Contract):
    """Material mounted read-only into the coding workspaces of the pack's campaigns: a folder inside the pack's package,
    or the folder an environment variable names when it is set (material kept outside the package, possibly absent)."""
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    folder: str | None = None
    environment: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")

    @field_validator("folder")
    @classmethod
    def inside(cls, value):
        return _folder(value)

    @model_validator(mode="after")
    def located(self):
        if self.folder is None and self.environment is None:
            raise ValueError(f"Reference {self.name!r} needs a folder or an environment variable")
        return self


class ProblemPack(Contract):
    package: str = Field(pattern=r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*$")
    problem_ids: list[str] = Field(min_length=1)
    tools: PackTools = Field(default_factory=PackTools)
    procedures: str | None = None
    estimators: PackEstimators = Field(default_factory=PackEstimators)
    racing: PackRacing | None = None
    presentation: PackPresentation = Field(default_factory=PackPresentation)
    references: list[PackReference] = Field(default_factory=list)
    legacy: dict[str, str] = Field(default_factory=dict)

    @field_validator("procedures")
    @classmethod
    def inside(cls, value):
        return _folder(value)

    @field_validator("legacy")
    @classmethod
    def legacy_hooks(cls, value):
        return {name: _hook(item) for name, item in value.items()}

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.problem_ids)) != len(self.problem_ids):
            raise ValueError("A pack lists each problem id once")
        if len({item.name for item in self.references}) != len(self.references):
            raise ValueError("A pack names each reference once")
        return self

    def hooks(self) -> list[str]:
        return [*self.tools.agent_tools, *self.tools.operations,
                *(hook for hook in (self.estimators.memory, self.estimators.time) if hook),
                *([self.racing.cost_model] if self.racing and self.racing.cost_model else []), *self.legacy.values()]

    def folders(self) -> list[str]:
        return ([self.procedures] if self.procedures else []) + [item.folder for item in self.references if item.folder]
