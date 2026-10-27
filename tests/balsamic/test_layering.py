"""The ported core never imports the service layer or a module the rebuild removed, and names no new domain."""
import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
REMOVED = ("optimization_framework.api.app", "optimization_framework.api.compatibility", "optimization_framework.campaigns.manager",
           "optimization_framework.campaigns.memory", "optimization_framework.campaigns.context", "optimization_framework.campaigns.research_commands",
           "optimization_framework.research.engine", "optimization_framework.research.coordinator", "optimization_framework.research.context",
           "optimization_framework.research.codex_provider", "optimization_framework.research.decision_review", "optimization_framework.research.lifecycle",
           "optimization_framework.research.progress", "optimization_framework.research.action_policy", "optimization_framework.research.discovery",
           "optimization_framework.research.providers", "optimization_framework.research.model_policy", "dqn_meent.workspace", "dqn_meent.research_seeds",
           # Roadmap H8: the implementation service's agent loop (its builder, test designer and validator grants).
           "optimization_framework.agents.implementation")


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


# The domain-names ratchet (roadmap N1, INV-27). The files of the core whose text names a domain, generated from the code
# at the commit that added the test. The list only shrinks: a file that stops naming one leaves it in the same change, and
# no file joins it. `GRATING_*` environment variables carry the project's old name, not domain logic, and do not count.
CORE = SRC / "optimization_framework"
DOMAIN = re.compile(r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))(?i:meent|rcwa|grating|flrl|deflector)")
ENVIRONMENT = re.compile(r"\bGRATING_\w*")
NAMES_A_DOMAIN = {
    "agents/development_runtime.py", "agents/roles/results_analyst.md", "analysis/comparison.py",
    "assets/service_costs.py", "campaigns/experiment_rules.py", "contracts/racing.py", "contracts/requests.py",
    "evaluation/legacy_confirmation.py", "execution/observability.py", "execution/racing.py", "execution/rcwa_memory.py",
    "execution/worker.py", "implementations/api.py", "implementations/bridge.py", "implementations/client.py",
    "implementations/models.py", "implementations/protected_diagnostics.py", "implementations/runtime.py", "installed.py",
    "optimizers/binary.py", "problem_import/guideline.md", "reports/evidence.py",
}


def naming_a_domain(root):
    """The files under `root` whose text names a domain, as paths relative to it."""
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts
            and DOMAIN.search(ENVIRONMENT.sub("", path.read_text(errors="replace")))}


def ratchet(root, allowed):
    """What breaks the ratchet: files naming a domain that are not allowed, and allowed files that no longer name one."""
    found = naming_a_domain(root)
    return sorted(found - allowed), sorted(allowed - found)


def test_no_new_file_of_the_core_names_a_domain():
    new, cleaned = ratchet(CORE, NAMES_A_DOMAIN)
    assert not new, ("These files of the core now name a domain (meent, rcwa, grating, flrl, deflector); move the domain "
                     "into the problem's own package instead:\n" + "\n".join(new))
    assert not cleaned, "These files no longer name a domain; remove them from NAMES_A_DOMAIN:\n" + "\n".join(cleaned)


def test_the_ratchet_catches_a_new_domain_name_and_a_cleaned_file(tmp_path):
    (tmp_path / "execution").mkdir()
    (tmp_path / "execution" / "service.py").write_text('fallback = problems.resolve("meent_grating", values)\n')
    (tmp_path / "execution" / "clean.py").write_text('enabled = os.environ.get("GRATING_LLM_DISABLED")  # integrating\n')
    (tmp_path / "roles.md").write_text("Report the score at the searched orders.\n")
    assert ratchet(tmp_path, {"execution/service.py"}) == ([], [])
    (tmp_path / "optimizers.py").write_text("class DeflectorSearch: pass\n")
    (tmp_path / "roles.md").write_text("A score at the searched RCWA orders may not hold.\n")
    (tmp_path / "execution" / "camel.py").write_text("adapter = makeMeentAdapter()\n")
    assert ratchet(tmp_path, {"execution/service.py"}) == (["execution/camel.py", "optimizers.py", "roles.md"], [])
    (tmp_path / "execution" / "service.py").write_text("fallback = None\n")
    assert ratchet(tmp_path, {"execution/service.py", "execution/camel.py", "optimizers.py", "roles.md"}) == ([], ["execution/service.py"])
