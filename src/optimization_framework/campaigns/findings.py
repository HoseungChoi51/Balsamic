"""Findings remain scoped claims with provenance, never unqualified memory."""
from optimization_framework.analysis.claims import numbers as numbers_in
from optimization_framework.contracts.assets import Asset
from optimization_framework.contracts.commands import FindingInput
from optimization_framework.storage.sqlite import now

MEASUREMENT_KINDS = ("runtime_profile", "evaluator_equivalence", "fixed_mask_job", "fixed_mask_report", "agent_artifact")
# What an evidence finding must cite one of: a record of something measured. A proposal, a review, a source or a
# reply is not one; of the agents' saved records only an analysis is.
MEASURED = {"trial", "reproduction_comparison", "confirmation_report", "validation_result", "evaluator_evidence",
    *(kind for kind in MEASUREMENT_KINDS if kind != "agent_artifact")}
MEASURED_ASSETS = {"validation_evidence", "solution", "solution_archive", "dataset", "fields", "learner_diagnostics"}
# What a decision finding must cite one of: the record of a choice. The stops (V1) and mandates (Phase 3) join it.
DECISIONS = {"decision", "finalist_selection", "reuse_decision", "waiver", "budget_amendment", "campaign_budget_amendment",
    "implementation_grant", "execution_grant", "study_activation", "nomination"}
FINDING_KINDS = {"finding", "counterevidence"}


def measured(entry):
    data = entry["data"]
    return (entry["kind"] in MEASURED or (entry["kind"] == "agent_artifact" and data.get("kind") == "analysis")
        or (entry["kind"] == "asset" and data.get("kind") in MEASURED_ASSETS))


def links(finding):
    """A finding's typed links; one recorded before them has its counterevidence_for as contradicts links."""
    if "links" in finding:
        return finding["links"]
    return [{"id": identity, "relation": "contradicts"} for identity in finding.get("counterevidence_for", [])]


def normalized(finding):
    return {**finding, "statement": finding.get("statement") or "unspecified", "links": links(finding)}


def visible_evidence(workspace, campaign_id):
    """The ids an agent may cite as evidence: the campaign's visible records, its measurements and declared references."""
    store = workspace.store
    campaign = store.get(campaign_id, "campaign")
    visible = {item["id"] for _, item in workspace.memory._records(campaign_id)}
    # Measurements of the evaluator and the agents' saved analyses are this campaign's evidence too:
    # what a campaign learned about speed or numerical agreement is citable like an experiment.
    for kind in MEASUREMENT_KINDS:
        visible.update(item["id"] for item in store.list(kind, campaign_id))
    visible.update(item["asset_id"] for item in workspace.assets.manager_references(campaign_id, campaign.get("active_study_id")) if "payload" in item)
    return visible


