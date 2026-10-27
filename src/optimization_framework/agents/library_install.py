"""Installing a coding workspace's library into the lab. Balsamic does it by itself once a workspace delivers (not a delivery
its coding agent reports not ready); the researcher can install again from the Implementations page.

The exact submitted commit's `libraries/<name>/` is read from the workspace's own Git store (listed and read as blobs: no
filter, hook or attribute of a repository the coding agent could write runs on the host), checked against what was
submitted, and copied into the lab's `libraries/<name>/`. The root pyproject.toml pins it in the `libraries` extra as an
editable path dependency, `uv lock` and `uv sync --inexact --extra libraries` install it, and the running lab picks its
methods and problems up at the next listing. A library provides methods (`optimization_framework.optimizers` entry points),
problems (`optimization_framework.problems`), or both; a method or problem id another installed package provides is refused
before uv runs. A dry run first: a change to any package already installed waits for the researcher's
confirmation (it could affect their other campaigns); a reinstall and the lab's own projects are no change. Every file this
touched is put back when it stops or fails. Each install is a `library_install` record: who (balsamic or the researcher),
when, what (package, version, commit, workspace, submission), the methods and problems it added, and how it ended.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import tomllib
from pathlib import Path, PurePosixPath

from importlib import metadata

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

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
    def __init__(self, workspace, development, root, runner=run, uv=None, plugins=None, problems=None, providers=providers):
        """runner runs uv (tests give their own); Git always runs directly, read-only. providers(group) names the installed
        distribution of each entry point of a group."""
        from optimization_framework.evaluation.registry import problems as registry
        from optimization_framework.optimizers import plugins as installed
        self.workspace, self.store, self.development = workspace, workspace.store, development
        self.root = Path(root)
        self.runner = runner
        self.uv = uv or shutil.which("uv")
        self.plugins = plugins or installed.installed
        self.problems = problems or registry
        self.providers = providers

    # Checks -----------------------------------------------------------------------------------------------------------
    def _git(self, record, *args):
        git = self.development.driver.root(record) / "work" / "git"
        done = subprocess.run(["git", "--no-replace-objects", f"--git-dir={git}", *args], cwd=self.root, capture_output=True, timeout=60, env=GIT_ENV)
        if done.returncode:
            raise ValueError("Reading the submitted commit failed: " + done.stderr.decode(errors="replace").strip()[:500])
        return done.stdout

    def files(self, record, submission, name):
        """{path: bytes} of libraries/<name>/ at the submitted commit."""
        listing = self._git(record, "ls-tree", "-r", "-z", "--full-tree", submission["commit"], "--", f"libraries/{name}").decode()
        found, total = {}, 0
        for item in filter(None, listing.split("\0")):
            meta, path = item.split("\t", 1)
            mode, kind, _ = meta.split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError(f"{path} is a {'link' if mode == '120000' else kind}: a library holds plain files only")
            pure = PurePosixPath(path)
            if pure.is_absolute() or ".." in pure.parts or pure.parts[:2] != ("libraries", name):
                raise ValueError(f"{path} leaves libraries/{name}/")
            found[path] = content = self._git(record, "cat-file", "blob", f"{submission['commit']}:{path}")
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
            existing = {path.relative_to(self.root).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()
                        and "__pycache__" not in path.parts and not any(part.endswith(".egg-info") for part in path.parts)}
            if str(current.get("version")) == version and existing != files:
                raise ValueError(f"{package} {version} is installed with other code; the coding agent has to raise the version for the lab to load the new code")
        return {"name": name, "package": package, "version": version, "entry_points": entries, "problem_entry_points": problems,
                "files": files, "report": report, "record": record, "submission": submission}

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
                "missing_methods": [], "problems_added": [], "missing_problems": [], "changes": [], "log_tail": ""}, "library.install_failed")
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
                   "missing_problems": [], "changes": [], "log_tail": "",
                   **({"retry_of": retry_of} if retry_of else {})}
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

    def install(self, identity, plan, confirm_changes):
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
                for path, content in plan["files"].items():
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
                record = self._update(identity, "library.installed", status="installed", finished_at=now(), changes=changes,
                                      methods_added=sorted(after - before), missing_methods=sorted(set(reported) - after),
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
        try:
            record = self._update(identity, **after_install(self.workspace, record))
        except Exception as exc:
            record = self._update(identity, bindings=[], skipped=[], after_install_error=f"{type(exc).__name__}: {exc}"[:500])
        who = "The researcher" if record["actor"] == "researcher" else "Balsamic"
        self.development.notify(plan["record"], identity, f"{who} installed {plan['package']} {plan['version']} from commit "
            f"{plan['submission']['commit'][:7]}: {added(record)}."
            + (" " + bound_text(record) + " Tell the researcher which proposals can run now." if plan["entry_points"] else ""), "installs")
        return record

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


def added(record):
    """What an install added, as its notice and the monitor name it: methods, problems (when it provides any), and what was
    not found."""
    parts = [f"methods {', '.join(record.get('methods_added') or []) or 'none new'}"] if record.get("entry_points") or not record.get("problem_entry_points") else []
    if record.get("problem_entry_points") or record.get("problems_added"):
        parts.append(f"problems {', '.join(record.get('problems_added') or []) or 'none new'}")
    missing = [*(record.get("missing_methods") or []), *(record.get("missing_problems") or [])]
    return "; ".join(parts) + (f"; not found: {', '.join(missing)}" if missing else "")


def after_install(workspace, install):
    """What Balsamic does by itself once a library is installed, always in this order: adopt its problem (E5), bind the
    proposals it serves (bind_served), start the approved runs (plan_runs.launch_ready). {bindings, skipped, launched} for the
    install record."""
    from optimization_framework.campaigns.plan_runs import launch_ready
    bound = bind_served(workspace, install)
    try:
        return {**bound, "launched": launch_ready(workspace, install["campaign_id"])["launched"]}
    except Exception as exc:   # the bindings stand; the next sync tries the runs again
        return {**bound, "launched": [], "launch_error": f"{type(exc).__name__}: {exc}"[:500]}


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
