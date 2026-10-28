"""Design constraints and per-variable values (roadmap N9, M5 part 1).

A charter states a non-linear condition on the design (a minimum gap between fins, an aspect ratio) as a ``design``
constraint: an expression over the decision variables by name. It reaches the declared problem's candidate schema, which
refuses a candidate that breaks it, and the built-in methods resample. Each variable keeps its own permitted values, so a
whole number of fins sits beside continuous widths without the evaluator rounding.
"""
from copy import deepcopy

import pytest

from optimization_framework.contracts.problem_imports import ProblemSetup
from optimization_framework.contracts.problems import (CandidateSchema, DesignConstraint, Objective, ProblemInstance,
                                                        SchemaVariable)
from optimization_framework.optimizers import registry
from optimization_framework.optimizers.enumerate import count
from optimization_framework.optimizers.functions import FunctionMethod
from optimization_framework.problem_charter import charter as C
from optimization_framework.problem_charter.expressions import ExpressionError, evaluate


def heat_sink(**changes):
    """A finned heat sink to be built: a whole number of fins, their width and height, two rules on their geometry."""
    charter = {
        "title": "Finned heat sink",
        "text": "Fins on a base {base_width_mm} wide, at least {min_gap_mm} apart, no taller than {max_aspect} widths.",
        "quantities": {
            "base_width_mm": {"description": "Width of the base", "value": 50.0, "units": "mm", "citation": 1},
            "min_gap_mm": {"description": "Smallest gap the saw can cut", "value": 1.5, "units": "mm", "citation": 1},
            "max_aspect": {"description": "Tallest fin per unit of width that survives machining", "value": 12.0, "units": "1", "citation": 1},
            "air_speed": {"description": "Air speed", "value": 2.0, "units": "m/s", "citation": 1},
        },
        "variables": [
            {"name": "fins", "description": "Number of fins", "representation": "discrete", "values": [float(n) for n in range(2, 13)]},
            {"name": "fin_width_mm", "description": "Fin width", "representation": "continuous", "lower": 0.5, "upper": 5.0, "units": "mm"},
            {"name": "fin_height_mm", "description": "Fin height", "representation": "continuous", "lower": 5.0, "upper": 50.0, "units": "mm"}],
        "constraints": [
            {"id": "min_gap", "form": "design", "statement": "Fins stand at least {min_gap_mm} apart.",
             "test": "(base_width_mm - fins * fin_width_mm) / (fins - 1) >= min_gap_mm"},
            {"id": "aspect", "form": "design", "statement": "A fin is at most {max_aspect} widths tall.",
             "test": "fin_height_mm / fin_width_mm <= max_aspect"}],
        "objective": {"name": "thermal_resistance", "direction": "minimize", "units": "K/W", "definition": "Base to air"},
        "evaluator": {"kind": "declared", "problem_id": "finned_heat_sink", "configuration": {"base_width_mm": "base_width_mm",
                      "air_speed": "air_speed"}, "notes": "Compute the resistance with the fin correlation."},
        "instances": [{"name": "Base", "split": "development"}],
        "citations": [{"id": 1, "source": "brief.md"}],
    }
    charter.update(changes)
    return charter


def compiled(charter):
    setup = ProblemSetup(**C.compile_setups(charter)[0])
    return setup.evaluator_manifest.resolve("v1", setup.configuration, setup.fidelity)


def blocking(rows):
    return {row["code"] for row in rows if row["severity"] == "blocking"}


def test_a_minimum_gap_rule_and_a_ratio_rule_refuse_violating_designs_and_accept_others():
    assert not blocking(C.findings(heat_sink()))
    schema = compiled(heat_sink()).candidate_schema
    assert schema.representation == "continuous" and [d.name for d in schema.design] == ["min_gap", "aspect"]
    assert schema.design[0].constants == {"base_width_mm": 50.0, "min_gap_mm": 1.5}
    assert schema.canonicalize([5, 2.0, 20.0]) == [5.0, 2.0, 20.0]          # gap (50 - 10) / 4 = 10, aspect 10
    with pytest.raises(ValueError, match="violates constraints: min_gap"):
        schema.canonicalize([12, 4.0, 20.0])                                 # (50 - 48) / 11 < 1.5
    with pytest.raises(ValueError, match="violates constraints: aspect"):
        schema.canonicalize([5, 1.0, 20.0])                                  # 20 widths tall
    assert not schema.feasible([12, 4.5, 50.0]) and schema.feasible([3, 3.0, 30.0])
    # A different instance carries its own thresholds.
    wide = heat_sink(instances=[{"name": "Wide gap", "values": {"min_gap_mm": 15.0}}])
    assert not compiled(wide).candidate_schema.feasible([5, 2.0, 20.0])


