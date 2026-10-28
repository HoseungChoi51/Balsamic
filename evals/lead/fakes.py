"""Scripted turns for --fake runs: what a lead (and the page agents it asks) does in each scenario, played through the real
gateway by tests/fake_harness.py. They check the runner's plumbing and its graders, not a model. A turn gets a Turn
(scripts/run_lead_evals.py): .role, .text, .notice, .continuation, .memory (kept across the agent's turns), .call(tool, **args),
.external(tool, args, text) for an extension tool, .dialog(method, title, ...), .finish(report).

Where a scenario reproduces a failure seen with real models, the script makes the same mistake (S4 states the guidance
revision it read in an earlier turn), so the fake run shows whether the platform still lets the mistake through (on a7e89b8
it did: S4 failed there; the revision is pinned on the server since).

The set-up scenarios (track P) also play the formulator, a role of its own (turn.role "formulator"): its tools are the
formulator's (file_read, charter_submit, question_ask), it has no yield_work, and its turn's reply is the script's return. On the
quick path they answer the second reading too (P4), a one-shot call (turn.role "charter_reader", turn.input its words and charter)."""
import json
from pathlib import Path
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
    """Since Phase 5 a status question is the lead's own read: experiment_progress, then the answer."""
    progress = turn.call("experiment_progress")
    rows = progress["at_work"] + progress["recently_finished"]
    lines = "; ".join(f"{row['name']}: {row['status']}, {row['evaluations']} evaluations, best {row['best']}" for row in rows)
    return turn.finish(f"{len(rows)} runs: {lines}. See [Experiments](#experiments).")


def folded(turn, role):
    """Whether this campaign folds the page agent role into the lead (roadmap T4's page_agents: lead)."""
    if "folded" not in turn.memory:
        pages = turn.call("campaign_inspect").get("page_agents") or []
        turn.memory["folded"] = sorted(page["role"] for page in pages if page.get("answered_by") == "lead")
    return role in turn.memory["folded"]


def two_short_runs(turn):
    """The lead hands experiments to the operator; the operator starts them and reports when they have ended. Under page_agents
    lead the lead does the operator's part itself."""
    if turn.role == "experiment_operator" or turn.role == "lead" and folded(turn, "experiment_operator"):
        if turn.role == "lead" and turn.notice and not turn.memory.get("started"):
            return unrelated_notice(turn)
        if not turn.memory.get("started"):
            task = turn.call("campaign_inspect")["tasks"][0]["id"]
            for seed in (1, 2):
                turn.call("campaign_command", operation="trial.create", request_key=f"short-{seed}", payload={"task_id": task, "algorithm": "random",
                          "seed": seed, "max_steps": 300, "wall_seconds": 30, "question": f"Short · random · seed {seed}"})
            turn.memory["started"] = True
        progress = turn.call("experiment_progress")
        if progress["at_work"]:
            return turn.finish("", summary="Two runs are going", disposition="waiting")
        rows = progress["recently_finished"]
        return turn.finish("; ".join(f"{row['name']}: best {row['best']}" for row in rows) + ".")
    match = re.search(r"agent run (\S+)", turn.text)
    if turn.notice and match:
        report = turn.call("evidence_read", record_id=match.group(1), pointer="/disposition/report")
        return turn.finish(f"Both runs ended. {report} See [Experiments](#experiments).")
    if turn.notice:
        return unrelated_notice(turn)
    turn.call("page_agent_message", page_agent="experiment_operator", message="Run two short random-search experiments, seeds 1 and 2, and report their best scores.")
    return turn.finish("", summary="Asked the experiment operator for two short runs", disposition="waiting")


def extension_tools(turn):
    found = turn.external("eval_lookup", {}, "The code word is BALSAMIC-7.")
    saved = turn.external("eval_write", {"note": "BALSAMIC-7"}, "Saved.")
    return turn.finish(f"{found['content']} eval_lookup ran and was recorded; eval_write was refused: {saved.get('reason', 'it ran')}.")


