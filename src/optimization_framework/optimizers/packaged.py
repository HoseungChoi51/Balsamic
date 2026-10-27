"""Optimizer libraries built to the optimizer_v1 package contract, used in-process as plug-in methods.

An implemented algorithm is a library (docs/optimizer-plugins.md): a module with ``create_optimizer(context)`` whose
optimizer speaks the same JSON contract a coding workspace or the implementation service builds to (proposals,
observations and problem descriptors as plain data; checkpoints as bytes). A library offers its methods by
subclassing ``PackagedPlugin`` and registering it under the ``optimization_framework.optimizers`` entry point;
``PackagedOptimizer`` translates between that contract and the framework's own.
"""
from __future__ import annotations

import base64

from optimization_framework.contracts.problems import Proposal
from optimization_framework.optimizers.finish import MethodFinished


class PackagedOptimizer:
    """One optimizer_v1 module's optimizer, initialized for a problem instance as the worker initializes a package."""

    def __init__(self, module, instance, parameters, seed):
        descriptor = instance.descriptor()
        dimensions = instance.candidate_schema.dimensions
        context = {"dimensions": dimensions, "n_cells": dimensions, "seed": seed, "parameters": dict(parameters),
                   "problem": descriptor, "capabilities": instance.capabilities, "declared_assets": []}
        self.optimizer = module.create_optimizer(context)
        self.optimizer.initialize(descriptor, dict(parameters), seed, [])
        self.pending = []

    def propose(self, max_candidates=1):
        if self.pending:
            raise ValueError("Observe the outstanding batch before proposing again")
        try:
            raw = self.optimizer.propose(max_candidates)
        except StopIteration as exc:
            raise MethodFinished(exc.value if isinstance(exc.value, str) else None) from None
        if isinstance(raw, list) and not raw:
            raise MethodFinished()
        proposals = [Proposal(**proposal) for proposal in raw]
        if not 1 <= len(proposals) <= max_candidates or len({p.id for p in proposals}) != len(proposals):
            raise ValueError("The optimizer returned no proposal, too many, or repeated proposal ids")
        self.pending = proposals
        return list(proposals)

    def observe(self, observations):
        if [o.proposal_id for o in observations] != [p.id for p in self.pending]:
            raise ValueError("Observations must match the outstanding proposals in order")
        self.optimizer.observe([o.model_dump(mode="json") for o in observations])
        self.pending = []

    def checkpoint(self):
        state = self.optimizer.checkpoint()
        if not isinstance(state, bytes):
            raise ValueError("An optimizer_v1 checkpoint is bytes")
        return {"contract": "optimizer_v1", "state": base64.b64encode(state).decode(),
                "pending": [p.model_dump(mode="json") for p in self.pending]}

    def restore(self, checkpoint):
        if checkpoint.get("contract") != "optimizer_v1":
            raise ValueError("Not an optimizer_v1 checkpoint")
        self.optimizer.restore(base64.b64decode(checkpoint["state"]))
        self.pending = [Proposal(**p) for p in checkpoint["pending"]]

    def inspect(self):
        return self.optimizer.inspect()

    def export_artifacts(self):
        return self.optimizer.export_artifacts() if hasattr(self.optimizer, "export_artifacts") else []

    def close(self):
        if hasattr(self.optimizer, "close"):
            self.optimizer.close()


class PackagedPlugin:
    """A library's plug-in: METHODS maps each method id to its module and descriptor (name, description, problem_ids...).

    A method accepts its own ``representations``, else the library's REPRESENTATIONS, else binary candidates; a method left
    on that default says so (``representations_defaulted``), so an incompatibility can name the missing declaration."""

    METHODS: dict = {}
    REPRESENTATIONS: list | None = None

    def methods(self):
        listed = []
        for name, method in self.METHODS.items():
            declared = method.get("representations") or self.REPRESENTATIONS
            listed.append({"constraints": False, "parameters": {}, "parameter_properties": {},
                           **{key: value for key, value in method.items() if key != "module"},
                           "representations": list(declared or ["binary"]), **({} if declared else {"representations_defaulted": True}),
                           "id": name})
        return listed

    def unavailable_reason(self):
        return None

    def validate(self, name, instance, parameters):
        return None

    def create(self, name, instance, parameters, seed):
        return PackagedOptimizer(self.METHODS[name]["module"], instance, parameters, seed)
