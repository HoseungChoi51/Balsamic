"""Panels: the catalog, bindings that resolve from records, fields that write through the charter, buttons that name commands."""
import pytest

from balsamic.panels import service
from optimization_framework.problem_charter.service import KIND as CHARTER_KIND
from optimization_framework.storage.sqlite import now
from support import activate_team, command, submitted, tool_call

MAIN = "thread_main_demo"


def charter(workspace, campaign):
    doc = {"title": "Token sharing", "summary": "s", "text": "", "assumptions": [], "waivers": [], "references": [], "citations": [], "constraints": [], "metrics": [], "tables": {}, "instances": [],
           "objective": None, "evaluator": None, "forked_from": None,
           "quantities": {"n_users": {"description": "People", "kind": "integer", "role": "input", "value": 10, "expression": None, "units": "1", "range": [1, None], "origin": "source", "accepted": False, "note": ""},
                          "monthly_budget_tokens": {"description": "Tokens", "kind": "integer", "role": "input", "value": None, "expression": None, "units": "token", "range": [0, None], "origin": "source", "accepted": False, "note": ""},
                          "per_user": {"description": "Each", "kind": "number", "role": "derived", "value": None, "expression": "monthly_budget_tokens / n_users", "units": "token", "range": None, "origin": "computed", "accepted": False, "note": ""}},
           "variables": [{"name": "daily_cap", "description": "d", "representation": "continuous", "shape": [], "lower": 0.0, "upper": None, "values": [], "units": "token/day", "meaning": "m", "layout": ""}],
           "questions": [{"id": "value_scoring", "question": "How is value scored?", "options": ["Discrete", "Currency"], "about": [], "answer": None, "answered_at": None, "sent": False, "blocking": True}]}
    record = workspace.charters.create(doc, source={"kind": "test", "id": "t", "name": "t"}, by="researcher", rationale="test")
    record["campaign_ids"] = [campaign["id"]]
    workspace.store.put(CHARTER_KIND, record)
    return record


def test_a_panel_is_validated_against_the_catalog_and_its_bindings(client, workspace, campaign):
    cid = campaign["id"]
    ch = charter(workspace, campaign)
    good = {"title": "Seats", "page": "#note/charter", "components": [
        {"type": "markdown", "text": "Set the budget."},
        {"type": "number", "id": "budget", "label": "Monthly budget", "bind": {"charter": ch["id"], "path": "quantities.monthly_budget_tokens.value"}, "min": 0},
        {"type": "kv", "rows": [{"label": "Per user", "bind": {"charter": ch["id"], "value": "per_user"}}, {"label": "Fixed", "value": 3}]},
        {"type": "select", "id": "scoring", "label": "Value scoring", "bind": {"charter": ch["id"], "question": "value_scoring"}, "options": [{"value": "Discrete"}, {"value": "Currency"}]},
        {"type": "section", "title": "More", "children": [{"type": "link", "label": "Charter", "page": "#note/charter"}, {"type": "button", "id": "gen", "label": "Three strategies", "command": {"operation": "research.generate", "payload": {"count": 3}}}]},
    ]}
    service.validate(workspace, cid, good)
    for bad, why in [
        ({**good, "components": [{"type": "widget"}]}, "components/0"),
        ({**good, "components": [{"type": "number", "id": "x", "label": "x", "bind": {"charter": ch["id"], "path": "quantities.nope.value"}}]}, "No quantity nope"),
        ({**good, "components": [{"type": "number", "id": "x", "label": "x", "bind": {"charter": ch["id"], "path": "quantities.per_user.value"}}]}, "derived"),
        ({**good, "components": [{"type": "number", "id": "x", "label": "x", "bind": {"charter": ch["id"], "path": "variables.3.lower"}}]}, "No variable 3"),
        ({**good, "components": [{"type": "button", "id": "b", "label": "b", "command": {"operation": "nothing.here"}}]}, "not a command operation"),
        ({**good, "components": [{"type": "button", "id": "b", "label": "b", "command": {"operation": "agent.control"}}]}, "not a button's"),
        ({**good, "components": [{"type": "table", "columns": [{"key": "secret"}], "source": {"kind": "hypothesis"}}]}, "unknown field"),
        ({**good, "components": [{"type": "number", "id": "d", "label": "a", "bind": {"charter": ch["id"], "path": "quantities.n_users.value"}}, {"type": "number", "id": "d", "label": "b", "bind": {"charter": ch["id"], "path": "quantities.n_users.value"}}]}, "used twice"),
        ({**good, "page": "#nowhere"}, "page"),
    ]:
        with pytest.raises(ValueError, match=why):
            service.validate(workspace, cid, bad)


