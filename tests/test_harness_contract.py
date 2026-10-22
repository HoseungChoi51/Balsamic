"""Contract tests of what the harness hands each model, checked without a model call (Tier A of evals/lead/README.md).

The prompt-size ratchet: a role's instructions may not grow more than 10% over the size recorded here. When a change
shrinks them, lower the number; raising it is a decision taken with the live evals, not to make this test pass."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "balsamic"))
from support import QUADRATIC, activate_team, command, submitted  # noqa: E402

from optimization_framework.agents.tools import PiTools  # noqa: E402

MAIN = "thread_main_demo"
# Words of the instructions at a7e89b8: the lead's (shared instructions, role lines and the workspace briefing) and a specialist's.
LEAD_WORDS = 2889
SPECIALIST_WORDS = 1993
GROWTH = 1.10


@pytest.fixture
def team(tmp_path, monkeypatch):
    from balsamic.app import create_app
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path / "workspace", start_workers=False)
    with TestClient(app) as client:
        workspace = app.state.workspace
        campaign = command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Find a better optimizer", "tasks": [QUADRATIC],
                                                               "compute_budget_seconds": 600, "llm_budget_usd": 1}, 0)["outcome"]["campaign"]
        lead = activate_team(client, workspace, campaign, monkeypatch)
        receipt = command(client, "agent.message", "demo", {"message": "Hello", "thread_id": MAIN}, campaign["version"], origin={"thread_id": MAIN})
        yield SimpleNamespace(client=client, workspace=workspace, campaign=campaign, lead=lead, run=submitted(workspace, "pi_run_" + receipt["id"]),
                              tools=PiTools(workspace.pi))


def specialist(team, role="methodology_specialist"):
    child = team.tools.call(team.lead["id"], team.run["id"], "delegate_" + role, "delegate",
                            {"role": role, "objective": "Check whether random search suits this task.", "request_key": role})
    return team.workspace.store.get(child["agent_id"], "agent_session"), submitted(team.workspace, child["run_id"])


def words(text):
    return len(text.split())


def test_instructions_do_not_grow_past_the_ratchet(team):
    lead = team.tools.manifest(team.lead["id"], team.run["id"])["instructions"]
    agent, run = specialist(team)
    other = team.tools.manifest(agent["id"], run["id"])["instructions"]
    assert words(lead) <= LEAD_WORDS * GROWTH, f"The lead's instructions grew to {words(lead)} words (ratchet {LEAD_WORDS} + 10%)"
    assert words(other) <= SPECIALIST_WORDS * GROWTH, f"A specialist's instructions grew to {words(other)} words (ratchet {SPECIALIST_WORDS} + 10%)"
