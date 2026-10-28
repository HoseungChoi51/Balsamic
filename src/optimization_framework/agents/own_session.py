"""Bring your own session (roadmap H3): the researcher delivers a coding workspace's library from their own coding agent, on
their own machine, with `balsamic-workspace` run outside the box.

The token. The researcher makes one on the workspace's card (`issue()`). It is in that answer only: Balsamic keeps its
SHA-256 (`development_session_token`, one per workspace), so no record, event or notice, and nothing an agent reads, holds the
token itself. Making another replaces it. It opens nothing while the workspace is stopped, and a token made before the
workspace's latest stop stays revoked after a resume. Every route that takes it (`Authorization: Bearer <token>`) answers
401 to any other token, or none, before it reads anything else.

The library. `balsamic-workspace clone` fetches the workspace's start (`start()`): the library generated from its campaign's
charter (roadmap F4), or the installed version it builds on (L3), byte for byte what the box started from, as one commit holding `libraries/<name>/`, in a Git bundle.

The delivery. `balsamic-workspace submit` sends a commit as a Git bundle (`deliver()`), taken only while the workspace runs
(`closed()`: a paused one, at its deadline among others, waits for its resume, as its coding agent does). The host checks
that the bundle carries that commit, fetches it into a store of its own beside the box's (`own/git`, which the box never
mounts; the box's store is only its alternate, so a bundle may build on the box's commits), and captures it as the box's
submissions are captured (`DevelopmentWorkspaces.capture_submission()`): the exact commit's manifest and files, never loose
files, with its delivery report. From there nothing asks who wrote it: Balsamic installs it at its next sync, reading that
exact commit (`library_install.Installer.files()`), and binds the proposals it serves and starts the approved runs, citing
the install, as for the coding agent's delivery. The submission records `source: own_session`.

Git runs on the host's own store only, without the system's or the user's configuration, hooks or background upkeep, and
checks every object a bundle brings; the box's store is never run as a repository here (its refs are read as files).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import tempfile
import threading
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, Request
from pydantic import Field, ValidationError

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now

KIND = "development_session_token"
SOURCE = "own_session"
PREFIX = "bws_"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_BODY_BYTES = MAX_BUNDLE_BYTES * 4 // 3 + 1024 * 1024   # the bundle in base64, and the report beside it
MAX_FILE_BYTES = 1024 * 1024   # a package file, as DockerWorkspace.snapshot() reads them
HASH = re.compile(r"[a-f0-9]{40}")
SAFE = ["-c", "core.hooksPath=" + os.devnull, "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-c", "transfer.fsckObjects=true"]
# The start commit's author and time are fixed, so the same library always gives the same commit.
START = {"GIT_AUTHOR_NAME": "Balsamic", "GIT_AUTHOR_EMAIL": "balsamic@localhost", "GIT_AUTHOR_DATE": "1980-01-01T00:00:00+00:00",
         "GIT_COMMITTER_NAME": "Balsamic", "GIT_COMMITTER_EMAIL": "balsamic@localhost", "GIT_COMMITTER_DATE": "1980-01-01T00:00:00+00:00"}
_lock = threading.Lock()


class Refused(PermissionError):
    """The token does not open the workspace (answered 401, before anything else is read)."""


class OwnSubmission(Contract):
    """What `balsamic-workspace submit` sends from outside the box: the box's submission and the bundle that carries it."""
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    manifest_path: str = Field(default="implementation-manifest.json", min_length=1, max_length=500)
    notes: str = Field(default="", max_length=10000)
    report: dict
    bundle: str = Field(min_length=1, description="The Git bundle, base64")


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def identity(workspace_id):
    return "development_session_token_" + content_hash(workspace_id)[:24]


def revoked(store, record, saved):
    """Why the token no longer opens the workspace (it is stopped, or was stopped after the token was made); None while it does."""
    if record.get("desired_status") == "stopped":
        return "the workspace is stopped"
    if any(command["workspace_id"] == record["id"] and command.get("operation") == "stop" and command.get("recorded")
           and command["created_at"] >= saved["issued_at"] for command in store.list("development_command", record["campaign_id"])):
        return "the workspace was stopped after it was made"
    return None


def closed(record):
    """Why the workspace takes no delivery now, or None. A delivery goes on the workspace's work, so it needs the workspace
    running: one paused at its deadline (roadmap H5), at its CPU allowance or by the researcher waits for its resume, which for
    a deadline is a new go-ahead. The box's walls themselves (egress, limits) bound the box, not the researcher's machine."""
    from .development import past
    if record.get("desired_status") == "stopped":
        return "The workspace is stopped"
    if record.get("deadline_reached") or past(record.get("deadline_at")):
        return ("The workspace reached its deadline and is paused: going on is a new go-ahead. Resume it with a new deadline "
                "before delivering to it")
    if record.get("desired_status") != "running":
        return "The workspace is paused" + (f" ({record['error']})" if record.get("error") else "") + ": resume it before delivering to it"
    return None


