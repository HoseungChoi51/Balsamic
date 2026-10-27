"""The researcher installs a coding workspace's library with one click: the exact submitted commit's libraries/<name>/ is
copied from the workspace's Git store, checked against the submission, pinned and installed; a change to installed packages
waits for their confirmation, and a failure leaves the lab as it was. uv is faked here; Git is real."""
import functools
from pathlib import Path
import subprocess
import tempfile

import pytest

from optimization_framework.agents.development import DevelopmentWorkspaces
from optimization_framework.agents import development_runtime
from optimization_framework.agents.library_install import Installer, changed_packages, lab_projects
from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace

PYPROJECT = """[project]
name = "lab"
version = "1.0"

[project.optional-dependencies]
dev = ["pytest"]
libraries = ["grating-mask-search==0.1.2"]

[tool.uv.sources]
grating-mask-search = { path = "libraries/grating-mask-search", editable = true }

[tool.other]
x = 1
"""
LIBRARY = {
    "libraries/bakery/pyproject.toml": '[project]\nname = "bakery-search"\nversion = "0.2.0"\n\n'
                                       '[project.entry-points."optimization_framework.optimizers"]\nbakery = "bakery.plugin:Plugin"\n',
    "libraries/bakery/src/bakery/plugin.py": "class Plugin: pass\n",
}

# uv 0.11's own dry-run lines (`uv sync --dry-run --inexact --extra libraries`) in a lab laid out like this one, after the
# libraries extra gained a library: the lab's root project is reinstalled from the same path, and its version shows only on
# the line that removes it.
REINSTALL = """Would use project environment at: .venv
Resolved 5 packages in 3ms
Found up-to-date lockfile at: uv.lock
Would download 2 packages
Would uninstall 1 package
Would install 2 packages
 + bakery-search @ file:///srv/balsamic/libraries/bakery
 - lab==1.0 (from file:///srv/balsamic)
 + lab @ file:///srv/balsamic
"""
# The same, with another library of the lab's reinstalled and a package from the index upgraded.
UPGRADE = """Would use project environment at: .venv
Resolved 5 packages in 2ms
Found up-to-date lockfile at: uv.lock
Would download 3 packages
Would uninstall 4 packages
Would install 4 packages
 - bakery-search==0.2.0 (from file:///srv/balsamic/libraries/bakery)
 + bakery-search @ file:///srv/balsamic/libraries/bakery
 - lab==1.0 (from file:///srv/balsamic)
 + lab @ file:///srv/balsamic
 - other-search==0.3.0 (from file:///srv/balsamic/libraries/other)
 + other-search @ file:///srv/balsamic/libraries/other
 - six==1.16.0
 + six==1.17.0
"""


class Driver:
    def __init__(self, directory):
        self.directory = directory

    def root(self, record):
        return self.directory / record["id"]

    def name(self, record):
        return "grating-" + record["id"]


class Plugins:
    """The lab's plug-ins: the library's method appears once uv sync ran."""
    def __init__(self):
        self.synced = False

    def methods(self):
        return [{"id": "random"}] + ([{"id": "bakery_dp"}] if self.synced else [])


