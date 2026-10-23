"""MEENT is optional (README, "MEENT (optional)"): a test marked meent needs what scripts/install-meent installs (PyTorch,
the meent-private fork, mask-optimizers and gymnasium). It runs where they are installed and is skipped elsewhere, with the
reason, rather than failing on a machine that will never run a grating problem."""
import importlib.util

import pytest


def missing():
    """What of scripts/install-meent's packages is missing here, or None."""
    try:
        from dqn_meent.rcwa import load
        load()   # PyTorch and the meent-private fork; the PyPI release is refused
    except ModuleNotFoundError as error:
        return str(error)
    absent = [name for name in ("mask_optimizers", "gymnasium") if importlib.util.find_spec(name) is None]
    return f"{' and '.join(absent)} not installed; scripts/install-meent installs them" if absent else None


def pytest_collection_modifyitems(config, items):
    marked = [item for item in items if item.get_closest_marker("meent")]
    if not marked or not (reason := missing()):
        return
    skip = pytest.mark.skip(reason=f"needs MEENT, which is optional: {reason}")
    for item in marked:
        item.add_marker(skip)
