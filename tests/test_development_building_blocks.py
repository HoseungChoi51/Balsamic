"""A coding box imports the shared library repository's building blocks (issue #101): its ticket names them at their latest tags,
TASK.md lists their functions and the dependency to declare, Balsamic exports them into the workspace and puts them on the box's
Python path (mounted read-only at /opt/libraries), validation outside the box imports the same copy, and the install pins the
dependency to the tag the box had."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from optimization_framework.agents import development_runtime, shared_libraries
from optimization_framework.agents.development_runtime import BLOCKS_PTH, BOX_PYTHON, ROOT, DockerWorkspace, write_blocks
from optimization_framework.agents.development_ticket import BLOCKS, build, files, task

from test_library_install import deliver, installer, lab, request   # noqa: F401  (the fixture)

BLOCK = {"libraries/toyblocks/pyproject.toml": b'[project]\nname = "toyblocks"\nversion = "0.1.0"\ndescription = "Toy building blocks."\n'
                                               b'dependencies = []\n[tool.balsamic]\nfamily = "toys"\n',
         "libraries/toyblocks/src/toyblocks/__init__.py": b'"""Toy blocks."""\n__all__ = ["double"]\nfrom .core import double\n',
         "libraries/toyblocks/src/toyblocks/core.py": b'def double(x: int) -> int:\n    """Twice x."""\n    return 2 * x\n',
         "libraries/toyblocks/tests/test_core.py": b"from toyblocks import double\n\n\ndef test_double():\n    assert double(2) == 4\n"}


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def shared(tmp_path, monkeypatch):
    """The shared library repository with one building block and one library of methods (which no box imports)."""
    repository = tmp_path / "shared"
    repository.mkdir()
    git("init", "-q", "-b", "main", cwd=repository)
    monkeypatch.setenv(shared_libraries.SETTING, str(repository))
    shared_libraries.publish(repository, "toyblocks", BLOCK, "0.1.0", "toyblocks 0.1.0")
    methods = {"libraries/toysearch/pyproject.toml": b'[project]\nname = "toysearch"\nversion = "1.0.0"\n'
                                                     b'[project.entry-points."optimization_framework.optimizers"]\ntoy = "toysearch:Plugin"\n',
               "libraries/toysearch/toysearch/__init__.py": b"class Plugin:\n    pass\n"}
    shared_libraries.publish(repository, "toysearch", methods, "1.0.0", "toysearch 1.0.0")
    return repository


def blocks():
    return shared_libraries.building_blocks(ROOT)


def test_only_packages_with_neither_methods_nor_problems_are_building_blocks(shared):
    (block,) = blocks()
    assert (block["package"], block["version"], block["tag"], block["module"], block["layout"]) == ("toyblocks", "0.1.0", "toyblocks-v0.1.0", "toyblocks", "src")
    assert block["functions"] == [{"signature": "double(x: int) -> int", "doc": "Twice x."}]
    assert shared_libraries.building_blocks(ROOT, exclude={"toyblocks"}) == []


def test_the_ticket_fixes_the_blocks_and_task_md_says_how_to_import_and_declare_them(shared):
    record = {"id": "development_toy", "campaign_id": "campaign_toy", "title": "Toy", "objective": "Build it", "evidence_ids": []}
    ticket = build(record, [], {}, blocks=blocks())
    assert ticket["building_blocks"][0]["commit"] == git("rev-parse", "toyblocks-v0.1.0", cwd=shared)
    text = task(ticket)
    assert "## Building blocks you can import" in text and "### toyblocks 0.1.0: `import toyblocks`" in text
    assert '`"toyblocks>=0.1.0"`' in text and "- `double(x: int) -> int`: Twice x." in text and f"`{BLOCKS}/`" in text
    assert "never copy their code" in ticket["house_rules"] and b"building_blocks" in files(ticket)[".balsamic/spec.json"]
    assert "## Building blocks" not in task(build(record, [], {}))


def test_the_box_gets_each_block_at_its_tag_on_its_python_path(shared, tmp_path):
    root = tmp_path / "development_toy"
    (root / "home").mkdir(parents=True)
    assert write_blocks(root, blocks()) == [f"{BLOCKS}/toyblocks/src"]
    assert (root / "blocks/toyblocks/src/toyblocks/core.py").read_bytes() == BLOCK["libraries/toyblocks/src/toyblocks/core.py"]
    assert (root / BLOCKS_PTH).read_text() == f"{BLOCKS}/toyblocks/src\n"
    # A version never changes: a tag moved to another commit stops the workspace from starting with it.
    (shared / "toyblocks/NOTE").write_text("later\n")
    git("add", ".", cwd=shared)
    git("-c", "user.name=r", "-c", "user.email=r@r", "commit", "-q", "-m", "note", cwd=shared)
    stale = blocks()
    git("tag", "-f", "toyblocks-v0.1.0", "HEAD", cwd=shared)
    with pytest.raises(ValueError, match="a version never changes"):
        write_blocks(root, [{**stale[0], "commit": "0" * 40}])
    # A workspace without blocks keeps no copy and no .pth (a home warmed from an earlier workspace may have had one).
    assert write_blocks(root, []) == [] and not (root / "blocks").exists() and not (root / BLOCKS_PTH).exists()


def test_the_box_mounts_its_blocks_read_only(shared, tmp_path, monkeypatch):
    driver = DockerWorkspace(tmp_path / "development")
    record = {"id": "development_toy", "model": {"provider": "openai", "model": "gpt", "effort": None}}
    root = driver.root(record)
    (root / "home").mkdir(parents=True)
    write_blocks(root, blocks())
    commands = []
    monkeypatch.setattr(development_runtime, "run", lambda args, **kwargs: commands.append(args) or "")
    monkeypatch.setattr(DockerWorkspace, "inspect", lambda self, record: None)
    driver.start(record)
    assert f"type=bind,src={root / 'blocks'},dst={BLOCKS},readonly" in commands[0]


def test_the_boxes_python_is_the_one_its_image_has():
    dockerfile = (ROOT / "deploy/implementation-workspace/Dockerfile").read_text()
    assert re.search(rf"^FROM python:{re.escape(BOX_PYTHON)}-", dockerfile, re.M), "BLOCKS_PTH names the image's Python"


# Validation and the install use what the box had ----------------------------------------------------------------------------
@pytest.mark.skipif(not shutil.which("bwrap"), reason="validation outside the box needs bubblewrap")
def test_validation_outside_the_box_imports_a_block_laid_out_under_src():
    from optimization_framework.agents import library_validation as validation
    from test_library_validation import files as oven_files
    library = oven_files(**{"tests/test_blocks.py": "from toyblocks import double\n\n\ndef test_blocks_import():\n    assert double(3) == 6\n"})
    passed = validation.run(library, "oven_trays", dependencies={path: content for path, content in BLOCK.items() if "/tests/" not in path})
    assert passed["tests"]["failed"] == 0, passed["tests"]
    assert validation.run(library, "oven_trays")["tests"]["failed"] >= 1   # without the block it cannot import


DEPENDS = ('[project]\nname = "bakery-search"\nversion = "0.3.0"\ndependencies = ["toyblocks>=0.1.0"]\n\n'
           '[project.entry-points."optimization_framework.optimizers"]\nbakery = "bakery.plugin:Plugin"\n')


def test_the_install_validates_with_the_boxs_blocks_and_pins_the_tag_it_had(lab, shared):
    workspace, cid, development, root, submission = lab
    record = workspace.store.get("development_bakery", "development_workspace")
    write_blocks(development.driver.root(record), blocks())
    ticket = workspace.store.put("development_ticket", {"id": "development_ticket_bakery", "campaign_id": cid, "workspace_id": record["id"],
                                                        "building_blocks": blocks()})
    workspace.store.put("development_workspace", {**record, "ticket_id": ticket["id"]})
    # A later version is published after the box started: the install still pins the one the box had.
    later = {path: content.replace(b'version = "0.1.0"', b'version = "0.2.0"') for path, content in BLOCK.items()}
    shared_libraries.publish(shared, "toyblocks", later, "0.2.0", "toyblocks 0.2.0")
    seen = {}

    def validator(files, name, **options):
        seen.update(options)
        return {"tests": {"passed": 3, "failed": 0, "skipped": 0, "results": []}, "protected": None, "methods": [], "seconds": 0.5}
    install, _ = installer(lab, validator=validator)
    delivered = deliver(lab, DEPENDS, methods=["bakery_dp"])
    record = install.request(cid, "development_bakery", delivered["id"], request_key="blocks", background=False)
    assert record["status"] == "installed", record.get("error")
    assert sorted(seen["dependencies"]) == ["libraries/toyblocks/pyproject.toml", "libraries/toyblocks/src/toyblocks/__init__.py",
                                            "libraries/toyblocks/src/toyblocks/core.py", "libraries/toyblocks/tests/test_core.py"]
    text = (root / "pyproject.toml").read_text()
    assert f'toyblocks = {{ git = "{Path(shared).resolve().as_uri()}", subdirectory = "toyblocks", tag = "toyblocks-v0.1.0" }}' in text
    assert '"toyblocks==0.1.0"' in text


# A workspace's sync hands its ticket's blocks to the box ------------------------------------------------------------------------
from test_development_generated_library import LibraryDriver, charter_lab, opened   # noqa: E402,F401  (the fixtures)
from test_pi_development_workspaces import setup   # noqa: E402,F401


def test_a_workspace_opened_on_a_charter_gets_the_blocks_its_ticket_names(charter_lab, shared, monkeypatch):
    workspace, cid, development, driver, charter = charter_lab
    given = []
    prepare = LibraryDriver.prepare
    monkeypatch.setattr(LibraryDriver, "prepare", lambda self, *args, blocks=(), **kwargs: given.append(list(blocks)) or prepare(self, *args, **kwargs))
    record = opened(development, cid)
    development.sync(cid)
    ticket = development.ticket_of(development.get(cid, record["id"]))
    assert [block["package"] for block in ticket["building_blocks"]] == ["toyblocks"] and given == [ticket["building_blocks"]]
    assert "import toyblocks" in (driver.repo(record) / "TASK.md").read_text()
