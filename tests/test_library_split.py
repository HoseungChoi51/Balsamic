"""Method libraries split off when a second problem needs them (roadmap L6, decision 26): binding or running a problem library's
method on a problem it does not provide records a split and tells the lead once; a split workspace starts from the problem
library's latest version and its ticket asks for a method library and the problem library's next version; the two are installed
as one step, the method library takes over the methods the split names and no others, and the Packages page shows which depends
on which. uv is faked as in tests/test_library_install.py; Git is real."""
import tempfile
from pathlib import Path

import pytest

from optimization_framework.agents import library_install, library_repository as repositories, library_split
from optimization_framework.agents.library_install import Installer
from optimization_framework.campaigns import method_catalog
from optimization_framework.contracts.base import content_hash
from optimization_framework.implementations.builtin import bind
from optimization_framework.optimizers import plugins

from test_development_generated_library import LIBRARY, charter_lab, opened   # noqa: F401  (the fixture)
from test_library_base import install_version
from test_library_install import LIBRARY as BAKERY, Problems, git, lab   # noqa: F401  (the fixture)
from test_library_keep import OLD, other   # noqa: F401  (the fixture)
from test_pi_development_workspaces import setup   # noqa: F401  (the fixture)

SPLIT_ID = "library_split_test"
METHODS_TOML = ('[project]\nname = "bakery-search-methods"\nversion = "0.1.0"\n\n'
                '[project.entry-points."optimization_framework.optimizers"]\nbakery_methods = "bakery_methods.plugin:Plugin"\n')
PROBLEM_TOML = ('[project]\nname = "bakery-search"\nversion = "0.3.0"\ndependencies = ["bakery-search-methods==0.1.0"]\n\n'
                '[project.entry-points."optimization_framework.optimizers"]\nbakery = "bakery.plugin:Plugin"\n')


# Binding on a second problem -------------------------------------------------------------------------------------------------
@pytest.fixture
def library_method(setup, monkeypatch):
    """coordinate, as if it came from bakery-search 0.2.0, a problem library providing baking_order (the campaign's task is on
    bounded_continuous), whose versions the lab records."""
    workspace, campaign, development, driver = setup
    origin = plugins.installed.origin
    monkeypatch.setattr(plugins.installed, "origin", lambda method_id: {"entry_point": "bakery", "distribution": "bakery-search",
        "version": "0.2.0", "own": False} if method_id == "coordinate" else origin(method_id))
    real = library_install.providers
    monkeypatch.setattr(library_install, "providers", lambda group: {**real(group), "baking_order": "bakery-search"}
                        if group == library_install.PROBLEMS else real(group))
    repositories.record(workspace.store, "bakery", "bakery-search", "0.2.0", "0" * 40, source={}, methods=["coordinate"], problems=["baking_order"])
    told = []
    monkeypatch.setattr(workspace.pi, "enqueue", lambda agent, identity, text, **options: told.append((agent["role"], text)))
    workspace.store.put("hypothesis", {"id": "H1", "campaign_id": campaign["id"], "title": "H1", "status": "proposed", "mechanism": "m",
                                       "rationale": "r", "parent_ids": [], "algorithm": "coordinate", "algorithm_config": {}, "algorithm_chosen": True})
    return workspace, campaign["id"], told


def binding(workspace, cid, key):
    task = workspace.current_tasks(cid)[0]
    hypothesis = workspace.store.get("H1", "hypothesis")
    return bind(workspace, cid, {"hypothesis_id": "H1", "task_id": task["id"], "algorithm": "coordinate", "parameters": {},
                                 "expected_algorithm": hypothesis["algorithm"], "expected_configuration_hash": content_hash(hypothesis["algorithm_config"]),
                                 "reason": "reuse it"}, key)


