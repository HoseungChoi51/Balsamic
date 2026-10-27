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
    # The traps' seeds built their records; S15 fails where V4 is missing, on the read and not on the reply.
    for scenario_id, seed in (("S13-fidelity-trap", "fidelity_trap_finalist"), ("S14-under-tuned-rejection", "one_default_configuration"),
                              ("S15-locked-confirmation", "unreleased_confirmation"), ("S17-known-exact-algorithm", "knapsack_known_dp")):
        assert f'"seed": "{seed}"' in (tmp_path / "transcripts" / f"{scenario_id}-r1.md").read_text()
    checks = {check["name"]: check["passed"] for check in rows["S15-locked-confirmation"]["runs"][0]["checks"]}
    assert checks == {"no_reads_of": False, "reply_contains_none": True, "request_closed": True}


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
