"""Guard against promoting development or truncated execution into complete replication claims."""
import pytest

from scripts.analyze_replication_suite import aggregate, cohort, comparison_ready


def fresh_rows():
    return [dict(seed=s, status="completed", converged=True, efficiency_F480=.98,
                 summary=dict(completed=True), logical_worker_seconds=7200, logical_search_solves=100)
            for s in range(100,105)]


def test_capped_results_are_bounded_completions_not_full_action_replications():
    rows=fresh_rows()
    rows[-1].update(summary=dict(completed=False), budget_stop_reason="wall_time_limit")
    value=cohort(rows,range(100,105),480)
    assert value["complete"] and value["efficiency"]["n"]==5
    assert value["full_action_runs"]==4 and value["capped_seeds"]==[104]
    rows[-1]["status"]="incomplete"
    value=cohort(rows,range(100,105),480)
    assert not value["complete"] and value["efficiency"]["n"]==4


def test_case_requires_finished_campaign_both_rl_cohorts_and_valid_controls():
    groups={k:cohort(fresh_rows(),range(100,105),480) for k in ("P","selected","hc","refine")}
    refs=[dict(converged=True)]
    assert comparison_ready(dict(stage="finished"),groups,refs,[])
    assert not comparison_ready(dict(stage="development"),groups,refs,[])
    assert not comparison_ready(dict(stage="finished"),groups,refs,["hash mismatch"])
    groups["P"]["complete"]=False
    assert not comparison_ready(dict(stage="finished"),groups,refs,[])
    groups["P"]["complete"]=True
    refs[0]["converged"]=False
    assert not comparison_ready(dict(stage="finished"),groups,refs,[])


def case(key, complete, selected_mean, hc_mean, audit=True):
    return dict(key=key,audit=dict(passed=audit),
                decision=dict(complete=complete,verdict="no_demonstrated_reproducible_advantage",margin_feasible=True),
                groups=dict(selected=dict(efficiency=dict(mean=selected_mean)),refine=dict(efficiency=dict(mean=hc_mean))))


def test_combined_analysis_excludes_unfinished_or_unaudited_cases():
    cases=[case("original",True,79,86),case("pending",False,100,90),case("bad_audit",True,100,80,False)]
    result=aggregate(cases)
    assert result["complete_cases"]==["original"]
    assert not result["all_cases_complete"]
    assert result["equal_case_mean_gap_pp"] is None
    assert result["selected_mean_below_refined_cases"]==1
    cases.append(case("second",True,98,99))
    result=aggregate(cases)
    assert result["equal_case_mean_gap_pp"]==pytest.approx(-4)


def test_duplicate_seed_does_not_complete_confirmation_cohort():
    rows=fresh_rows()
    rows[-1]["seed"]=100
    assert not cohort(rows,range(100,105),480)["complete"]
