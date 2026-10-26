"""The installed problem a campaign runs on, stated for whoever writes from it: the lead writing the note, the formulator at Adopt.

A campaign set up on an installed problem is stated by the problem's package: its definition, and the example whose instance
the tasks run on, with the example's charter. The lead writes the note from it by itself and asks the researcher only what the
package leaves open; the formulator builds the charter on the same evaluator. Read from the registry; no problem is named here.
"""
import json

from optimization_framework.storage.sqlite import now

# The lead's request at creation; the note page reads it to say the lead is writing.
NOTE_REQUEST = "installed_problem"
WRITING = {"queued", "submitted", "running"}


def problems_of(workspace, campaign_id):
    """[{problem_id, name, evaluator, tasks, example}] for the campaign's live tasks on installed problems; [] when it has none."""
    from optimization_framework.evaluation.registry import problems
    from optimization_framework.problem_import.service import outline
    installed, rows = set(problems.ids()), {}
    for task in workspace.store.list("task", campaign_id):
        name = task.get("problem_id")
        if task.get("archived") or task.get("evaluator_manifest") or name not in installed:
            continue
        if name not in rows:
            definition = problems.get(name).describe()
            rows[name] = {"problem_id": name, "name": definition.name, "evaluator": f"{definition.evaluator_id} {definition.evaluator_version}", "tasks": [], "example": None}
        row = rows[name]
        setup = {"configuration": task.get("configuration") or {}, "fidelity": task.get("fidelity") or {}}
        row["tasks"].append({"name": task["name"], **setup})
        if row["example"] is None:
            for example in problems.examples():
                if any(instance.get("problem_id") == name and (instance.get("configuration") or {}) == setup["configuration"]
                       and (instance.get("fidelity") or {}) == setup["fidelity"] for instance in example.get("instances") or []):
                    row["example"] = {"id": example["id"], "name": example["name"], "summary": example.get("summary", ""),
                                      **({"charter": outline(example["charter"])} if example.get("charter") else {})}
                    break
    return list(rows.values())


def statement(rows):
    """The installed problems as a section of the formulator's statement: what the tasks run on is settled, not a question."""
    if not rows:
        return ""
    lines = ["## The installed problem this campaign runs on", ""]
    for row in rows:
        example = row["example"]
        lines.append(f"The campaign's tasks already run on the installed problem `{row['problem_id']}` ({row['name']}; evaluator {row['evaluator']})"
                     + (f", on the values of its example \"{example['name']}\", which `problem_catalog` lists with its charter." if example else "."))
        lines += [f"- Task \"{task['name']}\": configuration {json.dumps(task['configuration'])}; fidelity {json.dumps(task['fidelity'])}" for task in row["tasks"]]
        lines.append("")
    lines.append("Formulate the charter on this evaluator" + (", from the example's charter," if any(row["example"] for row in rows) else "")
                 + " keeping these values unless the note above says otherwise. What the installed problem states is settled: do not ask "
                   "the researcher to confirm it. Ask only about what the note leaves open and the installed problem does not state.")
    return "\n".join(lines) + "\n"


def prompt(rows):
    """The lead's request at creation: write the whole note from the installed problem, and decide whether anything needs the researcher."""
    return ("This campaign was set up on an installed problem; its package states the problem:\n"
            + json.dumps(rows, indent=1)[:40000] + "\n\n"
            "Write the problem note from it now with problem_note_draft, every section in one call: objective (what is optimized, how it is "
            "computed, its direction and units), knobs (the decision variables and the inputs held fixed, with their values), observables "
            "(the objective and the recorded metrics), noise (whether the evaluator is deterministic, and what a score depends on), constraints, "
            "confounders (what could mislead a comparison: fidelity, seeds, budgets, the instance split) and open questions. Decide yourself "
            "whether anything needs the researcher before adoption: only what the researcher's question in this conversation leaves open and the "
            "package does not state. Each such question is an item of open questions, with the answer you suggest. When nothing does, write "
            "open questions as \"None remaining\" with no items. Do not propose skips and do not ask the researcher to confirm what the package "
            "states. Then reply in two or three lines: that the note is written from the installed problem, and either that nothing is missing "
            "and the note is ready to adopt on [the note](#note), or your questions. Then yield_work.")


def request_note(workspace, campaign_id, thread):
    """Ask the lead to write the note from the installed problem the campaign was set up on; the run, or None when it runs on none.

    The researcher's Create is the request: the lead is started if it is not, and an assistant line in the thread says what it was asked."""
    from optimization_framework.contracts.commands import Command
    from optimization_framework.contracts.base import content_hash
    from balsamic.threads.service import lead_agent
    rows = problems_of(workspace, campaign_id)
    if not rows:
        return None
    if not workspace.pi.owns(campaign_id):
        workspace.commands.execute(Command(id="ui_note_activate_" + content_hash([campaign_id])[:20], campaign_id=campaign_id, operation="agent.activate",
                                           expected_revision=workspace.store.get(campaign_id, "campaign")["version"], payload={}), actor="researcher")
    lead = lead_agent(workspace, campaign_id)
    workspace.pi._request(campaign_id, True)
    with workspace.lock:
        workspace.store.put("message", {"id": f"message_note_request_{campaign_id}", "campaign_id": campaign_id, "thread_id": thread["id"], "role": "assistant",
                                        "origin": "setup", "content": "The lead writes the problem note from the installed problem now; it asks you only what the problem leaves open.",
                                        "created_at": now()}, "message.created")
    placement = {"leaf_entry_id": thread["agent_leaf"]} if thread.get("agent_leaf") else {"branch_from_entry_id": thread.get("fork_entry_id")}
    return workspace.pi.enqueue(lead, "pi_run_note_" + campaign_id, prompt(rows), origin={"thread_id": thread["id"], "actor": "researcher", "note_request": NOTE_REQUEST},
                                thread_revision=thread.get("guidance_revision"), **placement)


def writing(workspace, campaign_id):
    """The lead's note-writing run while it is queued or running, else None: the note page says the lead is writing."""
    from balsamic.threads.service import lead_agent
    lead = lead_agent(workspace, campaign_id)
    if lead is None:
        return None
    run = next((run for run in reversed(workspace.store.list_agent_runs(lead["id"])) if (run.get("origin") or {}).get("note_request") == NOTE_REQUEST), None)
    return {"run_id": run["id"], "status": run["status"]} if run and run.get("status") in WRITING else None
