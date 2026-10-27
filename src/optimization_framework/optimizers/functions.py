"""Plain-function methods: ``def <method_id>(problem, evaluate, rng) -> None`` becomes a method the worker runs.

A few lines of search should not need the optimizer_v1 contract's six calls. A function method calls
``evaluate(candidate)``, which records the candidate and returns its primary objective in the charter's own units and
direction; ``evaluate`` raises ``ValueError`` for an invalid candidate (the method may catch it and try another) and
``StopSearch`` once the run is over (its evaluation or wall cap, a pause, a stop). Returning ends the method: the run
completes as ``method_finished`` (``optimizers/finish.py``), and a returned string is its reason.

``FunctionMethod`` runs the function in a daemon thread and turns each ``evaluate`` into one proposal and its
observation, so the worker drives it like any optimizer. Its checkpoint is the journal of what ``evaluate`` answered;
``restore()`` runs the function again from the start with the same seed and answers from the journal, checking that each
candidate is the one recorded. A function that is not deterministic for its seed (it reads the clock, say) is refused on
resume rather than continued on a history it would not have made.

On a white-box problem (the default, decision 22) the method may compute the objective itself as often as it likes:
the worker gives the descriptor an ``objective(candidate)`` (``WhiteBoxProblem``), and a library's own problem object or
its ``objective.py`` may offer the same. Such calls are not observations and are not counted; only what ``evaluate``
records is known to Balsamic, and the run is judged by its time (N11). On an oracle problem the descriptor has no
``objective``.

``FunctionPlugin`` offers a library's function methods as plug-in methods. It lists them from the ``METHODS`` literal in
the methods module's source, without importing the module, so agent code never runs in the server; only ``create()``,
in the worker, imports it.
"""
from __future__ import annotations

import ast
from collections.abc import Mapping
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
import queue
import random
import threading
from types import MappingProxyType

import numpy as np

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.problems import Proposal
from optimization_framework.optimizers.finish import MethodFinished


class StopSearch(BaseException):
    """The run is over; ``evaluate`` raises it. A ``BaseException``, so a method's ``except Exception`` cannot swallow it."""


