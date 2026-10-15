"""Problem charters: relations computed by code, findings, proposals, confirmation, forks and campaigns.

Most fixtures come from fields other than the installed photonics problems, so the mechanics are
shown to be general; the installed deflector example is used where its identity must be kept.
"""
from copy import deepcopy

import pytest

from optimization_framework.contracts.problem_charter import ProblemCharter
from optimization_framework.contracts.problem_imports import ProblemSetup
from optimization_framework.evaluation.registry import problems
from optimization_framework.problem_charter import charter as C
from optimization_framework.problem_charter.expressions import ExpressionError, evaluate, names


def reactor(**changes):
    """A flow reaction to be optimized, with no installed evaluator: a declared problem."""
    charter = {
        "title": "Flow reactor yield",
        "summary": "Maximize the yield of a flow reaction at {pressure_bar}.",
        "text": "A tubular reactor of {reactor_volume_ml} runs at {pressure_bar} and {temperature_c}. "
                "The residence time follows from the flow rate: {residence_time_s:.3g}.",
        "quantities": {
            "reactor_volume_ml": {"description": "Reactor volume", "value": 10.0, "units": "mL", "range": [0, None], "citation": 1},
            "flow_rate_ml_min": {"description": "Flow rate", "value": 2.0, "units": "mL/min", "range": [0.1, 20.0], "citation": 1},
            "residence_time_s": {"description": "Residence time", "role": "derived", "units": "s",
                                 "expression": "reactor_volume_ml / flow_rate_ml_min * 60"},
            "pressure_bar": {"description": "Back pressure", "value": 5.0, "units": "bar", "citation": 1},
            "temperature_c": {"description": "Reaction temperature", "value": 80.0, "units": "C", "range": [20.0, 200.0], "citation": 1},
            "max_temperature_c": {"description": "Decomposition temperature of the product", "value": 150.0, "units": "C", "citation": 1},
            "solvent_viscosity_cp": {"description": "Solvent viscosity at the temperature", "role": "derived", "units": "cP",
                                     "expression": "table(viscosity, temperature_c)"},
            "repeats": {"description": "Repeat measurements per condition", "kind": "integer", "value": 3, "units": "1", "citation": 1},
        },
        "tables": {"viscosity": {"description": "Solvent viscosity", "x_units": "C", "y_units": "cP",
                                 "points": [[20.0, 1.0], [100.0, 0.3], [200.0, 0.15]], "citation": 1}},
        "variables": [{"name": "loadings", "description": "Catalyst, ligand and additive loading, scaled", "representation": "continuous",
                       "shape": [3], "lower": 0.0, "upper": 1.0}],
        "constraints": [
            {"id": "below_decomposition", "form": "quantities", "statement": "Run below {max_temperature_c}.",
             "test": "temperature_c <= max_temperature_c"},
            {"id": "loading_budget", "form": "linear", "statement": "The scaled loadings add up to at most 2.",
             "terms": [{"variable": "loadings", "weight": "sum"}], "relation": "le", "bound": 2.0}],
        "objective": {"name": "isolated_yield", "direction": "maximize", "units": "fraction", "definition": "Isolated yield, mean of {repeats} repeats"},
        "metrics": [{"name": "selectivity", "units": "fraction", "direction": "maximize"}],
        "evaluator": {"kind": "declared", "problem_id": "flow_reactor_yield", "deterministic": False,
                      "configuration": {"residence_time_s": "residence_time_s", "temperature_c": "temperature_c", "pressure_bar": "pressure_bar"},
                      "fidelity": {"repeats": "repeats"}, "notes": "Run the reaction and measure yield by HPLC."},
        "instances": [{"name": "Base conditions", "split": "development"}],
        "citations": [{"id": 1, "source": "documents/statement.md.txt", "location": "para 2"}],
    }
    charter.update(changes)
    return charter


def flrl():
    return deepcopy(next(e for e in problems.examples() if e["id"].startswith("flrl")))


def codes(rows, severity=None):
    return {row["code"] for row in rows if severity is None or row["severity"] == severity}


