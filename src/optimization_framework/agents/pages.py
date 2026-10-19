"""The workspace's pages, read from the file the frontend router is built from.

The lead agent links its replies to pages; the frontend puts the current thread in front of the address. Both read
``frontend/src/router/pages.json`` so a page cannot exist on one side only (tests/balsamic/test_pages_json.py).
"""
from functools import lru_cache
import json
from pathlib import Path

PAGES_FILE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "router" / "pages.json"


@lru_cache(maxsize=1)
def catalog():
    return json.loads(PAGES_FILE.read_text())


def pages():
    """(address, title, description) for every rail page, in rail order, then each sub page."""
    rows = []
    for name in catalog()["rail"]:
        page = catalog()["pages"][name]
        rows.append(("#" + name, page["title"], page["description"]))
        for sub, title in (page.get("subs") or {}).items():
            rows.append((f"#{name}/{sub}", f"{page['title']} · {title}", ""))
    return tuple(rows)


def command_pages():
    return {operation: "#" + page for operation, page in catalog()["commands"].items()}


def agent_page(role):
    """The page a page agent is in charge of, as an address."""
    page = catalog()["agents"].get(role)
    return "#" + page if page else None


def canonical(address):
    """An old address (#decisions, #agents/usage, ...) as its current page; unknown ones unchanged."""
    bare = address.lstrip("#").split("?", 1)[0]
    aliases = catalog()["aliases"]
    head, _, rest = bare.partition("/")
    if bare in aliases:
        return "#" + aliases[bare]
    if head in aliases:
        return "#" + aliases[head] + ("/" + rest if rest else "")
    return "#" + bare if bare else "#monitor"


def command_page(record):
    """The page that shows what a command created, for the lead to link."""
    operation = record.get("request", {}).get("operation")
    page = command_pages().get(operation)
    outcome = record.get("outcome")
    if page == "#experiments" and isinstance(outcome, dict) and isinstance(outcome.get("trial_id"), str):
        return f"{page}/{outcome['trial_id']}"
    if page == "#hypotheses" and isinstance(outcome, dict) and isinstance(outcome.get("hypothesis_id"), str):
        return f"{page}/{outcome['hypothesis_id']}"
    return page
