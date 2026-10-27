"""Bring your own session (roadmap H3): the researcher clones a coding workspace's library, works on it with their own coding
agent, and delivers a commit as a Git bundle with a token only they were shown. The host captures it as it captures the box's
commit (capture_submission), and Balsamic installs and binds it the same way. Git is real; uv is faked as in
test_library_install."""
import base64
import contextlib
import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from optimization_framework.agents import development_api, own_session
from optimization_framework.agents.development import DevelopmentWorkspaces
from optimization_framework.agents.development_runtime import ROOT, write_library
from optimization_framework.agents.development_timeline import timeline
from optimization_framework.agents.library_install import Installer
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace
from optimization_framework.problem_charter.scaffold import scaffold
from optimization_framework.storage.sqlite import now
from test_automatic_binding import proposal
from test_library_install import PYPROJECT, Plugins, Problems
from test_problem_charter_scaffold import METHODS, OBJECTIVE, ovens

LIBRARY = "libraries/oven_trays"
CLI = ROOT / "deploy/implementation-workspace/balsamic-workspace.mjs"
REPORT = {"verdict": "ready", "summary": "The methods work.", "limitations": [], "next_actions": [],
          "tests": {"passed": 21, "failed": 0, "skipped": 0, "command": "pytest libraries/oven_trays"},
          # A method of the lab's stands in for the library's, as in test_automatic_binding, so that it can be bound.
          "methods": [{"method_id": "random", "hypothesis_id": "hypothesis_dev", "state": "implemented", "conformance": "passed"}]}
WHO = ["-c", "user.name=Researcher", "-c", "user.email=researcher@example.org"]


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class Driver:
    """The fake driver: the box's store is a directory of its own, and a snapshot reads it as `docker exec git show` does."""

    def __init__(self, directory):
        self.directory = directory

    def root(self, record):
        return self.directory / record["id"]

    def name(self, record):
        return "grating-" + record["id"]

    def snapshot(self, record, commit, manifest_path):
        return own_session.snapshot(self.root(record) / "work" / "git", commit, manifest_path)


class Lab:
    """A campaign made from the ovens' charter, a coding workspace that started from its generated library, the box's store
    (a bare clone of the lab's history, as DockerWorkspace.prepare() makes it), the lab a library installs into, and the
    workspace routes."""

    def __init__(self, base):
        self.base = base
        self.workspace = Workspace(base / "workspace")
        self.cid = self.workspace.create_campaign(CampaignInput(name="Ovens", compute_budget_seconds=100, validation_reserve_seconds=10,
            tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))["id"]
        charter = self.workspace.charters.create(ovens(), source={"kind": "test"})
        self.workspace.store.put("campaign", {**self.workspace.store.get(self.cid, "campaign"),
                                              "charter": {"id": charter["id"], "revision": charter["revision"]}})
        proposal(self.workspace, self.cid, "hypothesis_dev")
        self.driver = Driver(base / "development")
        self.development = DevelopmentWorkspaces(self.workspace.pi, driver=self.driver)
        self.workspace.pi.development = self.development
        self.notices = []
        self.development.notify = lambda record, key, text, read="": self.notices.append(text)
        self.record = self.open("development_ovens")
        self.source = base / "lab-source"
        self.source.mkdir()
        (self.source / "README.md").write_text("The lab\n")
        git("init", "-q", "-b", "main", cwd=self.source)
        git("add", ".", cwd=self.source)
        git(*WHO, "commit", "-q", "-m", "The lab", cwd=self.source)
        self.box = self.driver.root(self.record) / "work" / "git"
        self.box.parent.mkdir(parents=True)
        git("clone", "-q", "--bare", str(self.source), str(self.box), cwd=base)
        self.root = base / "lab"
        (self.root / "libraries").mkdir(parents=True)
        (self.root / "pyproject.toml").write_text(PYPROJECT)
        (self.root / "uv.lock").write_text("lock v1\n")
        self.app = FastAPI()
        # The app's own answers to a refused or missing record (balsamic/app.py).
        self.app.add_exception_handler(ValueError, lambda request, exc: JSONResponse({"detail": str(exc)}, status_code=409))
        self.app.add_exception_handler(KeyError, lambda request, exc: JSONResponse({"detail": "Workspace record not found"}, status_code=404))
        development_api.install(self.app, self.workspace)
        self.client = TestClient(self.app)
        self.url = self.address(self.record)

    def open(self, identity):
        """A workspace that started from the charter's generated library, its record as _sync_one() leaves it."""
        record = {"id": identity, "campaign_id": self.cid, "hypothesis_id": "hypothesis_dev", "title": "Oven trays", "status": "idle",
                  "desired_status": "running", "created_at": now(), "cursor": 0, "control_revision": 0, "usage": {"container_cpu_seconds": 0}}
        library = self.development.generated_library(record)[0]
        hashes = write_library(self.base / "generated" / identity, library)
        record["library"] = {key: value for key, value in library.items() if key != "files"} | {"files": hashes}
        return self.workspace.store.put("development_workspace", record)

    def address(self, record):
        return f"/api/campaigns/{self.cid}/implementation-workspaces/{record['id']}"

    def token(self, record=None):
        answer = self.client.post(self.address(record or self.record) + "/session-token")
        assert answer.status_code == 200, answer.text
        return answer.json()["token"]

    def submissions(self):
        return self.workspace.store.list("development_submission", self.cid)

    def install(self, submission, monkeypatch):
        """Balsamic's own install of the submission (Installer.automatic), uv faked."""
        monkeypatch.setattr(Installer, "_refuse_clashes", lambda self, *args: None)
        plugins = Plugins()

        def runner(args, cwd, timeout=600):
            if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
                plugins.synced = True
            return 0, " Would make no changes\n" if "--dry-run" in args else "ok"
        installer = Installer(self.workspace, self.development, self.root, runner=runner, uv="uv", plugins=plugins,
                              problems=Problems(plugins, ("oven_trays",)), providers=lambda group: {})
        return installer.automatic(self.cid, self.record["id"], submission, background=False)


