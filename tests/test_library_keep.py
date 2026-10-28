"""An install keeps what campaigns use (roadmap L1, decision 25): a new version of a library may add methods and problems, but a
method or problem the installed version provides that any campaign of the lab uses (a run ran it, a proposal is bound to it, a
task is on it) may not be left out or fail validation outside the box. Every installed version is archived on the host, the
replaced one first. uv is faked, as in tests/test_library_install.py, whose lab this uses."""
import json

import pytest

from optimization_framework.agents import library_repository as repositories
from optimization_framework.agents.library_install import Installer, kept_text
from optimization_framework.agents.library_usage import used_methods, used_problems
from optimization_framework.contracts.requests import CampaignInput, TaskInput

from test_library_install import Problems, lab, request   # noqa: F401  (the fixture)

OLD = '[project]\nname = "bakery-search"\nversion = "0.1.0"\n\n[project.entry-points."optimization_framework.optimizers"]\nbakery = "bakery.plugin:Plugin"\n'


class Versioned:
    """The lab's plug-ins: the installed version's methods, then the new version's once uv sync ran; bakery-search provides them."""
    def __init__(self, before, after):
        self.before, self.after, self.synced = before, after, False

    def methods(self):
        return [{"id": "random"}] + [{"id": method} for method in (self.after if self.synced else self.before)]

    def origin(self, method_id):
        return None if method_id == "random" else {"distribution": "bakery-search"}


def listing(*methods, failing=()):
    """Validation outside the box that lists these methods, those in failing with a failed conformance."""
    def validate(files, name, instances=(), protected=None):
        return {"tests": {"passed": 1, "failed": 0, "skipped": 0, "results": []}, "protected": None, "seconds": 0.1,
                "methods": [{"method_id": method, "check": "check", "problem_id": "bounded_continuous",
                             "conformance": "failed" if method in failing else "passed",
                             **({"failed_check": "seeded replay"} if method in failing else {})} for method in methods]}
    return validate


def installed(lab, before, after, validator, problems=None):
    """An installer for a lab that has bakery-search 0.1.0 installed with ``before``, delivering 0.2.0 with ``after``."""
    workspace, cid, development, root, submission = lab
    (root / "libraries/bakery/src/bakery").mkdir(parents=True)
    (root / "libraries/bakery/pyproject.toml").write_text(OLD)
    (root / "libraries/bakery/src/bakery/plugin.py").write_text("class Plugin: 'version 0.1.0'\n")
    plugins, commands = Versioned(before, after), []
    def runner(args, cwd, timeout=600):
        commands.append(args[1:])
        if args[1:] == ["sync", "--inexact", "--extra", "libraries"]:
            plugins.synced = True
            return 0, "Installed 1 package"
        return 0, " Would make no changes\n" if "--dry-run" in args else "Resolved 3 packages"
    providers = lambda group: (problems or {}) if group == "optimization_framework.problems" else {}
    return Installer(workspace, development, root, runner=runner, uv="uv", plugins=plugins, problems=Problems(plugins),
                     providers=providers, validator=validator), commands


