"""The state block: what changes between an agent's turns, read from the records at the start of each turn and put before the
turn's message by the harness (POST /api/internal/pi/turn_state).

An agent's system prompt is fixed for its runtime's life, and it must be: a change to it alters the start of every request
and costs the provider's prompt cache for the whole session. So the instructions say only what holds for the role, and what
the campaign is now (the gate, the experiment rules, the resource level, the thread's pins) comes here, every turn, without
asking the model to remember or copy it. Items come in a fixed order, the block is capped, and it carries no wall-clock
time, so the same state gives the same text.
"""
from optimization_framework.contracts.base import content_hash

from .models import LEAD, NOTICE, PAGE_AGENTS

HEADER = "[Workspace state at the start of this turn. Read-only; campaign_inspect has the full records.]"
LIMIT = 3000
QUESTIONS = 5
CUT = "[… the rest is left out; campaign_inspect has it.]"
ASKED_BY = {"researcher": "the researcher, on your page", "platform": "the platform (resource events)"}


def one_line(text, limit=160):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def common(tools, agent, run):
    """For every standing agent: what kind of turn this is, the thread it runs in, and the researcher's open questions."""
    store = tools.store
    lines = ["Turn: " + ("a platform notice, not a request" if run.get("input", "").startswith(NOTICE) else "a request")]
    thread_id = (run.get("origin") or {}).get("thread_id")
    if thread_id:
        try:
            title = store.get(thread_id, "thread").get("title")
        except KeyError:
            title = None
        lines.append(f"Thread: {thread_id}" + (f" ({one_line(title, 80)})" if title else ""))
    sessions = {a["id"]: a for a in store.list("agent_session", agent["campaign_id"])}
    def asked_here(question):
        # As in yield_work's outstanding check: the lead answers for every question but the page agents' own.
        owner = sessions.get(question.get("agent_id"))
        return question.get("agent_id") == agent["id"] or agent["role"] == LEAD and not (owner and owner["role"] in PAGE_AGENTS)
    # An extension's dialog is answered inside the tool call that asked it, not in a turn.
    pending = [q for q in store.list("agent_question", agent["campaign_id"]) if q["status"] == "pending" and q.get("kind") != "extension_dialog" and asked_here(q)]
    if pending:
        lines.append(f"Open questions to the researcher ({len(pending)}):")
        lines += [f"- {q['id']}: {one_line(q.get('question'))}" for q in pending[:QUESTIONS]]
    else:
        lines.append("Open questions to the researcher: none.")
    lines.append(compute_rule(tools, agent["campaign_id"]))
    lines += mandate_line(tools, agent, run)
    return lines


def mandate_line(tools, agent, run):
    """The mandate this turn's request is checked against (R3: its own newest, else a standing one), with its model dollars (R5),
    the worker time and coding workspaces it has left and its deadline (R2); with none, Explore by default."""
    from optimization_framework.campaigns import mandates
    from optimization_framework.campaigns.compute_consent import _minutes, request_root
    root = tools.controller.run_root(agent, run) or request_root(tools.workspace, {"run_id": run["id"]})
    if not root or not root.get("thread_id"):
        return []
    mandate = mandates.governing(tools.workspace, agent["campaign_id"], root)
    if mandate is None:
        return ["Mandate: none, Explore by default (mandate_propose for more)."]
    left = mandates.model_left(mandate)
    compute, used = mandate.compute, mandate.used
    coding = compute.coding_workspaces - used.coding_workspaces
    return [f"Mandate: {mandate.template.replace('_', ' ')} ({mandate.id}); model spend "
            + (f"${left:.2f} left of ${mandate.model_usd:.2f}" + (" (spent: new turns under this request wait for the researcher)" if left <= 1e-9 else "")
               if left is not None else "without an envelope of its own (the campaign's cap applies)")
            + (f"; {mandate.status}" + (", new work is refused" if mandate.status in mandates.ENDED else "") if mandate.status != "active" else "")
            + f"; worker time {_minutes(max(0.0, compute.worker_seconds - used.worker_seconds))} left"
            + (f", {coding} coding workspace{'s' if coding != 1 else ''}" if compute.coding_workspaces else "")
            + (f"; deadline {mandate.deadline_at[:16].replace('T', ' ')} UTC" if mandate.deadline_at else "; no deadline") + "."]


