"""The researcher installs a coding workspace's library with one click: the exact submitted commit's libraries/<name>/ is
copied from the workspace's Git store, checked against the submission, pinned and installed; a change to installed packages
waits for their confirmation, and a failure leaves the lab as it was. uv is faked here; Git is real."""
import subprocess

import pytest

from optimization_framework.agents.development import DevelopmentWorkspaces
from optimization_framework.agents.library_install import Installer, changed_packages
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


def installer(lab, dry_run=" Would make no changes\n", sync_code=0):
    workspace, cid, development, root, submission = lab
    plugins, commands = Plugins(), []
    def runner(args, cwd, timeout=600):
        commands.append(args[1:])
        if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
            plugins.synced = sync_code == 0
            return sync_code, "Installed 1 package" if sync_code == 0 else "error: no matching distribution"
        return 0, dry_run if "--dry-run" in args else "Resolved 3 packages"
    return Installer(workspace, development, root, runner=runner, uv="uv", plugins=plugins), commands


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