def fill(repo):
    """The researcher's work: the objective and the methods written into the library, committed."""
    for path, text in {"oven_trays/objective.py": OBJECTIVE, "oven_trays/methods.py": METHODS}.items():
        (repo / LIBRARY / path).write_text(text)
    git("add", ".", cwd=repo)
    git(*WHO, "commit", "-q", "-m", "Objective and methods", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def bundle(repo, commit, *exclude):
    """A bundle of the commit (base64) without those of the commits excluded that the repository has, as balsamic-workspace
    submit makes it."""
    exclude = [sha for sha in exclude if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo, capture_output=True).returncode == 0]
    git("update-ref", "refs/test/submit", commit, cwd=repo)
    file = repo.parent / f"{commit[:12]}.bundle"
    try:
        git("bundle", "create", str(file), "refs/test/submit", *(["--not", *exclude] if exclude else []), cwd=repo)
    finally:
        git("update-ref", "-d", "refs/test/submit", cwd=repo)
    return base64.b64encode(file.read_bytes()).decode()


def clone(lab, token, target):
    """balsamic-workspace clone: the workspace's start, as a Git repository."""
    start = lab.client.get(lab.url + "/bundles/start", headers=bearer(token))
    assert start.status_code == 200, start.text
    file = target.parent / "start.bundle"
    file.write_bytes(base64.b64decode(start.json()["bundle"]))
    git("clone", "-q", "--branch", "main", str(file), str(target), cwd=target.parent)
    return start.json()


def deliver(lab, token, commit, data, **fields):
    return lab.client.post(lab.url + "/bundles", headers=bearer(token), json={"commit": commit, "report": REPORT, "bundle": data, **fields})


def outcome(install):
    """What an install did, without who asked for it, when, or from which commit."""
    return {**{key: install[key] for key in ("status", "package", "version", "path", "methods_added", "missing_methods", "problems_added",
                                              "changed_generated_files", "skipped")},
            "bindings": [(row["hypothesis_id"], row["method"]) for row in install["bindings"]]}


