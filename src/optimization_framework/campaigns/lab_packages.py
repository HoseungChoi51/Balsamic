"""What code the lab has, for every campaign (issue #101): each installed package with its versions, methods and problems and
the campaigns its versions came from, the building blocks of the shared library repository, and which of them concern a
campaign's problem.

Before this a campaign saw another campaign's library only as a method name, and nothing at all of a library whose methods
did not fit its tasks, so a second campaign on the same problem found nothing and asked the researcher for ids. The lead reads
listing() with the lab_packages tool; its state block names the matches every turn (balsamic/lead/state.py); and the
researcher and the lead are told once per campaign and package version when one concerns the campaign (tell()).

A package concerns a campaign when it provides a problem the campaign's charter or tasks name, when its library carries the
name of such a problem (a coding workspace names its library after the problem it builds for), or when one of its methods runs
on a current task. Reuse needs no id from the researcher: bind a method that runs here (implementation.bind_builtin), adopt a
provided problem (campaign.adopt_problem with the version's library_version_id), or let a coding workspace build on it.
"""
from __future__ import annotations

import logging

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

NOTICE_KIND = "package_notice"
REUSE = ("Reuse needs no id from the researcher. Bind a method that runs here to a proposal with implementation.bind_builtin "
         "{hypothesis_id, task_id, algorithm} (reuse, no coding time); adopt a provided problem with campaign.adopt_problem "
         "{library_version_id}; a coding workspace on a problem whose library is installed builds on its latest version. A "
         "coding box imports the shared repository's building blocks (listed with their signatures; its TASK.md names them): a "
         "library written around them names them in its dependencies and never copies them.")


def not_a_service_version(operation, version_id):
    """implementation.attach and evaluator.attach take a version of the implementation service; an installed package's id
    (library_version_..., library_install_...) is refused with the command that reuses it."""
    if not str(version_id).startswith(("library_version_", "library_install_")):
        return
    instead = ("bind one of its methods to the proposal with implementation.bind_builtin {hypothesis_id, task_id, algorithm}"
               if operation == "implementation.attach" else
               f"adopt the problem it provides with campaign.adopt_problem {{{'library_version_id' if version_id.startswith('library_version_') else 'install_id'}: "
               f"{version_id}}}")
    raise ValueError(f"{version_id} is an installed package, not a version of the implementation service that {operation} attaches: "
                     f"{instead}. lab_packages lists its methods, problems and where they run.")


def normal(value):
    import re
    return re.sub(r"[-_.]+", "-", str(value or "")).lower()


def problem_ids(workspace, campaign):
    """The problem ids a campaign names: its charter's evaluator and its current tasks."""
    ids = set()
    charter = campaign.get("charter")
    if charter:
        try:
            binding = workspace.charters.revision(charter["id"], charter["revision"])["charter"].get("evaluator") or {}
        except (AttributeError, KeyError, ValueError):
            binding = {}
        if binding.get("problem_id"):
            ids.add(binding["problem_id"])
    ids |= {task["problem_id"] for task in workspace.current_tasks(campaign["id"]) if task.get("problem_id")}
    return ids


def _campaigns(store):
    names = {}
    def name(campaign_id):
        if campaign_id not in names:
            try:
                names[campaign_id] = store.get(campaign_id, "campaign").get("name") or campaign_id
            except KeyError:
                names[campaign_id] = campaign_id
        return {"id": campaign_id, "name": names[campaign_id]}
    return name