def test_binding_a_problem_librarys_method_on_another_problem_records_a_split_and_tells_the_lead_once(library_method):
    workspace, cid, told = library_method
    binding(workspace, cid, "one")
    [split] = library_split.splits(workspace.store)
    assert (split["status"], split["methods"], split["library"], split["package"], split["method_library"]) == (
        "needed", ["coordinate"], "bakery", "bakery-search", "bakery-methods")
    assert split["problems"] == ["baking_order", "bounded_continuous"] and split["needed_by"][0]["campaign_id"] == cid
    [(role, text)] = told
    assert role == "lead" and "coordinate of package bakery-search now runs on problem bounded_continuous, a second problem besides baking_order" in text
    assert f"implementation_workspace_create, split {split['id']}" in text
    # The method list shows it as the next step; a run of it on the same problem tells nobody again.
    row = next(row for row in method_catalog.catalog(workspace, cid)["methods"] if row["id"] == "coordinate")
    assert row["split"]["id"] == split["id"] and row["next_action"]["text"].startswith("Split it into the method package libraries/bakery-methods/")
    library_split.noticed(workspace, cid, "coordinate", workspace.current_tasks(cid)[0], via="trial_x")
    assert len(told) == 1 and len(library_split.splits(workspace.store)) == 1
    # A method on its own library's problem, or one bundled with Balsamic, needs no split.
    assert library_split.needed(workspace, cid, "coordinate", "baking_order", via="x") is None
    assert library_split.needed(workspace, cid, "random", "bounded_continuous", via="x") is None


# The split workspace -----------------------------------------------------------------------------------------------------------
def test_a_split_workspace_starts_from_the_problem_library_and_asks_for_both_libraries(charter_lab):
    workspace, cid, development, driver, charter = charter_lab
    files = install_version(workspace, charter, "0.2.0")
    workspace.store.put("library_split", {"id": SPLIT_ID, "status": "needed", "methods": ["random_search"], "library": "oven_trays",
        "package": "oven-trays", "version": "0.2.0", "method_library": "oven_trays-methods", "problems": ["bounded_continuous", "oven_trays"],
        "library_problems": ["oven_trays"], "needed_by": [], "created_at": "2026-10-28T00:00:00Z"})
    record = opened(development, cid, split=SPLIT_ID)
    assert record["id"] != opened(development, cid, request_key="other")["id"]   # not the proposal's ordinary workspace
    assert workspace.store.get(SPLIT_ID, "library_split")["status"] == "building"
    with pytest.raises(ValueError, match=f"The split {SPLIT_ID} is building in workspace {record['id']}"):
        opened(development, cid, split=SPLIT_ID, request_key="again", hypothesis_id="hypothesis_greedy")
    development.sync(cid)
    repo = driver.repo(record)
    assert {path: (repo / LIBRARY / path).read_bytes() for path in files} == files
    task = (repo / "TASK.md").read_text()
    assert "## The split" in task and "`random_search` of oven-trays now runs on 2 problems (`bounded_continuous`, `oven_trays`)" in task
    assert "1. `libraries/oven_trays-methods/`: a new library" in task and "provides `random_search` and no problem" in task
    assert "2. `libraries/oven_trays/`: the next version of oven-trays without `random_search`" in task
    ticket = development.ticket_of(development.get(cid, record["id"]))
    assert ticket["split"]["id"] == SPLIT_ID and ticket["test_command"].endswith("libraries/oven_trays libraries/oven_trays-methods")
    assert development.get(cid, record["id"])["library"]["base"]["version"] == "0.2.0"


# Installing a split --------------------------------------------------------------------------------------------------------------
class Moving:
    """The lab's plug-ins: bakery-search provides bakery_dp and bakery_greedy; after uv sync, bakery_greedy comes from
    bakery-search-methods."""
    def __init__(self):
        self.synced = False

    def methods(self):
        return [{"id": "random"}, {"id": "bakery_dp"}, {"id": "bakery_greedy"}]

    def origin(self, method_id):
        if method_id == "random":
            return None
        return {"distribution": "bakery-search-methods" if self.synced and method_id == "bakery_greedy" else "bakery-search"}


