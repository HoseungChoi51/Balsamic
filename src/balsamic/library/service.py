"""Library entries: immutable records of a strategy that won, or of one assessed and stopped (roadmap K4), with its
signature and evidence; search by signature and words; apply as a new root.

An entry records the winner's code (roadmap L5): the package, version and method it ran, when its method comes from an installed
package. Applying an entry whose method is installed and runs on a current task gives a proposal bound to it, ready to run;
one whose method is not installed says so.

A positive entry is a finalist or a strategy whose confirmation was promising. A negative entry is a stopped strategy
whose typed stop (V1) is a judgement of the method: `configuration_unpromising` or `adequately_assessed_deprioritized`
after an adequate assessment or the researcher's tuning waiver (V2), or `implementation_invalid` or
`assumptions_incompatible` with their evidence. Entries written before K4 have no kind and read as positive.
"""
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now

from balsamic.library.signature import match, signature_of


# Stops that judge the method, and so may go to the library as a negative entry; the others say nothing about it.
JUDGEMENTS = {"configuration_unpromising", "adequately_assessed_deprioritized", "implementation_invalid", "assumptions_incompatible"}
NEGATIVE_LABEL = "assessed and stopped"


class PublishInput(Contract):
    hypothesis_id: str
    kind: Literal["positive", "negative"] = "positive"
    notes: str = Field(default="", max_length=8000)


class ApplyInput(Contract):
    entry_id: str
    note: str = Field(default="", max_length=8000)
    title: str | None = Field(default=None, max_length=300)


def entries(workspace):
    return workspace.store.list("library_entry")


def kind_of(entry):
    return entry.get("kind") or "positive"


def label_of(entry):
    """What a search row says of the entry: a negative one is "assessed and stopped", with its outcome in words."""
    if kind_of(entry) != "negative":
        return None
    return f"{NEGATIVE_LABEL}: {(entry.get('stop') or {}).get('words') or 'no outcome recorded'}"


def search(workspace, *, campaign_id=None, problem_id=None, q="", limit=20):
    signature = signature_of(workspace, campaign_id) if campaign_id else {"problem_id": problem_id}
    words = [w for w in (q or "").lower().split() if w]
    rows = []
    for entry in entries(workspace):
        score, reasons = match(entry["signature"], signature) if (campaign_id or problem_id) else (0, [])
        haystack = " ".join(str(v) for v in (entry["strategy"].get("title"), entry["strategy"].get("mechanism"), entry["strategy"].get("algorithm"), entry.get("notes"),
                                              (entry.get("stop") or {}).get("reason"))).lower()
        if words:
            hits = sum(1 for w in words if w in haystack)
            if not hits:
                continue
            score += 1; reasons.append(f"matches {hits} of {len(words)} words")
        if problem_id and entry["signature"].get("problem_id") != problem_id:
            continue
        rows.append({"entry": entry, "match": {"score": score, "reasons": reasons}, "kind": kind_of(entry), "label": label_of(entry)})
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
    existing = [e for e in entries(workspace) if e["hypothesis_id"] == values.hypothesis_id]
    if existing:
        return {"entry_id": existing[-1]["id"], "entry": existing[-1], "already": True}
    if values.kind == "negative":
        return _publish_negative(workspace, campaign_id, values, hypothesis, row, command_id=command_id, actor=actor)
    promising = bool((row.get("confirmation") or {}).get("promising"))
    if not (row["finalist"] or promising):
        raise ValueError("Only a finalist, or a strategy whose confirmation was promising, goes to the library")
    # Other campaigns reuse what is here: the best score passed the problem's fidelity check, or the researcher waived it (V3).
    from optimization_framework.campaigns import promotion
    fidelity = promotion.fidelity_state(workspace, hypothesis)
    if fidelity["state"] not in promotion.OPEN:
        raise ValueError("A library entry needs its best score to pass the problem's fidelity check, or your waiver. "
                         + promotion.explain(fidelity, agent=False))
    signature = signature_of(workspace, campaign_id)
    trials = [t for t in store.list("trial", campaign_id) if t.get("hypothesis_id") == values.hypothesis_id]
    finalist = next((s for s in store.list("finalist_selection", campaign_id) if set(s.get("trial_ids", [])) & {t["id"] for t in trials}), None)
    record = {"id": "library_" + content_hash(command_id)[:20], "kind": "positive", "origin_campaign_id": campaign_id, "hypothesis_id": values.hypothesis_id,
              "strategy": {key: hypothesis.get(key) for key in ("title", "mechanism", "rationale", "family", "algorithm", "algorithm_config", "implementation_version_id")},
              "signature": {key: signature.get(key) for key in ("problem_id", "evaluator_version", "objective", "representation", "dimensions", "constraint_digest", "instance_digest", "charter_id")},
              "code": code_of(workspace, hypothesis),
              "evidence": {"confirmation_protocol_id": (row.get("confirmation") or {}).get("protocol_id"), "race_id": (row.get("race") or {}).get("race_id"),
                           "finalist_selection_id": finalist["id"] if finalist else None, "best_score": row["best"]["score"], "best_basis": row["best"]["basis"], "interval": None,
                           "seeds_won": (row.get("confirmation") or {}).get("seeds_won"), "worker_seconds": row["worker_seconds"], "trial_ids": row["trial_ids"],
                           "fidelity": promotion.record(fidelity)},
              "graph": {"thread_id": None, "round": row.get("round"), "stage": row["stage"], "parent_links": row.get("parent_links")},
              "notes": values.notes, "published_by": actor, "created_at": now()}
    return _write(workspace, hypothesis, record)