class Problems:
    """The lab's problem registry: a library's problems are listed once uv sync ran (refresh reads them at once)."""
    def __init__(self, plugins, provided=()):
        self.plugins, self.provided = plugins, list(provided)

    def ids(self):
        return ["bounded_continuous", *(self.provided if self.plugins.synced else [])]

    def refresh(self):
        return self.ids()


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    campaign = workspace.create_campaign(CampaignInput(name="Bakery", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    development = DevelopmentWorkspaces(workspace.pi, driver=Driver(tmp_path / "development"))
    record = {"id": "development_bakery", "campaign_id": campaign["id"], "hypothesis_id": "hypothesis_dp", "title": "Subset DP",
              "status": "idle", "desired_status": "running", "created_at": "2026-10-27T03:10:00+00:00", "cursor": 0, "usage": {}}
    workspace.store.put("development_workspace", record)
    # The coding agent's commit, in its workspace's own Git store.
    source = tmp_path / "source"
    for path, content in LIBRARY.items():
        (source / path).parent.mkdir(parents=True, exist_ok=True)
        (source / path).write_text(content)
    git("init", "-q", cwd=source)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base", cwd=source)
    git("add", ".", cwd=source)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "library", cwd=source)
    commit = git("rev-parse", "HEAD", cwd=source)
    store = development.driver.root(record) / "work" / "git"
    store.parent.mkdir(parents=True)
    git("clone", "-q", "--bare", str(source), str(store), cwd=tmp_path)
    root = tmp_path / "lab"
    (root / "libraries").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "uv.lock").write_text("lock v1\n")
    report = {"verdict": "ready_with_limits", "summary": "s", "tests": {"passed": 3, "failed": 0, "skipped": 0, "command": ""},
              "limitations": ["no evaluator"], "next_actions": [],
              "methods": [{"method_id": "bakery_dp", "hypothesis_id": "hypothesis_dp", "state": "implemented", "conformance": "passed"}]}
    submission = workspace.store.put("development_submission", {"id": "development_submission_1", "campaign_id": campaign["id"],
        "workspace_id": record["id"], "hypothesis_id": "hypothesis_dp", "commit": commit, "status": "submitted", "report": report,
        "package": {"files": [{"path": path, "content": content} for path, content in LIBRARY.items()]},
        "manifest": {"files": list(LIBRARY)}, "created_at": "2026-10-27T03:22:00+00:00"})
    return workspace, campaign["id"], development, root, submission


def passing(files, name, instances=(), protected=None):
    """Validation outside the box that the library passes (library_validation.run's result): the libraries here are fakes, so
    the real sandbox is tested on a real library in tests/test_library_validation.py."""
    return {"tests": {"passed": 3, "failed": 0, "skipped": 0, "results": []}, "protected": None, "methods": [], "seconds": 0.5}


def installer(lab, dry_run=" Would make no changes\n", sync_code=0, provided=(), installed=None, validator=passing):
    """installed: {group: {entry-point name: distribution}} of what other packages provide."""
    workspace, cid, development, root, submission = lab
    plugins, commands = Plugins(), []
    problems = Problems(plugins, provided)
    def runner(args, cwd, timeout=600):
        commands.append(args[1:])
        if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
            plugins.synced = sync_code == 0
            return sync_code, "Installed 1 package" if sync_code == 0 else "error: no matching distribution"
        return 0, dry_run if "--dry-run" in args else "Resolved 3 packages"
    return Installer(workspace, development, root, runner=runner, uv="uv", plugins=plugins, problems=problems,
                     providers=lambda group: (installed or {}).get(group, {}), validator=validator), commands


def request(lab, install, **options):
    workspace, cid, development, root, submission = lab
    return install.request(cid, "development_bakery", submission["id"], request_key=options.pop("key", "one"), background=False, **options)


def test_the_researcher_installs_the_exact_submitted_library_and_its_methods_appear(lab):
    workspace, cid, development, root, submission = lab
    install, commands = installer(lab)
    record = request(lab, install)
    assert record["status"] == "installed" and record["package"] == "bakery-search" and record["version"] == "0.2.0"
    assert record["methods_added"] == ["bakery_dp"] and record["missing_methods"] == [] and record["actor"] == "researcher"
    assert (root / "libraries/bakery/src/bakery/plugin.py").read_text() == "class Plugin: pass\n"
    text = (root / "pyproject.toml").read_text()
    assert 'libraries = ["grating-mask-search==0.1.2", "bakery-search==0.2.0"]' in text
    assert 'bakery-search = { path = "libraries/bakery", editable = true }\n\n[tool.other]' in text
    assert commands == [["lock"], ["sync", "--dry-run", "--inexact", "--extra", "libraries"], ["sync", "--inexact", "--extra", "libraries"]]
    assert development.public(workspace.store.get("development_bakery", "development_workspace"))["installs"][0]["id"] == record["id"]
    # The same request again is the same install.
    assert request(lab, install)["id"] == record["id"]