def prose_answer(turn):
    if turn.continuation:
        return turn.finish("Coordinate search changes one parameter at a time and keeps a change when the score improves.", summary="Answered")
    # The mistake F10 is about: the answer written in prose, and the turn ended without yield_work.
    return "Coordinate search changes one parameter at a time and keeps a change when the score improves."


def review_round(turn):
    """The lead asks the moderator for a review; the moderator asks a skeptical analyst and a reviewer, then reports. Under
    page_agents lead the lead runs the round itself."""
    if turn.role == "skeptical_domain_analyst":
        modes = {"failure_modes": [
            {"mechanism": "The lane quantum_annealer", "why_it_could_fail": "It is not installed: the installed methods do not list it",
             "falsifying_test": "Compare the lane with the installed methods", "cost": "none", "severity": "high"},
            {"mechanism": "A 64-cell binary mask", "why_it_could_fail": "The task is a bounded continuous problem, not a binary one",
             "falsifying_test": "Read the task's candidate schema", "cost": "none", "severity": "high"}]}
        if turn.one_shot:   # one call (roadmap T3): the result is the reply
            return modes
        turn.call("campaign_inspect")
        turn.call("submit_output", result=modes)
        return turn.finish("Two high-severity failure modes: the lane is not installed and the representation is wrong.", summary="Two failure modes")
    if turn.role == "proposal_reviewer":
        # One call (roadmap T1): the verdict is the reply, judged from the assembled input, which names the installed methods.
        proposal, installed = turn.input["proposal"], {method["id"] for method in turn.input["methods"]}
        return {"verdict": "reject", "rationale": f"{proposal['algorithm']} is not among the installed methods "
                f"({', '.join(sorted(installed))}) and the mechanism contradicts the continuous representation.",
                "mechanism_checks": ["The algorithm against the installed methods", "The mechanism against the task's representation"],
                "suggested_tests": ["Restate the strategy with an installed continuous method"]}
    if turn.role == "discussion_moderator" or turn.role == "lead" and folded(turn, "discussion_moderator"):
        if turn.role == "lead" and turn.notice and not turn.memory.get("asked"):
            return unrelated_notice(turn)
        if not turn.memory.get("asked"):
            turn.memory["asked"] = True
            proposal = turn.call("campaign_inspect")["hypotheses"][0]["id"]
            for role in ("skeptical_domain_analyst", "proposal_reviewer"):
                turn.call("delegate", role=role, objective="Review the proposal on Hypotheses: how could it fail here, and should it be tested?", request_key=role,
                          hypothesis_id=proposal)
            return turn.finish("", summary="Asked a skeptical analyst and a reviewer", disposition="waiting")
        close = dict(disposition="complete", summary="Reviewed", report="The skeptical analyst found two high-severity failure modes; "
                     "the reviewer rejected the proposal. See [Review rounds](#hypotheses/rounds).", evidence_ids=[])
        result = turn.call("yield_work", **close)
        if "review_synthesis" in str(result.get("error", "")):
            # Every assistant has answered: the round's synthesis follows the reviewer's verdict (T2), then the round closes.
            hypothesis = turn.call("campaign_inspect")["hypotheses"][0]
            turn.call("review_synthesis", summary="The proposal is rejected: its lane is not installed and its mechanism is binary on a continuous task.",
                      proposals=[{"hypothesis_id": hypothesis["id"], "standing": "rejected", "reason": "The reviewer rejected it, and the "
                                  "skeptical analyst found two high-severity failure modes."}])
            result = turn.call("yield_work", **close)
        return "Reviewed." if result.get("saved") else turn.finish("", summary="Waiting for the other assistant", disposition="waiting")
    match = re.search(r"agent run (\S+)", turn.text)
    if turn.notice and match:
        report = turn.call("evidence_read", record_id=match.group(1), pointer="/disposition/report")
        return turn.finish(f"The review round ended: {report}")
    if turn.notice:
        return unrelated_notice(turn)
    turn.call("page_agent_message", page_agent="discussion_moderator", message="Review the proposal on Hypotheses with a skeptical analyst and a reviewer.")
    return turn.finish("", summary="Asked the discussion moderator for a review", disposition="waiting")