def record(workspace, command, actor):
    store = workspace.store
    values = FindingInput(**command.payload)
    if actor == "manager" and values.interpretation == "researcher_endorsed":
        raise ValueError("Only the researcher can endorse a conclusion")
    if actor != "researcher" and values.statement is None:
        raise ValueError("Say what the finding states: statement promise (why something may work, not measured), "
            "evidence (what was measured) or decision (what was chosen, and why)")
    typed = [{"id": link.id, "relation": link.relation} for link in values.links]
    typed += [{"id": identity, "relation": "contradicts"} for identity in values.counterevidence_for
              if {"id": identity, "relation": "contradicts"} not in typed]
    linked = list(dict.fromkeys(link["id"] for link in typed))
    visible = visible_evidence(workspace, command.campaign_id)
    if set([*values.source_ids, *linked]) - visible:
        raise ValueError("Finding cites evidence outside the visible context; declare historical reference access first")
    sources = [store.get(identity) for identity in dict.fromkeys([*values.source_ids, *values.counterevidence_for])]
    cited = [store.get_entry(identity) for identity in values.source_ids]
    if values.statement == "evidence" and not any(measured(entry) for entry in cited):
        raise ValueError("An evidence finding cites at least one measurement: an experiment, a comparison, a confirmation, "
            "a validation result, a runtime profile or a saved analysis. A proposal, a review or a source is not one; "
            "record what they argue as a promise")
    if values.statement == "decision" and not any(entry["kind"] in DECISIONS for entry in cited):
        raise ValueError("A decision finding cites the record of the decision: an approval, a finalist selection, "
            "a waiver, a reuse decision or a nomination")
    for identity in values.study_ids:
        if store.get(identity, "study")["campaign_id"] != command.campaign_id:
            raise ValueError("Finding scope belongs to another campaign's study")
    for identity in linked:
        entry = store.get_entry(identity)
        if entry["kind"] not in {"asset", "manager_note"} or entry["data"].get("kind") not in FINDING_KINDS:
            raise ValueError("Counterevidence must qualify a recorded finding" if identity in values.counterevidence_for
                else "A link names an earlier finding of this campaign")
    finding = {"id": "finding_" + command.id, "campaign_id": command.campaign_id,
        "kind": "counterevidence" if values.interpretation == "counterevidence" else "finding",
        **values.model_dump(exclude={"schema_version", "publish", "links", "statement"}),
        "statement": values.statement or "unspecified", "links": typed, "author": actor, "created_at": now()}
    unsourced = [] if actor == "researcher" else unverified_numbers(store, command, values, linked)
    if unsourced:
        finding["unverified_numbers"] = unsourced
    if values.publish:
        finding["asset_id"] = "asset_" + finding["id"]
    store.put_immutable("manager_note", finding, "finding.recorded")
    if values.publish:
        dependencies, exposed = set(), set()
        evidence_covered = True
        for source in sources:
            entry = store.get_entry(source["id"])
            candidates = ([source["id"]] if entry["kind"] == "asset" else source.get("latest_output_asset_ids", [])
                + source.get("research_cost_asset_ids", []) + ([source["asset_id"]] if source.get("asset_id") else []))
            evidence_covered &= bool(candidates)
            dependencies.update(candidates)
            # An experiment carries its problem; a measurement record names it by digest only.
            if isinstance(source.get("problem"), dict):
                exposed.add(source["problem"]["scientific_identity"])
        if actor == "manager" and command.id.startswith("action_"):
            try:
                action = store.get(command.id.removeprefix("action_"), "action")
                run = store.get(action["research_run_id"], "research_run")
            except KeyError:
                evidence_covered = False
            else:
                from optimization_framework.assets.service_costs import capture_research
                dependencies.add(capture_research(workspace, run)["id"])
        assets = [store.get(identity, "asset") for identity in sorted(dependencies)]
        for asset in assets:
            workspace.assets.check_export_exposure(asset)
            exposed.update(asset["exposed_instance_ids"])
        workspace.assets.publish(Asset(id=finding["asset_id"], campaign_id=command.campaign_id, kind="finding",
            title=values.content[:160], payload={"finding_id": finding["id"], "content": values.content,
                "classification": values.interpretation, "statement": finding["statement"], "links": typed, "evidence_ids": values.source_ids,
                "problem_scope": values.problem_scope, "study_ids": values.study_ids,
                "limitations": values.limitations, "counterevidence_for": values.counterevidence_for,
                **({"unverified_numbers": unsourced} if unsourced else {})},
            applicability={"problem_scope": values.problem_scope, "study_ids": values.study_ids, "limitations": values.limitations},
            producer_id=finding["id"], dependency_ids=sorted(dependencies), exposed_instance_ids=sorted(exposed),
            exposure_status="known" if assets and all(row["exposure_status"] == "known" for row in assets) else "unknown",
            cost_provenance="complete" if evidence_covered and all(row["cost_provenance"] == "complete" for row in assets) else "partial",
            authority=actor, created_at=finding["created_at"]))
    return {"finding_id": finding["id"], **({"asset_id": finding["asset_id"]} if values.publish else {}),
            **({"unverified_numbers": unsourced, "note": "No cited source or receipt of this request holds these numbers; "
                "they are shown as unverified. Cite the record they come from, or derive them with compute."} if unsourced else {})}