def frozen(value):
    """A read-only view of a descriptor: mappings become ``MappingProxyType`` and lists tuples, all the way down."""
    if isinstance(value, dict):
        return MappingProxyType({key: frozen(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(frozen(item) for item in value)
    return value


def plain(candidate):
    """A candidate as JSON data: arrays and tuples become lists, numpy scalars Python numbers."""
    if hasattr(candidate, "tolist"):
        return candidate.tolist()
    if isinstance(candidate, (list, tuple)):
        return [plain(item) for item in candidate]
    return candidate


class WhiteBoxProblem(Mapping):
    """The read-only descriptor of a white-box problem with ``objective(candidate)``: the primary objective, computed by the
    problem's own evaluator, in the charter's units and direction. It is not recorded and costs only time."""

    def __init__(self, descriptor, objective):
        self._descriptor, self.objective = descriptor, objective

    def __getitem__(self, key):
        return self._descriptor[key]

    def __iter__(self):
        return iter(self._descriptor)

    def __len__(self):
        return len(self._descriptor)


# Seeds are global to the process (random, np.random), so one process runs one live function method. Each trial's
# worker is a process of its own.
_live = None
_live_lock = threading.Lock()


class FunctionMethod:
    """One function method for a problem instance, exposing what the worker expects of an optimizer."""

    def __init__(self, fn, instance, parameters, seed, *, problem=None):
        global _live
        with _live_lock:
            if _live is not None and _live.live():
                raise RuntimeError("Another function method is live in this process; each runs in a worker of its own")
            _live = self
        self.fn, self.instance, self.parameters, self.seed = fn, instance, dict(parameters), seed
        self.problem = problem if problem is not None else frozen(instance.descriptor())
        self.own_problem = problem is not None
        self.log = []                    # [candidate_hash, status, score] or [candidate_hash, status, None, error]
        self.replay = []                 # the restored journal, answered without evaluating
        self.pending = None
        self.closed = False
        self.thread = None
        self.calls = queue.Queue()       # from the method: ("candidate", c), ("returned", reason), ("raised", exc)
        self.answers = queue.Queue()     # to the method: ("score", x), ("invalid", message), ("stop", None)

    def live(self):
        return not self.closed or (self.thread is not None and self.thread.is_alive())

    def _start(self):
        def body():
            random.seed(self.seed)
            np.random.seed(self.seed % 2**32)
            rng = np.random.default_rng(self.seed)
            try:
                result = self.fn(self.problem, self.evaluate, rng)
            except StopSearch:
                return
            except BaseException as exc:
                self.calls.put(("raised", exc))
                return
            self.calls.put(("returned", result if isinstance(result, str) else None))
        self.thread = threading.Thread(target=body, name=f"function-method-{getattr(self.fn, '__name__', 'fn')}", daemon=True)
        self.thread.start()

    def open_objective(self, objective):
        """A white-box problem (N11): the descriptor the method gets carries ``objective``. A library's own problem object
        is its own; it is left as it is."""
        if self.thread is not None:
            raise ValueError("The objective is given to a function method before it starts")
        if not self.own_problem:
            self.problem = WhiteBoxProblem(self.problem, objective)

    def evaluate(self, candidate):
        """Record a candidate and return its primary objective; ``ValueError`` if it was not evaluated, ``StopSearch`` once the run is over."""
        if self.closed:
            raise StopSearch()
        candidate = plain(candidate)
        if self.replay:
            entry = self.replay.pop(0)
            if self._hash(candidate) != entry[0]:
                self.replay.clear()
                self.calls.put(("raised", ValueError(
                    "The method is not deterministic for its seed: on resume it proposed another candidate than the one "
                    f"recorded at evaluation {len(self.log) + 1}, so it cannot continue from its checkpoint")))
                raise StopSearch()
            self.log.append(entry)
            return self._answer(entry[1], entry[2], entry[3] if len(entry) > 3 else None)
        self.calls.put(("candidate", candidate))
        kind, value = self.answers.get()
        if kind == "stop":
            raise StopSearch()
        return value if kind == "score" else self._answer("invalid", None, value)

    @staticmethod
    def _hash(candidate):
        try:
            return content_hash(candidate)
        except (TypeError, ValueError):
            return content_hash(repr(candidate))

    @staticmethod
    def _answer(status, score, error):
        if status == "ok":
            return score
        raise ValueError(error or f"The candidate was not evaluated ({status})")

    def propose(self, max_candidates=1):
        if self.pending is not None:
            raise ValueError("Observe the outstanding candidate before proposing again")
        if self.closed:
            raise ValueError("The function method is closed")
        if self.thread is None:
            self._start()
        kind, value = self.calls.get()
        if kind == "returned":
            raise MethodFinished(value)
        if kind == "raised":
            raise value
        self.pending = Proposal(id=f"evaluation_{len(self.log) + 1}", candidate=value)
        return [self.pending]

    def observe(self, observations):
        if self.pending is None or [o.proposal_id for o in observations] != [self.pending.id]:
            raise ValueError("Observations must match the outstanding candidate")
        observation = observations[0]
        candidate_hash = self._hash(plain(self.pending.candidate))
        self.pending = None
        name = self.instance.primary_objective.name
        if observation.status == "ok" and name in observation.objectives:
            score = observation.objectives[name]
            self.log.append([candidate_hash, "ok", score])
            self.answers.put(("score", score))
        else:
            error = observation.error or f"The candidate was not evaluated ({observation.status})"
            self.log.append([candidate_hash, observation.status, None, error])
            self.answers.put(("invalid", error))

    def checkpoint(self):
        return {"contract": "function_v1", "seed": self.seed, "log": [list(entry) for entry in self.log]}

    def restore(self, checkpoint):
        if checkpoint.get("contract") != "function_v1":
            raise ValueError("Not a function_v1 checkpoint")
        if checkpoint.get("seed") != self.seed:
            raise ValueError("The checkpoint was made with another seed")
        if self.thread is not None:
            raise ValueError("A function method is restored before it starts")
        self.log, self.replay = [], [list(entry) for entry in checkpoint["log"]]

    def inspect(self):
        return {"evaluations": len(self.log), "replaying": bool(self.replay)}

    def export_artifacts(self):
        return []

    def close(self, timeout=5.0):
        """The next (or the waiting) ``evaluate`` raises ``StopSearch``; the method's thread is given ``timeout`` to end."""
        self.closed = True
        self.answers.put(("stop", None))
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout)


def listed_methods(module):
    """The ``METHODS = {id: {name, description, ...}}`` literal of a module, read from its source without importing it."""
    spec = find_spec(module)
    if spec is None or not spec.origin or not spec.origin.endswith(".py"):
        raise ValueError(f"Function methods module {module!r} is not an installed Python source file")
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"), filename=spec.origin)
    values = [node.value for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
              and any(isinstance(target, ast.Name) and target.id == "METHODS"
                      for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))]
    if len(values) != 1:
        raise ValueError(f"{module} must assign METHODS once, at the top level")
    try:
        methods = ast.literal_eval(values[0])
    except ValueError:
        raise ValueError(f"{module}.METHODS must be a literal (strings, numbers, lists and dicts), so it can be listed without "
                         "running the module") from None
    if not isinstance(methods, dict):
        raise ValueError(f"{module}.METHODS must map each method id to its description")
    for name, method in methods.items():
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise ValueError(f"{module}.METHODS key {name!r} must be the name of a public function in the module")
        if not isinstance(method, dict) or not all(isinstance(method.get(key), str) for key in ("name", "description")):
            raise ValueError(f"{module}.METHODS[{name!r}] needs a name and a description")
    return methods


class FunctionPlugin:
    """A library's plain-function methods: set ``MODULE = "<pkg>.methods"`` and ``REPRESENTATIONS``.

    The module defines ``METHODS = {id: {name, description, hypothesis_id?, parameters?, parameter_properties?, ...}}``
    and one function ``def <id>(problem, evaluate, rng)`` for each id. ``parameters`` are the defaults and
    ``parameter_properties`` their JSON Schema; a method may also give its own ``representations``, ``problem_ids`` and
    ``completion_units``. A library that provides its own problem object overrides ``problem(instance)``."""

    MODULE: str = ""
    REPRESENTATIONS: list | None = None

    def methods(self):
        listed = []
        for name, method in listed_methods(self.MODULE).items():
            declared = method.get("representations") or self.REPRESENTATIONS
            listed.append({"constraints": False, "parameters": {}, "parameter_properties": {}, **method,
                           "representations": list(declared or ["binary"]), **({} if declared else {"representations_defaulted": True}),
                           "id": name})
        return listed

    def unavailable_reason(self):
        return None

    def validate(self, name, instance, parameters):
        return None

    def problem(self, instance):
        """The library's own problem object for an instance, given to its methods; None gives them the read-only descriptor."""
        return None

    def create(self, name, instance, parameters, seed):
        fn = getattr(import_module(self.MODULE), name, None)
        if not callable(fn):
            raise ValueError(f"{self.MODULE} lists {name!r} in METHODS but defines no function {name}(problem, evaluate, rng)")
        defaults = listed_methods(self.MODULE).get(name, {}).get("parameters") or {}
        return FunctionMethod(fn, instance, {**defaults, **parameters}, seed, problem=self.problem(instance))
