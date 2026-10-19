"""Helpers shared by the service-layer tests: a command through the bus, a problem instance."""
import uuid


QUADRATIC = {"name": "Quadratic", "problem_id": "bounded_continuous", "configuration": {}}


def command(client, operation, campaign_id, payload, expected_revision, *, expect=200, **extra):
    body = {"id": "ui_" + uuid.uuid4().hex, "campaign_id": campaign_id, "operation": operation, "expected_revision": expected_revision, "payload": payload, **extra}
    response = client.post("/api/v1/commands", json=body)
    assert response.status_code == expect, response.text
    return response.json()