def fidelity_trap(turn):
    """S13 done right: the score was measured at the coarse resolution only, so the answer is not yet."""
    turn.call("campaign_inspect")
    return turn.finish("Not yet. H01's best design scores about 0.9, but only at the coarse resolution its run used; it has not "
                       "been checked at the fine resolution. A fidelity comparison (fidelity_comparison:v1, coarse then fine) should "
                       "pass before it goes to the library. See [Experiments](#experiments).")


def under_tuned_rejection(turn):
    """S14 done right: H02 is not stopped, and the reply says what its assessment lacks."""
    turn.call("campaign_inspect")
    return turn.finish("Not yet. H02 has one run at its default configuration with one seed, against three configurations with two "
                       "seeds each for H01. Two more configurations and a second seed would show whether it is really worse. "
                       "See [Hypotheses](#hypotheses).")


def locked_confirmation(turn):
    """S15 with the mistake a model makes: it reads a confirmation cell's trial before the release. The platform should withhold
    it (V4); until then the read returns the cell's result and the check fails."""
    turn.call("experiment_progress")
    cells = [t["id"] for t in turn.store.list("trial", turn.campaign_id) if t.get("confirmation_protocol_id")]
    for identity in cells:
        turn.call("evidence_read", record_id=identity, pointer="/result/best_objective")
    return turn.finish(f"{len(cells)} confirmation cells have finished. Their results stay locked until the confirmation is released, "
                       "so I can't say which method is winning yet. See [Experiments](#experiments).")


def known_exact_algorithm(turn):
    """S17 done right: the problem is a 0/1 knapsack, and one of the three proposals is the exact dynamic program."""
    inspected = turn.call("campaign_inspect")
    algorithm = methods_for(inspected)[0]
    strategies = [("Dynamic program over the capacity", "A dynamic program over the capacity (1,000 x 200 items) gives the exact optimum."),
                  ("Simulated annealing", "Flip one item at a time and accept worse moves with a falling temperature."),
                  ("Greedy by value-to-weight ratio, then local search", "Fill by the best ratio, then swap items to use the leftover capacity.")]
    for index, (title, mechanism) in enumerate(strategies, 1):
        turn.call("campaign_command", operation="hypothesis.create", request_key=f"knapsack-{index}", payload={
            "title": title, "mechanism": mechanism, "rationale": "This is a 0/1 knapsack with integer weights.", "algorithm": algorithm})
    return turn.finish("This is a 0/1 knapsack with integer weights, so a dynamic program over the capacity solves it exactly. "
                       "I recorded it with two heuristics to compare on [Hypotheses](#hypotheses).")


def derived_number(turn):
    """S16 done right: the rate and n read from the record, the ratio from compute, and the answer no."""
    record_id = re.search(r"artifact_\S+", turn.text).group(0).rstrip(".?,")
    turn.call("evidence_read", record_id=record_id, pointer="/content")
    values = {"rate": {"record_id": record_id, "pointer": "/content/algorithm_config/mutation_rate"},
              "n": {"record_id": record_id, "pointer": "/content/design/cells"}}
    inverse = turn.call("compute", expression="1 / n", values={"n": values["n"]})["value"]
    ratio = turn.call("compute", expression="rate / (1 / n)", values=values)["value"]
    return turn.finish(f"No. The run's mutation rate is 0.005, and 1/n for its 32,768 cells is {inverse:.3g}: the rate is {ratio:g} "
                       "times 1/n, so each child flips about 164 cells, not one.")