def unverified_numbers(store, command, values, linked):
    """The numbers of an agent's finding that neither its sources (and the findings it links to) nor the recording request's
    tool receipts hold (K2). Saved on the finding and shown as a badge; nothing is refused."""
    from optimization_framework.analysis.claims import Evidence, receipts, request_runs, unverified
    if not numbers_in(values.content):
        return []
    evidence = [store.get(identity) for identity in dict.fromkeys([*values.source_ids, *values.counterevidence_for, *linked])]
    run_id = command.origin.run_id if command.origin else None
    try:
        run = store.get(run_id, "agent_run") if run_id else None
    except KeyError:
        run = None
    if run:
        runs = request_runs(store, run)
        evidence += [row.get("input") for row in runs] + receipts(store, [row["id"] for row in runs])
    return unverified(values.content, Evidence(evidence))


def view(store, campaign_id):
    """The campaign's findings as Files shows them: current ones first, superseded ones apart (still readable by id).

    Support is counted by distinct measurement: each finding lists the measurements it cites and those of the findings
    that support it, two levels deep. A supporter that cites no source the finding and its earlier supporters did not
    already cite restates them: three agents restating one trial are one measurement, not three supports."""
    rows = sorted((normalized(row) for row in store.list("manager_note", campaign_id) if row.get("kind") in FINDING_KINDS),
                  key=lambda row: row["created_at"])
    by_id = {row["id"]: row for row in rows}
    supporters, superseded_by = {}, {}
    for row in rows:
        for link in row["links"]:
            if link["relation"] == "supports":
                supporters.setdefault(link["id"], []).append(row["id"])
            elif link["relation"] == "supersedes":
                superseded_by.setdefault(link["id"], []).append(row["id"])
    kinds = {}

    def measurements(row):
        found = []
        for identity in row["source_ids"]:
            if identity not in kinds:
                try:
                    kinds[identity] = measured(store.get_entry(identity))
                except KeyError:
                    kinds[identity] = False
            if kinds[identity]:
                found.append(identity)
        return found

    result = {"findings": [], "superseded_findings": []}
    for row in rows:
        seen, distinct, chain = set(row["source_ids"]), list(measurements(row)), []
        queue = [(identity, 1) for identity in supporters.get(row["id"], [])]
        while queue:
            identity, depth = queue.pop(0)
            if identity == row["id"] or any(item["id"] == identity for item in chain):
                continue
            supporter = by_id[identity]
            adds = [source for source in supporter["source_ids"] if source not in seen]
            seen.update(supporter["source_ids"])
            distinct.extend(item for item in measurements(supporter) if item not in distinct)
            chain.append({"id": identity, "depth": depth, "statement": supporter["statement"], "restates": not adds})
            if depth < 2:
                queue.extend((item, depth + 1) for item in supporters.get(identity, []))
        entry = {**row, "measurement_ids": measurements(row), "support": {"measurement_ids": distinct, "supporters": chain},
                 "superseded_by": superseded_by.get(row["id"], [])}
        result["superseded_findings" if entry["superseded_by"] else "findings"].append(entry)
    # A supporting finding is marked by what it restates: the findings it supports without adding a source.
    restated = {}
    for entry in result["findings"] + result["superseded_findings"]:
        for item in entry["support"]["supporters"]:
            if item["restates"] and item["depth"] == 1:
                restated.setdefault(item["id"], []).append(entry["id"])
    for entry in result["findings"] + result["superseded_findings"]:
        entry["restates"] = restated.get(entry["id"], [])
    return result