def test_a_change_to_installed_packages_waits_for_confirmation_and_leaves_the_lab_as_it_was(lab):
    workspace, cid, development, root, submission = lab
    install, _ = installer(lab, dry_run="Would uninstall 1 package\nWould install 2 packages\n - numpy==2.1.0\n + numpy==2.3.0\n + bakery-search==0.2.0\n")
    waiting = request(lab, install)
    assert waiting["status"] == "needs_confirmation" and waiting["changes"] == [{"name": "numpy", "from": "2.1.0", "to": "2.3.0"}]
    assert (root / "pyproject.toml").read_text() == PYPROJECT and not (root / "libraries/bakery").exists()
    confirmed = request(lab, install, key="two", confirm_changes=True)
    assert confirmed["status"] == "installed" and confirmed["changes"][0]["name"] == "numpy"


def test_a_failed_install_is_recorded_and_puts_everything_back(lab):
    workspace, cid, development, root, submission = lab
    install, _ = installer(lab, sync_code=1)
    failed = request(lab, install)
    assert failed["status"] == "failed" and "uv sync failed" in failed["error"] and "no matching distribution" in failed["log_tail"]
    assert (root / "pyproject.toml").read_text() == PYPROJECT and (root / "uv.lock").read_text() == "lock v1\n"
    assert not (root / "libraries/bakery").exists() and not list((root / "libraries").glob(".*"))


def test_what_cannot_be_installed_is_refused_before_anything_changes(lab):
    workspace, cid, development, root, submission = lab
    install, commands = installer(lab)
    workspace.store.put("development_submission", {**submission, "package": {"files": [{"path": "libraries/bakery/src/bakery/plugin.py", "content": "other"}]}})
    with pytest.raises(ValueError, match="differs from what was submitted"):
        request(lab, install)
    workspace.store.put("development_submission", {**submission, "report": {**submission["report"], "verdict": "not_ready"}})
    with pytest.raises(ValueError, match="not ready; confirm"):
        request(lab, install)
    assert request(lab, install, accept_not_ready=True)["status"] == "installed"
    workspace.store.put("development_submission", {**submission, "manifest": {"files": ["h12_optimizer.py"]}})
    with pytest.raises(ValueError, match="one libraries/<name>/"):
        request(lab, install)
    # The same version with other code would not reload in the running lab.
    workspace.store.put("development_submission", submission)
    (root / "libraries/bakery/src/bakery/plugin.py").write_text("class Plugin: changed = True\n")
    with pytest.raises(ValueError, match="raise the version"):
        request(lab, install, key="again")


def test_a_dry_run_names_only_other_packages_it_would_change():
    output = "Would install 3 packages\n - numpy==2.1.0\n + numpy==2.3.0\n + scipy==1.18.1\n + bakery-search==0.2.0\n - bakery_search==0.1.0\n"
    assert changed_packages(output, "bakery-search") == [{"name": "numpy", "from": "2.1.0", "to": "2.3.0"}]


def test_balsamic_installs_a_delivered_library_by_itself_once_and_records_what_stops_it(lab, monkeypatch):
    workspace, cid, development, root, submission = lab
    install, commands = installer(lab)
    done = install.automatic(cid, "development_bakery", submission, background=False)
    assert done["status"] == "installed" and done["actor"] == "balsamic" and done["methods_added"] == ["bakery_dp"]
    assert install.automatic(cid, "development_bakery", submission, background=False) is None   # once per delivery
    assert len([c for c in commands if c[0] == "sync" and "--dry-run" not in c]) == 1
    # Not a delivery its coding agent reports not ready, nor loose files.
    for changed in ({"report": {**submission["report"], "verdict": "not_ready"}}, {"manifest": {"files": ["h12_optimizer.py"]}}):
        assert installer(lab)[0].automatic(cid, "development_bakery", {**submission, "id": "other", **changed}, background=False) is None
    # A refusal is a failed install, told to the lead.
    workspace.store.put("development_submission", {**submission, "id": "development_submission_2",
        "package": {"files": [{"path": "libraries/bakery/src/bakery/plugin.py", "content": "other"}]}})
    refused = installer(lab)[0].automatic(cid, "development_bakery", workspace.store.get("development_submission_2", "development_submission"), background=False)
    assert refused["status"] == "failed" and "differs from what was submitted" in refused["error"] and refused["actor"] == "balsamic"