def test_a_bundle_from_outside_the_box_installs_and_binds_like_the_coding_agents_commit(tmp_path, monkeypatch):
    inside, outside = Lab(tmp_path / "inside"), Lab(tmp_path / "outside")

    # The coding agent's delivery: its commit on the workspace's branch in the box's store, and its submit event.
    write_library(inside.source, inside.development.generated_library(inside.record)[0])
    git("checkout", "-q", "-b", "implementation/development_ovens", cwd=inside.source)
    agents = fill(inside.source)
    git("--git-dir", str(inside.box), "fetch", "-q", str(inside.source), "implementation/development_ovens:implementation/development_ovens",
        cwd=tmp_path)
    root = inside.driver.root(inside.record)
    for folder in ("outgoing/events", "incoming/results"):
        (root / folder).mkdir(parents=True)
    (root / "outgoing/events/submit.json").write_text(json.dumps({"type": "submission", "payload": {
        "commit": agents, "manifest_path": "implementation-manifest.json", "notes": "", "report": REPORT}}))
    inside.development.receive(inside.record)
    [ours] = inside.submissions()

    # The researcher's: their own clone of the workspace's library, their commit, a bundle of what the host lacks.
    token = outside.token()
    repo = tmp_path / "mine"
    clone(outside, token, repo)
    commit = fill(repo)
    have = outside.client.get(outside.url + "/bundles/base", headers=bearer(token)).json()["commits"]
    answer = deliver(outside, token, commit, bundle(repo, commit, *have))
    assert answer.status_code == 200, answer.text
    [theirs] = outside.submissions()
    assert answer.json() == {"submission_id": theirs["id"], "status": "submitted"}
    # The exact commit, read from the bundle: the same manifest and files as the coding agent's delivery of the same library.
    assert theirs["commit"] == commit and theirs["source"] == "own_session" and "source" not in ours
    assert theirs["report"] == ours["report"] and theirs["manifest"] == ours["manifest"]
    same = lambda lab, submission: [(row["path"], row["content"].replace(lab.record["library"]["charter_id"], "<charter>"))
                                    for row in submission["package"]["files"]]   # each lab's charter has an id of its own
    assert same(outside, theirs) == same(inside, ours)
    assert theirs["manifest"]["files"] == sorted(f"{LIBRARY}/{path}" for path in scaffold(ovens(), 1, balsamic=True))
    # Nothing in the box answers it, and the lead is told who delivered.
    assert not list((outside.driver.root(outside.record) / "incoming").glob("**/*.json"))
    assert outside.notices[0].startswith(f"The researcher delivered commit {commit} from their own coding session as {theirs['id']}. "
                                         "The researcher's verdict: ready")
    entries = timeline(outside.workspace.store, outside.development.get(outside.cid, outside.record["id"]))["entries"]
    assert entries[0]["title"] == f"Delivered commit {commit[:7]} from your own session: ready"

    # Balsamic installs and binds both the same way: installed from the exact commit, the proposal bound by Balsamic.
    mine, its = outside.install(theirs, monkeypatch), inside.install(ours, monkeypatch)
    assert outcome(mine) == outcome(its)
    assert mine["status"] == "installed" and mine["commit"] == commit and mine["changed_generated_files"] == []
    assert outcome(mine)["bindings"] == [("hypothesis_dev", "random")]
    binding = outside.workspace.store.get(mine["bindings"][0]["binding_id"], "builtin_binding")
    assert binding["authority"] == "balsamic" and binding["install_id"] == mine["id"]
    installed = {path.relative_to(outside.root).as_posix(): path.read_bytes() for path in (outside.root / LIBRARY).rglob("*") if path.is_file()}
    assert installed == {path: subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo, capture_output=True, check=True).stdout
                         for path in theirs["manifest"]["files"]}
    assert "Balsamic bound hypothesis_dev to random." in outside.notices[-1]


def test_a_commit_on_the_labs_history_travels_without_the_history_the_box_has(tmp_path):
    lab = Lab(tmp_path)
    token = lab.token()
    have = lab.client.get(lab.url + "/bundles/base", headers=bearer(token)).json()["commits"]
    tip = git("rev-parse", "HEAD", cwd=lab.source)
    assert have == [tip]   # the box's store names the lab's commit it was cloned at
    # The researcher's own clone of the lab: a branch with the library, on top of the lab's commit.
    repo = tmp_path / "checkout"
    git("clone", "-q", str(lab.source), str(repo), cwd=tmp_path)
    write_library(repo, lab.development.generated_library(lab.record)[0])
    commit = fill(repo)
    data = bundle(repo, commit, *have)
    assert b"-" + tip.encode() in base64.b64decode(data)   # a thin bundle: it needs the lab's commit, which it does not carry
    answer = deliver(lab, token, commit, data)
    assert answer.status_code == 200, answer.text
    assert [row["commit"] for row in lab.submissions()] == [commit]
    # The host has it now, so the next bundle may build on it.
    assert commit in lab.client.get(lab.url + "/bundles/base", headers=bearer(token)).json()["commits"]


