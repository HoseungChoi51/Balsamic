"""Installing a coding workspace's library into the lab. Balsamic does it by itself once a workspace delivers (not a delivery
its coding agent reports not ready); the researcher can install again from the Implementations page.

The exact submitted commit's `libraries/<name>/` is read from the workspace's own Git store (listed and read as blobs: no
filter, hook or attribute of a repository the coding agent could write runs on the host), or, for a commit the researcher
delivered from their own session, from the host's store of those (agents/own_session.py), checked against what was
submitted, and copied into the lab's `libraries/<name>/`. The root pyproject.toml pins it in the `libraries` extra as an
editable path dependency, `uv lock` and `uv sync --inexact --extra libraries` install it, and the running lab picks its
methods and problems up at the next listing. A library provides methods (`optimization_framework.optimizers` entry points),
problems (`optimization_framework.problems`), or both; a method or problem id another installed package provides is refused
before uv runs. A dry run first: a change to any package already installed waits for the researcher's
confirmation (it could affect their other campaigns); a reinstall and the lab's own projects are no change. Every file this
touched is put back when it stops or fails. Before any of that, the host validates the exact commit's files outside the
box (library_validation, roadmap H6): the library's tests, each method's conformance and the protected acceptance tests. A
method that fails there is not installed, and a failure no method owns stops the install. Each install is a `library_install` record: who (balsamic or the researcher),
when, what (package, version, commit, workspace, submission), the methods and problems it added, and how it ended.

A new version keeps what campaigns use (roadmap L1): a method or problem the installed version provides that the new one drops,
or a method it keeps that fails validation outside the box, refuses the install when any campaign of the lab uses it
(library_usage); unused ones may go and are recorded as removed.

Each library has its own Git repository on the host (roadmap L2, agents/library_repository.py). An install commits the version's
files onto it and writes the lab's copy from that commit, checked against what was submitted; once the version is in, the
commit is tagged v<version> and recorded as a `library_version`. A library the lab had before (L1's archive, the lab's own copy)
is imported as its first versions the first time it is installed again.

A split (roadmap L6, agents/library_split.py) delivers two libraries in one commit, a method library and a new version of the
problem library that depends on it, and installs them as one step: both are validated outside the box (the problem library with
the method library importable beside it), the method library takes over the methods the split names and no others, a moved
method counts as kept, the moved methods replay their recorded runs on every problem, and both are committed, pinned, synced,
tagged and recorded together, or neither is.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import tomllib
from pathlib import Path, PurePosixPath

from importlib import metadata

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import atomic_json, now

from . import library_repository as repositories

GROUP = "optimization_framework.optimizers"
PROBLEMS = "optimization_framework.problems"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
TIMEOUT_SECONDS = 600
# A dry run's package line: ` - name==version`, ` - name==version (from url)` or ` + name @ url`.
CHANGE = re.compile(r"^\s*([-+~])\s+([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:==\s*(\S+)(?:\s+\(from\s+([^)\s]+)\))?|@\s+(\S+))\s*$")
DRY_RUN = "$ sync --dry-run"
# Git reads the workspace's store as plain objects; the user's and the system's Git settings play no part.
GIT_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
_lock = threading.Lock()


def normal(name):
    """A distribution name as packaging compares it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def providers(group):
    """{entry-point name: the installed distribution that provides it} of a group (None for an entry with no distribution)."""
    return {entry.name: entry.dist.name if entry.dist else None for entry in metadata.entry_points(group=group)}


def run(args, cwd, timeout=TIMEOUT_SECONDS):
    """(exit code, combined output) of a command."""
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


