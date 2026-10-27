"""Monitor rows: problem, budget (measured and forecast, labelled), compute (workers, queue, GPU), agents, autopilot, needs-you; and the pill.

Unknown is said, never shown as zero; a forecast is called a forecast."""


def inbox_view(workspace, campaign_id):
    from optimization_framework.campaigns.decisions import public_decision
    store = workspace.store
    decisions = [public_decision(workspace, row) for row in store.list("decision", campaign_id) if row.get("status") in {"pending", "executing"}]
    issues = [row for row in store.list("manager_issue", campaign_id) if row.get("status") == "pending"]
    questions = [row for row in store.list("agent_question", campaign_id) if row.get("status") == "pending"]
    # What the lead closed as no longer holding stays in view with its reason (the latest 30); the researcher can reopen it.
    closed = sorted((row for row in store.list("manager_issue", campaign_id) if row.get("status") == "resolved" and row.get("resolved_by") == "lead"),
                    key=lambda row: row.get("resolved_at") or "")[-30:]
    notices = compute_notices(workspace, campaign_id)
    implementations = implementation_outcomes(workspace, campaign_id) + install_outcomes(workspace, campaign_id)
    items = inbox_items(decisions, issues, questions, closed, notices, implementations)
    seen = set(acknowledged(workspace, campaign_id))
    from optimization_framework.campaigns.compute_consent import thresholds
    notice_seconds, gate_seconds = thresholds(workspace, campaign_id)
    return {"decisions": decisions, "issues": issues, "questions": questions,
            "resolved": [row for row in store.list("decision", campaign_id) if row.get("status") == "resolved"][-20:],
            "closed_by_lead": closed, "notices": notices, "implementations": implementations, "thresholds": {"notice_seconds": notice_seconds, "gate_seconds": gate_seconds},
            "unacknowledged": [item for item in items if item["key"] not in seen]}


def compute_notices(workspace, campaign_id, limit=30):
    """Work an agent started between the researcher's two thresholds, without waiting for their go-ahead (the latest 30), each
    with who started it."""
    store = workspace.store
    roles = {row["id"]: row.get("role") for row in store.list("agent_session", campaign_id)}
    rows = sorted(store.list("compute_notice", campaign_id), key=lambda row: row.get("created_at") or "")[-limit:]
    rows = [{**row, "role": roles.get(row.get("agent_id"))} for row in rows]
    return [{**row, "title": notice_title(row)} for row in rows]


# A coding workspace's results the researcher hears about; validating and stopped are steps someone took, not news.
INBOX_OUTCOMES = {"delivered", "validated", "needs_revision", "failed"}


def implementation_outcomes(workspace, campaign_id):
    """Each coding workspace's latest result worth the researcher's attention (a delivery with the coding agent's verdict, a
    validation's result, a failure), back in the inbox whenever it changes."""
    from optimization_framework.agents.development import outcome
    store = workspace.store
    submissions = store.list("development_submission", campaign_id)
    by_id = {row["id"]: row for row in submissions}
    rows = []
    for record in store.list("development_workspace", campaign_id):
        result = outcome(record, submissions)
        if result and result["state"] in INBOX_OUTCOMES:
            rows.append({**result, "workspace_id": record["id"], "workspace_title": record.get("title", ""),
                         "title": outcome_title(record, result, by_id.get(result.get("submission_id")))})
    return sorted(rows, key=lambda row: row["at"] or "")


def install_outcomes(workspace, campaign_id):
    """Each delivered library's latest install that is news: installed (with its methods), waiting for the researcher's yes
    because it would change installed packages, or failed."""
    from optimization_framework.agents.library_install import added
    latest = {}
    for row in sorted(workspace.store.list("library_install", campaign_id), key=lambda row: row["requested_at"]):
        latest[row["submission_id"]] = row
    rows = []
    for row in latest.values():
        name = row.get("package") or row.get("path") or "the library"
        title = {"installed": f"Installed {name} {row.get('version') or ''}: {added(row)}",
                 "needs_confirmation": f"Installing {name} waits for your yes: it would change "
                                       + ", ".join(f"{c['name']} {c['from']} → {c.get('to') or 'removed'}" for c in row.get("changes", [])),
                 "failed": f"Installing {name} failed: {_first_line(row.get('error'), 120)}"}.get(row["status"])
        if title:
            rows.append({"workspace_id": row["workspace_id"], "workspace_title": "", "state": "install_" + row["status"], "at": row.get("finished_at") or row["requested_at"],
                         "submission_id": row["id"], "title": title.replace("  ", " ")})
    return rows


