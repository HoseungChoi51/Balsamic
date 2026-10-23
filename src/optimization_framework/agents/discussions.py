"""The exchange between the agents that run review rounds and their assistants, read from what each of them saved.

Nothing here is written by a model for this view and nothing is stored: a round is the assistants that the
lead or the discussion moderator created in one turn, each with its assignment, its own closing summary, its
reply, its verdicts and the response of whoever asked it.
"""
import json

from optimization_framework.contracts.base import content_hash
from .models import LEAD, NOTICE, PAGE_AGENTS

TEXT_LIMIT = 20000
ROUND_LIMIT = 40


def cut(text):
    text = text or ""
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "\n\n[cut: the saved record holds the rest]"


def request_text(run):
    """The researcher's own words of a request turn, without what the platform appended."""
    return run["input"].split("\nResearch request details: ", 1)[0]


def view(workspace, campaign_id):
    store = workspace.store
    store.get(campaign_id, "campaign")
    sessions = {agent["id"]: agent for agent in store.list("agent_session", campaign_id)}
    lead = next((agent for agent in sessions.values() if agent["role"] == LEAD), None)
    # The agents in charge of pages are not a round's assistants: the moderator runs rounds, the others do other work.
    assistants = [agent for agent in sessions.values() if agent.get("parent_agent_id") and agent["role"] not in PAGE_AGENTS]
    if not lead or not assistants:
        return {"rounds": [], "earlier_rounds": 0, "proposals": [], "unreviewed_proposals": 0}
    runs = {run["id"]: run for run in store.list("agent_run", campaign_id)}
    by_agent = {}
    for run in runs.values():
        by_agent.setdefault(run["agent_id"], []).append(run)
    with store.connection() as db:
        delegations = db.execute("SELECT json_extract(data,'$.agent_id') AS agent_id, json_extract(data,'$.run_id') AS run_id, "
            "json_extract(data,'$.arguments.request_key') AS request_key FROM records WHERE kind='agent_tool_intent' AND campaign_id=? "
            "AND json_extract(data,'$.tool')='delegate' ORDER BY rowid", (campaign_id,)).fetchall()
        artifacts = db.execute("SELECT id, json_extract(data,'$.agent_id') AS agent_id, json_extract(data,'$.run_id') AS run_id, "
            "json_extract(data,'$.kind') AS kind, json_extract(data,'$.title') AS title, json_extract(data,'$.created_at') AS created_at, "
            "CASE WHEN json_extract(data,'$.kind')='proposal_review' THEN json_extract(data,'$.content') END AS review "
            "FROM records WHERE kind='agent_artifact' AND campaign_id=? ORDER BY rowid", (campaign_id,)).fetchall()
        # Which agent's turn created each proposal: its hypothesis.create receipt.
        created = {row["hypothesis_id"]: (row["agent_id"], row["run_id"]) for row in db.execute(
            "SELECT json_extract(data,'$.result.outcome.hypothesis_id') AS hypothesis_id, json_extract(data,'$.agent_id') AS agent_id, "
            "json_extract(data,'$.run_id') AS run_id FROM records WHERE kind='agent_tool_receipt' AND campaign_id=? "
            "AND json_extract(data,'$.tool')='campaign_command' AND json_extract(data,'$.result.request.operation')='hypothesis.create' ORDER BY rowid",
            (campaign_id,)).fetchall() if row["hypothesis_id"]}
    # The turn of the lead or the moderator in which each assistant was created (the identity is derived as the delegate tool derives it).
    created_in = {"agent_" + content_hash([row["agent_id"], row["request_key"]])[:30]: row["run_id"] for row in delegations}
    hypotheses = {record["id"]: record for record in store.list("hypothesis", campaign_id)}

    groups = {}
    for agent in sorted(assistants, key=lambda item: item["created_at"]):
        groups.setdefault(created_in.get(agent["id"]) or "alone_" + agent["id"], []).append(agent)
    round_of_agent = {agent["id"]: number for number, members in enumerate(groups.values(), 1) for agent in members}
    reply_turn = {}   # the asking agent's turn woken by an assistant's finished turn -> that assistant
    for agent in assistants:
        for run in by_agent.get(agent["id"], []):
            reply_turn["pi_child_result_" + content_hash(run["id"])[:28]] = agent["id"]

    rounds, round_of_turn = [], {}   # the turns of a round's owner (the one that asked, and those its answers woke) -> round
    for number, (run_id, members) in enumerate(groups.items(), 1):
        turn = runs.get(run_id)
        owner = sessions.get(turn["agent_id"]) if turn else None
        owner = owner or lead
        if turn is None:
            trigger = {"kind": "unknown"}
        elif turn["id"].startswith("page_request_"):
            trigger = {"kind": "lead", "text": cut(turn["input"])}   # the lead asked the moderator for this round
        elif not turn["input"].startswith(NOTICE):
            trigger = {"kind": "request", "text": cut(request_text(turn))}
        else:
            trigger = {"kind": "continued", "round": round_of_agent.get(reply_turn.get(run_id))}
        owner_turns = {run_id}
        people = []
        for agent in members:
            turns = []
            for run in sorted(by_agent.get(agent["id"], []), key=lambda item: item["created_at"]):
                notice, result = run["input"].startswith(NOTICE), run.get("result") or {}
                response = runs.get("pi_child_result_" + content_hash(run["id"])[:28])
                if response:
                    owner_turns.add(response["id"])
                if notice and not result.get("text"):
                    continue   # a platform notice that produced nothing to read
                turns.append({"run_id": run["id"], "created_at": run["created_at"], "status": run["status"],
                    "kind": "assignment" if run["id"] == "assignment_" + agent["id"] else "notice" if notice else "follow_up",
                    "asked": None if notice or run["input"] == agent["objective"] else cut(run["input"]),
                    "delivered_while_working": result.get("delivery") == "steering_queued",
                    "summary": (run.get("disposition") or {}).get("summary"), "reply": cut(result.get("text")), "error": run.get("error"),
                    "response": None if not response else {"run_id": response["id"], "created_at": response["created_at"], "status": response["status"],
                        "summary": (response.get("disposition") or {}).get("summary"), "text": cut((response.get("result") or {}).get("text"))}})
            verdicts, documents = [], []
            for row in artifacts:
                if row["agent_id"] != agent["id"]:
                    continue
                if row["kind"] == "proposal_review":
                    review = json.loads(row["review"] or "{}")
                    verdicts.append({"artifact_id": row["id"], "created_at": row["created_at"], "hypothesis_id": review.get("hypothesis_id"),
                        "title": hypotheses.get(review.get("hypothesis_id"), {}).get("title"), "verdict": review.get("verdict"),
                        "rationale": review.get("rationale"), "required_changes": review.get("required_changes") or [],
                        "suggested_tests": review.get("suggested_tests") or []})
                else:
                    documents.append({"id": row["id"], "kind": row["kind"], "title": row["title"], "created_at": row["created_at"]})
            people.append({"agent_id": agent["id"], "role": agent["role"], "model": agent.get("model"), "status": agent["status"],
                "created_at": agent["created_at"], "assignment": cut(agent["objective"]), "turns": turns, "verdicts": verdicts, "documents": documents,
                # The result it submitted in its role's schema (agents/roles), which whoever asked reads and synthesizes.
                "output": agent.get("output"), "output_schema": bool(agent.get("output_schema"))})
        round_of_turn.update({identity: number for identity in owner_turns})
        rounds.append({"number": number, "run_id": run_id if turn else None, "started_at": members[0]["created_at"], "trigger": trigger,
            "owner": owner["role"], "active": any(agent["status"] in {"queued", "running"} for agent in members), "assistants": people,
            "owner_documents": [{"id": row["id"], "kind": row["kind"], "title": row["title"], "created_at": row["created_at"]}
                                for row in artifacts if row["agent_id"] == owner["id"] and row["run_id"] in owner_turns and row["kind"] != "mask"]})

    # How each proposal fared: a proposal and its revisions, with the verdicts each received, in order.
    verdict_round = {row["id"]: round_of_agent.get(row["agent_id"]) for row in artifacts if row["kind"] == "proposal_review"}
    def root(record, seen=()):
        parent = next((hypotheses[key] for key in record.get("parent_ids") or [] if key in hypotheses and key not in seen), None)
        return root(parent, (*seen, record["id"])) if parent else record
    lineages = {}
    for record in sorted(hypotheses.values(), key=lambda item: item.get("created_at") or ""):
        lineages.setdefault(root(record)["id"], []).append(record)
    def origin(record):
        """The round whose turn created a revision and the role of the agent that did; none for one the researcher created."""
        agent_id, run_id = created.get(record["id"], (None, None))
        return {"created_in_round": round_of_turn.get(run_id), "created_by": sessions[agent_id]["role"] if agent_id in sessions else None}
    proposals, unreviewed = [], 0
    for members in lineages.values():
        revisions = [{"id": record["id"], "title": record.get("title"), "status": record.get("status"), "created_at": record.get("created_at"),
            "parent_ids": [key for key in record.get("parent_ids") or [] if key in hypotheses], **origin(record),
            "verdicts": [{"verdict": review["verdict"], "author": review.get("author"), "created_at": review.get("created_at"),
                          "round": verdict_round.get(review.get("id"))} for review in record.get("reviews") or [] if review.get("verdict")]}
            for record in members]
        reviewed = any(revision["verdicts"] for revision in revisions)
        unreviewed += not reviewed
        # Unreviewed proposals are listed too, for the graph of how proposals came about; the table shows the reviewed ones.
        proposals.append({"id": members[-1]["id"], "title": members[-1].get("title"), "status": members[-1].get("status"), "reviewed": reviewed, "revisions": revisions})
    return {"rounds": rounds[-ROUND_LIMIT:][::-1], "earlier_rounds": max(0, len(rounds) - ROUND_LIMIT),
            "proposals": proposals, "unreviewed_proposals": unreviewed}
