"""The panel catalog: what an agent may put on a page, as a JSON schema.

A panel is a title, the page it belongs to and a list of components. Components are declarative: text, bound
values, tables of records, number and select fields bound to charter paths or questions, charts of trial curves,
buttons that issue bus commands, links to pages, and sections that group them. No code travels; the workspace's own
React components render every one. Values are resolved on the server at read time (panels/service.resolve), so a
panel never shows a stale number, and every change goes through the charter service or the command bus with a
receipt. The shape follows the component-tree idea of A2UI so a renderer switch stays possible (docs/panels.md).
"""
S = {"type": "string"}
ID = {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,63}$"}
PAGE = {"type": "string", "pattern": "^#(overview|note|hypotheses|experiments|evolution|files|inbox|monitor|library|branches)(/[a-z0-9_-]+)?$"}
NUMBER_PATH = {"type": "string", "pattern": "^(quantities\\.[a-z][a-z0-9_]*\\.(value|expression)|variables\\.[0-9]{1,3}\\.(lower|upper))$"}
MAX_BYTES = 64 * 1024
MAX_COMPONENTS = 60
TABLE_KINDS = {
    "hypothesis": ("id", "title", "short_title", "status", "algorithm", "round", "created_at"),
    "trial": ("id", "status", "algorithm", "hypothesis_id", "wall_seconds", "seed", "created_at"),
    "decision": ("id", "title", "status", "requested_by", "created_at"),
    "study": ("id", "goal", "status", "created_at"),
    "adaptive_race": ("id", "status", "study_id", "started_at"),
    "asset": ("id", "name", "kind", "status", "created_at"),
    "thread": ("id", "title", "status", "kind", "created_at"),
    "task": ("id", "name", "problem_id", "split"),
}
COMPONENT_TYPES = ("markdown", "kv", "table", "number", "select", "chart", "button", "link", "section")

CHARTER_BIND = {"type": "object", "properties": {"charter": S, "path": NUMBER_PATH, "question": ID, "value": S},
                "required": ["charter"], "additionalProperties": False}
COMPONENT = {"$ref": "#/$defs/component"}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
        "page": PAGE,
        "placement": {"enum": ["top", "bottom"]},
        "note": {"type": "string", "maxLength": 2000},
        "components": {"type": "array", "minItems": 1, "maxItems": MAX_COMPONENTS, "items": COMPONENT},
    },
    "required": ["title", "page", "components"],
    "additionalProperties": False,
    "$defs": {
        "component": {"oneOf": [
            {"type": "object", "properties": {"type": {"const": "markdown"}, "id": ID, "text": {"type": "string", "minLength": 1, "maxLength": 20000}},
             "required": ["type", "text"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "kv"}, "id": ID, "title": S, "rows": {"type": "array", "minItems": 1, "maxItems": 40, "items": {
                "type": "object", "properties": {"label": S, "value": {}, "units": S, "bind": CHARTER_BIND, "record": {"type": "object", "properties": {"id": S, "field": S}, "required": ["id", "field"], "additionalProperties": False}},
                "required": ["label"], "additionalProperties": False}}},
             "required": ["type", "rows"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "table"}, "id": ID, "title": S,
                "source": {"type": "object", "properties": {"kind": {"enum": sorted(TABLE_KINDS)}, "fields": {"type": "array", "items": S, "maxItems": 12},
                           "where": {"type": "object", "additionalProperties": {"type": ["string", "number", "boolean", "null"]}}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
                           "required": ["kind"], "additionalProperties": False},
                "columns": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "object", "properties": {"key": S, "label": S}, "required": ["key"], "additionalProperties": False}},
                "rows": {"type": "array", "maxItems": 200, "items": {"type": "object"}}},
             "required": ["type", "columns"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "number"}, "id": ID, "label": {"type": "string", "minLength": 1}, "bind": CHARTER_BIND, "units": S,
                "min": {"type": "number"}, "max": {"type": "number"}, "step": {"type": "number", "exclusiveMinimum": 0}, "help": S},
             "required": ["type", "id", "label", "bind"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "select"}, "id": ID, "label": {"type": "string", "minLength": 1}, "bind": CHARTER_BIND,
                "options": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "properties": {"value": {"type": ["string", "number"]}, "label": S}, "required": ["value"], "additionalProperties": False}}, "help": S},
             "required": ["type", "id", "label", "bind", "options"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "chart"}, "id": ID, "title": S, "source": {"type": "object", "properties": {"trial": S, "hypothesis": S}, "additionalProperties": False},
                "points": {"type": "array", "maxItems": 2000, "items": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}, "required": ["x", "y"], "additionalProperties": False}}},
             "required": ["type"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "button"}, "id": ID, "label": {"type": "string", "minLength": 1}, "command": {"type": "object", "properties": {"operation": S, "payload": {"type": "object"}},
                "required": ["operation"], "additionalProperties": False}, "confirm": S, "tone": {"enum": ["primary", "default"]}},
             "required": ["type", "id", "label", "command"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "link"}, "id": ID, "label": {"type": "string", "minLength": 1}, "page": {"type": "string", "pattern": "^#[a-z]"}},
             "required": ["type", "label", "page"], "additionalProperties": False},
            {"type": "object", "properties": {"type": {"const": "section"}, "id": ID, "title": {"type": "string", "minLength": 1}, "children": {"type": "array", "minItems": 1, "maxItems": 30, "items": COMPONENT}},
             "required": ["type", "title", "children"], "additionalProperties": False},
        ]},
    },
}
# The lead's tool schema: the same shape without $defs recursion (the tool layer validates with the full schema again).
TOOL_INPUT = {"type": "object", "properties": {"title": SCHEMA["properties"]["title"], "page": PAGE, "placement": SCHEMA["properties"]["placement"],
                                                "note": SCHEMA["properties"]["note"], "components": {"type": "array", "minItems": 1, "maxItems": MAX_COMPONENTS, "items": {"type": "object"}},
                                                "panel_id": S}, "required": ["title", "page", "components"], "additionalProperties": False}


def walk(components):
    """Every component, depth first."""
    for component in components:
        yield component
        if component.get("type") == "section":
            yield from walk(component.get("children") or [])
