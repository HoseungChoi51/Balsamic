"""One Git repository per code library (roadmap L2): each install commits the version onto the library's repository and tags
it, the lab's copy is that commit's files, each version is a library_version record with the one before it, and what the lab had
before (L1's archive, the lab's own copy) is imported once. The Packages page reads /api/libraries."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from optimization_framework.agents import development_api, library_repository as repositories
from optimization_framework.agents.library_install import import_lab, lab_files

from test_library_install import deliver, lab, request   # noqa: F401  (the fixture)
from test_library_keep import OLD, installed, listing, other   # noqa: F401  (the fixture)

V3 = '[project]\nname = "bakery-search"\nversion = "0.3.0"\n\n[project.entry-points."optimization_framework.optimizers"]\nbakery = "bakery.plugin:Plugin"\n'


def test_two_installs_make_two_tagged_versions_and_the_labs_copy_is_the_tag(lab, other):
    workspace, cid, development, root, submission = lab
    install, _ = installed(lab, ["bakery_dp", "bakery_greedy"], ["bakery_dp", "bakery_greedy"], listing("bakery_dp", "bakery_greedy"))
    first = request(lab, install)
    deliver(lab, V3, methods=["bakery_dp", "bakery_greedy", "bakery_new"])
    install.plugins.before, install.plugins.after, install.plugins.synced = ["bakery_dp", "bakery_greedy"], ["bakery_dp", "bakery_greedy", "bakery_new"], False
    install.validator = listing("bakery_dp", "bakery_greedy", "bakery_new")
    second = request(lab, install, key="two")
    assert first["status"] == second["status"] == "installed"
    rows = repositories.versions(workspace.store, "bakery")
    assert [row["version"] for row in rows] == ["0.1.0", "0.2.0", "0.3.0"]
    assert rows[2]["parent_id"] == rows[1]["id"] and rows[2]["methods_added"] == ["bakery_new"] and rows[2]["methods"] == ["bakery_dp", "bakery_greedy", "bakery_new"]
    store = repositories.path(workspace.directory, "bakery")
    # The tags form one line of history, and the lab's copy is the latest tag's tree.
    assert repositories._git(store, "rev-list", "--count", "v0.3.0").decode().strip() == "3"
    assert repositories._git(store, "rev-parse", "v0.3.0^").decode().strip() == rows[1]["commit"]
    assert lab_files(root / "libraries/bakery", root) == repositories.files_at(store, "v0.3.0", "bakery")
    assert second["tag"] == "v0.3.0" and second["library_commit"] == rows[2]["commit"]
    assert f"from commit {second['commit']}" in repositories._git(store, "log", "-1", "--format=%B", "v0.3.0").decode()


def test_a_version_installed_before_with_other_code_is_refused(lab):
    workspace, cid, development, root, submission = lab
    install, _ = installed(lab, ["bakery_dp"], ["bakery_dp"], listing("bakery_dp"))
    assert request(lab, install)["status"] == "installed"
    # The lab's copy goes back to 0.1.0 by hand; 0.2.0 again, with other code, is refused by its tag.
    (root / "libraries/bakery/pyproject.toml").write_text(OLD)
    changed = V3.replace("0.3.0", "0.2.0") + "\n# other code\n"
    deliver(lab, changed, methods=["bakery_dp"])
    install.plugins.synced = False
    again = request(lab, install, key="two")
    assert again["status"] == "failed" and "Version 0.2.0 was installed before with other code" in again["error"]


def test_l1s_archive_and_the_labs_copy_are_imported_once(lab, tmp_path):
    workspace, cid, development, root, submission = lab
    archived = workspace.directory / "library_archive/bakery/0.0.9"
    (archived / "files").mkdir(parents=True)
    (archived / "files/pyproject.toml").write_text(OLD.replace("0.1.0", "0.0.9"))
    (archived / "version.json").write_text(json.dumps({"package": "bakery-search", "version": "0.0.9", "methods": ["bakery_dp"],
                                                       "install_id": "library_install_old", "archived_at": "2026-10-28T03:00:00+00:00"}))
    (root / "libraries/bakery").mkdir(parents=True)
    (root / "libraries/bakery/pyproject.toml").write_text(OLD)

    class Plugins:
        def methods(self):
            return [{"id": "bakery_dp"}, {"id": "random"}]
        def origin(self, method_id):
            return {"distribution": "bakery_search"} if method_id == "bakery_dp" else None
    rows = import_lab(workspace, root, plugins=Plugins(), provided_by=lambda group: {})
    assert [(row["version"], row["source"]["imported"]) for row in rows] == [("0.0.9", "archive"), ("0.1.0", "the lab's copy")]
    assert rows[0]["source"]["install_id"] == "library_install_old" and rows[1]["methods"] == ["bakery_dp"]
    assert import_lab(workspace, root, plugins=Plugins(), provided_by=lambda group: {}) == []


def test_the_api_lists_versions_methods_and_the_campaigns_using_each(lab, other):
    workspace, cid, development, root, submission = lab
    install, _ = installed(lab, ["bakery_dp", "bakery_greedy"], ["bakery_dp", "bakery_greedy"], listing("bakery_dp", "bakery_greedy"))
    request(lab, install)
    workspace.pi.development = development
    app = FastAPI()
    development_api.install(app, workspace)
    client = TestClient(app)
    detail = client.get("/api/libraries/bakery").json()
    assert detail["package"] == "bakery-search" and detail["latest"] == "0.2.0"
    assert [row["version"] for row in detail["versions"]] == ["0.2.0", "0.1.0"]
    assert detail["versions"][0]["source"]["campaign_id"] == cid
    greedy = next(row for row in detail["methods"] if row["id"] == "bakery_greedy")
    assert greedy == {"id": "bakery_greedy", "since": "0.1.0", "in_latest": True, "campaigns": [{"id": other["id"], "name": "Second bakery"}]}
    assert client.get("/api/libraries/nothing").status_code == 404
    listed = repositories.catalog(workspace.store)["libraries"]
    assert [(row["name"], row["latest"], row["versions"]) for row in listed] == [("bakery", "0.2.0", 2)]