def test_expressions_are_whitelisted_and_never_run_python():
    assert evaluate("sqrt(a ** 2 + b ** 2)", {"a": 3, "b": 4}) == 5
    assert evaluate("x if x > 0 else -x", {"x": -2}) == 2
    assert names("table(viscosity, temperature_c) * k + pi") == {"temperature_c", "k"}
    for unsafe in ("().__class__", "__import__('os')", "[1, 2][0]", "(lambda: 1)()", "open('x')", "a.b", "{1: 2}"):
        with pytest.raises(ExpressionError):
            evaluate(unsafe, {"a": 1})
    with pytest.raises(ExpressionError, match="unknown name"):
        evaluate("missing + 1", {})
    with pytest.raises(ExpressionError):      # floats overflow instead of building a huge integer
        evaluate("9 ** 9 ** 9", {})
    with pytest.raises(ExpressionError, match="not a real number"):
        evaluate("(-8) ** 0.5", {})
    with pytest.raises(ExpressionError, match="not extrapolated"):
        evaluate("table(t, 300)", {}, {"t": [[0, 0], [100, 1]]})
    assert evaluate("table(t, 25)", {}, {"t": [[0, 0], [100, 1]]}) == 0.25


def test_derived_quantities_follow_their_inputs_and_texts_show_current_values():
    charter = reactor()
    view = C.describe(charter)
    assert view["values"]["residence_time_s"] == 300.0 and view["values"]["solvent_viscosity_cp"] == pytest.approx(0.475)
    assert view["rendered"]["text"] == ("A tubular reactor of 10 mL runs at 5 bar and 80 C. The residence time follows from the flow rate: 300 s.")
    assert view["blocking"] == 0, view["findings"]
    # The viscosity follows the temperature but nothing receives it: the checks say so, as a warning.
    assert [(f["about"], f["severity"]) for f in view["findings"] if f["code"] == "quantity.unused"] == [(["solvent_viscosity_cp"], "warning")]
    faster = C.apply_changes(charter, [{"op": "set", "path": "quantities.flow_rate_ml_min.value", "value": 4.0}], origin="researcher")
    values = C.resolve(faster)["values"]
    assert values["residence_time_s"] == 150.0
    assert faster["quantities"]["flow_rate_ml_min"]["origin"] == "researcher"
    with pytest.raises(ValueError, match="derived"):
        C.apply_changes(charter, [{"op": "set", "path": "quantities.residence_time_s.value", "value": 100}])


def test_checks_find_each_kind_of_problem_without_knowing_the_field():
    broken = reactor()
    q = broken["quantities"]
    q["flow_rate_ml_min"]["value"] = 50.0                                             # outside its range
    q["pressure_bar"]["units"] = ""                                                    # no units
    q["temperature_c"]["value"] = 160.0                                                # breaks a constraint
    q["a"] = {"description": "A", "role": "derived", "expression": "b + 1", "units": "1"}  # a cycle
    q["b"] = {"description": "B", "role": "derived", "expression": "a + 1", "units": "1"}
    q["angle_deg"] = {"description": "Angle", "value": 30.0, "units": "deg"}
    q["lateral_shift"] = {"description": "Shift", "role": "derived", "units": "1", "expression": "sin(angle_deg)"}
    q["guess_c"] = {"description": "Ambient", "value": 25.0, "units": "C", "origin": "assumed", "note": "room temperature"}
    broken["text"] = "The reactor holds 10 mL and runs at 90 C."                       # a value stated, and one disagreeing
    broken["constraints"] += [
        {"id": "safe", "form": "qualitative", "statement": "Operate safely."},
        {"id": "loading_floor", "form": "linear", "statement": "At least 2.5 in all.", "terms": [{"variable": "loadings", "weight": "sum"}],
         "relation": "ge", "bound": 2.5}]
    broken["questions"] = [{"id": "solvent", "question": "Which solvent?", "options": ["MeCN", "Toluene"]}]
    rows = C.findings(broken)
    blocking = codes(rows, "blocking")
    assert {"quantity.range", "constraint.violated", "relation.error", "assumption.unaccepted", "text.literal_mismatch",
            "constraint.qualitative", "constraint.infeasible", "question.open"} <= blocking
    assert {"quantity.no_units", "text.literal", "relation.degrees"} <= codes(rows, "warning")
    cycle = next(row for row in rows if row["code"] == "relation.error" and row["about"] == ["a"])
    assert "cycle" in cycle["message"]
    infeasible = next(row for row in rows if row["code"] == "constraint.infeasible")
    assert set(infeasible["about"]) == {"loading_budget", "loading_floor"}
    with pytest.raises(ValueError, match="blocking"):
        C.compile_setups(broken)


