"""The race's fidelity ladder and the memory planner come from the problem's pack (roadmap N5).

`tests/fixtures/meent_race_reference.json` holds what the code before N5, with the ladder, limit and RCWA planner in the
core, gave for the scenarios below; MEENT races and forecasts must give the same now that they come from MEENT's pack.
Regenerate it only for a deliberate change of MEENT's values: `uv run python tests/test_pack_racing.py`.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_framework_racing import FakeWorkspace, final_validation_fixture, setup_race  # noqa: E402
from test_resource_observability import GIB, make_observer, write_manifest, write_race, write_trial  # noqa: E402

from optimization_framework.execution.racing import AdaptiveRacing  # noqa: E402

REFERENCE = Path(__file__).parent / "fixtures/meent_race_reference.json"
MEENT_2D = "meent_2d_dual_polarization_deflector"
# Ids, times and the hashes over them differ per run; the plan's basis names the problem's cost model instead of MEENT's harmonic counts.
VOLATILE = {"id", "race_id", "content_hash", "created_at", "observed_at", "prediction_basis"}


def stable(value):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key not in VOLATILE}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def plan_at(tmp_path, order, *, samples=True, declared=None, highest=None, validation_peak=None):
    workspace, controller, race, _ = final_validation_fixture(tmp_path, search_order=order)
    if not samples:
        race["profile"]["validation_memory_samples"] = []
    if highest is not None:
        race["preflight"]["highest_fidelities"] = [highest]
    if validation_peak is not None:
        race["profile"]["validation_peak_bytes"] = validation_peak
    if declared is not None:
        frozen = controller._protocol
        controller._protocol = lambda race: {**frozen(race), "numerical_parameters": {"fidelities": declared}}
    return stable(controller._final_validation_plan(race))


def fidelity(x, y):
    return {"rcwa_order_x": x, "rcwa_order_y": y}


RACE_SCENARIOS = {
    "amended_22_measured": lambda path: plan_at(path, 22),
    "amended_22_unmeasured": lambda path: plan_at(path, 22, samples=False),
    "amended_30_capped": lambda path: plan_at(path, 30),
    "at_limit_34": lambda path: plan_at(path, 34),
    "search_10_default_ladder": lambda path: plan_at(path, 10, samples=False, highest=fidelity(14, 7)),
    "search_10_measured_default_ladder": lambda path: plan_at(path, 10, highest=fidelity(14, 7)),
    "search_12_declared_ladder": lambda path: plan_at(path, 12, samples=False, highest=fidelity(16, 8),
                                                      declared=[fidelity(12, 6), fidelity(16, 8), fidelity(20, 10)],
                                                      validation_peak=7 * GIB),
    "search_12_declared_beyond_limit": lambda path: plan_at(path, 12, declared=[fidelity(12, 6), fidelity(40, 20)]),
}


def forecast(tmp_path, *, manifest=True, grid=None, available_gib=16):
    observer, workspace, _ = make_observer(tmp_path, available_gib=available_gib)
    write_trial(workspace)
    write_trial(workspace, "u", execution_seconds=20)
    write_race(workspace)
    if grid:
        task = workspace.store.get("task", "task")
        task["problem"]["configuration"] = {"grid_x": grid[0], "grid_y": grid[1]}
        workspace.store.put("task", task)
    if manifest:
        write_manifest(workspace)
    plan = observer.snapshot("c")["plans"][0]
    return stable({"memory_forecast": plan["memory_forecast"], "memory_checks": plan["memory_checks"]})


FORECAST_SCENARIOS = {
    "manifest_16_gib": lambda path: forecast(path),
    "manifest_30_gib": lambda path: forecast(path, available_gib=30),
    "no_manifest_small_grid": lambda path: forecast(path, manifest=False, grid=(16, 8)),
}


def reference():
    return json.loads(REFERENCE.read_text())


@pytest.mark.parametrize("name", sorted(RACE_SCENARIOS))
def test_meent_validation_plans_are_unchanged(tmp_path, name):
    assert RACE_SCENARIOS[name](tmp_path) == stable(reference()["race"][name])


@pytest.mark.parametrize("name", sorted(FORECAST_SCENARIOS))
def test_meent_memory_forecasts_are_unchanged(tmp_path, name):
    assert FORECAST_SCENARIOS[name](tmp_path) == stable(reference()["forecast"][name])


def generate(directory):
    result = {"race": {}, "forecast": {}}
    for group, scenarios in (("race", RACE_SCENARIOS), ("forecast", FORECAST_SCENARIOS)):
        for name, scenario in scenarios.items():
            path = Path(directory) / group / name
            path.mkdir(parents=True)
            result[group][name] = scenario(path)
    return result


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        REFERENCE.write_text(json.dumps(generate(directory), indent=1, sort_keys=True) + "\n")
    print(f"wrote {REFERENCE}")


def test_a_meent_race_takes_its_ladder_limit_cost_model_and_preferred_methods_from_the_pack(tmp_path):
    from dqn_meent.pack import pack
    workspace, controller, view = setup_race(tmp_path)
    race = workspace.store.get(view["id"], "adaptive_race")
    racing = pack().racing
    assert race["racing"] == racing.model_dump(mode="json")
    assert racing.ladder == [fidelity(10, 5), fidelity(12, 6), fidelity(14, 7)] and racing.limit == fidelity(34, 17)
    assert racing.preferred_methods == ["motif_surgery", "flrl_ppo_residual", "flrl_autograd_adam", "flrl_lsf_random"]
    assert controller._racing(race) == racing
    # A race recorded before N5 has no snapshot and reads its problem's pack.
    del race["racing"]
    assert controller._racing(race) == racing


def test_the_meent_section_applies_only_to_tasks_at_rcwa_orders():
    from optimization_framework.evaluation.packs import racing_for
    assert racing_for(MEENT_2D, fidelity(10, 5)) is not None
    assert racing_for("meent_grating", {"fourier_order": 40}) is None
    assert racing_for("bounded_continuous", {}) is None
    assert racing_for("not_installed", fidelity(10, 5)) is None


def bounded_race(tmp_path):
    workspace = FakeWorkspace(tmp_path)
    workspace.store.put("campaign", {"id": "campaign", "active_study_id": "study", "version": 1})
    workspace.store.put("task", {"id": "task", "campaign_id": "campaign", "split": "development", "problem": {
        "definition_id": "bounded_continuous", "configuration": {"dimension": 4}, "fidelity": {}}})
    workspace.store.put("trial", {"id": "old", "campaign_id": "campaign", "task_id": "task", "algorithm": "random_search",
        "algorithm_config": {}, "seed": 17, "execution_seconds": 60., "wall_seconds": 60., "max_steps": 1000,
        "status": "budget_exhausted", "progress": {"elapsed_seconds": 60.}})
    controller = AdaptiveRacing(workspace)
    view = controller.create("campaign", {"task_id": "task", "configurations": [
        {"id": "random", "algorithm": "random_search", "pilot_trial_ids": ["old"]},
        {"id": "nelder", "algorithm": "nelder_mead"}, {"id": "cma", "algorithm": "cma_es"}],
        "baseline_configuration_id": "random", "preflight_subject_trial_ids": ["old"]})
    return workspace, controller, workspace.store.get(view["id"], "adaptive_race")


def test_a_bounded_continuous_race_runs_with_no_ladder(tmp_path):
    workspace, controller, race = bounded_race(tmp_path)
    assert race["racing"] is None and controller._racing(race) is None
    race.update(status="running", stage="final_validation")
    race["preflight"] = {"status": "passed", "evidence_trial_ids": ["check"]}
    race["confirmation"] = {"status": "numerical_validation_pending"}
    plan = controller._final_validation_plan(race)
    assert plan["status"] == "declared_fidelity"
    assert plan["parameters"]["fidelities"] == [] and plan["search_fidelity"] == {}
    assert plan["predicted_peak_bytes"] is None and plan["maximum_fidelity"] is None
    endpoint = {"id": "endpoint", "eligible": True, "trial_id": "old", "configuration_id": "nelder", "seed": 17,
                "score": .5, "phase": "confirmation"}
    controller._queue_final_validation(race, [endpoint])
    # Nothing to validate above the declared fidelity: the race ends with its confirmation, and queues no checks.
    assert workspace.created == []
    assert race["status"] == "completed" and race["confirmation"]["status"] == "complete_at_declared_fidelity"
    assert workspace.store.list("race_decision", "campaign")[-1]["action"] == "complete"


def test_a_bounded_continuous_race_launches_its_cells_without_preferred_methods(tmp_path):
    workspace, controller, race = bounded_race(tmp_path)
    race.update(status="running", stage="development")
    race["preflight"]["status"] = "passed"
    workspace.store.put("adaptive_race", race)
    controller.tick()
    race = workspace.store.get(race["id"], "adaptive_race")
    assert not race.get("last_error")
    launched = [cell["configuration_id"] for cell in race["cells"] if cell["status"] == "allocated"]
    assert launched == ["random", "nelder"]   # declaration order; two workers


def test_memory_checks_without_an_estimator_report_measured_peaks_only(tmp_path):
    observer, workspace, _ = make_observer(tmp_path)
    write_trial(workspace)
    write_trial(workspace, "u", execution_seconds=20)
    write_race(workspace)
    task = workspace.store.get("task", "task")
    task["problem"] = {"definition_id": "bounded_continuous", "configuration": {"dimension": 4}, "fidelity": {}}
    workspace.store.put("task", task)
    assert observer.snapshot("c")["plans"][0]["memory_checks"] == []
    write_manifest(workspace)
    plan = observer.snapshot("c")["plans"][0]
    assert plan["memory_checks"] == [{"fidelity": fidelity(18, 9), "predicted_bytes": None, "headroom_bytes": 4 * GIB,
                                      "measured_peak_bytes": 6 * GIB, "fits_now": None,
                                      "basis": "Measured peak only: the problem declares no memory estimator"}]
    assert plan["memory_forecast"]["measured_peak_bytes"] == 6 * GIB


@pytest.mark.parametrize("racing, message", [
    ({"ladder": [fidelity(10, 5)], "limit": {"fourier_order": 40}, "cost_model": "math:pow"}, "same keys"),
    ({"ladder": [fidelity(10, 5)]}, "needs a cost model"),
    ({"limit": {"rcwa_order_x": 1.5}, "cost_model": "math:pow"}, "integer"),
])
def test_a_racing_section_with_mixed_or_unscaled_fidelities_is_refused(racing, message):
    from pydantic import ValidationError
    from optimization_framework.contracts.packs import PackRacing
    with pytest.raises(ValidationError, match=message):
        PackRacing.model_validate(racing)
