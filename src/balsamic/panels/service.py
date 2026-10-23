"""Panels: validate, store, resolve and act on the declarative pages agents compose (schema.py has the catalog)."""
import json

import jsonschema

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

from .schema import MAX_BYTES, SCHEMA, TABLE_KINDS, walk

KIND = "panel"
CHARTER_KIND = "problem_charter"


def validate(workspace, campaign_id, values):
    """The panel against the catalog, and every binding against what exists in this campaign."""
    if len(json.dumps(values).encode()) > MAX_BYTES:
        raise ValueError(f"A panel is at most {MAX_BYTES // 1024} KiB")
    try:
        jsonschema.validate(values, SCHEMA)
    except jsonschema.ValidationError as error:
        where = "/".join(str(p) for p in error.absolute_path) or "panel"
        raise ValueError(f"{where}: {error.message[:300]}") from None
    from optimization_framework.contracts.commands import Operation
    from typing import get_args
    operations = set(get_args(Operation))
    ids = set()
    for component in walk(values["components"]):
        if component.get("id"):
            if component["id"] in ids:
                raise ValueError(f"Component id {component['id']} is used twice")
            ids.add(component["id"])
        kind = component["type"]
        if kind in {"number", "select"} or (kind == "kv" and any(r.get("bind") for r in component["rows"])):
            binds = [component["bind"]] if kind != "kv" else [r["bind"] for r in component["rows"] if r.get("bind")]
            for bind in binds:
                _check_bind(workspace, campaign_id, bind, kind)
        if kind == "kv":
            for row in component["rows"]:
                if row.get("record"):
                    workspace.store.get_entry(row["record"]["id"])
        if kind == "table" and component.get("source"):
            fields = component["source"].get("fields") or [c["key"] for c in component["columns"]]
            unknown = [f for f in fields if f not in TABLE_KINDS[component["source"]["kind"]]]
            if unknown:
                raise ValueError(f"Table of {component['source']['kind']}: unknown field(s) {', '.join(unknown)}; allowed: {', '.join(TABLE_KINDS[component['source']['kind']])}")
        if kind == "table" and not component.get("source") and component.get("rows") is None:
            raise ValueError("A table needs a source or rows")
        if kind == "chart":
            source = component.get("source") or {}
            if source.get("trial"):
                workspace.store.get(source["trial"], "trial")
            elif source.get("hypothesis"):
                workspace.store.get(source["hypothesis"], "hypothesis")
            elif component.get("points") is None:
                raise ValueError("A chart needs a source (trial or hypothesis) or points")
        if kind == "button":
            operation = component["command"]["operation"]
            if operation not in operations:
                raise ValueError(f"Button {component['id']}: {operation} is not a command operation")
            if operation.startswith(("agent.", "campaign.create", "context.")) and operation != "agent.message":
                raise ValueError(f"Button {component['id']}: {operation} is not a button's to issue")
    return values


def _check_bind(workspace, campaign_id, bind, kind):
    charter = workspace.store.get(bind["charter"], CHARTER_KIND)
    if campaign_id and charter.get("campaign_ids") and campaign_id not in charter["campaign_ids"]:
        raise ValueError(f"Charter {bind['charter']} belongs to another campaign")
    doc = charter["charter"]
    if bind.get("question"):
        if kind != "select":
            raise ValueError("Only a select binds to a question")
        if not any(q["id"] == bind["question"] for q in doc.get("questions", [])):
            raise ValueError(f"No question {bind['question']} on charter {bind['charter']}")
    elif bind.get("path"):
        parts = bind["path"].split(".")
        if parts[0] == "quantities":
            quantity = doc.get("quantities", {}).get(parts[1])
            if quantity is None:
                raise ValueError(f"No quantity {parts[1]} on charter {bind['charter']}")
            if quantity.get("role") == "derived" and parts[2] == "value":
                raise ValueError(f"{parts[1]} is derived; bind its expression or its inputs")
        elif int(parts[1]) >= len(doc.get("variables", [])):
            raise ValueError(f"No variable {parts[1]} on charter {bind['charter']}")
    elif bind.get("value"):
        if bind["value"] not in doc.get("quantities", {}):
            raise ValueError(f"No quantity {bind['value']} on charter {bind['charter']}")
    else:
        raise ValueError("A charter bind names a path, a question or a value")


