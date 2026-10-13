"""The platform's own cost per evaluation stays within a few candidates, whatever the problem."""
import json

from fastapi.testclient import TestClient

from optimization_framework.api.app import create_app
from optimization_framework.execution import worker
from optimization_framework.execution.worker import read_journal, run
from test_framework_worker import prepare

STEPS = 60
PER_STEP = {"requests.jsonl", "observations.jsonl", "metrics.jsonl", "costs.jsonl"}


def size(record):
    return len(json.dumps(record, separators=(",", ":")))


def test_bytes_written_per_evaluation_stay_within_a_few_candidates(tmp_path, monkeypatch):
    written = {"appended": 0, "progress": [], "archive": 0}
    append, rewrite = worker.append_json, worker.atomic_json
    def counted_append(path, record):
        written["appended"] += size(record) if path.name in PER_STEP else 0
        return append(path, record)
    def counted_rewrite(path, record, *args, **kwargs):
        if path.name == "progress.json":
            written["progress"].append(size(record))
        written["archive"] += path.name == "archive.json"
        return rewrite(path, record, *args, **kwargs)
    monkeypatch.setattr(worker, "append_json", counted_append)
    monkeypatch.setattr(worker, "atomic_json", counted_rewrite)
    # A free evaluator on a large candidate: everything written is the platform's own.
    prepare(tmp_path, algorithm="random", max_steps=STEPS, config={"dimensions": 2000})
    result = run(tmp_path)
    assert result["status"] == "completed" and result["step"] == STEPS
    observations = read_journal(tmp_path / "observations.jsonl")
    candidate = size(observations[0]["candidate"])
    allowance = 3 * candidate + 8192
    assert candidate > 20000
    assert written["appended"] / STEPS <= allowance
    # The record rewritten after every step holds the best candidate, not the archive of ten.
    assert len(written["progress"]) == STEPS + 1 and max(written["progress"][:-1]) <= allowance
    # The archive is rewritten only when an observation entered it.
    entered, best = 0, []
    for observation in observations:
        value = observation["objectives"]["value"]
        if len(best) < 10 or value < max(best):
            entered, best = entered + 1, sorted([*best, value])[:10]
    assert written["archive"] == entered < STEPS
    # Nothing is lost: the archive file is the result's archive, and the result still holds everything.
    assert json.loads((tmp_path / "archive.json").read_text()) == result["archive"]
    assert len(result["archive"]) == 10
    assert json.loads((tmp_path / "progress.json").read_text())["archive"] == result["archive"]


def test_state_is_encoded_once_per_snapshot(tmp_path, monkeypatch):
    import fastapi.encoders
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    calls, encode = [], fastapi.encoders.jsonable_encoder
    def counted(value, *args, **kwargs):
        if isinstance(value, dict) and "workspace_id" in value:   # the whole snapshot, not its parts
            calls.append(1)
        return encode(value, *args, **kwargs)
    monkeypatch.setattr(fastapi.encoders, "jsonable_encoder", counted)
    with TestClient(create_app(tmp_path / "workspace", start_workers=False)) as client:
        created = client.post("/api/campaigns", json={"name": "Polling", "llm_budget_usd": 0, "compute_budget_seconds": 500,
            "validation_reserve_seconds": 30, "tasks": [{"name": "Development", "physics": {"n_cells": 6, "fourier_order": 1}}]})
        assert created.status_code == 201, created.text
        parameters = {"campaign_id": created.json()["id"]}
        calls.clear()
        first = client.get("/api/state", params=parameters)
        assert first.status_code == 200 and first.headers["content-type"] == "application/json" and first.json()["campaign"]["name"] == "Polling"
        assert client.get("/api/state", params=parameters).content == first.content and len(calls) == 1
        # A committed event is never hidden by the cached encoding.
        client.app.state.workspace.store.event(parameters["campaign_id"], "note.recorded", {})
        client.get("/api/state", params=parameters)
        assert len(calls) == 2


