"""Commissions run as headless coding boxes (roadmap H7): an implementation lead's implementation.commission (or
evaluator.commission) through the bus opens a coding workspace in which Pi runs headless, on a work ticket that holds the
commission's frozen specification, behind the box's walls; its protected acceptance tests are written outside the box and kept
there; what it delivers is a submission like any other, validated outside the box (H6) and installed. Its compute is the
commission's, charged to the go-ahead once. A commission that cannot open a box (coding workspaces off, a package to import, an
evaluator no charter declares) is refused with what to do instead since H8, and old jobs stay readable.

The box is a fake driver over real Git stores (no Docker here), and the test plays its coding agent; validation outside the box
is real (bubblewrap); uv is faked as in test_library_install."""
import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from optimization_framework.agents import own_session
from optimization_framework.agents.development import DevelopmentWorkspaces
from optimization_framework.agents.development_commission import FIXTURES, NEEDS_PROTECTED
from optimization_framework.agents.development_runtime import write_library, write_ticket
from optimization_framework.agents.library_install import Installer
from optimization_framework.agents.library_validation import PROTECTED, protected_tests
from optimization_framework.campaigns import mandates
from optimization_framework.contracts.commands import Command, CommandOrigin
from optimization_framework.contracts.requests import CampaignInput
from optimization_framework.execution.service import Workspace
from optimization_framework.implementations.models import EvaluatorSpec, ImplementationSpec
from optimization_framework.storage.sqlite import now
from test_library_install import PYPROJECT, Plugins, Problems, git
from test_problem_charter_scaffold import METHODS, OBJECTIVE, ovens

LIBRARY = "libraries/oven_trays"
ROOT = {"thread_id": "thread_main", "message_id": "message_ask", "run_id": "run_ask"}
SECRET = "the heater check the coding agent never reads"
# The commissioner's protected acceptance test, written outside the box: no method may ask the heater for more than it holds.
HEATER = f'''
import numpy as np
import pytest

from oven_trays.harness import methods, run
from oven_trays.problem import problem


@pytest.mark.parametrize("name", sorted(methods()))
def test_no_method_asks_more_than_the_heater_holds(name):
    result = run(methods()[name], problem(), seed=0, max_evaluations=20)
    assert float(np.asarray(result.best).sum()) <= 760.0, "{SECRET}"
'''
SPEC = ImplementationSpec(name="Oven tray search", mechanism="Try the listed settings tray by tray and keep the closest valid one.",
                          acceptance_criteria=["Every candidate is a listed setting within the heater limit", "The same seed repeats its run"],
                          problem_id="oven_trays").model_dump(mode="json")
REPORT = {"verdict": "ready", "summary": "The three methods work.", "limitations": [], "next_actions": [],
          "tests": {"passed": 21, "failed": 0, "skipped": 0, "command": f"uv run pytest {LIBRARY}"},
          "methods": [{"method_id": method, "hypothesis_id": "hypothesis_dev", "state": "implemented", "conformance": "passed"}
                      for method in ("random_search", "all_middle", "all_cold")]}


class Box:
    """The fake driver: the box's worktree and its Git store are directories of this test, and its harness setting is recorded at
    start. Nothing runs in the box but what the test does as its coding agent."""

    def __init__(self, directory):
        self.directory, self.started = directory, []

    def root(self, record):
        return self.directory / record["id"]

    def name(self, record):
        return "grating-" + record["id"]

    def repo(self, record):
        return self.root(record) / "work" / "repo"

    def capability(self):
        return {"available": True}

    def prepare(self, record, brief, evidence, library=None, ticket=None, references=()):
        root = self.root(record)
        for name in ("incoming/commands", "incoming/results", "outgoing/events"):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / "brief.md").write_text(brief)
        hashes = write_library(self.repo(record), library) if library else None
        write_ticket(self.repo(record), ticket)
        return hashes

    def start(self, record):
        self.started.append(record["harness"])
        return self.inspect(record)

    def inspect(self, record):
        return {"running": True, "paused": False}

    def cpu_seconds(self, state):
        return 0

    def pause(self, record):
        pass

    def stop(self, record):
        pass

    def snapshot(self, record, commit, manifest_path):
        return own_session.snapshot(self.root(record) / "work" / "git", commit, manifest_path)