def test_a_wrong_token_or_none_opens_nothing(tmp_path):
    lab = Lab(tmp_path)
    token = lab.token()
    other = lab.token(lab.open("development_other"))
    stranger = lab.workspace.create_campaign(CampaignInput(name="Other", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))["id"]
    routes = [("get", lab.url + "/bundles/base"), ("get", lab.url + "/bundles/start"), ("post", lab.url + "/bundles"),
              ("get", f"/api/campaigns/{stranger}/implementation-workspaces/development_ovens/bundles/base"),
              ("get", f"/api/campaigns/{lab.cid}/implementation-workspaces/development_missing/bundles/start")]
    body = {"commit": "a" * 40, "report": REPORT, "bundle": "eA=="}
    for headers in [{}, bearer("bws_wrong"), bearer(""), {"Authorization": token}, {"Authorization": f"Basic {token}"}, bearer(other)]:
        for method, url in routes:
            answer = getattr(lab.client, method)(url, headers=headers, **({"json": body} if method == "post" else {}))
            assert answer.status_code == 401, (headers, url)
            assert answer.json() == {"detail": "The token does not open this workspace"}
            assert answer.headers["www-authenticate"] == "Bearer"
    # The workspace's own token opens only its own workspace, in its own campaign.
    for _, url in routes[3:]:
        assert lab.client.get(url, headers=bearer(token)).status_code == 401
    # Nothing was read, kept or made.
    assert lab.submissions() == [] and lab.workspace.store.list("development_event", lab.cid) == []
    assert not (lab.driver.root(lab.record) / "own").exists()


def test_a_bundle_without_the_commit_is_refused_and_nothing_is_captured(tmp_path):
    lab = Lab(tmp_path)
    token = lab.token()
    repo = tmp_path / "mine"
    start = clone(lab, token, repo)["commit"]
    commit = fill(repo)
    # The bundle of another commit, claiming this one.
    other = deliver(lab, token, commit, bundle(repo, start))
    assert other.status_code == 409 and other.json()["detail"].startswith(f"The bundle does not carry commit {commit}: it carries {start[:12]}")
    # A bundle that builds on a commit the host does not have.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    git("init", "-q", cwd=elsewhere)
    git(*WHO, "commit", "-q", "--allow-empty", "-m", "theirs", cwd=elsewhere)
    base = git("rev-parse", "HEAD", cwd=elsewhere)
    git(*WHO, "commit", "-q", "--allow-empty", "-m", "next", cwd=elsewhere)
    thin = git("rev-parse", "HEAD", cwd=elsewhere)
    missing = deliver(lab, token, thin, bundle(elsewhere, thin, base))
    assert missing.status_code == 409 and "The bundle builds on commits this workspace does not have" in missing.json()["detail"]
    assert base in missing.json()["detail"]
    # Not a bundle, not base64, not a commit hash.
    assert "The upload is not a Git bundle" in deliver(lab, token, commit, base64.b64encode(b"loose files").decode()).json()["detail"]
    assert deliver(lab, token, commit, "not base64!").json() == {"detail": "bundle: not base64"}
    assert deliver(lab, token, "HEAD", bundle(repo, commit)).status_code == 422
    assert lab.submissions() == []
    assert git("--git-dir", str(lab.driver.root(lab.record) / "own/git"), "for-each-ref", "refs/balsamic", cwd=tmp_path) == ""
    # Each refusal is on the workspace's history, as a refused submission from the box is.
    refused = [entry["title"] for entry in timeline(lab.workspace.store, lab.development.get(lab.cid, lab.record["id"]))["entries"]
               if entry["kind"] == "refused"]
    assert len(refused) == 4 and f"Refused: The bundle does not carry commit {commit}" in " ".join(refused)
    # The same commit with its own bundle is taken.
    assert deliver(lab, token, commit, bundle(repo, commit, start)).status_code == 200