def test_a_declared_problem_compiles_to_a_manifest_and_an_installed_one_keeps_its_identity():
    setup = ProblemSetup.model_validate(C.compile_setups(reactor())[0])
    manifest = setup.evaluator_manifest
    assert manifest.id == "flow_reactor_yield" and manifest.candidate_schema.dimensions == 3
    assert manifest.candidate_schema.bounds == [(0.0, 1.0)] * 3
    assert manifest.candidate_schema.constraints[0].coefficients == [1.0, 1.0, 1.0]
    assert manifest.configuration == {"residence_time_s": 300.0, "temperature_c": 80.0, "pressure_bar": 5.0}
    assert manifest.fidelity == {"repeats": 3} and not manifest.deterministic
    assert setup.task_input().problem.primary_objective.name == "isolated_yield"
    for example in problems.examples():
        charter = example.get("charter") or C.from_setups(example["name"], example["instances"])
        charter = C.apply_changes(charter, [{"op": "set", "path": f"quantities.{name}.accepted", "value": True}
                                            for name, q in charter["quantities"].items() if q.get("origin") == "assumed"])
        compiled = ProblemSetup.model_validate(C.compile_setups(charter)[0]).task_input().problem.scientific_identity
        assert compiled == ProblemSetup.model_validate(example["instances"][0]).task_input().problem.scientific_identity


def test_the_deflector_example_states_its_relations_and_solving_replaces_mental_arithmetic():
    charter = flrl()["charter"]
    view = C.describe(charter)
    assert view["values"]["period_x_nm"] == 1050 / __import__("math").sin(__import__("math").radians(75))
    assert view["values"]["silicon_n"] == 3.567390909090909
    assert codes(view["findings"], "blocking") == {"assumption.unaccepted"}
    assert "1087.04 nm" in view["rendered"]["text"] and "{" not in view["rendered"]["text"]
    by_angle = C.apply_changes(charter, [{"op": "solve", "input": "target_angle_deg", "target": "period_x_nm", "value": 1100}])
    by_wavelength = C.apply_changes(charter, [{"op": "solve", "input": "wavelength_nm", "target": "period_x_nm", "value": 1100}])
    assert C.resolve(by_angle)["values"]["target_angle_deg"] == pytest.approx(72.65855719724024, abs=1e-7)
    assert C.resolve(by_angle)["values"]["period_x_nm"] == pytest.approx(1100, rel=1e-9)
    assert C.resolve(by_wavelength)["values"]["silicon_n"] == pytest.approx(3.5631938636940084, abs=1e-9)
    rows = {row["name"]: row for row in C.diff(charter, by_wavelength) if row["part"] == "value"}
    assert rows["silicon_n"]["role"] == "derived" and rows["wavelength_nm"]["after"] == "1062.52 nm"
    assert [r["applies"] for r in C.describe(by_wavelength)["references"]] == [False, True]
    with pytest.raises(ValueError, match="no value of target_angle_deg"):
        C.apply_changes(charter, [{"op": "solve", "input": "target_angle_deg", "target": "period_x_nm", "value": 900}])


def test_an_installed_evaluator_holds_the_charter_to_its_fields_and_objective():
    charter = flrl()["charter"]
    charter["quantities"]["incident_angle_deg"]["accepted"] = True
    unmapped = deepcopy(charter)
    del unmapped["evaluator"]["configuration"]["thickness_nm"]
    assert "evaluator.unmapped" in codes(C.findings(unmapped))
    other = deepcopy(charter)
    other["objective"]["name"] = "min_plus1_transmission"
    assert "evaluator.objective" in codes(C.findings(other))
    shape = deepcopy(charter)
    shape["variables"][0]["shape"] = [128, 128]
    assert "evaluator.variables" in codes(C.findings(shape))


@pytest.fixture
def workspace(tmp_path):
    from optimization_framework.execution.service import Workspace
    return Workspace(tmp_path)