def listing(workspace, campaign_id=None, *, root=None, blocks=True):
    """{packages, building_blocks, shared_repository, reuse}: every library the lab has a version of, newest version first in
    each, with, for a campaign, where its methods run and why it concerns the campaign (``concerns``, empty when it does not).
    The building blocks are read from the shared library repository unless ``blocks`` is false."""
    from optimization_framework.agents import library_repository, shared_libraries
    from optimization_framework.agents.development_runtime import ROOT
    from optimization_framework.agents.library_install import PROBLEMS, providers
    from optimization_framework.optimizers import plugins
    from optimization_framework.optimizers.registry import capability_reason
    store, root = workspace.store, root or ROOT
    campaign = store.get(campaign_id, "campaign") if campaign_id else None
    ids = problem_ids(workspace, campaign) if campaign else set()
    tasks = [task for task in workspace.current_tasks(campaign_id) if task.get("problem")] if campaign else []
    loaded = {method["id"] for method in plugins.installed.methods()}
    loaded_problems = providers(PROBLEMS)
    name_of, rows = _campaigns(store), []
    for library in library_repository.catalog(store)["libraries"]:
        history = library_repository.versions(store, library["name"])
        last = history[-1]
        sources = list(dict.fromkeys(row["source"].get("campaign_id") for row in reversed(history) if (row.get("source") or {}).get("campaign_id")))
        methods = []
        for method in last["methods"]:
            reasons = [capability_reason(method, task["problem"]) for task in tasks] if method in loaded else []
            methods.append({"id": method, "loaded": method in loaded, "runs_on_task_ids": [task["id"] for task, why in zip(tasks, reasons) if why is None],
                            **({"why_not_here": next((why for why in reasons if why), None)} if tasks and None not in reasons else {})})
        problems = [{"id": problem, "loaded": normal(loaded_problems.get(problem)) == normal(last["package"]), "named_here": problem in ids}
                    for problem in last["problems"]]
        concerns = [f"provides problem {row['id']}, which this campaign names" for row in problems if row["named_here"]]
        concerns += [f"built for problem {problem} (its library carries the problem's name)" for problem in sorted(ids)
                     if normal(problem) == normal(library["name"]) and problem not in last["problems"]]
        runnable = [row["id"] for row in methods if row["runs_on_task_ids"]]
        if runnable:
            concerns.append("its methods " + ", ".join(runnable) + " run on this campaign's tasks")
        rows.append({"library": library["name"], "package": last["package"], "version": last["version"], "tag": last["tag"],
                     "commit": last["commit"], "library_version_id": last["id"], "install_id": (last.get("source") or {}).get("install_id"),
                     "kind": library["kind"], "versions": [row["version"] for row in reversed(history)],
                     "from_campaigns": [name_of(value) for value in sources], "methods": methods, "problems": problems,
                     "depends_on": library.get("depends_on") or [], **({"concerns": concerns} if campaign else {})})
    if campaign:
        rows.sort(key=lambda row: (not row["concerns"], row["library"]))
    repository = shared_libraries.location(root)
    try:
        shared = shared_libraries.packages(repository) if blocks else []
    except ValueError as exc:   # a broken shared repository never hides what the lab has
        logging.getLogger(__name__).warning("Reading the shared library repository failed: %s", exc)
        shared = []
    in_lab = {normal(row["package"]) for row in rows}
    found = [{"package": row["package"], "version": row["latest"], "tag": row["tag"], "family": row["family"],
               "description": row["description"], "in_lab": normal(row["package"]) in in_lab,
               "functions": [{"signature": block["signature"], "doc": block["doc"], "module": block["module"]} for block in row["blocks"]]}
              for row in shared if row["blocks"]]
    return {"packages": rows, "building_blocks": found, "shared_repository": str(repository) if repository else None, "reuse": REUSE}


def matches(workspace, campaign_id, *, root=None):
    """The packages of listing() that concern a campaign, but for those only it built: its own install notice told of them."""
    own = lambda row: bool(row["from_campaigns"]) and all(item["id"] == campaign_id for item in row["from_campaigns"])
    return [row for row in listing(workspace, campaign_id, root=root, blocks=False)["packages"] if row.get("concerns") and not own(row)]


def line(row):
    """One package as the lead's state block and the notices name it."""
    sources = ", ".join(item["name"] for item in row["from_campaigns"]) or "the lab"
    return (f"{row['package']} {row['version']} ({row['library_version_id']}, from {sources}): " + "; ".join(row["concerns"]))


def tell(workspace, campaign_id, *, root=None):
    """Tell the researcher (one line in the campaign's conversation) and the lead (a platform notice) about each package that
    concerns the campaign, once per package version; never raises. The package versions told."""
    try:
        found = matches(workspace, campaign_id, root=root)
    except Exception as exc:
        logging.getLogger(__name__).warning("Matching the lab's packages to %s failed: %s", campaign_id, exc)
        return []
    told = []
    for row in found:
        identity = NOTICE_KIND + "_" + content_hash([campaign_id, row["library_version_id"]])[:24]
        try:
            workspace.store.get(identity, NOTICE_KIND)
            continue
        except KeyError:
            pass
        text = f"Installed in the lab and relevant here: {line(row)}."
        with workspace.lock, workspace.store.transaction():
            workspace.store.put(NOTICE_KIND, {"id": identity, "campaign_id": campaign_id, "library_version_id": row["library_version_id"],
                                              "package": row["package"], "version": row["version"], "concerns": row["concerns"], "created_at": now()},
                                "library.package_noticed")
            workspace.store.put("message", {"id": "message_" + identity, "campaign_id": campaign_id, "role": "assistant", "origin": "lab_event",
                                            "kind": NOTICE_KIND, "content": text + " The lead can reuse it without new code.", "created_at": now()},
                                "message.created")
        try:
            from optimization_framework.agents.models import NOTICE
            config = workspace.pi.configuration(campaign_id) if getattr(workspace, "pi", None) else None
            if config and config.get("enabled"):
                lead = workspace.store.get(config["lead_id"], "agent_session")
                workspace.pi.enqueue(lead, "pi_" + identity, NOTICE + text + " Read it with lab_packages. " + REUSE)
        except Exception as exc:   # telling the lead never undoes the record
            logging.getLogger(__name__).warning("Telling the lead about %s failed: %s", row["package"], exc)
        told.append(row["library_version_id"])
    return told
