"""A coding workspace starts from the library generated from its campaign's charter (roadmap F4): the scaffold is written
once into the worktree, the brief lists every proposal the workspace serves with the METHODS key for each, and the
install refuses a library whose charter data was edited and lists the other generated files the agent changed
(decision 9)."""
import hashlib
import json

import pytest

from optimization_framework.agents.development import DEVELOPMENT_INSTRUCTIONS, DevelopmentWorkspaces, method_keys
from optimization_framework.agents.development_runtime import references_note, write_library, write_ticket
from optimization_framework.agents.library_install import Installer
from optimization_framework.problem_charter.scaffold import scaffold
from test_library_install import PYPROJECT, Plugins, Problems, git, passing
from test_pi_development_workspaces import Driver, setup  # noqa: F401  (the fixture)
from test_problem_charter_scaffold import METHODS, OBJECTIVE, ovens

LIBRARY = "libraries/oven_trays"
# DEVELOPMENT_INSTRUCTIONS at cc0e693: the size this part shrinks it from.
BEFORE_WORDS, BEFORE_CHARACTERS = 524, 3781


class LibraryDriver(Driver):
    """The fake driver, with the worktree a directory of its own; the library is written as the Docker driver writes it."""

    def __init__(self, root):
        super().__init__(root)
        self.libraries = []

    def prepare(self, record, brief, evidence, library=None, ticket=None, references=()):
        super().prepare(record, brief, evidence)
        self.libraries.append(library)
        hashes = write_library(self.repo(record), library) if library else None
        write_ticket(self.repo(record), ticket)
        return hashes


@pytest.fixture
def charter_lab(setup):  # noqa: F811
    """The development campaign, made from a confirmed charter revision (the ovens), with a second proposal."""
    workspace, campaign, _, fake = setup
    record = workspace.charters.create(ovens(), source={"kind": "test"})
    workspace.store.put("campaign", {**workspace.store.get(campaign["id"], "campaign"),
                                     "charter": {"id": record["id"], "revision": record["revision"]}})
    workspace.store.put("hypothesis", {"id": "hypothesis_greedy", "campaign_id": campaign["id"], "title": "Greedy trays",
                                       "status": "proposed", "mechanism": "Each tray takes the setting nearest the target",
                                       "algorithm": "custom", "algorithm_config": {}})
    driver = LibraryDriver(fake.directory.parent / "library-development")
    development = DevelopmentWorkspaces(workspace.pi, driver=driver)
    workspace.pi.development = development
    return workspace, campaign["id"], development, driver, record


def opened(development, cid, **values):
    return development.create(cid, {"hypothesis_id": "hypothesis_dev", "objective": "Implement these methods",
                                    "evidence_ids": [], "request_key": "f4", **values})


def test_the_workspace_starts_from_the_generated_library_and_a_recovery_keeps_what_the_agent_changed(charter_lab):
    workspace, cid, development, driver, charter = charter_lab
    record = opened(development, cid)
    development.sync(cid)
    repo = driver.repo(record)
    generated = scaffold(ovens(), charter["revision"], charter_id=charter["id"], balsamic=True)
    assert {path: (repo / LIBRARY / path).read_bytes() for path in generated} == generated
    saved = development.get(cid, record["id"])["library"]
    assert saved == {"name": "oven_trays", "package": "oven_trays", "charter_id": charter["id"], "revision": charter["revision"],
                     "fixed": [f"{LIBRARY}/charter.json", f"{LIBRARY}/oven_trays/data.py"],
                     "files": {f"{LIBRARY}/{path}": hashlib.sha256(content).hexdigest() for path, content in generated.items()}}
    assert json.loads((driver.root(record) / "prepared.json").read_text())["library"] == saved

    # The workspace is prepared again (its prepared.json was lost): a file the agent changed is kept, a removed one returns.
    harness = repo / LIBRARY / "oven_trays/harness.py"
    harness.write_text("# the agent's harness\n")
    (repo / LIBRARY / "README.md").unlink()
    (driver.root(record) / "prepared.json").unlink()
    development.sync(cid)
    assert driver.prepared == 2
    assert harness.read_text() == "# the agent's harness\n" and (repo / LIBRARY / "README.md").read_bytes() == generated["README.md"]
    assert development.get(cid, record["id"])["library"] == saved   # the hashes are the generated files', not the edits'


