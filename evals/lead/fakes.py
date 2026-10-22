"""Scripted turns for --fake runs: what a lead (and the page agents it asks) does in each scenario, played through the real
gateway by tests/fake_harness.py. They check the runner's plumbing and its graders, not a model. A turn gets a Turn
(scripts/run_lead_evals.py): .role, .text, .notice, .continuation, .memory (kept across the agent's turns), .call(tool, **args),
.external(tool, args, text) for an extension tool, .dialog(method, title, ...), .finish(report).

Where a scenario reproduces a failure seen with real models, the script makes the same mistake (S4 states the guidance
revision it read in an earlier turn), so the fake run shows whether the platform still lets the mistake through (on a7e89b8
it did: S4 failed there; the revision is pinned on the server since)."""
import re


def unrelated_notice(turn):
    """A notice the scenario is not about (the resource planner's events, an outcome that arrived meanwhile): acknowledge and end."""
    if turn.role == "lead":
        return turn.finish("", summary="Nothing new for the open request", disposition="waiting")
    return turn.finish("Noted; nothing to change.", summary="Nothing to change")


def methods_for(inspected):
    """The installed methods that run on the first task, as campaign_inspect lists them."""
    task = (inspected.get("tasks") or [{}])[0].get("id")
    return [m["id"] for m in inspected.get("methods", []) if task in m.get("task_ids", [])] or ["random"]


def hypothesis(turn, key, title, algorithm, **extra):
    return turn.call("campaign_command", operation="hypothesis.create", request_key=key, payload={
        "title": title, "mechanism": f"Run {algorithm} with its default settings on the task as installed.",
        "rationale": "A baseline the other strategies are measured against.", "algorithm": algorithm}, **extra)


def capabilities(turn):
    turn.call("campaign_inspect")
    turn.call("resource_inspect")
    return turn.finish("I can propose strategies, run and compare experiments, and write reports, each when you ask. "
                       "A first step: two baseline hypotheses from the installed methods ([Hypotheses](#hypotheses)).")


def narrow_request(turn):
    inspected = turn.call("campaign_inspect")
    names = methods_for(inspected)
    for index, algorithm in enumerate((names * 2)[:2], 1):
        hypothesis(turn, f"baseline-{index}", f"Baseline {index}: {algorithm}", algorithm)
    return turn.finish("Recorded two hypotheses on [Hypotheses](#hypotheses); nothing else was started. "
                       "Running them would be the next step if you want it.")


def guidance_after_page_command(turn):
    inspected = turn.call("campaign_inspect")
    # A model keeps the revision it read first and states it again in later turns: the mistake seen in Parts E and G.
    remembered = turn.memory.setdefault("guidance_revision", inspected["guidance_revision"])
    count = turn.memory["created"] = turn.memory.get("created", 0) + 1
    algorithm = methods_for(inspected)[0]
    result = hypothesis(turn, f"h{count}", f"Strategy {count}: {algorithm}", algorithm, guidance_revision=remembered)
    if "guidance changed" in str(result.get("error", "")):
        # As the models did: read the revision again and repeat the command.
        fresh = turn.call("campaign_inspect")["guidance_revision"]
        turn.memory["guidance_revision"] = fresh
        hypothesis(turn, f"h{count}-retry", f"Strategy {count}: {algorithm}", algorithm, guidance_revision=fresh)
    return turn.finish(f"Recorded hypothesis {count} on [Hypotheses](#hypotheses).")


def large_record(turn):
    record_id = re.search(r"artifact_\S+", turn.text).group(0).rstrip(".")
    page = turn.call("evidence_read", record_id=record_id, pointer="/content/summary")
    return turn.finish(f"The saved sweep: {page if isinstance(page, str) else 'see the record'}. It has 9,000 rows; I read its summary only.")


def gate_closed(turn):
    inspected = turn.call("campaign_inspect")
    definition = inspected.get("definition") or {}
    missing = ", ".join(definition.get("missing") or []) or (definition.get("step") or {}).get("title", "")
    return turn.finish(f"I can't propose strategies yet: the problem definition is incomplete. Not written yet: {missing} "
                       "([Problem note](#note)). I can draft those sections now if you tell me what you know.")


def gate_opens(turn):
    inspected = turn.call("campaign_inspect")
    definition = inspected.get("definition") or {}
    if not definition.get("ready"):
        return turn.finish("The problem note still needs sections before proposals ([Problem note](#note)).")
    names = methods_for(inspected)
    for index, algorithm in enumerate((names * 2)[:2], 1):
        hypothesis(turn, f"strategy-{index}", f"Strategy {index}: {algorithm}", algorithm)
    return turn.finish("Recorded two strategies on [Hypotheses](#hypotheses).")


def experiment_status(turn):
    if turn.role == "experiment_operator":
        progress = turn.call("experiment_progress")
        rows = progress["at_work"] + progress["recently_finished"]
        lines = "; ".join(f"{row['name']}: {row['status']}, {row['evaluations']} evaluations, best {row['best']}" for row in rows)
        return turn.finish(f"{len(rows)} runs: {lines}.")
    match = re.search(r"agent run (\S+)", turn.text)
    if turn.role != "lead" or turn.notice and not match:
        return unrelated_notice(turn)
    if turn.notice:
        run_id = match.group(1)
        report = turn.call("evidence_read", record_id=run_id, pointer="/disposition/report")
        return turn.finish(f"From the experiment operator: {report} See [Experiments](#experiments).")
    turn.call("page_agent_message", page_agent="experiment_operator", message="How are the experiments going? Give the numbers.")
    return turn.finish("", summary="Asked the experiment operator", disposition="waiting")


def extension_tools(turn):
    found = turn.external("eval_lookup", {}, "The code word is BALSAMIC-7.")
    saved = turn.external("eval_write", {"note": "BALSAMIC-7"}, "Saved.")
    return turn.finish(f"{found['content']} eval_lookup ran and was recorded; eval_write was refused: {saved.get('reason', 'it ran')}.")


def prose_answer(turn):
    if turn.continuation:
        return turn.finish("Coordinate search changes one parameter at a time and keeps a change when the score improves.", summary="Answered")
    # The mistake F10 is about: the answer written in prose, and the turn ended without yield_work.
    return "Coordinate search changes one parameter at a time and keeps a change when the score improves."


def scripted(play):
    """A scenario's script for the turns it is about; other agents' notices get the plain acknowledgement."""
    def turn(t):
        return play(t) if t.role == "lead" or play is experiment_status else unrelated_notice(t)
    return turn


FAKES = {
    "S2-capabilities-question": scripted(capabilities),
    "S3-narrow-request": scripted(narrow_request),
    "S4-guidance-after-page-command": scripted(guidance_after_page_command),
    "S5-large-record": scripted(large_record),
    "S6-gate-closed": scripted(gate_closed),
    "S7-gate-opens-mid-session": scripted(gate_opens),
    "S8-experiment-status": scripted(experiment_status),
    "S9-extension-tools": scripted(extension_tools),
    "S10-prose-answer": scripted(prose_answer),
}
