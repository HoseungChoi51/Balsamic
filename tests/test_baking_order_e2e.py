"""The baking order replayed offline (roadmap G1): the whole path from a charter to ranked results, with the scripted harness
standing in for the model. A permutation charter of 8 bakes (durations and due dates as data; minimize total tardiness) is confirmed
and a campaign made from it; the researcher asks for four methods, and the lead's turn records 4 proposals and one compute
plan (the coding workspace and 4 proposals x 2 seeds), which the researcher approves.

Step 4: the lead, woken by the go-ahead, opens the coding workspace, which starts from the library Balsamic generates from the
charter (F3, F4); a fake coding agent fills the objective and one method per proposal under the keys its brief gives, the
library's own tests pass, it commits and submits a `ready` report. Step 5: Balsamic installs it with a fake uv, which makes
the library's entry points visible to the lab as an install would, and the campaign's task adopts its problem (E4).

The assertions on the 8 automatic starts, the methods' outcomes, the ranking and the single comparison wake are added as E5
merges, never against a stand-in for it."""
import importlib
import subprocess
import itertools
import socket
import sys
import time
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "balsamic"))
from balsamic.app import create_app  # noqa: E402
from fake_harness import FakeHarness, serve  # noqa: E402
from optimization_framework.agents.development import DevelopmentWorkspaces, method_keys  # noqa: E402
from optimization_framework.agents.library_install import Installer  # noqa: E402
from optimization_framework.evaluation import registry as problem_registry  # noqa: E402
from optimization_framework.optimizers import plugins as optimizer_plugins  # noqa: E402
from optimization_framework.problem_charter import charter as C  # noqa: E402
from test_development_generated_library import LibraryDriver  # noqa: E402
from test_library_install import PYPROJECT  # noqa: E402
from test_problem_charter_scaffold import pytest_in  # noqa: E402
from support import command  # noqa: E402

MAIN = "thread_main_bakery"
DURATIONS = [30, 45, 20, 60, 35, 25, 50, 40]       # minutes
DUE = [210, 130, 200, 110, 190, 100, 40, 120]      # minutes from the oven's start; earliest due date is 415 late, the best order 290
METHODS = [("Earliest due date", "Sort the bakes by due time: the classic rule for lateness, one pass"),
           ("Adjacent swap search", "From the earliest-due-date order, swap neighbours while the tardiness falls"),
           ("Random restarts", "Swap search from random orders, keeping the best"),
           ("Exact enumeration", "All 8! = 40,320 orders: the optimum, as the reference")]
SEEDS = [0, 1]
PACKAGE = "baking_order"
LIBRARY = "libraries/baking_order"
PLACEHOLDERS = ["EDD", "SWAP", "RESTARTS", "EXACT"]   # in the order of METHODS above

def methods_code(keys):
    """methods.py as the coding agent writes it: each proposal's method under the METHODS key its brief gives (keys: proposal
    id -> key, in the order of the proposals)."""
    text = METHODS_CODE
    for placeholder, (hypothesis_id, key) in zip(PLACEHOLDERS, keys.items()):
        text = text.replace(f'"H_{placeholder}"', f'"{hypothesis_id}"').replace(f'"{placeholder}"', f'"{key}"').replace(f"def {placeholder}(", f"def {key}(")
    return text


# What the fake coding agent writes into the generated library: the objective, and one method per proposal.
OBJECTIVE = '''
def objective(problem, candidate) -> float:
    clock, late = 0, 0
    for bake in problem.unpack(candidate)["bake_order"].astype(int):
        clock += problem.values.minutes[bake]
        late += max(0, clock - problem.values.due[bake])
    return float(late)
'''