def code_of(workspace, hypothesis):
    """The code a strategy ran (roadmap L5): {package, version, method, library_version_id} when its method comes from an installed
    package, else None (a bundled method, or a published implementation, which the strategy names itself)."""
    from optimization_framework.agents import library_repository as repositories
    from optimization_framework.campaigns.method_catalog import package_of
    method = hypothesis.get("algorithm")
    package = package_of(method) if method else None
    if package is None:
        return None
    version = next((row for row in repositories.versions(workspace.store)
                    if row.get("package") == package["name"] and row.get("version") == package["version"]), None)
    return {"package": package["name"], "version": package["version"], "method": method, "library_version_id": (version or {}).get("id")}


def _bound(workspace, campaign_id, entry, record, *, command, actor):
    """Bind the applied proposal to the entry's installed method (roadmap L5): {binding} or {not_bound: why}."""
    from optimization_framework.campaigns.method_catalog import package_of
    from optimization_framework.execution.service import algorithms
    from optimization_framework.implementations.builtin import bind
    from optimization_framework.optimizers.registry import capability_reason
    method, code = record.get("algorithm"), entry.get("code") or {}
    if not method or record.get("implementation_version_id"):
        return {}
    if method not in {row["id"] for row in algorithms()}:
        named = f" from package {code['package']} {code['version']}" if code else ""
        return {"not_bound": f"{method}{named} is not installed in this lab: build it in a coding workspace, or install the package"}
    task = next((task for task in workspace.current_tasks(campaign_id) if task.get("problem")
                 and capability_reason(method, task["problem"]) is None), None)
    if task is None:
        return {"not_bound": f"{method} runs on no current task of this campaign"}
    package = package_of(method)
    where = f"package {package['name']} {package['version']}" if package else "Balsamic"
    try:
        binding = bind(workspace, campaign_id, {"hypothesis_id": record["id"], "task_id": task["id"], "algorithm": method,
            "parameters": record.get("algorithm_config") or {}, "expected_algorithm": method,
            "expected_configuration_hash": content_hash(record.get("algorithm_config") or {}),
            "reason": f"Applied from library entry {entry['id']}: {method}, installed from {where}, runs on {task['id']}; reuse needs no coding time."},
            "apply_" + command.id, actor=actor)
    except ValueError as exc:
        return {"not_bound": str(exc)[:300]}
    if code and package and code.get("version") != package["version"]:
        binding["note"] = f"The entry ran {code['package']} {code['version']}; the lab runs {package['version']}, which reproduces its kept methods (L4)"
    return {"binding": binding}