def test_bindings_resolve_from_records_and_fields_write_through_the_charter(client, workspace, campaign):
    cid = campaign["id"]
    ch = charter(workspace, campaign)
    hyp = command(client, "hypothesis.create", cid, {"title": "Proportional rule", "mechanism": "m", "rationale": "r"}, campaign["version"], origin={"thread_id": MAIN})["outcome"]["hypothesis"]
    panel = service.create(workspace, cid, {"title": "Seats", "page": "#note/charter", "components": [
        {"type": "number", "id": "budget", "label": "Monthly budget", "bind": {"charter": ch["id"], "path": "quantities.monthly_budget_tokens.value"}, "min": 0},
        {"type": "number", "id": "upper", "label": "Daily cap upper", "bind": {"charter": ch["id"], "path": "variables.0.upper"}},
        {"type": "kv", "id": "facts", "rows": [{"label": "Per user", "bind": {"charter": ch["id"], "value": "per_user"}}, {"label": "Title", "record": {"id": hyp["id"], "field": "title"}}]},
        {"type": "select", "id": "scoring", "label": "Value scoring", "bind": {"charter": ch["id"], "question": "value_scoring"}, "options": [{"value": "Discrete"}, {"value": "Currency"}]},
        {"type": "table", "id": "proposals", "columns": [{"key": "title", "label": "Title"}, {"key": "status"}], "source": {"kind": "hypothesis"}},
        {"type": "chart", "id": "curve", "source": {"hypothesis": hyp["id"]}},
    ]}, author="researcher")
    response = client.get(f"/api/v1/panels/{panel['id']}")
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["data"]["budget"]["value"] is None and view["data"]["upper"]["value"] is None and view["data"]["upper"]["name"] == "daily_cap"
    assert view["data"]["facts"]["rows"][0]["value"] is None and view["data"]["facts"]["rows"][1]["value"] == "Proportional rule"
    assert view["data"]["proposals"]["rows"] == [{"title": "Proportional rule", "status": "proposed"}]
    assert view["data"]["curve"]["points"] == [] and view["data"]["scoring"]["options"] == ["Discrete", "Currency"]
    # Setting a field goes through the charter: a receipt in its history, derived values follow.
    set_budget = client.post(f"/api/v1/panels/{panel['id']}/set", json={"component_id": "budget", "value": 120000000})
    assert set_budget.status_code == 200, set_budget.text
    assert set_budget.json()["data"]["budget"]["value"] == 120000000 and set_budget.json()["data"]["facts"]["rows"][0]["value"] == 12000000
    charter_view = workspace.charters.view(ch["id"])
    assert charter_view["history"][-1]["rationale"] == "Set Monthly budget on the panel Seats" and charter_view["charter"]["quantities"]["monthly_budget_tokens"]["origin"] == "researcher"
    assert client.post(f"/api/v1/panels/{panel['id']}/set", json={"component_id": "budget", "value": -5}).status_code == 422
    assert client.post(f"/api/v1/panels/{panel['id']}/set", json={"component_id": "budget", "value": "lots"}).status_code == 422
    assert client.post(f"/api/v1/panels/{panel['id']}/set", json={"component_id": "scoring", "value": "Discrete"}).json()["data"]["scoring"]["value"] == "Discrete"
    assert workspace.charters.view(ch["id"])["charter"]["questions"][0]["answer"] == "Discrete"
    assert client.post(f"/api/v1/panels/{panel['id']}/set", json={"component_id": "scoring", "value": "Other"}).status_code == 422
    listing = client.get(f"/api/v1/campaigns/{cid}/panels", params={"page": "#note/charter"}).json()["panels"]
    assert [p["id"] for p in listing] == [panel["id"]]
    assert client.get(f"/api/v1/campaigns/{cid}/panels", params={"page": "#note"}).json()["panels"] == [], "a page shows its own and its sub pages' panels, not the other way round"
    assert [p["id"] for p in client.get(f"/api/v1/campaigns/{cid}/panels", params={"page": "#note/charter/x"}).json()["panels"]] == [], "an unknown sub page has no panels"
    client.post(f"/api/v1/panels/{panel['id']}/retire")
    assert client.get(f"/api/v1/campaigns/{cid}/panels").json()["panels"] == []


