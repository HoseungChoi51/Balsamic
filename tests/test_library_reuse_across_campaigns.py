"""A new campaign reuses what earlier campaigns delivered, without ids from the researcher (issue #101): every install publishes
its version to the shared library repository, a checkout restores the libraries it lacks, the lead lists the lab's packages
with the campaigns they came from and why they concern its campaign, the researcher and the lead are told once per version,
and a campaign adopts a problem by its library version."""
import subprocess
from pathlib import Path

import pytest

from optimization_framework.agents import library_repository as repositories, shared_libraries
from optimization_framework.agents.library_install import restore
from optimization_framework.campaigns import lab_packages
from optimization_framework.contracts.requests import CampaignInput, TaskInput

from test_library_install import PYPROJECT, installer, lab, request   # noqa: F401  (the fixture)


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def shared(tmp_path, monkeypatch):
    """The shared library repository: a work tree with one commit of a package written by hand."""
    repository = tmp_path / "shared"
    (repository / "notes").mkdir(parents=True)
    (repository / "notes/README.md").write_text("by hand\n")
    git("init", "-q", "-b", "main", cwd=repository)
    git("add", ".", cwd=repository)
    git("-c", "user.name=r", "-c", "user.email=r@r", "commit", "-q", "-m", "start", cwd=repository)
    monkeypatch.setenv(shared_libraries.SETTING, str(repository))
    return repository


BLOCKS = {"libraries/blocks/pyproject.toml": b'[project]\nname = "blocks"\nversion = "0.1.0"\ndescription = "Building blocks"\n'
                                              b'[tool.balsamic]\nfamily = "toy scheduling"\n',
          "libraries/blocks/src/blocks/__init__.py": b'"""Blocks."""\n__all__ = ["solve"]\nfrom .core import solve, hidden\n',
          "libraries/blocks/src/blocks/core.py": b'def solve(p: list[int], d: list[int], *, seed: int = 0) -> list[int]:\n'
                                                 b'    """An order of the jobs.\n\n    More text."""\n    return []\n\n\ndef hidden():\n    pass\n',
          "libraries/blocks/tests/test_core.py": b"def test_solve():\n    pass\n"}