def _write(workspace, hypothesis, record):
    record = workspace.store.put_immutable("library_entry", record, "library.published")
    hypothesis["library_entry_id"] = record["id"]
    workspace.store.put("hypothesis", hypothesis)
    return {"entry_id": record["id"], "entry": record, "already": False}


def _assessment_basis(workspace, hypothesis, stop):
    """Why a performance stop may stand as a verdict: the assessment was adequate, or the researcher waived the minimums.
    The stop's own record decides; a waiver given after the stop counts too. None when neither holds."""
    from optimization_framework.campaigns.assessment import adequacy, waived
    recorded = stop.get("assessment") or {key: value for key, value in adequacy(workspace, hypothesis).items()
                                          if key in {"adequate", "configurations", "seeds_per_configuration", "stochastic", "words"}}
    if recorded.get("adequate"):
        return {**recorded, "basis": "adequate"}
    waiver_id = recorded.get("waiver_id") or (waived(workspace, hypothesis) or {}).get("id")
    if waiver_id:
        return {**recorded, "basis": "waiver", "waiver_id": waiver_id}
    return None


def _configurations(trials):
    """The assessment as run: each distinct configuration of the proposal with the seeds it ran on."""
    seen = {}
    for trial in trials:
        if trial.get("status") in {"failed", "cancelled", "queued"} or trial.get("locked") or trial.get("confirmation_protocol_id"):
            continue
        config = trial.get("algorithm_config") or {}
        item = seen.setdefault(content_hash(config)[:16], {"configuration_hash": content_hash(config)[:16], "algorithm": trial.get("algorithm"),
                                                          "algorithm_config": config, "seeds": []})
        if trial.get("seed", 0) not in item["seeds"]:
            item["seeds"].append(trial.get("seed", 0))
    return [{**item, "seeds": sorted(item["seeds"])} for item in seen.values()]


def _publish_negative(workspace, campaign_id, values, hypothesis, row, *, command_id, actor):
    """A stopped strategy whose stop judged the method (K4): what another campaign of the problem should know before trying it."""
    from optimization_framework.campaigns.assessment import PERFORMANCE
    from optimization_framework.campaigns.hypotheses import stop_of
    stop = stop_of(hypothesis)
    if stop is None:
        raise ValueError("Only a stopped strategy goes to the library as a negative entry")
    outcome = stop["outcome"]
    if outcome not in JUDGEMENTS:
        said = "the stop names no outcome" if outcome in {"researcher_decision", "unspecified"} else f"its stop outcome is {stop['words']}"
        raise ValueError(f"A negative library entry needs a stop that judges the method (configuration unpromising or adequately assessed, "
                         f"deprioritized after an adequate assessment; implementation invalid or assumptions incompatible with their evidence): "
                         f"{said}, which says nothing about the method")
    assessment = None
    if outcome in PERFORMANCE:
        assessment = _assessment_basis(workspace, hypothesis, stop)
        if assessment is None:
            from optimization_framework.campaigns.assessment import adequacy
            missing = "; ".join(adequacy(workspace, hypothesis)["missing"]) or "the assessment was not adequate"
            raise ValueError(f"A stop as {stop['words']} goes to the library only after an adequate assessment or your waiver of the minimums "
                             f"(decision 14): {missing}")
    elif not stop.get("evidence_ids"):
        raise ValueError(f"A stop as {stop['words']} goes to the library only with its evidence: the stop cites no records")
    store = workspace.store
    signature = signature_of(workspace, campaign_id)
    trials = [t for t in store.list("trial", campaign_id) if t.get("hypothesis_id") == values.hypothesis_id]
    record = {"id": "library_" + content_hash(command_id)[:20], "kind": "negative", "origin_campaign_id": campaign_id, "hypothesis_id": values.hypothesis_id,
              "strategy": {key: hypothesis.get(key) for key in ("title", "mechanism", "rationale", "family", "algorithm", "algorithm_config", "implementation_version_id")},
              "signature": {key: signature.get(key) for key in ("problem_id", "evaluator_version", "objective", "representation", "dimensions", "constraint_digest", "instance_digest", "charter_id")},
              "code": code_of(workspace, hypothesis),
              "stop": {key: stop.get(key) for key in ("outcome", "words", "evidence_ids", "reason", "by", "at")},
              "assessment": {**(assessment or {"basis": "not required"}), "configurations_run": _configurations(trials)},
              "evidence": {"best_score": row["best"]["score"], "best_basis": row["best"]["basis"], "interval": None, "worker_seconds": row["worker_seconds"],
                           "trial_ids": row["trial_ids"], "evidence_ids": stop.get("evidence_ids") or []},
              "graph": {"thread_id": None, "round": row.get("round"), "stage": row["stage"], "parent_links": row.get("parent_links")},
              "notes": values.notes, "published_by": actor, "created_at": now()}
    return _write(workspace, hypothesis, record)


