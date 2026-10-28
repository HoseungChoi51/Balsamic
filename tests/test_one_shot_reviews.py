"""A proposal review is one call with an assembled context, not a session with read tools (roadmap T1).

The reviewer's input holds the exact revision, its parents' required changes, the tasks, the installed methods and what the
asker cited, read under the read tools' visibility rule, and never another review of the revision. The verdict is recorded as
proposal_review records it, the asker is told as before, and the call is saved with its exact input."""
import json

from optimization_framework.agents import calls
from optimization_framework.agents.discussions import view
from optimization_framework.agents.tools import PiTools
from optimization_framework.campaigns.proposals import hypothesis_revision, readiness, record_review
from optimization_framework.contracts.base import content_hash
from test_pi_agents import invoke, prepared   # noqa: F401  (the fixture)

VERDICT = {"verdict": "reject", "rationale": "The annealer is not installed and a binary mask contradicts the continuous task.",
           "mechanism_checks": ["The algorithm against the installed methods"], "suggested_tests": ["Restate it with an installed continuous method"]}


class Harness:
    """The agent service: the reviewer's model, signed in with a price, and single calls answered with a verdict."""
    def __init__(self, reply=VERDICT, billing="subscription"):
        self.reply, self.billing, self.calls = reply, billing, []

    def status(self):
        return {"configured": True, "providers": {"openai-codex": {"auth": "oauth", "billing": self.billing}},
                "models": [{"provider": "openai-codex", "id": "gpt-6-astra", "name": "Astra", "reasoning": True, "thinking_levels": ["xhigh"],
                            "context_window": 400000, "max_tokens": 32000, "cost": {"input": 5.0, "output": 20.0}}]}

    def inspect(self, agent_id, after=0):
        return None

    def submit(self, agent, run):
        return {}

    def control(self, *args):
        return {}

    def complete(self, call_id, body, timeout=1800):
        self.calls.append(body)
        return {"text": "```json\n" + json.dumps(self.reply) + "\n```", "stop_reason": "stop", "provider": "openai-codex", "model": body["model"],
                "billing": self.billing, "thinking_level": body.get("effort"), "occurred_at": "2026-10-27T23:00:00+00:00",
                "usage": {"input": 900, "output": 200, "cacheRead": 0, "cacheWrite": 0, "reasoning": 50, "totalTokens": 1100,
                          "cost_usd": 0.0 if self.billing == "subscription" else 0.01}}


def proposal(w, c, identity, **fields):
    return w.store.put("hypothesis", {"id": identity, "campaign_id": c["id"], "title": identity.upper(), "candidate_id": identity.upper(),
        "mechanism": "Anneal a 64-cell binary mask on a quantum annealer.", "rationale": "Annealers find binary optima.",
        "algorithm": "quantum_annealer", "requires_concept_review": True, "status": "proposed", "created_at": "2026-10-27T10:00:00+00:00", **fields})


def reviewed(w, h, reviewer, verdict, changes=()):
    """A verdict an earlier reviewer recorded on the current revision of h."""
    content = {"hypothesis_id": h["id"], "hypothesis_hash": hypothesis_revision(w.store.get(h["id"], "hypothesis")), "verdict": verdict,
               "rationale": f"SECRET-{reviewer}: earlier verdict", "required_changes": list(changes), "suggested_tests": ["One run"]}
    return record_review(w.store, h, content, artifact_id="artifact_" + reviewer, agent_id=reviewer, run_id="run_" + reviewer)


def dispatch(w, c):
    """One scheduling pass, and the call it started run to its end."""
    w.pi._sync(c["id"])
    for name, thread in list(w.research_threads.items()):
        if name.startswith("call_"):
            thread.join(30)


