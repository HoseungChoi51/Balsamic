"""Declared problems show their data to methods (roadmap D3).

The configuration a charter binds to its declared evaluator is the instance's input data, so a method sees it in
``descriptor()["public"]``; the fidelity stays private. Tasks compiled before keep their manifest and its digest.
"""
from types import SimpleNamespace

from optimization_framework.contracts.problem_imports import ProblemSetup
from optimization_framework.optimizers.packaged import PackagedOptimizer
from optimization_framework.problem_charter import charter as C

from test_problem_charter import reactor


def compiled(charter):
    return ProblemSetup.model_validate(C.compile_setups(charter)[0])


def test_a_task_compiled_from_a_declared_charter_gives_methods_its_configuration():
    setup = compiled(reactor())
    manifest = setup.evaluator_manifest
    assert manifest.public_configuration_keys == ["pressure_bar", "residence_time_s", "temperature_c"]
    instance = setup.task_input().problem
    public = instance.descriptor()["public"]
    assert public == {"residence_time_s": 300.0, "temperature_c": 80.0, "pressure_bar": 5.0}
    assert "repeats" not in public   # fidelity stays private

    seen = {}

    class Method:
        def initialize(self, problem, parameters, seed, assets):
            seen["initialize"] = problem["public"]

    module = SimpleNamespace(create_optimizer=lambda context: seen.update(create=context["problem"]["public"]) or Method())
    PackagedOptimizer(module, instance, {}, 0)
    assert seen["create"] == seen["initialize"] == public


def test_a_data_table_reaches_the_method_as_data():
    draft = reactor()
    draft["quantities"]["due_hours"] = {"description": "Due time of each bake", "kind": "data", "role": "input",
                                        "origin": "source", "value": [3, 5, 8], "units": "h"}
    draft["evaluator"]["configuration"]["due_hours"] = "due_hours"
    public = compiled(draft).task_input().problem.descriptor()["public"]
    assert public["due_hours"] == [3, 5, 8]


def test_an_existing_task_keeps_its_digest_and_its_empty_public_descriptor():
    current = compiled(reactor())
    stored = current.model_dump(mode="json")
    stored["evaluator_manifest"]["public_configuration_keys"] = []   # as compiled before D3
    before = ProblemSetup.model_validate(stored)
    assert before.model_dump(mode="json") == stored
    old, new = before.evaluator_manifest, current.evaluator_manifest
    assert old.version != new.version   # only tasks compiled after the change get the data
    instance = before.task_input().problem
    assert instance.definition_version == old.version
    assert instance.descriptor()["public"] == {}