METHODS_CODE = '''
import itertools

from .harness import deterministic

METHODS = {"EDD": {"name": "Earliest due date", "description": "Sorted by due time, evaluated once.", "hypothesis_id": "H_EDD"},
           "SWAP": {"name": "Adjacent swap search", "description": "From earliest due date, swap neighbours while it improves.",
                    "hypothesis_id": "H_SWAP"},
           "RESTARTS": {"name": "Random restarts", "description": "Adjacent swap descent from random orders until the cap.",
                        "hypothesis_id": "H_RESTARTS"},
           "EXACT": {"name": "Exact enumeration", "description": "Every order once: the optimum.", "hypothesis_id": "H_EXACT"}}


def _edd(problem):
    return sorted(range(problem.dimensions), key=lambda bake: problem.values.due[bake])


def _descend(order, evaluate):
    best = evaluate(order)
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            trial = order[:i] + [order[i + 1], order[i]] + order[i + 2:]
            value = evaluate(trial)
            if value < best:
                order, best, improved = trial, value, True
    return order


@deterministic
def EDD(problem, evaluate, rng):
    evaluate(_edd(problem))


@deterministic
def SWAP(problem, evaluate, rng):
    _descend(_edd(problem), evaluate)


def RESTARTS(problem, evaluate, rng):
    while True:
        _descend([int(bake) for bake in problem.random_candidate(rng)], evaluate)


@deterministic
def EXACT(problem, evaluate, rng):
    for order in itertools.permutations(range(problem.dimensions)):
        evaluate(list(order))
'''
RUN_SECONDS = 60


def bakery():
    """Choose the order of 8 bakes in one oven: a declared problem whose decision variable is an order."""
    return {
        "title": "Baking order",
        "summary": "Order {n_bakes:.0f} bakes in one oven to minimize their total tardiness.",
        "text": "One oven takes {n_bakes:.0f} bakes, one after another. Each bake has a duration and a due time; a bake that ends after "
                "its due time is late by the difference. Choose the order that minimizes the total lateness.",
        "quantities": {"n_bakes": {"description": "Bakes to schedule", "kind": "integer", "value": 8, "units": "1", "citation": 1},
                       "minutes": {"description": "Duration of each bake, by its index", "kind": "data", "value": DURATIONS, "citation": 1},
                       "due": {"description": "Due time of each bake, by its index, from the oven's start", "kind": "data", "value": DUE,
                               "citation": 1}},
        "variables": [{"name": "bake_order", "description": "The order the bakes go into the oven", "representation": "permutation",
                       "shape": ["n_bakes"], "meaning": "Each entry is the index of a bake in minutes and due"}],
        "constraints": [],
        "objective": {"name": "total_tardiness", "direction": "minimize", "units": "min",
                      "definition": "The sum over bakes of max(0, end time - due time)"},
        "metrics": [],
        "evaluator": {"kind": "declared", "problem_id": "baking_order", "deterministic": True, "configuration": {"minutes": "minutes", "due": "due"},
                      "fidelity": {}, "notes": "Run the bakes in the given order from time 0; sum each bake's lateness past its due time."},
        "instances": [{"name": "Eight bakes", "split": "development"}],
        "citations": [{"id": 1, "source": "documents/bakery.md.txt", "location": "the order sheet"}],
    }