def test_the_third_review_sees_neither_earlier_verdict_and_a_revision_sees_its_parents_required_changes(prepared):
    w, c, lead, _ = prepared
    parent = proposal(w, c, "h1")
    reviewed(w, parent, "r0", "revise", ["Use an installed method", "Match the continuous representation"])
    revision = proposal(w, c, "h1b", title="H1, revised", parent_ids=["h1"])
    first, second = reviewed(w, revision, "r1", "test"), reviewed(w, revision, "r2", "reject", ["Drop the mask"])
    note = PiTools(w.pi).call(lead["id"], prepared[3]["id"], "note", "artifact_save", {"title": "My take on H1b", "kind": "analysis",
                                                                                      "content": "SECRET-note: h1b looks weak"})
    delegated = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review H1B for a short run.", "request_key": "third",
                                              "evidence_ids": [first["id"], second["id"], note["artifact_id"], "h1"]}, "third")
    reviewer = w.store.get(delegated["agent_id"], "agent_session")
    assert (reviewer["one_shot"], reviewer["hypothesis_id"]) == (True, "h1b")   # named by its candidate id in the objective
    content = calls.assemble(w, c["id"], "proposal_reviewer", reviewer["objective"], reviewer["evidence_ids"], "h1b")
    text = json.dumps(content)
    assert "SECRET" not in text and "reviews" not in content["proposal"]
    assert {item["record_id"] for item in content["assignment"]["evidence"] if "not_read" in item} == {first["id"], second["id"], note["artifact_id"]}
    assert content["proposal"]["hypothesis_hash"] == hypothesis_revision(w.store.get("h1b", "hypothesis")) and content["proposal"]["title"] == "H1, revised"
    assert content["parents"] == [{"id": "h1", "title": "H1", "mechanism": parent["mechanism"],
                                   "required_changes": ["Use an installed method", "Match the continuous representation"]}]
    # The parent itself, cited, is read; its reviews are not part of what a reviewer of the revision is given.
    [cited] = [item for item in content["assignment"]["evidence"] if item["record_id"] == "h1"]
    assert cited["kind"] == "hypothesis"
    assert [task["objective"]["name"] for task in content["tasks"]] == ["value"] and content["methods"]
    # The instructions are the brief without its tool lines.
    system = calls.instructions("proposal_reviewer")
    assert "proposal_review" not in system and "campaign_inspect" not in system and "you have no tools" in system


def test_the_verdict_is_recorded_as_before_the_asker_is_told_and_the_call_holds_its_exact_input(prepared):
    w, c, lead, _ = prepared
    h = proposal(w, c, "h1")
    w.pi.client = harness = Harness()
    delegated = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review this proposal.", "request_key": "r",
                                              "hypothesis_id": "h1"}, "review")
    dispatch(w, c)
    [body] = harness.calls
    assert body["label"] == "proposal_reviewer" and body["model"] == "gpt-6-astra"
    run = w.store.get(delegated["run_id"], "agent_run")
    assert run["status"] == "completed" and run["result"]["text"].startswith("Reject: The annealer is not installed")
    # The artifact pins the exact revision, the proposal carries the verdict, and readiness reads it as it always has.
    [artifact] = [row for row in w.store.list("agent_artifact", c["id"]) if row["kind"] == "proposal_review"]
    assert artifact["agent_id"] == delegated["agent_id"] and artifact["run_id"] == run["id"]
    assert artifact["content"]["hypothesis_hash"] == hypothesis_revision(h) and artifact["content"]["verdict"] == "reject"
    assert [review["verdict"] for review in w.store.get("h1", "hypothesis")["reviews"]] == ["reject"]
    assert readiness(w.store, w.store.get("h1", "hypothesis"))["state"] == "revision_required"
    # The Review rounds view lists the reviewer with its verdict.
    [person] = view(w, c["id"])["rounds"][0]["assistants"]
    assert person["role"] == "proposal_reviewer" and [v["verdict"] for v in person["verdicts"]] == ["reject"]
    # The asker gets its notice; a message to the reviewer is refused.
    notice = w.store.get("pi_child_result_" + content_hash(run["id"])[:28], "agent_run")
    assert notice["agent_id"] == lead["id"] and notice["status"] == "queued"
    refused = invoke(prepared, "agent_message", {"agent_id": delegated["agent_id"], "message": "And the seeds?"}, "follow")
    assert "answers once" in refused["error"]
    # The call is saved with exactly what the model was sent, before the verdict was recorded from it.
    call = w.store.get("agent_call_" + run["id"], "agent_call")
    assert call["status"] == "completed" and call["input"] == json.loads(body["prompt"]) and call["instructions"] == body["system"]
    assert call["output"]["verdict"] == "reject" and artifact["content"]["call_id"] == call["id"]
    assert w.store.get(delegated["agent_id"], "agent_session")["status"] == "completed"
    # The call is listed like an agent's call, under the agent.
    from optimization_framework.agents import usage as llm_usage
    assert llm_usage.last_thinking_levels(w.store, c["id"]).get(delegated["agent_id"]) == "xhigh"
    # Another scheduling pass makes no second call.
    dispatch(w, c)
    assert len(harness.calls) == 1