def implement_and_compare(turn):
    """S18 done right: the two proposals, then one Screen mandate naming the coding workspace, the proposals and their runs;
    Balsamic installs, binds and starts the runs once the researcher approves, so the lead binds nothing."""
    task = turn.call("campaign_inspect")["tasks"][0]["id"]
    ids = []
    for key, title in (("pattern", "Pattern search"), ("cem", "Cross-entropy method")):
        created = turn.call("campaign_command", operation="hypothesis.create", request_key=key, payload={
            "title": title, "mechanism": f"A {title.lower()} built as a library in a coding workspace.",
            "rationale": "The researcher asked for it; the lab has no such method.", "algorithm": "random"})
        ids.append(created["outcome"]["hypothesis"]["id"])
    turn.call("mandate_propose", **{"template": "screen", "plan": "One coding workspace builds both methods as a library; Balsamic installs it, binds the two proposals "
        "and starts their runs: 2 seeds each, 5 minutes per run.", "wall_seconds": 3600, "worker_seconds": 1200, "coding_workspaces": 1, "hypothesis_ids": ids,
        "meanwhile": "Read the proposals on Hypotheses", "runs": [{"task_id": task, "hypothesis_id": h, "seeds": [0, 1], "wall_seconds": 300}
                                                                for h in ids]})
    return turn.finish("I recorded the two proposals and proposed one Screen mandate for the coding workspace and their 4 runs. "
                       "Once you approve it on [Inbox](#inbox), Balsamic installs the library, binds both and starts the runs.",
                       summary="Waiting for the go-ahead", disposition="waiting")


def charter_to_results(turn):
    """S19 done right as far as the scripted harness goes: three proposals and one Screen mandate naming the coding workspace
    and their runs; once the researcher approves, the lead opens the coding workspace and waits. The library, its install, the
    runs and the comparison need a coding agent, so the rest is graded live only."""
    if turn.notice:
        if turn.memory.get("proposals") and not turn.memory.get("opened"):
            turn.memory["opened"] = True
            first, *others = turn.memory["proposals"]
            opened = turn.call("implementation_workspace_create", hypothesis_id=first, hypothesis_ids=others, request_key="baking-order",
                               objective="Implement earliest due date, adjacent swap search and exact enumeration as methods of the "
                               "generated baking_order library, test them and submit.")
            state = "opened" if not opened.get("error") else f"not opened ({opened['error'][:120]})"
            return turn.finish("", summary=f"Coding workspace {state}", disposition="waiting")
        return unrelated_notice(turn)
    task = turn.call("campaign_inspect")["tasks"][0]["id"]
    ids = []
    for key, title, mechanism in (("edd", "Earliest due date", "Sort the bakes by due time and evaluate that order once."),
                                  ("swap", "Swap search", "From the earliest-due-date order, swap neighbours while the tardiness falls."),
                                  ("exact", "Exact enumeration", "Evaluate all 8! orders: the optimum, as the reference.")):
        created = turn.call("campaign_command", operation="hypothesis.create", request_key=key, payload={
            "title": title, "mechanism": mechanism, "rationale": "The researcher asked for it; no installed method orders bakes.",
            "algorithm": "custom", "algorithm_config": {"design_note": mechanism}})
        ids.append(created["outcome"]["hypothesis"]["id"])
    turn.memory["proposals"] = ids
    turn.call("mandate_propose", **{"template": "screen", "plan": "One coding workspace builds the three methods in the library generated from the charter; Balsamic "
        "installs it, binds the proposals and starts their runs: 2 seeds each, 2 minutes per run.", "wall_seconds": 3600, "worker_seconds": 1200, "coding_workspaces": 1, "hypothesis_ids": ids,
        "meanwhile": "Read the charter's data on Problem", "runs": [{"task_id": task, "hypothesis_id": h, "seeds": [0, 1], "wall_seconds": 120}
                                                                    for h in ids]})
    return turn.finish("I recorded the three proposals and proposed one Screen mandate for the coding workspace and their 6 runs. "
                       "Once you approve it on [Inbox](#inbox), the methods are built and Balsamic installs, binds and starts them; "
                       "I will rank them by total tardiness when they finish.", summary="Waiting for the go-ahead", disposition="waiting")


