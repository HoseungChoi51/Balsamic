"""Method libraries split off when a second problem needs them (roadmap L6, decision 26). Until then a library is one problem's
(decision 1): its methods and its problem version together.

When a method of a problem library (a package that provides a problem) is bound or run on a task whose problem that package does
not provide, a second problem needs it: Balsamic records a `library_split` (the method, its library and package, the problems
using it, the campaigns that need it) and tells the campaign's lead once; the method list shows the split as the next step.

The lead opens a split workspace (implementation_workspace_create with `split`), under a coding go-ahead like any workspace. It
starts from the problem library's latest version, and its ticket asks for a method library `libraries/<library>-methods/` that
provides the methods and no problem, and a new version of the problem library without them that depends on it. The delivery is
installed as one step (library_install.Installer): both libraries are validated outside the box, the method library takes over the
methods the split names and no others, a moved method counts as kept (L1), and the moved methods replay their recorded runs on
every problem (L4). Once installed the split is done."""
from __future__ import annotations

import logging
import re
import tomllib

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

KIND = "library_split"
OPEN = {"needed", "building"}


def method_library_name(library):
    """The directory of the method library a split makes: libraries/<library>-methods/."""
    return f"{library}-methods"


def problems_of(package):
    """The problem ids an installed package provides."""
    from .library_install import PROBLEMS, normal, providers
    return {problem for problem, distribution in providers(PROBLEMS).items() if distribution and normal(distribution) == normal(package)}


def library_of(store, package):
    """The library (its directory under libraries/) of an installed package: its latest version's, else its latest install's."""
    from . import library_repository as repositories
    from .library_install import normal
    rows = [row for row in repositories.versions(store) if row.get("package") and normal(row["package"]) == normal(package)]
    if rows:
        return rows[-1]["library"]
    installs = sorted((row for row in store.list("library_install") if row.get("status") == "installed" and row.get("package")
                       and normal(row["package"]) == normal(package)), key=lambda row: row.get("finished_at") or "")
    return installs[-1]["path"].split("/", 1)[1] if installs else None


def problem_id_of(task):
    """The problem a task is on."""
    return task.get("problem_id") or (task.get("problem") or {}).get("definition_id") or (task.get("evaluator_manifest") or {}).get("id")


def splits(store, status=None):
    return sorted((row for row in store.list(KIND) if status is None or row["status"] in ({status} if isinstance(status, str) else status)),
                  key=lambda row: row["created_at"])


def open_for(store, method_id):
    """The split a method waits for, or None."""
    return next((row for row in splits(store, OPEN) if method_id in row["methods"]), None)


def needed(workspace, campaign_id, method_id, problem_id, *, via):
    """Record that a second problem needs a problem library's method (``via``: the binding or run that shows it) and tell the lead
    once: the split, or None when the method is not a problem library's or the library provides that problem."""
    from optimization_framework.campaigns.method_catalog import package_of
    package = package_of(method_id)
    if package is None or not problem_id:
        return None
    provided = problems_of(package["name"])
    if not provided or problem_id in provided:
        return None   # a method library already, or the library's own problem
    library = library_of(workspace.store, package["name"])
    if library is None:
        return None
    store = workspace.store
    with workspace.lock:
        found = open_for(store, method_id)
        need = {"campaign_id": campaign_id, "problem_id": problem_id, "via": via, "at": now()}
        if found is not None:
            if any(row["campaign_id"] == campaign_id and row["problem_id"] == problem_id for row in found["needed_by"]):
                return found
            found = store.put(KIND, {**found, "needed_by": [*found["needed_by"], need],
                                     "problems": sorted({*found["problems"], problem_id})}, "library.split_needed")
            new = False
        else:
            found = store.put(KIND, {"id": "library_split_" + content_hash([library, method_id])[:20], "status": "needed", "methods": [method_id],
                "library": library, "package": package["name"], "version": package["version"], "method_library": method_library_name(library),
                "problems": sorted({*provided, problem_id}), "library_problems": sorted(provided), "needed_by": [need], "created_at": now()},
                "library.split_needed")
            new = True
    if new or all(row["campaign_id"] != campaign_id for row in found["needed_by"][:-1]):
        tell_lead(workspace, campaign_id, found["id"], text(found, problem_id))
    return found