@pytest.fixture
def other(lab):
    """A second campaign of the lab, which ran bakery_greedy."""
    workspace = lab[0]
    campaign = workspace.create_campaign(CampaignInput(name="Second bakery", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Orders", problem_id="bounded_continuous", configuration={})]))
    workspace.store.put("trial", {"id": "trial_greedy", "campaign_id": campaign["id"], "algorithm": "bakery_greedy", "seed": 3,
                                  "status": "completed"})
    return campaign


def test_usage_is_lab_wide_runs_bound_proposals_and_tasks(lab, other):
    store = lab[0].store
    store.put("hypothesis", {"id": "hypothesis_bound", "campaign_id": lab[1], "algorithm": "bakery_dp", "builtin_binding_id": "b"})
    store.put("hypothesis", {"id": "hypothesis_named", "campaign_id": lab[1], "algorithm": "bakery_named"})
    assert used_methods(store) == {"bakery_greedy": [other["id"]], "bakery_dp": [lab[1]]}
    assert used_problems(store)["bounded_continuous"] == sorted([lab[1], other["id"]])


def test_a_version_that_leaves_out_a_method_another_campaign_ran_is_refused_and_the_lab_is_unchanged(lab, other):
    workspace, cid, development, root, submission = lab
    install, commands = installed(lab, ["bakery_dp", "bakery_greedy"], ["bakery_dp"], listing("bakery_dp"))
    record = request(lab, install)
    assert record["status"] == "failed" and commands == []
    assert "method bakery_greedy is left out, and Second bakery uses it" in record["error"]
    assert "give a method whose behaviour changes a new name (such as bakery_greedy_v2)" in record["error"]
    assert record["methods_kept"] == ["bakery_dp"] and record["methods_removed"] == ["bakery_greedy"]
    assert (root / "libraries/bakery/pyproject.toml").read_text() == OLD


def test_a_kept_method_another_campaign_ran_that_fails_validation_refuses_the_install(lab, other):
    install, commands = installed(lab, ["bakery_dp", "bakery_greedy"], ["bakery_dp", "bakery_greedy"],
                                  listing("bakery_dp", "bakery_greedy", failing=["bakery_greedy"]))
    record = request(lab, install)
    assert record["status"] == "failed" and commands == []
    assert "method bakery_greedy fails validation outside the box, and Second bakery uses it" in record["error"]


def test_a_version_that_leaves_out_a_problem_a_task_is_on_is_refused(lab, other):
    workspace, cid, development, root, submission = lab
    install, commands = installed(lab, ["bakery_dp"], ["bakery_dp"], listing("bakery_dp"),
                                  problems={"bounded_continuous": "bakery-search", "bakery_free": "bakery-search"})
    record = request(lab, install)
    assert record["status"] == "failed" and commands == []
    assert record["problems_removed"] == ["bakery_free", "bounded_continuous"]
    assert "problem bounded_continuous is left out" in record["error"] and "bakery_free" not in record["error"]


def test_an_unused_method_may_go_and_every_version_is_archived(lab, other):
    workspace, cid, development, root, submission = lab
    install, _ = installed(lab, ["bakery_dp", "bakery_greedy", "bakery_old"], ["bakery_dp", "bakery_greedy", "bakery_new"],
                           listing("bakery_dp", "bakery_greedy", "bakery_new"))
    record = request(lab, install)
    assert record["status"] == "installed"
    assert record["methods_kept"] == ["bakery_dp", "bakery_greedy"] and record["methods_removed"] == ["bakery_old"]
    assert record["methods_added"] == ["bakery_new"]
    assert kept_text(record) == "Of the version it replaced, it keeps 2 methods and removes bakery_old, which no campaign uses"
    # Both versions are kept in the library's repository (L2 replaced L1's folders): the replaced one, from the lab's copy,
    # imported before it was replaced, and the new one, with where it came from and what it has.
    store = repositories.path(workspace.directory, "bakery")
    old, new = repositories.versions(workspace.store, "bakery")
    assert (old["version"], old["source"]["imported"]) == ("0.1.0", "the lab's copy")
    assert old["methods"] == ["bakery_dp", "bakery_greedy", "bakery_old"]
    assert repositories.files_at(store, "v0.1.0", "bakery")["libraries/bakery/src/bakery/plugin.py"] == b"class Plugin: 'version 0.1.0'\n"
    assert new["source"]["install_id"] == record["id"] and new["source"]["commit"] == submission["commit"] and new["source"]["campaign_id"] == cid
    assert new["methods"] == ["bakery_dp", "bakery_greedy", "bakery_new"] and new["parent_version"] == "0.1.0"
    assert new["methods_added"] == ["bakery_new"] and new["methods_removed"] == ["bakery_old"]
    assert repositories.files_at(store, "v0.2.0", "bakery")["libraries/bakery/src/bakery/plugin.py"] == b"class Plugin: pass\n"
    assert record["library_version_id"] == new["id"] and record["tag"] == "v0.2.0"


def test_a_first_install_keeps_nothing_and_says_nothing_of_it(lab):
    install, _ = installed(lab, [], ["bakery_dp"], listing("bakery_dp"))
    record = request(lab, install)
    assert record["status"] == "installed" and record["methods_kept"] == [] and record["methods_removed"] == []
    assert kept_text(record) == ""