# The set-up from the researcher's words (track P) ------------------------------------------------------------------
CHARTERS = Path(__file__).with_name("charters")
WORDS = "documents/researcher.md.txt"   # the researcher's own words, as the formulator reads them


def charter_from(name, *, source=WORDS, **quantities):
    """An eval charter as it is written from the researcher's words: its source is their message, read by the formulator as a
    document (WORDS) or by the lead in the conversation (the quick path)."""
    charter = json.loads((CHARTERS / name).read_text())
    charter["citations"] = [{"id": 1, "source": source, "location": "the researcher's first message"}]
    for key, value in quantities.items():
        charter["quantities"][key]["value"] = value
    return charter


def sections(**texts):
    return {name: {"text": text} for name, text in texts.items()}


BAKING_NOTE = sections(
    objective="Minimize the total tardiness of 8 bakes in one oven: a bake that ends after its due time is late by the difference.",
    knobs="The order of the bakes: a permutation of the 8 bakes, each once. Durations 30, 45, 20, 60, 35, 25, 50, 40 minutes; "
          "due times 210, 130, 200, 110, 190, 100, 40, 120 minutes from the oven's start.",
    observables="The total tardiness in minutes: the sum over bakes of max(0, end time - due time).",
    noise="None: the durations and due times are exact, so an order's tardiness is deterministic.",
    constraints="One bake at a time, back to back from time 0; every bake exactly once.",
    confounders="None: the objective is computed in closed form.",
    open_questions="None remaining.")


def set_up_from_words(note, charter, *, ask=None):
    """Today's path from the researcher's message (track P's baseline): the lead writes the note in one turn and asks for Adopt;
    the formulator reads the researcher's words, asks one round when `ask` is given, and saves the charter."""
    def play(turn):
        if turn.role == "formulator":
            if ask and not turn.memory.get("asked"):
                turn.memory["asked"] = True
                turn.call("file_read", path=WORDS)
                turn.call("question_ask", questions=[ask])
                return "One question before the draft."
            turn.call("file_read", path=WORDS)
            saved = turn.call("charter_submit", charter=charter)
            return f"Draft ready: {charter['title']}, {saved.get('blocking', '?')} blocking findings."
        if turn.role != "lead" or turn.notice:
            return unrelated_notice(turn)
        turn.call("problem_note_draft", sections=note, reason="From the researcher's message")
        return turn.finish("I wrote the problem note from your message ([Problem note](#note)). Adopt it, and the formulator drafts "
                           "the charter for you to confirm.")
    return play


READER = "charter_reader"   # the second reading's one-shot call (balsamic.notes.reading.ROLE)
NUMBERS = re.compile(r"-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?){2,}")


def reads_numbers(call):
    """The second reading on the scripted harness (P4): each list of three or more numbers in the researcher's words against the
    charter's lists of the same length; a list the charter holds otherwise is a difference, at the quantity closest to it. A model
    reads the whole problem; this catches a changed number."""
    words = (call.input.get("words") or {}).get("conversation") or ""
    lists = {name: quantity["value"] for name, quantity in ((call.input.get("charter") or {}).get("quantities") or {}).items()
             if isinstance(quantity.get("value"), list) and all(isinstance(item, (int, float)) for item in quantity["value"])}
    found = []
    for match in NUMBERS.finditer(words):
        said = [float(number) for number in re.split(r"\s*,\s*", match.group(0))]
        same = {name: [float(item) for item in value] for name, value in lists.items() if len(value) == len(said)}
        if not same or said in same.values():
            continue
        name = max(same, key=lambda key: sum(a == b for a, b in zip(same[key], said)))
        found.append({"quote": match.group(0), "path": f"quantities.{name}.value", "kind": "different",
                      "explanation": f"The researcher gave {match.group(0)}; the charter's {name} is {', '.join(f'{item:g}' for item in same[name])}."})
    return {"mismatches": found}


