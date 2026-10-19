"""Monitor rows: problem, budget, compute, agents, needs-you. Labels are honest: measured vs forecast, unknown is not zero."""


def inbox_view(workspace, campaign_id):
    from optimization_framework.campaigns.decisions import public_decision
    store = workspace.store
    decisions = [public_decision(workspace, row) for row in store.list("decision", campaign_id) if row.get("status") in {"pending", "executing"}]
    issues = [row for row in store.list("manager_issue", campaign_id) if row.get("status") == "pending"]
    questions = [row for row in store.list("agent_question", campaign_id) if row.get("status") == "pending"]
    return {"decisions": decisions, "issues": issues, "questions": questions,
            "resolved": [row for row in store.list("decision", campaign_id) if row.get("status") == "resolved"][-20:]}


def monitor_view(workspace, campaign_id):
    store = workspace.store
    campaign = store.get(campaign_id, "campaign")
    try:
        budget = workspace.resources.assessment(campaign_id)
    except (KeyError, ValueError) as exc:
        budget = {"unavailable": str(exc)}
    admission = getattr(workspace, "admission", None)
    try:
        compute = admission.view(campaign_id) if admission is not None else None
    except (KeyError, ValueError) as exc:
        compute = {"unavailable": str(exc)}
    try:
        agents = workspace.pi.progress(campaign_id) if workspace.pi.owns(campaign_id) else {"status": "absent", "headline": "No agent team yet"}
    except (KeyError, ValueError) as exc:
        agents = {"status": "unknown", "headline": str(exc)}
    inbox = inbox_view(workspace, campaign_id)
    needs_you = {"decisions": len(inbox["decisions"]), "issues": len(inbox["issues"]), "questions": len(inbox["questions"])}
    live = [trial for trial in store.list("trial", campaign_id) if trial.get("status") in {"queued", "running", "pausing", "stopping"}]
    from optimization_framework.agents import usage
    llm = {"cap_usd": campaign.get("llm_budget_usd"), "agent_charged_usd": usage.charged(store, campaign_id),
           "implementation_committed_usd": workspace.implementations.api_committed(campaign_id)}
    rows = {"problem": {"name": campaign["name"], "objective": campaign.get("objective"), "tasks": len(store.list("task", campaign_id))},
            "budget": {"worker": budget, "llm": llm},
            "compute": {"busy": len(live), "limit": workspace.max_workers, "admission": compute, "level": admission.level() if admission is not None else None},
            "agents": agents, "needs_you": needs_you}
    attention = []
    if sum(needs_you.values()):
        attention.append(("needs_you", f"{sum(needs_you.values())} waiting for you"))
    if agents.get("status") in {"paused", "stopped"}:
        attention.append(("agents", "The agent team is " + agents["status"]))
    if isinstance(budget, dict) and budget.get("exhausted"):
        attention.append(("budget", "Worker budget exhausted"))
    pill = {"state": "attention" if attention else "clear", "text": attention[0][1] if attention else "All clear", "row": attention[0][0] if attention else None}
    return {"rows": rows, "pill": pill, "digest_id": None}