class Service:
    """The implementation service, as test_implementation_ceiling fakes it: a job accepted for each grant it is sent."""

    def __init__(self):
        self.jobs = {}

    def versions(self):
        return []

    def submit(self, request):
        return self.jobs.setdefault(request["idempotency_key"], {"id": "job_" + request["idempotency_key"], "status": "queued"})


class Lab:
    """A campaign made from the ovens' confirmed charter (its evaluator declared: oven_trays), its team on, a proposal, the
    implementation lead working for the researcher's request under a Screen mandate approved for it, and the lab a library
    installs into."""

    def __init__(self, base, *, coding_workspaces=0):
        self.base = base
        self.service = Service()
        self.workspace = self.service.workspace = Workspace(base / "workspace", implementation_client=self.service)
        store = self.workspace.store
        confirmed = self.workspace.charters.confirm(self.workspace.charters.create(ovens(), source={"kind": "test"})["id"])
        self.cid = self.workspace.create_campaign(CampaignInput(name="Ovens", charter=confirmed["charter"], autonomy="delegated",
                                                                compute_budget_seconds=7200, validation_reserve_seconds=0))["id"]
        self.workspace.commands.execute(Command(id="activate", campaign_id=self.cid, expected_revision=store.get(self.cid, "campaign")["version"],
                                                operation="agent.activate", payload={"objective": "Implement the ovens' methods"}))
        store.put("hypothesis", {"id": "hypothesis_dev", "campaign_id": self.cid, "title": "Oven tray search", "status": "proposed",
                                 "mechanism": "Tray by tray", "algorithm": "custom", "algorithm_config": {}})
        self.box = Box(base / "boxes")
        self.development = DevelopmentWorkspaces(self.workspace.pi, driver=self.box)
        self.workspace.pi.development = self.development
        self.lead = self.workspace.pi.page_agent(self.cid, "implementation_lead")
        store.put("agent_session", {**store.get(self.lead["id"], "agent_session"), "assignment_origin": ROOT})
        self.run = store.put("agent_run", {"id": "run_implementation_lead", "campaign_id": self.cid, "agent_id": self.lead["id"],
                                           "status": "running", "created_at": now()})
        decision = store.put("decision", {"id": "decision_screen", "campaign_id": self.cid, "title": "Screen", "question": "Screen",
            "status": "resolved", "requested_by": "lead", "audience": "researcher", "created_at": now(), "request_root": ROOT,
            "approval_request": {"kind": "mandate", "template": "screen", "plan": "Commission the ovens' method and evaluator",
                                 "wall_seconds": 3600, "worker_seconds": 2400, "coding_workspaces": coding_workspaces,
                                 "hypothesis_ids": ["hypothesis_dev"]}})
        self.consent_id = mandates.approve(self.workspace, decision)["consent_id"]
        self.root = base / "lab"
        (self.root / "libraries").mkdir(parents=True)
        (self.root / "pyproject.toml").write_text(PYPROJECT)
        (self.root / "uv.lock").write_text("lock v1\n")

    def command(self, operation, payload, key, actor="manager"):
        campaign = self.workspace.store.get(self.cid, "campaign")
        pins = {"expected_guidance_revision": self.workspace.memory.state(self.cid)["guidance_revision"],
                "expected_authority_hash": self.workspace.commands.authority_hash(campaign),
                "origin": CommandOrigin(actor="page_agent", agent_id=self.lead["id"], run_id=self.run["id"])} if actor == "manager" else {}
        return self.workspace.commands.execute(Command(id=key, campaign_id=self.cid, expected_revision=campaign["version"],
                                                       operation=operation, payload=payload, **pins), actor=actor)

    def consent(self):
        return self.workspace.store.get(self.consent_id, "compute_consent")

    def deliver(self, record, files, report, key="submission"):
        """The coding agent's work: the library's files written and committed in the box's worktree, the commit in the box's Git
        store, and its submission through the bridge, as campaign_submit sends it."""
        repo = self.box.repo(record)
        for path, text in files.items():
            (repo / LIBRARY / path).write_text(text)
        if not (repo / ".git").exists():
            git("init", "-q", cwd=repo)
        git("add", "-A", cwd=repo)
        git("-c", "user.name=coder", "-c", "user.email=coder@box", "commit", "-q", "-m", key, cwd=repo)
        commit = git("rev-parse", "HEAD", cwd=repo)
        store = self.box.root(record) / "work" / "git"
        if store.exists():
            git("--git-dir", str(store), "fetch", "-q", str(repo), "+HEAD:refs/heads/main", cwd=self.base)
        else:
            git("clone", "-q", "--bare", str(repo), str(store), cwd=self.base)
        event = {"type": "submission", "payload": {"commit": commit, "manifest_path": "implementation-manifest.json", "notes": "",
                                                   **({"report": report} if report else {})}}
        (self.box.root(record) / "outgoing/events" / f"{key}.json").write_text(json.dumps(event))
        self.development.sync(self.cid)
        return next(row for row in self.workspace.store.list("development_submission", self.cid) if row["commit"] == commit)

    def install(self, record, submission, problems=("oven_trays",)):
        """Balsamic's own install of the delivery, validated outside the box with the real sandbox; uv and the lab's plug-ins faked."""
        plugins = Plugins()

        def runner(args, cwd, timeout=600):
            if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
                plugins.synced = True
            return 0, " Would make no changes\n" if "--dry-run" in args else "ok"
        installer = Installer(self.workspace, self.development, self.root, runner=runner, uv="uv", plugins=plugins,
                              problems=Problems(plugins, problems), providers=lambda group: {})
        return installer.automatic(self.cid, record["id"], submission, background=False)


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_DEVELOPMENT_ENABLED", "true")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    monkeypatch.setenv("GRATING_AUTO_INSTALL", "false")   # the install below goes into this test's lab, not the checkout
    return Lab(tmp_path)


