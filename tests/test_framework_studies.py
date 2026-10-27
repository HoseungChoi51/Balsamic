"""Frozen science on the independent problem."""
import pytest

from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate, TaskInput, TrialInput, ControlInput
from optimization_framework.execution.service import Workspace


def test_new_study_links_scientific_changes_and_amendments_keep_original_spec(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Continuous", compute_budget_seconds=100, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={"dimensions": 2})]))
    first_study = workspace.store.get(campaign["active_study_id"], "study")
    task = workspace.current_tasks(campaign["id"])[0]
    trial = workspace.create_trial(TrialInput(campaign_id=campaign["id"], task_id=task["id"], algorithm="coordinate",
                                           max_steps=20, wall_seconds=10, schedule_steps=100))
    frozen = workspace.store.get(trial["experiment_spec_id"], "experiment_spec")
    workspace.control(trial["id"], ControlInput(action="extend", max_steps=30, wall_seconds=15, rationale="Collect more observations"))
    assert workspace.store.get(frozen["id"], "experiment_spec") == frozen
    assert frozen["schedule"]["steps"] == 100 and frozen["completion"]["count"] == 20
    amendment = workspace.store.list("budget_amendment", campaign["id"])[0]
    assert amendment["previous_count"] == 20 and amendment["count"] == 30
    assert amendment["rationale"] == "Collect more observations"
    revised = workspace.update_campaign(campaign["id"], CampaignUpdate(objective="Compare robustness to initialization"))
    second = workspace.store.get(revised["active_study_id"], "study")
    assert second["parent_study_id"] == first_study["id"]
    assert second["goal"] != first_study["goal"]
    assert workspace.store.get(first_study["id"], "study") == first_study
    with pytest.raises(ValueError, match="requires binary"):
        workspace.create_trial(TrialInput(campaign_id=campaign["id"], task_id=task["id"], algorithm="dqn", wall_seconds=10))