def test_the_lead_composes_a_panel_in_its_thread_and_the_thread_shows_a_card(client, workspace, campaign, monkeypatch):
    cid = campaign["id"]
    ch = charter(workspace, campaign)
    lead = activate_team(client, workspace, campaign, monkeypatch)
    receipt = command(client, "agent.message", cid, {"message": "Give me an input panel for the seats.", "thread_id": MAIN}, campaign["version"], origin={"thread_id": MAIN})
    run = submitted(workspace, "pi_run_" + receipt["id"])
    made = tool_call(workspace, lead, run, "panel_render", {"title": "Seat budget", "page": "#note/charter", "components": [
        {"type": "number", "id": "budget", "label": "Monthly budget", "bind": {"charter": ch["id"], "path": "quantities.monthly_budget_tokens.value"}}]}, call_id="p1")
    assert made["panel_id"].startswith("panel_") and made["link"] == f"#note/charter?sel={made['panel_id']}"
    record = workspace.store.get(made["panel_id"], "panel")
    assert record["author"] == "lead" and record["thread_id"] == MAIN and record["revision"] == 1
    messages = client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"]
    card = [m for m in messages if m.get("kind") == "panel_link"]
    assert len(card) == 1 and card[0]["panel_id"] == made["panel_id"] and "Seat budget" in card[0]["content"]
    revised = tool_call(workspace, lead, run, "panel_render", {"panel_id": made["panel_id"], "title": "Seat budget (v2)", "page": "#note/charter", "components": [
        {"type": "markdown", "text": "Set the budget."}]}, call_id="p2")
    assert revised["revision"] == 2 and workspace.store.get(made["panel_id"], "panel")["title"] == "Seat budget (v2)"
    assert len([m for m in client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"] if m.get("kind") == "panel_link"]) == 1, "a revision is not announced again"
    bad = tool_call(workspace, lead, run, "panel_render", {"title": "x", "page": "#note/charter", "components": [{"type": "button", "id": "b", "label": "b", "command": {"operation": "agent.control"}}]}, call_id="p3")
    assert "not a button's" in str(bad)


def test_the_formulator_composes_a_charter_panel_through_the_workspace_hook(client, workspace, campaign):
    cid = campaign["id"]
    ch = charter(workspace, campaign)
    ch["campaign_ids"] = []
    workspace.store.put(CHARTER_KIND, ch)
    note = {"id": "note_panel", "campaign_id": cid, "thread_id": MAIN, "title": "t", "current_revision": 1, "adopted_revision": 1, "charter_id": ch["id"], "import_id": None, "status": "adopted", "created_at": now(), "updated_at": now()}
    workspace.store.put("problem_note", note)
    assert workspace.panels.campaign_of_charter(ch["id"]) == cid
    saved = workspace.panels.create(cid, {"title": "Seats", "page": "#note/charter", "components": [{"type": "markdown", "text": "hi"}]}, author="formulator", agent_id="import_x", run_id="r1")
    assert saved["author"] == "formulator" and saved["page"] == "#note/charter"
    assert [p["id"] for p in client.get(f"/api/v1/campaigns/{cid}/panels", params={"page": "#note/charter"}).json()["panels"]] == [saved["id"]]