def everything_under(directory):
    return b"\n".join(path.read_bytes() for path in directory.rglob("*") if path.is_file())


def commission(lab, key="commission", **changes):
    payload = {"hypothesis_id": "hypothesis_dev", "spec": SPEC, "compute_seconds": 900,
               "ticket": {"protected_tests": [{"name": "test_heater.py", "content": HEATER}]}, **changes}
    return lab.command("implementation.commission", payload, key)


needs_bwrap = pytest.mark.skipif(not shutil.which("bwrap"), reason="validation outside the box needs bubblewrap")


@needs_bwrap
def test_a_commission_opens_a_headless_box_on_a_ticket_and_ends_with_an_install_validated_outside_the_box(lab):
    receipt = commission(lab)
    outcome = receipt["outcome"]
    store = lab.workspace.store
    record = lab.development.get(lab.cid, outcome["workspace_id"])
    # No implementation service job: the commission is a coding workspace, headless, on a ticket, opened for the implementation lead.
    assert store.list("implementation_grant", lab.cid) == [] and not [row for row in store.list("outbox", lab.cid) if row["kind"] == "implementation_submit"]
    assert record["harness"] == {"name": "pi", "mode": "headless"} and record["hypothesis_ids"] == ["hypothesis_dev"]
    assert record["opened_by"] == {"actor": "lead", "agent_id": lab.lead["id"], "role": "implementation_lead"} and record["request_root"] == ROOT
    assert record["wall_seconds"] == 900 and record["egress"]["package_index"]   # its walls: the commission's compute time as its deadline
    assert record["commission"]["kind"] == "implementation" and record["commission"]["command_id"] == receipt["id"]
    ticket = store.get(outcome["ticket_id"], "development_ticket")
    assert ticket["commission"]["spec"]["mechanism"] == SPEC["mechanism"] and ticket["protected_tests"] == ["test_heater.py"]
    assert [row["path"] for row in ticket["acceptance_tests"]] == [f"{LIBRARY}/tests/test_{name}.py" for name in ("contract", "methods", "problem")]
    lab.development.sync(lab.cid)
    assert lab.box.started == [{"name": "pi", "mode": "headless"}]
    task = (lab.box.repo(record) / "TASK.md").read_text()
    assert "## The commission" in task and SPEC["mechanism"] in task and "- The same seed repeats its run" in task
    assert "Its METHODS key: `oven_tray_search`" in task and "`test_heater.py`" in task
    # The protected test was written outside the box: kept with it on the host, never in it.
    assert protected_tests(store, record) == {"test_heater.py": HEATER}
    assert SECRET.encode() not in everything_under(lab.box.root(record)) and SECRET not in json.dumps(ticket)

    # The coding agent fills the generated library and submits it with its report: a submission like any other.
    submission = lab.deliver(record, {"oven_trays/objective.py": OBJECTIVE, "oven_trays/methods.py": METHODS}, REPORT)
    assert submission["workspace_id"] == record["id"] and submission["report"]["verdict"] == "ready"
    install = lab.install(record, submission)
    assert install["status"] == "installed" and install["actor"] == "balsamic" and install["refused_methods"] == []
    host = install["host_validation"]
    assert host["tests"]["failed"] == 0 and {row["method_id"]: row["host"] for row in host["methods"]} == {
        method: "passed" for method in ("random_search", "all_middle", "all_cold")}
    # The protected test ran outside the box: by name and outcome on the install, its source and failure text nowhere else.
    assert {row["test"]: row["outcome"] for row in host["protected"]["results"]} == {
        f"test_heater.py::test_no_method_asks_more_than_the_heater_holds[{method}]": "passed" for method in ("all_cold", "all_middle", "random_search")}
    assert SECRET not in json.dumps(install) and SECRET.encode() not in everything_under(lab.box.root(record))
    # One log: the box's history is the commission's, from its opening to the install.
    from optimization_framework.agents.development_timeline import entries
    history = entries(store, lab.development.get(lab.cid, record["id"]))
    assert history[0]["title"] == "Commissioned by the implementation lead under your go-ahead"
    assert "Commission: an implementation job of 15 min, Oven tray search; its protected tests (test_heater.py) run outside the box" in history[0]["detail"]
    assert [row["kind"] for row in history[1:]].count("delivery") == 1


