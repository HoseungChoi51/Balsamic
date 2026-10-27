"""The baking order replayed offline (roadmap G1): the whole path from a charter to ranked results, with the scripted harness
standing in for the model. A permutation charter of 8 bakes (durations and due dates as data; minimize total tardiness) is confirmed
and a campaign made from it; the researcher asks for four methods, and the lead's turn records 4 proposals and one compute
plan (the coding workspace and 4 proposals x 2 seeds), which the researcher approves.

Step 4: the lead, woken by the go-ahead, opens the coding workspace, which starts from the library Balsamic generates from the
charter (F3, F4); a fake coding agent fills the objective and one method per proposal under the keys its brief gives, the
library's own tests pass, it commits and submits a `ready` report. Step 5: Balsamic installs it with a fake uv, an editable
install into a site directory of this test, and by itself adopts the problem (E4, E5), binds the 4 proposals (B4) and starts
the 8 approved runs (B5). The runs execute on the lab's experiment workers; when all have ended Balsamic wakes the lead
once, and the lead's comparison ranks exact enumeration best."""
import importlib
import itertools
import os
import re
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "balsamic"))
from balsamic.app import create_app  # noqa: E402
from fake_harness import FakeHarness, serve  # noqa: E402
from optimization_framework import installed as installed_packages  # noqa: E402
from optimization_framework.agents.development import DevelopmentWorkspaces  # noqa: E402
from optimization_framework.agents.library_install import Installer  # noqa: E402
from optimization_framework.evaluation import preflight, registry as problem_registry  # noqa: E402
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
           "EXACT": {"name": "Exact enumeration", "description": "Scores every order with the objective, evaluates the best: the optimum.", "hypothesis_id": "H_EXACT"}}


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
    from .objective import objective   # white-box: all 8! orders scored here, the best one evaluated
    evaluate(list(min(itertools.permutations(range(problem.dimensions)), key=lambda order: objective(problem, list(order)))))
