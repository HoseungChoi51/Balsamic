"""Researcher idea records and feedback, independent of requesting a model turn."""
from optimization_framework.storage.sqlite import now


def create(workspace, campaign_id, values, *, identity, bundle=None):
    from optimization_framework.execution.service import algorithms
    campaign = workspace.store.get(campaign_id, "campaign")
    for parent in values.parent_ids:
        if workspace.store.get(parent, "hypothesis")["campaign_id"] != campaign_id:
            raise ValueError("Parents must belong to this campaign")
    links = [link.model_dump(mode="json") for link in values.parent_links]
    linked = [link["id"] for link in links]
    if set(linked) - set(values.parent_ids):
        values = values.model_copy(update={"parent_ids": list(dict.fromkeys([*values.parent_ids, *linked]))})
        for parent in values.parent_ids:
            if workspace.store.get(parent, "hypothesis")["campaign_id"] != campaign_id:
                raise ValueError("Parents must belong to this campaign")
    links += [{"id": parent, "kind": "hybrid" if len(values.parent_ids) > 1 else "revision"} for parent in values.parent_ids if parent not in linked]
    if values.library_entry_id and not any(link["kind"] == "inspired_by" for link in links):
        links.append({"id": values.library_entry_id, "kind": "inspired_by"})
    record = {**values.model_dump(mode="json"), "parent_links": links, "id": identity, "created_at": now(),
        "charter_version": campaign["version"], "origin": "researcher", "reviews": [], "status_revision": 0,
        "claim_level": "rationale_only", "executable": values.algorithm in {item["id"] for item in algorithms()},
        # The default search lane is recorded like a choice; the page says when it was not one.
        "algorithm_chosen": "algorithm" in values.model_fields_set}
    if values.implementation_version_id:
        if bundle is None or bundle["version"]["id"] != values.implementation_version_id:
            raise ValueError("A verified implementation binding is required")
        record.update(algorithm="package", executable=True, implementation_status="validated")
        workspace.implementations._exposure(campaign_id, bundle["version"])
    if values.status == "finalist":
        record = nominate(workspace, record)
    return workspace.store.put("hypothesis", record, "hypothesis.created")


def nominate(workspace, hypothesis):
    from optimization_framework.evaluation.legacy_confirmation import nominate_finalist
    readiness = workspace.implementations.readiness(hypothesis)
    if not readiness["runnable"]:
        raise ValueError(readiness["reason"])
    return nominate_finalist(hypothesis)


AGENT_ACTORS = {"manager", "autopilot"}


def stop_of(hypothesis):
    """A stopped strategy's stop record; one stopped before typed outcomes reads as unspecified."""
    if hypothesis.get("status") != "archived":
        return None
    stop = hypothesis.get("stop") or {"outcome": "unspecified", "evidence_ids": [], "reason": hypothesis.get("stop_reason"),
                                      "by": None, "at": hypothesis.get("stopped_at")}
    from optimization_framework.contracts.commands import STOP_WORDS
    words = STOP_WORDS.get(stop["outcome"], stop["outcome"])
    return {**stop, "words": words, "label": "stopped: " + words}


def stop_record(workspace, hypothesis, *, outcome=None, evidence_ids=(), reason=None, actor="researcher"):
    """An agent's stop names an outcome and the visible records it rests on; the researcher's may name none."""
    evidence_ids = list(dict.fromkeys(evidence_ids))
    if actor in AGENT_ACTORS:
        if outcome is None or not evidence_ids:
            raise ValueError("An agent's stop needs a stop outcome and at least one evidence id: the trials, comparisons, "
                             "validation results or reviews it rests on")
    if evidence_ids:
        from .findings import visible_evidence
        campaign_id = hypothesis["campaign_id"]
        visible = visible_evidence(workspace, campaign_id)
        visible.update(review["id"] for item in workspace.store.list("hypothesis", campaign_id) for review in item.get("reviews") or [])
        hidden = [identity for identity in evidence_ids if identity not in visible]
        if hidden:
            raise ValueError(f"A stop cites evidence that is not a visible record of this campaign: {', '.join(hidden[:5])}")
    return {"outcome": outcome or ("researcher_decision" if actor == "researcher" else "unspecified"), "evidence_ids": evidence_ids,
            "reason": reason, "by": actor, "at": now()}


def set_status(workspace, hypothesis, status, expected_revision, *, stop_reason=None, outcome=None, evidence_ids=(), actor="researcher"):
    revision = hypothesis.get("status_revision", 0)
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("Idea status changed; refresh before changing it again")
    stop = stop_record(workspace, hypothesis, outcome=outcome, evidence_ids=evidence_ids, reason=stop_reason, actor=actor) if status == "archived" else None
    changed = nominate(workspace, hypothesis) if status == "finalist" else {**hypothesis, "status": status}
    if status == "archived":
        changed["stop_reason"] = stop_reason or hypothesis.get("stop_reason") or "stopped without a stated reason"
        changed["stopped_at"] = stop["at"]
        changed["stop"] = {**stop, "reason": changed["stop_reason"]}
    elif hypothesis.get("status") == "archived":
        for key in ("stop_reason", "stopped_at", "stop"):
            changed.pop(key, None)
    if changed != hypothesis:
        changed.update(status_revision=revision + 1, updated_at=now())
        workspace.store.put("hypothesis", changed, "hypothesis.status")
    return changed


def review(workspace, hypothesis, text, *, identity, author="researcher"):
    hypothesis.setdefault("reviews", []).append({"id": identity, "text": text, "author": author, "created_at": now()})
    return workspace.store.put("hypothesis", hypothesis, "hypothesis.reviewed")