@needs_bwrap
def test_a_commissions_compute_is_charged_to_the_go_ahead_once(lab, monkeypatch):
    from optimization_framework.agents import development as module
    receipt = commission(lab)
    record = lab.development.get(lab.cid, receipt["outcome"]["workspace_id"])
    consent = lab.consent()
    # The bus charged the commission's compute time once, as it charges any commission; the box took no coding workspace.
    assert (consent["used_seconds"], consent["used_workspaces"]) == (900, 0) and record["id"] in consent["workspace_ids"]
    assert lab.workspace.implementations.compute_committed(lab.cid) == 900   # the researcher's optional ceiling counts it
    # The box runs for ten minutes: its wall time is counted on it, against the commission, and not charged again.
    lab.development.sync(lab.cid)
    later = datetime.now(timezone.utc) + timedelta(seconds=600)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return later
    monkeypatch.setattr(module, "datetime", Clock)
    lab.development.sync(lab.cid)
    monkeypatch.setattr(module, "datetime", datetime)
    assert lab.development.get(lab.cid, record["id"])["usage"]["wall_seconds"] >= 599
    # Its delivery's validation outside the box is counted on the commission too.
    submission = lab.deliver(record, {"oven_trays/objective.py": OBJECTIVE, "oven_trays/methods.py": METHODS}, REPORT)
    install = lab.install(record, submission)
    assert install["status"] == "installed"
    saved = lab.development.get(lab.cid, record["id"])
    assert 0 < saved["commission"]["usage"]["validation_seconds"] == pytest.approx(install["host_validation"]["seconds"])
    consent = lab.consent()
    assert (consent["used_seconds"], consent["used_workspaces"], consent.get("used_wall_seconds", 0)) == (900, 0, 0)
    # Replaying the command opens nothing more and charges nothing more.
    assert commission(lab)["outcome"] == receipt["outcome"] and lab.consent()["used_seconds"] == 900
    assert len(lab.workspace.store.list("development_workspace", lab.cid)) == 1


