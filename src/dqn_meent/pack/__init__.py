"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

Each roadmap part that adds to it writes a module of its own, ``<part>_<topic>.py`` (``n3_procedures.py``: MEENT's
procedures and cell labels; ``n4_tools.py``: its agent tools and commands, whose code is ``tools.py``), defining
``CONTRIBUTION``, a mapping of ``ProblemPack`` fields. ``pack()`` assembles the modules in name order: lists are joined,
mappings merged, and a key two modules both set is refused, naming both, so parts built in parallel never edit the same
file. The roadmap's N5 to N8 move MEENT's estimators, racing ladder, references and legacy hooks out of the core this way.
"""
import importlib
import pkgutil
import re
from copy import deepcopy

from optimization_framework.contracts.packs import ProblemPack

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]
# A part's module: the part id (a letter and a number) and a topic.
PART_MODULE = re.compile(r"^[a-z]\d+_[a-z0-9_]+$")


def contributions():
    """[(module, CONTRIBUTION)] of the pack's part modules, in name order."""
    names = sorted(info.name for info in pkgutil.iter_modules(__path__) if PART_MODULE.match(info.name))
    return [(name, importlib.import_module(f"{__name__}.{name}").CONTRIBUTION) for name in names]


def assemble(parts):
    """The ProblemPack fields the parts set together: lists joined in order, mappings merged; ValueError when two parts set
    the same key."""
    merged, owners = {}, {}

    def merge(into, part, name, path):
        for key, value in part.items():
            where = (*path, key)
            if key not in into:
                into[key] = deepcopy(value)
                owners[where] = name
            elif isinstance(into[key], list) and isinstance(value, list):
                into[key] = into[key] + deepcopy(value)
            elif isinstance(into[key], dict) and isinstance(value, dict):
                merge(into[key], value, name, where)
            else:
                first = next(owners[where[:depth]] for depth in range(len(where), 0, -1) if where[:depth] in owners)
                raise ValueError(f"MEENT's pack: {'.'.join(where)} is set by both {first} and {name}")

    for name, part in parts:
        merge(merged, part, name, ())
    return merged


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS, **assemble(contributions()))