def create(workspace, campaign_id, values, *, author, agent_id=None, run_id=None, thread_id=None, panel_id=None):
    """Save a panel (or a new revision of one); a panel made in a conversation thread is announced there by one line."""
    workspace.store.get(campaign_id, "campaign")
    validate(workspace, campaign_id, values)
    previous = workspace.store.get(panel_id, KIND) if panel_id else None
    if previous and previous["campaign_id"] != campaign_id:
        raise ValueError("The panel belongs to another campaign")
    identity = previous["id"] if previous else "panel_" + content_hash([campaign_id, run_id or author, values["title"], now()])[:16]
    record = {**(previous or {}), "id": identity, "campaign_id": campaign_id, "title": values["title"], "page": values["page"],
              "placement": values.get("placement", "bottom"), "note": values.get("note", ""), "components": values["components"],
              "author": author, "agent_id": agent_id, "run_id": run_id, "thread_id": thread_id or (previous or {}).get("thread_id"),
              "revision": int((previous or {}).get("revision", 0)) + 1, "status": "active",
              "created_at": (previous or {}).get("created_at") or now(), "updated_at": now()}
    workspace.store.put(KIND, record, "panel.revised" if previous else "panel.created")
    if thread_id and not previous:
        workspace.store.put("message", {"id": "message_panel_" + identity, "campaign_id": campaign_id, "role": "assistant", "origin": "lab_event",
                                        "kind": "panel_link", "panel_id": identity, "thread_id": thread_id, "run_id": run_id,
                                        "content": f"The {author} added a panel to {values['page']}: {values['title']}", "created_at": now()}, "message.created")
    return record


def retire(workspace, panel_id):
    record = workspace.store.get(panel_id, KIND)
    record.update(status="retired", updated_at=now())
    workspace.store.put(KIND, record, "panel.retired")
    return record


def for_page(workspace, campaign_id, page=None):
    """Active panels of a campaign, those of one page when given (a sub page also shows its page's panels)."""
    rows = [p for p in workspace.store.list(KIND, campaign_id) if p.get("status") == "active"]
    if page:
        address = page.lstrip("#")
        head = address.split("/")[0]
        rows = [p for p in rows if p["page"].lstrip("#") in {address, head}]
    return sorted(rows, key=lambda p: p["created_at"])


class Panels:
    """What the core's agents (the formulator) may do with panels, installed as workspace.panels."""
    def __init__(self, workspace):
        self.workspace = workspace

    def create(self, campaign_id, values, **kw):
        return create(self.workspace, campaign_id, values, **kw)

    def campaign_of_charter(self, charter_id):
        """The campaign whose problem note adopted this charter, if any."""
        for note in self.workspace.store.list("problem_note"):
            if note.get("charter_id") == charter_id:
                return note["campaign_id"]
        return None


def register(workspace):
    workspace.panels = Panels(workspace)


# ---- resolution ---------------------------------------------------------------------------------------------

def resolve(workspace, panel):
    """The panel with its data filled in from the records it binds: one read for the page."""
    charters = {}
    data = {}

    def charter_view(charter_id):
        if charter_id not in charters:
            charters[charter_id] = workspace.charters.view(charter_id)
        return charters[charter_id]

    for component in walk(panel["components"]):
        cid = component.get("id")
        kind = component["type"]
        if kind == "number":
            data[cid] = _bound(charter_view, component["bind"])
        elif kind == "select":
            data[cid] = _bound(charter_view, component["bind"])
        elif kind == "kv":
            data[cid] = {"rows": [_kv_row(workspace, charter_view, row) for row in component["rows"]]}
        elif kind == "table" and component.get("source"):
            data[cid] = {"rows": _table_rows(workspace, panel["campaign_id"], component)}
        elif kind == "chart" and component.get("source"):
            data[cid] = {"points": _chart_points(workspace, component["source"])}
    return {**panel, "data": data, "resolved_at": now()}