def tardiness(order):
    clock, late = 0, 0
    for bake in order:
        clock += DURATIONS[bake]
        late += max(0, clock - DUE[bake])
    return late


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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
def stack(tmp_path, monkeypatch, client, workspace):
    """The scripted harness on a port, calling the workspace's callback routes as the real one does."""
    token = "b" * 40
    token_file = tmp_path / "pi.token"
    token_file.write_text(token)
    port = free_port()
    monkeypatch.setenv("GRATING_PI_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("GRATING_PI_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    monkeypatch.setenv("GRATING_LLM_ENABLED", "true")

    def gateway(operation, body):
        response = client.post(f"/api/internal/pi/{operation}", json=body, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200, response.text
        return response.json()
    harness = FakeHarness(gateway)
    harness.notify = workspace.pi.notify
    server = serve(harness, port, token)
    yield harness
    server.shutdown()


def settle(workspace, run_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        workspace.on_manager_tick()
        for thread in list(workspace.pi.threads.values()):
            thread.join(timeout=2)
        run = workspace.store.get(run_id, "agent_run")
        if run["status"] in {"completed", "failed"}:
            return run
        time.sleep(0.1)
    raise AssertionError("the turn did not settle: " + workspace.store.get(run_id, "agent_run")["status"])


def lead_turn(workspace, campaign_id):
    """The lead's answer to the researcher's request: 4 proposals and one compute plan naming them, through campaign_command."""
    def script(agent, run, tools):
        tools("campaign_inspect", {})
        proposals = sorted(workspace.store.list("hypothesis", campaign_id), key=lambda h: h["created_at"])
        if proposals:   # the researcher approved the plan: open its coding workspace for the four proposals
            opened = tools("implementation_workspace_create", {"hypothesis_id": proposals[0]["id"], "hypothesis_ids": [h["id"] for h in proposals[1:]],
                  "objective": "Implement the four methods in the generated library", "request_key": "bakery"})
            assert "error" not in opened, opened
            reply = "The go-ahead is in: a coding workspace is implementing the four methods."
            tools("yield_work", {"disposition": "waiting", "report": reply, "summary": "opened the coding workspace", "evidence_ids": []})
            return reply
        [task] = workspace.current_tasks(campaign_id)
        proposals = []
        for index, (title, mechanism) in enumerate(METHODS):
            receipt = tools("campaign_command", {"operation": "hypothesis.create", "request_key": f"proposal_{index}", "payload": {
                "title": title, "mechanism": mechanism, "rationale": "The researcher asked for it", "algorithm": "custom",
                "algorithm_config": {"design_note": mechanism}}})
            proposals.append(receipt["outcome"]["hypothesis_id"])
        runs = [{"task_id": task["id"], "hypothesis_id": h, "seeds": SEEDS, "wall_seconds": RUN_SECONDS} for h in proposals]
        tools("campaign_command", {"operation": "approval.request", "request_key": "plan", "payload": {
            "kind": "compute", "plan": "Implement the four methods in one coding workspace, then run each on 2 seeds",
            "rationale": "Compare the four orders at matched cost", "wall_seconds": 1800,
            "worker_seconds": 900 + len(runs) * len(SEEDS) * RUN_SECONDS, "coding_workspaces": 1, "hypothesis_ids": proposals,
            "meanwhile": "Read the charter's data", "runs": runs}})
        reply = "I recorded four proposals and asked for one go-ahead covering the coding workspace and the 8 runs."
        tools("yield_work", {"disposition": "complete", "report": reply, "summary": "proposed and asked", "evidence_ids": []})
        return reply
    return script


def lead_runs(workspace, campaign_id):
    lead_id = workspace.pi.configuration(campaign_id)["lead_id"]
    return sorted((run for run in workspace.store.list("agent_run", campaign_id) if run["agent_id"] == lead_id), key=lambda run: run["created_at"])


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fake_uv(monkeypatch, root):
    """uv as the installer runs it: the dry run changes no other package, and the sync makes the library's two entry points
    (its methods and its problem) visible to the lab, as installing it into the environment would."""
    def runner(args, cwd, timeout=600):
        if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
            entries = tomllib.loads((root / LIBRARY / "pyproject.toml").read_text())["project"]["entry-points"]
            monkeypatch.syspath_prepend(str(root / LIBRARY))
            installed = optimizer_plugins.installed
            monkeypatch.setattr(installed, "_entries", {**installed.entries(), **entries["optimization_framework.optimizers"]})
            monkeypatch.setattr(installed, "_owners", None)
            for name, value in entries["optimization_framework.problems"].items():
                monkeypatch.setitem(problem_registry.problems._loaders, name, lambda value=value: problem_registry._factory(value))
                monkeypatch.delitem(problem_registry.problems._adapters, name, raising=False)
        return 0, " Would make no changes\n" if "--dry-run" in args else "ok"
    return runner


@pytest.fixture
def forget_library():
    yield
    for name in [name for name in sys.modules if name == PACKAGE or name.startswith(PACKAGE + ".")]:
        sys.modules.pop(name)


def test_the_baking_order_goes_from_a_charter_to_an_installed_library_the_campaign_adopts(client, workspace, stack, tmp_path, monkeypatch,
                                                                                            forget_library):
    # 1. The permutation charter, confirmed by the researcher, and a campaign made from it.
    rows = C.findings(bakery())
    assert not [row for row in rows if row["severity"] == "blocking"], rows
    assert tardiness(sorted(range(8), key=lambda b: DUE[b])) > min(
        tardiness(order) for order in itertools.permutations(range(8))), "earliest due date is not optimal here"
    record = workspace.charters.create(bakery(), source={"kind": "test", "id": "bakery", "name": "Bakery"})
    response = client.post(f"/api/v1/problem-charters/{record['id']}/confirm", json={"expected_revision": record["revision"]})
    assert response.status_code == 200, response.text
    confirmed = response.json()
    receipt = command(client, "campaign.create", "bakery", {"name": "Baking order", "research_question": "Which order of bakes is least late?",
        "charter": confirmed["charter"], "compute_budget_seconds": 7200, "validation_reserve_seconds": 0, "llm_budget_usd": 1}, 0)
    campaign = receipt["outcome"]["campaign"]
    cid = campaign["id"]
    [task] = workspace.current_tasks(cid)
    schema = task["evaluator_manifest"]["candidate_schema"]
    assert (schema["representation"], schema["dimensions"]) == ("permutation", 8)
    assert task["evaluator_manifest"]["primary_objective"]["direction"] == "minimize"
    assert workspace.charters.get(record["id"])["campaign_ids"] == [cid]

    # 2. The lead starts; the researcher's one message gets a turn that records the 4 proposals and the plan.
    version = lambda: workspace.store.get(cid, "campaign")["version"]
    command(client, "agent.activate", cid, {}, version())
    monkeypatch.setenv("GRATING_DEVELOPMENT_ENABLED", "true")
    driver = LibraryDriver(tmp_path / "development")
    development = DevelopmentWorkspaces(workspace.pi, driver=driver)
    workspace.pi.development = development
    stack.script = lead_turn(workspace, cid)
    ask = command(client, "agent.message", cid, {"message": "Compare four ways to order the bakes: earliest due date, an adjacent swap "
        "search, random restarts and exact enumeration. Two seeds each.", "thread_id": MAIN}, version(), origin={"thread_id": MAIN})
    run = settle(workspace, "pi_run_" + ask["id"])
    assert run["status"] == "completed", run.get("error")
    proposals = sorted(workspace.store.list("hypothesis", cid), key=lambda h: h["created_at"])
    assert [h["title"] for h in proposals] == [title for title, _ in METHODS]
    assert all(h["requested_by"]["message_id"] == "message_" + ask["id"] for h in proposals), "asked for by the researcher"

    # 3. One compute plan, the workspace and 4 x 2 runs, approved by the researcher's one decision.
    [decision] = [d for d in workspace.store.list("decision", cid) if d.get("status") == "pending"]
    assert [o["label"] for o in decision["options"]] == ["Start now", "Not now"]
    command(client, "decision.resolve", cid, {"decision_id": decision["id"], "choice": "0", "comment": "", "expected_resolution_revision": 0},
            version())
    [consent] = workspace.store.list("compute_consent", cid)
    assert sorted(consent["hypothesis_ids"]) == sorted(h["id"] for h in proposals)
    planned = [(r["hypothesis_id"], seed) for r in consent["runs"] for seed in r["seeds"]]
    assert len(planned) == 8 and len(set(planned)) == 8
    assert consent["request_root"]["message_id"] == "message_" + ask["id"]
    assert workspace.store.list("trial", cid) == [], "nothing runs before the methods exist"

    # The researcher acted three times: the charter's confirmation, one message and one decision.
    researcher = [r["request"]["operation"] for r in workspace.store.list("work_command", cid) if r.get("actor") == "researcher"]
    assert [op for op in researcher if op not in {"campaign.create", "agent.activate"}] == ["agent.message", "decision.resolve"]
    assert len(workspace.charters.get(record["id"])["confirmed"]) == 1


    # 4. The go-ahead wakes the lead, which opens the coding workspace; it starts from the library generated from the charter.
    first = run["id"]
    deadline = time.time() + 15
    while not [r for r in lead_runs(workspace, cid) if r["id"] != first and r["status"] in {"completed", "failed"}] and time.time() < deadline:
        workspace.on_manager_tick()
        for thread in list(workspace.pi.threads.values()):
            thread.join(timeout=2)
        time.sleep(0.1)
    [answer] = [r for r in lead_runs(workspace, cid) if r["id"] != first]
    assert answer["status"] == "completed", answer.get("error")
    [record] = workspace.store.list("development_workspace", cid)
    assert record["hypothesis_ids"] == [h["id"] for h in proposals]
    development.sync(cid)
    record = development.get(cid, record["id"])
    assert record["library"]["revision"] == confirmed["charter"]["revision"] and record["library"]["package"] == PACKAGE
    repo = driver.repo(record)
    brief = (driver.root(record) / "brief.md").read_text()
    keys = method_keys(proposals)
    for proposal in proposals:
        assert f'its METHODS key: `{keys[proposal["id"]]}` with `"hypothesis_id": "{proposal["id"]}"`' in brief
    # The fake coding agent fills the two files it writes, runs the library's tests, commits and submits a ready report.
    (repo / LIBRARY / PACKAGE / "objective.py").write_text(OBJECTIVE)
    (repo / LIBRARY / PACKAGE / "methods.py").write_text(methods_code(keys))
    result = pytest_in(repo / LIBRARY, "-rs")
    assert result.returncode == 0, result.stdout + result.stderr   # the contract with Balsamic among them
    git("init", "-q", cwd=repo)
    git("add", ".", cwd=repo)
    git("-c", "user.name=coder", "-c", "user.email=coder@lab", "commit", "-q", "-m", "The four orders", cwd=repo)
    store = driver.root(record) / "work" / "git"
    git("clone", "-q", "--bare", str(repo), str(store), cwd=tmp_path)
    files = sorted(str(path.relative_to(repo)) for path in (repo / LIBRARY).rglob("*") if path.is_file() and "__pycache__" not in path.parts
                   and ".pytest_cache" not in path.parts)
    report = {"verdict": "ready", "summary": "Four methods; the library's tests pass", "limitations": [], "next_actions": [],
              "tests": {"passed": 1, "failed": 0, "skipped": 0, "command": f"uv run pytest {LIBRARY}"},
              "methods": [{"method_id": keys[h["id"]], "hypothesis_id": h["id"], "state": "implemented", "conformance": "passed"} for h in proposals]}
    submission = workspace.store.put("development_submission", {"id": "development_submission_bakery", "campaign_id": cid,
        "workspace_id": record["id"], "hypothesis_id": record["hypothesis_id"], "commit": git("rev-parse", "HEAD", cwd=repo),
        "status": "submitted", "report": report, "manifest": {"files": files},
        "package": {"files": [{"path": path, "content": (repo / path).read_text()} for path in files]},
        "created_at": "2026-10-27T13:30:00+00:00"})

    # 5. Balsamic installs it by itself (a fake uv), and the campaign's task adopts the problem the library provides.
    lab = tmp_path / "lab"
    (lab / "libraries").mkdir(parents=True)
    (lab / "pyproject.toml").write_text(PYPROJECT)
    (lab / "uv.lock").write_text("lock v1\n")
    installer = Installer(workspace, development, lab, runner=fake_uv(monkeypatch, lab), uv="uv", providers=lambda group: {})
    install = installer.automatic(cid, record["id"], submission, background=False)
    assert install["status"] == "installed", install
    assert install["actor"] == "balsamic" and install["problems_added"] == ["baking_order"]
    assert sorted(install["methods_added"]) == sorted(keys.values()) and install.get("changed_generated_files", []) == []
    adopted = workspace.adopt_library_problem(cid, install["id"], authority="balsamic")   # E5 makes this step Balsamic's own
    [task] = workspace.current_tasks(cid)
    assert task["provided_by"]["install_id"] == install["id"] and task["provided_by"]["commit"] == submission["commit"]
    assert task["problem_id"] == "baking_order" and not task.get("evaluator_requirement_id") and adopted["adopted"]
    instance = problem_registry.problems.resolve("baking_order", task["configuration"])
    assert instance.candidate_schema.representation == "permutation"
    assert problem_registry.problems.evaluator(instance).evaluate(sorted(range(8), key=lambda b: DUE[b])).objectives == {"total_tardiness": 415.0}
    # The library's own comparison ranks exact enumeration best: the optimum, 290 min, against earliest due date's 415.
    compare = importlib.import_module(f"{PACKAGE}.compare")
    rows = compare.compare(seeds=len(SEEDS), evaluations=50_000)
    best = {row["method"]: row["best"] for row in rows}
    edd, exact = keys[proposals[0]["id"]], keys[proposals[3]["id"]]
    assert best[edd] == 415 and best[exact] == 290 == min(best.values())
