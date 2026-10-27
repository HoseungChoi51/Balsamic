"""A charter revision exported as a zipped Python project (roadmap F2), for the researcher's own tools."""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from balsamic.app import create_app
from optimization_framework.problem_charter.scaffold import archive, scaffold
from test_problem_charter import reactor


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    with TestClient(create_app(tmp_path / "workspace", start_workers=False)) as client:
        yield client


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


def test_archive_is_the_scaffold_under_the_project_folder_and_the_same_bytes_every_time():
    filename, data = archive(reactor(), 3, charter_id="c")
    assert filename == "flow-reactor-yield-r3.zip"
    files = unzip(data)
    assert files == {f"flow-reactor-yield/{path}": text for path, text in scaffold(reactor(), 3, charter_id="c").items()}
    assert archive(reactor(), 3, charter_id="c") == (filename, data)
    assert archive(reactor(), 3, name="kiln")[0] == "kiln-r3.zip"
    with pytest.raises(ValueError, match="no objective"):
        archive(reactor(objective=None), 1)


def test_the_export_endpoint_returns_the_project_of_the_asked_revision(client):
    charters = client.app.state.workspace.charters
    record = charters.create(reactor(), source={"kind": "test"})
    charters.edit(record["id"], [{"op": "set", "path": "quantities.temperature_c.value", "value": 90.0}], expected_revision=1)
    for revision in (1, 2):
        response = client.get(f"/api/v1/problem-charters/{record['id']}/revisions/{revision}/export.zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["content-disposition"] == f'attachment; filename="flow-reactor-yield-r{revision}.zip"'
        files = unzip(response.content)
        assert {name.split("/", 1)[0] for name in files} == {"flow-reactor-yield"}
        assert b'name = "flow-reactor-yield"' in files["flow-reactor-yield/pyproject.toml"]
        exported = json.loads(files["flow-reactor-yield/charter.json"])
        assert (exported["charter_id"], exported["revision"]) == (record["id"], revision)
        assert exported["charter"]["quantities"]["temperature_c"]["value"] == charters.revision(record["id"], revision)["charter"]["quantities"]["temperature_c"]["value"]
    first = json.loads(unzip(client.get(f"/api/v1/problem-charters/{record['id']}/revisions/1/export.zip").content)["flow-reactor-yield/charter.json"])
    assert first["charter"]["quantities"]["temperature_c"]["value"] != 90.0


def test_the_export_refuses_a_missing_revision_and_a_charter_with_nothing_to_generate(client):
    charters = client.app.state.workspace.charters
    record = charters.create(reactor(objective=None), source={"kind": "test"})
    assert client.get(f"/api/v1/problem-charters/{record['id']}/revisions/7/export.zip").status_code == 404
    response = client.get(f"/api/v1/problem-charters/{record['id']}/revisions/1/export.zip")
    assert response.status_code == 409
    assert "no objective" in response.json()["detail"]
