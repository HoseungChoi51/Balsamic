"""Which methods the campaign can run, and why the others cannot: one view joining what is installed (bundled methods and
installed libraries), what coding workspaces delivered but nobody installed yet, what is still being built, and the
proposals that use each, with the next step and who takes it.

A method's state is per task: runnable (its candidates fit the task's problem), incompatible (with the reason), or, for a
method that is not installed, not_installed / needs_revision. A task can be blocked as a whole, by its evaluator.
"""
from __future__ import annotations

import re

LIBRARY = re.compile(r"^libraries/([^/]+)/")


def latest_submissions(store, campaign_id):
    """Each coding workspace's latest submission."""
    latest = {}
    for submission in sorted(store.list("development_submission", campaign_id), key=lambda row: row["created_at"]):
        latest[submission["workspace_id"]] = submission
    return list(latest.values())


def served(submission):
    """The proposals a submission serves: those its report's methods name, else those its workspace was opened for."""
    named = [method["hypothesis_id"] for method in (submission.get("report") or {}).get("methods", []) if method.get("hypothesis_id")]
    return list(dict.fromkeys(named + (submission.get("hypothesis_ids") or [submission["hypothesis_id"]])))


def library_of(submission):
    """The library directory a submission's manifest files sit in (libraries/<name>/), or None."""
    names = {match.group(1) for path in (submission.get("manifest") or {}).get("files", []) if (match := LIBRARY.match(str(path)))}
    return names.pop() if len(names) == 1 else None


def methods_for(submission, hypothesis_id):
    """The method ids a submission reports for one proposal; all of its methods when none names a proposal."""
    methods = (submission.get("report") or {}).get("methods", [])
    mine = [method["method_id"] for method in methods if method.get("hypothesis_id") == hypothesis_id]
    return mine or ([method["method_id"] for method in methods] if not any(method.get("hypothesis_id") for method in methods) else [])


def installing(store, submission):
    """Where a delivered, not yet installed library stands, as the next step and who takes it."""
    tries = sorted((row for row in store.list("library_install", submission["campaign_id"]) if row.get("submission_id") == submission["id"]),
                   key=lambda row: row["requested_at"])
    latest = tries[-1] if tries else None
    if latest and latest["status"] == "needs_confirmation":
        changes = ", ".join(f"{c['name']} {c['from']} → {c.get('to') or 'removed'}" for c in latest.get("changes", []))
        return {"owner": "researcher", "text": f"Confirm the install on the Implementations page: it would change {changes}"}
    if latest and latest["status"] == "failed":
        return {"owner": "lead", "text": "Have the coding agent fix what stopped the install: " + str(latest.get("error", ""))[:300]}
    if latest and latest["status"] in {"queued", "installing"}:
        return {"owner": "balsamic", "text": "Balsamic is installing it"}
    if (submission.get("report") or {}).get("verdict") == "not_ready":
        return {"owner": "lead", "text": "The coding agent reported it not ready; the researcher can still install it on the Implementations page"}
    return {"owner": "balsamic", "text": "Balsamic installs it at its next check"}


def binding(install, hypothesis_ids, *, subject=None):
    """Who binds installed, unbound proposals, as the next step: Balsamic while their install's post-install step has not run,
    else the lead, for a proposal Balsamic left (with its reason) or one no recorded install covers."""
    subject = subject or ", ".join(hypothesis_ids) + " to it"
    if install and "bindings" not in install and not install.get("after_install_error"):
        return {"owner": "balsamic", "text": f"Balsamic binds {subject} as its install finishes"}
    reasons = [row["reason"] for row in (install or {}).get("skipped") or [] if row["hypothesis_id"] in hypothesis_ids]
    return {"owner": "lead", "text": f"Bind {subject} (implementation.bind_builtin)" + (f"; Balsamic left it: {'; '.join(reasons)}" if reasons else "")}