def issue(development, campaign_id, workspace_id):
    """A new token for the workspace, which replaces the one before it: {token, issued_at, workspace_id}. The token is in this
    answer only. Refused while the workspace is stopped."""
    store = development.store
    with development.workspace.lock, store.transaction():
        record = development.get(campaign_id, workspace_id)
        if record.get("desired_status") == "stopped":
            raise ValueError("The workspace is stopped: resume it before delivering to it from your own session")
        token = PREFIX + secrets.token_urlsafe(32)
        # No journal event: the record is the card's to read, through view().
        saved = store.put(KIND, {"id": identity(workspace_id), "campaign_id": campaign_id, "workspace_id": workspace_id,
                                 "digest": digest(token), "issued_at": now(), "last_used_at": None})
    return {"token": token, "issued_at": saved["issued_at"], "workspace_id": workspace_id}


def view(development, campaign_id, workspace_id):
    """The token's state for the card, never the token: {issued_at, last_used_at, active, revoked, stopped}."""
    record = development.get(campaign_id, workspace_id)
    stopped = record.get("desired_status") == "stopped"
    try:
        saved = development.store.get(identity(workspace_id), KIND)
    except KeyError:
        return {"issued_at": None, "last_used_at": None, "active": False, "revoked": None, "stopped": stopped}
    why = revoked(development.store, record, saved)
    return {"issued_at": saved["issued_at"], "last_used_at": saved.get("last_used_at"), "active": why is None, "revoked": why,
            "stopped": stopped}


def authorize(development, campaign_id, workspace_id, header):
    """(workspace record, token record) when `header` is `Bearer <the workspace's current token>`; Refused otherwise, saying
    no more than that, unless the token is the workspace's own (then why it no longer opens it)."""
    scheme, _, token = str(header or "").strip().partition(" ")
    refused = Refused("The token does not open this workspace")
    try:
        record = development.get(campaign_id, workspace_id)
        saved = development.store.get(identity(workspace_id), KIND)
    except (KeyError, ValueError):
        raise refused from None
    if scheme.lower() != "bearer" or not token.strip() or saved.get("workspace_id") != workspace_id \
            or not hmac.compare_digest(digest(token.strip()), saved["digest"]):
        raise refused
    why = revoked(development.store, record, saved)
    if why:
        raise Refused(f"The token no longer opens this workspace: {why}. Make a new one on the workspace's card")
    return record, saved


# Git on the host's own store ---------------------------------------------------------------------------------------------
def _env(extra=None):
    """The environment Git runs in: no inherited GIT_* variable, no system or user configuration, no prompt."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return {**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", **(extra or {})}


def _git(store, *args, input=None, env=None, timeout=120):
    done = subprocess.run(["git", "--no-replace-objects", f"--git-dir={store}", *SAFE, *args], input=input, capture_output=True,
                          timeout=timeout, env=_env(env), cwd=Path(store).parent)
    if done.returncode:
        raise ValueError((done.stderr.decode(errors="replace").strip() or f"git {args[0]} failed")[-1000:])
    return done.stdout


def own_store(development, record):
    """The host's store of the researcher's deliveries, made on first use: bare, in the workspace's directory beside `work/`
    (the box mounts `work/`, never this), with the box's store as its alternate so a bundle may build on the box's commits."""
    root = Path(development.driver.root(record)).resolve()
    store = root / "own" / "git"
    if not (store / "HEAD").exists():
        store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        done = subprocess.run(["git", "init", "-q", "--bare", str(store)], capture_output=True, timeout=60, env=_env(), cwd=store.parent)
        if done.returncode:
            raise ValueError("Making the workspace's store for your deliveries failed: " + done.stderr.decode(errors="replace")[-500:])
    box = root / "work" / "git" / "objects"
    alternates = store / "objects" / "info" / "alternates"
    if box.is_dir() and not alternates.exists():
        alternates.write_text(str(box) + "\n")
    return store


def git_dir(driver, record, submission=None):
    """The store a submission's commit is read from: the host's own for a delivery from the researcher's session, the box's
    for the coding agent's."""
    root = Path(driver.root(record))
    return root / "own" / "git" if (submission or {}).get("source") == SOURCE else root / "work" / "git"


def box_tips(record_root):
    """The commits the box's store names (its branches and tags), read as files: the box's store is never run as a repository."""
    git = Path(record_root) / "work" / "git"
    found = set()
    packed = git / "packed-refs"
    if packed.is_file() and not packed.is_symlink() and packed.stat().st_size < 4 * 1024 * 1024:
        for line in packed.read_text(errors="replace").splitlines():
            value = line.split(" ", 1)[0]
            if HASH.fullmatch(value):
                found.add(value)
    refs = git / "refs"
    if refs.is_dir() and not refs.is_symlink():
        for path in refs.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.stat().st_size < 200:
                value = path.read_text(errors="replace").strip()
                if HASH.fullmatch(value):
                    found.add(value)
    return found


