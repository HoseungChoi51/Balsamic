"""Library entries: immutable records of a strategy that won, with its signature and evidence; search by signature and words; apply as a new root."""
from pydantic import Field

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now

from balsamic.library.signature import match, signature_of


class PublishInput(Contract):
    hypothesis_id: str
    notes: str = Field(default="", max_length=8000)


class ApplyInput(Contract):
    entry_id: str
    note: str = Field(default="", max_length=8000)
    title: str | None = Field(default=None, max_length=300)


def entries(workspace):
    return workspace.store.list("library_entry")


def search(workspace, *, campaign_id=None, problem_id=None, q="", limit=20):
    signature = signature_of(workspace, campaign_id) if campaign_id else {"problem_id": problem_id}
    words = [w for w in (q or "").lower().split() if w]
    rows = []
    for entry in entries(workspace):
        score, reasons = match(entry["signature"], signature) if (campaign_id or problem_id) else (0, [])
        haystack = " ".join(str(v) for v in (entry["strategy"].get("title"), entry["strategy"].get("mechanism"), entry["strategy"].get("algorithm"), entry.get("notes"))).lower()
        if words:
            hits = sum(1 for w in words if w in haystack)
            if not hits:
                continue
            score += 1; reasons.append(f"matches {hits} of {len(words)} words")
        if problem_id and entry["signature"].get("problem_id") != problem_id:
            continue
        rows.append({"entry": entry, "match": {"score": score, "reasons": reasons}})
    rows.sort(key=lambda row: (-row["match"]["score"], row["entry"]["created_at"]))
    return {"signature": signature, "entries": rows[:limit]}


def publish(workspace, campaign_id, values, *, command_id, actor):
    if actor != "researcher":
        raise ValueError("Only the researcher publishes to the library")
    store = workspace.store
    hypothesis = store.get(values.hypothesis_id, "hypothesis")
    if hypothesis["campaign_id"] != campaign_id:
        raise ValueError("The strategy belongs to another campaign")
    from balsamic.evolution.ledger import rows as ledger_rows
    row = next((r for r in ledger_rows(workspace, campaign_id)[0] if r["id"] == values.hypothesis_id), None)
    if row is None:
        raise ValueError("No ledger row for this strategy")
    promising = bool((row.get("confirmation") or {}).get("promising"))
    if not (row["finalist"] or promising):
        raise ValueError("Only a finalist, or a strategy whose confirmation was promising, goes to the library")
    existing = [e for e in entries(workspace) if e["hypothesis_id"] == values.hypothesis_id]
    if existing:
        return {"entry_id": existing[-1]["id"], "entry": existing[-1], "already": True}
    # Other campaigns reuse what is here: the best score passed the problem's fidelity check, or the researcher waived it (V3).
    from optimization_framework.campaigns import promotion
    fidelity = promotion.fidelity_state(workspace, hypothesis)
    if fidelity["state"] not in promotion.OPEN:
        raise ValueError("A library entry needs its best score to pass the problem's fidelity check, or your waiver. "
                         + promotion.explain(fidelity, agent=False))
    signature = signature_of(workspace, campaign_id)
    trials = [t for t in store.list("trial", campaign_id) if t.get("hypothesis_id") == values.hypothesis_id]
    finalist = next((s for s in store.list("finalist_selection", campaign_id) if set(s.get("trial_ids", [])) & {t["id"] for t in trials}), None)
    record = {"id": "library_" + content_hash(command_id)[:20], "origin_campaign_id": campaign_id, "hypothesis_id": values.hypothesis_id,
              "strategy": {key: hypothesis.get(key) for key in ("title", "mechanism", "rationale", "algorithm", "algorithm_config", "implementation_version_id")},
              "signature": {key: signature.get(key) for key in ("problem_id", "evaluator_version", "objective", "representation", "dimensions", "constraint_digest", "instance_digest", "charter_id")},
              "evidence": {"confirmation_protocol_id": (row.get("confirmation") or {}).get("protocol_id"), "race_id": (row.get("race") or {}).get("race_id"),
                           "finalist_selection_id": finalist["id"] if finalist else None, "best_score": row["best"]["score"], "best_basis": row["best"]["basis"], "interval": None,
                           "seeds_won": (row.get("confirmation") or {}).get("seeds_won"), "worker_seconds": row["worker_seconds"], "trial_ids": row["trial_ids"],
                           "fidelity": promotion.record(fidelity)},
              "graph": {"thread_id": None, "round": row.get("round"), "stage": row["stage"], "parent_links": row.get("parent_links")},
              "notes": values.notes, "published_by": actor, "created_at": now()}
    record = store.put_immutable("library_entry", record, "library.published")
    hypothesis["library_entry_id"] = record["id"]
    store.put("hypothesis", hypothesis)
    return {"entry_id": record["id"], "entry": record, "already": False}


def apply(workspace, campaign_id, values, *, command, actor):
    """A new root strategy in this campaign, inspired by the entry; the campaign's signature is compared and said."""
    entry = workspace.store.get(values.entry_id, "library_entry")
    score, reasons = match(entry["signature"], signature_of(workspace, campaign_id))
    from optimization_framework.contracts.requests import HypothesisInput
    from optimization_framework.campaigns import hypotheses
    strategy = entry["strategy"]
    values_in = HypothesisInput(campaign_id=campaign_id, title=values.title or f"{strategy['title']} (from the library)", mechanism=strategy.get("mechanism") or "",
                                rationale=((strategy.get("rationale") or "") + f"\n\nApplied from library entry {entry['id']} (campaign {entry['origin_campaign_id']}; "
                                           f"best measured {entry['evidence'].get('best_score')}). Fit here: {', '.join(reasons) or 'no shared signature'} (score {score})."
                                           + (f"\nResearcher's note: {values.note}" if values.note else "")).strip(),
                                algorithm=strategy.get("algorithm") or "", algorithm_config=strategy.get("algorithm_config") or {},
                                implementation_version_id=None, library_entry_id=entry["id"])
    bundle = None
    if strategy.get("implementation_version_id"):
        try:
            bundle = workspace.implementations.fetch(strategy["implementation_version_id"]) if hasattr(workspace.implementations, "fetch") else None
        except Exception:
            bundle = None
        if bundle is not None:
            values_in = values_in.model_copy(update={"implementation_version_id": strategy["implementation_version_id"]})
    record = hypotheses.create(workspace, campaign_id, values_in, identity="hypothesis_" + command.id, bundle=bundle)
    if actor != "researcher":
        from optimization_framework.campaigns.proposals import researcher_request
        asked = researcher_request(workspace, command.origin)
        record.update(origin="pi", requires_concept_review=True, **({"requested_by": asked} if asked else {}))
        workspace.store.put("hypothesis", record)
    return {"hypothesis_id": record["id"], "hypothesis": record, "entry_id": entry["id"], "match": {"score": score, "reasons": reasons}}


def register(workspace):
    commands = workspace.commands

    def publish_command(command, actor):
        return publish(workspace, command.campaign_id, PublishInput(**command.payload), command_id=command.id, actor=actor)

    def apply_command(command, actor):
        return apply(workspace, command.campaign_id, ApplyInput(**command.payload), command=command, actor=actor)

    commands.register("library.publish", publish_command, model=PublishInput)
    commands.register("library.apply", apply_command, model=ApplyInput, delegable=True)