def validating(by_library, calls):
    """Validation outside the box listing, for each library, its methods."""
    def validate(files, name, instances=(), protected=None, **extra):
        calls.append((name, sorted({path.split("/")[1] for path in extra.get("dependencies") or {}})))
        return {"tests": {"passed": 1, "failed": 0, "skipped": 0, "results": []}, "protected": None, "seconds": 0.1,
                "methods": [{"method_id": method, "check": "check", "problem_id": "bounded_continuous", "conformance": "passed"}
                            for method in by_library[name]]}
    return validate


@pytest.fixture
def splitting(lab, other):
    """bakery-search 0.1.0 installed with bakery_dp and bakery_greedy (which another campaign ran); a split workspace delivers
    bakery-methods 0.1.0 with bakery_greedy and bakery 0.3.0 without it."""
    workspace, cid, development, root, submission = lab
    (root / "libraries/bakery/src/bakery").mkdir(parents=True)
    (root / "libraries/bakery/pyproject.toml").write_text(OLD)
    (root / "libraries/bakery/src/bakery/plugin.py").write_text("class Plugin: 'version 0.1.0'\n")
    workspace.store.put("library_split", {"id": SPLIT_ID, "status": "building", "methods": ["bakery_greedy"], "library": "bakery",
        "package": "bakery-search", "version": "0.1.0", "method_library": "bakery-methods", "problems": ["baking_order", "bounded_continuous"],
        "library_problems": ["baking_order"], "needed_by": [], "workspace_id": "development_bakery", "created_at": "2026-10-28T00:00:00Z"})
    record = workspace.store.get("development_bakery", "development_workspace")
    workspace.store.put("development_workspace", {**record, "split": {"id": SPLIT_ID, "library": "bakery", "package": "bakery-search",
                                                                     "method_library": "bakery-methods", "methods": ["bakery_greedy"]}})
    plugins, commands = Moving(), []
    def runner(args, cwd, timeout=600):
        commands.append(args[1:])
        if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
            plugins.synced = True
            return 0, "Installed 2 packages"
        return 0, " Would make no changes\n" if "--dry-run" in args else "Resolved 4 packages"
    def make(by_library, problem_toml=PROBLEM_TOML, calls=None):
        files = {**BAKERY, "libraries/bakery/pyproject.toml": problem_toml,
                 "libraries/bakery-methods/pyproject.toml": METHODS_TOML, "libraries/bakery-methods/src/bakery_methods/plugin.py": "class Plugin: pass\n"}
        submitted = commit(lab, files, by_library)
        installer = Installer(workspace, development, root, runner=runner, uv="uv", plugins=plugins, problems=Problems(plugins),
                              providers=lambda group: {"baking_order": "bakery-search"} if group == library_install.PROBLEMS else {},
                              validator=validating(by_library, calls if calls is not None else []))
        return installer, submitted
    return make, commands


def commit(lab, files, by_library):
    """The split workspace's delivery: both libraries at a new commit in its Git store."""
    workspace, cid, development, root, submission = lab
    store = development.driver.root({"id": "development_bakery"}) / "work" / "git"
    source = Path(tempfile.mkdtemp(dir=store.parent)) / "edit"
    git("clone", "-q", str(store), str(source), cwd=store.parent)
    for path, content in files.items():
        (source / path).parent.mkdir(parents=True, exist_ok=True)
        (source / path).write_text(content)
    git("add", ".", cwd=source)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "split", cwd=source)
    git("push", "-q", "origin", "HEAD", cwd=source)
    methods = [{"method_id": method, "hypothesis_id": "hypothesis_dp", "state": "implemented", "conformance": "passed"}
               for name in sorted(by_library) for method in by_library[name]]
    return workspace.store.put("development_submission", {**submission, "id": "development_submission_split", "commit": git("rev-parse", "HEAD", cwd=source),
        "report": {**submission["report"], "methods": methods}, "manifest": {"files": sorted(files)},
        "package": {"files": [{"path": path, "content": content} for path, content in files.items()]}})