def known(development, record):
    """The commits the host has that a bundle may build on (so it need not carry them): the tips of the box's store and of
    the host's own, each a commit the host can read."""
    store = own_store(development, record)
    tips = box_tips(development.driver.root(record))
    for line in _git(store, "for-each-ref", "--format=%(objectname)").decode().split():
        tips.add(line)
    if not tips:
        return []
    listing = _git(store, "cat-file", "--batch-check", input="".join(f"{tip}\n" for tip in sorted(tips)).encode()).decode()
    return sorted(parts[0] for parts in map(str.split, listing.splitlines()) if len(parts) == 3 and parts[1] == "commit")


def _tree(store, entries):
    """A tree object of {name: bytes | {nested}}: blobs written first, subtrees made bottom-up."""
    lines = []
    for name, value in sorted(entries.items()):
        if isinstance(value, dict):
            lines.append(f"040000 tree {_tree(store, value)}\t{name}")
        else:
            sha = _git(store, "hash-object", "-w", "--stdin", input=value).decode().strip()
            lines.append(f"100644 blob {sha}\t{name}")
    return _git(store, "mktree", input=("\n".join(lines) + "\n").encode()).decode().strip()


def start(development, record):
    """The workspace's library as the box started from it, as a Git bundle of one commit holding `libraries/<name>/` on
    branch `main`: {library, commit, bundle (base64)}. The same library always gives the same commit."""
    library = record.get("library")
    generated = development.generated_library(record)[0] if library else None
    if not library or not generated:
        raise ValueError("This workspace starts from no library generated from a charter: deliver a commit of your own repository "
                         "that holds the library under libraries/<name>/")
    files = {f"libraries/{library['name']}/{path}": content for path, content in generated["files"].items()}
    differ = sorted(path for path in set(files) | set(library["files"])
                    if path not in files or hashlib.sha256(files[path]).hexdigest() != library["files"].get(path))
    if differ:
        raise ValueError("The library generated now differs from the one this workspace started from (" + ", ".join(differ[:5])
                         + "): start from the coding agent's commit instead")
    root = {}
    for path, content in files.items():
        *folders, name = path.split("/")
        node = root
        for folder in folders:
            node = node.setdefault(folder, {})
        node[name] = content
    with _lock:
        store = own_store(development, record)
        tree = _tree(store, root)
        message = (f"{library['base']['package']} {library['base']['version']}, the version this workspace builds on" if library.get("base")
                   else f"The library generated from charter revision {library['revision']}")
        commit = _git(store, "commit-tree", tree, "-m", message,
                      env=START).decode().strip()
        _git(store, "update-ref", "refs/heads/main", commit)
        with tempfile.TemporaryDirectory(dir=store.parent) as folder:
            bundle = Path(folder) / "start.bundle"
            _git(store, "bundle", "create", str(bundle), "refs/heads/main")
            data = bundle.read_bytes()
    return {"library": f"libraries/{library['name']}", "commit": commit, "bundle": base64.b64encode(data).decode()}


def snapshot(store, commit, manifest_path):
    """(package, manifest, ignored manifest keys) of a commit in the host's store, read as DockerWorkspace.snapshot() reads the
    box's: the committed manifest (or one derived from the commit's single library) and each file it names, as plain blobs."""
    from optimization_framework.implementations.models import Package
    from .development import submission_manifest
    if not HASH.fullmatch(commit):
        raise ValueError("Submit the full 40-character Git commit hash")

    def inside(path):
        pure = PurePosixPath(path)
        if pure.is_absolute() or str(pure) != path or ".." in pure.parts or "\\" in path:
            raise ValueError("Submission paths must stay in the repository")
        return path

    def read(path):
        content = _git(store, "cat-file", "blob", f"{commit}:{inside(path)}")
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("Submitted file exceeds the package transport limit")
        try:
            return content.decode()
        except UnicodeDecodeError:
            raise ValueError(f"{path} is not text: a submitted package holds text files") from None

    present = bool(_git(store, "ls-tree", "--name-only", commit, "--", inside(manifest_path)).strip())
    tracked = [path for path in _git(store, "ls-tree", "-r", "-z", "--name-only", commit, "--", "libraries").decode().split("\0") if path]
    manifest, ignored = submission_manifest(read(manifest_path) if present else None, tracked)
    package = Package(contract=manifest.contract, entrypoint=manifest.entrypoint,
                      files=[{"path": path, "content": read(path)} for path in manifest.files])
    return package.model_dump(), manifest.model_dump(), ignored