def test_researcher_edits_answers_waivers_and_confirmation(workspace):
    charters = workspace.charters
    draft = reactor(questions=[{"id": "solvent", "question": "Which solvent?", "options": ["MeCN", "Toluene"]}],
                    constraints=reactor()["constraints"] + [{"id": "safe", "form": "qualitative", "statement": "Operate safely."}])
    draft["quantities"]["pressure_bar"]["units"] = ""
    record = charters.create(draft, source={"kind": "test"}, by="formulator")
    with pytest.raises(ValueError, match="blocking"):
        charters.confirm(record["id"])
    with pytest.raises(ValueError, match="changed"):
        charters.edit(record["id"], [], expected_revision=record["revision"] + 1)
    record = charters.edit(record["id"], [{"op": "set", "path": "quantities.temperature_c.value", "value": 90.0}], expected_revision=1)
    assert record["charter"]["quantities"]["temperature_c"]["origin"] == "researcher" and record["revision"] == 2
    record = charters.answer(record["id"], "solvent", "MeCN", expected_revision=2)
    with pytest.raises(ValueError, match="cannot be waived"):
        charters.waive(record["id"], "quantity.no_units:pressure_bar", "x")
    record = charters.waive(record["id"], "constraint.qualitative:safe", "Kept as a recorded criterion", expected_revision=3)
    confirmed = charters.confirm(record["id"], expected_revision=4)
    assert confirmed["charter"] == {"id": record["id"], "revision": 4}
    assert confirmed["setups"][0]["configuration"]["temperature_c"] == 90.0
    assert charters.get(record["id"])["status"] == "confirmed"
    # The formulator cannot overwrite what the researcher set.
    rewrite = deepcopy(charters.get(record["id"])["charter"])
    rewrite["quantities"]["temperature_c"]["value"] = 70.0
    with pytest.raises(ValueError, match="set by the researcher"):
        charters.submit(record["id"], rewrite, run_id="r1")


def test_proposals_are_computed_here_and_apply_only_to_the_charter_they_were_made_for(workspace):
    charters = workspace.charters
    record = charters.create(reactor(), source={"kind": "test"})
    with pytest.raises(ValueError, match="leaves blocking findings"):
        charters.propose(record["id"], "Run hotter", [{"label": "Hot", "reason": "Faster", "changes": [
            {"op": "set", "path": "quantities.temperature_c.value", "value": 170.0}]}], run_id="r1")
    proposal = charters.propose(record["id"], "Make the residence time 200 s", [
        {"label": "Faster flow", "reason": "Keeps the reactor", "changes": [{"op": "solve", "input": "flow_rate_ml_min", "target": "residence_time_s", "value": 200}]},
        {"label": "Smaller reactor", "reason": "Keeps the pump", "changes": [{"op": "set", "path": "quantities.reactor_volume_ml.value",
                                                                             "expression": "200 * flow_rate_ml_min / 60"}]}], run_id="r1")
    flow = next(row for row in proposal["options"][0]["diff"] if row["name"] == "flow_rate_ml_min")
    assert flow["after"] == "3 mL/min"
    volume = next(row for row in proposal["options"][1]["diff"] if row["name"] == "reactor_volume_ml")
    assert volume["after"] == "6.66667 mL"
    charters.decide(proposal["id"], None)
    assert charters.get(record["id"])["revision"] == 1
    proposal = charters.propose(record["id"], "Make the residence time 200 s", proposal["options"][:1], run_id="r2")
    charters.ask(record["id"], [{"id": "scale", "question": "Which scale?", "options": ["mg", "g"]}])   # a question keeps it current
    record = charters.decide(proposal["id"], 0)
    assert C.resolve(record["charter"])["values"]["residence_time_s"] == pytest.approx(200)
    assert record["charter"]["quantities"]["flow_rate_ml_min"]["origin"] == "researcher" and record["charter"]["questions"][0]["id"] == "scale"
    late = charters.propose(record["id"], "Hotter", [{"label": "Hot", "reason": "r", "changes": [
        {"op": "set", "path": "quantities.temperature_c.value", "value": 100.0}]}], run_id="r3")
    charters.edit(record["id"], [{"op": "set", "path": "quantities.pressure_bar.value", "value": 6.0}])
    assert charters.view(record["id"])["proposals"][0]["status"] == "stale"
    with pytest.raises(ValueError, match="changed after"):
        charters.decide(late["id"], 0)


