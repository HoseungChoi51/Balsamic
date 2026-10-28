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

    def prepare(self, campaign_id, workspace_id, submission_id, *, accept_not_ready=False):
        """What would be installed: {name, package, version, methods, files, report}; ValueError when it cannot be."""
        from optimization_framework.campaigns.method_catalog import library_of
        record = self.development.get(campaign_id, workspace_id)
        submission = self.store.get(submission_id, "development_submission")
        if submission["workspace_id"] != workspace_id or submission["campaign_id"] != campaign_id:
            raise ValueError("The submission belongs to another workspace")
        name = library_of(submission)
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
        self._refuse_clashes(package, entries, problems, report)
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

    def _refuse_clashes(self, package, entries, problems, report):
        """A problem id, plug-in name or method id that another installed distribution (the lab's own included) provides is
        refused before uv runs: the registries would keep the first one loaded, or stop listing either. The library's own
        earlier version is no clash."""
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
            if found and theirs(found.get("distribution")):
                raise ValueError(f"method {method_id} is provided by {found.get('distribution') or 'the lab'}")

    # Install ----------------------------------------------------------------------------------------------------------
    def automatic(self, campaign_id, workspace_id, submission, *, background=True):
        """Balsamic's own install of a delivered library, once per submission: none for a delivery its coding agent reports not
        ready, or one delivered as loose files. A refusal (the same version with other code, files that differ from what was
        submitted) is recorded as a failed install and told to the lead."""
        from optimization_framework.campaigns.method_catalog import library_of
        if (submission.get("report") or {}).get("verdict") == "not_ready" or not library_of(submission):
            return None
        if any(row.get("submission_id") == submission["id"] for row in self.store.list("library_install", campaign_id)):
            return None
        try:
            return self.request(campaign_id, workspace_id, submission["id"], request_key="automatic", actor="balsamic", background=background)
        except ValueError as exc:
            identity = "library_install_" + content_hash([submission["id"], "automatic"])[:24]
            record = self.store.put("library_install", {"id": identity, "campaign_id": campaign_id, "workspace_id": workspace_id,
                "submission_id": submission["id"], "commit": submission["commit"], "package": None, "version": None,
                "path": f"libraries/{library_of(submission)}", "entry_points": {}, "problem_entry_points": {}, "actor": "balsamic",
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
        plan = self.prepare(campaign_id, workspace_id, submission_id, accept_not_ready=accept_not_ready)
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
                   **({"retry_of": retry_of} if retry_of else {}), **base_of(plan)}
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
        try:
            result = self.validator(plan["files"], plan["name"], instances=validation.instances_of(self.workspace, record["campaign_id"]),
                                    protected=validation.protected_tests(self.store, record))
        except ValueError as exc:
            raise ValueError(f"Balsamic could not validate the library outside the box: {exc}") from None
        self._charge(record, identity, result.get("seconds") or 0.0)
        judged = validation.verdict(result, plan["report"])
        host = {**validation.public(result), **judged, "at": now()}
        self._update(identity, host_validation=host, refused_methods=judged["refused_methods"])
        listed = [row["method_id"] for row in judged["methods"]]
        if judged["library_failures"]:
            raise ValueError("Validation outside the box failed, in tests no method owns: " + "; ".join(judged["library_failures"][:10]))
        if listed and not plan["problem_entry_points"] and len(judged["refused_methods"]) == len(listed):
            raise ValueError("Validation outside the box failed for every method: " + refused_text(judged["refused_methods"]))
        return judged

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
        with _lock:
            name, root = plan["name"], self.root
            target, staging = root / "libraries" / name, root / "libraries" / f".staging-{identity}"
            backup = root / "libraries" / f".previous-{name}-{identity}"
            saved = {file: (root / file).read_bytes() for file in ("pyproject.toml", "uv.lock") if (root / file).exists()}
            log, created = [], False
            try:
                self._update(identity, status="installing")
                before = {method["id"] for method in self.plugins.methods()}
                problems_before = set(self.problems.ids())
                if target.exists():
                    self._import_replaced(target, plan["package"])
                # The lab's copy is the version's commit in the library's repository: written from it, checked against the submission.
                repository, made = repositories.commit(self.workspace.directory, name, plan["files"], commit_message(plan, identity))
                repositories.check_tag(repository, made, plan["version"])
                exported = repositories.files_at(repository, made, name)
                if exported != plan["files"]:
                    raise ValueError("The library's repository does not hold what was submitted")
                for path, content in exported.items():
                    destination = staging / Path(path).relative_to(f"libraries/{name}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                if target.exists():
                    target.rename(backup)
                staging.rename(target)
                created = True
                self._pin(plan["package"], plan["version"], name)
                for args in ([self.uv, "lock"], [self.uv, "sync", "--dry-run", "--inexact", "--extra", "libraries"]):
                    code, output = self.runner(args, cwd=root)
                    log.append(f"$ {' '.join(args[1:])}\n{output}")
                    if code:
                        raise ValueError(f"uv {args[1]} failed: " + output.strip()[-800:])
                changes = changed_packages(output, plan["package"], lab_projects(root))
                if changes and not confirm_changes:
                    self._restore(saved, target, backup, created)
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
                if backup.exists():
                    shutil.rmtree(backup)
                kept = self.store.get(identity, "library_install")
                tagged = repositories.publish(repository, made, plan["version"])
                version = repositories.record(self.store, name, plan["package"], plan["version"], tagged,
                    source={"install_id": identity, "campaign_id": plan["record"]["campaign_id"], "workspace_id": plan["record"]["id"],
                            "submission_id": plan["submission"]["id"], "commit": plan["submission"]["commit"], "actor": kept["actor"]},
                    methods=sorted({*(kept.get("methods_kept") or []), *(after - before - refused)}), problems=sorted(plan["problem_entry_points"]))
                record = self._update(identity, "library.installed", status="installed", finished_at=now(), changes=changes,
                                      library_version_id=version["id"], tag=version["tag"], library_commit=tagged,
                                      methods_added=sorted(after - before - refused), missing_methods=sorted(set(reported) - after - refused),
                                      problems_added=sorted(problems_after - problems_before),
                                      missing_problems=sorted(set(plan["problem_entry_points"]) - problems_after),
                                      log_tail="\n".join(log)[-4000:])
            except Exception as exc:   # every failure is recorded and the lab is put back as it was
                self._restore(saved, target, backup, created)
                return self._update(identity, "library.install_failed", status="failed", finished_at=now(), error=str(exc)[:2000],
                                    log_tail="\n".join(log)[-4000:])
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        # The library is in: what Balsamic does next never undoes the install.
        self._feedback(identity, plan)
        try:
            record = self._update(identity, **after_install(self.workspace, record))
        except Exception as exc:
            record = self._update(identity, adopted=[], adoption_skipped=None, bindings=[], skipped=[],
                                  after_install_error=f"{type(exc).__name__}: {exc}"[:500])
        who = "The researcher" if record["actor"] == "researcher" else "Balsamic"
        adoption = adoption_text(record)
        self.development.notify(plan["record"], identity, f"{who} installed {plan['package']} {plan['version']} from commit "
            f"{plan['submission']['commit'][:7]}: {added(record)}." + (f" {kept_text(record)}." if kept_text(record) else "")
            + (f" Not installed, failed outside the box: {refused_text(record['refused_methods'])}." if record.get("refused_methods") else "")
            + (f" Generated files it changed: {', '.join(plan['changed_generated_files'])}." if plan["changed_generated_files"] else "")
            + (" " + adoption if adoption else "")
            + (" " + bound_text(record) + " Tell the researcher which proposals can run now." if plan["entry_points"] else ""), "installs")
        return record

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
        new_methods, new_problems = listed - refused, set(plan["problem_entry_points"])
        self._update(identity, methods_kept=sorted(old_methods & new_methods), methods_removed=sorted(old_methods - new_methods),
                     problems_kept=sorted(old_problems & new_problems), problems_removed=sorted(old_problems - new_problems))
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

    def _restore(self, saved, target, backup, created):
        """pyproject.toml and uv.lock as they were, and the library directory as it was (the previous copy, or none)."""
        for file, content in saved.items():
            (self.root / file).write_bytes(content)
        if created and target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)

    def _pin(self, package, version, name):
        """The libraries extra pins package==version, and [tool.uv.sources] names its editable path."""
        path = self.root / "pyproject.toml"
        text = path.read_text()
        extras = (tomllib.loads(text).get("project") or {}).get("optional-dependencies") or {}
        normal = lambda value: re.sub(r"[-_.]+", "-", value).lower()
        pins = [pin for pin in extras.get("libraries", []) if normal(re.split(r"[=<>!~ ;\[]", pin, maxsplit=1)[0]) != normal(package)]
        line = "libraries = [" + ", ".join(f'"{pin}"' for pin in [*pins, f"{package}=={version}"]) + "]"
        text, count = re.subn(r"(?m)^libraries = \[.*\]$", line, text)
        if count != 1:
            raise ValueError("pyproject.toml has no one-line `libraries = [...]` extra to pin the library in")
        source = f'{package} = {{ path = "libraries/{name}", editable = true }}'
        text, count = re.subn(rf"(?m)^{re.escape(package)} = \{{.*\}}$", source, text)
        if not count:
            match = re.search(r"(?m)^\[tool\.uv\.sources\]\n((?:(?!\[).*\n?)*)", text)
            if not match:
                raise ValueError("pyproject.toml has no [tool.uv.sources] table to name the library's path in")
            end = match.start(1) + len(match.group(1).rstrip("\n"))   # after the table's last line
            text = text[:end] + "\n" + source + text[end:]
        path.write_text(text)


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
    """The install notice's line on what the new version keeps and removes of the one it replaced; "" for a first install."""
    parts = []
    if record.get("methods_kept") or record.get("methods_removed"):
        parts.append(f"it keeps {len(record.get('methods_kept') or [])} method{'s' if len(record.get('methods_kept') or []) != 1 else ''}")
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