def test_a_recorded_design_is_found_without_reading_the_others_whole(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from optimization_framework.evaluation import jobs
    from optimization_framework.execution.metrics import full_row, scalar_rows
    spec = prepare(tmp_path, problem_id="meent_grating", algorithm="random", max_steps=24, config={"n_cells": 160, "fourier_order": 1})
    assert run(tmp_path)["status"] == "completed"
    observations = read_journal(tmp_path / "observations.jsonl")
    rows = list(scalar_rows(tmp_path / "observations.jsonl"))
    # The scalar view drops the designs and nothing else, and a line read whole is the record itself.
    assert [row for _, _, row in rows] == [{**observation, "candidate": []} for observation in observations]
    assert [full_row(tmp_path / "observations.jsonl", offset) for offset, _, _ in rows] == observations
    with (tmp_path / "observations.jsonl").open("ab") as stream:
        stream.write(b'{"id": "torn')   # an unfinished last write is not a record
    assert len(list(scalar_rows(tmp_path / "observations.jsonl"))) == len(observations)
    whole, published = [], []
    monkeypatch.setattr(jobs, "full_row", lambda path, offset: whole.append(offset) or full_row(path, offset))
    workspace = SimpleNamespace(job_dir=lambda identity: tmp_path, assets=SimpleNamespace(publish=lambda asset: published.append(asset) or {"id": asset.id}))
    trial = {**spec, "initial_assets": []}
    chosen = observations[7]
    assert jobs.snapshot_solutions(workspace, trial, [chosen["candidate"]]) == [{"id": published[0].id}]
    assert published[0].payload["observation"] == chosen and published[0].payload["request_prefix_stop"] == len(observations)
    assert len(whole) == 1
    # A candidate that was never observed is still reported as absent after every record was compared.
    absent = [1 - cell for cell in chosen["candidate"]]
    assert absent not in [observation["candidate"] for observation in observations]
    try:
        jobs.snapshot_solutions(workspace, trial, [absent])
    except ValueError as error:
        assert "no successful authoritative observation" in str(error)
    else:
        raise AssertionError("An unobserved candidate was snapshotted")


def test_publishing_an_output_reads_its_dependencies_not_the_catalog(tmp_path, monkeypatch):
    from optimization_framework.assets.catalog import AssetCatalog
    from optimization_framework.contracts.assets import Asset
    from optimization_framework.storage.sqlite import Store
    store = Store(tmp_path)
    catalog = AssetCatalog(store)
    publish = lambda name, *dependencies: catalog.publish(Asset(id=name, campaign_id="current", kind="solution", title=name,
        dependency_ids=list(dependencies), authority="researcher", created_at="test"))
    for index in range(30):
        publish(f"earlier-{index}")
    publish("archive", "earlier-3")
    listed, read, load = [], [], store.get
    monkeypatch.setattr(store, "list", lambda kind, *args: listed.append(kind) or [])
    monkeypatch.setattr(store, "get", lambda identity, *args: read.append(identity) or load(identity, *args))
    publish("solution", "archive")
    # A finished experiment publishes about ten outputs; each must cost its own upstream, however many assets exist.
    assert not listed and set(read) == {"archive", "earlier-3"}
    assert catalog.contributions(["solution"])["asset_ids"] == ["archive", "earlier-3", "solution"]
    try:
        publish("orphan", "never-published")
    except KeyError:
        pass
    else:
        raise AssertionError("An output with an unpublished dependency was accepted")


def test_a_long_binary_design_costs_a_fraction_of_its_list_in_the_journals(tmp_path):
    prepare(tmp_path, problem_id="meent_grating", algorithm="random", max_steps=8, config={"n_cells": 1024, "fourier_order": 1})
    assert run(tmp_path)["step"] == 8
    as_list = size(read_journal(tmp_path / "observations.jsonl")[0]["candidate"])
    # Each evaluation is journaled twice, as intent and as observation: what each of them spends on the design.
    for name in ("requests.jsonl", "observations.jsonl"):
        written = [size(json.loads(line)["candidate"]) for line in (tmp_path / name).read_text().splitlines()]
        assert len(written) == 8 and as_list > 2000 and max(written) < as_list / 8