def test_the_workspaces_sync_installs_what_was_delivered_unless_turned_off(lab, monkeypatch):
    workspace, cid, development, root, submission = lab
    calls = []
    monkeypatch.setattr(Installer, "automatic", lambda self, campaign_id, workspace_id, row, background=True: calls.append(row["id"]))
    monkeypatch.setenv("GRATING_AUTO_INSTALL", "false")
    development.install_delivered(cid)
    assert calls == []
    monkeypatch.delenv("GRATING_AUTO_INSTALL")
    development.install_delivered(cid)
    assert calls == [submission["id"]]


def test_a_reinstall_and_the_labs_own_projects_are_no_change():
    assert changed_packages(REINSTALL, "bakery-search") == []
    assert changed_packages(UPGRADE, "bakery-search") == [{"name": "six", "from": "1.16.0", "to": "1.17.0"}]
    # The same version, or the same url, again is a reinstall; another version or url is a change.
    assert changed_packages(" - six==1.16.0\n + six==1.16.0\n ~ lab==1.0 (from file:///srv/balsamic)\n", "x") == []
    assert changed_packages(" - tool==1.0 (from file:///a)\n + tool @ file:///b\n", "x") == [{"name": "tool", "from": "1.0", "to": "file:///b"}]
    assert changed_packages(" - tool==1.0 (from file:///a)\n + tool==1.1 (from file:///a)\n", "x")[0]["to"] == "1.1"
    assert changed_packages(" - gone==1.0\n", "x") == [{"name": "gone", "from": "1.0", "to": None}]
    # The lab's own projects never count, whatever changes in them.
    upgraded = " - grating_mask_search==0.1.2\n + grating-mask-search==0.1.3\n - numpy==2.1.0\n + numpy==2.2.0\n"
    assert changed_packages(upgraded, "bakery-search", {"balsamic", "grating-mask-search"}) == [{"name": "numpy", "from": "2.1.0", "to": "2.2.0"}]


def test_the_labs_own_projects_are_its_root_and_its_libraries(lab):
    workspace, cid, development, root, submission = lab
    (root / "libraries/grating-mask-search").mkdir()
    (root / "libraries/grating-mask-search/pyproject.toml").write_text('[project]\nname = "grating-mask-search"\nversion = "0.1.2"\n')
    (root / "libraries/broken").mkdir()
    (root / "libraries/broken/pyproject.toml").write_text("not toml [")
    assert lab_projects(root) == {"lab", "grating-mask-search"}


def test_balsamic_installs_without_asking_when_its_dry_run_only_reinstalls(lab):
    install, _ = installer(lab, dry_run=REINSTALL)
    record = install.automatic(lab[1], "development_bakery", lab[4], background=False)
    assert record["status"] == "installed" and record["changes"] == []


def stale(lab, log_tail, **fields):
    """Balsamic's install as the earlier parser left it: waiting for a confirmation."""
    workspace, cid, development, root, submission = lab
    return workspace.store.put("library_install", {"id": "library_install_stale", "campaign_id": cid, "workspace_id": "development_bakery",
        "submission_id": submission["id"], "commit": submission["commit"], "package": "bakery-search", "version": "0.2.0",
        "path": "libraries/bakery", "entry_points": {}, "actor": "balsamic", "status": "needs_confirmation",
        "requested_at": "2026-10-27T03:23:00+00:00", "finished_at": "2026-10-27T03:23:05+00:00", "confirm_changes": False,
        "changes": [{"name": "lab", "from": "1.0", "to": None}], "methods_added": [], "missing_methods": [],
        "log_tail": log_tail, **fields})


@pytest.fixture
def syncing(lab, monkeypatch):
    """The workspaces' sync, with the lab at root and uv faked."""
    workspace, cid, development, root, submission = lab
    fake, commands = installer(lab, dry_run=REINSTALL)
    original = Installer.__init__
    monkeypatch.setattr(development_runtime, "ROOT", root)
    monkeypatch.setattr(Installer, "reparsed", functools.partialmethod(Installer.reparsed, background=False))
    monkeypatch.setattr(Installer, "__init__", lambda self, *args, **kwargs: original(self, *args, **{**kwargs, "runner": fake.runner, "uv": "uv", "plugins": fake.plugins,
        "problems": fake.problems, "providers": fake.providers, "validator": fake.validator}))
    return commands


def installs(lab):
    return sorted(lab[0].store.list("library_install", lab[1]), key=lambda row: row["requested_at"])


