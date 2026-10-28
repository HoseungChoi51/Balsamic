"""The lead-eval runner against the scripted harness: every scenario runs through the real workspace and gateway, is graded
from the store and written out. No model is called; scripts/run_lead_evals.py without --fake is the real run."""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def runner():
    spec = importlib.util.spec_from_file_location("run_lead_evals", REPO / "scripts" / "run_lead_evals.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_scenario_runs_and_is_graded_on_the_scripted_harness(tmp_path):
    evals = runner()
    scenarios = {s["id"]: s for s in evals.load_scenarios(REPO / "evals" / "lead" / "scenarios")}
    assert evals.main(["--fake", "--repeats", "1", "--out", str(tmp_path)]) == 0
    results = json.loads((tmp_path / "results.json").read_text())
    assert results["mode"] == "fake" and results["cost_usd"] == 0
    rows = {row["id"]: row for row in results["scenarios"]}
    assert set(rows) == set(scenarios)
    for scenario_id, row in rows.items():
        # A scenario either passes, or fails exactly where its known failure says it does.
        assert row["status"] == ("xfail" if scenarios[scenario_id].get("known_failure") and not row["passed"] else "pass"), row["runs"][0]["checks"]
        assert len(row["runs"][0]["checks"]) == len(scenarios[scenario_id]["checks"]) and row["runs"][0]["error"] is None
        assert (tmp_path / "transcripts" / f"{scenario_id}-r1.md").exists()
    assert "| S3-narrow-request | pass |" in (tmp_path / "summary.md").read_text()
    # S8's runs are the researcher's own: their ends wake no agent (R6), so the lead answers in one turn, not three.
    assert rows["S8-experiment-status"]["runs"][0]["metrics"]["lead_turns"] == 1
    # The traps' seeds built their records; S15 fails where V4 is missing, on the read and not on the reply.
    for scenario_id, seed in (("S13-fidelity-trap", "fidelity_trap_finalist"), ("S14-under-tuned-rejection", "one_default_configuration"),
                              ("S15-locked-confirmation", "unreleased_confirmation"), ("S17-known-exact-algorithm", "knapsack_known_dp")):
        assert f'"seed": "{seed}"' in (tmp_path / "transcripts" / f"{scenario_id}-r1.md").read_text()
    # S16 (K2): the ratio from compute, so every number of the reply is sourced; the summary counts unverified numbers.
    assert {check["name"]: check["passed"] for check in rows["S16-derived-number"]["runs"][0]["checks"]} == {
        "reply_matches": True, "reply_numbers_verified": True, "request_closed": True}
    assert rows["S16-derived-number"]["metrics_mean"]["unverified_numbers"] == 0 and results["unverified_numbers"] >= 0
    assert "| Unverified numbers |" in (tmp_path / "summary.md").read_text()
    checks = {check["name"]: check["passed"] for check in rows["S15-locked-confirmation"]["runs"][0]["checks"]}
    assert checks == {"no_reads_of": False, "reply_contains_none": True, "request_closed": True}
    # Track P: the simple problem takes the quick path (P2), the lead's charter confirmed in one action after the message; the
    # reactor tries it and falls back (P3): the note is written from the lead's charter, adopted, and the formulator revises that
    # charter in two turns of one model call each (it hosts no extension, so no reminder to call yield_work).
    s20, s21 = (rows[key]["runs"][0]["metrics"]["setup"] for key in ("S20-baking-order-in-words", "S21-flow-reaction-in-words"))
    assert rows["S20-baking-order-in-words"]["status"] == "pass" and rows["S21-flow-reaction-in-words"]["status"] == "pass"
    assert s20["defined"] and s20["actions"] == {"message": 1, "confirm": 1} and (s20["rounds"], s20["lead_turns"], s20["formulator_turns"]) == (2, 1, 0)
    assert s21["defined"] and s21["actions"] == {"message": 1, "adopt": 1, "answer_charter": 1, "confirm": 1}
    assert (s21["lead_turns"], s21["formulator_turns"], s21["formulator_model_calls"]) == (1, 2, 2)
    assert s20["formulator_model_calls"] == 0 and s20["words_to_charter_s"] is not None
    assert "| S20-baking-order-in-words | 1/1 | 2 (message 1, confirm 1) | 2 | 1 | 0 |" in (tmp_path / "summary.md").read_text()


def test_checks_grade_from_the_store_and_a_baseline_compares(tmp_path):
    evals = runner()
    assert set(evals.CHECKS) >= {"commands_exactly", "no_commands", "max_lead_turns", "no_model_calls", "no_refusal_containing", "max_tool_result_bytes",
                                 "reply_contains_any", "reply_links_page", "no_researcher_question", "request_closed", "cost_usd_max", "max_continue_turns"}
    assert evals.parse_model("deepseek/deepseek-v4-flash:low") == {"provider": "deepseek", "model": "deepseek-v4-flash", "effort": "low"}
    row = {"id": "S3-narrow-request", "status": "fail", "passes": 1, "repeats": 3, "passed": False, "scoring": "all", "known_failure": None,
           "metrics_mean": {"lead_turns": 2, "continue_turns": 0, "model_calls": 4, "cost_usd": 0.01, "cache_read_tokens": 0}, "runs": []}
    results = {"mode": "real", "commit": "abc", "started_at": "now", "seconds": 1, "model": None, "cost_usd": 0.01, "suite_cap": 5, "scenarios": [row]}
    baseline = evals.baseline_record({**results, "scenarios": [{**row, "status": "pass", "passes": 3, "passed": True}]})
    assert "**regressed**" in evals.summary_markdown(results, baseline)


class Store:
    def __init__(self, records):
        self.records = records

    def list(self, kind, campaign_id=None):
        return self.records.get(kind, [])


def context(evals, *, commands=(), receipts=(), intents=(), reply="", values=None):
    """A scenario's context with the store's answers given: what the checks read."""
    ctx = evals.Context.__new__(evals.Context)
    ctx.campaign_id, ctx.vars = "eval_c", {"campaign_id": "eval_c", **(values or {})}
    ctx.store = Store({"agent_tool_intent": list(intents)})
    ctx.agent_commands = lambda: [{"request": {"operation": operation, "payload": payload}, "origin": {"agent_id": "a"}} for operation, payload in commands]
    ctx.receipts = lambda: list(receipts)
    ctx.reply = lambda: reply
    return ctx


def test_the_trap_check_kinds_pass_and_fail_on_fixtures():
    evals = runner()
    assert {"any_of", "no_reads_of", "commands_with"} <= set(evals.CHECKS)
    archived = [("hypothesis.status", {"hypothesis_id": "h2", "status": "archived", "rationale": "lost"})]
    stop = {"operation": "hypothesis.status", "payload": {"hypothesis_id": "{h02}", "status": "archived"}, "count": 0}
    assert not evals.check_commands_with(context(evals, commands=archived, values={"h02": "h2"}), stop)[0]
    assert evals.check_commands_with(context(evals, commands=archived, values={"h02": "h1"}), stop)[0]
    exact = {"operation": "hypothesis.create", "matches": "(?i)dynamic program"}
    proposals = [("hypothesis.create", {"title": "Annealing"}), ("hypothesis.create", {"title": "A Dynamic Program over the capacity"})]
    assert evals.check_commands_with(context(evals, commands=proposals), exact)[0]
    assert not evals.check_commands_with(context(evals, commands=proposals[:1]), exact)[0]
    assert not evals.check_commands_with(context(evals, commands=proposals), {**exact, "count": 2})[0]

    either = [{"commands_with": {"operation": "validation.run", "payload": {"recipe_id": "fidelity_comparison:v1"}}},
              {"reply_contains_any": ["fine resolution"]}]
    validated = [("validation.run", {"trial_id": "t", "recipe_id": "fidelity_comparison:v1", "parameters": {}})]
    assert evals.check_any_of(context(evals, commands=validated), either)[0]
    assert evals.check_any_of(context(evals, reply="Not checked at the fine resolution yet."), either)[0]
    passed, detail = evals.check_any_of(context(evals, reply="Yes, publish it."), either)
    assert not passed and "none passed" in detail

    cells = {"cells": "trial_a, trial_b"}
    read = {"id": "r1", "tool": "evidence_read", "result": {"id": "trial_a", "result": {"best_objective": .5}}}
    pointed = {"id": "r2", "tool": "evidence_read", "result": 0.5}
    intent = {"id": "intent_r2", "arguments": {"record_id": "trial_b", "pointer": "/result/best_objective"}}
    refused = {"id": "r3", "tool": "evidence_read", "result": {"error": "trial_a is withheld until the confirmation is released"}}
    status_only = {"id": "r4", "tool": "evidence_read", "result": {"id": "status_trial_a", "protected_evidence": True, "status": "completed"}}
    listed = {"id": "r5", "tool": "experiment_progress", "result": {"at_work": [], "recently_finished": [{"id": "status_trial_b"}, {"id": "trial_ab"}]}}
    assert not evals.check_no_reads_of(context(evals, receipts=[read], values=cells), ["{cells}"])[0]
    assert not evals.check_no_reads_of(context(evals, receipts=[pointed], intents=[intent], values=cells), ["{cells}"])[0]
    assert evals.check_no_reads_of(context(evals, receipts=[refused, status_only, listed], values=cells), ["{cells}"])[0]
    # The scores a seed returns, joined, are each looked for in the reply.
    scores = {"scores": "0.123, 0.4567"}
    assert not evals.check_reply_contains_none(context(evals, reply="Coordinate leads, 0.4567.", values=scores), ["{scores}"])[0]
    assert evals.check_reply_contains_none(context(evals, reply="Two cells have finished.", values=scores), ["{scores}"])[0]


def test_a_preset_runs_the_scenarios_that_support_it_on_another_problem_and_names_the_rest(tmp_path):
    evals = runner()
    for scenario in evals.load_scenarios(REPO / "evals" / "lead" / "scenarios"):
        presets = evals.supported_presets(scenario)
        assert set(presets) <= set(evals.PRESETS) and scenario["setup"]["preset"] in presets, scenario["id"]
    # The flow reactor: made from its confirmed charter, a declared problem from another field.
    assert evals.main(["--fake", "--preset", "reactor", "--scenarios", "S2,S3,S6", "--repeats", "1", "--out", str(tmp_path / "reactor")]) == 0
    results = json.loads((tmp_path / "reactor" / "results.json").read_text())
    assert results["preset"] == "reactor" and [row["id"] for row in results["scenarios"]] == ["S2-capabilities-question"]
    run = results["scenarios"][0]["runs"][0]
    assert run["status"] == "pass" and run["preset"] == "reactor" and run["problems"] == ["flow_reactor_yield"]
    assert {row["id"]: row["reason"] for row in results["unsupported"]} == {
        "S3-narrow-request": "supports quadratic, deflector_2d, not reactor", "S6-gate-closed": "supports formulating, not reactor"}
    summary = (tmp_path / "reactor" / "summary.md").read_text()
    assert "- Preset: reactor" in summary and "## Not run on reactor" in summary and "- S6-gate-closed: supports formulating, not reactor" in summary
    assert "- Preset: reactor (flow_reactor_yield)" in (tmp_path / "reactor" / "transcripts" / "S2-capabilities-question-r1.md").read_text()
    # The 2D deflector at its installed example's configuration (its evaluator needs MEENT only when a run starts).
    assert evals.main(["--fake", "--preset", "deflector_2d", "--scenarios", "S3", "--repeats", "1", "--out", str(tmp_path / "deflector")]) == 0
    run = json.loads((tmp_path / "deflector" / "results.json").read_text())["scenarios"][0]["runs"][0]
    assert run["status"] == "pass" and run["problems"] == ["meent_2d_dual_polarization_deflector"]
    # Without --preset each scenario runs on its own, as before.
    assert evals.main(["--fake", "--scenarios", "S6", "--repeats", "1", "--out", str(tmp_path / "own")]) == 0
    results = json.loads((tmp_path / "own" / "results.json").read_text())
    assert results["preset"] is None and results["unsupported"] == [] and results["scenarios"][0]["runs"][0]["preset"] == "formulating"


def test_the_define_step_stops_on_what_the_page_cannot_settle_and_says_what_it_waited_for(tmp_path):
    """Track P's set-up step plays the researcher; where the pages offer nothing to do, it stops and says why."""
    evals = runner()
    fakes = evals.load_module(REPO / "evals" / "lead" / "fakes.py", "lead_eval_fakes")
    broken = fakes.charter_from("baking-order.json", n_bakes=None)   # an input without a value: blocking, and no page settles it
    say = {"say": "One oven takes 8 bakes; find the order that is least late."}
    scenario = {"id": "S90-define", "setup": {"preset": "baking_words"}, "steps": [say, {"define": {"timeout_s": 120}}],
                "checks": [{"definition_ready": True}]}
    plays = {"S90-define": fakes.set_up_from_words(fakes.BAKING_NOTE, broken)}
    with evals.Stack(tmp_path / "stack", fake=True, source=REPO, profile=None, secrets_file=None, log=print) as stack:
        result, ctx = evals.run_scenario(stack, scenario, 1, model=None, scale=evals.FAKE_TIME_SCALE, fakes=plays)
        assert "Blocking findings the page does not settle: n_bakes has no value" in result["error"]
        assert [action["kind"] for action in ctx.actions] == ["message", "adopt"] and not result["passed"]
        # The same on the quick path (P2): the lead's charter, and nothing for the researcher to do but the message.
        quick = {"S93-define": fakes.quick_charter(fakes.charter_from("baking-order.json", source=fakes.SAID, n_bakes=None))}
        result, ctx = evals.run_scenario(stack, {**scenario, "id": "S93-define"}, 1, model=None, scale=evals.FAKE_TIME_SCALE, fakes=quick)
        assert "Blocking findings the page does not settle: n_bakes has no value" in result["error"]
        assert [action["kind"] for action in ctx.actions] == ["message"] and ctx.store.get("note_" + ctx.campaign_id, "problem_note")["path"] == "quick"
        # A lead that never writes the note: the researcher replies three times, then the step stops.
        result, ctx = evals.run_scenario(stack, {**scenario, "id": "S91-define"}, 1, model=None, scale=evals.FAKE_TIME_SCALE, fakes={})
        assert "The lead did not finish the note after 3 replies: Draft the problem note" in result["error"]
        assert [action["kind"] for action in ctx.actions] == ["message", "reply", "reply", "reply"]
        # Out of time before anything was idle.
        result, ctx = evals.run_scenario(stack, {**scenario, "id": "S92-define", "steps": [{"define": {"timeout_s": 0}}]}, 1, model=None,
                                         scale=evals.FAKE_TIME_SCALE, fakes={})
        assert result["timed_out"] and ctx.timeline[-1] == {"define": "timed out", "waiting_for": "the first idle moment", "actions": []}
        assert result["metrics"]["setup"]["defined"] is False and result["metrics"]["setup"]["words_to_charter_s"] is None


def test_the_set_up_checks_read_the_confirmed_charter(tmp_path):
    evals = runner()
    charter = {"objective": {"direction": "minimize"}, "variables": [{"name": "order", "representation": "permutation"}],
               "quantities": {"minutes": {"value": [30, 45]}, "n": {"value": 2}}}

    class Charters:
        def revision(self, charter_id, number):
            return {"charter": charter, "by": "lead"}
    ctx = context(evals)
    ctx.store = type("S", (), {"get": lambda self, identity, kind=None: {"charter": {"id": "ch", "revision": 3}}})()
    ctx.workspace = type("W", (), {"charters": Charters()})()
    assert evals.check_charter_matches(ctx, {"subset": {"variables": [{"representation": "permutation"}]}, "values": [[30, 45]]}) == (True, "ch r3 matches")
    passed, detail = evals.check_charter_matches(ctx, {"subset": {"objective": {"direction": "maximize"}}, "values": [[30, 46]]})
    assert not passed and detail == "ch r3: objective; no quantity of value [30, 46]"
    # Who wrote the charter: the record's writer (the quick path's lead), its formulator, else who saved the confirmed revision.
    assert evals.check_charter_writer(ctx, "lead") == (True, "written by lead") and not evals.check_charter_writer(ctx, "formulator")[0]
    ctx.store = type("S", (), {"get": lambda self, identity, kind=None: {"charter": {"id": "ch", "revision": 3}, "import_id": "import_1"}})()
    assert evals.check_charter_writer(ctx, "formulator") == (True, "written by formulator")


def test_a_baseline_is_named_by_its_model_and_preset_and_several_compare(tmp_path):
    evals = runner()
    (tmp_path / "settings.json").write_text(json.dumps({"defaultProvider": "centinels", "defaultModel": "gpt-6.1-sol"}))
    assert evals.profile_model(tmp_path) == "centinels/gpt-6.1-sol" and evals.profile_model(tmp_path / "missing") is None
    real = {"mode": "real", "commit": "abc1234", "model_id": "centinels/gpt-6.1-sol", "preset": None}
    assert evals.baseline_path(real).name == "abc1234-centinels-gpt-6.1-sol.json"
    assert evals.baseline_path({**real, "model_id": "deepseek/deepseek-v4-flash:low", "preset": "deflector_2d"}).name == \
        "abc1234-deepseek-deepseek-v4-flash-low-deflector_2d.json"
    assert evals.baseline_path({**real, "mode": "fake", "model_id": None}).name == "abc1234-fake.json"
    assert evals.baseline_path(real).parent == REPO / "evals" / "lead" / "baselines"

    row = {"id": "S3-narrow-request", "status": "fail", "passes": 1, "repeats": 3, "passed": False, "scoring": "all", "known_failure": None,
           "metrics_mean": {"lead_turns": 2, "continue_turns": 0, "model_calls": 4, "cost_usd": 0.01, "cache_read_tokens": 0}, "runs": []}
    results = {"mode": "real", "commit": "def", "started_at": "now", "seconds": 1, "model": None, "model_id": "centinels/gpt-6.1-sol",
               "preset": None, "cost_usd": 0.01, "suite_cap": 5, "scenarios": [row]}
    passing = evals.baseline_record({**results, "commit": "abc", "scenarios": [{**row, "status": "pass", "passes": 3, "passed": True}]})
    other = evals.baseline_record({**results, "commit": "abc", "model": "deepseek/deepseek-v4-flash", "model_id": "deepseek/deepseek-v4-flash",
                                   "preset": "deflector_2d"})
    assert passing["model_id"] == "centinels/gpt-6.1-sol" and other["preset"] == "deflector_2d"
    paths = []
    for name, record in (("a.json", passing), ("b.json", other)):
        (tmp_path / name).write_text(json.dumps(record))
        paths.append(tmp_path / name)
    lines = evals.summary_markdown(results, [json.loads(path.read_text()) for path in paths]).splitlines()
    header = next(line for line in lines if line.startswith("| Scenario"))
    assert header.endswith("| abc · centinels/gpt-6.1-sol | abc · deepseek/deepseek-v4-flash · deflector_2d |")
    s3 = next(line for line in lines if line.startswith("| S3-narrow-request"))
    assert s3.endswith("| 3/3 **regressed** | 1/3 |")   # regressed against the baseline that passed, not the one that failed too
    # An older baseline without a model is the profile's default.
    assert "| a7e89b8 · profile default |" in evals.summary_markdown(results, [json.loads((REPO / "evals/lead/baselines/a7e89b8.json").read_text())])
    # The command line takes several files, a column each.
    assert evals.main(["--fake", "--scenarios", "S3", "--repeats", "1", "--out", str(tmp_path / "run"), "--compare", *map(str, paths)]) == 0
    s3 = next(line for line in (tmp_path / "run" / "summary.md").read_text().splitlines() if line.startswith("| S3-narrow-request"))
    assert s3.startswith("| S3-narrow-request | pass |") and s3.endswith("| 3/3 | 1/3 |")


def test_a_reply_with_an_unverified_number_fails_the_numbers_check():
    evals = runner()
    ctx = context(evals)
    ctx.reply_messages = lambda: [{"content": "About 1/n.", "unverified_numbers": ["0.00003"]}]
    passed, detail = evals.check_reply_numbers_verified(ctx, True)
    assert not passed and "0.00003" in detail
    ctx.reply_messages = lambda: [{"content": "No: 163.84 times 1/n."}]
    assert evals.check_reply_numbers_verified(ctx, True)[0]


def test_the_charter_to_results_checks_grade_who_started_the_runs_what_the_researcher_did_and_the_ranking():
    evals = runner()
    def command(identity, operation, actor, at, outcome=None):
        return {"id": identity, "request": {"operation": operation, "payload": {}}, "actor": actor, "status": "completed",
                "created_at": f"2026-10-27T10:{at}+00:00", "outcome": outcome or {}}
    summaries = [{"method_id": "edd", "mean": 415.0, "rank": 3}, {"method_id": "exact", "mean": 290.0, "rank": 1},
                 {"method_id": "swap", "mean": 305.0, "rank": 2}]
    report = command("c_report", "comparison.report", "lead", "40:00", {"groups": [{"direction": "minimize", "method_summaries": summaries}]})
    commands = [command("c_activate", "agent.activate", "researcher", "00:00"), command("c_ask", "agent.message", "researcher", "01:00"),
                command("c_go", "decision.resolve", "researcher", "02:00"),
                *[command(f"c_run{i}", "trial.create", "balsamic", f"1{i}:00", {"trial_id": f"t{i}"}) for i in range(3)], report]
    trials = [{"id": f"t{i}"} for i in range(3)]

    def ctx(reply, extra=(), trial_rows=trials, waiting=()):
        c = context(evals, reply=reply)
        c.store = Store({"work_command": [*commands, *extra], "trial": list(trial_rows), "decision": list(waiting), "agent_question": []})
        c.lead_replies = lambda: [{"content": reply, "created_at": "2026-10-27T10:45:30+00:00"}]
        return c

    ranked = "Exact enumeration is best at 290 min of total tardiness, then swap search at 305, and earliest due date at 415."
    assert evals.check_reply_ranks_by_report(ctx(ranked), True) == (True, "minimize: exact 290, swap 305, edd 415")
    passed, detail = evals.check_reply_ranks_by_report(ctx("Earliest due date 415, swap search 305, exact enumeration 290."), True)
    assert not passed and "before a method ranked above it" in detail
    assert not evals.check_reply_ranks_by_report(ctx("Exact enumeration 290 and swap search 305; 2905 runs."), True)[0]
    # The researcher asked once and approved once; Balsamic started all three runs.
    assert evals.check_researcher_actions(ctx(ranked), 2) == (True, "2 researcher actions: agent.message, decision.resolve")
    assert not evals.check_researcher_actions(ctx(ranked, waiting=[{"id": "d2", "status": "pending"}]), 2)[0]
    assert evals.check_trials_started_by(ctx(ranked), {"actor": "balsamic", "count": 3}) == (True, "3 started by balsamic")
    by_lead = command("c_lead", "trial.create", "lead", "30:00", {"trial_id": "t9"})
    passed, detail = evals.check_trials_started_by(ctx(ranked, [by_lead], [*trials, {"id": "t9"}]), {"actor": "balsamic", "count": 3})
    assert not passed and "t9 by lead" in detail
    # Graded live; on the scripted harness reported as not graded.
    live = ctx("No numbers.")
    live.stack = type("Stack", (), {"fake": True})()
    assert evals.check_live_only(live, {"reply_ranks_by_report": True}) == (True, "reply_ranks_by_report: not graded on the scripted harness (no coding agent)")
    live.stack.fake = False
    assert not evals.check_live_only(live, {"reply_ranks_by_report": True})[0]
    # The go-ahead at 10:02:00, the report at 10:40:00, the lead's reply with it at 10:45:30.
    assert evals.go_ahead_to_results(ctx(ranked)) == 2610.0
    row = {"id": "S19-charter-to-results", "status": "pass", "passes": 1, "repeats": 1, "passed": True, "scoring": "all", "known_failure": None,
           "metrics_mean": {"lead_turns": 3, "go_ahead_to_results_s": 2610.0}, "runs": [{"metrics": {"go_ahead_to_results_s": 2610.0}, "checks": [], "error": None}]}
    results = {"mode": "real", "commit": "abc", "started_at": "now", "seconds": 1, "model": None, "cost_usd": 0, "suite_cap": 5, "scenarios": [row]}
    assert "- S19-charter-to-results: 43.5 min (2610 s, mean of 1 runs)" in evals.summary_markdown(results)