def test_the_token_is_shown_once_kept_as_a_digest_replaced_by_a_new_one_and_revoked_when_the_workspace_stops(tmp_path):
    lab = Lab(tmp_path)
    assert lab.client.get(lab.url + "/session-token").json() == {"issued_at": None, "last_used_at": None, "active": False,
                                                                 "revoked": None, "stopped": False}
    made = lab.client.post(lab.url + "/session-token").json()
    token = made["token"]
    assert token.startswith("bws_") and len(token) > 40 and made["workspace_id"] == "development_ovens"
    assert made["cli"].endswith("deploy/implementation-workspace/balsamic-workspace.mjs")
    state = lab.client.get(lab.url + "/session-token")
    assert state.json() == {"issued_at": made["issued_at"], "last_used_at": None, "active": True, "revoked": None, "stopped": False}
    # Balsamic keeps its digest only: the token is in no file of the lab, and in nothing an agent reads of the workspace.
    saved = lab.workspace.store.get(own_session.identity("development_ovens"), own_session.KIND)
    assert saved["digest"] == hashlib.sha256(token.encode()).hexdigest()
    for path in lab.workspace.directory.rglob("*"):
        assert not path.is_file() or token.encode() not in path.read_bytes(), path
    seen = json.dumps(lab.development.events(lab.cid, "development_ovens")) + json.dumps(lab.development.view(lab.cid))
    assert token not in seen and saved["digest"] not in seen
    assert lab.client.get(lab.url + "/bundles/base", headers=bearer(token)).status_code == 200
    assert lab.client.get(lab.url + "/session-token").json()["last_used_at"] is None   # reading is not delivering

    # A new token replaces it.
    newer = lab.token()
    assert lab.client.get(lab.url + "/bundles/base", headers=bearer(token)).status_code == 401
    assert lab.client.get(lab.url + "/bundles/base", headers=bearer(newer)).status_code == 200

    # Stopping the workspace revokes it; no token is made while it is stopped, and a resume does not bring it back.
    lab.development.control(lab.cid, "development_ovens", {"action": "stop", "request_key": "stop", "expected_revision": 0})
    refused = lab.client.get(lab.url + "/bundles/start", headers=bearer(newer))
    assert refused.status_code == 401 and refused.json()["detail"] == ("The token no longer opens this workspace: the workspace is stopped. "
                                                                       "Make a new one on the workspace's card")
    assert lab.client.get(lab.url + "/session-token").json()["revoked"] == "the workspace is stopped"
    assert lab.client.post(lab.url + "/session-token").status_code == 409
    lab.development.control(lab.cid, "development_ovens", {"action": "resume", "request_key": "resume", "expected_revision": 1})
    assert "was stopped after it was made" in lab.client.get(lab.url + "/bundles/base", headers=bearer(newer)).json()["detail"]
    assert lab.client.get(lab.url + "/bundles/base", headers=bearer(lab.token())).status_code == 200


def test_a_paused_workspace_takes_no_delivery_until_it_is_resumed_and_one_past_its_deadline_needs_a_new_go_ahead(tmp_path):
    lab = Lab(tmp_path)
    token = lab.token()
    repo = tmp_path / "mine"
    start = clone(lab, token, repo)["commit"]
    commit = fill(repo)
    data = bundle(repo, commit, start)
    lab.development.control(lab.cid, "development_ovens", {"action": "pause", "request_key": "pause", "expected_revision": 0})
    paused = deliver(lab, token, commit, data)
    assert paused.status_code == 409 and paused.json()["detail"] == "The workspace is paused: resume it before delivering to it"
    # Reading stays open: the library can still be cloned while the workspace is paused.
    assert lab.client.get(lab.url + "/bundles/start", headers=bearer(token)).status_code == 200
    lab.development.control(lab.cid, "development_ovens", {"action": "resume", "request_key": "resume", "expected_revision": 1})
    # Past its deadline (H5), before the sync has paused it: going on is a new go-ahead.
    record = lab.development.get(lab.cid, "development_ovens")
    lab.workspace.store.put("development_workspace", {**record, "wall_seconds": 60, "deadline_at": "2026-01-01T00:00:00+00:00"})
    late = deliver(lab, token, commit, data)
    assert late.status_code == 409 and "reached its deadline and is paused: going on is a new go-ahead" in late.json()["detail"]
    assert lab.submissions() == []
    lab.development.control(lab.cid, "development_ovens", {"action": "resume", "request_key": "again", "expected_revision": 2,
                                                          "wall_seconds": 3600})
    assert deliver(lab, token, commit, data).status_code == 200
    assert lab.client.get(lab.url + "/session-token").json()["last_used_at"]