def test_the_brief_lists_every_served_proposal_with_its_methods_key_and_the_charters_summary(charter_lab):
    # Since H4 the brief is the work ticket's TASK.md and its house rules (AGENTS.md); .campaign/assignment.md keeps the session's rules.
    workspace, cid, development, driver, _ = charter_lab
    record = opened(development, cid, hypothesis_ids=["hypothesis_greedy"])
    development.sync(cid)
    task, rules = ((driver.repo(record) / name).read_text() for name in ("TASK.md", "AGENTS.md"))
    assert "Oven tray temperatures. Set each of 4 trays to a listed temperature, as close to 180 C as the heater allows." in task
    assert "Objective: minimize squared_gap (C^2)." in task and "`libraries/oven_trays/`" in task
    assert '### Test method (`hypothesis_dev`)\n\nIts METHODS key: `test_method` with `"hypothesis_id": "hypothesis_dev"`.\n\n' \
           "A test implementation" in task
    assert '### Greedy trays (`hypothesis_greedy`)\n\nIts METHODS key: `greedy_trays` with `"hypothesis_id": "hypothesis_greedy"`.\n\n' \
           "Each tray takes the setting nearest the target" in task
    assert "python -m pytest libraries/oven_trays" in task + rules and "libraries/<name>" not in task + rules
    # The generic brief names no grating library, reference repository or paper.
    brief = task + rules + (driver.root(record) / "brief.md").read_text()
    assert not {"grating", "flrl", "paper"} & set(brief.lower().replace("`", " ").replace("/", " ").split())


def test_a_campaign_without_a_charter_gets_no_library_and_a_charter_without_an_evaluator_says_why(charter_lab):
    workspace, cid, development, driver, charter = charter_lab
    workspace.store.put("campaign", {k: v for k, v in workspace.store.get(cid, "campaign").items() if k != "charter"})
    record = opened(development, cid)
    development.sync(cid)
    assert driver.libraries == [None] and "library" not in development.get(cid, record["id"])
    brief = (driver.repo(record) / "TASK.md").read_text()
    assert "## The problem" not in brief and "METHODS key" not in brief and "### Test method (`hypothesis_dev`)" in brief

    revised = workspace.charters.create(ovens(evaluator=None), source={"kind": "test"})
    workspace.store.put("campaign", {**workspace.store.get(cid, "campaign"), "charter": {"id": revised["id"], "revision": revised["revision"]}})
    library, _, why = development.generated_library(record)
    assert library is None and "names no evaluator" in why
    from optimization_framework.agents.development_ticket import task
    assert "No library could be generated from it (The charter names no evaluator" in task(development.ticket(record))


def test_method_keys_are_method_ids_unique_among_the_proposals():
    keys = method_keys([{"id": "a", "title": "Greedy trays"}, {"id": "b", "short_title": "Greedy  trays!"},
                        {"id": "c", "title": "2-opt swaps"}, {"id": "d", "title": "Ünïcode"}])
    assert keys == {"a": "greedy_trays", "b": "greedy_trays_2", "c": "method_2_opt_swaps", "d": "n_code"}


def test_references_are_named_only_when_the_workspace_holds_them(tmp_path):
    assert references_note(tmp_path / "missing") == "" and references_note(tmp_path) == ""
    (tmp_path / "flrl").mkdir()
    (tmp_path / "flrl.commit").write_text("abc")
    (tmp_path / "paper.pdf").write_bytes(b"%PDF")
    assert references_note(tmp_path) == "\n\n## References\n\n- `/references/flrl`\n- `/references/paper.pdf`\n"


def test_the_instructions_are_shorter_than_before_and_name_no_grating_library():
    # The steps (objective.py, methods.py, the tests, campaign_submit, the version) moved to the work ticket's house rules in H4;
    # tests/test_development_ticket.py checks them there.
    assert len(DEVELOPMENT_INSTRUCTIONS.split()) < BEFORE_WORDS and len(DEVELOPMENT_INSTRUCTIONS) < BEFORE_CHARACTERS
    for gone in ("grating-mask-search", "/references/flrl", "paper.pdf"):
        assert gone not in DEVELOPMENT_INSTRUCTIONS