def text(split, problem_id):
    methods = ", ".join(split["methods"])
    return (f"{methods} of package {split['package']} now runs on problem {problem_id}, a second problem besides "
            f"{', '.join(split['library_problems'])}: a second problem needs it (decision 26). Split it into a method package so that "
            f"neither problem's versions decide it for the other: open a split workspace with implementation_workspace_create, "
            f"split {split['id']} (it needs a coding go-ahead like any workspace). It builds libraries/{split['method_library']}/ with "
            f"{methods} and a new version of {split['package']} that depends on it. Until then {methods} keeps running from {split['package']}.")


def tell_lead(workspace, campaign_id, key, message):
    """A platform notice to the campaign's lead."""
    from .models import NOTICE
    try:
        config = workspace.pi.configuration(campaign_id)
        if not config or not config.get("enabled"):
            return
        lead = workspace.store.get(config["lead_id"], "agent_session")
        workspace.pi.enqueue(lead, "pi_library_split_" + content_hash([campaign_id, key])[:24], NOTICE + message)
    except Exception as exc:   # telling never undoes what was recorded
        logging.getLogger(__name__).warning("Telling the lead about a library split failed: %s", exc)


def noticed(workspace, campaign_id, method_id, task, *, via):
    """needed(), for a binding or run on a task; never raises."""
    try:
        return needed(workspace, campaign_id, method_id, problem_id_of(task), via=via)
    except Exception as exc:
        logging.getLogger(__name__).warning("Recording a library split need failed: %s", exc)
        return None


def depends_on(pyproject):
    """The distribution names a pyproject's project depends on, normalized."""
    from .library_install import normal
    project = tomllib.loads(pyproject.decode() if isinstance(pyproject, bytes) else pyproject).get("project") or {}
    return {normal(re.split(r"[=<>!~ ;\[(@]", item.strip(), maxsplit=1)[0]) for item in project.get("dependencies") or [] if item.strip()}


def check(split, methods_plan, problem_plan, listed):
    """What a split delivery must be (ValueError otherwise): a method library that provides no problem and every method the split
    names, takes over no other method of the problem library, and a problem library version that depends on it.
    ``listed``: the methods validation outside the box listed for the method library."""
    from .library_install import normal
    if methods_plan["problem_entry_points"]:
        raise ValueError(f"libraries/{methods_plan['name']} provides problems ({', '.join(sorted(methods_plan['problem_entry_points']))}): "
                         "a method library provides methods only")
    missing = sorted(set(split["methods"]) - set(listed))
    if missing:
        raise ValueError(f"libraries/{methods_plan['name']} does not provide {', '.join(missing)}, which the split moves into it")
    if normal(problem_plan["package"]) != normal(split["package"]):
        raise ValueError(f"The split delivers {problem_plan['package']}, not a new version of {split['package']}")
    if normal(methods_plan["package"]) not in depends_on(problem_plan["files"][f"libraries/{problem_plan['name']}/pyproject.toml"]):
        raise ValueError(f"{problem_plan['package']} {problem_plan['version']} does not depend on {methods_plan['package']}: list it in "
                         "its project dependencies")


def takeovers(old_methods, listed, split):
    """ValueError when the method library takes over a method of the problem library the split does not name."""
    taken = sorted((set(old_methods) & set(listed)) - set(split["methods"]))
    if taken:
        raise ValueError(f"The method library takes over {', '.join(taken)} from {split['package']}, which the split does not move: a "
                         f"split moves only {', '.join(split['methods'])}. Leave the others in {split['package']}, or give a new method a new name")