class Installer:
    def __init__(self, workspace, development, root, runner=run, uv=None, plugins=None, problems=None, providers=providers,
                 validator=None):
        """runner runs uv (tests give their own); Git always runs directly, read-only. providers(group) names the installed
        distribution of each entry point of a group. validator(files, name, instances=, protected=) validates the library
        outside the box (library_validation.run)."""
        from . import library_validation
        from optimization_framework.evaluation.registry import problems as registry
        from optimization_framework.optimizers import plugins as installed
        self.workspace, self.store, self.development = workspace, workspace.store, development
        self.root = Path(root)
        self.runner = runner
        self.uv = uv or shutil.which("uv")
        self.plugins = plugins or installed.installed
        self.problems = problems or registry
        self.providers = providers
        self.validator = validator or library_validation.run

    # Checks -----------------------------------------------------------------------------------------------------------
    def _git(self, record, *args, submission=None):
        """Git on the store the submission's commit is in: the box's, or the host's own for the researcher's (roadmap H3)."""
        from .own_session import git_dir
        git = git_dir(self.development.driver, record, submission)
        done = subprocess.run(["git", "--no-replace-objects", f"--git-dir={git}", *args], cwd=self.root, capture_output=True, timeout=60, env=GIT_ENV)
        if done.returncode:
            raise ValueError("Reading the submitted commit failed: " + done.stderr.decode(errors="replace").strip()[:500])
        return done.stdout

    def files(self, record, submission, name):
        """{path: bytes} of libraries/<name>/ at the submitted commit."""
        listing = self._git(record, "ls-tree", "-r", "-z", "--full-tree", submission["commit"], "--", f"libraries/{name}",
                            submission=submission).decode()
        found, total = {}, 0
        for item in filter(None, listing.split("\0")):
            meta, path = item.split("\t", 1)
            mode, kind, _ = meta.split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError(f"{path} is a {'link' if mode == '120000' else kind}: a library holds plain files only")
            pure = PurePosixPath(path)
            if pure.is_absolute() or ".." in pure.parts or pure.parts[:2] != ("libraries", name):
                raise ValueError(f"{path} leaves libraries/{name}/")
            found[path] = content = self._git(record, "cat-file", "blob", f"{submission['commit']}:{path}", submission=submission)
            total += len(content)
            if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError(f"libraries/{name} is larger than an installable library ({MAX_FILE_BYTES >> 20} MB a file, {MAX_TOTAL_BYTES >> 20} MB in all)")
        if not found:
            raise ValueError(f"The submitted commit has no libraries/{name}/")
        return found

    def plan(self, campaign_id, workspace_id, submission_id, *, accept_not_ready=False):
        """prepare()'s plan; for a split workspace (roadmap L6) the problem library's, with the method library's plan under
        ``with`` and the split under ``split``."""
        from optimization_framework.campaigns.method_catalog import libraries_of
        record = self.development.get(campaign_id, workspace_id)
        if not record.get("split"):
            return self.prepare(campaign_id, workspace_id, submission_id, accept_not_ready=accept_not_ready)
        split = self.store.get(record["split"]["id"], "library_split")
        submission = self.store.get(submission_id, "development_submission")
        expected, names = {split["library"], split["method_library"]}, libraries_of(submission)
        if names != expected:
            raise ValueError(f"A split delivers libraries/{split['method_library']}/ and libraries/{split['library']}/ in one commit; this one "
                             f"delivers {', '.join(f'libraries/{name}/' for name in sorted(names)) or 'no library'}")
        methods = self.prepare(campaign_id, workspace_id, submission_id, accept_not_ready=accept_not_ready, name=split["method_library"],
                               moving=split)
        problem = self.prepare(campaign_id, workspace_id, submission_id, accept_not_ready=accept_not_ready, name=split["library"])
        return {**problem, "with": [methods], "split": split}

    def prepare(self, campaign_id, workspace_id, submission_id, *, accept_not_ready=False, name=None, moving=None):
        """What would be installed: {name, package, version, methods, files, report}; ValueError when it cannot be. ``name``: the
        library to read (a split delivers two); ``moving``: the split whose package's methods this library may take over."""
        from optimization_framework.campaigns.method_catalog import library_of
        record = self.development.get(campaign_id, workspace_id)
        submission = self.store.get(submission_id, "development_submission")
        if submission["workspace_id"] != workspace_id or submission["campaign_id"] != campaign_id:
            raise ValueError("The submission belongs to another workspace")
        name = name or library_of(submission)
        if not name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,99}", name):
            raise ValueError("Only a library delivered under one libraries/<name>/ directory can be installed")
        report = submission.get("report") or {}
        if report.get("verdict") == "not_ready" and not accept_not_ready:
            raise ValueError("The coding agent reported it not ready; confirm that you install it anyway")
        files = self.files(record, submission, name)
        # What was submitted is what is installed: every manifest file inside the library, byte for byte.
        for item in (submission.get("package") or {}).get("files", []):
            if item["path"] in files and files[item["path"]] != str(item["content"]).encode():
                raise ValueError(f"{item['path']} at the commit differs from what was submitted")
        changed = generated_changes(record, name, files)
        pyproject = files.get(f"libraries/{name}/pyproject.toml")
        if pyproject is None:
            raise ValueError(f"libraries/{name} has no pyproject.toml")
        project = tomllib.loads(pyproject.decode()).get("project") or {}
        package, version = project.get("name"), str(project.get("version") or "")
        groups = project.get("entry-points") or {}
        entries, problems = groups.get(GROUP) or {}, groups.get(PROBLEMS) or {}
        if not package or not version:
            raise ValueError(f"libraries/{name}/pyproject.toml names no project name and version")
        if not entries and not problems:
            raise ValueError(f"libraries/{name}/pyproject.toml names no {GROUP} or {PROBLEMS} entry point, so it adds no method or problem")
        self._refuse_clashes(package, entries, problems, report, **({"moving": moving} if moving else {}))
        target = self.root / "libraries" / name
        if (target / "pyproject.toml").exists():
            current = tomllib.loads((target / "pyproject.toml").read_text()).get("project") or {}
            if current.get("name") != package:
                raise ValueError(f"libraries/{name} holds another project ({current.get('name')})")
            existing = lab_files(target, self.root)
            if str(current.get("version")) == version and existing != files:
                raise ValueError(f"{package} {version} is installed with other code; the coding agent has to raise the version for the lab to load the new code")
        return {"name": name, "package": package, "version": version, "entry_points": entries, "problem_entry_points": problems,
                "files": files, "report": report, "record": record, "submission": submission, "changed_generated_files": changed}

    def _refuse_clashes(self, package, entries, problems, report, moving=None):
        """A problem id, plug-in name or method id that another installed distribution (the lab's own included) provides is
        refused before uv runs: the registries would keep the first one loaded, or stop listing either. The library's own
        earlier version is no clash, nor, for a split's method library (``moving``), the split's package, whose methods the
        report names too: which of them it takes over is checked on what validation lists (library_split.takeovers())."""
        from optimization_framework.optimizers.registry import BUILTIN_IDS
        theirs = lambda distribution: distribution is None or normal(distribution) != normal(package)
        for kind, group, ids in (("problem", PROBLEMS, problems), ("optimizer plug-in", GROUP, entries)):
            installed = self.providers(group)
            for identity in sorted(ids):
                if identity in installed and theirs(installed[identity]):
                    raise ValueError(f"{kind} {identity} is provided by {installed[identity] or 'the lab'}")
        origin = getattr(self.plugins, "origin", lambda method_id: None)
        for method_id in sorted({item.get("method_id") for item in report.get("methods", []) if item.get("method_id")}):
            if method_id in BUILTIN_IDS:
                raise ValueError(f"method {method_id} is provided by the lab (a built-in method)")
            found = origin(method_id)
            if moving and found and found.get("distribution") and normal(found["distribution"]) == normal(moving["package"]):
                continue
            if found and theirs(found.get("distribution")):
                raise ValueError(f"method {method_id} is provided by {found.get('distribution') or 'the lab'}")

    # Install ----------------------------------------------------------------------------------------------------------
    def automatic(self, campaign_id, workspace_id, submission, *, background=True):
        """Balsamic's own install of a delivered library, once per submission: none for a delivery its coding agent reports not
        ready, or one delivered as loose files. A refusal (the same version with other code, files that differ from what was
        submitted) is recorded as a failed install and told to the lead."""
        from optimization_framework.campaigns.method_catalog import library_of
        split = (self.development.get(campaign_id, workspace_id).get("split") or {})
        if (submission.get("report") or {}).get("verdict") == "not_ready" or not (library_of(submission) or split):
            return None
        if any(row.get("submission_id") == submission["id"] for row in self.store.list("library_install", campaign_id)):
            return None
        try:
            return self.request(campaign_id, workspace_id, submission["id"], request_key="automatic", actor="balsamic", background=background)
        except ValueError as exc:
            identity = "library_install_" + content_hash([submission["id"], "automatic"])[:24]
            record = self.store.put("library_install", {"id": identity, "campaign_id": campaign_id, "workspace_id": workspace_id,
                "submission_id": submission["id"], "commit": submission["commit"], "package": None, "version": None,
                "path": f"libraries/{library_of(submission) or split.get('library')}", "entry_points": {}, "problem_entry_points": {}, "actor": "balsamic",
                "status": "failed", "requested_at": now(), "finished_at": now(), "error": str(exc)[:2000], "methods_added": [],
                "missing_methods": [], "problems_added": [], "missing_problems": [], "changes": [], "log_tail": "",
                "changed_generated_files": []}, "library.install_failed")
            self.development.notify(self.development.get(campaign_id, workspace_id), identity, f"Balsamic could not install the library "
                f"from commit {submission['commit'][:7]}: {exc} Have the coding agent fix it and deliver again.", "installs")
            return record

    def reparsed(self, campaign_id, submission, *, background=True):
        """Balsamic's own install that waits for a confirmation it never needed (an older parser counted reinstalls and the lab's
        own projects as changes), requested once more when its dry run, read again, changes nothing. Never twice."""
        tries = sorted((row for row in self.store.list("library_install", campaign_id) if row.get("submission_id") == submission["id"]),
                       key=lambda row: row["requested_at"])
        if not tries or any(row.get("retry_of") for row in tries):
            return None
        latest, log = tries[-1], tries[-1].get("log_tail") or ""
        # Only a dry run whose output the log still holds from its first line can be read again.
        if latest.get("actor") != "balsamic" or latest["status"] != "needs_confirmation" or DRY_RUN not in log:
            return None
        if changed_packages(log.rsplit(DRY_RUN, 1)[1], latest["package"], lab_projects(self.root)):
            return None
        return self.request(campaign_id, latest["workspace_id"], submission["id"], request_key="automatic:reparsed", actor="balsamic",
                            retry_of=latest["id"], background=background)

    def request(self, campaign_id, workspace_id, submission_id, *, request_key, confirm_changes=False, accept_not_ready=False,
                background=True, actor="researcher", retry_of=None):
        """Record an install (Balsamic's own, or the researcher's) and start it; the record says how it goes. retry_of names the
        install this one tries again."""
        if not self.uv:
            raise ValueError("uv is not available to the lab; install by hand: copy the library into libraries/<name>/, "
                             "add it to the libraries extra in pyproject.toml, and run `uv sync --inexact --extra libraries`")
        plan = self.plan(campaign_id, workspace_id, submission_id, accept_not_ready=accept_not_ready)
        identity = "library_install_" + content_hash([submission_id, request_key])[:24]
        try:
            return self.store.get(identity, "library_install")
        except KeyError:
            pass
        install = {"id": identity, "campaign_id": campaign_id, "workspace_id": workspace_id, "submission_id": submission_id,
                   "commit": plan["submission"]["commit"], "package": plan["package"], "version": plan["version"], "path": f"libraries/{plan['name']}",
                   "entry_points": plan["entry_points"], "problem_entry_points": plan["problem_entry_points"], "actor": actor, "status": "queued",
                   "requested_at": now(), "confirm_changes": confirm_changes, "methods_added": [], "missing_methods": [], "problems_added": [],
                   "missing_problems": [], "changes": [], "log_tail": "", "changed_generated_files": plan["changed_generated_files"],
                   **({"retry_of": retry_of} if retry_of else {}), **base_of(plan),
                   **({"split_id": plan["split"]["id"], "method_library": {key: plan["with"][0][key] for key in ("name", "package", "version")}}
                      if plan.get("split") else {})}
        self.store.put("library_install", install, "library.install_requested")
        if background:
            threading.Thread(target=self.install, args=(identity, plan, confirm_changes), daemon=True).start()
        else:
            self.install(identity, plan, confirm_changes)
        return self.store.get(identity, "library_install")

    def _update(self, identity, event=None, **fields):
        record = {**self.store.get(identity, "library_install"), **fields}
        self.store.put("library_install", record, event)
        return record

    def _validate(self, identity, plan):
        """Validate the exact commit's files outside the box and record it on the install: its verdict, or ValueError naming
        what failed when nothing of it may be installed. Its compute is charged to the go-ahead the workspace opened under."""
        from . import library_validation as validation
        record = plan["record"]
        self._update(identity, status="validating")
        # Tests accumulate and kept methods reproduce their recorded runs (roadmap L4): what the installed version has is checked again.
        old_methods, old_problems = self.provided(plan["package"])
        moved, extra = set(), {}
        if plan.get("split"):   # the method library first; the problem library imports it (roadmap L6)
            moved, extra = self._validate_split(identity, plan, old_methods)
        blocks = self._blocks(record)   # what the box imported, as the box had it (issue #101)
        if blocks:
            extra["dependencies"] = {**blocks, **extra.get("dependencies", {})}
        earlier = validation.earlier_tests(self.store, self.workspace.directory, plan["name"], plan["files"])
        protected = {**validation.earlier_protected(self.store, record, plan["name"]), **validation.protected_tests(self.store, record)}
        replays = validation.recorded_runs(self.workspace, old_methods - moved, old_problems & set(plan["problem_entry_points"]))
        extra |= {**({"earlier": earlier} if earlier else {}), **({"replays": replays} if replays else {})}
        try:
            result = self.validator(plan["files"], plan["name"], instances=validation.instances_of(self.workspace, record["campaign_id"]),
                                    protected=protected, **extra)
        except ValueError as exc:
            raise ValueError(f"Balsamic could not validate the library outside the box: {exc}") from None
        self._charge(record, identity, result.get("seconds") or 0.0)
        listed = {row["method_id"] for row in result.get("methods", [])}
        judged = validation.verdict(result, plan["report"], removed=old_methods - listed - moved if listed else moved)
        host = {**validation.public(result), **judged, "reproduced": validation.reproduced(result), "at": now()}
        if moved:
            split = self.store.get(identity, "library_install")["host_validation"]["method_library"]
            host["method_library"] = split
            judged = {**judged, "moved": sorted(moved), "refused_methods": [*split["refused_methods"], *judged["refused_methods"]]}
        self._update(identity, host_validation=host, refused_methods=judged["refused_methods"])
        listed = [row["method_id"] for row in judged["methods"]]
        if judged["library_failures"]:
            raise ValueError("Validation outside the box failed, in tests no method owns: " + "; ".join(judged["library_failures"][:10]))
        if listed and not plan["problem_entry_points"] and len(judged["refused_methods"]) == len(listed):
            raise ValueError("Validation outside the box failed for every method: " + refused_text(judged["refused_methods"]))
        return judged

    def _blocks(self, record):
        """The shared library repository's building blocks the workspace's box imported (issue #101): {libraries/<name>/<path>:
        bytes}, read from the copy the box had (development_runtime.write_blocks); {} for a box that had none."""
        try:
            folder = Path(self.development.driver.root(record)) / "blocks"
        except (AttributeError, KeyError, TypeError):
            return {}
        if not folder.is_dir():
            return {}
        return {f"libraries/{path.relative_to(folder).as_posix()}": path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}

    def _ticket_blocks(self, record):
        """The building blocks the workspace's ticket names, with the versions its box had."""
        try:
            return list(self.development.ticket_of(record).get("building_blocks") or [])
        except (AttributeError, KeyError, TypeError, ValueError):
            return []

    def _validate_split(self, identity, plan, old_methods):
        """A split's method library, validated outside the box before the problem library: it provides the methods the split moves
        and no problem, takes over no other method, and the moved methods pass and replay their recorded runs on every problem
        (ValueError otherwise). (the moved methods, the problem library's validation arguments)."""
        from . import library_split, library_validation as validation
        split, methods = plan["split"], plan["with"][0]
        replays = validation.recorded_runs(self.workspace, set(split["methods"]), ())
        try:
            result = self.validator(methods["files"], methods["name"], instances=validation.instances_of(self.workspace, plan["record"]["campaign_id"]),
                                    protected={}, **({"replays": replays} if replays else {}))
        except ValueError as exc:
            raise ValueError(f"Balsamic could not validate the method library outside the box: {exc}") from None
        self._charge(plan["record"], identity, result.get("seconds") or 0.0)
        listed = {row["method_id"] for row in result.get("methods", [])}
        judged = validation.verdict(result, plan["report"])
        self._update(identity, host_validation={"method_library": {**validation.public(result), **judged, "name": methods["name"],
                     "reproduced": validation.reproduced(result)}})
        library_split.check(split, methods, plan, listed)
        library_split.takeovers(old_methods, listed, split)
        if judged["library_failures"]:
            raise ValueError(f"Validation outside the box of libraries/{methods['name']} failed, in tests no method owns: "
                             + "; ".join(judged["library_failures"][:10]))
        failing = [row for row in judged["refused_methods"] if row["method_id"] in split["methods"]]
        if failing:
            raise ValueError(f"The methods the split moves fail in libraries/{methods['name']}: " + refused_text(failing))
        return set(split["methods"]), {"dependencies": methods["files"]}

    def _charge(self, record, identity, seconds):
        """Validation's time, charged to the go-ahead the workspace opened under; for a commission's box (roadmap H7), counted on the
        commission instead, whose compute time the bus charged to the go-ahead once when it opened."""
        from optimization_framework.campaigns import compute_consent
        if record.get("commission"):
            with self.workspace.lock:
                current = self.store.get(record["id"], "development_workspace")
                usage = current["commission"].setdefault("usage", {})
                usage["validation_seconds"] = usage.get("validation_seconds", 0.0) + (seconds or 0.0)
                self.store.put("development_workspace", current)
            return
        consent_id = (record.get("consent") or {}).get("id")
        if not consent_id or not seconds:
            return
        with self.workspace.lock:
            try:
                consent = self.store.get(consent_id, "compute_consent")
            except KeyError:
                return
            compute_consent.spend(self.workspace, consent, seconds, subjects=[identity])

    def _feedback(self, identity, plan):
        """The host's results to the coder, once per install, when something failed: a result file in the box (the workspace's
        incoming/results, which the box reads at /bridge/in/results; protected tests by name and outcome only) and one message
        pointing at it. Whether it was sent; failing to send it never stops the
        install or what follows it."""
        install, record = self.store.get(identity, "library_install"), plan["record"]
        host = install.get("host_validation")
        if not host or (not install.get("refused_methods") and install["status"] != "failed"):
            return False
        name = f"host-validation-{identity}.json"
        what = (f"Nothing was installed: {install.get('error')}" if install["status"] == "failed"
                else f"Methods not installed: {refused_text(install['refused_methods'])}")
        try:
            atomic_json(self.development.driver.root(record) / "incoming/results" / name, {"install_id": identity,
                "commit": plan["submission"]["commit"], "status": install["status"], "error": install.get("error"), **host})
            self.development.message(record["campaign_id"], record["id"], {"message": f"Balsamic validated commit "
                f"{plan['submission']['commit'][:7]} outside the box. {what} The results are in /bridge/in/results/{name}. Fix them in a "
                "new commit, raise the version, and deliver again.", "request_key": "host-validation-" + identity, "mode": "follow_up"},
                actor="system")
        except Exception as exc:
            logging.getLogger(__name__).warning("Telling the coding agent what failed outside the box failed: %s", exc)
            return False
        return True

    def install(self, identity, plan, confirm_changes):
        try:
            judged = self._validate(identity, plan)
            self._keeps(identity, plan, judged)
        except Exception as exc:   # nothing of it is installed; the coder and the lead are told what failed
            record = self._update(identity, "library.install_failed", status="failed", finished_at=now(), error=str(exc)[:2000])
            told = self._feedback(identity, plan)
            self.development.notify(plan["record"], identity, f"Balsamic did not install the library from commit "
                f"{plan['submission']['commit'][:7]}: {exc}" + (" The coding agent has the results." if told else ""), "installs")
            return record
        refused = {row["method_id"] for row in judged["refused_methods"]}
        # A split's method library goes in with the problem library, first (roadmap L6); every other install is one library.
        plans = [*plan.get("with", []), plan]
        with _lock:
            root = self.root
            places = [{"plan": item, "target": root / "libraries" / item["name"], "staging": root / "libraries" / f".staging-{identity}-{item['name']}",
                       "backup": root / "libraries" / f".previous-{item['name']}-{identity}", "created": False} for item in plans]
            saved = {file: (root / file).read_bytes() for file in ("pyproject.toml", "uv.lock") if (root / file).exists()}
            log = []
            try:
                self._update(identity, status="installing")
                before = {method["id"] for method in self.plugins.methods()}
                problems_before = set(self.problems.ids())
                for place in places:
                    item, name, target, staging = place["plan"], place["plan"]["name"], place["target"], place["staging"]
                    if target.exists():
                        self._import_replaced(target, item["package"])
                    # The lab's copy is the version's commit in the library's repository: written from it, checked against the submission.
                    place["repository"], place["made"] = repositories.commit(self.workspace.directory, name, item["files"], commit_message(item, identity))
                    repositories.check_tag(place["repository"], place["made"], item["version"])
                    exported = repositories.files_at(place["repository"], place["made"], name)
                    if exported != item["files"]:
                        raise ValueError("The library's repository does not hold what was submitted")
                    for path, content in exported.items():
                        destination = staging / Path(path).relative_to(f"libraries/{name}")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(content)
                for place in places:
                    if place["target"].exists():
                        place["target"].rename(place["backup"])
                    place["staging"].rename(place["target"])
                    place["created"] = True
                    self._pin(place["plan"]["package"], place["plan"]["version"], place["plan"]["name"], self._ticket_blocks(place["plan"]["record"]))
                for args in ([self.uv, "lock"], [self.uv, "sync", "--dry-run", "--inexact", "--extra", "libraries"]):
                    code, output = self.runner(args, cwd=root)
                    log.append(f"$ {' '.join(args[1:])}\n{output}")
                    if code:
                        raise ValueError(f"uv {args[1]} failed: " + output.strip()[-800:])
                changes = [change for change in changed_packages(output, plan["package"], lab_projects(root))
                           if all(normal(change["name"]) != normal(item["package"]) for item in plans)]
                if changes and not confirm_changes:
                    self._restore_all(saved, places)
                    return self._update(identity, "library.install_failed", status="needs_confirmation", changes=changes, finished_at=now(),
                                        error="Installing it would change packages the lab already has; confirm to go on", log_tail="\n".join(log)[-4000:])
                args = [self.uv, "sync", "--inexact", "--extra", "libraries"]
                code, output = self.runner(args, cwd=root)
                log.append(f"$ {' '.join(args[1:])}\n{output}")
                if code:
                    raise ValueError("uv sync failed: " + output.strip()[-800:])
                after = {method["id"] for method in self.plugins.methods()}
                problems_after = set(self.problems.refresh() if hasattr(self.problems, "refresh") else self.problems.ids())
                reported = [method["method_id"] for method in plan["report"].get("methods", [])]
                for place in places:
                    if place["backup"].exists():
                        shutil.rmtree(place["backup"])
                kept = self.store.get(identity, "library_install")
                source = {"install_id": identity, "campaign_id": plan["record"]["campaign_id"], "workspace_id": plan["record"]["id"],
                          "submission_id": plan["submission"]["id"], "commit": plan["submission"]["commit"], "actor": kept["actor"]}
                split, versions = plan.get("split"), []
                for place in places:
                    item = place["plan"]
                    tagged = repositories.publish(place["repository"], place["made"], item["version"])
                    if split:   # each library's methods are those its package provides now
                        methods = sorted(self.provided(item["package"])[0] - refused)
                    else:
                        methods = sorted({*(kept.get("methods_kept") or []), *(after - before - refused)})
                    depends = sorted({plans[0]["package"]}) if split and item is plan else ()
                    moved = {"package": plans[0]["package"], "methods": list(split["methods"])} if split and item is plan else None
                    versions.append(repositories.record(self.store, item["name"], item["package"], item["version"], tagged, source=source,
                                    methods=methods, problems=sorted(item["problem_entry_points"]), depends_on=depends, moved=moved))
                version = versions[-1]
                shared = self._share(places, versions, plan, identity)
                record = self._update(identity, "library.installed", status="installed", finished_at=now(), changes=changes, **shared,
                                      library_version_id=version["id"], tag=version["tag"], library_commit=version["commit"],
                                      methods_added=sorted(after - before - refused), missing_methods=sorted(set(reported) - after - refused),
                                      problems_added=sorted(problems_after - problems_before),
                                      missing_problems=sorted(set(plan["problem_entry_points"]) - problems_after),
                                      log_tail="\n".join(log)[-4000:],
                                      **({"method_library": {**kept["method_library"], "library_version_id": versions[0]["id"], "tag": versions[0]["tag"],
                                                             "library_commit": versions[0]["commit"], "methods": versions[0]["methods"]}} if split else {}))
                if split:
                    self.store.put("library_split", {**self.store.get(split["id"], "library_split"), "status": "done", "install_id": identity,
                                                     "done_at": now()}, "library.split_done")
            except Exception as exc:   # every failure is recorded and the lab is put back as it was
                self._restore_all(saved, places)
                return self._update(identity, "library.install_failed", status="failed", finished_at=now(), error=str(exc)[:2000],
                                    log_tail="\n".join(log)[-4000:])
            finally:
                for place in places:
                    if place["staging"].exists():
                        shutil.rmtree(place["staging"])
        # The library is in: what Balsamic does next never undoes the install.
        self._feedback(identity, plan)
        try:
            record = self._update(identity, **after_install(self.workspace, record))
        except Exception as exc:
            record = self._update(identity, adopted=[], adoption_skipped=None, bindings=[], skipped=[],
                                  after_install_error=f"{type(exc).__name__}: {exc}"[:500])
        who = "The researcher" if record["actor"] == "researcher" else "Balsamic"
        adoption = adoption_text(record)
        moved = (f" It splits {', '.join(record['methods_moved'])} into the method package {record['method_library']['package']} "
                 f"{record['method_library']['version']}, which {plan['package']} now depends on (roadmap L6)." if record.get("method_library") else "")
        self.development.notify(plan["record"], identity, f"{who} installed {plan['package']} {plan['version']} from commit "
            f"{plan['submission']['commit'][:7]}: {added(record)}." + moved + (f" {kept_text(record)}." if kept_text(record) else "")
            + (f" Not installed, failed outside the box: {refused_text(record['refused_methods'])}." if record.get("refused_methods") else "")
            + (f" Generated files it changed: {', '.join(plan['changed_generated_files'])}." if plan["changed_generated_files"] else "")
            + (" " + adoption if adoption else "")
            + (" " + bound_text(record) + " Tell the researcher which proposals can run now." if plan["entry_points"] else "")
            + (f" {shared_text(record)}" if shared_text(record) else ""), "installs")
        return record

    def _share(self, places, versions, plan, identity):
        """Publish each version just tagged to the shared library repository (issue #101), so that another checkout, data folder or
        machine has it: {published} for the install's own library, or {publish_skipped} with why; never raises."""
        from . import shared_libraries
        repository = shared_libraries.location(self.root)
        if repository is None:
            return {}
        source = plan["record"]
        try:
            campaign = self.store.get(source["campaign_id"], "campaign").get("name") or source["campaign_id"]
        except KeyError:
            campaign = source["campaign_id"]
        found = {}
        for place, version in zip(places, versions):
            item = place["plan"]
            message = (f"{item['package']} {item['version']}\n\nInstalled by Balsamic from campaign {campaign} ({source['campaign_id']}): "
                       f"workspace {source['id']}, submission {plan['submission']['id']}, source commit {plan['submission']['commit']}, "
                       f"install {identity}, lab version {version['id']}.")
            try:
                made = shared_libraries.publish(repository, item["name"], item["files"], item["version"], message)
                published = {key: made[key] for key in ("repository", "branch", "commit", "tag")}
                self.store.put(repositories.KIND, {**self.store.get(version["id"], repositories.KIND), "published": published}, "library.version_published")
            except Exception as exc:   # publishing never undoes an install that went in
                found = {"publish_skipped": f"{item['package']} {item['version']} is not in the shared library repository {repository}: {exc}"[:600]}
                continue
            if item is plan:
                found = {"published": published}
        return found

    def provided(self, package):
        """(methods, problems) the installed package provides now; both empty when it is not installed."""
        origin = getattr(self.plugins, "origin", lambda method_id: None)
        mine = lambda distribution: bool(distribution) and normal(distribution) == normal(package)
        methods = {method["id"] for method in self.plugins.methods() if mine((origin(method["id"]) or {}).get("distribution"))}
        return methods, {problem for problem, distribution in self.providers(PROBLEMS).items() if mine(distribution)}

    def _keeps(self, identity, plan, judged):
        """What the new version keeps and removes of the installed one's methods and problems, on the install record; ValueError
        naming each dropped method or problem a campaign uses (roadmap L1, decision 25). A kept method that fails validation outside
        the box counts as dropped. The new version's methods are those the validation listed (the report's when it listed none)."""
        from .library_usage import campaign_names, used_methods, used_problems
        old_methods, old_problems = self.provided(plan["package"])
        refused = {row["method_id"] for row in judged["refused_methods"]}
        listed = {row["method_id"] for row in judged["methods"]} or {row["method_id"] for row in plan["report"].get("methods", []) if row.get("method_id")}
        moved = set(judged.get("moved") or ())   # moved to a split's method library (roadmap L6): kept
        new_methods, new_problems = (listed - refused) | moved, set(plan["problem_entry_points"])
        self._update(identity, methods_kept=sorted(old_methods & new_methods), methods_removed=sorted(old_methods - new_methods),
                     problems_kept=sorted(old_problems & new_problems), problems_removed=sorted(old_problems - new_problems),
                     **({"methods_moved": sorted(moved)} if moved else {}))
        if not old_methods - new_methods and not old_problems - new_problems:
            return
        methods, problems, broken = used_methods(self.store), used_problems(self.store), []
        for method in sorted(old_methods - new_methods):
            if method in methods:
                why = "fails validation outside the box" if method in refused else "is left out"
                broken.append(f"method {method} {why}, and {campaign_names(self.store, methods[method])} use{'s' if len(methods[method]) == 1 else ''} it")
        for problem in sorted(old_problems - new_problems):
            if problem in problems:
                broken.append(f"problem {problem} is left out, and {campaign_names(self.store, problems[problem])} "
                              f"use{'s' if len(problems[problem]) == 1 else ''} it")
        if broken:
            example = next((m for m in sorted(old_methods - new_methods) if m in methods), "foo")
            raise ValueError(f"{plan['package']} {plan['version']} would take away what campaigns use: " + "; ".join(broken) + ". A new "
                             "version may add methods and problems but not remove one a campaign uses: keep it unchanged, give a method whose "
                             f"behaviour changes a new name (such as {example}_v2), and make a changed scoring function a new problem id.")

    def _import_replaced(self, target, package):
        """A library the lab had before its repository (L1's archive, the lab's own copy) becomes its first versions, once."""
        try:
            current = tomllib.loads((target / "pyproject.toml").read_text()).get("project") or {}
            methods, problems = self.provided(package)
            repositories.imported(self.workspace.directory, self.store, target.name, {"package": current.get("name"),
                "version": str(current.get("version") or ""), "files": lab_files(target, self.root), "methods": sorted(methods),
                "problems": sorted(problems)})
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:   # importing the history never stops an install
            logging.getLogger(__name__).warning("Importing %s into its repository failed: %s", target, exc)

    def _restore_all(self, saved, places):
        """_restore() for every library an install touched."""
        for index, place in enumerate(places):
            self._restore(saved if index == 0 else {}, place["target"], place["backup"], place["created"])

    def _restore(self, saved, target, backup, created):
        """pyproject.toml and uv.lock as they were, and the library directory as it was (the previous copy, or none)."""
        for file, content in saved.items():
            (self.root / file).write_bytes(content)
        if created and target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)

    def _pin(self, package, version, name, blocks=()):
        """The libraries extra pins package==version, [tool.uv.sources] names its editable path, and each dependency it has on a
        package of the shared library repository is pinned (pin_dependencies): to the version its box had (``blocks``), else the
        latest."""
        pin(self.root, package, version, f'{{ path = "libraries/{name}", editable = true }}')
        pin_dependencies(self.root, self.root / "libraries" / name, blocks)