def stopped_words(entry):
    """Why and where a negative entry's method was stopped, for the rationale of a strategy applied from it."""
    stop, assessment, signature = entry.get("stop") or {}, entry.get("assessment") or {}, entry.get("signature") or {}
    objective = signature.get("objective") or {}
    where = ", ".join(str(part) for part in (signature.get("problem_id"), " ".join(str(v) for v in (objective.get("name"), objective.get("direction")) if v),
                                              signature.get("representation"), f"{signature['dimensions']} dimensions" if signature.get("dimensions") else None) if part)
    tried = {"adequate": f"after an adequate assessment ({assessment.get('words')})", "waiver": f"on fewer runs than the minimums, with the researcher's waiver ({assessment.get('words')})"}.get(assessment.get("basis"))
    because = f": {stop['reason']}" if stop.get("reason") else ""
    return (f"assessed and stopped as {stop.get('words') or stop.get('outcome')}{because}" + (f", {tried}" if tried else "")
            + f", in campaign {entry['origin_campaign_id']} on {where or 'an unknown problem'}"
            + (f"; evidence {', '.join(stop['evidence_ids'][:5])}" if stop.get("evidence_ids") else ""))


def apply(workspace, campaign_id, values, *, command, actor):
    """A new root strategy in this campaign, inspired by the entry; the campaign's signature is compared and said."""
    entry = workspace.store.get(values.entry_id, "library_entry")
    score, reasons = match(entry["signature"], signature_of(workspace, campaign_id))
    from optimization_framework.contracts.requests import HypothesisInput
    from optimization_framework.campaigns import hypotheses
    strategy = entry["strategy"]
    rationale = (strategy.get("rationale") or "") + f"\n\nApplied from library entry {entry['id']} (campaign {entry['origin_campaign_id']}; best measured {entry['evidence'].get('best_score')}). "
    if kind_of(entry) == "negative":
        rationale += f"It was {stopped_words(entry)}. "
    rationale += f"Fit here: {', '.join(reasons) or 'no shared signature'} (score {score})." + (f"\nResearcher's note: {values.note}" if values.note else "")
    values_in = HypothesisInput(campaign_id=campaign_id, title=values.title or f"{strategy['title']} (from the library)", mechanism=strategy.get("mechanism") or "",
                                rationale=rationale.strip()[:20000],
                                family=strategy.get("family"), algorithm=strategy.get("algorithm") or "", algorithm_config=strategy.get("algorithm_config") or {},
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
    bound = _bound(workspace, campaign_id, entry, record, command=command, actor=actor) if kind_of(entry) != "negative" else {}
    if bound.get("binding"):
        record = workspace.store.get(record["id"], "hypothesis")
    return {"hypothesis_id": record["id"], "hypothesis": record, "entry_id": entry["id"], "match": {"score": score, "reasons": reasons}, **bound}


def register(workspace):
    commands = workspace.commands

    def publish_command(command, actor):
        return publish(workspace, command.campaign_id, PublishInput(**command.payload), command_id=command.id, actor=actor)

    def apply_command(command, actor):
        return apply(workspace, command.campaign_id, ApplyInput(**command.payload), command=command, actor=actor)

    commands.register("library.publish", publish_command, model=PublishInput)
    commands.register("library.apply", apply_command, model=ApplyInput, delegable=True)