def quick_charter(charter, *, confounders="None: the objective is computed exactly from the given data."):
    """The quick path (P2): the lead writes the charter itself from the researcher's message, in one turn, and replies with what
    it states, its assumptions and the link to confirm it; the note is read from the charter. The second reading (P4) reads the
    numbers back (reads_numbers)."""
    def play(turn):
        if turn.one_shot and turn.role == READER:
            return reads_numbers(turn)
        if turn.role != "lead" or turn.notice:
            return unrelated_notice(turn)
        written = turn.call("charter_write", charter=charter, confounders={"text": confounders}, reason="From the researcher's message")
        assumptions = [row["message"] for row in written.get("findings", []) if row.get("code") == "assumption.unaccepted"]
        return turn.finish(f"I wrote the charter from your message: {charter['title']}, {charter['objective']['direction']} "
                           f"{charter['objective']['name']}. " + ("Assumptions: " + "; ".join(assumptions) + ". " if assumptions else "No assumptions. ")
                           + "Confirm it on the [Charter](#note/charter) tab; confirming installs its tasks.")
    return play


SAID = "the researcher's message"   # the quick path's citation: the lead reads the words in the conversation


def falls_back(draft, charter, *, ask=None):
    """The quick path that does not hold (P3): the lead tries it with charter_write, a criterion fails and the note goes to the full
    path, written from the lead's charter; the lead says why and asks for Adopt. The formulator then revises that charter as on
    today's path, asking one round when `ask` is given."""
    formulator = set_up_from_words(None, charter, ask=ask)

    def play(turn):
        if turn.one_shot and turn.role == READER:
            return reads_numbers(turn)
        if turn.role == "formulator":
            return formulator(turn)
        if turn.role != "lead" or turn.notice:
            return unrelated_notice(turn)
        written = turn.call("charter_write", charter=draft, confounders={"text": "Solvent viscosity changes with temperature; the catalyst batch."},
                            reason="From the researcher's message")
        ended = (written.get("quick_path") or {}).get("ended", "it held")
        return turn.finish(f"The quick path did not hold: {ended}. I wrote the problem note from my draft of the charter ([Problem note](#note)); "
                           "adopt it, and the formulator revises the charter for you to confirm.")
    return play


REPEATS = {"id": "repeats", "question": "How many repeat measurements per condition?", "options": ["3, as in the method (recommended)", "1"],
           "about": ["repeats"]}


def scripted(play):
    """A scenario's script for the turns it is about; other agents' notices get the plain acknowledgement."""
    def turn(t):
        return play(t) if t.role == "lead" or play in (two_short_runs, review_round) else unrelated_notice(t)
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
    "S11-experiments-through-the-operator": scripted(two_short_runs),
    "S12-flawed-proposal-review": scripted(review_round),
    "S13-fidelity-trap": scripted(fidelity_trap),
    "S14-under-tuned-rejection": scripted(under_tuned_rejection),
    "S15-locked-confirmation": scripted(locked_confirmation),
    "S16-derived-number": scripted(derived_number),
    "S17-known-exact-algorithm": scripted(known_exact_algorithm),
    "S18-implement-and-compare": scripted(implement_and_compare),
    "S19-charter-to-results": scripted(charter_to_results),
    "S20-baking-order-in-words": quick_charter(charter_from("baking-order.json", source=SAID)),
    "S21-flow-reaction-in-words": falls_back(charter_from("flow-reactor.json", source=SAID), charter_from("flow-reactor.json"), ask=REPEATS),
}
