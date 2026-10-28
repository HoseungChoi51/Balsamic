"""The shared library repository (issue #101): one Git repository, outside every checkout and data folder, holding each code
library as a package directory with one tag per version.

The lab's own repositories (agents/library_repository.py, roadmap L2) live in its data folder, and the lab's copy of a library
in one checkout's `libraries/<name>/`, so a new checkout, a rebuilt environment or a new data folder started without them. The
shared repository is the durable copy. Each install publishes the version it tagged (publish()): the files of
`libraries/<name>/` go to `<repository>/<name>/` as one commit on the repository's branch, tagged `<name>-v<version>`. A lab
restores from it what a checkout lacks (library_install.restore()). It also holds packages written by hand, such as the
building blocks a campaign's library is written around (`permutation-scheduling`); packages() lists every package with its
methods, problems and public functions, read from the code, for the agents and the Packages page.

Where: BALSAMIC_LIBRARY_REPOSITORY (a Git work tree, or `off` for none), else `balsamic-libraries` beside the checkout when that
is a Git work tree. Balsamic commits only a library's own directory and only when it holds no uncommitted change, never runs the
repository's hooks or the researcher's Git configuration, and never pushes: where the repository goes from here is the
researcher's choice.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import threading
import tomllib
from pathlib import Path, PurePosixPath

from .own_session import SAFE, _env

SETTING = "BALSAMIC_LIBRARY_REPOSITORY"
DEFAULT_NAME = "balsamic-libraries"
METHODS, PROBLEMS = "optimization_framework.optimizers", "optimization_framework.problems"
AUTHOR = {"GIT_AUTHOR_NAME": "Balsamic", "GIT_AUTHOR_EMAIL": "balsamic@localhost",
          "GIT_COMMITTER_NAME": "Balsamic", "GIT_COMMITTER_EMAIL": "balsamic@localhost"}
_lock = threading.RLock()


def location(root):
    """The shared repository's work tree, or None: BALSAMIC_LIBRARY_REPOSITORY, else balsamic-libraries beside the checkout."""
    setting = os.environ.get(SETTING, "").strip()
    if setting.lower() in {"off", "none", "false"}:
        return None
    path = Path(setting).expanduser() if setting else Path(root).resolve().parent / DEFAULT_NAME
    return path if (path / ".git").exists() else None


def tag_of(name, version):
    return f"{name}-v{version}"


def git(repository, *args, input=None, env=None):
    done = subprocess.run(["git", "--no-replace-objects", "-C", str(repository), *SAFE, *args], input=input, capture_output=True,
                          timeout=120, env=_env(env))
    if done.returncode:
        raise ValueError((done.stderr.decode(errors="replace").strip() or f"git {args[0]} failed")[-1000:])
    return done.stdout


def _ref(repository, ref):
    try:
        return git(repository, "rev-parse", "--verify", "--quiet", ref + "^{commit}").decode().strip() or None
    except ValueError:
        return None


def files_at(repository, ref, name):
    """{libraries/<name>/<path>: bytes} of a package directory at a commit or tag; {} when the commit has no such directory."""
    listing = git(repository, "ls-tree", "-r", "-z", ref, "--", name).decode()
    found = {}
    for item in filter(None, listing.split("\0")):
        meta, path = item.split("\t", 1)
        if meta.split()[1] != "blob":
            continue
        found[f"libraries/{name}/{PurePosixPath(path).relative_to(name).as_posix()}"] = git(repository, "cat-file", "blob", meta.split()[2])
    return found


def versions(repository, name):
    """[(version, tag)] of a package directory, oldest first: by version number, or by the tagged commit's date when a version
    is not a release number."""
    from packaging.version import InvalidVersion, Version
    lines = git(repository, "for-each-ref", "--sort=creatordate", "--format=%(refname:strip=2)", f"refs/tags/{name}-v*").decode().split()
    found = [(tag[len(name) + 2:], tag) for tag in lines if tag.startswith(f"{name}-v")]
    try:
        return sorted(found, key=lambda row: Version(row[0]))
    except InvalidVersion:
        return found


def publish(repository, name, files, version, message):
    """Commit a version's files ({libraries/<name>/<path>: bytes}) as `<name>/` of the shared repository and tag it
    `<name>-v<version>`: {repository, branch, commit, tag, created}. The version's tag already holding the same files is no
    change (created false). ValueError, and nothing changed, when the tag holds other code, the repository is not on a branch,
    or `<name>/` has changes of the researcher's own."""
    prefix, tag = f"libraries/{name}/", tag_of(name, version)
    wanted = {path[len(prefix):]: content for path, content in files.items() if path.startswith(prefix)}
    with _lock:
        branch = git(repository, "symbolic-ref", "-q", "--short", "HEAD").decode().strip()
        existing = _ref(repository, "refs/tags/" + tag)
        if existing:
            if {path[len(prefix):]: content for path, content in files_at(repository, existing, name).items()} != wanted:
                raise ValueError(f"{tag} of the shared library repository holds other code; a version, once published, never changes")
            return {"repository": str(repository), "branch": branch, "commit": existing, "tag": tag, "created": False}
        if git(repository, "status", "--porcelain", "--untracked-files=all", "--", name).strip():
            raise ValueError(f"{name}/ of the shared library repository has uncommitted changes; commit or remove them, and Balsamic "
                             "publishes the next version")
        folder = Path(repository) / name
        for path in git(repository, "ls-files", "-z", "--", name).decode().split("\0"):
            if path and PurePosixPath(path).relative_to(name).as_posix() not in wanted:
                (Path(repository) / path).unlink()
        for path, content in wanted.items():
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        git(repository, "add", "-A", "--", name)
        if _staged(repository, name):   # the same files as the branch already has need no commit, only the tag
            git(repository, "commit", "-q", "-m", message, "--only", "--", name, env=AUTHOR)
        made = _ref(repository, "HEAD")
        git(repository, "tag", tag, made)
        return {"repository": str(repository), "branch": branch, "commit": made, "tag": tag, "created": True}


