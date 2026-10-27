"""A mandate's model-spend envelope (roadmap R5): each model call names its run and the researcher's request that run serves, a
mandate's spend is the sum of its own request's calls, and turns under a spent envelope hold with one card to raise it, while
the campaign's cap still holds every turn."""
import pytest

from optimization_framework.agents import usage
from optimization_framework.agents.tools import PiTools
from optimization_framework.agents.turn_state import build
from optimization_framework.campaigns import mandates
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace
from optimization_framework.storage.sqlite import now


class Client:
    def __init__(self): self.submissions = []
    def status(self): return {"configured": True}
    def inspect(self, agent_id, after=0): return {"runs": {}, "events": [], "cursor": after, "session_id": "exact"}
    def submit(self, agent, run): self.submissions.append(run["id"])
    def control(self, *args): return {}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_ENABLED", "true")
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Envelope", compute_budget_seconds=100, validation_reserve_seconds=10, llm_budget_usd=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    workspace.commands.execute(Command(id="activate", campaign_id=campaign["id"], expected_revision=1, operation="agent.activate", payload={}))
    for thread in ("thread_a", "thread_b"):
        workspace.store.put("thread", {"id": thread, "campaign_id": campaign["id"], "title": thread, "guidance_revision": 0})
    workspace.pi.client = Client()
    lead = workspace.store.get(workspace.pi.configuration(campaign["id"])["lead_id"], "agent_session")
    return workspace, campaign["id"], lead


def call(seq, cost, run_id=None, billing="api"):
    return {"seq": seq, "occurred_at": now(), "type": "assistant.message", "text": "done", "provider": "deepseek", "model": "deepseek-v4-pro",
            "billing": billing, **({"run_id": run_id} if run_id else {}),
            "usage": {"input": 10, "output": 2, "cacheRead": 0, "cacheWrite": 0, "reasoning": 0, "totalTokens": 12, "cost_usd": cost}}


def receive(workspace, agent_id, *events):
    workspace.pi._receive(agent_id, {"runs": {}, "cursor": events[-1]["seq"], "events": list(events)})


def ask(workspace, campaign_id, thread_id, identity, text="Screen the methods"):
    run = workspace.pi.message(campaign_id, {"message": text, "thread_id": thread_id}, identity)
    return run, workspace.pi.request_root(run)


def rows(workspace, campaign_id):
    with workspace.store.connection() as db:
        return [dict(row) for row in db.execute("SELECT agent_id, run_id, root_thread_id, root_message_id, root_run_id, charged_usd "
                                                "FROM llm_usage WHERE campaign_id=? ORDER BY id", (campaign_id,)).fetchall()]


def test_usage_rows_carry_their_run_and_request_and_a_mandate_sums_its_own_and_nothing_else(lab):
    workspace, cid, lead = lab
    first, root_a = ask(workspace, cid, "thread_a", "ask_a")
    first.update(status="running"); workspace.store.put("agent_run", first)
    # The lead's call names no run (an older harness): it is the lead's run at work.
    receive(workspace, lead["id"], call(1, 0.25))
    # An assistant the lead sent for this request counts under it, by its own run.
    child = workspace.pi.create_agent(cid, "methodology_specialist", "Review", "child_a", parent_id=lead["id"])
    child["assignment_origin"] = root_a; workspace.store.put("agent_session", child)
    task = workspace.pi.enqueue(child, "assignment_child_a", "Review the methods")
    receive(workspace, child["id"], call(1, 0.5, run_id=task["id"]))
    first.update(status="completed"); workspace.store.put("agent_run", first)
    # Another request, asked of a page agent from thread B, counts under that request only.
    planner = workspace.pi.page_agent(cid, "experiment_operator")
    other = workspace.pi.message(cid, {"message": "Plan the runs", "thread_id": "thread_b", "page_agent": "experiment_operator"}, "ask_b")
    receive(workspace, planner["id"], call(1, 2.0, run_id=other["id"]))
    # A call in no request, and a subscription call, count under none.
    receive(workspace, lead["id"], call(2, 4.0), call(3, 9.0, billing="subscription"))
    recorded = rows(workspace, cid)
    assert [(row["agent_id"], row["run_id"], row["root_thread_id"], row["root_message_id"]) for row in recorded[:3]] == [
        (lead["id"], first["id"], "thread_a", "message_ask_a"), (child["id"], task["id"], "thread_a", "message_ask_a"),
        (planner["id"], other["id"], "thread_b", "message_ask_b")]
    assert [(row["run_id"], row["root_thread_id"]) for row in recorded[3:]] == [(None, None), (None, None)]
    mandate = mandates.grant(workspace, cid, "explore", root=root_a, model_usd=2.0)
    assert mandate.used.model_usd == pytest.approx(0.75) and mandates.model_left(mandate) == pytest.approx(1.25)
    assert usage.spent(workspace.store, cid, {"thread_id": "thread_b", "message_id": "message_ask_b"}) == pytest.approx(2.0)
    assert usage.charged(workspace.store, cid) == pytest.approx(6.75)
    # A standing mandate counts the campaign's calls from its grant on.
    standing = mandates.grant(workspace, cid, "explore", model_usd=5.0)
    receive(workspace, lead["id"], call(4, 0.5))
    assert mandates.read(workspace, workspace.store.get(standing.id, "mandate")).used.model_usd == pytest.approx(0.5)