def test_a_call_the_model_budget_cannot_cover_is_refused_before_it_is_made(prepared):
    w, c, lead, _ = prepared
    proposal(w, c, "h1")
    campaign = w.store.get(c["id"], "campaign")
    w.store.put("campaign", {**campaign, "llm_budget_usd": 0.01})
    w.pi.client = harness = Harness(billing="api")
    delegated = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review H1.", "request_key": "r"}, "review")
    dispatch(w, c)
    assert harness.calls == []
    run = w.store.get(delegated["run_id"], "agent_run")
    assert run["status"] == "failed" and "model budget cannot cover this review" in run["error"]
    assert not w.store.get("h1", "hypothesis").get("reviews") and not [row for row in w.store.list("agent_artifact", c["id"]) if row["kind"] == "proposal_review"]
    assert w.store.get("agent_call_" + run["id"], "agent_call")["status"] == "refused"
    # The asker hears that its reviewer failed, and the call is not repeated.
    assert w.store.get("pi_child_result_" + content_hash(run["id"])[:28], "agent_run")["agent_id"] == lead["id"]
    dispatch(w, c)
    assert harness.calls == []


def test_an_invalid_verdict_records_nothing_and_a_restart_does_not_repeat_a_call(prepared):
    w, c, lead, _ = prepared
    proposal(w, c, "h1")
    w.pi.client = harness = Harness(reply={**VERDICT, "verdict": "test", "required_changes": ["Pin the schedule"]})
    delegated = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review H1.", "request_key": "r"}, "review")
    dispatch(w, c)
    run = w.store.get(delegated["run_id"], "agent_run")
    assert len(harness.calls) == 1 and run["status"] == "failed" and "invalid structured result" in run["error"]
    assert not w.store.get("h1", "hypothesis").get("reviews") and w.store.get("agent_call_" + run["id"], "agent_call")["status"] == "failed"
    # A run left in flight by a restart ends failed at the next pass; nothing calls the model again.
    again = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review H1 again.", "request_key": "r2"}, "again")
    w.store.put("agent_run", {**w.store.get(again["run_id"], "agent_run"), "status": "running"})
    dispatch(w, c)
    restarted = w.store.get(again["run_id"], "agent_run")
    assert restarted["status"] == "failed" and "restart" in restarted["error"] and len(harness.calls) == 1


def test_a_reviewer_is_delegated_exactly_one_proposal(prepared):
    w, c, lead, _ = prepared
    proposal(w, c, "h1")
    proposal(w, c, "h2")
    none = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review the proposals.", "request_key": "a"}, "a")
    both = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review H1 and H2.", "request_key": "b"}, "b")
    assert "name it with hypothesis_id" in none["error"] and "(2 named)" in both["error"]
    assert not [a for a in w.store.list("agent_session", c["id"]) if a["role"] == "proposal_reviewer"]
    cited = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review this one.", "request_key": "c", "evidence_ids": ["h2"]}, "c")
    assert w.store.get(cited["agent_id"], "agent_session")["hypothesis_id"] == "h2"
    # Other assistants keep their sessions.
    analyst = invoke(prepared, "delegate", {"role": "skeptical_domain_analyst", "objective": "How could H1 fail?", "request_key": "d"}, "d")
    assert not w.store.get(analyst["agent_id"], "agent_session").get("one_shot")