def outcome_title(record, result, submission):
    from optimization_framework.agents.development_timeline import VERDICTS, tests_text
    name = _first_line(record.get("title"), 80)
    if result["state"] == "failed":
        return f"Implementation failed: {name}: its workspace could not run for 30 min"
    if result["state"] == "validated":
        return f"Implementation validated: {name}"
    if result["state"] == "needs_revision":
        return f"Implementation needs revision: {name}: independent validation found problems"
    report = (submission or {}).get("report")
    if not report:
        return f"Implementation delivered: {name}, without a delivery report"
    return f"Implementation delivered: {name}: {VERDICTS[report['verdict']]}, {tests_text(report['tests'])}"


def notice_title(row):
    from optimization_framework.campaigns.compute_consent import _minutes
    who = "The " + row["role"].replace("_", " ") if row.get("role") else "An agent"
    return f"{who} started {row['what']}, about {_minutes(float(row['seconds']))} of compute"


def _first_line(text, limit=160):
    line = next((part.strip() for part in str(text or "").splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[:limit].rsplit(" ", 1)[0] + "…"


def inbox_items(decisions, issues, questions, closed, notices=(), implementations=()):
    """Everything in the inbox, newest first, each under a key that changes when the item changes: what the researcher
    acknowledged once comes back when it is raised again or revised."""
    items = [{"key": f"{row['id']}:{row.get('resolution_revision', 0)}", "kind": "decision", "id": row["id"], "title": _first_line(row.get("title")),
              "at": row.get("created_at")} for row in decisions]
    items += [{"key": f"{row['id']}:{row.get('revision', 1)}", "kind": "issue", "id": row["id"], "title": _first_line(row.get("message")),
               "at": row.get("updated_at") or row.get("created_at")} for row in issues]
    items += [{"key": row["id"], "kind": "question", "id": row["id"], "title": _first_line(row.get("question") or row.get("title")),
               "at": row.get("created_at")} for row in questions]
    items += [{"key": f"{row['id']}:{row.get('revision', 1)}", "kind": "closed", "id": row["id"], "title": _first_line(row.get("comment")),
               "at": row.get("resolved_at")} for row in closed]
    items += [{"key": row["id"], "kind": "notice", "id": row["id"], "title": notice_title(row), "at": row.get("created_at")} for row in notices]
    items += [{"key": f"implementation:{row['workspace_id']}:{row['state']}:{row.get('submission_id') or row['at']}", "kind": "implementation",
               "id": row["workspace_id"], "title": row["title"], "at": row["at"]} for row in implementations]
    return sorted(items, key=lambda item: item["at"] or "", reverse=True)


def acknowledged(workspace, campaign_id):
    try:
        return workspace.store.get(f"inbox_seen_{campaign_id}", "inbox_seen")["keys"]
    except KeyError:
        return []


def acknowledge(workspace, campaign_id, keys):
    """Record that the researcher saw these inbox items; only keys of items still in the inbox are kept."""
    from optimization_framework.storage.sqlite import now
    view = inbox_view(workspace, campaign_id)
    live = {item["key"] for item in inbox_items(view["decisions"], view["issues"], view["questions"], view["closed_by_lead"], view["notices"],
                                                view["implementations"])}
    keys = sorted(live & (set(acknowledged(workspace, campaign_id)) | set(keys)))
    return workspace.store.put("inbox_seen", {"id": f"inbox_seen_{campaign_id}", "campaign_id": campaign_id, "keys": keys[-500:],
                                              "updated_at": now()}, "inbox.acknowledged")


def gpu_row(host):
    """The GPU row from the host snapshot: busy when any device is measured busy; honest when nothing is reported."""
    gpu = (host or {}).get("gpu")
    devices = gpu.get("devices") if isinstance(gpu, dict) else gpu if isinstance(gpu, list) else []
    readings = [d for d in (devices or []) if isinstance(d, dict)]
    measured = [d for d in readings if isinstance(d.get("utilization_percent"), (int, float))]
    if not readings:
        return {"reported": False, "basis": "no GPU reported by the host"}
    if not measured:
        return {"reported": True, "measured": False, "devices": len(readings), "basis": "devices listed; utilization not measured (nvidia-smi unavailable)"}
    return {"reported": True, "measured": True, "devices": len(readings), "busy": any(d["utilization_percent"] >= 10 for d in measured),
            "utilization_percent": max(d["utilization_percent"] for d in measured),
            "memory_used_bytes": sum(d.get("memory_used_bytes") or 0 for d in measured), "memory_total_bytes": sum(d.get("memory_total_bytes") or 0 for d in measured),
            "basis": "measured by nvidia-smi"}


def monitor_view(workspace, campaign_id):
    store = workspace.store
    campaign = store.get(campaign_id, "campaign")
    try:
        assessment = workspace.resources.assessment(campaign_id)
    except (KeyError, ValueError) as exc:
        assessment = {"unavailable": str(exc)}
    live = store.list_trials_in_status({"queued", "running", "pausing", "stopping"}, campaign_id)
    remaining_live = sum(max(0.0, float(t.get("wall_seconds") or 0) - float(t.get("execution_seconds") or 0)) for t in live)
    budget_seconds = float(campaign.get("compute_budget_seconds") or 0)
    worker = {"budget_seconds": budget_seconds, **({"allocated_seconds": assessment["allocated_seconds"], "actual_seconds": assessment["actual_seconds"],
              "forecast_seconds": assessment["actual_seconds"] + remaining_live, "forecast_basis": "measured use plus the remaining allotment of live runs"}
              if "allocated_seconds" in assessment else {"unavailable": assessment.get("unavailable")}),
              "exhausted": "allocated_seconds" in assessment and assessment["allocated_seconds"] >= budget_seconds - 1e-6 and budget_seconds > 0}
    from optimization_framework.agents import usage
    charged = usage.charged(store, campaign_id)
    committed = workspace.implementations.api_committed(campaign_id)
    cap = campaign.get("llm_budget_usd")
    llm = {"cap_usd": cap, "agent_charged_usd": charged, "implementation_committed_usd": committed, "spent_usd": charged + committed,
           "exhausted": cap is not None and charged + committed >= float(cap) - 1e-9 and float(cap) > 0,
           "basis": "charged by the harness's price catalogue; subscription calls cost nothing here"}
    admission = getattr(workspace, "admission", None)
    try:
        admission_view = admission.view(campaign_id) if admission is not None else None
    except (KeyError, ValueError) as exc:
        admission_view = {"unavailable": str(exc)}
    host = None
    try:
        from optimization_framework.execution.observability import get_observer
        snapshot = get_observer(workspace).snapshot(campaign_id)
        host = snapshot.get("host") if isinstance(snapshot, dict) else None
    except Exception:   # the host snapshot is best effort; the row says when it is missing
        host = None
    compute = {"busy": len(live), "limit": workspace.max_workers, "pools": workspace.devices.view([t for t in live if t["status"] != "queued"]), "queued": len((admission_view or {}).get("waiting") or []) if isinstance(admission_view, dict) else None,
               "waiting": (admission_view or {}).get("waiting") if isinstance(admission_view, dict) else None, "level": admission.level().get("level") if admission is not None else None,
               "gpu": gpu_row(host), "host": {"cpu_percent": ((host or {}).get("cpu") or {}).get("utilization_percent"), "memory_available_bytes": ((host or {}).get("memory") or {}).get("effective_available_bytes")} if host else None}
    try:
        agents = workspace.pi.progress(campaign_id) if workspace.pi.owns(campaign_id) else {"status": "absent", "headline": "No agent team yet", "active": False}
    except (KeyError, ValueError) as exc:
        agents = {"status": "unknown", "headline": str(exc), "active": False}
    inbox = inbox_view(workspace, campaign_id)
    needs_you = {"decisions": len(inbox["decisions"]), "issues": len(inbox["issues"]), "questions": len(inbox["questions"])}
    from balsamic.autopilot.rounds import round_state
    try:
        autopilot = round_state(workspace, campaign_id)
    except (KeyError, ValueError) as exc:
        autopilot = {"enabled": False, "reason": str(exc), "can_start": False}
    from balsamic.monitor.digest import open_digest
    digest = open_digest(workspace, campaign_id)
    rows = {"problem": {"name": campaign["name"], "objective": campaign.get("objective"), "tasks": len([t for t in store.list("task", campaign_id) if not t.get("archived")]), "stage_pin": campaign.get("stage_pin")},
            "budget": {"worker": worker, "llm": llm}, "compute": compute, "agents": agents, "autopilot": autopilot, "needs_you": needs_you}
    attention = []
    if sum(needs_you.values()):
        attention.append(("needs_you", f"{sum(needs_you.values())} waiting for you"))
    from balsamic.monitor.stalls import attention as stalled
    attention.extend(stalled(workspace, campaign_id))
    if agents.get("status") in {"paused", "stopped", "failed"}:
        attention.append(("agents", "The agent team is " + agents["status"]))
    if worker.get("exhausted"):
        attention.append(("budget", "Worker budget exhausted"))
    if llm["exhausted"]:
        attention.append(("budget", "Model budget exhausted"))
    if "unavailable" in worker:
        attention.append(("budget", "Worker accounting unavailable"))
    if digest:
        pill = {"state": "digest", "text": "Away digest", "row": "digest"}
    elif attention:
        pill = {"state": "attention", "text": attention[0][1], "row": attention[0][0]}
    else:
        pill = {"state": "clear", "text": "All clear", "row": None}
    return {"rows": rows, "pill": pill, "attention": [{"row": row, "text": text} for row, text in attention], "digest_id": digest["id"] if digest else None}
