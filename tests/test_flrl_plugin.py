"""The FLRL Fourier methods as dqn_meent's optimizer plug-in, not core built-ins (roadmap N8, INV-N8-1).

The fixtures were written by the code before the move: `optimizer-methods-before-n8.json` is every method descriptor
`registry.methods()` listed, and `flrl-runs-before-n8.json` the masks two FLRL methods proposed across a checkpoint.
"""
import ast
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from dqn_meent.problem_2d import Meent2DProblem
from optimization_benchmarks.problems import ContinuousProblem
from optimization_framework.contracts.problems import Observation
from optimization_framework.optimizers import plugins, registry
from optimization_framework.optimizers.registry import capability_reason, create, methods, validate_parameters


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
FLRL = ["flrl_lsf_random", "flrl_lsf_es", "flrl_ppo", "flrl_autograd_adam", "flrl_ppo_polish", "flrl_ppo_residual"]


def deflector():
    configuration = {"wavelength_nm": 1050, "target_angle_deg": 75, "period_x_nm": 1050 / math.sin(math.radians(75)),
                     "period_y_nm": 525, "thickness_nm": 325, "grid_x": 16, "grid_y": 8, "incident_n": 1.45, "exit_n": 1.0,
                     "incident_angle_deg": 0, "target_order_x": 1, "target_order_y": 0,
                     "silicon_index_source": "FLRL Si_refractive_data.csv", "silicon_n_1050": 3.567390909090909,
                     "reference_meent_version": "0.9.5"}
    return Meent2DProblem().resolve(configuration, {"rcwa_order_x": 1, "rcwa_order_y": 1})


def test_every_method_listed_before_the_move_is_listed_with_the_same_descriptor():
    before = json.loads((FIXTURES / "optimizer-methods-before-n8.json").read_text())
    now = {method["id"]: method for method in methods()}
    assert {name: now.get(name) for name in before} == before
    listed = [method["id"] for method in methods()]
    assert listed.index("surrogate") < listed.index("flrl_lsf_random") < listed.index("motif_surgery")   # the order too


def test_the_flrl_methods_come_from_the_lab_s_own_plug_in():
    assert plugins.installed.entries()["flrl"] == "dqn_meent.flrl_methods:FourierPlugin"
    assert not set(FLRL) & registry.BUILTIN_IDS
    for name in FLRL:
        origin = plugins.installed.origin(name)
        # The lab's own package: the method catalog still shows it as bundled, not as an installed library.
        assert origin["entry_point"] == "flrl" and origin["own"] is True
    adam = next(method for method in methods() if method["id"] == "flrl_autograd_adam")
    assert adam["execution_capabilities"]["completion_units"] == ["evaluation_requests", "optimizer_decisions"]


def test_the_core_registry_imports_nothing_from_dqn_meent():
    for path in (ROOT / "src/optimization_framework/optimizers").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not [name for name in names if name.startswith("dqn_meent")], path
    assert not (ROOT / "src/optimization_framework/optimizers/fourier_specs.py").exists()
    loaded = subprocess.run([sys.executable, "-c", "import sys; from optimization_framework.optimizers import registry; "
                             "registry.capabilities('random'); print(sorted(m for m in sys.modules if m.startswith('dqn_meent')))"],
                            capture_output=True, text=True, check=True).stdout
    assert loaded.strip() == "[]"


def observe(optimizer, instance, proposal):
    share = sum(proposal.candidate) / len(proposal.candidate)
    objectives = {"mean_plus1_transmission": share, "te_plus1_transmission": share, "tm_plus1_transmission": 1 - share}
    optimizer.observe([Observation(id="o", experiment_id="e", attempt_id="a", request_id="r", proposal_id=proposal.id,
        candidate=proposal.candidate, status="ok", objectives=objectives, metadata={}, evaluator_identity=instance.evaluation_identity)])
    return "".join(map(str, proposal.candidate))


@pytest.mark.parametrize("name", ["flrl_lsf_random", "flrl_lsf_es"])
def test_a_stored_flrl_run_continues_as_before(name):
    stored = json.loads((FIXTURES / "flrl-runs-before-n8.json").read_text())[name]
    instance = deflector()
    first = create(name, instance, stored["parameters"], stored["seed"], 10)
    masks = [observe(first, instance, first.propose()[0]) for _ in range(4)]
    checkpoint = first.checkpoint()
    # The checkpoint's identity is the one the core registry gave the run, so a run checkpointed before the move restores.
    assert checkpoint["identity"] == stored["identity"]
    resumed = create(name, instance, stored["parameters"], 99, 10)
    resumed.restore(checkpoint)
    masks += [observe(resumed, instance, resumed.propose()[0]) for _ in range(4)]
    assert masks == stored["masks"]
    assert {key: resumed.inspect()[key] for key in stored["inspect"]} == stored["inspect"]


def test_the_plug_in_keeps_the_methods_checks():
    instance = deflector()
    with pytest.raises(ValueError, match="elite count"):
        validate_parameters("flrl_lsf_es", instance, {"population_size": 2, "elite_count": 3})
    with pytest.raises(ValueError, match="Unsupported optimizer parameters: initial_design"):
        validate_parameters("flrl_ppo", instance, {"initial_design": [0] * 128})
    with pytest.raises(ValueError, match="RCWA settings disagree"):
        validate_parameters("flrl_ppo", instance, {"rcwa_order_x": 3})
    assert capability_reason("flrl_lsf_random", instance) is None
    other = ContinuousProblem().resolve({})
    assert capability_reason("flrl_lsf_random", other) == ("Fourier level-set random search runs only on "
        "meent_2d_dual_polarization_deflector; this task's problem is bounded_continuous")


def test_a_frozen_run_records_the_flrl_entry_point_and_its_solver(tmp_path):
    from optimization_framework.execution import provenance
    manifest = provenance.capture(tmp_path, problem_ids=["meent_2d_dual_polarization_deflector"])
    assert manifest["optimizer_entry_points"]["flrl"] == "dqn_meent.flrl_methods:FourierPlugin"
    assert {"dqn_meent/flrl_methods.py", "dqn_meent/flrl_optimizers.py"} <= set(manifest["scientific_files"])
    frozen = plugins.OptimizerPlugins(manifest["optimizer_entry_points"])
    assert [method["id"] for method in frozen.methods() if method["id"].startswith("flrl_")] == FLRL
