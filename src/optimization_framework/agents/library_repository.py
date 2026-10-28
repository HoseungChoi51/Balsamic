"""One Git repository per code library (roadmap L2): a library's history as one line of tagged versions.

Balsamic keeps a bare repository per library on the host, `<data>/library_repositories/<name>.git`, which no box mounts. Each
install commits the version's files (as `libraries/<name>/` holds them, at the repository's root) onto `main` as Balsamic's own
commit, with where it came from in the message, and tags it `v<version>`; the lab's copy is a checkout of that tag. Each version
is a `library_version` record: library, package, version, tag and commit, the version before it, where it came from (campaign,
workspace, submission, install, source commit), its methods and problems and what it added and removed. A library the lab had
before L2 (archived by L1 in `<data>/library_archive/<name>/<version>/`, or the lab's own copy) is imported as its first
versions, once.

Git runs on the host's own store only, as agents/own_session.py runs it: no system or user configuration, hooks or upkeep.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path, PurePosixPath

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

from .own_session import _env, _git, _tree

KIND = "library_version"
_lock = threading.RLock()


def tag_of(version):
    return "v" + version


def version_id(name, version):
    return "library_version_" + content_hash([name, version])[:24]


def path(directory, name):
    return Path(directory) / "library_repositories" / f"{name}.git"


def repository(directory, name):
    """The library's bare repository, made on first use."""
    import subprocess
    store = path(directory, name)
    if not (store / "HEAD").exists():
        store.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(store)], capture_output=True, timeout=60,
                              env=_env(), cwd=store.parent)
        if done.returncode:
            raise ValueError("Making the library's repository failed: " + done.stderr.decode(errors="replace")[-500:])
    return store


def _ref(store, ref):
    """The commit a ref names, or None."""
    try:
        return _git(store, "rev-parse", "--verify", "--quiet", ref + "^{commit}").decode().strip() or None
    except ValueError:
        return None


def files_at(store, ref, name):
    """{libraries/<name>/<path>: bytes} of a commit or tag of the library's repository."""
    listing = _git(store, "ls-tree", "-r", "-z", "--full-tree", ref).decode()
    found = {}
    for item in filter(None, listing.split("\0")):
        meta, relative = item.split("\t", 1)
        found[f"libraries/{name}/{relative}"] = _git(store, "cat-file", "blob", meta.split()[2])
    return found


def commit(directory, name, files, message):
    """A commit of the library's files ({libraries/<name>/<path>: bytes}) on top of main, not yet on any ref: (store, commit).
    The install names it on main and tags it once the version is in the lab (publish())."""
    prefix = f"libraries/{name}/"
    root = {}
    for item, content in files.items():
        relative = PurePosixPath(item[len(prefix):] if item.startswith(prefix) else item)
        node = root
        for folder in relative.parts[:-1]:
            node = node.setdefault(folder, {})
        node[relative.parts[-1]] = content
    with _lock:
        store = repository(directory, name)
        tree = _tree(store, root)
        parent = _ref(store, "refs/heads/main")
        stamp = now()
        env = {"GIT_AUTHOR_NAME": "Balsamic", "GIT_AUTHOR_EMAIL": "balsamic@localhost", "GIT_AUTHOR_DATE": stamp,
               "GIT_COMMITTER_NAME": "Balsamic", "GIT_COMMITTER_EMAIL": "balsamic@localhost", "GIT_COMMITTER_DATE": stamp}
        made = _git(store, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", message, env=env).decode().strip()
    return store, made


def check_tag(store, made, version):
    """The commit already tagged v<version> when it holds the same files as ``made`` (None when there is none); ValueError when
    the tag holds other code: a version, once installed, never changes."""
    existing = _ref(store, "refs/tags/" + tag_of(version))
    if existing and _git(store, "rev-parse", existing + "^{tree}") != _git(store, "rev-parse", made + "^{tree}"):
        raise ValueError(f"Version {version} was installed before with other code (tag {tag_of(version)} of the library's repository); "
                         "raise the version")
    return existing


def publish(store, made, version):
    """Name a commit main's tip and tag it v<version>: the tagged commit (the earlier one when the tag holds the same files)."""
    with _lock:
        tag = tag_of(version)
        existing = check_tag(store, made, version)
        if existing:
            return existing
        _git(store, "update-ref", "refs/tags/" + tag, made)
        _git(store, "update-ref", "refs/heads/main", made)
        return made


def record(store_records, name, package, version, made, *, source, methods, problems, at=None, depends_on=(), moved=None):
    """The library_version record of a version just tagged, with the version before it and what it added and removed; for a split
    (roadmap L6) the method packages it depends on (``depends_on``) and the methods it moved there (``moved``: {package, methods})."""
    previous = latest(store_records, name)
    previous = previous if previous and previous["version"] != version else None
    before_methods, before_problems = set((previous or {}).get("methods") or []), set((previous or {}).get("problems") or [])
    row = {"id": version_id(name, version), "library": name, "package": package, "version": version, "tag": tag_of(version),
           "commit": made, "parent_id": previous["id"] if previous else None, "parent_version": previous["version"] if previous else None,
           "source": source, "methods": sorted(methods), "problems": sorted(problems),
           "methods_added": sorted(set(methods) - before_methods), "methods_removed": sorted(before_methods - set(methods)),
           "problems_added": sorted(set(problems) - before_problems), "problems_removed": sorted(before_problems - set(problems)),
           "created_at": at or now(), **({"depends_on": sorted(depends_on)} if depends_on else {}), **({"moved": moved} if moved else {})}
    return store_records.put(KIND, row, "library.version_recorded")


def versions(store_records, name=None):
    """The library_version records of a library (of every library without a name), oldest first."""
    rows = [row for row in store_records.list(KIND) if name is None or row["library"] == name]
    return sorted(rows, key=lambda row: (row["created_at"], row["id"]))


def latest(store_records, name):
    rows = versions(store_records, name)
    return rows[-1] if rows else None


def imported(directory, store_records, name, lab_copy=None):
    """Import what the lab had of a library before its repository, once: L1's archived versions in the order they were
    archived, then the lab's copy (``lab_copy``: {package, version, files, methods, problems}) when its version is not among
    them. Nothing when the library already has a version."""
    if versions(store_records, name):
        return []
    found = []
    archived = Path(directory) / "library_archive" / name
    for folder in sorted(archived.glob("*/version.json"), key=lambda item: json.loads(item.read_text()).get("archived_at") or ""):
        meta = json.loads(folder.read_text())
        files = {f"libraries/{name}/{item.relative_to(folder.parent / 'files').as_posix()}": item.read_bytes()
                 for item in sorted((folder.parent / "files").rglob("*")) if item.is_file()}
        found.append({"package": meta.get("package"), "version": str(meta.get("version") or folder.parent.name), "files": files,
                      "methods": meta.get("methods") or [], "problems": meta.get("problems") or [],
                      "source": {key: meta.get(key) for key in ("install_id", "campaign_id", "workspace_id", "submission_id", "commit")
                                 if meta.get(key)} | {"imported": "archive"}, "at": meta.get("archived_at")})
    if lab_copy and lab_copy["version"] not in {row["version"] for row in found}:
        found.append({**lab_copy, "source": {"imported": "the lab's copy"}, "at": None})
    rows = []
    for item in found:
        if not item["package"] or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,63}", item["version"]):
            continue
        store, made = commit(directory, name, item["files"], f"{item['package']} {item['version']}\n\nImported: {item['source']['imported']}.")
        made = publish(store, made, item["version"])
        rows.append(record(store_records, name, item["package"], item["version"], made, source=item["source"], methods=item["methods"],
                           problems=item["problems"], at=item["at"]))
    return rows