def declared_task(lab, name="Four trays"):
    return next(task for task in lab.workspace.current_tasks(lab.cid) if task["name"] == name)


def evaluator_spec(lab, task, **changes):
    """An evaluator commission's specification for the task's declared problem, with one independent fixture: every tray at 175 C
    misses the 180 C target by 4 x 5^2 = 100 C^2."""
    manifest = lab.workspace.store.get(task["evaluator_requirement_id"], "evaluator_requirement")["manifest"]
    fixture = {"name": "every tray at 175", "candidate": [175.0] * 4, "configuration": task["configuration"], "fidelity": task["fidelity"] or {},
               "basis": "4 x (175 - 180)^2, from the oven logbook", "objectives": {"squared_gap": 100.0}}
    return EvaluatorSpec(name="Oven tray gap", mechanism="The sum over the trays of the squared gap between each setting and the target.",
                         acceptance_criteria=["The objective is the charter's squared gap"], manifest=manifest, correctness_cases=[fixture],
                         **changes).model_dump(mode="json")


@needs_bwrap
def test_an_evaluator_commission_builds_the_tasks_problem_and_its_fixtures_are_checked_outside_the_box(lab, monkeypatch):
    from test_problem_charter import installed
    from optimization_framework.evaluation.registry import problems
    task = declared_task(lab)
    spec = evaluator_spec(lab, task)
    receipt = lab.command("evaluator.commission", {"task_id": task["id"], "spec": spec, "compute_seconds": 600}, "evaluator")
    store = lab.workspace.store
    record = lab.development.get(lab.cid, receipt["outcome"]["workspace_id"])
    # A box for the task, serving no proposal; the task says its evaluator is being built there.
    assert (record["hypothesis_ids"], record["task_id"], record["harness"]["mode"]) == ([], task["id"], "headless")
    assert receipt["outcome"]["task_id"] == task["id"] and store.list("implementation_grant", lab.cid) == []
    readiness = lab.workspace.evaluators.readiness(store.get(task["id"], "task"))
    assert (readiness["state"], readiness["workspace_id"]) == ("building", record["id"])
    # The specification's independent fixtures are a protected test Balsamic wrote; the coding agent sees how many, never them.
    ticket = store.get(record["ticket_id"], "development_ticket")
    assert ticket["protected_tests"] == [FIXTURES] and ticket["commission"]["fixtures"] == 1
    assert "correctness_cases" not in ticket["commission"]["spec"] and "oven logbook" not in json.dumps(ticket)
    assert "oven logbook" in protected_tests(store, record)[FIXTURES]
    lab.development.sync(lab.cid)
    task_text = (lab.box.repo(record) / "TASK.md").read_text()
    assert "Balsamic holds 1 independent numerical fixtures" in task_text and "None: this work builds the evaluator" in task_text
    assert b"oven logbook" not in everything_under(lab.box.root(record))

    # A wrong objective (the plain gap, not its square) fails the fixture outside the box: nothing is installed.
    wrong = OBJECTIVE.replace(" ** 2", "").replace("((problem.unpack", "(abs(problem.unpack")
    report = {**REPORT, "summary": "The objective is written.", "methods": []}
    failed = lab.install(record, lab.deliver(record, {"oven_trays/objective.py": wrong}, report, "first"))
    assert failed["status"] == "failed" and f"{FIXTURES}::test_the_evaluator_agrees_with_each_independent_fixture[fixture_1]" in failed["error"]
    assert "oven logbook" not in json.dumps(failed) and b"oven logbook" not in everything_under(lab.box.root(record))

    # The right one passes it, installs, and the declared task adopts the problem the library provides (E5).
    registry = installed(ovens(), distribution="oven-trays")
    monkeypatch.setitem(problems._loaders, "oven_trays", registry._loaders["oven_trays"])
    monkeypatch.delitem(problems._adapters, "oven_trays", raising=False)
    passed = lab.install(record, lab.deliver(record, {"oven_trays/objective.py": OBJECTIVE}, report, "second"))
    assert passed["status"] == "installed", passed.get("error")
    assert {row["test"]: row["outcome"] for row in passed["host_validation"]["protected"]["results"]} == {
        f"{FIXTURES}::test_the_evaluator_agrees_with_each_independent_fixture[fixture_1]": "passed"}
    assert task["id"] in [row["old_task_id"] for row in passed["adopted"]]   # with the charter's other declared task


