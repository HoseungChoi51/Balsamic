"""Fixtures for the service layer: an app on a temporary workspace, a client, a campaign made through the bus."""
import pytest
from fastapi.testclient import TestClient

from balsamic.app import create_app
from support import QUADRATIC, command

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    return create_app(tmp_path / "workspace", start_workers=False)


@pytest.fixture
def workspace(app):
    return app.state.workspace


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def campaign(client):
    receipt = command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Find a better optimizer", "tasks": [QUADRATIC],
                                                           "compute_budget_seconds": 600, "llm_budget_usd": 1}, 0)
    return receipt["outcome"]["campaign"]