# The install (decision 9) ------------------------------------------------------------------------------------------------
@pytest.fixture
def delivered(tmp_path):
    """A workspace that started from the ovens' library, and a function to commit and submit its library."""
    from optimization_framework.contracts.requests import CampaignInput, TaskInput
    from optimization_framework.execution.service import Workspace
    workspace = Workspace(tmp_path / "workspace")
    campaign = workspace.create_campaign(CampaignInput(name="Ovens", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    development = DevelopmentWorkspaces(workspace.pi, driver=Driver(tmp_path / "development"))
    generated = scaffold(ovens(), 1, charter_id="problem_charter_ovens", balsamic=True)
    source = tmp_path / "source"
    hashes = write_library(source, {"name": "oven_trays", "files": generated})
    record = {"id": "development_ovens", "campaign_id": campaign["id"], "hypothesis_id": "hypothesis_dev", "title": "Ovens",
              "status": "idle", "desired_status": "running", "created_at": "2026-10-27T13:00:00+00:00", "cursor": 0, "usage": {},
              "library": {"name": "oven_trays", "package": "oven_trays", "charter_id": "problem_charter_ovens", "revision": 1,
                          "fixed": [f"{LIBRARY}/charter.json", f"{LIBRARY}/oven_trays/data.py"], "files": hashes}}
    workspace.store.put("development_workspace", record)
    root = tmp_path / "lab"
    (root / "libraries").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "uv.lock").write_text("lock v1\n")

    def deliver(changes, number=1):
        """Commit the library with the objective and methods filled and `changes` ({path in the library: text}), submit it."""
        for path, text in {"oven_trays/objective.py": OBJECTIVE, "oven_trays/methods.py": METHODS, **changes}.items():
            (source / LIBRARY / path).write_text(text)
        if not (source / ".git").exists():
            git("init", "-q", cwd=source)
        git("add", ".", cwd=source)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"delivery {number}", cwd=source)
        store = development.driver.root(record) / "work" / "git"
        if store.exists():
            git("--git-dir", str(store), "fetch", "-q", str(source), "+HEAD:refs/heads/main", cwd=tmp_path)
        else:
            store.parent.mkdir(parents=True)
            git("clone", "-q", "--bare", str(source), str(store), cwd=tmp_path)
        files = sorted(str(path.relative_to(source)) for path in (source / LIBRARY).rglob("*") if path.is_file())
        report = {"verdict": "ready", "summary": "s", "tests": {"passed": 21, "failed": 0, "skipped": 0, "command": ""},
                  "limitations": [], "next_actions": [],
                  "methods": [{"method_id": m, "hypothesis_id": "hypothesis_dev", "state": "implemented", "conformance": "passed"}
                              for m in ("random_search", "all_middle", "all_cold")]}
        return workspace.store.put("development_submission", {"id": f"development_submission_{number}", "campaign_id": campaign["id"],
            "workspace_id": record["id"], "hypothesis_id": "hypothesis_dev", "commit": git("rev-parse", "HEAD", cwd=source),
            "status": "submitted", "report": report, "manifest": {"files": files},
            "package": {"files": [{"path": path, "content": (source / path).read_text()} for path in files]},
            "created_at": "2026-10-27T13:10:00+00:00"})

    plugins = Plugins()
    def runner(args, cwd, timeout=600):
        if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
            plugins.synced = True
        return 0, " Would make no changes\n" if "--dry-run" in args else "ok"
    # The validator is stubbed here: these tests change generated files in ways the library's own tests refuse.
    installer = Installer(workspace, development, root, runner=runner, uv="uv", plugins=plugins,
                          problems=Problems(plugins, ("oven_trays",)), providers=lambda group: {}, validator=passing)
    return workspace, campaign["id"], record, installer, deliver, root


def test_the_install_lists_the_generated_files_the_agent_changed(delivered):
    workspace, cid, record, installer, deliver, root = delivered
    submission = deliver({"oven_trays/harness.py": "# the agent's own harness\n"})
    install = installer.request(cid, record["id"], submission["id"], request_key="one", background=False)
    assert install["status"] == "installed" and install["package"] == "oven-trays"
    # The objective and the methods are the agent's to write; any other generated file it changed is listed.
    assert install["changed_generated_files"] == [f"{LIBRARY}/oven_trays/harness.py"]
    assert (root / LIBRARY / "oven_trays/harness.py").read_text() == "# the agent's own harness\n"


@pytest.mark.parametrize("fixed", ["oven_trays/data.py", "charter.json"])
def test_the_install_refuses_a_library_whose_charter_data_was_edited(delivered, fixed):
    workspace, cid, record, installer, deliver, root = delivered
    submission = deliver({fixed: "TITLE = 'Another problem'\n"})
    with pytest.raises(ValueError, match=f"The library's data no longer matches the charter revision: {LIBRARY}/{fixed} differs"):
        installer.request(cid, record["id"], submission["id"], request_key="one", background=False)
    assert not (root / LIBRARY).exists() and (root / "pyproject.toml").read_text() == PYPROJECT
    # Balsamic's own install records the refusal and tells the agent what to do.
    failed = installer.automatic(cid, record["id"], submission, background=False)
    assert failed["status"] == "failed" and "no longer matches the charter revision" in failed["error"]


def test_a_library_the_workspace_did_not_generate_is_not_compared(delivered):
    workspace, cid, record, installer, deliver, root = delivered
    workspace.store.put("development_workspace", {**record, "library": {**record["library"], "name": "other"}})
    submission = deliver({"oven_trays/data.py": "TITLE = 'Another problem'\n"})
    install = installer.request(cid, record["id"], submission["id"], request_key="one", background=False)
    assert install["status"] == "installed" and install["changed_generated_files"] == []


def test_the_library_is_written_only_where_a_file_is_absent_and_hashed_as_generated(tmp_path):
    files = {"a.py": b"generated\n", "b/c.py": b"also\n"}
    (tmp_path / "libraries/x").mkdir(parents=True)
    (tmp_path / "libraries/x/a.py").write_text("edited\n")
    hashes = write_library(tmp_path, {"name": "x", "files": files})
    assert hashes == {"libraries/x/a.py": hashlib.sha256(b"generated\n").hexdigest(),
                      "libraries/x/b/c.py": hashlib.sha256(b"also\n").hexdigest()}
    assert (tmp_path / "libraries/x/a.py").read_text() == "edited\n" and (tmp_path / "libraries/x/b/c.py").read_bytes() == b"also\n"