def development_readiness(store, hypothesis, installed):
    """A proposal whose method a coding workspace builds or delivered: building, submitted_not_installed, or
    installed_not_bound; None when no workspace serves it."""
    hypothesis_id = hypothesis.get("id")
    if not hypothesis_id or not hypothesis.get("campaign_id"):
        return None   # a draft's candidate, not a recorded proposal
    for submission in sorted(latest_submissions(store, hypothesis["campaign_id"]), key=lambda row: row["created_at"], reverse=True):
        if hypothesis_id not in served(submission):
            continue
        methods = methods_for(submission, hypothesis_id)
        ready = [method for method in methods if method in installed]
        if ready:
            install = next((row for row in sorted(store.list("library_install", hypothesis["campaign_id"]), key=lambda row: row["requested_at"],
                                                  reverse=True) if row.get("submission_id") == submission["id"] and row.get("status") == "installed"), None)
            return {"state": "installed_not_bound", "runnable": False, "methods": ready, "submission_id": submission["id"],
                    "reason": f"Installed: {', '.join(ready)}. {binding(install, [hypothesis_id], subject='this proposal to its method')['text']}."}
        verdict = ((submission.get("report") or {}).get("verdict") or "no delivery report").replace("_", " ")
        install = installing(store, submission)
        if submission["status"] == "needs_revision":
            return {"state": "needs_revision", "runnable": False, "submission_id": submission["id"], "workspace_id": submission["workspace_id"],
                    "reason": f"Delivered in commit {submission['commit'][:7]}; independent validation found problems to repair."}
        return {"state": "submitted_not_installed", "runnable": False, "submission_id": submission["id"], "workspace_id": submission["workspace_id"],
                "methods": methods, "reason": f"Delivered in commit {submission['commit'][:7]} ({verdict}), not installed yet. {install['text']}."}
    for record in store.list("development_workspace", hypothesis["campaign_id"]):
        if hypothesis_id in (record.get("hypothesis_ids") or [record["hypothesis_id"]]) and record.get("desired_status") == "running":
            return {"state": "building", "runnable": False, "workspace_id": record["id"],
                    "reason": "Being built in a coding workspace" + (f" ({record['phase']})" if record.get("phase") else "") + "."}
    return None