def test_forks_record_their_origin_and_campaigns_are_made_and_revised_from_confirmed_charters(workspace):
    from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate
    charters = workspace.charters
    record = charters.create(reactor(), source={"kind": "test"})
    with pytest.raises(ValueError, match="confirmed"):
        charters.fork(record["id"], [])
    confirmed = charters.confirm(record["id"])
    campaign = workspace.create_campaign(CampaignInput(name="Reactor", charter=confirmed["charter"], research_question="Which ligand works best?",
                                                       compute_budget_seconds=600, validation_reserve_seconds=0))
    assert campaign["objective"].startswith("Which ligand works best?\n\nA tubular reactor of 10 mL")
    assert campaign["charter"] == {"id": record["id"], "revision": 1}
    tasks = workspace.current_tasks(campaign["id"])
    assert len(tasks) == 1 and tasks[0]["evaluator_manifest"]["id"] == "flow_reactor_yield"
    assert charters.get(record["id"])["campaign_ids"] == [campaign["id"]]
    fork = charters.fork(record["id"], [{"op": "set", "path": "quantities.temperature_c.value", "value": 120.0}])
    assert fork["charter"]["forked_from"] == {"charter_id": record["id"], "revision": 1, "changes": {"temperature_c": [80.0, 120.0]}}
    assert C.resolve(fork["charter"])["values"]["solvent_viscosity_cp"] == pytest.approx(0.27)
    with pytest.raises(ValueError, match="confirmed charter revision"):
        workspace.create_campaign(CampaignInput(name="x", charter={"id": fork["id"], "revision": 1}))
    # Revising: a new confirmed revision replaces the instances; the research question is kept.
    charters.edit(record["id"], [{"op": "set", "path": "quantities.pressure_bar.value", "value": 8.0}])
    second = charters.confirm(record["id"])
    revised = workspace.update_campaign(campaign["id"], CampaignUpdate(charter=second["charter"]))
    assert revised["version"] == 2 and "8 bar" in revised["objective"] and revised["objective"].startswith("Which ligand")
    assert workspace.current_tasks(campaign["id"])[0]["configuration"]["pressure_bar"] == 8.0


def test_campaigns_made_before_charters_get_one_from_their_instances(workspace):
    from optimization_framework.contracts.requests import CampaignInput
    example = flrl()
    campaign = workspace.create_campaign(CampaignInput(name="Old", objective="Deflect 1050 nm light.", tasks=example["instances"],
                                                       compute_budget_seconds=600, validation_reserve_seconds=0))
    record = workspace.charters.for_campaign(campaign["id"])
    assert record["status"] == "confirmed" and record["campaign_ids"] == [campaign["id"]]
    assert workspace.store.get(campaign["id"], "campaign")["charter"] == {"id": record["id"], "revision": 1}
    assert record["charter"]["quantities"]["wavelength_nm"]["origin"] == "researcher"
    assert "quantity.no_units" in codes(C.findings(record["charter"]), "warning")   # units were never recorded; the checks say so
    assert workspace.charters.for_campaign(campaign["id"])["id"] == record["id"]


def test_the_charter_contract_rejects_malformed_structure():
    for bad in ({"quantities": {"Bad Name": {"description": "x", "value": 1}}},
                {"quantities": {"x": {"description": "x", "role": "derived", "value": 1}}},
                {"constraints": [{"id": "c", "form": "linear", "statement": "s"}]},
                {"tables": {"t": {"description": "t", "x_units": "1", "y_units": "1", "points": [[2, 0], [1, 0]]}}}):
        with pytest.raises(ValueError):
            ProblemCharter.model_validate({"title": "t", **bad})


def test_changing_only_the_research_question_keeps_the_campaigns_instances(workspace):
    from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate
    charters = workspace.charters
    record = charters.create(reactor(), source={"kind": "test"})
    confirmed = charters.confirm(record["id"])
    campaign = workspace.create_campaign(CampaignInput(name="Reactor", charter=confirmed["charter"], research_question="Which ligand?",
                                                       compute_budget_seconds=600, validation_reserve_seconds=0))
    before = [task["id"] for task in workspace.current_tasks(campaign["id"])]
    revised = workspace.update_campaign(campaign["id"], CampaignUpdate(research_question="Which ligand, at what loading?"))
    assert [task["id"] for task in workspace.current_tasks(campaign["id"])] == before
    assert revised["objective"].startswith("Which ligand, at what loading?\n\nA tubular reactor") and revised["research_question"].startswith("Which ligand, at")
    budget = workspace.update_campaign(campaign["id"], CampaignUpdate(compute_budget_seconds=900))
    assert budget["objective"] == revised["objective"] and [task["id"] for task in workspace.current_tasks(campaign["id"])] == before


