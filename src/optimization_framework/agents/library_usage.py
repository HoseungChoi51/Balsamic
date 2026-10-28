"""What the lab's campaigns use of its code libraries (roadmap track L). A campaign uses a method when one of its runs ran it or
one of its proposals is bound to it, and a problem when one of its tasks is on it. Usage is lab-wide: an install keeps what
any campaign uses (L1), whichever campaign installs it.
"""
from __future__ import annotations


def used_methods(store):
    """{method id: sorted ids of the campaigns that ran it or bound a proposal to it}."""
    found = {}
    for trial in store.list_trial_headers():
        if trial.get("algorithm"):
            found.setdefault(trial["algorithm"], set()).add(trial["campaign_id"])
    for hypothesis in store.list("hypothesis"):
        if hypothesis.get("builtin_binding_id") and hypothesis.get("algorithm"):
            found.setdefault(hypothesis["algorithm"], set()).add(hypothesis["campaign_id"])
    return {method: sorted(campaigns) for method, campaigns in found.items()}


def used_problems(store):
    """{problem id: sorted ids of the campaigns with a task on it}."""
    found = {}
    for task in store.list("task"):
        for problem_id in {task.get("problem_id"), (task.get("evaluator_manifest") or {}).get("id")} - {None}:
            found.setdefault(problem_id, set()).add(task["campaign_id"])
    return {problem: sorted(campaigns) for problem, campaigns in found.items()}


def campaign_names(store, campaign_ids, limit=3):
    """The campaigns, as a researcher names them: their names, then how many more."""
    names = []
    for campaign_id in campaign_ids:
        try:
            names.append(store.get(campaign_id, "campaign").get("name") or campaign_id)
        except KeyError:
            names.append(campaign_id)
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")