'''
RUN_SECONDS = 60
EVALUATIONS = [10, 2_000, 2_000, 10]   # each proposal's cap: one order, a descent, restarts, the best of all 8! orders


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
    app = create_app(tmp_path / "workspace", start_workers=False)
    yield app
    app.state.workspace.close()   # the replay starts the experiment workers itself


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


def lead_turn(workspace, campaign_id, comparisons):
    """The lead's turns: its answer to the researcher's request (4 proposals and one compute plan naming them, through
    campaign_command), then to the go-ahead (it opens the coding workspace), then to Balsamic's notice that every approved run
    ended (it writes the comparison, kept in comparisons)."""
    def script(agent, run, tools):
        tools("campaign_inspect", {})
        proposals = sorted(workspace.store.list("hypothesis", campaign_id), key=lambda h: h["created_at"])
        if "Write the comparison (comparison.report)" in run["text"]:
            trials = [t["id"] for t in workspace.store.list("trial", campaign_id)]
            comparisons.append(tools("campaign_command", {"operation": "comparison.report", "request_key": "comparison",
                                                          "payload": {"trial_ids": trials}}))
            reply = "All 8 runs ended; the comparison ranks the four orders."
            tools("yield_work", {"disposition": "complete", "report": reply, "summary": "compared", "evidence_ids": []})
            return reply
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
        runs = [{"task_id": task["id"], "hypothesis_id": h, "seeds": SEEDS, "wall_seconds": RUN_SECONDS, "max_evaluations": cap}
                for h, cap in zip(proposals, EVALUATIONS)]
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


def fake_uv(monkeypatch, root, site_dir):
    """uv as the installer runs it: the dry run changes no other package, and the sync installs the library as uv makes an
    editable install, its metadata (both entry points) in a site directory and a .pth naming its source directory."""
    def runner(args, cwd, timeout=600):
        if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
            project = tomllib.loads((root / LIBRARY / "pyproject.toml").read_text())["project"]
            info = site_dir / f"{PACKAGE}-{project['version']}.dist-info"
            info.mkdir()
            (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {project['name']}\nVersion: {project['version']}\n")
            (info / "entry_points.txt").write_text("".join(f"[{group}]\n" + "".join(f"{name} = {value}\n" for name, value in entries.items())
                                                          for group, entries in project["entry-points"].items()))
            (site_dir / f"_{PACKAGE}.pth").write_text(str(root / LIBRARY) + "\n")
            monkeypatch.setattr(optimizer_plugins.installed, "_checked", 0.0)   # the sync took longer than the plug-ins' recheck
        return 0, " Would make no changes\n" if "--dry-run" in args else "ok"
    return runner


@pytest.fixture
def site_dir(tmp_path, monkeypatch):
    """The environment's site directory, empty of the library until the fake uv installs it; afterwards the lab forgets it."""
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    monkeypatch.setattr(sys, "path", [str(site_dir), *sys.path])
    monkeypatch.setattr(installed_packages.site, "getsitepackages", lambda: [str(site_dir)])
    monkeypatch.setattr(installed_packages.site, "getusersitepackages", lambda: str(tmp_path / "no-user-site"))
    # The evaluator's preflight builds it in a child of this interpreter, which reads the real site directory: it is given
    # this one too, with the directories its .pth files name, as the environment's own site directory would give them.
    def run(args, **options):
        named = [line for pth in site_dir.glob("*.pth") for line in pth.read_text().split()]
        env = {**options["env"], "PYTHONPATH": os.pathsep.join([options["env"]["PYTHONPATH"], str(site_dir), *named])}
        return subprocess.run(args, **{**options, "env": env})
    monkeypatch.setattr(preflight, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))
    yield site_dir
    monkeypatch.undo()
    for name in [name for name in sys.modules if name == PACKAGE or name.startswith(PACKAGE + ".")]:
        sys.modules.pop(name)
    importlib.invalidate_caches()
    problem_registry.problems._sync(installed_packages.snapshot(problem_registry.GROUP))
    optimizer_plugins.installed._owners = None


def test_the_baking_order_goes_from_a_charter_to_ranked_results(client, workspace, stack, tmp_path, monkeypatch, site_dir):
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
    comparisons = []
    stack.script = lead_turn(workspace, cid, comparisons)
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
    # The brief gives each proposal its METHODS key (made from its short title, which the titling may still be writing).
    keys = {h["id"]: re.search(rf'\(`{h["id"]}`\); its METHODS key: `(\w+)` with `"hypothesis_id": "{h["id"]}"`', brief).group(1)
            for h in proposals}
    assert len(set(keys.values())) == 4
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
    installer = Installer(workspace, development, lab, runner=fake_uv(monkeypatch, lab, site_dir), uv="uv", providers=lambda group: {})
    install = installer.automatic(cid, record["id"], submission, background=False)
    assert install["status"] == "installed", install
    assert install["actor"] == "balsamic" and install["problems_added"] == ["baking_order"]
    assert sorted(install["methods_added"]) == sorted(keys.values()) and install.get("changed_generated_files", []) == []
    # The problem is picked up: the declared task adopts the library's problem, by Balsamic, first after the install (E5).
    [task] = workspace.current_tasks(cid)
    assert [row["new_task_id"] for row in install["adopted"]] == [task["id"]]
    assert task["provided_by"]["install_id"] == install["id"] and task["provided_by"]["commit"] == submission["commit"]
    assert task["problem_id"] == "baking_order" and not task.get("evaluator_requirement_id")
    # Then the 4 proposals are bound by Balsamic, and exactly the 8 planned runs start under the one consent, on the new task.
    assert sorted(row["hypothesis_id"] for row in install["bindings"]) == sorted(h["id"] for h in proposals)
    assert all(row["task_id"] == task["id"] for row in install["bindings"]) and install["skipped"] == []
    for row in install["bindings"]:
        assert workspace.store.get(row["command_id"], "work_command")["actor"] == "balsamic"
    launched = install["launched"]
    assert sorted((row["hypothesis_id"], row["seed"]) for row in launched) == sorted(planned), install.get("launch_error")
    for row in launched:
        receipt = workspace.store.get(row["command_id"], "work_command")
        assert receipt["actor"] == "balsamic" and receipt["origin"]["consent_id"] == consent["id"]
        assert workspace.store.get(row["trial_id"], "trial")["task_id"] == task["id"]
    assert len(workspace.store.list("trial", cid)) == 8

    # The runs execute (the lab's experiment workers start now); earliest due date and exact enumeration end by themselves.
    workspace.start()
    deadline = time.time() + 240
    while time.time() < deadline and any(t["status"] not in {"completed", "failed", "stopped", "interrupted"} for t in workspace.store.list("trial", cid)):
        time.sleep(0.5)
    trials = {(t["hypothesis_id"], t["seed"]): t for t in workspace.store.list("trial", cid)}
    by_method = {h["id"]: [trials[(h["id"], seed)] for seed in SEEDS] for h in proposals}
    assert all(t["status"] == "completed" for t in trials.values()), {k: (t["status"], t.get("reason")) for k, t in trials.items()}
    for proposal in (proposals[0], proposals[3]):   # earliest due date and exact enumeration
        assert [t["reason"] for t in by_method[proposal["id"]]] == ["method_finished"] * len(SEEDS)

    # Balsamic wakes the lead once, for the comparison, when every approved run has ended; the lead writes it.
    deadline = time.time() + 60
    while not comparisons and time.time() < deadline:
        time.sleep(0.5)
    lead_id = workspace.pi.configuration(cid)["lead_id"]
    wakes = [r for r in stack.agents[lead_id]["runs"].values() if "Write the comparison (comparison.report)" in r["text"]]
    assert len(wakes) == 1 and len(comparisons) == 1, comparisons
    # The report ranks exact enumeration best (lowest tardiness, the optimum) and earliest due date last.
    [group] = comparisons[0]["comparison"]
    rows = {row["algorithm"]: row for row in group["method_summaries"]}
    edd, exact = keys[proposals[0]["id"]], keys[proposals[3]["id"]]
    assert group["direction"] == "minimize" and rows[exact]["rank"] == 1 and rows[exact]["mean"] == 290 == min(r["mean"] for r in rows.values())
    assert rows[edd]["mean"] == 415 and rows[edd]["rank"] == max(r["rank"] for r in rows.values())
    # So does the ledger: the proposals' best results on the Evolution page.
    ledger = {node["id"]: node["best"]["score"] for node in client.get(f"/api/v1/campaigns/{cid}/evolution").json()["nodes"]}
    assert ledger[proposals[3]["id"]] == 290 == min(ledger.values()) and ledger[proposals[0]["id"]] == 415

    # The researcher acted three times in all: the charter's confirmation, one message and one decision.
    researcher = [r["request"]["operation"] for r in workspace.store.list("work_command", cid) if r.get("actor") == "researcher"]
    assert [op for op in researcher if op not in {"campaign.create", "agent.activate"}] == ["agent.message", "decision.resolve"]