def test_unused_drafts_are_removed_with_their_formulator_and_used_ones_stay(workspace, tmp_path):
    from optimization_framework.contracts.requests import CampaignInput
    from optimization_framework.problem_import.service import ImportCreate, ProblemImports
    forgotten = []

    class Pi:
        def status(self):
            return {"configured": True, "providers": {"x": {"billing": "api"}}, "models": [{"provider": "x", "id": "m", "thinking_levels": []}]}
        def submit(self, agent, run):
            pass
        def inspect(self, agent_id, after=0):
            return None
        def forget(self, agent_id):
            forgotten.append(agent_id)
    imports = ProblemImports(workspace, client=Pi())
    workspace.problem_imports = imports
    record = imports.create(ImportCreate(provider="x", model="m", statement="Maximize yield."))
    imports.start(record["id"])
    imports.save({**imports.get(record["id"]), "status": "ready"})
    imports._charter_tool(imports.get(record["id"]), record["id"] + "_run_1", "charter_submit", {"charter": reactor()})
    charter_id = imports.get(record["id"])["charter_id"]
    folder = imports.folder(record).root
    assert folder.exists() and workspace.charters.revision(charter_id, 1)
    workspace.charters.remove(charter_id)
    assert forgotten == [record["id"]] and not folder.exists()
    for kind, identity in (("problem_import", record["id"]), ("problem_charter", charter_id), ("problem_charter_revision", f"{charter_id}_r1")):
        with pytest.raises(KeyError):
            workspace.store.get(identity, kind)
    used = workspace.charters.create(reactor(), source={"kind": "test"})
    workspace.create_campaign(CampaignInput(name="R", charter=workspace.charters.confirm(used["id"])["charter"], compute_budget_seconds=60, validation_reserve_seconds=0))
    with pytest.raises(ValueError, match="campaign was made"):
        workspace.charters.remove(used["id"])
    with pytest.raises(ValueError, match="not drafts"):
        workspace.store.delete_drafts("trial", ["x"])


def test_an_installed_evaluator_without_an_example_starts_from_its_declared_defaults(workspace):
    record = workspace.charters.from_evaluator("bounded_continuous")
    charter = record["charter"]
    assert set(charter["quantities"]) == {"function", "dimensions"}        # arrays the evaluator derives are left to it
    assert charter["variables"][0]["representation"] == "continuous" and charter["objective"]["direction"] == "minimize"
    record = workspace.charters.edit(record["id"], [{"op": "set", "path": "quantities.dimensions.value", "value": 5}])
    setup = workspace.charters.confirm(record["id"])["setups"][0]
    assert setup["configuration"] == {"function": "quadratic", "dimensions": 5}
    unknown = workspace.charters.from_evaluator("meent_2d_dual_polarization_deflector")   # no defaults: fields to fill in
    view = workspace.charters.view(unknown["id"])
    assert "quantity.no_value" in {row["code"] for row in view["findings"]}


def test_the_formulator_cannot_waive_accept_or_answer_for_the_researcher(workspace):
    draft = reactor(waivers=[{"key": "constraint.qualitative:safe", "reason": "self-waived"}],
                    assumptions=[{"statement": "Ambient is 25 C", "accepted": True}],
                    questions=[{"id": "q", "question": "Which solvent?", "options": ["A"], "answer": "A"}],
                    constraints=reactor()["constraints"] + [{"id": "safe", "form": "qualitative", "statement": "Operate safely."}])
    draft["quantities"]["pressure_bar"].update(origin="assumed", accepted=True)
    record = workspace.charters.create(workspace.charters.from_formulator(None, draft), source={"kind": "test"}, by="formulator")
    charter = record["charter"]
    assert charter["waivers"] == [] and not charter["assumptions"][0]["accepted"] and charter["questions"][0]["answer"] is None
    assert not charter["quantities"]["pressure_bar"]["accepted"]
    record = workspace.charters.accept_assumptions(record["id"], ["pressure_bar"])
    record = workspace.charters.answer(record["id"], "q", "A")
    again = workspace.charters.submit(record["id"], {**record["charter"], "waivers": [{"key": "constraint.qualitative:safe", "reason": "x"}]}, run_id="r")
    assert again["charter"]["quantities"]["pressure_bar"]["accepted"] and again["charter"]["questions"][0]["answer"] == "A"
    assert again["charter"]["waivers"] == []
