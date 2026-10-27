"""A campaign with a started team has its reports written on the lead agent's model, through the agent service, billed to the campaign."""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from pydantic import BaseModel

from optimization_framework.agents import usage as llm_usage
from optimization_framework.agents.tools import PiTools
from balsamic.app import create_app
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.reports import editorial
from optimization_framework.reports.writer import ReportWriter
from optimization_framework.llm.adapter import LLMAdapter, structured_reply
from test_report_pipeline import scripted_model

SCHEMAS = {schema.__name__: schema for schema in (editorial.Brief, editorial.Investigation, editorial.Selection, editorial.Draft, editorial.Review)}
EVIDENCE = {"outcome": "Unequal budgets; unfinished learning; observed short-run advantage"}


class Harness:
    """The agent service: one signed-in model with a price, and single calls answered by the scripted editorial roles."""
    def __init__(self, respond, cost=0.01):
        self.respond, self.cost, self.calls, self.fail_at, self.entries, self.max_tokens = respond, cost, [], None, {}, 32000

    def status(self):
        return {"configured": True, "providers": {"openai-codex": {"auth": "api_key", "billing": "api"}},
            "models": [{"provider": "openai-codex", "id": "gpt-6-astra", "name": "Astra", "reasoning": True, "thinking_levels": ["off", "high", "xhigh"],
                        "context_window": 400000, "max_tokens": self.max_tokens, "cost": {"input": 0.5, "output": 2.0}}]}

    def inspect(self, agent_id, after=0):
        return None

    def live(self, ids):
        return {identity: self.entries[identity] for identity in ids if identity in self.entries}

    def complete(self, call_id, body, timeout=1800):
        self.calls.append({"call_id": call_id, **{key: body[key] for key in ("provider", "model", "effort", "label", "max_tokens")}})
        if self.fail_at == len(self.calls):
            raise ValueError("Provider request failed")
        schema = SCHEMAS[json.loads(body["system"].split("Return JSON matching: ", 1)[1])["title"]]
        result = self.respond(SimpleNamespace(usage={"calls": 0, "subscription_calls": 0}), body["label"], body["system"], json.loads(body["prompt"]), result_type=schema)
        return {"text": "Here is the result.\n```json\n" + result.model_dump_json() + "\n```", "stop_reason": "stop", "provider": "openai-codex",
            "model": "gpt-6-astra", "billing": "api", "thinking_level": "xhigh", "occurred_at": "2026-10-14T03:00:00+00:00",
            "usage": {"input": 1200, "output": 300, "cacheRead": 50, "cacheWrite": 0, "reasoning": 100, "totalTokens": 1650, "cost_usd": self.cost}}