def deliver(development, record, values):
    """Capture the commit a bundle carries, as the box's submissions are captured (capture_submission): {submission_id,
    status, ignored_fields?}. A workspace that is not running (closed()), a bundle that does not carry the commit, or one that
    builds on commits the host does not have, is refused before anything is captured; the refusal is on the workspace's
    history, as a refused submission from the box is."""
    key = "own_session_" + content_hash([values.commit, now()])[:16]
    try:
        why = closed(development.get(record["campaign_id"], record["id"]))
        if why:
            raise ValueError(why)
        try:
            data = base64.b64decode(values.bundle, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("bundle: not base64") from None
        if len(data) > MAX_BUNDLE_BYTES:
            raise ValueError(f"The bundle is larger than {MAX_BUNDLE_BYTES >> 20} MB")
        with _lock:
            store = own_store(development, record)
            with tempfile.TemporaryDirectory(dir=store.parent) as folder:
                bundle = Path(folder) / "submission.bundle"
                bundle.write_bytes(data)
                try:
                    heads = [line.split()[0] for line in _git(store, "bundle", "list-heads", str(bundle)).decode().splitlines() if line.strip()]
                except ValueError as exc:
                    raise ValueError(f"The upload is not a Git bundle: {exc}") from None
                if values.commit not in heads:
                    raise ValueError(f"The bundle does not carry commit {values.commit}: it carries "
                                     + (", ".join(head[:12] for head in heads) or "no commit"))
                try:
                    _git(store, "bundle", "verify", str(bundle))
                except ValueError as exc:
                    lacking = re.findall(r"\b[a-f0-9]{40}\b", str(exc))
                    raise ValueError("The bundle builds on commits this workspace does not have (" + (", ".join(lacking) or str(exc))
                                     + "); send it with their history (balsamic-workspace submit leaves out only the commits "
                                     "the workspace names)") from None
                _git(store, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", str(bundle),
                     f"{values.commit}:refs/balsamic/submissions/{values.commit}", timeout=600)
        result = development.capture_submission(record, key, {"commit": values.commit, "manifest_path": values.manifest_path,
            "notes": values.notes, "report": values.report}, snapshot=lambda _record, commit, path: snapshot(store, commit, path), source=SOURCE)
    except ValueError as exc:
        with development.workspace.lock, development.store.transaction():
            development.event(record, key, "bridge_error", {"error": str(exc)[:2000], "source": SOURCE})
        raise
    with development.workspace.lock:
        try:
            saved = development.store.get(identity(record["id"]), KIND)
            development.store.put(KIND, {**saved, "last_used_at": now()})
        except KeyError:
            pass
    return result


# HTTP --------------------------------------------------------------------------------------------------------------------
def routes(app, workspace):
    """The token's two routes, the researcher's (the card), and the three `balsamic-workspace` takes it to from outside the box."""
    from starlette.concurrency import run_in_threadpool
    from .development_runtime import ROOT
    development = workspace.pi.development
    base = "/api/campaigns/{campaign_id}/implementation-workspaces/{identity}"
    cli = ROOT / "deploy" / "implementation-workspace" / "balsamic-workspace.mjs"

    @app.post(base + "/session-token")
    def make_token(campaign_id: str, identity: str):
        workspace.store.get(campaign_id, "campaign")
        return {**issue(development, campaign_id, identity), "cli": str(cli)}

    @app.get(base + "/session-token")
    def token_state(campaign_id: str, identity: str):
        workspace.store.get(campaign_id, "campaign")
        return view(development, campaign_id, identity)

    def opened(request, campaign_id, identity):
        try:
            return authorize(development, campaign_id, identity, request.headers.get("authorization"))
        except Refused as exc:
            raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"}) from None

    @app.get(base + "/bundles/base")
    def bundle_base(campaign_id: str, identity: str, request: Request):
        record, _ = opened(request, campaign_id, identity)
        return {"commits": known(development, record)}

    @app.get(base + "/bundles/start")
    def bundle_start(campaign_id: str, identity: str, request: Request):
        record, _ = opened(request, campaign_id, identity)
        try:
            return start(development, record)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post(base + "/bundles")
    async def bundle_submit(campaign_id: str, identity: str, request: Request):
        record, _ = await run_in_threadpool(opened, request, campaign_id, identity)
        too_large = HTTPException(413, f"A delivery is at most {MAX_BUNDLE_BYTES >> 20} MB of bundle")
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            raise too_large
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY_BYTES:
                raise too_large
        try:
            values = OwnSubmission.model_validate_json(bytes(body))
        except ValidationError as exc:
            raise HTTPException(422, str(exc)[:2000]) from None
        try:
            return await run_in_threadpool(deliver, development, record, values)
        except ValueError as exc:
            raise HTTPException(409, str(exc)[:2000]) from None