def test_a_whole_number_and_a_continuous_variable_canonicalize_each_by_its_own_values():
    schema = CandidateSchema(representation="continuous", dimensions=3, bounds=[(2, 12), (0.5, 5), (5, 50)],
        variables=[SchemaVariable(name="fins", size=1, values=[float(n) for n in range(2, 13)]),
                   SchemaVariable(name="fin_width_mm", size=1), SchemaVariable(name="fin_height_mm", size=1)])
    assert schema.canonicalize([3.4, 1.25, 10.0]) == [3.0, 1.25, 10.0]
    assert schema.canonicalize([3.5, 1.25, 10.0])[0] == 3.0 and schema.canonicalize([3.51, 1.25, 10.0])[0] == 4.0
    with pytest.raises(ValueError, match="outside the declared bounds"):
        schema.canonicalize([13, 1.0, 10.0])
    # Discrete variables with lists of their own: each entry is checked against its variable's list.
    discrete = CandidateSchema(representation="discrete", dimensions=4,
        variables=[SchemaVariable(name="pacing", size=1, values=[0.5, 1.0, 1.5]), SchemaVariable(name="weights", size=3, values=[1, 2, 3, 4, 5, 6, 7])])
    assert discrete.canonicalize([1.0, 7, 7, 2]) == [1.0, 7, 7, 2]
    with pytest.raises(ValueError, match="discrete domain of pacing"):
        discrete.canonicalize([7, 1, 1, 1])
    assert count(discrete) == 3 * 7 ** 3
    with pytest.raises(ValueError, match="permitted values"):
        CandidateSchema(representation="discrete", dimensions=2, variables=[SchemaVariable(name="a", size=1, values=[1]), SchemaVariable(name="b", size=1)])
    with pytest.raises(ValueError, match="within its bounds"):
        CandidateSchema(representation="continuous", dimensions=1, bounds=[(0, 1)], variables=[SchemaVariable(name="a", size=1, values=[2])])
    # A schema without variables dumps as it did before them, so its digest is unchanged.
    plain = CandidateSchema(representation="discrete", dimensions=2, values=[1, 2])
    assert set(plain.model_dump()) == {"schema_version", "representation", "dimensions", "bounds", "values", "constraints"}


def test_a_charter_with_mixed_values_compiles_with_each_variables_own_list():
    """The ``evaluator.mixed_values`` workaround (write them as ranges the evaluator rounds) is retired."""
    draft = heat_sink(constraints=[])
    draft["variables"].append({"name": "coating", "description": "Coating thickness class", "representation": "discrete",
                               "values": [0.1, 0.2, 0.4]})
    rows = C.findings(draft)
    assert not blocking(rows) and not any(row["code"] == "evaluator.mixed_values" for row in rows)
    schema = compiled(draft).candidate_schema
    assert [(v.name, v.values) for v in schema.variables][::3] == [("fins", [float(n) for n in range(2, 13)]), ("coating", [0.1, 0.2, 0.4])]
    assert schema.canonicalize([2.2, 1.0, 10.0, 0.33]) == [2.0, 1.0, 10.0, 0.4]
    # Two discrete variables with different lists make a discrete schema with a list each.
    discrete = heat_sink(constraints=[], variables=[draft["variables"][0], draft["variables"][3]])
    schema = compiled(discrete).candidate_schema
    assert schema.representation == "discrete" and schema.values == [] and [v.values for v in schema.variables][1] == [0.1, 0.2, 0.4]
    # A charter that needs neither keeps the schema it had.
    same = heat_sink(constraints=[], variables=[{**draft["variables"][1], "shape": [3]}])
    assert compiled(same).candidate_schema.variables == []


def test_random_proposes_only_feasible_designs_and_enumerate_visits_only_feasible_ones():
    problem = compiled(heat_sink())
    assert registry.capability_reason("random", problem) is None
    mask = ProblemInstance(definition_id="mask", definition_version="1", evaluator_id="mask", evaluator_version="1", configuration={},
        candidate_schema=CandidateSchema(representation="binary", dimensions=4, variables=[SchemaVariable(name="cells", size=4)],
                                         design=[DesignConstraint(name="half", expression="count(cells) == 2")]),
        primary_objective=Objective(name="loss", direction="minimize"), scientific_identity="mask")
    assert "explicit feasibility constraints" in registry.capability_reason("hillclimb", mask)
    assert registry.capability_reason("random", mask) is None
    optimizer = registry.create("random", problem, {}, 3, 200)
    fins = set()
    for _ in range(200):
        proposal, = optimizer.propose()
        candidate = problem.candidate_schema.canonicalize(proposal.candidate)   # raises if infeasible
        fins.add(candidate[0])
        assert proposal.candidate[0] == int(proposal.candidate[0])            # sampled from its own values
        optimizer.observe([type("Observation", (), {"proposal_id": proposal.id, "status": "ok", "candidate": candidate,
                                                     "objectives": {"thermal_resistance": candidate[2]}, "error": None})()])
    assert len(fins) > 4
    # Enumeration over a discrete schema skips the designs that break a design constraint.
    schema = CandidateSchema(representation="discrete", dimensions=3, values=[0, 1, 2, 3],
        variables=[SchemaVariable(name="edges", size=3)], design=[DesignConstraint(name="gap", expression="all(diff(edges) >= 1)")])
    order = ProblemInstance(definition_id="edges", definition_version="1", evaluator_id="edges", evaluator_version="1", configuration={},
        candidate_schema=schema, primary_objective=Objective(name="span", direction="minimize"), scientific_identity="edges")
    enumeration = registry.create("enumerate", order, {}, 0, 100)
    seen = []
    while True:
        try:
            proposal, = enumeration.propose()
        except Exception:
            break
        seen.append(proposal.candidate)
        enumeration.observe([type("Observation", (), {"proposal_id": proposal.id, "status": "ok", "candidate": proposal.candidate,
                                                       "objectives": {"span": proposal.candidate[2] - proposal.candidate[0]}, "error": None})()])
    assert seen == [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]