@pytest.fixture
def team(tmp_path, monkeypatch):
    """A campaign whose agent team is started, with no earlier research provider on the server."""
    monkeypatch.setenv("GRATING_LLM_ENABLED", "true")
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    monkeypatch.delenv("GRATING_LLM_PROVIDER", raising=False)
    # The scripted editorial roles of the pipeline tests answer; here they are reached through the real adapter.
    original = LLMAdapter.call_with_prompt
    scripted_model(monkeypatch)
    respond = LLMAdapter.call_with_prompt
    monkeypatch.setattr(LLMAdapter, "call_with_prompt", original)
    monkeypatch.setattr(ReportWriter, "launch", lambda self, job, background=True: (self.execute(job), self.store.get(job["id"], "report_writer_job"))[1])
    app = create_app(tmp_path, start_workers=False)
    workspace = app.state.workspace
    campaign = workspace.create_campaign(CampaignInput(name="Deflector", compute_budget_seconds=100, validation_reserve_seconds=10, llm_budget_usd=1,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    workspace.commands.execute(Command(id="start_team", campaign_id=campaign["id"], expected_revision=1, operation="agent.activate", payload={}))
    workspace.pi.client = Harness(respond)
    lead = workspace.store.get(workspace.pi.configuration(campaign["id"])["lead_id"], "agent_session")
    return SimpleNamespace(app=app, workspace=workspace, store=workspace.store, campaign=campaign, lead=lead, harness=workspace.pi.client,
        write=lambda **kw: workspace.report_writer.start(campaign_id=campaign["id"], evidence=EVIDENCE, brief="ES needs twice the requests.", **kw))


def test_every_stage_runs_on_the_leads_model_and_each_call_is_charged_to_the_campaign(team):
    job = team.write(request_id="first")
    assert job["status"] == "completed" and job["result_id"]
    snapshot = job["provider_snapshot"]
    assert (snapshot["transport"], snapshot["pi_provider"], snapshot["model"], snapshot["billing_mode"]) == ("pi", "openai-codex", "gpt-6-astra", "api")
    # Every stage is one call through the agent service, under the job's identity, on the lead's model and thinking level.
    calls = team.harness.calls
    assert len(calls) == job["usage"]["calls"] >= 8
    assert {(call["call_id"], call["provider"], call["model"], call["effort"]) for call in calls} == {(job["id"], "openai-codex", "gpt-6-astra", team.lead["reasoning_effort"])}
    assert {call["label"] for call in calls} == {"report_editor", "report_evidence_investigator", "technical_report_writer", "report_scientific_reviewer", "report_reader_reviewer"}
    # The stages are listed in order for the page that follows the job.
    assert [(row["key"], row["status"]) for row in job["stage_log"]] == [(key, "completed") for key in
        ("brief", "investigate_1", "investigate_2", "select", "draft", "science", "reader", "edit_1", "verify_1")]
    assert all(row["started_at"] <= row["finished_at"] for row in job["stage_log"])
    # Each call is in the campaign's usage ledger at the harness's price and counts toward its model budget.
    spent = llm_usage.charged(team.store, team.campaign["id"])
    assert spent == pytest.approx(0.01 * len(calls)) == pytest.approx(job["usage"]["api_cost_usd"])
    assert team.workspace.pi.model_allowance(team.campaign["id"]) == pytest.approx(1 - spent)
    summary = llm_usage.summary(team.store, team.campaign["id"], since=None, bucket="hour")
    assert [(row["agent_id"], row["role"], row["calls"]) for row in summary["by_agent"]] == [(job["id"], "report_writer", len(calls))]
    assert job["usage"]["cost_accounting"] == "harness_price_catalogue" and "pending_reservation" not in job["usage"]
    kinds = [row["kind"] for row in team.store.events(team.campaign["id"], limit=1000)]
    assert "report.writer_started" in kinds and "report.writer_completed" in kinds
    # The page is told which model writes and what is left of the budget; the saved job names it too.
    listing = TestClient(team.app).get(f"/api/reports?campaign_id={team.campaign['id']}").json()
    assert listing["writer"] == {"model": "gpt-6-astra", "reasoning_effort": team.lead["reasoning_effort"], "billing_mode": "api", "allowance_usd": pytest.approx(1 - spent)}
    assert (listing["jobs"][0]["model"], listing["jobs"][0]["billing_mode"]) == ("gpt-6-astra", "api") and "provider_snapshot" not in listing["jobs"][0]
    assert listing["reports"][0]["id"] == job["result_id"]


def test_a_stage_the_budget_cannot_cover_is_not_started(team):
    # Upper bound of a call: its prompt counted as tokens at $0.5 per million, plus 32,000 output tokens at $2: about 7 cents.
    team.harness.cost = 0.05
    team.store.put("campaign", {**team.store.get(team.campaign["id"], "campaign"), "llm_budget_usd": 0.2})
    job = team.write(request_id="short")
    assert job["status"] == "failed" and "model budget cannot cover the next stage" in job["error"] and not job.get("result_id")
    assert len(team.harness.calls) == 3 == sum(row["status"] == "completed" for row in job["stage_log"])
    assert llm_usage.charged(team.store, team.campaign["id"]) == pytest.approx(0.15)
    # With nothing left, a new report is refused before any call.
    team.store.put("campaign", {**team.store.get(team.campaign["id"], "campaign"), "llm_budget_usd": 0.15})
    with pytest.raises(ValueError, match="model budget is used up"):
        team.write(request_id="none")
    assert len(team.harness.calls) == 3


def test_a_call_is_capped_and_reserved_at_the_report_bound_not_at_the_models_own_limit(team):
    # A model that may write 384,000 tokens would hold about 77 cents per call at $2 per million; a stage needs far fewer.
    team.harness.max_tokens = 384000
    writer, reserved = team.workspace.report_writer, []
    capture = writer.capture
    writer.capture = lambda job_id, event: (reserved.append(event["reservation"]) if event.get("type") == "provider_call_reserved" else None, capture(job_id, event))[1]
    job = team.write(request_id="capped")
    assert job["status"] == "completed"
    assert {call["max_tokens"] for call in team.harness.calls} == {64000}
    assert len(reserved) == len(team.harness.calls) and {row["output_tokens_reserved"] for row in reserved} == {64000}
    assert max(row["cost_usd_reserved"] for row in reserved) < 0.2
    # A model with a smaller limit keeps its own.
    team.harness.max_tokens, team.harness.calls = 32000, []
    team.write(request_id="small")
    assert {call["max_tokens"] for call in team.harness.calls} == {32000}


def test_a_failed_call_is_not_repeated_and_its_reservation_stands(team):
    team.harness.fail_at = 2
    job = team.write(request_id="broken")
    assert job["status"] == "failed" and "The model call failed: Provider request failed" in job["error"]
    assert len(team.harness.calls) == 2 and [row["status"] for row in job["stage_log"]] == ["completed", "failed"]
    # The second call may have been charged: its upper bound stays in the job's account, marked as not measured.
    assert job["usage"]["api_cost_usd"] > 0.01 and "unknown" in job["usage"]["cost_accounting"]
    assert team.write(request_id="broken")["id"] == job["id"] and len(team.harness.calls) == 2


def test_the_lead_starts_the_writer_and_is_woken_when_the_draft_is_ready(team):
    w, cid = team.workspace, team.campaign["id"]
    run = w.pi.message(cid, {"message": "Make a report of the final round."}, "ask")
    w.store.put("agent_run", {**run, "status": "submitted"})
    tools = PiTools(w.pi)
    assert {"report_write", "report_answer"} <= tools.names(team.lead)
    # The scripted investigator reads one supplied record; the lead's tool passes none, so supply it here.
    start = w.report_writer.start
    w.report_writer.start = lambda **kw: start(**{"evidence": EVIDENCE, **kw})
    started = tools.call(team.lead["id"], run["id"], "c1", "report_write", {"notes": "Requests and solves per run; leave out the unfinished run.", "request_key": "final round"})
    job = w.store.get(started["job_id"], "report_writer_job")
    assert (job["requested_by"], job["input"]["instruction"], started["page"]) == ("lead", "Requests and solves per run; leave out the unfinished run.", "#reports")
    assert started["status"] == "completed" and started["draft"] == "/reports/" + job["result_id"]
    # The same request does not start a second report.
    assert tools.call(team.lead["id"], run["id"], "c2", "report_write", {"notes": "Requests and solves per run; leave out the unfinished run.", "request_key": "final round"})["job_id"] == job["id"]
    # Its end is an outcome of the open request: the lead is woken with the link to the draft.
    w.pi._campaign_events(cid)
    woken = [item for item in w.store.list("agent_run", cid) if item["id"].startswith("pi_events_")]
    assert len(woken) == 1 and "report.writer_completed" in woken[0]["input"] and started["draft"] in woken[0]["input"]
    # The lead reads the job and the draft's text as evidence.
    assert tools.call(team.lead["id"], run["id"], "c3", "evidence_read", {"record_id": job["id"]})["status"] == "completed"
    assert "sections" in json.dumps(tools.call(team.lead["id"], run["id"], "c4", "evidence_read", {"record_id": job["result_id"]}))
    # A report started from the Reports page is the researcher's own: it wakes nobody.
    assert team.write(request_id="from_page")["status"] == "completed"
    w.pi._campaign_events(cid)
    assert len([item for item in w.store.list("agent_run", cid) if item["id"].startswith("pi_events_")]) == 1
    # While a report the lead started is being written, the lead cannot call its request fulfilled.
    w.store.put("report_writer_job", {**job, "id": "report_writer_pending", "status": "awaiting_focus", "question": "Which decision?"})
    refused = tools.call(team.lead["id"], run["id"], "c5", "yield_work", {"disposition": "complete", "summary": "Done."})
    assert "report you started is still being written" in refused["error"]
    with pytest.raises(ValueError, match="another campaign"):
        other = w.create_campaign(CampaignInput(name="Other", compute_budget_seconds=100, validation_reserve_seconds=10,
            tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
        w.store.put("report_writer_job", {**job, "id": "report_writer_elsewhere", "campaign_id": other["id"], "status": "awaiting_focus"})
        tools._execute(team.lead, run, "report_answer", {"job_id": "report_writer_elsewhere", "answer": "Budget"}, "identity")


def test_a_report_the_lead_starts_includes_the_verdicts_and_replies_it_names(team):
    w, cid = team.workspace, team.campaign["id"]
    run = w.pi.message(cid, {"message": "Report on H2 and its review."}, "ask")
    w.store.put("agent_run", {**run, "status": "submitted"})
    tools = PiTools(w.pi)
    hypothesis = w.store.put("hypothesis", {"id": "hypothesis_h2", "campaign_id": cid, "title": "ES beats random search", "status": "proposed"})
    verdict = w.store.put_immutable("agent_artifact", {"id": "artifact_verdict", "campaign_id": cid, "agent_id": "agent_reviewer",
        "title": "Review of H2", "content": {"verdict": "revise", "reasons": ["The basis does the work, not the search."]}})
    reply = w.store.put("agent_run", {"id": "assignment_agent_reviewer", "campaign_id": cid, "agent_id": "agent_reviewer", "status": "completed",
        "result": {"text": "Revise: add a same-basis random baseline."}})
    start = w.report_writer.start
    w.report_writer.start = lambda **kw: start(**{"evidence": {**EVIDENCE, **(kw.pop("evidence", None) or {})}, **kw})
    started = tools.call(team.lead["id"], run["id"], "c1", "report_write", {"notes": "H2 and its review.", "request_key": "h2",
        "reference_ids": [hypothesis["id"], verdict["id"], reply["id"], verdict["id"]]})
    job = w.store.get(started["job_id"], "report_writer_job")
    snapshot = w.store.get(job["snapshot_id"], "report_evidence_snapshot")
    # The writer sees each named agent record under its own id and kind, beside the campaign records it froze itself.
    assert job["references"] == [hypothesis["id"], verdict["id"], reply["id"]]
    assert (snapshot["kinds"][verdict["id"]], snapshot["kinds"][reply["id"]], snapshot["kinds"][hypothesis["id"]]) == ("agent_artifact", "agent_run", "hypothesis")
    assert snapshot["records"][verdict["id"]]["content"]["verdict"] == "revise" and "Fields: agent_records" not in json.dumps(snapshot["records"]["inventory"])
    # Another campaign's record and an unknown id are refused, naming the record.
    other = w.create_campaign(CampaignInput(name="Other", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    w.store.put_immutable("agent_artifact", {"id": "artifact_elsewhere", "campaign_id": other["id"], "title": "Not ours"})
    refused = tools.call(team.lead["id"], run["id"], "c2", "report_write", {"notes": "x", "request_key": "elsewhere", "reference_ids": ["artifact_elsewhere"]})
    assert "not readable within this campaign" in refused["error"]
    assert "No saved record artifact_missing" in tools.call(team.lead["id"], run["id"], "c3", "report_write",
        {"notes": "x", "request_key": "missing", "reference_ids": ["artifact_missing"]})["error"]


def test_the_report_being_written_shows_the_reasoning_of_its_current_call(team):
    w, cid = team.workspace, team.campaign["id"]
    job = team.write(request_id="shown")
    w.store.put("report_writer_job", {**job, "status": "running", "stage": "science"})
    team.harness.entries[job["id"]] = {"run_id": "report_scientific_reviewer", "phase": "thinking", "started_at": "2026-10-14T03:00:00+00:00", "finished_at": None,
        "thinking": "Does claim c1 follow from the receipts?", "text": "", "steps": []}
    assert w.pi.live(cid)["reports"] == [{"job_id": job["id"], "stage": "science", "phase": "thinking", "started_at": "2026-10-14T03:00:00+00:00",
        "thinking": "Does claim c1 follow from the receipts?", "text": ""}]
    # Between two calls there is nothing to show, and a finished job is not listed.
    team.harness.entries[job["id"]]["finished_at"] = "2026-10-14T03:01:00+00:00"
    assert w.pi.live(cid)["reports"] == [{"job_id": job["id"], "stage": "science", "phase": "between calls", "started_at": None, "thinking": "", "text": ""}]
    w.store.put("report_writer_job", job)
    assert w.pi.live(cid)["reports"] == []


def test_a_campaign_without_a_team_keeps_the_earlier_provider_when_one_is_set(team, monkeypatch):
    w = team.workspace
    other = w.create_campaign(CampaignInput(name="No team", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    # No team and no earlier provider: the lead's model would write, but only a team can be started on this server's provider.
    monkeypatch.setattr("optimization_framework.llm.providers.provider_status", lambda: {"configured": True, "model": "fixture-writer", "provider": "codex",
        "billing_mode": "subscription", "pricing_known": False, "transport": "codex_exec"})
    scripted_model(monkeypatch, question="Which focus?")
    job = w.report_writer.start(campaign_id=other["id"], evidence=EVIDENCE, brief="Notes", request_id="old_path")
    assert job["provider_snapshot"]["transport"] == "codex_exec" and team.harness.calls == []


def test_a_json_reply_is_read_from_a_fence_or_from_surrounding_words():
    class Result(BaseModel):
        focus: str
    for text in ('{"focus": "cost"}', '```json\n{"focus": "cost"}\n```', 'Here it is:\n{"focus": "cost"}\nDone.'):
        assert structured_reply(text, Result).focus == "cost"
    with pytest.raises(ValueError):
        structured_reply("No structured result.", Result)


def test_without_any_model_a_new_report_says_what_to_do(team):
    w = team.workspace
    other = w.create_campaign(CampaignInput(name="No team", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    team.harness.status = lambda: {"configured": False, "providers": {}, "models": []}   # nobody is signed in
    with pytest.raises(ValueError, match="Start this campaign's agent team on the Models page"):
        w.report_writer.start(campaign_id=other["id"], evidence=EVIDENCE, brief="Notes", request_id="nothing")
    assert team.harness.calls == [] and not w.store.list("report_writer_job", other["id"])


def test_report_stages_count_under_the_request_that_asked_and_stop_at_its_envelope(team):
    from optimization_framework.campaigns import mandates
    # As in the test above, against the request's envelope instead of the campaign's budget: three stages fit, the fourth does not.
    team.harness.cost = 0.05
    root = {"thread_id": "thread_report", "message_id": "message_report", "run_id": "pi_run_report"}
    mandate = mandates.grant(team.workspace, team.campaign["id"], "explore", root=root, model_usd=0.2)
    job = team.write(request_id="enveloped", run_id="pi_run_report", request_root=root)
    assert job["status"] == "failed" and "request's model-spend envelope cannot cover the next stage" in job["error"]
    assert len(team.harness.calls) == 3 and llm_usage.spent(team.store, team.campaign["id"], root) == pytest.approx(0.15)
    assert mandates.read(team.workspace, team.store.get(mandate.id, "mandate")).used.model_usd == pytest.approx(0.15)
    with team.store.connection() as db:
        assert {tuple(row) for row in db.execute("SELECT run_id, root_message_id FROM llm_usage")} == {("pi_run_report", "message_report")}