def test_a_split_installs_both_libraries_at_once_and_the_method_moves(lab, splitting):
    workspace, cid, development, root, submission = lab
    make, commands = splitting
    calls = []
    installer, submitted = make({"bakery-methods": ["bakery_greedy"], "bakery": ["bakery_dp"]}, calls=calls)
    record = installer.request(cid, "development_bakery", submitted["id"], request_key="split", background=False)
    assert record["status"] == "installed", record.get("error")
    # The method library first; the problem library with it importable beside it.
    assert calls == [("bakery-methods", []), ("bakery", ["bakery-methods"])]
    assert record["methods_moved"] == ["bakery_greedy"] and record["methods_kept"] == ["bakery_dp", "bakery_greedy"] and record["methods_removed"] == []
    assert record["method_library"]["package"] == "bakery-search-methods" and record["method_library"]["methods"] == ["bakery_greedy"]
    assert commands == [["lock"], ["sync", "--dry-run", "--inexact", "--extra", "libraries"], ["sync", "--inexact", "--extra", "libraries"]]
    pins = (root / "pyproject.toml").read_text()
    assert '"bakery-search-methods==0.1.0", "bakery-search==0.3.0"' in pins and 'bakery-search-methods = { path = "libraries/bakery-methods", editable = true }' in pins
    assert (root / "libraries/bakery-methods/src/bakery_methods/plugin.py").exists() and (root / "libraries/bakery/pyproject.toml").read_text() == PROBLEM_TOML
    methods_version, problem_version = repositories.latest(workspace.store, "bakery-methods"), repositories.latest(workspace.store, "bakery")
    assert methods_version["methods"] == ["bakery_greedy"] and methods_version["problems"] == []
    assert problem_version["version"] == "0.3.0" and problem_version["methods"] == ["bakery_dp"]
    assert problem_version["depends_on"] == ["bakery-search-methods"] and problem_version["moved"] == {"package": "bakery-search-methods", "methods": ["bakery_greedy"]}
    assert workspace.store.get(SPLIT_ID, "library_split")["status"] == "done"
    # The Packages page: a method package, and the problem package that depends on it.
    listed = {row["name"]: row for row in repositories.catalog(workspace.store)["libraries"]}
    assert listed["bakery-methods"]["kind"] == "method" and listed["bakery-methods"]["used_by"] == ["bakery-search"]
    assert listed["bakery"]["depends_on"] == ["bakery-search-methods"]
    assert repositories.detail(workspace.store, "bakery-methods")["used_by"] == ["bakery-search"]


def test_a_method_library_that_takes_over_a_method_the_split_does_not_name_is_refused(lab, splitting):
    workspace, cid, development, root, submission = lab
    make, commands = splitting
    installer, submitted = make({"bakery-methods": ["bakery_greedy", "bakery_dp"], "bakery": []})
    record = installer.request(cid, "development_bakery", submitted["id"], request_key="split", background=False)
    assert record["status"] == "failed" and commands == []
    assert "The method library takes over bakery_dp from bakery-search, which the split does not move" in record["error"]
    assert (root / "libraries/bakery/pyproject.toml").read_text() == OLD and not (root / "libraries/bakery-methods").exists()
    assert workspace.store.get(SPLIT_ID, "library_split")["status"] == "building"


def test_a_problem_library_that_does_not_depend_on_the_method_library_is_refused(lab, splitting):
    workspace, cid, development, root, submission = lab
    make, commands = splitting
    installer, submitted = make({"bakery-methods": ["bakery_greedy"], "bakery": ["bakery_dp"]},
                                problem_toml=PROBLEM_TOML.replace('dependencies = ["bakery-search-methods==0.1.0"]\n', ""))
    record = installer.request(cid, "development_bakery", submitted["id"], request_key="split", background=False)
    assert record["status"] == "failed" and "bakery-search 0.3.0 does not depend on bakery-search-methods" in record["error"]


def test_a_split_delivering_one_library_is_refused(lab, splitting):
    workspace, cid, development, root, submission = lab
    make, commands = splitting
    installer, _ = make({"bakery-methods": ["bakery_greedy"], "bakery": ["bakery_dp"]})
    with pytest.raises(ValueError, match="A split delivers libraries/bakery-methods/ and libraries/bakery/ in one commit; this one delivers libraries/bakery/"):
        installer.request(cid, "development_bakery", submission["id"], request_key="one", background=False)
