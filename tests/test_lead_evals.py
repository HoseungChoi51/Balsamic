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