def _staged(repository, name):
    """Whether `<name>/` has staged changes against HEAD (a first commit always does)."""
    if not _ref(repository, "HEAD"):
        return True
    done = subprocess.run(["git", "-C", str(repository), *SAFE, "diff", "--cached", "--quiet", "--", name], capture_output=True,
                          timeout=60, env=_env())
    return done.returncode == 1


# What a package holds, read from its code ---------------------------------------------------------------------------------
def project(files, name):
    """The [project] table of a package's pyproject.toml ({} when it has none)."""
    text = files.get(f"libraries/{name}/pyproject.toml")
    try:
        return (tomllib.loads(text.decode()) if text else {}).get("project") or {}
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def _signature(node):
    arguments = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{node.name}({arguments}){returns}"


def blocks(files, name):
    """The package's public functions and classes, read from its source without importing it: [{name, kind, signature, doc,
    module}], doc being the docstring's first line (None when it has none). Public is what the package's __init__ lists in
    __all__, else every top-level name of its modules without a leading underscore."""
    sources = {path: content for path, content in files.items() if path.endswith(".py") and "/tests/" not in path
               and not PurePosixPath(path).name.startswith(("test_", "conftest"))
               and (PurePosixPath(path).name == "__init__.py" or not PurePosixPath(path).name.startswith("_"))}
    exported, found = None, []
    for path, content in sorted(sources.items()):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        if PurePosixPath(path).name == "__init__.py":
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                    try:
                        exported = set(ast.literal_eval(node.value)) | (exported or set())
                    except ValueError:
                        pass
            continue
        module = ".".join(PurePosixPath(path).with_suffix("").parts[2:])
        module = re.sub(r"^src\.", "", module)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
                doc = ast.get_docstring(node)
                signature = _signature(node) if isinstance(node, ast.FunctionDef) else node.name + next(
                    (_signature(item)[len("__init__"):] for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "__init__"), "()")
                found.append({"name": node.name, "kind": "class" if isinstance(node, ast.ClassDef) else "function", "signature": signature,
                              "doc": doc.strip().splitlines()[0] if doc else None, "module": module})
    return [row for row in found if exported is None or row["name"] in exported]


def module_of(files, name):
    """(the package's import name, the folder it imports from: "src" or ""), from its files; (None, "") when it has no package."""
    for layout in ("src", ""):
        prefix = f"libraries/{name}/" + (layout + "/" if layout else "")
        found = sorted(PurePosixPath(path[len(prefix):]).parts[0] for path in files
                       if path.startswith(prefix) and PurePosixPath(path[len(prefix):]).parts[1:] == ("__init__.py",))
        found = [module for module in found if module not in {"tests", "tools"}]
        if found:
            return found[0], layout
    return None, ""


def describe(files, name):
    """{package, version, description, family, module, layout, plugins (entry point names), problems, dependencies, blocks} of a
    package's files."""
    meta = project(files, name)
    groups = meta.get("entry-points") or {}
    text = files.get(f"libraries/{name}/pyproject.toml")
    try:
        family = ((tomllib.loads(text.decode()).get("tool") or {}).get("balsamic") or {}).get("family") if text else None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        family = None
    module, layout = module_of(files, name)
    return {"package": meta.get("name"), "version": str(meta.get("version") or ""), "description": meta.get("description"),
            "family": family, "module": module, "layout": layout, "plugins": sorted(groups.get(METHODS) or {}), "problems": sorted(groups.get(PROBLEMS) or {}),
            "dependencies": list(meta.get("dependencies") or []), "blocks": blocks(files, name)}


def packages(repository):
    """Every package directory of the shared repository with a tagged version: [{name, latest, tag, commit, versions, package,
    version, description, family, plugins, problems, dependencies, blocks}], read at its latest tag."""
    if repository is None:
        return []
    tags = git(repository, "for-each-ref", "--format=%(refname:strip=2)", "refs/tags/").decode().split()
    names = sorted({match.group(1) for tag in tags if (match := re.fullmatch(r"(.+)-v(\d.*)", tag))})
    rows = []
    for name in names:
        tagged = versions(repository, name)
        if not tagged:
            continue
        version, tag = tagged[-1]
        files = files_at(repository, tag, name)
        if not files:
            continue
        rows.append({"name": name, "latest": version, "tag": tag, "commit": _ref(repository, "refs/tags/" + tag),
                     "versions": [row[0] for row in tagged], **describe(files, name)})
    return rows


def building_blocks(root, exclude=()):
    """The shared repository's packages a coding box imports (issue #101): those with neither methods nor problems, at their latest
    tags, other than the libraries named in ``exclude``; each {name, package, version, tag, commit, module, layout, description,
    family, functions}. [] without a repository or when it cannot be read."""
    repository = location(root)
    try:
        rows = packages(repository)
    except ValueError:
        return []
    return [{"name": row["name"], "package": row["package"], "version": row["latest"], "tag": row["tag"], "commit": row["commit"],
             "module": row["module"], "layout": row["layout"], "description": row["description"], "family": row["family"],
             "functions": [{"signature": block["signature"], "doc": block["doc"]} for block in row["blocks"]]}
            for row in rows if not row["plugins"] and not row["problems"] and row["module"] and row["name"] not in set(exclude)]


def normal(value):
    return re.sub(r"[-_.]+", "-", str(value)).lower()


def requirement_name(requirement):
    return normal(re.split(r"[=<>!~ ;\[(@]", requirement.strip(), maxsplit=1)[0])