# What the Packages page shows ---------------------------------------------------------------------------------------------------
def _public(row):
    return {key: row.get(key) for key in ("id", "version", "tag", "commit", "parent_version", "source", "methods", "problems",
                                          "methods_added", "methods_removed", "problems_added", "problems_removed", "depends_on", "moved", "created_at",
                                          "published")}


def _links(store_records):
    """{library: (the packages its latest version depends on, the libraries whose latest version depends on it)} (roadmap L6)."""
    from .library_install import normal
    latest_rows = {name: versions(store_records, name)[-1] for name in {row["library"] for row in versions(store_records)}}
    by_package = {normal(row["package"]): name for name, row in latest_rows.items() if row.get("package")}
    links = {name: ([], []) for name in latest_rows}
    for name, row in latest_rows.items():
        for package in row.get("depends_on") or []:
            links[name][0].append(package)
            if normal(package) in by_package:
                links[by_package[normal(package)]][1].append(latest_rows[name]["package"])
    return links


def catalog(store_records):
    """Every library with a version: {libraries: [{name, package, kind, latest, versions, methods, problems, depends_on, used_by,
    updated_at}]}; a method library (kind method) provides no problem."""
    names = sorted({row["library"] for row in versions(store_records)})
    links, rows = _links(store_records), []
    for name in names:
        history = versions(store_records, name)
        last = history[-1]
        rows.append({"name": name, "package": last["package"], "kind": "problem" if last["problems"] else "method", "latest": last["version"],
                     "versions": len(history), "methods": last["methods"], "problems": last["problems"],
                     "depends_on": sorted(links[name][0]), "used_by": sorted(links[name][1]), "updated_at": last["created_at"]})
    return {"libraries": rows}


def detail(store_records, name):
    """One library: its versions newest first, and each method and problem it ever had with the version that brought it, whether
    the latest version has it, and the campaigns that use it. KeyError for a library with no version."""
    from .library_usage import used_methods, used_problems
    history = versions(store_records, name)
    if not history:
        raise KeyError(name)
    names = {}
    def campaigns(ids):
        found = []
        for campaign_id in ids:
            if campaign_id not in names:
                try:
                    names[campaign_id] = store_records.get(campaign_id, "campaign").get("name") or campaign_id
                except KeyError:
                    names[campaign_id] = campaign_id
            found.append({"id": campaign_id, "name": names[campaign_id]})
        return found
    def items(key, used):
        since = {}
        for row in history:
            for item in row[key]:
                since.setdefault(item, row["version"])
        return [{"id": item, "since": first, "in_latest": item in history[-1][key], "campaigns": campaigns(used.get(item, []))}
                for item, first in sorted(since.items())]
    links = _links(store_records)[name]
    return {"name": name, "package": history[-1]["package"], "latest": history[-1]["version"],
            "kind": "problem" if history[-1]["problems"] else "method", "depends_on": sorted(links[0]), "used_by": sorted(links[1]),
            "versions": [_public(row) for row in reversed(history)],
            "methods": items("methods", used_methods(store_records)), "problems": items("problems", used_problems(store_records))}