def compute_rule(tools, campaign_id):
    """The researcher's two compute thresholds, as they set them for this campaign."""
    from optimization_framework.campaigns.compute_consent import _minutes, thresholds
    notice, gate = thresholds(tools.workspace, campaign_id)
    return (f"Compute thresholds (the researcher's): work up to {_minutes(notice)} starts freely; "
            + (f"up to {_minutes(gate)}, it starts with a notice to them; " if gate > notice else "")
            + f"longer than {_minutes(gate)} (the go-ahead threshold), and any coding workspace, waits for their go-ahead.")


def experiment_rules(tools, agent):
    from optimization_framework.campaigns.experiment_rules import current
    rules = current(tools.store, agent["campaign_id"])
    presentation = rules["presentation"]
    return ["The campaign's experiment rules (revision " + str(rules["revision"]) + "):",
            "- Name each run in the first line of its question: " + rules["naming"],
            "- Short runs are allotted less than " + f"{rules['short_run_seconds']:g}" + " seconds; long runs at least that.",
            "- Runs of this campaign at once: " + (f"at most {rules['max_concurrent']} (the scheduler holds the rest in the queue)" if rules["max_concurrent"]
                else "no limit of the campaign's own") + f"; the workspace runs at most {tools.workspace.max_workers} in all.",
            "- How runs are chosen and ordered:\n" + rules["strategy"],
            "- How runs are presented on the Experiments page (" + ("chosen: " + (presentation.get("rationale") or "no reason given")
                if rules.get("presentation_chosen") else "not chosen yet; a default drawn from the problem's description is shown") + "): list columns "
                + ", ".join(presentation["list_columns"]) + "; entry sections " + ", ".join(presentation["entry_sections"])
                + "; design drawn as " + presentation["design"]["render"] + "."]


def resource_level(tools):
    from optimization_framework.execution.admission import LEVELS
    admission = getattr(tools.workspace, "admission", None)
    level = admission.level() if admission else {"level": "balanced", **LEVELS["balanced"]}
    return ["The researcher chose the " + level["label"].lower() + " resource level: " + level["summary"],
            f"Run slots: {tools.workspace.max_workers} runs at once, {tools.workspace.devices.sizes()['cuda']} of them on the GPU "
            "(the researcher's, on the Resources page; ask with approval.request worker_ceiling, workers and gpu_workers)."]


def page_agent(tools, agent):
    lines = []
    if agent.get("request_open"):
        lines.append("Request from: " + ASKED_BY.get(agent.get("requested_by"), "the lead agent"))
    if agent["role"] == "experiment_operator":
        lines += experiment_rules(tools, agent)
    if agent["role"] == "resource_planner":
        lines += resource_level(tools)
    return lines


def cap(lines):
    """Whole lines up to LIMIT characters, the header first; what does not fit is named as left out."""
    text = "\n".join([HEADER, *lines])
    if len(text) <= LIMIT:
        return text
    kept = HEADER
    for line in lines:
        if len(kept) + len(line) + len(CUT) + 2 > LIMIT:
            break
        kept += "\n" + line
    return kept + "\n" + CUT


def build(tools, agent, run):
    """The block for this agent's turn: empty for assistants of one assignment, import agents and implementation roles."""
    if agent.get("grant_id") or agent["role"] not in {LEAD, *PAGE_AGENTS}:
        return {"text": "", "hash": content_hash("")[:16]}
    lines = common(tools, agent, run)
    if agent["role"] == LEAD:
        extra = getattr(tools.workspace, "lead_state", None)
        lines += list(extra(agent, run)) if callable(extra) else []
    else:
        lines += page_agent(tools, agent)
    text = cap(lines)
    return {"text": text, "hash": content_hash(text)[:16]}