def test_a_stale_confirmation_is_tried_once_more_and_only_once(lab, syncing):
    workspace, cid, development, root, submission = lab
    old = stale(lab, "$ lock\nResolved 5 packages in 5ms\nAdded bakery-search v0.2.0\n$ sync --dry-run --inexact --extra libraries\n" + REINSTALL)
    development.install_delivered(cid)
    first, retry = installs(lab)
    assert first == old and retry["retry_of"] == old["id"] and retry["actor"] == "balsamic"
    assert retry["status"] == "installed" and retry["methods_added"] == ["bakery_dp"] and retry["changes"] == []
    assert retry["id"] == "library_install_" + content_hash([submission["id"], "automatic:reparsed"])[:24]
    development.install_delivered(cid)
    assert len(installs(lab)) == 2 and len([c for c in syncing if c == ["sync", "--inexact", "--extra", "libraries"]]) == 1


def test_a_retry_that_waits_again_is_not_tried_a_third_time(lab, syncing):
    workspace, cid, development, root, submission = lab
    stale(lab, "$ sync --dry-run --inexact --extra libraries\n" + REINSTALL)
    stale(lab, "$ sync --dry-run --inexact --extra libraries\n" + REINSTALL, id="library_install_retry", retry_of="library_install_stale",
          requested_at="2026-10-27T04:00:00+00:00")
    development.install_delivered(cid)
    assert len(installs(lab)) == 2 and syncing == []


@pytest.mark.parametrize("log_tail, fields", [
    ("$ sync --dry-run --inexact --extra libraries\n" + UPGRADE, {}),                       # a real change still waits
    ("$ sync --dry-run --inexact --extra libraries\n" + REINSTALL, {"actor": "researcher"}),  # the researcher's own install
    ("$ sync --dry-run --inexact --extra libraries\n" + REINSTALL, {"status": "failed"}),
    (REINSTALL[-200:], {}),                                                                   # the log lost the dry run's start
])
def test_only_balsamics_stale_confirmation_with_no_change_is_tried_again(lab, syncing, log_tail, fields):
    workspace, cid, development, root, submission = lab
    stale(lab, log_tail, **fields)
    development.install_delivered(cid)
    assert len(installs(lab)) == 1 and syncing == []


PROBLEM_PYPROJECT = '[project]\nname = "bakery-search"\nversion = "0.2.0"\n\n' \
                    '[project.entry-points."optimization_framework.problems"]\nbaking_order = "bakery.problem:Problem"\n'


def deliver(lab, pyproject, methods=()):
    """The workspace's submission with libraries/bakery/pyproject.toml replaced, at a new commit in its Git store."""
    workspace, cid, development, root, submission = lab
    store = development.driver.root({"id": "development_bakery"}) / "work" / "git"
    source = Path(tempfile.mkdtemp(dir=store.parent))
    git("clone", "-q", str(store), str(source / "edit"), cwd=store.parent)
    source = source / "edit"
    (source / "libraries/bakery/pyproject.toml").write_text(pyproject)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-am", "edit", cwd=source)
    git("push", "-q", "origin", "HEAD", cwd=source)
    files = {**LIBRARY, "libraries/bakery/pyproject.toml": pyproject}
    report = {**submission["report"], "methods": [{**submission["report"]["methods"][0], "method_id": method} for method in methods]}
    return workspace.store.put("development_submission", {**submission, "commit": git("rev-parse", "HEAD", cwd=source), "report": report,
        "package": {"files": [{"path": path, "content": content} for path, content in files.items()]}})


def test_a_library_that_provides_only_a_problem_installs_and_records_the_problem(lab, monkeypatch):
    workspace, cid, development, root, submission = lab
    notices = []
    monkeypatch.setattr(development, "notify", lambda record, identity, text, kind: notices.append(text))
    deliver(lab, PROBLEM_PYPROJECT)
    install, commands = installer(lab, provided=["baking_order"])
    record = request(lab, install)
    assert record["status"] == "installed" and record["problem_entry_points"] == {"baking_order": "bakery.problem:Problem"}
    assert record["problems_added"] == ["baking_order"] and record["missing_problems"] == [] and record["entry_points"] == {}
    from optimization_framework.agents.library_install import added
    assert added(record) == "problems baking_order"
    # The notice names the problem, and asks for no binding: a problem has no proposal to bind.
    assert notices[-1].startswith("The researcher installed bakery-search 0.2.0 from commit ") and notices[-1].endswith(": problems baking_order.")
    # A problem whose entry point does not load is named, as a method's is.
    deliver(lab, PROBLEM_PYPROJECT.replace("0.2.0", "0.2.1"))
    missing = request(lab, installer(lab)[0], key="two")
    assert missing["problems_added"] == [] and missing["missing_problems"] == ["baking_order"]
    assert added(missing) == "problems none new; not found: baking_order"