def catalog(workspace, campaign_id, *, other_limit=40):
    """{tasks, methods, building, other}: every method that matters to this campaign, as described in the module."""
    from optimization_framework.execution.service import algorithms
    from optimization_framework.optimizers import plugins
    from optimization_framework.optimizers.registry import BUILTIN_IDS, capability_reason
    store = workspace.store
    tasks = workspace.current_tasks(campaign_id)
    task_rows = []
    for task in tasks:
        try:
            evaluator = workspace.evaluators.readiness(task, wait=False)
        except (KeyError, ValueError) as exc:
            evaluator = {"runnable": False, "reason": str(exc)}
        task_rows.append({"id": task["id"], "name": task.get("name") or task["id"], "problem_id": task.get("problem_id"),
                          "blocker": None if evaluator.get("runnable") else evaluator.get("reason") or "Its evaluator is not ready."})
    hypotheses = [row for row in store.list("hypothesis", campaign_id) if row.get("status") != "archived"]
    installs = {row.get("submission_id"): row for row in store.list("library_install", campaign_id) if row.get("status") == "installed"}
    submissions = latest_submissions(store, campaign_id)
    built_by = {}   # method id -> the submission that delivered it
    for submission in submissions:
        for method in (submission.get("report") or {}).get("methods", []):
            built_by.setdefault(method["method_id"], submission)
    rows, other = [], []
    installed = {method["id"]: method for method in algorithms()}
    for method in installed.values():
        per_task = []
        for task in tasks:
            reason = capability_reason(method["id"], task["problem"]) if task.get("problem") else "The task has no problem definition yet"
            per_task.append({"task_id": task["id"], "runnable": reason is None, "reason": reason})
        proposals = [{"hypothesis_id": h["id"], "bound": True, "default": h.get("algorithm_chosen") is False}
                     for h in hypotheses if h.get("algorithm") == method["id"]]
        submission = built_by.get(method["id"])
        if submission:
            proposals += [{"hypothesis_id": h, "bound": False, "default": False} for h in served(submission)
                          if method["id"] in methods_for(submission, h) and h not in {p["hypothesis_id"] for p in proposals}]
        origin = plugins.installed.origin(method["id"]) if method["id"] not in BUILTIN_IDS else None
        library = bool(origin) and not origin["own"]   # the lab's own plug-ins ship with it: bundled
        # A procedure (replaying, inferring) is not a search method: listed with the others unless a proposal uses it.
        if not (any(row["runnable"] for row in per_task) or proposals or submission) or (method.get("purpose") and not proposals):
            other.append({"id": method["id"], "name": method["name"], "source": "library" if library else "bundled",
                          "reason": f"A procedure for {method['purpose'].replace('_', ' ')}, not a search method" if method.get("purpose")
                          else next((row["reason"] for row in per_task if row["reason"]), None)})
            continue
        install = installs.get(submission["id"]) if submission else None
        unbound = [p["hypothesis_id"] for p in proposals if not p["bound"]]
        next_action = binding(install, unbound) if unbound and any(r["runnable"] for r in per_task) else None
        rows.append({"id": method["id"], "name": method["name"], "source": "library" if library else "bundled",
                     "package": {"name": (origin or {}).get("distribution"), "version": (origin or {}).get("version"),
                                 "commit": (submission or {}).get("commit"), "install_id": (install or {}).get("id")} if library else None,
                     "workspace_id": (submission or {}).get("workspace_id"), "submission_id": (submission or {}).get("id"),
                     "state": "runnable" if any(row["runnable"] for row in per_task) else "incompatible", "tasks": per_task,
                     "proposals": proposals, "next_action": next_action})
    # Delivered but not installed: what the coding agent reported, method by method.
    for submission in submissions:
        report = submission.get("report") or {}
        # Files delivered outside libraries/<name>/ (before libraries were the rule) cannot be installed as a library.
        state = "needs_revision" if submission["status"] == "needs_revision" else "not_installed" if library_of(submission) else "legacy"
        action = {"needs_revision": {"owner": "lead", "text": "Have the coding agent repair what validation found"},
                  "not_installed": installing(store, submission),
                  "legacy": {"owner": "lead", "text": "Have the coding agent rebuild it as a library under libraries/<name>/ if it is still wanted"}}[state]
        listed = [method for method in report.get("methods", []) if method["method_id"] not in installed] if report else [None]
        for method in listed:
            identity = method["method_id"] if method else (submission.get("manifest") or {}).get("entrypoint", submission["commit"][:7])
            rows.append({"id": identity, "name": identity, "source": "submitted", "reported": bool(method),
                         "package": {"name": library_of(submission), "version": None, "commit": submission["commit"], "install_id": None},
                         "workspace_id": submission["workspace_id"], "submission_id": submission["id"],
                         "verdict": report.get("verdict") or "unreported", "implementation": (method or {}).get("state"),
                         "conformance": (method or {}).get("conformance"), "state": state,
                         "tasks": [{"task_id": task["id"], "runnable": False, "reason": {"not_installed": "Not installed", "needs_revision": "Needs revision",
                                    "legacy": "Delivered as files outside libraries/; not installable"}[state]} for task in tasks],
                         "proposals": [{"hypothesis_id": h, "bound": False, "default": False} for h in served(submission)
                                       if not method or method["method_id"] in methods_for(submission, h)],
                         "next_action": action})
    delivered = {submission["workspace_id"] for submission in submissions}
    building = [{"workspace_id": record["id"], "title": record.get("title", ""), "phase": record.get("phase"),
                 "hypothesis_ids": record.get("hypothesis_ids") or [record["hypothesis_id"]]}
                for record in store.list("development_workspace", campaign_id) if record.get("desired_status") == "running" and record["id"] not in delivered]
    order = {"runnable": 0, "not_installed": 1, "needs_revision": 2, "incompatible": 3, "legacy": 4}
    rows.sort(key=lambda row: (order.get(row["state"], 4), row["source"] == "bundled", row["id"]))
    return {"tasks": task_rows, "methods": rows, "building": building, "other": other[:other_limit], "other_count": len(other)}


def unavailable(workspace, campaign_id, limit=30):
    """For the agents (campaign_inspect): the methods that matter here but cannot run, each with why and what next."""
    view = catalog(workspace, campaign_id)
    return {"tasks_blocked": [row for row in view["tasks"] if row["blocker"]],
            "methods": [{"id": row["id"], "source": row["source"], "state": row["state"],
                         "reason": next((t["reason"] for t in row["tasks"] if t["reason"]), None),
                         "proposals": [p["hypothesis_id"] for p in row["proposals"]], "next_action": row["next_action"]}
                        for row in view["methods"] if row["state"] != "runnable"][:limit],
            "building": view["building"][:limit]}