def test_a_table_from_before_runs_were_recorded_gains_the_columns_and_its_rows_name_none(tmp_path):
    workspace = Workspace(tmp_path)
    with workspace.store.connection() as db:
        db.execute("DROP TABLE llm_usage")
        db.execute(usage.SCHEMA[0].split(", run_id TEXT")[0] + ")")
        db.execute("INSERT INTO llm_usage(event_key, campaign_id, agent_id, billing, input, output, cache_read, cache_write, reasoning, "
                   "total_tokens, charged_usd, occurred_at) VALUES ('old', 'campaign_x', 'pi_x', 'api', 1, 1, 0, 0, 0, 2, 0.5, ?)", (now(),))
    usage.ensure(workspace.store)
    with workspace.store.connection() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(llm_usage)").fetchall()}
    assert set(usage.ROOT_COLUMNS) <= columns
    assert usage.charged(workspace.store, "campaign_x") == 0.5
    assert usage.spent(workspace.store, "campaign_x", {"thread_id": "thread_a", "message_id": "message_a"}) == 0


def test_turns_under_a_spent_envelope_hold_with_one_card_and_go_on_once_it_is_raised(lab):
    workspace, cid, lead = lab
    first, root = ask(workspace, cid, "thread_a", "ask_a")
    mandate = mandates.grant(workspace, cid, "explore", root=root, model_usd=1.0)
    first.update(status="running"); workspace.store.put("agent_run", first)
    state = PiTools(workspace.pi).turn_state(lead["id"], first["id"])["text"]
    assert f"Mandate: explore ({mandate.id}); model spend $1.00 left of $1.00;" in state
    receive(workspace, lead["id"], call(1, 1.0))
    first.update(status="completed"); workspace.store.put("agent_run", first)
    assert mandates.read(workspace, workspace.store.get(mandate.id, "mandate")).status == "exhausted"
    # A notice continuing the spent request waits (another request does not: the next test).
    notice = workspace.pi.enqueue(lead, "pi_events_spent", "[notice] A run finished.", root=root)
    workspace.pi._sync(cid)
    assert workspace.pi.client.submissions == [] and workspace.store.get(notice["id"], "agent_run")["status"] == "queued"
    workspace.pi._sync(cid)
    cards = [row for row in workspace.store.list("decision", cid) if (row.get("approval_request") or {}).get("kind") == "mandate_model"]
    assert len(cards) == 1 and cards[0]["approval_request"] == {"kind": "mandate_model", "mandate_id": mandate.id, "model_usd": 2.0}
    assert "$1.00 of the $1.00" in cards[0]["rationale"] and cards[0]["status"] == "pending"
    state = build(PiTools(workspace.pi), lead, workspace.store.get(notice["id"], "agent_run"))["text"]
    assert "$0.00 left of $1.00 (spent: new turns under this request wait for the researcher)" in state
    # Raising it is the researcher's choice on the card; the turn then goes.
    workspace.commands.execute(Command(id="raise", campaign_id=cid, expected_revision=workspace.store.get(cid, "campaign")["version"],
        operation="decision.resolve", payload={"decision_id": cards[0]["id"], "choice": "0", "comment": "", "expected_resolution_revision": 0}), actor="researcher")
    raised = mandates.read(workspace, workspace.store.get(mandate.id, "mandate"))
    assert (raised.model_usd, raised.status, workspace.store.get(cards[0]["id"], "decision")["status"]) == (2.0, "active", "resolved")
    assert workspace.store.get(mandate.id, "mandate")["raises"][0]["decision_id"] == cards[0]["id"]
    workspace.pi._sync(cid)
    assert workspace.pi.client.submissions == [notice["id"]]


def test_another_request_runs_beside_a_spent_one_and_the_campaign_cap_still_holds_without_a_mandate(lab):
    workspace, cid, lead = lab
    first, root = ask(workspace, cid, "thread_a", "ask_a")
    mandates.grant(workspace, cid, "explore", root=root, model_usd=0.5)
    first.update(status="running"); workspace.store.put("agent_run", first)
    receive(workspace, lead["id"], call(1, 0.5))
    first.update(status="completed"); workspace.store.put("agent_run", first)
    second, _ = ask(workspace, cid, "thread_b", "ask_b", "What did the last run show?")
    workspace.pi._sync(cid)
    assert workspace.pi.client.submissions == [second["id"]]
    second.update(status="completed"); workspace.store.put("agent_run", second)
    # At the campaign's cap a request with no mandate holds too, as before.
    workspace.store.put("campaign", {**workspace.store.get(cid, "campaign"), "llm_budget_usd": 0.5})
    third, _ = ask(workspace, cid, "thread_b", "ask_c", "And the one before?")
    workspace.pi._sync(cid)
    assert workspace.pi.client.submissions == [second["id"]] and workspace.store.get(third["id"], "agent_run")["status"] == "queued"
    assert any(issue["code"] == "llm_budget" for issue in workspace.store.list("manager_issue", cid))
    assert not [row for row in workspace.store.list("decision", cid) if (row.get("approval_request") or {}).get("kind") == "mandate_model"]


def test_a_mandate_without_an_envelope_never_holds_and_the_state_block_says_the_cap_applies(lab):
    workspace, cid, lead = lab
    first, root = ask(workspace, cid, "thread_a", "ask_a")
    mandate = mandates.grant(workspace, cid, "explore", root=root)
    receive(workspace, lead["id"], call(1, 3.0, run_id=first["id"]))
    assert mandates.hold(workspace, cid, root) is None
    state = build(PiTools(workspace.pi), lead, first)["text"]
    assert f"Mandate: explore ({mandate.id}); model spend without an envelope of its own (the campaign's cap applies);" in state