# The shared repository ----------------------------------------------------------------------------------------------------
def test_where_the_shared_repository_is(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.delenv(shared_libraries.SETTING, raising=False)
    assert shared_libraries.location(checkout) is None   # nothing beside the checkout
    beside = tmp_path / shared_libraries.DEFAULT_NAME
    beside.mkdir()
    git("init", "-q", cwd=beside)
    assert shared_libraries.location(checkout) == beside
    monkeypatch.setenv(shared_libraries.SETTING, "off")
    assert shared_libraries.location(checkout) is None
    monkeypatch.setenv(shared_libraries.SETTING, str(tmp_path / "elsewhere"))
    assert shared_libraries.location(checkout) is None   # not a Git work tree


def test_publishing_commits_one_directory_tags_the_version_and_never_changes_it(shared):
    made = shared_libraries.publish(shared, "blocks", BLOCKS, "0.1.0", "blocks 0.1.0")
    assert made["created"] and made["tag"] == "blocks-v0.1.0" and made["branch"] == "main"
    assert (shared / "blocks/src/blocks/core.py").read_bytes() == BLOCKS["libraries/blocks/src/blocks/core.py"]
    assert git("log", "-1", "--format=%an %s", cwd=shared) == "Balsamic blocks 0.1.0"
    assert git("status", "--porcelain", cwd=shared) == ""
    assert shared_libraries.publish(shared, "blocks", BLOCKS, "0.1.0", "again")["created"] is False
    with pytest.raises(ValueError, match="holds other code"):
        shared_libraries.publish(shared, "blocks", {**BLOCKS, "libraries/blocks/extra.py": b"x = 1\n"}, "0.1.0", "changed")
    (shared / "blocks/mine.txt").write_text("the researcher's own\n")
    with pytest.raises(ValueError, match="uncommitted changes"):
        shared_libraries.publish(shared, "blocks", BLOCKS, "0.2.0", "blocks 0.2.0")
    (shared / "blocks/mine.txt").unlink()
    # A staged change of the researcher's elsewhere stays theirs: only the library's directory is committed.
    (shared / "notes/README.md").write_text("staged\n")
    git("add", "notes/README.md", cwd=shared)
    newer = {path: content for path, content in BLOCKS.items() if not path.endswith("test_core.py")}
    assert shared_libraries.publish(shared, "blocks", {**newer, "libraries/blocks/pyproject.toml": BLOCKS["libraries/blocks/pyproject.toml"].replace(b"0.1.0", b"0.2.0")},
                                    "0.2.0", "blocks 0.2.0")["created"]
    assert not (shared / "blocks/tests/test_core.py").exists() and git("diff", "--cached", "--name-only", cwd=shared) == "notes/README.md"


def test_packages_list_versions_entry_points_and_public_functions_from_the_code(shared):
    shared_libraries.publish(shared, "blocks", BLOCKS, "0.1.0", "blocks 0.1.0")
    (row,) = shared_libraries.packages(shared)
    assert row["name"] == "blocks" and row["latest"] == "0.1.0" and row["versions"] == ["0.1.0"] and row["family"] == "toy scheduling"
    assert row["blocks"] == [{"name": "solve", "kind": "function", "signature": "solve(p: list[int], d: list[int], *, seed: int=0) -> list[int]",
                              "doc": "An order of the jobs.", "module": "blocks.core"}]
    assert row["plugins"] == row["problems"] == []


# Every install publishes its version --------------------------------------------------------------------------------------
def test_an_install_publishes_its_version_and_says_so(lab, shared):
    workspace, cid, development, root, submission = lab
    install, _ = installer(lab)
    record = request(lab, install)
    assert record["status"] == "installed" and record["published"]["tag"] == "bakery-v0.2.0"
    assert (shared / "bakery/pyproject.toml").read_bytes() == (root / "libraries/bakery/pyproject.toml").read_bytes()
    (version,) = repositories.versions(workspace.store, "bakery")
    assert version["published"] == record["published"]
    assert "Bakery" in git("log", "-1", "--format=%B", "bakery-v0.2.0", cwd=shared)


def test_an_install_the_shared_repository_cannot_take_still_installs_and_says_why(lab, shared):
    (shared / "bakery").mkdir()
    (shared / "bakery/draft.py").write_text("the researcher's own\n")
    install, _ = installer(lab)
    record = request(lab, install)
    assert record["status"] == "installed" and "published" not in record and "uncommitted changes" in record["publish_skipped"]


def test_without_a_shared_repository_an_install_is_as_before(lab, monkeypatch):
    monkeypatch.setenv(shared_libraries.SETTING, "off")
    install, _ = installer(lab)
    record = request(lab, install)
    assert record["status"] == "installed" and "published" not in record and "publish_skipped" not in record


# A checkout restores what it lacks -----------------------------------------------------------------------------------------
class Restoring:
    """uv for restore(): records its commands; the dry run changes nothing unless told to."""
    def __init__(self, dry_run=" Would make no changes\n"):
        self.commands, self.dry_run = [], dry_run

    def __call__(self, args, cwd, timeout=600):
        self.commands.append(args[1:])
        return 0, self.dry_run if "--dry-run" in args else "ok"


def test_a_new_checkout_gets_the_labs_libraries_back_from_the_data_folder(lab, shared):
    workspace, cid, development, root, submission = lab
    install, _ = installer(lab)
    request(lab, install)
    lab_copy = {path: (root / path).read_bytes() for path in ("libraries/bakery/pyproject.toml", "libraries/bakery/src/bakery/plugin.py")}
    # Another checkout of the lab on the same data folder: no libraries/, the project as committed.
    other = root.parent / "other-checkout"
    (other / "libraries").mkdir(parents=True)
    (other / "pyproject.toml").write_text(PYPROJECT)
    uv = Restoring()
    done = restore(workspace, other, runner=uv, uv="uv", installed=lambda package: False)
    assert done["restored"] == [{"library": "bakery", "package": "bakery-search", "version": "0.2.0", "from": "the lab's repository"}]
    assert {path: (other / path).read_bytes() for path in lab_copy} == lab_copy
    assert 'bakery-search = { path = "libraries/bakery", editable = true }' in (other / "pyproject.toml").read_text()
    assert uv.commands == [["lock"], ["sync", "--dry-run", "--inexact", "--extra", "libraries"], ["sync", "--inexact", "--extra", "libraries"]]
    # Restoring again finds nothing missing and runs nothing.
    again = Restoring()
    assert restore(workspace, other, runner=again, uv="uv", installed=lambda package: True)["restored"] == [] and again.commands == []


def test_a_fresh_lab_installs_the_shared_repositorys_packages(lab, shared):
    workspace, cid, development, root, submission = lab
    shared_libraries.publish(shared, "blocks", BLOCKS, "0.1.0", "blocks 0.1.0")
    uv = Restoring()
    done = restore(workspace, root, runner=uv, uv="uv", installed=lambda package: False)
    assert done["pinned"] == [{"package": "blocks", "version": "0.1.0", "tag": "blocks-v0.1.0"}]
    text = (root / "pyproject.toml").read_text()
    assert f'blocks = {{ git = "{shared.resolve().as_uri()}", subdirectory = "blocks", tag = "blocks-v0.1.0" }}' in text and '"blocks==0.1.0"' in text
    assert not (root / "libraries/blocks").exists()   # a building block is a dependency, not one of the lab's libraries


def test_a_restore_that_would_change_the_labs_packages_changes_nothing(lab, shared):
    workspace, cid, development, root, submission = lab
    shared_libraries.publish(shared, "blocks", BLOCKS, "0.1.0", "blocks 0.1.0")
    before = (root / "pyproject.toml").read_text(), (root / "uv.lock").read_text()
    uv = Restoring(dry_run=" - six==1.16.0\n + six==1.17.0\n")
    done = restore(workspace, root, runner=uv, uv="uv", installed=lambda package: False)
    assert done["pinned"] == [] and "six" in done["error"]
    assert ((root / "pyproject.toml").read_text(), (root / "uv.lock").read_text()) == before
    assert ["sync", "--inexact", "--extra", "libraries"] not in uv.commands


# The lead lists the lab's packages ----------------------------------------------------------------------------------------
def version_of(workspace, library, package, version, *, campaign_id, problems=(), methods=(), install_id=None):
    return repositories.record(workspace.store, library, package, version, "c0ffee" + version.replace(".", ""), methods=list(methods),
                               problems=list(problems), source={"campaign_id": campaign_id, "install_id": install_id or f"library_install_{library}"})


def second(workspace, problem_id="bounded_continuous", name="Bakery again"):
    return workspace.create_campaign(CampaignInput(name=name, compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Again", problem_id=problem_id, configuration={})]))["id"]


def test_another_campaigns_package_is_listed_with_where_it_came_from_and_why_it_concerns_this_campaign(lab, monkeypatch):
    monkeypatch.setenv(shared_libraries.SETTING, "off")
    workspace, cid, development, root, submission = lab
    version_of(workspace, "bounded_continuous", "bounded-search", "0.2.1", campaign_id=cid, methods=["bounded_dp"])
    version_of(workspace, "unrelated", "unrelated-search", "0.1.0", campaign_id=cid, methods=["unrelated_walk"])
    other = second(workspace)
    view = lab_packages.listing(workspace, other, root=root)
    first, rest = view["packages"]
    assert first["package"] == "bounded-search" and first["from_campaigns"] == [{"id": cid, "name": "Bakery"}]
    assert first["concerns"] == ["built for problem bounded_continuous (its library carries the problem's name)"]
    assert first["library_version_id"] == repositories.version_id("bounded_continuous", "0.2.1") and first["methods"][0]["loaded"] is False
    assert rest["package"] == "unrelated-search" and rest["concerns"] == []
    assert "implementation.bind_builtin" in view["reuse"] and "campaign.adopt_problem" in view["reuse"]
    assert [row["package"] for row in lab_packages.matches(workspace, other, root=root)] == ["bounded-search"]


def test_a_package_that_provides_the_campaigns_problem_concerns_it(lab, monkeypatch):
    monkeypatch.setenv(shared_libraries.SETTING, "off")
    workspace, cid, development, root, submission = lab
    version_of(workspace, "bounded-lab", "bounded-lab", "1.0.0", campaign_id=cid, problems=["bounded_continuous"])
    (row,) = lab_packages.matches(workspace, second(workspace), root=root)
    assert row["concerns"] == ["provides problem bounded_continuous, which this campaign names"]
    assert row["problems"] == [{"id": "bounded_continuous", "loaded": False, "named_here": True}]


def test_the_shared_repositorys_building_blocks_are_listed(lab, shared):
    workspace, cid, development, root, submission = lab
    shared_libraries.publish(shared, "blocks", BLOCKS, "0.1.0", "blocks 0.1.0")
    (blocks,) = lab_packages.listing(workspace, cid, root=root)["building_blocks"]
    assert blocks["package"] == "blocks" and blocks["in_lab"] is False and blocks["functions"][0]["doc"] == "An order of the jobs."


def test_the_researcher_and_the_lead_are_told_once_per_package_version(lab, monkeypatch):
    monkeypatch.setenv(shared_libraries.SETTING, "off")
    workspace, cid, development, root, submission = lab
    version_of(workspace, "bounded_continuous", "bounded-search", "0.2.1", campaign_id=cid, methods=["bounded_dp"])
    other = second(workspace)
    assert lab_packages.tell(workspace, other, root=root) == [repositories.version_id("bounded_continuous", "0.2.1")]
    assert lab_packages.tell(workspace, other, root=root) == []
    (message,) = [row for row in workspace.store.list("message", other) if row.get("kind") == lab_packages.NOTICE_KIND]
    assert "bounded-search 0.2.1" in message["content"] and "from Bakery" in message["content"]
    version_of(workspace, "bounded_continuous", "bounded-search", "0.3.0", campaign_id=other, methods=["bounded_dp"])
    assert lab_packages.tell(workspace, other, root=root) == [repositories.version_id("bounded_continuous", "0.3.0")]


# A problem is adopted by its library version, from any campaign ---------------------------------------------------------------
from optimization_framework.contracts.commands import Command   # noqa: E402
from test_problem_adoption import declared, library_install, provided   # noqa: E402,F401  (the fixtures)


def command(workspace, cid, operation, payload, identity):
    campaign = workspace.store.get(cid, "campaign")
    return workspace.commands.execute(Command(id=identity, campaign_id=cid, expected_revision=campaign["version"], operation=operation,
                                              payload=payload), actor="researcher")


def test_a_campaign_adopts_the_problem_another_campaigns_library_version_provides(declared, provided):
    workspace, cid = declared
    earlier = second(workspace, name="Earlier reactor")
    install = library_install(workspace, earlier)   # installed in the other campaign
    version = version_of(workspace, "flow_reactor_yield", "reactor-lab", "0.2.0", campaign_id=earlier, problems=["flow_reactor_yield"],
                         install_id=install["id"])
    assert version["source"]["install_id"] == install["id"]
    receipt = command(workspace, cid, "campaign.adopt_problem", {"library_version_id": version["id"]}, "adopt_by_version")
    (row,) = receipt["outcome"]["adopted"]
    assert receipt["outcome"]["install_id"] == install["id"] and workspace.store.get(row["new_task_id"], "task")["provided_by"]["version"] == "0.2.0"


def test_adopting_names_one_library_and_a_version_no_install_made_says_what_to_do(declared, provided):
    workspace, cid = declared
    with pytest.raises(ValueError, match="one of them"):
        command(workspace, cid, "campaign.adopt_problem", {}, "adopt_none")
    imported = repositories.record(workspace.store, "flow_reactor_yield", "reactor-lab", "0.1.0", "abc", methods=[], problems=["flow_reactor_yield"],
                                   source={"imported": "the lab's copy"})
    with pytest.raises(ValueError, match="without an install"):
        command(workspace, cid, "campaign.adopt_problem", {"library_version_id": imported["id"]}, "adopt_imported")


def test_attaching_an_installed_package_says_which_command_reuses_it(declared):
    workspace, cid = declared
    task, = workspace.current_tasks(cid)
    with pytest.raises(ValueError, match=r"campaign.adopt_problem \{library_version_id: library_version_abc\}"):
        command(workspace, cid, "evaluator.attach", {"task_id": task["id"], "version_id": "library_version_abc", "rationale": "reuse"}, "attach_lib")
    with pytest.raises(ValueError, match="implementation.bind_builtin"):
        lab_packages.not_a_service_version("implementation.attach", "library_install_abc")
    assert lab_packages.not_a_service_version("implementation.attach", "implementation_version_abc") is None


def test_the_lead_and_the_implementation_lead_have_lab_packages():
    from balsamic.lead.tools import register
    from optimization_framework.agents.tools import EXTRA_TOOLS
    if "lab_packages" not in EXTRA_TOOLS:
        register()
    assert EXTRA_TOOLS["lab_packages"]["roles"] == {"lead", "implementation_lead"}


def test_a_campaign_is_not_told_of_a_package_only_it_built(lab, monkeypatch):
    monkeypatch.setenv(shared_libraries.SETTING, "off")
    workspace, cid, development, root, submission = lab
    version_of(workspace, "bounded_continuous", "bounded-search", "0.2.1", campaign_id=cid, methods=["bounded_dp"])
    assert lab_packages.listing(workspace, cid, root=root)["packages"][0]["concerns"]   # listed, with why
    assert lab_packages.matches(workspace, cid, root=root) == [] and lab_packages.tell(workspace, cid, root=root) == []