def test_the_start_is_the_generated_library_byte_for_byte_and_the_same_commit_each_time(tmp_path):
    lab = Lab(tmp_path)
    token = lab.token()
    repo = tmp_path / "mine"
    first = clone(lab, token, repo)
    assert first["library"] == LIBRARY and first == lab.client.get(lab.url + "/bundles/start", headers=bearer(token)).json()
    generated = scaffold(ovens(), lab.record["library"]["revision"], charter_id=lab.record["library"]["charter_id"], balsamic=True)
    files = {path.relative_to(repo).as_posix(): path.read_bytes() for path in repo.rglob("*") if path.is_file() and ".git" not in path.parts}
    assert files == {f"{LIBRARY}/{path}": content for path, content in generated.items()}
    assert git("rev-parse", "HEAD", cwd=repo) == first["commit"] and git("log", "--format=%an %s", cwd=repo) == \
        f"Balsamic The library generated from charter revision {lab.record['library']['revision']}"
    # A workspace that did not start from a generated library has no start to give.
    lab.workspace.store.put("development_workspace", {k: v for k, v in lab.development.get(lab.cid, "development_ovens").items() if k != "library"})
    none = lab.client.get(lab.url + "/bundles/start", headers=bearer(token))
    assert none.status_code == 409 and none.json()["detail"].startswith("This workspace starts from no library generated from a charter")


def test_in_the_lab_a_page_of_another_origin_makes_no_token_and_a_stranger_leaves_no_trace(tmp_path, monkeypatch):
    from balsamic.app import create_app
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path / "workspace", start_workers=False)
    with TestClient(app) as client:
        workspace = app.state.workspace
        cid = workspace.create_campaign(CampaignInput(name="Ovens", compute_budget_seconds=100, validation_reserve_seconds=10,
            tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))["id"]
        workspace.store.put("development_workspace", {"id": "development_ovens", "campaign_id": cid, "hypothesis_id": "hypothesis_dev",
            "title": "Oven trays", "status": "idle", "desired_status": "running", "created_at": now(), "cursor": 0, "control_revision": 0})
        url = f"/api/campaigns/{cid}/implementation-workspaces/development_ovens"
        # The card's route is the researcher's: a page of another origin cannot make a token, the lab's own page can.
        assert client.post(url + "/session-token", headers={"Origin": "https://elsewhere.example"}).status_code == 403
        token = client.post(url + "/session-token").json()["token"]
        issues = len(workspace.store.list("manager_issue", cid))
        stranger = client.post(url + "/bundles", json={"commit": "a" * 40, "report": REPORT, "bundle": "eA=="})
        assert stranger.status_code == 401 and len(workspace.store.list("manager_issue", cid)) == issues
        # The CLI sends no Origin; its token opens the workspace's routes in the lab.
        assert client.get(url + "/bundles/base", headers=bearer(token)).json() == {"commits": []}


@contextlib.contextmanager
def serving(app):
    """The routes on a real port, for the CLI."""
    import uvicorn
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(500):
        if server.started:
            break
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)


def cli(env, *args, cwd):
    result = subprocess.run(["node", str(CLI), *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="the CLI runs on Node")
def test_the_cli_clones_the_library_and_delivers_a_commit_from_outside_the_box(tmp_path, monkeypatch):
    lab = Lab(tmp_path / "lab")
    token = lab.token()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(REPORT))
    with serving(lab.app) as address:
        env = {key: value for key, value in os.environ.items() if not key.startswith(("BALSAMIC_", "GRATING_DEVELOPMENT_BRIDGE"))}
        env.update(BALSAMIC_WORKSPACE_URL=address + lab.url, BALSAMIC_WORKSPACE_TOKEN=token)
        cloned = cli(env, "clone", "mine", cwd=tmp_path)
        repo = tmp_path / "mine"
        assert cloned["library"] == LIBRARY and cloned["directory"] == str(repo)
        commit = fill(repo)
        answer = cli(env, "submit", "HEAD", "--report", str(report), cwd=repo)
    [submission] = lab.submissions()
    assert answer["submission_id"] == submission["id"] and answer["message"].startswith(f"Submitted {submission['id']}.")
    assert submission["commit"] == commit and submission["source"] == "own_session"
    assert git("for-each-ref", cwd=repo) == f"{commit} commit\trefs/heads/main"   # the temporary ref is gone, and no remote is left
    install = lab.install(submission, monkeypatch)
    assert install["status"] == "installed" and [row["method"] for row in install["bindings"]] == ["random"]
