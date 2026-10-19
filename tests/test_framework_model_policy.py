"""Campaign model routing persists in the policy snapshot without changing authority or leaking credentials."""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from balsamic.app import create_app
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.llm.adapter import BudgetUnavailable, LLMAdapter, RoleResult
from optimization_framework.llm.model_policy import apply_binding, resolve_policy


CONFIG = {"configured": True, "enabled": True, "provider": "fixture", "model": "fixture",
          "transport": "chat_completions", "billing_mode": "subscription", "pricing_known": False}


def policy():
    return {"default": {"model": "gpt-6-sol", "reasoning_effort": "xhigh"}, "roles": {
        "campaign_manager": {"model": "gpt-6-astra", "reasoning_effort": "xhigh"},
        "literature_investigator": {"model": "gpt-6-luna", "reasoning_effort": "xhigh"},
        "methodology_specialist": {"model": "gpt-6-luna", "reasoning_effort": "xhigh"}}}


@pytest.mark.parametrize(("role", "model"), [
    ("campaign_manager", "gpt-6-astra"), ("research_synthesizer", "gpt-6-astra"),
    ("problem_analyst", "gpt-6-sol"), ("skeptical_domain_analyst", "gpt-6-sol"),
    ("combinatorial_generator", "gpt-6-sol"), ("proposal_reviewer", "gpt-6-sol"),
    ("future_researcher", "gpt-6-sol"), ("implementation_builder", "gpt-6-sol"),
    ("implementation_validator", "gpt-6-sol"), ("literature_investigator", "gpt-6-luna"),
    ("literature_investigator_2", "gpt-6-luna"), ("methodology_specialist", "gpt-6-luna"),
    ("cross_domain_methodology_specialist", "gpt-6-luna"),
    ("cross_domain_methodology_specialist_3", "gpt-6-luna"),
    ("notmethodology_specialist", "gpt-6-sol"),
])
def test_role_families_and_unknown_personas_resolve_requested_models(role, model):
    config = resolve_policy(CONFIG, policy(), role)
    assert config["model"] == model
    assert config["reasoning_effort"] == "xhigh"
    assert config["provider"] == CONFIG["provider"] and config["configured"]
    assert CONFIG["model"] == "fixture"


def test_exact_override_wins_over_family_and_alias():
    values = policy()
    for role in ("cross_domain_methodology_specialist_3", "research_synthesizer"):
        values["roles"][role] = {"model": "custom-reviewed-model", "reasoning_effort": "medium"}
        actual = resolve_policy(CONFIG, values, role)
        assert (actual["model"], actual["reasoning_effort"]) == ("custom-reviewed-model", "medium")


def test_model_switch_cannot_inherit_another_models_api_prices():
    base = {**CONFIG, "billing_mode": "api", "pricing_known": True,
        "input_usd_per_million": 10, "output_usd_per_million": 30}
    routed = resolve_policy(base, policy(), "campaign_manager")
    assert not routed["pricing_known"]
    assert routed["input_usd_per_million"] is None and routed["output_usd_per_million"] is None
    one_price = apply_binding(base, {"model": "another-model", "input_usd_per_million": 2})
    assert not one_price["pricing_known"] and one_price["output_usd_per_million"] is None
    explicit = apply_binding(base, {"model": "another-model", "input_usd_per_million": 2, "output_usd_per_million": 7})
    assert explicit["pricing_known"] and explicit["output_usd_per_million"] == 7
    values = policy()
    values["default"].update(input_usd_per_million=1, output_usd_per_million=2)
    assert not resolve_policy(base, values, "campaign_manager")["pricing_known"]
    same_model = {"default": {"model": base["model"], "reasoning_effort": "high",
        "input_usd_per_million": None, "output_usd_per_million": None}, "roles": {}}
    cleared = resolve_policy(base, same_model, "problem_analyst")
    assert not cleared["pricing_known"]
    assert cleared["input_usd_per_million"] is None and cleared["output_usd_per_million"] is None
    legacy = apply_binding(base, {"reasoning_effort": "high"})
    assert legacy["pricing_known"] and legacy["output_usd_per_million"] == 30
    assert base["input_usd_per_million"] == 10


def test_blank_saved_prices_block_capped_api_before_any_provider_call(monkeypatch):
    events, transports = [], []
    monkeypatch.setattr("optimization_framework.llm.adapter.httpx.Client", lambda **kwargs: transports.append(kwargs))
    adapter = LLMAdapter(budget_usd=1, reservation_callback=events.append, config={**CONFIG,
        "base_url": "https://fixture.invalid/v1", "billing_mode": "api", "pricing_known": True,
        "input_usd_per_million": 10, "output_usd_per_million": 30,
        "model_policy": {"default": {"model": CONFIG["model"], "reasoning_effort": "high",
            "input_usd_per_million": None, "output_usd_per_million": None}, "roles": {}}})
    with pytest.raises(BudgetUnavailable, match="requires configured input/output model prices"):
        adapter.call_with_prompt("problem_analyst", "Fixture instructions", {}, result_type=RoleResult)
    assert not transports and not events
    assert adapter.usage["calls"] == 0 and adapter.usage["reserved_cost_usd"] == 0
    assert not adapter.config["pricing_known"]


def test_common_adapter_routes_each_role_from_snapshot_without_sticky_overrides(monkeypatch):
    adapter = LLMAdapter(config={**CONFIG, "transport": "codex_exec", "model_policy": policy()})
    observed = []
    monkeypatch.setattr(adapter, "_call_codex", lambda role, *args: observed.append((role, deepcopy(adapter.config))))
    for role in ("campaign_manager", "literature_investigator", "unknown_researcher", "methodology_specialist"):
        adapter.call_with_prompt(role, "Fixture instructions", {}, result_type=RoleResult)
    assert [config["model"] for _, config in observed] == ["gpt-6-astra", "gpt-6-luna", "gpt-6-sol", "gpt-6-luna"]
    assert all(config["reasoning_effort"] == "xhigh" for _, config in observed)
    assert adapter.base_config["model"] == "fixture"


def test_http_panel_reads_effective_models_without_returning_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    monkeypatch.setenv("GRATING_LLM_PROVIDER", "openai_api")
    monkeypatch.setenv("GRATING_LLM_API_KEY", "fixture-secret-never-return-in-model-panel")
    app = create_app(tmp_path, start_workers=False)
    workspace = app.state.workspace
    campaign = workspace.create_campaign(CampaignInput(name="Model panel", tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    with TestClient(app) as browser:
        url = f"/api/v1/campaigns/{campaign['id']}/models"
        initial = browser.get(url).json()
        assert initial["revision"] == 0 and not initial["saved"] and not initial["configured"]
        assert "fixture-secret-never-return-in-model-panel" not in json.dumps(initial)
        workspace.models.save(campaign["id"], {"expected_revision": 0, "policy": policy(), "reason": "Researcher selects campaign models"})
        current = browser.get(url).json()
        assert current["revision"] == 1 and current["saved"] and not current["configured"]
        assert current["provider"] == initial["provider"]
        roles = {row["role"]: row for row in current["roles"]}
        assert roles["campaign_manager"]["model"] == "gpt-6-astra"
        assert roles["cross_domain_methodology_specialist"]["matched_role"] == "methodology_specialist"
        assert "fixture-secret-never-return-in-model-panel" not in json.dumps(current)
        assert "models.configure" not in browser.get("/api/v1/command-catalog").json()
        assert browser.get("/api/v1/campaigns/missing/models").status_code == 404