def test_a_function_method_gets_the_check_as_a_function():
    problem = compiled(heat_sink())
    asked = []

    def method(problem, evaluate, rng):
        asked.append((problem.feasible([12, 4.0, 20.0]), problem.feasible([5, 2.0, 20.0]), problem["candidate_schema"]["design"][0]["name"]))
        return "done"

    runner = FunctionMethod(method, problem, {}, 0)
    with pytest.raises(Exception):
        runner.propose()
    runner.close()
    assert asked == [(False, True, "min_gap")]


def test_findings_check_that_a_design_expression_names_decision_variables_and_computes_on_a_valid_design():
    def rows_for(test):
        draft = heat_sink(constraints=[{"id": "rule", "form": "design", "statement": "A rule.", "test": test}])
        return [row for row in C.findings(draft) if row["key"].endswith(":rule")]

    assert not rows_for("fin_height_mm <= max_aspect * fin_width_mm")
    unknown, = rows_for("fin_height_mm <= tool_reach")
    assert unknown["code"] == "constraint.design_name" and unknown["severity"] == "blocking" and "tool_reach" in unknown["message"]
    quantities_only, = rows_for("min_gap_mm < base_width_mm")
    assert quantities_only["code"] == "constraint.design_name" and "test on quantities" in quantities_only["message"]
    number, = rows_for("fin_height_mm / fin_width_mm")
    assert number["code"] == "constraint.test" and "true or false" in number["message"]
    rare, = rows_for("fin_height_mm > 1000")
    assert rare["code"] == "constraint.design_rare" and rare["severity"] == "warning"
    with pytest.raises(ValueError, match="needs an expression"):
        C.parse(heat_sink(constraints=[{"id": "rule", "form": "design", "statement": "A rule."}]))


def test_the_expression_language_reads_vectors():
    edges = {"edges": [0.0, 2.0, 3.5, 7.0], "w": 1.0}
    assert evaluate("all(diff(edges) >= w)", edges) is True
    assert evaluate("all(diff(edges) >= 2 * w)", edges) is False
    assert evaluate("sum(edges) == 12.5 and count(edges) == 3 and len(edges) == 4", edges) is True
    assert evaluate("max(edges) / at(edges, 1) <= 3.5 and min(edges, -1) == -1", edges) is True
    assert evaluate("count(edges > 2)", edges) == 2.0 and evaluate("sum(abs(edges - 3))", edges) == 3 + 1 + .5 + 4
    assert evaluate("edges * 2", edges) == [0.0, 4.0, 7.0, 14.0]
    for wrong, message in (("edges > 1 and w > 0", "all\\(\\) or any\\(\\)"), ("at(edges, 4)", "outside a vector"),
                           ("edges + [1]", "not allowed"), ("sum(w)", "takes a vector"), ("edges + diff(edges)", "4 and 3 entries")):
        with pytest.raises(ExpressionError, match=message):
            evaluate(wrong, edges)


def test_an_installed_library_that_drops_a_design_constraint_differs_from_the_charter():
    manifest = ProblemSetup(**C.compile_setups(heat_sink())[0]).evaluator_manifest
    instance = manifest.resolve("v1")
    assert C.compare_provided(manifest, instance) == []
    schema = instance.candidate_schema.model_dump()
    schema["design"] = schema["design"][:1]
    library = instance.model_copy(update={"candidate_schema": CandidateSchema(**schema)})
    differences = {row["what"]: row for row in C.compare_provided(manifest, library)}
    assert differences["constraints"]["charter"] == "aspect, min_gap" and differences["constraints"]["library"] == "min_gap"
    rounded = deepcopy(schema)
    rounded["variables"][0]["values"] = []
    library = instance.model_copy(update={"candidate_schema": CandidateSchema(**rounded)})
    assert "values" in {row["what"] for row in C.compare_provided(manifest, library)}