def test_a_commission_without_protected_tests_or_over_its_limits_opens_nothing(lab):
    store = lab.workspace.store
    # The test designer's job is the commissioner's: a commission with no protected test is refused, naming where it goes.
    with pytest.raises(ValueError, match="A commission needs at least one protected acceptance test") as refused:
        commission(lab, "bare", ticket=None)
    assert str(refused.value) == NEEDS_PROTECTED
    task = declared_task(lab)
    clash = {"protected_tests": [{"name": FIXTURES, "content": "def test_x():\n    pass\n"}]}
    with pytest.raises(ValueError, match="protected test Balsamic writes from the specification's fixtures"):
        lab.command("evaluator.commission", {"task_id": task["id"], "spec": evaluator_spec(lab, task), "compute_seconds": 600, "ticket": clash}, "clash")
    # The researcher's optional ceiling counts a box's compute time as it counts a service job's.
    store.put("campaign", {**store.get(lab.cid, "campaign"), "implementation_compute_budget_seconds": 600})
    with pytest.raises(ValueError, match=r"exceed the implementation ceiling the researcher set \(600s\)"):
        commission(lab, "over")
    assert store.list("development_workspace", lab.cid) == [] and store.list(PROTECTED, lab.cid) == []
    assert lab.consent()["used_seconds"] == 0   # a refused command charges nothing


def test_the_deadline_is_the_commissions_compute_time_within_the_go_aheads_wall_time(lab):
    store = lab.workspace.store
    store.put("compute_consent", {**lab.consent(), "wall_seconds": 600})
    record = lab.development.get(lab.cid, commission(lab)["outcome"]["workspace_id"])
    assert record["wall_seconds"] == 600 and record["consent"]["id"] == lab.consent_id
    # The researcher's own commission has no go-ahead to fit: its compute time is its deadline.
    own = lab.command("implementation.commission", {"hypothesis_id": "hypothesis_dev", "spec": SPEC, "compute_seconds": 1200,
        "ticket": {"protected_tests": [{"name": "test_heater.py", "content": HEATER}]}}, "researchers", actor="researcher")
    mine = lab.development.get(lab.cid, own["outcome"]["workspace_id"])
    assert (mine["wall_seconds"], mine["consent"], mine["opened_by"]) == (1200, None, {"actor": "researcher"})


def test_a_delivery_without_methods_is_refused_except_from_an_evaluators_box(lab):
    record = lab.development.get(lab.cid, commission(lab)["outcome"]["workspace_id"])
    lab.development.sync(lab.cid)
    with pytest.raises(StopIteration):
        lab.deliver(record, {"oven_trays/objective.py": OBJECTIVE}, {**REPORT, "methods": []})
    [refused] = [event for event in lab.development.workspace_events(record) if event["type"] == "bridge_error"]
    assert "report.methods: name each method the library registers" in refused["payload"]["error"]


def test_a_failed_headless_run_tells_whoever_commissioned_it(lab):
    """Nobody attaches to a commission's box: a run of the coding agent that fails reaches the implementation lead as a notice
    that continues its request, once."""
    record = lab.development.get(lab.cid, commission(lab)["outcome"]["workspace_id"])
    lab.development.sync(lab.cid)
    failure = {"type": "harness_error", "payload": {"harness": "pi", "exit_code": 1, "signal": None, "error": "No API key for the provider"}}
    (lab.box.root(record) / "outgoing/events" / "failed.json").write_text(json.dumps(failure))
    lab.development.sync(lab.cid)
    lab.development.sync(lab.cid)
    told = [run for run in lab.workspace.store.list("agent_run", lab.cid) if run["agent_id"] == lab.lead["id"] and run["id"].startswith("pi_development_")]
    assert len(told) == 1 and "headless run failed: No API key for the provider" in told[0]["input"]
    assert told[0]["origin"]["root"] == ROOT