def pin(root, package, version, source):
    """The root pyproject.toml's libraries extra pins package==version, and its [tool.uv.sources] gives the package ``source``
    (an inline table: an editable path, or a tag of the shared library repository)."""
    path = Path(root) / "pyproject.toml"
    text = path.read_text()
    extras = (tomllib.loads(text).get("project") or {}).get("optional-dependencies") or {}
    pins = [line for line in extras.get("libraries", []) if normal(re.split(r"[=<>!~ ;\[]", line, maxsplit=1)[0]) != normal(package)]
    line = "libraries = [" + ", ".join(f'"{item}"' for item in [*pins, f"{package}=={version}"]) + "]"
    text, count = re.subn(r"(?m)^libraries = \[.*\]$", line, text)
    if count != 1:
        raise ValueError("pyproject.toml has no one-line `libraries = [...]` extra to pin the library in")
    entry = f"{package} = {source}"
    text, count = re.subn(rf"(?m)^{re.escape(package)} = \{{.*\}}$", lambda match: entry, text)
    if not count:
        match = re.search(r"(?m)^\[tool\.uv\.sources\]\n((?:(?!\[).*\n?)*)", text)
        if not match:
            raise ValueError("pyproject.toml has no [tool.uv.sources] table to name the library's source in")
        end = match.start(1) + len(match.group(1).rstrip("\n"))   # after the table's last line
        text = text[:end] + "\n" + entry + text[end:]
    path.write_text(text)


