"""Problems that are orders (roadmap C1): a permutation candidate is an order of the items 0 … n−1, each exactly once."""
import numpy as np
import pytest

from optimization_framework.contracts.problem_imports import ProblemSetup
from optimization_framework.contracts.problems import CandidateSchema, Constraint, Objective, ProblemInstance
from optimization_framework.optimizers import registry
from optimization_framework.problem_charter import charter as C

from test_problem_charter import codes, reactor


def baking(**changes):
    """Choose the order of the bakes: a declared problem whose decision variable is an order."""
    draft = reactor()
    draft["quantities"]["n_bakes"] = {"description": "Bakes to schedule", "kind": "integer", "value": 8, "units": "1", "citation": 1}
    draft["variables"] = [{"name": "bake_order", "description": "The order the bakes go into the oven", "representation": "permutation",
                           "shape": ["n_bakes"], "meaning": "Each entry is the index of a bake in the instance's data"}]
    draft["constraints"] = [c for c in draft["constraints"] if c["form"] != "linear"]
    draft.update(changes)
    return draft


def test_canonicalize_accepts_a_rearrangement_and_refuses_repeats_gaps_and_strangers():
    schema = CandidateSchema(representation="permutation", dimensions=4)
    assert schema.canonicalize([2, 0, 3, 1]) == [2, 0, 3, 1]
    assert schema.canonicalize(np.array([3, 2, 1, 0])) == [3, 2, 1, 0]
    assert schema.canonicalize([1.0, 0.0, 2.0, 3.0]) == [1, 0, 2, 3] and all(type(x) is int for x in schema.canonicalize([1.0, 0.0, 2.0, 3.0]))
    for bad in ([0, 0, 1, 2], [0, 1, 2], [0, 1, 2, 4], [0, 1, 2, -1], [0, 1, 2, 2.5], [0, 1, 2, True]):
        with pytest.raises(ValueError):
            schema.canonicalize(bad)


def test_a_permutation_schema_takes_no_bounds_values_or_linear_constraints():
    for extra in ({"bounds": [(0, 3)] * 4}, {"values": [0, 1, 2, 3]},
                  {"constraints": [Constraint(name="cap", coefficients=[1, 1, 1, 1], bound=6)]}):
        with pytest.raises(ValueError, match="Permutation"):
            CandidateSchema(representation="permutation", dimensions=4, **extra)


def test_a_permutation_charter_compiles_to_an_order_of_its_items_and_maps_back():
    rows = C.findings(baking())
    assert not [row for row in rows if row["severity"] == "blocking" and row["code"] != "question.open"], rows
    setup = ProblemSetup.model_validate(C.compile_setups(baking())[0])
    schema = setup.evaluator_manifest.candidate_schema
    assert (schema.representation, schema.dimensions, schema.bounds, schema.values, schema.constraints) == ("permutation", 8, [], [], [])
    back = C.from_setups("Baking order", [setup.model_dump(mode="json")])
    variable = back["variables"][0]
    assert (variable["representation"], variable["shape"], variable["lower"], variable["upper"], variable["values"]) == ("permutation", [8], None, None, [])
    assert not codes(C.findings(back), "blocking")


def test_a_permutation_charter_refuses_two_dimensions_bounds_linear_terms_and_two_orders():
    two = baking()
    two["quantities"]["n_ovens"] = {"description": "Ovens", "kind": "integer", "value": 2, "units": "1", "citation": 1}
    two["variables"][0]["shape"] = ["n_ovens", "n_bakes"]
    shape = [row for row in C.findings(two) if row["code"] == "variable.shape"]
    assert shape and "one-dimensional shape" in shape[0]["message"]
    bounded = baking()
    bounded["variables"][0].update(lower=0, upper=7)
    assert "variable.permutation" in codes(C.findings(bounded), "blocking")
    linear = baking()
    linear["constraints"].append({"id": "early", "form": "linear", "statement": "The first bakes come early.",
                                  "terms": [{"variable": "bake_order", "weight": "sum"}], "relation": "le", "bound": 28})
    assert "constraint.permutation" in codes(C.findings(linear), "blocking")
    orders = baking()
    orders["variables"].append({**orders["variables"][0], "name": "cool_order", "description": "The order they cool"})
    assert "evaluator.permutations" in codes(C.findings(orders), "blocking")
    mixed = baking()
    mixed["variables"].append({"name": "temperature", "description": "Oven temperature", "representation": "continuous", "lower": 150, "upper": 250})
    assert "evaluator.mixed_variables" in codes(C.findings(mixed), "blocking")


def instance(n=8):
    return ProblemInstance(definition_id="baking_order", definition_version="1", evaluator_id="baking_order", evaluator_version="1",
                           configuration={}, candidate_schema=CandidateSchema(representation="permutation", dimensions=n),
                           primary_objective=Objective(name="tardiness", direction="minimize"), scientific_identity="baking_order")


def test_random_proposes_only_valid_orders_and_binary_methods_say_why_not():
    problem = instance()
    assert registry.capability_reason("random", problem) is None
    assert "requires binary" in registry.capability_reason("hillclimb", problem)
    optimizer = registry.create("random", problem, {}, 7, 50)
    seen = set()
    for _ in range(50):
        proposal, = optimizer.propose()
        assert sorted(proposal.candidate) == list(range(8))
        seen.add(tuple(proposal.candidate))
        optimizer.observe([type("Observation", (), {"proposal_id": proposal.id, "status": "ok", "candidate": proposal.candidate,
                                                     "objectives": {"tardiness": float(proposal.candidate[0])}, "error": None})()])
    assert len(seen) > 40   # draws differ
    assert optimizer.optimizer.best.dtype.kind == "i" and optimizer.optimizer.best[0] == 0