def test_a_library_with_both_groups_records_methods_and_problems(lab):
    deliver(lab, PROBLEM_PYPROJECT + 'bakery_lb = "bakery.problem:LowerBound"\n\n[project.entry-points."optimization_framework.optimizers"]\n'
                 'bakery = "bakery.plugin:Plugin"\n', methods=["bakery_dp"])
    from optimization_framework.agents.library_install import added
    record = request(lab, installer(lab, provided=["baking_order", "bakery_lb"])[0])
    assert record["methods_added"] == ["bakery_dp"] and record["problems_added"] == ["bakery_lb", "baking_order"]
    assert added(record) == "methods bakery_dp; problems bakery_lb, baking_order"


def test_a_library_with_neither_entry_point_is_refused(lab):
    deliver(lab, '[project]\nname = "bakery-search"\nversion = "0.2.0"\n')
    install, commands = installer(lab)
    with pytest.raises(ValueError, match="no optimization_framework.optimizers or optimization_framework.problems entry point"):
        request(lab, install)
    assert commands == []


@pytest.mark.parametrize("pyproject, methods, installed, refusal", [
    (PROBLEM_PYPROJECT, (), {"optimization_framework.problems": {"baking_order": "other-bakery"}},
     "problem baking_order is provided by other-bakery"),
    (PROBLEM_PYPROJECT.replace("baking_order", "bounded_continuous"), (), {"optimization_framework.problems": {"bounded_continuous": "balsamic"}},
     "problem bounded_continuous is provided by balsamic"),
    (LIBRARY["libraries/bakery/pyproject.toml"], ["bakery_dp"], {"optimization_framework.optimizers": {"bakery": "someone-else"}},
     "optimizer plug-in bakery is provided by someone-else"),
    (LIBRARY["libraries/bakery/pyproject.toml"], ["random"], {}, "method random is provided by the lab"),
    (LIBRARY["libraries/bakery/pyproject.toml"], ["mask_dqn"], {}, "method mask_dqn is provided by grating-mask-search"),
])
def test_an_id_another_package_provides_is_refused_before_any_uv_command(lab, pyproject, methods, installed, refusal):
    workspace, cid, development, root, submission = lab
    deliver(lab, pyproject, methods)
    install, commands = installer(lab, installed=installed)
    install.plugins.origin = lambda method_id: {"distribution": "grating-mask-search"} if method_id == "mask_dqn" else None
    with pytest.raises(ValueError, match=refusal):
        request(lab, install)
    assert commands == [] and (root / "pyproject.toml").read_text() == PYPROJECT
    # Balsamic's own install records the refusal as a failed install.
    refused = install.automatic(cid, "development_bakery", workspace.store.get(submission["id"], "development_submission"), background=False)
    assert refused["status"] == "failed" and refusal in refused["error"] and refused["problems_added"] == []


def test_the_librarys_own_earlier_version_is_no_clash(lab):
    deliver(lab, PROBLEM_PYPROJECT, ["bakery_dp"])
    install, _ = installer(lab, provided=["baking_order"], installed={"optimization_framework.problems": {"baking_order": "bakery_search"},
                                                                       "optimization_framework.optimizers": {"bakery": "Bakery.Search"}})
    install.plugins.origin = lambda method_id: {"distribution": "bakery-search"}
    assert request(lab, install)["status"] == "installed"


def test_the_installed_providers_name_the_labs_own_problems():
    from optimization_framework.agents.library_install import PROBLEMS, providers
    import tomllib
    lab = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["name"]
    assert providers(PROBLEMS)["bounded_continuous"] == lab