def shared_source(repository, row):
    """The [tool.uv.sources] table of a shared repository's package at its latest tag."""
    return f'{{ git = "{Path(repository).resolve().as_uri()}", subdirectory = "{row["name"]}", tag = "{row["tag"]}" }}'


def pin_dependencies(root, folder, blocks=()):
    """Pin each dependency of the library in ``folder`` that is a package of the shared library repository, and not yet one of
    the root's sources, to the tag its box had (``blocks``, the ticket's building_blocks) or else that package's latest: a
    library written around building blocks installs with them. The packages pinned."""
    from . import shared_libraries
    repository = shared_libraries.location(root)
    pyproject = Path(folder) / "pyproject.toml"
    if repository is None or not pyproject.exists():
        return []
    wanted = {shared_libraries.requirement_name(item) for item in (tomllib.loads(pyproject.read_text()).get("project") or {}).get("dependencies") or []}
    if not wanted:
        return []
    sources = ((tomllib.loads((Path(root) / "pyproject.toml").read_text()).get("tool") or {}).get("uv") or {}).get("sources") or {}
    have = {normal(name) for name in sources}
    try:
        rows = shared_libraries.packages(repository)
    except ValueError as exc:   # uv lock then says what it cannot resolve
        logging.getLogger(__name__).warning("Reading the shared library repository failed: %s", exc)
        return []
    given = {normal(block["package"]): block for block in blocks}
    done = []
    for row in rows:
        if row["package"] and normal(row["package"]) in wanted and normal(row["package"]) not in have:
            block = given.get(normal(row["package"]))
            chosen = {"name": row["name"], "tag": block["tag"], "latest": block["version"]} if block and block["version"] in row["versions"] else row
            pin(root, row["package"], chosen["latest"], shared_source(repository, chosen))
            done.append(row["package"])
    return done