def test_a_commission_that_cannot_open_a_box_is_refused_with_what_to_do_instead(lab, monkeypatch):
    """Since roadmap H8 a coding box is the only place a commission builds code: one that cannot open a box is refused with the
    text that says what to do instead (turn coding workspaces on, deliver the code you have as a library or give it to a workspace
    as reference code, attach a validated evaluator), and nothing reserves an implementation service job for it."""
    from optimization_framework.agents.development_commission import PACKAGE, UNDECLARED, declared, refusal
    store = lab.workspace.store
    package = {"contract": "optimizer_v1", "entrypoint": "optimizer:create_optimizer",
               "files": [{"path": "optimizer.py", "content": "def create_optimizer(context):\n    raise NotImplementedError\n"}]}
    assert refusal(lab.workspace, "implementation.commission", {"hypothesis_id": "hypothesis_dev"}) is None
    assert refusal(lab.workspace, "implementation.commission", {"package": package}) == PACKAGE
    with pytest.raises(ValueError) as imported:
        commission(lab, "imported", package=package, ticket=None)
    assert str(imported.value) == PACKAGE
    # With coding workspaces off, a commission is refused with the switch that turns them on.
    monkeypatch.setenv("GRATING_DEVELOPMENT_ENABLED", "false")
    with pytest.raises(ValueError) as off:
        commission(lab, "off", compute_seconds=300)
    assert str(off.value) == lab.development.disabled() and "GRATING_DEVELOPMENT_ENABLED=true" in str(off.value)
    # An evaluator is built only for a task whose problem the campaign's charter declares.
    monkeypatch.setenv("GRATING_DEVELOPMENT_ENABLED", "true")
    task = declared_task(lab)
    assert declared(lab.workspace, task["id"])["id"] == task["id"]
    spec = evaluator_spec(lab, task)
    store.put("task", {**task, "evaluator_manifest": {**task["evaluator_manifest"], "id": "another_problem"}})
    assert declared(lab.workspace, task["id"]) is None
    with pytest.raises(ValueError) as undeclared:
        lab.command("evaluator.commission", {"task_id": task["id"], "spec": spec, "compute_seconds": 600}, "undeclared")
    assert str(undeclared.value) == UNDECLARED
    assert store.list("implementation_grant", lab.cid) == [] and store.list("development_workspace", lab.cid) == []
    assert lab.service.jobs == {} and not [row for row in store.list("outbox", lab.cid) if row["kind"] == "implementation_submit"]
    assert lab.consent()["used_seconds"] == 0   # a refused command charges nothing


def test_old_implementation_jobs_stay_readable(lab):
    """A job the service ran before H7 (or H8) is neither migrated nor hidden: its grant still answers the proposal's readiness, reads as
    evidence, and is exported with the campaign; a commission's box beside it leaves it as it was."""
    from balsamic.api.campaigns import export_markdown
    from optimization_framework.agents.tools import PiTools
    store = lab.workspace.store
    old = store.put("implementation_grant", {"id": "grant_before_h7", "campaign_id": lab.cid, "hypothesis_id": "hypothesis_dev",
        "status": "building", "job_id": "implementation_job_before_h7", "created_at": "2026-10-20T10:00:00+00:00", "usage": {"calls": 3},
        "compute_seconds": 120, "request": {"compute_seconds": 600, "api_budget_usd": 0, "spec": {"name": "Old search"}}})
    before = json.dumps(old, sort_keys=True)
    readiness = lab.workspace.implementations.readiness(store.get("hypothesis_dev", "hypothesis"))
    assert (readiness["state"], readiness["grant_id"], readiness["job_id"]) == ("building", old["id"], "implementation_job_before_h7")
    commission(lab)
    assert json.dumps(store.get(old["id"], "implementation_grant"), sort_keys=True) == before
    assert PiTools(lab.workspace.pi).record(lab.lead, old["id"])["job_id"] == "implementation_job_before_h7"
    assert "implementation_job_before_h7" in export_markdown(lab.workspace, store.get(lab.cid, "campaign"))
    assert lab.workspace.implementations.compute_committed(lab.cid) == 600 + 900   # the old job's and the box's, each once