def _bound(charter_view, bind):
    """A field's value, with whether the charter's formulator listens: while it revises the charter, fields wait."""
    view = charter_view(bind["charter"])
    return {**_bound_value(view, bind), "listening": (view.get("formulator") or {}).get("listening", True)}


def _bound_value(view, bind):
    doc = view["charter"]
    if bind.get("question"):
        question = next((q for q in doc.get("questions", []) if q["id"] == bind["question"]), None)
        return {"value": (question or {}).get("answer"), "revision": view["revision"], "options": (question or {}).get("options") or []}
    if bind.get("value"):
        name = bind["value"]
        quantity = doc["quantities"].get(name) or {}
        return {"value": view["values"].get(name), "units": quantity.get("units"), "revision": view["revision"]}
    parts = bind["path"].split(".")
    if parts[0] == "quantities":
        quantity = doc["quantities"].get(parts[1]) or {}
        return {"value": quantity.get(parts[2]), "units": quantity.get("units"), "origin": quantity.get("origin"), "accepted": quantity.get("accepted"), "revision": view["revision"]}
    variable = doc["variables"][int(parts[1])]
    return {"value": variable.get(parts[2]), "units": variable.get("units"), "name": variable.get("name"), "revision": view["revision"]}


def _kv_row(workspace, charter_view, row):
    if row.get("bind"):
        bound = _bound(charter_view, row["bind"])
        return {"label": row["label"], "value": bound.get("value"), "units": row.get("units") or bound.get("units")}
    if row.get("record"):
        try:
            value = workspace.store.get_entry(row["record"]["id"])["data"].get(row["record"]["field"])
        except (KeyError, AttributeError):
            value = None
        return {"label": row["label"], "value": value if isinstance(value, (str, int, float, bool)) or value is None else str(value)[:200], "units": row.get("units")}
    return {"label": row["label"], "value": row.get("value"), "units": row.get("units")}


def _table_rows(workspace, campaign_id, component):
    source = component["source"]
    allowed = TABLE_KINDS[source["kind"]]
    fields = [f for f in (source.get("fields") or [c["key"] for c in component["columns"]]) if f in allowed]
    where = source.get("where") or {}
    rows = [r for r in workspace.store.list(source["kind"], campaign_id) if all(r.get(k) == v for k, v in where.items())]
    rows.sort(key=lambda r: r.get("created_at") or "")
    return [{f: r.get(f) for f in fields} for r in rows[-int(source.get("limit") or 50):]]


def _chart_points(workspace, source):
    from balsamic.evolution.ledger import curve
    if source.get("trial"):
        return curve(workspace, source["trial"])
    trials = [t for t in workspace.store.list("trial") if t.get("hypothesis_id") == source.get("hypothesis")]
    best = max(trials, key=lambda t: float(((t.get("result") or t.get("progress") or {}).get("best_objective") or float("-inf"))), default=None)
    return curve(workspace, best["id"]) if best else []


# ---- actions ------------------------------------------------------------------------------------------------

def set_value(workspace, panel, component_id, value):
    """The researcher sets a bound field: the charter service applies it with a receipt in the charter's history."""
    component = next((c for c in walk(panel["components"]) if c.get("id") == component_id), None)
    if component is None or component["type"] not in {"number", "select"}:
        raise ValueError("No such field on this panel")
    bind = component["bind"]
    view = workspace.charters.view(bind["charter"])
    if component["type"] == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("A number field takes a number")
        if component.get("min") is not None and value < component["min"]:
            raise ValueError(f"{component['label']} is at least {component['min']}")
        if component.get("max") is not None and value > component["max"]:
            raise ValueError(f"{component['label']} is at most {component['max']}")
    else:
        if value not in {o["value"] for o in component["options"]}:
            raise ValueError(f"{component['label']}: choose one of its options")
    if bind.get("question"):
        workspace.charters.answer(bind["charter"], bind["question"], str(value), expected_revision=view["revision"])
    else:
        workspace.charters.edit(bind["charter"], [{"op": "set", "path": bind["path"], "value": value}], expected_revision=view["revision"],
                                rationale=f"Set {component['label']} on the panel {panel['title']}")
    return resolve(workspace, panel)