def shared_text(install):
    """The install notice's line on the shared library repository."""
    if install.get("published"):
        return f"Published to the shared library repository as {install['published']['tag']} ({install['published']['repository']})."
    return f"Not published: {install['publish_skipped']}" if install.get("publish_skipped") else ""


def distribution_installed(package):
    from importlib import metadata
    try:
        metadata.distribution(package)
        return True
    except metadata.PackageNotFoundError:
        return False


def at_start(workspace, root):
    """What the lab does with its libraries as it starts, in the background (issue #101): restore() what this checkout lacks,
    then import_lab() the lab's copies that have no version yet, so that a coding workspace builds on them (roadmap L3) without
    the Packages page being opened first. Off with Balsamic's own installs (GRATING_AUTO_INSTALL=false); never raises."""
    if os.environ.get("GRATING_AUTO_INSTALL", "true").lower() == "false":
        return None
    try:
        result = restore(workspace, root)
        import_lab(workspace, root)
        return result
    except Exception as exc:
        logging.getLogger(__name__).warning("Restoring the lab's libraries failed: %s", exc)
        return None


def restore(workspace, root, *, runner=run, uv=None, installed=distribution_installed, provided_by=providers):
    """Give a checkout the libraries the lab has (issue #101), as Balsamic's own step at the lab's start: a new checkout of the
    lab, a rebuilt environment or a new data folder no longer starts without them.

    Each library whose latest version the lab recorded (library_version) and whose `libraries/<name>/` this checkout lacks is
    written from its tag in the lab's repository (or, when that is gone, the shared library repository) and pinned as an
    editable path, as an install pins it. Each package of the shared repository the lab has no version of is pinned to its
    latest tag: one with methods or problems also gets its lab copy and is recorded as a version (import_lab), and one with
    neither (building blocks) is a dependency only. A package whose method or problem another installed package provides is
    left out. One uv lock and uv sync then install them, and a library pinned but not installed (a rebuilt environment) too.
    A dry run first: when it would change a package the lab already has, nothing is restored and ``error`` says why; every
    file is put back. {restored, pinned, skipped, synced, error}."""
    from . import shared_libraries
    root, store = Path(root), workspace.store
    uv = uv or shutil.which("uv")
    result = {"restored": [], "pinned": [], "skipped": [], "synced": False, "error": None}
    repository = shared_libraries.location(root)
    try:
        shared = {row["name"]: row for row in shared_libraries.packages(repository)}
    except ValueError as exc:
        shared, result["error"] = {}, f"Reading the shared library repository failed: {exc}"[:500]
    recorded = {row["library"] for row in repositories.versions(store)}
    writes, pins = {}, []
    for name in sorted(recorded):
        latest = repositories.latest(store, name)
        if (root / "libraries" / name / "pyproject.toml").exists():
            continue
        files, origin = {}, None
        try:
            files, origin = repositories.files_at(repositories.path(workspace.directory, name), latest["tag"], name), "the lab's repository"
        except ValueError:
            row = shared.get(name)
            if row and latest["version"] in row["versions"]:
                files = shared_libraries.files_at(repository, shared_libraries.tag_of(name, latest["version"]), name)
                origin = "the shared library repository"
        if not files:
            result["skipped"].append({"library": name, "reason": f"version {latest['version']} is in neither the lab's nor the shared repository"})
            continue
        writes[name] = (latest["package"], latest["version"], files, origin)
    sources = ((tomllib.loads((root / "pyproject.toml").read_text()).get("tool") or {}).get("uv") or {}).get("sources") or {}
    taken = {group: provided_by(group) for group in (GROUP, PROBLEMS)}
    for name, row in sorted(shared.items()):
        if name in recorded or name in writes or not row["package"] or normal(row["package"]) in {normal(key) for key in sources}:
            continue
        clash = [f"{kind} {identity} is provided by {taken[group][identity]}" for kind, group, ids in (("method plug-in", GROUP, row["plugins"]),
                 ("problem", PROBLEMS, row["problems"])) for identity in ids if identity in taken[group] and normal(taken[group][identity] or "the lab") != normal(row["package"])]
        if clash:
            result["skipped"].append({"library": name, "reason": "; ".join(clash)})
        elif row["plugins"] or row["problems"]:
            if not (root / "libraries" / name / "pyproject.toml").exists():
                writes[name] = (row["package"], row["latest"], shared_libraries.files_at(repository, row["tag"], name), "the shared library repository")
        else:
            pins.append(row)
    pinned = [line for line in ((tomllib.loads((root / "pyproject.toml").read_text()).get("project") or {}).get("optional-dependencies") or {}).get("libraries", [])]
    unsynced = [item for item in pinned if not installed(re.split(r"[=<>!~ ;\[]", item, maxsplit=1)[0])]
    if not writes and not pins and not unsynced:
        return result
    saved = {file: (root / file).read_bytes() for file in ("pyproject.toml", "uv.lock") if (root / file).exists()}
    created = []
    log = []
    with _lock:
        try:
            for name, (package, version, files, origin) in writes.items():
                target = root / "libraries" / name
                for path, content in files.items():
                    destination = target / Path(path).relative_to(f"libraries/{name}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                created.append(target)
                pin(root, package, version, f'{{ path = "libraries/{name}", editable = true }}')
                pin_dependencies(root, target)
                result["restored"].append({"library": name, "package": package, "version": version, "from": origin})
            for row in pins:
                pin(root, row["package"], row["latest"], shared_source(repository, row))
                result["pinned"].append({"package": row["package"], "version": row["latest"], "tag": row["tag"]})
            for args in ([uv, "lock"], [uv, "sync", "--dry-run", "--inexact", "--extra", "libraries"]):
                code, output = runner(args, cwd=root)
                log.append(f"$ {' '.join(args[1:])}\n{output}")
                if code:
                    raise ValueError(f"uv {args[1]} failed: " + output.strip()[-800:])
            restored = {normal(item["package"]) for item in result["restored"]} | {normal(item["package"]) for item in result["pinned"]}
            changes = [change for change in changed_packages(output, "", lab_projects(root)) if normal(change["name"]) not in restored]
            if changes:
                raise ValueError("Restoring them would change packages the lab already has: "
                                 + ", ".join(f"{change['name']} {change['from']} → {change.get('to') or 'removed'}" for change in changes))
            code, output = runner([uv, "sync", "--inexact", "--extra", "libraries"], cwd=root)
            log.append(f"$ sync --inexact --extra libraries\n{output}")
            if code:
                raise ValueError("uv sync failed: " + output.strip()[-800:])
            result["synced"] = True
        except Exception as exc:   # the checkout is put back as it was
            for file, content in saved.items():
                (root / file).write_bytes(content)
            for target in created:
                shutil.rmtree(target, ignore_errors=True)
            result.update(restored=[], pinned=[], error=str(exc)[:1000])
    if result["synced"]:
        try:
            import_lab(workspace, root, provided_by=provided_by)
        except Exception as exc:
            logging.getLogger(__name__).warning("Importing the restored libraries failed: %s", exc)
    store.event(None, "library.restored", {key: result[key] for key in ("restored", "pinned", "skipped", "synced", "error")}
                | {"log_tail": "\n".join(log)[-2000:]})
    return result


def lab_files(target, root):
    """{root-relative path: bytes} of a library's copy in the lab, without what building and importing it leave."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in Path(target).rglob("*") if path.is_file()
            and "__pycache__" not in path.parts and not any(part.endswith(".egg-info") for part in path.parts)}


def import_lab(workspace, root, plugins=None, provided_by=providers):
    """Import each library of the lab's libraries/ that has no version yet (one committed with the lab, or installed before L2)
    into its repository, with the methods and problems its package provides now. The versions imported."""
    from optimization_framework.optimizers import plugins as installed
    plugins = plugins or installed.installed
    rows = []
    for pyproject in sorted((Path(root) / "libraries").glob("*/pyproject.toml")):
        name = pyproject.parent.name
        if name.startswith(".") or repositories.versions(workspace.store, name):
            continue
        try:
            project = tomllib.loads(pyproject.read_text()).get("project") or {}
            package = project.get("name")
            mine = lambda distribution: bool(distribution) and bool(package) and normal(distribution) == normal(package)
            methods = sorted(method["id"] for method in plugins.methods() if mine((plugins.origin(method["id"]) or {}).get("distribution")))
            problems = sorted(problem for problem, distribution in provided_by(PROBLEMS).items() if mine(distribution))
            rows += repositories.imported(workspace.directory, workspace.store, name, {"package": package, "version": str(project.get("version") or ""),
                "files": lab_files(pyproject.parent, root), "methods": methods, "problems": problems})
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            logging.getLogger(__name__).warning("Importing %s into its repository failed: %s", name, exc)
    return rows


def base_of(plan):
    """The version a delivery built on (roadmap L3), as the install records it: {base_version} when its workspace started from one."""
    base = (plan["record"].get("library") or {}).get("base")
    return {"base_version": {key: base[key] for key in ("id", "package", "version", "commit")}} if base and plan["record"]["library"].get("name") == plan["name"] else {}


def commit_message(plan, identity):
    """The message of a version's commit in its library's repository: what it is and where it came from."""
    record, submission = plan["record"], plan["submission"]
    return (f"{plan['package']} {plan['version']}\n\nInstalled by {identity} from commit {submission['commit']} of coding workspace "
            f"{record['id']} in campaign {record['campaign_id']} (submission {submission['id']}).")


def kept_text(record):
    """The install notice's line on what the new version keeps and removes of the one it replaced, and the kept methods that
    reproduced their recorded runs (L4); "" for a first install."""
    parts = []
    reproduced = ((record.get("host_validation") or {}).get("reproduced") or {})
    if record.get("methods_kept") or record.get("methods_removed"):
        kept = record.get("methods_kept") or []
        same = [method for method in kept if method in (reproduced.get("methods") or [])]
        parts.append(f"it keeps {len(kept)} method{'s' if len(kept) != 1 else ''}" + (
            f" ({len(same)} reproduce{'s' if len(same) == 1 else ''} {reproduced['runs']} recorded run{'s' if reproduced['runs'] != 1 else ''})" if same else ""))
    if record.get("methods_removed"):
        parts.append(f"removes {', '.join(record['methods_removed'])}, which no campaign uses")
    if record.get("problems_removed"):
        parts.append(f"removes problem {', '.join(record['problems_removed'])}, which no campaign uses")
    return ("Of the version it replaced, " + " and ".join(parts)) if parts else ""


def generated_changes(record, name, files):
    """The generated files of libraries/<name>/ the coding agent changed or removed, when the workspace started from a library
    generated from the charter (its record's `library`, roadmap F4); [] for any other library. Under decision 9 the
    charter's data is fixed: a changed or missing `charter.json` or `data.py` is refused. The two files the agent writes,
    `objective.py` and `methods.py`, are not listed."""
    generated = record.get("library") or {}
    if generated.get("name") != name:
        return []
    digest = lambda path: hashlib.sha256(files[path]).hexdigest() if path in files else None
    for path in generated["fixed"]:
        if digest(path) != generated["files"].get(path):
            raise ValueError(f"The library's data no longer matches the charter revision: {path} differs from the one generated "
                             f"from revision {generated['revision']}; restore it, or regenerate the library from the charter")
    filled = {f"libraries/{name}/{generated['package']}/{file}" for file in ("objective.py", "methods.py")}
    return sorted(path for path, sha in generated["files"].items()
                  if path not in generated["fixed"] and path not in filled and digest(path) != sha)


def refused_text(refused):
    """Methods that failed validation outside the box, each with what failed."""
    return "; ".join(f"{row['method_id']} (reported {row['reported'].replace('_', ' ')}; failed: {', '.join(row['failing'])[:300]})"
                     for row in refused)


def added(record):
    """What an install added, as its notice and the monitor name it: methods, problems (when it provides any), and what was
    not found."""
    parts = [f"methods {', '.join(record.get('methods_added') or []) or 'none new'}"] if record.get("entry_points") or not record.get("problem_entry_points") else []
    if record.get("problem_entry_points") or record.get("problems_added"):
        parts.append(f"problems {', '.join(record.get('problems_added') or []) or 'none new'}")
    missing = [*(record.get("missing_methods") or []), *(record.get("missing_problems") or [])]
    return "; ".join(parts) + (f"; not found: {', '.join(missing)}" if missing else "")


def after_install(workspace, install):
    """What Balsamic does by itself once a library is installed, always in this order: adopt its problem (adopt_provided), bind
    the proposals it serves (bind_served), start the approved runs (plan_runs.launch_ready). {adopted, adoption_skipped,
    bindings, skipped, launched} for the install record."""
    from optimization_framework.campaigns.plan_runs import launch_ready
    adopted = adopt_provided(workspace, install)
    bound = {**adopted, **bind_served(workspace, install)}
    try:
        return {**bound, "launched": launch_ready(workspace, install["campaign_id"])["launched"]}
    except Exception as exc:   # the bindings stand; the next sync tries the runs again
        return {**bound, "launched": [], "launch_error": f"{type(exc).__name__}: {exc}"[:500]}


def adopt_provided(workspace, install):
    """When the install provides the problem its campaign's charter declares, the campaign's declared tasks adopt it (E4),
    through the bus as Balsamic's system actor, citing the install: only when no such task has a bound evaluator or live runs.
    Otherwise it is skipped with the reason, for the lead to adopt with campaign.adopt_problem. Replaying adopts nothing more.
    {adopted: [{old_task_id, new_task_id}], adoption_skipped: {problem_id, reason} or None}."""
    from optimization_framework.contracts.commands import Command, CommandOrigin
    store, campaign_id = workspace.store, install["campaign_id"]
    nothing = {"adopted": [], "adoption_skipped": None}
    provided = (set(install.get("problems_added") or []) | set(install.get("problem_entry_points") or {})) - set(install.get("missing_problems") or [])
    campaign = store.get(campaign_id, "campaign")
    if not provided or not campaign.get("charter"):
        return nothing
    binding = workspace.charters.revision(campaign["charter"]["id"], campaign["charter"]["revision"])["charter"].get("evaluator") or {}
    problem_id = binding.get("problem_id")
    if binding.get("kind") != "declared" or problem_id not in provided:
        return nothing
    old = [task for task in workspace.current_tasks(campaign_id) if (task.get("evaluator_manifest") or {}).get("id") == problem_id]
    if not old:
        return nothing
    reason = workspace.unused(old)
    if not reason:
        command = Command(id="balsamic_adopt_" + content_hash([install["id"], campaign_id])[:24], campaign_id=campaign_id,
            operation="campaign.adopt_problem", expected_revision=campaign["version"],
            origin=CommandOrigin(actor="balsamic", rationale=f"After installing {install['package']} {install['version']} ({install['id']})"),
            payload={"install_id": install["id"], "rationale": f"{install['package']} {install['version']}, installed from commit "
                     f"{install['commit'][:7]}, provides {problem_id}, the problem the charter declares, and nothing ran on its tasks yet."})
        try:
            receipt = workspace.commands.execute(command, actor="balsamic")
        except ValueError as exc:
            reason = str(exc)[:300]
        else:
            return {"adopted": [{"old_task_id": row["old_task_id"], "new_task_id": row["new_task_id"]} for row in receipt["outcome"]["adopted"]],
                    "adoption_skipped": None}
    return {"adopted": [], "adoption_skipped": {"problem_id": problem_id, "reason": reason}}


def adoption_text(install):
    """The install notice's line on the campaign's tasks adopting its problem, or why Balsamic left that to the lead."""
    if install.get("adopted"):
        return f"Balsamic had {len(install['adopted'])} task{'s' if len(install['adopted']) > 1 else ''} adopt its problem."
    skipped = install.get("adoption_skipped")
    if skipped:
        return (f"Balsamic did not adopt {skipped['problem_id']} for the campaign's tasks: {skipped['reason']}. Adopt it when that is "
                f"settled with campaign.adopt_problem (install_id {install['id']}).")
    return ""


def bind_served(workspace, install):
    """Bind each proposal the install's submission serves to its method, through the bus as Balsamic's system actor (decision
    6), citing the install: only when exactly one of the methods the delivery reports for it is installed and runnable on a
    current task. A proposal someone bound, one using another method and one with several candidate methods are skipped,
    each with its reason."""
    from optimization_framework.campaigns.method_catalog import methods_for, served
    from optimization_framework.contracts.commands import Command, CommandOrigin
    from optimization_framework.execution.service import algorithms
    from optimization_framework.optimizers.registry import capability_reason
    store, campaign_id = workspace.store, install["campaign_id"]
    submission = store.get(install["submission_id"], "development_submission")
    installed = {method["id"] for method in algorithms()}
    refused = {row["method_id"] for row in install.get("refused_methods") or []}
    tasks = [task for task in workspace.current_tasks(campaign_id) if task.get("problem")]
    bindings, skipped = [], []
    for hypothesis_id in served(submission):
        try:
            hypothesis = store.get(hypothesis_id, "hypothesis")
        except KeyError:
            skipped.append({"hypothesis_id": hypothesis_id, "reason": "No such proposal"})
            continue
        methods = methods_for(submission, hypothesis_id)
        runnable, reasons = {}, []
        for method in methods:
            if method in refused:
                reasons.append(f"{method} failed validation outside the box")
                continue
            if method not in installed:
                reasons.append(f"{method} is not installed")
                continue
            why = [capability_reason(method, task["problem"]) for task in tasks]
            if None in why:
                runnable[method] = tasks[why.index(None)]
            else:
                reasons += sorted(set(why)) or [f"{method}: the campaign has no task with a problem definition"]
        reason = None
        if hypothesis.get("campaign_id") != campaign_id:
            reason = "The proposal belongs to another campaign"
        elif hypothesis.get("status") == "archived":
            reason = "The proposal is stopped"
        elif hypothesis.get("implementation_version_id"):
            reason = "The proposal runs a published implementation"
        elif hypothesis.get("builtin_binding_id"):
            try:
                binding = store.get(hypothesis["builtin_binding_id"], "builtin_binding")
            except KeyError:
                binding = {}
            by = {"researcher": "the researcher", "balsamic": "Balsamic"}.get(binding.get("authority"), "an agent" if binding.get("authority") else "earlier")
            reason = f"Already bound to {hypothesis['algorithm']} by {by}" if by != "earlier" else f"Already bound to {hypothesis['algorithm']}"
        elif hypothesis.get("algorithm_chosen") is not False and hypothesis.get("algorithm") in installed:
            reason = f"It uses {hypothesis['algorithm']}" + (", already installed" if hypothesis["algorithm"] in methods else ", another method")
        elif not methods:
            reason = "The delivery reports no method for it"
        elif not runnable:
            reason = "; ".join(reasons)
        elif len(runnable) > 1:
            reason = f"Several methods could serve it ({', '.join(sorted(runnable))}); the lead chooses one"
        if reason:
            skipped.append({"hypothesis_id": hypothesis_id, "reason": reason})
            continue
        (method, task), = runnable.items()
        campaign = store.get(campaign_id, "campaign")
        command = Command(id="balsamic_bind_" + content_hash([install["id"], hypothesis_id])[:24], campaign_id=campaign_id,
            operation="implementation.bind_builtin", expected_revision=campaign["version"],
            origin=CommandOrigin(actor="balsamic", rationale=f"After installing {install['package']} {install['version']} ({install['id']})"),
            payload={"hypothesis_id": hypothesis_id, "task_id": task["id"], "algorithm": method, "parameters": {},
                     "expected_algorithm": hypothesis.get("algorithm"),
                     "expected_configuration_hash": content_hash(hypothesis.get("algorithm_config", {})), "install_id": install["id"],
                     "reason": f"{install['package']} {install['version']}, installed from commit {install['commit'][:7]}, provides {method}, "
                               "the one method its delivery reports for this proposal that runs on a current task."})
        try:
            receipt = workspace.commands.execute(command, actor="balsamic")
        except ValueError as exc:
            skipped.append({"hypothesis_id": hypothesis_id, "reason": str(exc)[:300]})
            continue
        bindings.append({"hypothesis_id": hypothesis_id, "title": hypothesis.get("short_title") or hypothesis.get("title") or hypothesis_id,
                         "method": method, "task_id": task["id"], "binding_id": receipt["outcome"]["binding_id"], "command_id": receipt["id"]})
    return {"bindings": bindings, "skipped": skipped}


def bound_text(install):
    """The install notice's line on what Balsamic bound and what it left."""
    done = "; ".join(f"{row['hypothesis_id']} to {row['method']}" for row in install.get("bindings") or [])
    left = "; ".join(f"{row['hypothesis_id']} ({row['reason']})" for row in install.get("skipped") or [])
    return ((f"Balsamic bound {done}." if done else "Balsamic bound no proposal.")
            + (f" Not bound: {left}." if left else "")
            + (f" Balsamic started {len(install['launched'])} approved run{'s' if len(install['launched']) != 1 else ''}: "
               + "; ".join(f"{row['hypothesis_id']} seed {row['seed']} ({row['trial_id']})" for row in install["launched"]) + "."
               if install.get("launched") else "")
            + (f" Binding stopped: {install['after_install_error']}." if install.get("after_install_error") else ""))


def lab_projects(root):
    """The lab's own projects: the root pyproject.toml's and each libraries/*/pyproject.toml's name."""
    root, names = Path(root), set()
    for path in [root / "pyproject.toml", *sorted((root / "libraries").glob("*/pyproject.toml"))]:
        try:
            names.add((tomllib.loads(path.read_text()).get("project") or {}).get("name"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
    return {name for name in names if name}


def changed_packages(output, package, own=()):
    """Packages a dry run would remove or change, other than the library itself and the lab's own projects: [{name, from, to}].
    A package removed and added again at the same version or from the same url is a reinstall, not a change."""
    normal = lambda value: re.sub(r"[-_.]+", "-", value).lower()
    skip = {normal(name) for name in [package, *own]}
    removed, added = {}, {}
    for line in output.splitlines():
        if match := CHANGE.match(line):
            sign, name, version, source, url = match.groups()
            if normal(name) in skip:
                continue
            (removed if sign == "-" else added)[normal(name)] = (version, source or url)
    def same(old, new):   # what both lines name agrees, and they name something in common
        pairs = [(a, b) for a, b in zip(old, new or (None, None)) if a and b]
        return bool(pairs) and all(a == b for a, b in pairs)
    return [{"name": name, "from": old[0] or old[1], "to": added[name][0] or added[name][1] if name in added else None}
            for name, old in sorted(removed.items()) if not same(old, added.get(name))]
