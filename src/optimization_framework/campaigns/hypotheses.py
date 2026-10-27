"""Researcher idea records and feedback, independent of requesting a model turn."""
from optimization_framework.storage.sqlite import now


def create(workspace, campaign_id, values, *, identity, bundle=None):
    from optimization_framework.contracts.requests import UNCHOSEN
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
        # A proposal without a method records none (unchosen); the page asks for a choice.
        "algorithm_chosen": "algorithm" in values.model_fields_set and values.algorithm != UNCHOSEN}
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


def set_status(workspace, hypothesis, status, expected_revision, *, stop_reason=None):
    revision = hypothesis.get("status_revision", 0)
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("Idea status changed; refresh before changing it again")
    changed = nominate(workspace, hypothesis) if status == "finalist" else {**hypothesis, "status": status}
    if status == "archived":
        changed["stop_reason"] = stop_reason or hypothesis.get("stop_reason") or "stopped without a stated reason"
        changed["stopped_at"] = now()
    elif hypothesis.get("status") == "archived":
        changed.pop("stop_reason", None); changed.pop("stopped_at", None)
    if changed != hypothesis:
        changed.update(status_revision=revision + 1, updated_at=now())
        workspace.store.put("hypothesis", changed, "hypothesis.status")
    return changed


def review(workspace, hypothesis, text, *, identity, author="researcher"):
    hypothesis.setdefault("reviews", []).append({"id": identity, "text": text, "author": author, "created_at": now()})
    return workspace.store.put("hypothesis", hypothesis, "hypothesis.reviewed")
