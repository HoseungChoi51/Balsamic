"""The problem registry picks up problem packages installed while the service runs (roadmap E1)."""
import shutil
import sys

import pytest

from optimization_benchmarks.problems import ContinuousProblem
from optimization_framework import installed
from optimization_framework.evaluation import registry
from optimization_framework.evaluation.registry import ProblemRegistry


PROBLEM = '''
from optimization_benchmarks.problems import ContinuousProblem


class LateProblem(ContinuousProblem):
    def describe(self):
        return super().describe().model_copy(update={"id": "late_problem", "name": TITLE})
'''


@pytest.fixture
def site_dir(tmp_path, monkeypatch):
    """A site directory to install into, as uv makes an editable install: metadata in site-packages, and a .pth naming the
    library's source directory."""
    site_dir, library = tmp_path / "site-packages", tmp_path / "library"
    site_dir.mkdir(), library.mkdir()
    monkeypatch.setattr(sys, "path", [str(site_dir), *sys.path])
    monkeypatch.setattr(installed.site, "getsitepackages", lambda: [str(site_dir)])
    monkeypatch.setattr(installed.site, "getusersitepackages", lambda: str(tmp_path / "no-user-site"))
    monkeypatch.delitem(sys.modules, "late_problem", raising=False)

    def install(version, title):
        for old in site_dir.glob("late_problem-*.dist-info"):
            shutil.rmtree(old)
        (library / "late_problem.py").write_text(PROBLEM.replace("TITLE", repr(title)))
        info = site_dir / f"late_problem-{version}.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: late-problem\nVersion: {version}\n")
        (info / "entry_points.txt").write_text(f"[{registry.GROUP}]\nlate_problem = late_problem:LateProblem\n")
        (site_dir / "_late_problem.pth").write_text(str(library) + "\n")

    def uninstall():
        shutil.rmtree(next(site_dir.glob("late_problem-*.dist-info")))

    install.uninstall = uninstall
    yield install
    sys.modules.pop("late_problem", None)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_problem_installed_while_the_service_runs_is_listed_within_a_second(site_dir, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(registry.time, "monotonic", clock)
    running = ProblemRegistry().discover()
    assert "late_problem" not in running.ids()
    site_dir("1.0", "Late problem")
    clock.now += 0.5
    assert "late_problem" not in running.ids()   # compared at most once a second
    clock.now += 0.5
    assert "late_problem" in running.ids()
    assert running.get("late_problem").describe().name == "Late problem"
    instance = running.resolve("late_problem", {"dimensions": 2})
    assert running.evaluator(instance) is not None


def test_a_version_bump_reloads_the_problem_and_an_uninstall_drops_it(site_dir, monkeypatch):
    monkeypatch.setattr(registry, "RECHECK_SECONDS", 0)
    running = ProblemRegistry().discover()
    site_dir("1.0", "Late problem")
    first = running.get("late_problem")
    assert first.describe().name == "Late problem"
    site_dir("1.1", "Late problem, revised")   # upgraded in place: the cached adapter goes and the module imports afresh
    second = running.get("late_problem")
    assert second is not first and second.describe().name == "Late problem, revised"
    site_dir.uninstall()
    assert "late_problem" not in running.ids()
    assert "late_problem" not in sys.modules
    with pytest.raises(ValueError, match="not installed"):
        running.get("late_problem")


def test_the_labs_own_problems_are_never_dropped(site_dir, monkeypatch):
    monkeypatch.setattr(registry, "RECHECK_SECONDS", 0)
    running = ProblemRegistry().discover()
    own = running.get("bounded_continuous")
    module = sys.modules[type(own).__module__]
    # The lab's own entry appears to change version, and another package is installed at the same time.
    real = registry.snapshot
    monkeypatch.setattr(registry, "snapshot", lambda group: {
        name: (value, "99" if name == "bounded_continuous" else version) for name, (value, version) in real(group).items()})
    site_dir("1.0", "Late problem")
    assert "late_problem" in running.ids()
    assert running.get("bounded_continuous") is own
    assert sys.modules[type(own).__module__] is module
    # Even gone from the metadata, the lab's own problem stays until a restart.
    monkeypatch.setattr(registry, "snapshot", lambda group: {name: entry for name, entry in real(group).items() if name != "bounded_continuous"})
    assert running.get("bounded_continuous") is own


def test_frozen_and_extended_registries_do_not_change(site_dir, monkeypatch):
    monkeypatch.setattr(registry, "RECHECK_SECONDS", 0)
    frozen = ProblemRegistry.from_entries({"bounded_continuous": "optimization_benchmarks.problems:ContinuousProblem"})
    extended = ProblemRegistry().discover().extended(ContinuousProblem())
    before = extended.ids()
    site_dir("1.0", "Late problem")
    assert frozen.ids() == ["bounded_continuous"]
    assert extended.ids() == before and "late_problem" not in before


def test_the_shared_registry_follows_installs_in_place(site_dir, monkeypatch):
    """Other modules hold a reference to ``problems``: the same object picks the install up."""
    monkeypatch.setattr(registry, "RECHECK_SECONDS", 0)
    shared = registry.problems
    try:
        site_dir("1.0", "Late problem")
        assert "late_problem" in shared.ids() and registry.problems is shared
    finally:
        site_dir.uninstall()
        shared.ids()   # forget the test package again, for the rest of the session
