"""The page catalog is one file for the router and the lead's links; both sides must agree with the agent roles."""
import json

from optimization_framework.agents import pages
from optimization_framework.agents.models import PAGE_AGENTS
from optimization_framework.agents.tools import COMMAND_PAGES, PAGES


def test_pages_json_is_consistent():
    catalog = json.loads(pages.PAGES_FILE.read_text())
    names = set(catalog["pages"])
    assert set(catalog["rail"]) <= names and "new" in names
    for page in catalog["pages"].values():
        assert page["title"] and "description" in page
    for operation, target in catalog["commands"].items():
        head, _, sub = target.partition("/")
        assert head in names, operation
        assert not sub or sub in (catalog["pages"][head].get("subs") or {}), operation
    for alias, target in catalog["aliases"].items():
        head, _, sub = target.partition("/")
        assert head in names, alias
        assert not sub or sub in (catalog["pages"][head].get("subs") or {}), alias
    assert set(catalog["agents"]) == set(PAGE_AGENTS)
    assert catalog["agents"] == PAGE_AGENTS


def test_the_lead_reads_the_same_catalog():
    addresses = {address for address, _, _ in PAGES}
    assert "#experiments" in addresses and "#hypotheses/implementations" in addresses and "#monitor/resources" in addresses
    assert COMMAND_PAGES["trial.create"] == "#experiments" and COMMAND_PAGES["approval.request"] == "#inbox"
    assert pages.command_page({"request": {"operation": "trial.create"}, "outcome": {"trial_id": "trial_9"}}) == "#experiments/trial_9"
    assert pages.command_page({"request": {"operation": "hypothesis.create"}, "outcome": {"hypothesis_id": "hypothesis_2"}}) == "#hypotheses/hypothesis_2"
    assert pages.agent_page("implementation_lead") == "#hypotheses/implementations"


def test_old_addresses_canonicalize():
    assert pages.canonical("#decisions") == "#inbox"
    assert pages.canonical("#agents/usage") == "#monitor/usage"
    assert pages.canonical("#experiments/trial_1") == "#experiments/trial_1"
    assert pages.canonical("#assets") == "#files/assets"
    assert pages.canonical("") == "#monitor"
