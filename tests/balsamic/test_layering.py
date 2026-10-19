"""The ported core never imports the service layer or a module the rebuild removed."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
REMOVED = ("optimization_framework.api.app", "optimization_framework.api.compatibility", "optimization_framework.campaigns.manager",
           "optimization_framework.campaigns.memory", "optimization_framework.campaigns.context", "optimization_framework.campaigns.research_commands",
           "optimization_framework.research.engine", "optimization_framework.research.coordinator", "optimization_framework.research.context",
           "optimization_framework.research.codex_provider", "optimization_framework.research.decision_review", "optimization_framework.research.lifecycle",
           "optimization_framework.research.progress", "optimization_framework.research.action_policy", "optimization_framework.research.discovery",
           "optimization_framework.research.providers", "optimization_framework.research.model_policy", "dqn_meent.workspace", "dqn_meent.research_seeds")


def imports(path):
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for alias in node.names:
                yield node.module + "." + alias.name


def test_no_module_imports_what_the_rebuild_removed():
    offenders = []
    for package in ("balsamic", "optimization_framework", "dqn_meent", "optimization_benchmarks"):
        for path in (SRC / package).rglob("*.py"):
            for name in imports(path):
                if any(name == removed or name.startswith(removed + ".") for removed in REMOVED):
                    offenders.append(f"{path.relative_to(SRC)}: {name}")
    assert not offenders, "\n".join(offenders)


def test_the_core_does_not_depend_on_the_service_layer():
    offenders = [f"{path.relative_to(SRC)}: {name}" for package in ("optimization_framework", "dqn_meent", "optimization_benchmarks")
                 for path in (SRC / package).rglob("*.py") for name in imports(path) if name == "balsamic" or name.startswith("balsamic.")]
    assert not offenders, "\n".join(offenders)


def test_the_removed_modules_are_gone():
    for removed in REMOVED:
        parts = removed.split(".")
        assert not (SRC / Path(*parts)).with_suffix(".py").exists(), removed
        assert not (SRC / Path(*parts)).is_dir(), removed
