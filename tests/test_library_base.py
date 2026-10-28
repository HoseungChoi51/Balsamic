"""A workspace builds on the latest installed version of its library (roadmap L3): it starts from that version's files instead
of the blank library generated from the charter, its ticket lists the existing methods and what a new version keeps, its
delivery is reviewed against that version, and the version's fixed files stay fixed. A prepared workspace keeps its start."""
import pytest

from optimization_framework.agents import library_repository as repositories
from optimization_framework.agents.library_install import generated_changes
from optimization_framework.problem_charter.scaffold import scaffold

from test_development_generated_library import LIBRARY, charter_lab, opened   # noqa: F401  (the fixture)
from test_pi_development_workspaces import setup   # noqa: F401  (the fixture)
from test_problem_charter_scaffold import METHODS, OBJECTIVE, ovens

METHOD_IDS = ["all_cold", "all_middle", "random_search"]


def install_version(workspace, charter, version, extra=None):
    """An earlier campaign's install of the ovens library, as L2 records it: a tagged commit and a library_version."""
    files = scaffold(ovens(), charter["revision"], charter_id=charter["id"], balsamic=True)
    files = {**files, "oven_trays/objective.py": OBJECTIVE.encode(), "oven_trays/methods.py": METHODS.encode(),
             "pyproject.toml": files["pyproject.toml"].replace(b'version = "0.1.0"', f'version = "{version}"'.encode()), **(extra or {})}
    store, made = repositories.commit(workspace.directory, "oven_trays", {f"{LIBRARY}/{path}": content for path, content in files.items()},
                                      f"oven-trays {version}")
    made = repositories.publish(store, made, version)
    repositories.record(workspace.store, "oven_trays", "oven-trays", version, made, source={"campaign_id": "campaign_earlier"},
                        methods=METHOD_IDS, problems=["oven_trays"])
    return files


def test_a_workspace_starts_from_the_latest_version_and_its_ticket_says_what_to_keep(charter_lab):
    workspace, cid, development, driver, charter = charter_lab
    install_version(workspace, charter, "0.1.0")
    files = install_version(workspace, charter, "0.2.0", {"tests/test_earlier.py": b"def test_earlier():\n    pass\n"})
    record = opened(development, cid)
    development.sync(cid)
    repo = driver.repo(record)
    assert {path: (repo / LIBRARY / path).read_bytes() for path in files} == files
    base = development.get(cid, record["id"])["library"]["base"]
    assert (base["version"], base["package"], base["methods"]) == ("0.2.0", "oven-trays", METHOD_IDS)
    task, rules = ((repo / name).read_text() for name in ("TASK.md", "AGENTS.md"))
    assert "## What you build on" in task and "holds oven-trays 0.2.0, the version the lab runs, with 3 methods: `all_cold`, `all_middle`, " \
           "`random_search` and the problem `oven_trays`" in task
    assert "a changed scoring function is a new problem id" in task and "Raise the version above 0.2.0." in task
    assert "`libraries/oven_trays/tests/test_earlier.py` (base version)" in task
    assert "at oven-trays 0.2.0, the version the lab runs" in rules
    # A version installed later does not change the start of a workspace already prepared.
    install_version(workspace, charter, "0.3.0")
    assert development.generated_library(development.get(cid, record["id"]))[0]["base"]["version"] == "0.2.0"


def test_the_delivery_is_reviewed_against_the_version_it_built_on_and_its_fixed_files_stay(charter_lab):
    workspace, cid, development, driver, charter = charter_lab
    files = install_version(workspace, charter, "0.2.0")
    record = opened(development, cid)
    development.sync(cid)
    record = development.get(cid, record["id"])
    delivered = {f"{LIBRARY}/{path}": content for path, content in files.items()}
    delivered[f"{LIBRARY}/oven_trays/methods.py"] = files["oven_trays/methods.py"] + b"\n# a new method\n"
    submission = {"id": "development_submission_x", "commit": "0" * 40, "manifest": {"files": sorted(delivered)},
                  "package": {"files": [{"path": path, "content": content.decode()} for path, content in delivered.items()]}}
    diff = development.diff(record, submission)
    assert diff["base_version"] == "0.2.0" and diff["files_changed"] == 1 and diff["files"][0]["path"] == f"{LIBRARY}/oven_trays/methods.py"
    # Decision 9 holds against the base: its data is fixed.
    assert generated_changes(record, "oven_trays", delivered) == []
    delivered[f"{LIBRARY}/oven_trays/data.py"] = b"TITLE = 'Another problem'\n"
    with pytest.raises(ValueError, match="data.py differs"):
        generated_changes(record, "oven_trays", delivered)


def test_a_workspace_on_a_problem_with_no_installed_version_starts_from_the_generated_library(charter_lab):
    workspace, cid, development, driver, charter = charter_lab
    record = opened(development, cid)
    development.sync(cid)
    assert "base" not in development.get(cid, record["id"])["library"]
    assert "## What you build on" not in (driver.repo(record) / "TASK.md").read_text()
    # And keeps that start once a version is installed.
    install_version(workspace, charter, "0.2.0")
    assert "base" not in development.generated_library(development.get(cid, record["id"]))[0]
