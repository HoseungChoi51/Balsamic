"""Validation outside the box (roadmap H6): before a delivered library's install counts, the host runs on the exact commit's
files, in a sandbox with no network, what the coding agent only reported: the library's own tests (the generated contract
tests among them, F3), conformance for each method (`check_function` for a plain-function method, `check` for any other),
and the protected acceptance tests kept on the host, which the box never saw.

The host writes the commit's files into a fresh directory, starts this module with `python -m` under bubblewrap (no network,
a read-only view of the lab's Python and Balsamic, nothing of the lab's data), and reads one result file back. A method whose
own tests or conformance fail is refused; a failure no method owns (a broken objective, a collection error) refuses the
library. Protected tests come back as names and outcomes only: their source and their failure text stay on the host. A
method refused here is not bound and does not run until a version that passes is installed (refused_reason()).

Tests accumulate (roadmap L4): beside the new version's own tests, the sandbox runs every earlier version's tests the new one does
not hold unchanged (mounted read-only at /earlier; earlier_tests()), and the protected tests of every earlier workspace of the
library. And kept methods reproduce their recorded runs: for each method and problem of the installed version that the new one
keeps, the first evaluations of up to three recorded runs (recorded_runs()) are replayed in the sandbox (_replays()): the method,
with the run's seed, settings and problem instance, fed the recorded results, must propose the recorded candidates; the problem
must evaluate them to the recorded results. A difference refuses the method, or the library for a problem (decision 25: a
changed behaviour is a new name).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path, PurePosixPath

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

TIMEOUT_SECONDS = 600
MEMORY_BYTES = 4 * 1024**3
RESULT_BYTES = 4 * 1024**2
FAILURES = 200   # the failing tests an install record keeps, each with why
PROTECTED = "development_protected_test"
# Inside the sandbox.
LIBRARY, TESTS, OUT, EARLIER, DEPENDENCIES = "/library", "/protected", "/out", "/earlier", "/dependencies"
REPLAY_RUNS, REPLAY_EVALUATIONS = 3, 8   # recorded runs replayed per kept method or problem, and evaluations of each


class ValidationUnavailable(ValueError):
    pass


# Protected acceptance tests: kept on the host with the workspace (the ticket's, roadmap H4), never mounted in the box --------
def protect(store, record, name, content):
    """Keep a protected acceptance test for a workspace: a pytest file the coder never sees, run on every delivery."""
    if not re.fullmatch(r"test_[A-Za-z0-9_]{1,80}\.py", name):
        raise ValueError("A protected test is a pytest file named test_<name>.py")
    return store.put(PROTECTED, {"id": "development_protected_" + content_hash([record["id"], name])[:24], "campaign_id": record["campaign_id"],
        "workspace_id": record["id"], "name": name, "content": str(content), "created_at": now()}, "development.protected_test_saved")


def protected_tests(store, record):
    """{file name: source} of a workspace's protected tests."""
    return {row["name"]: row["content"] for row in store.list(PROTECTED, record["campaign_id"]) if row["workspace_id"] == record["id"]}


# The host side ---------------------------------------------------------------------------------------------------------------
SYSTEM = ("/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin", "/etc/ld.so.cache", "/etc/localtime")


def source():
    """The directory that holds this Balsamic's packages (optimization_framework): the sandbox runs the host's own code, so what
    validates a library is the Balsamic that installs it."""
    return Path(__file__).resolve().parents[2]


def links(executable=None):
    """Each symlink between the interpreter and its binary, in order (a venv's python -> /usr/bin/python3 ->
    /etc/alternatives/python3 -> /usr/bin/python3.13), as agents/files.py interpreter() follows them: the sandbox starts the
    interpreter only if every link of the chain is there."""
    found, hop = [], executable or sys.executable
    while os.path.islink(hop):
        hop = os.path.normpath(os.path.join(os.path.dirname(hop), os.readlink(hop)))   # an absolute target replaces the directory
        found.append(hop)
    return found


def roots():
    """What the sandboxed Python reads besides the system: the lab's environment and its installation, the directories the
    environment's .pth files name (the lab's editable installs) and Balsamic's own source. Nothing else of the host: not its
    data, its home or /etc (a link of the interpreter's chain there is bound by itself, command())."""
    found = {Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).resolve().parents[1], source()}
    for site in {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}:
        found.add(Path(site))
        for pth in Path(site).glob("*.pth"):
            for line in pth.read_text(errors="replace").splitlines():
                if line.strip() and not line.startswith(("#", "import")) and Path(line.strip()).is_dir():
                    found.add(Path(line.strip()))
    return sorted({path.resolve() for path in found if path.exists()})


def command(library, protected, out, request, earlier=None, dependencies=None):
    """The bubblewrap command: no network, no host environment, read-only system and Python, the library and the protected
    tests read-only, and only the result directory writable."""
    bwrap = shutil.which("bwrap")
    if not bwrap or sys.platform != "linux":
        raise ValidationUnavailable("Validating a library outside the box needs Linux and bubblewrap (bwrap): install bubblewrap")
    args = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in SYSTEM:
        args += ["--ro-bind-try", path, path]
    bound = [*map(Path, SYSTEM), *roots()]
    for path in roots():
        args += ["--ro-bind", str(path), str(path)]
    # A link of the interpreter's chain outside what is bound (a Debian /etc/alternatives entry) is bound as itself: its target.
    # A directory on that path can be a link itself (uv's cpython-3.13-... -> cpython-3.13.13-...): binding the one file at that
    # path leaves Python without its standard library, so the link is recreated and its target bound.
    for hop in links():
        if any(Path(hop).is_relative_to(root) for root in bound):
            continue
        linked = next((ancestor for ancestor in reversed(Path(hop).parents) if ancestor.is_symlink()), None)
        if linked is None:
            args += ["--ro-bind", hop, hop]
            continue
        args += ["--symlink", os.readlink(linked), str(linked)]
        target = linked.resolve()
        if not any(target.is_relative_to(root) for root in bound):
            args += ["--ro-bind", str(target), str(target)]
    args += ["--ro-bind", str(library), LIBRARY, "--ro-bind", str(protected), TESTS, "--bind", str(out), OUT, "--chdir", LIBRARY]
    if earlier is not None:
        args[-2:-2] = ["--ro-bind", str(earlier), EARLIER]
    if dependencies is not None:   # the method libraries a split's problem library depends on (roadmap L6)
        args[-2:-2] = ["--ro-bind", str(dependencies), DEPENDENCIES]
    environment = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                   "PYTHONHASHSEED": "0", "PYTHONPATH": str(source()), "GRATING_LLM_DISABLED": "true", "MPLBACKEND": "Agg",
                   "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    for key, value in environment.items():
        args += ["--setenv", key, value]
    return [*args, "--", sys.executable, "-B", "-s", "-m", __name__, json.dumps(request)]


def run(files, name, *, instances=(), protected=None, earlier=None, replays=(), dependencies=None, timeout=TIMEOUT_SECONDS):
    """Validate libraries/<name>/ as {path: bytes} (the exact commit's): the result, with `seconds` it took. ValidationUnavailable
    when the sandbox cannot run, ValueError when it ran and gave no result. ``dependencies``: {libraries/<other>/...: bytes} of
    libraries it imports that are not installed yet (a split's method library, roadmap L6), importable beside it."""
    from .library_install import GROUP, PROBLEMS
    import tomllib
    prefix = f"libraries/{name}/"
    project = tomllib.loads(files[prefix + "pyproject.toml"].decode()).get("project") or {}
    groups = project.get("entry-points") or {}
    request = {"entry_points": groups.get(GROUP) or {}, "problem_entry_points": groups.get(PROBLEMS) or {},
               "instances": list(instances), "protected": bool(protected), "earlier": bool(earlier), "replays": list(replays),
               "dependencies": sorted({PurePosixPath(path).parts[1] for path in dependencies or {}}),
               "memory_bytes": MEMORY_BYTES}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="balsamic-validation-") as temporary:
        library, tests, out, before, needed = (Path(temporary) / part for part in ("library", "protected", "out", "earlier", "dependencies"))
        for directory in (library, tests, out, before, needed):
            directory.mkdir()
        for path, content in (dependencies or {}).items():
            relative = PurePosixPath(path).relative_to("libraries")
            (needed / relative).parent.mkdir(parents=True, exist_ok=True)
            (needed / relative).write_bytes(content)
        for relative, content in (earlier or {}).items():
            (before / relative).parent.mkdir(parents=True, exist_ok=True)
            (before / relative).write_bytes(content)
        for path, content in files.items():
            relative = PurePosixPath(path).relative_to(prefix)
            (library / relative).parent.mkdir(parents=True, exist_ok=True)
            (library / relative).write_bytes(content)
        for test, source in (protected or {}).items():
            (tests / test).write_text(source)
        process = subprocess.Popen(command(library, tests, out, request, before if earlier else None, needed if dependencies else None), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True, env={"PATH": "/usr/bin:/bin"})
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise ValueError(f"Validating the library outside the box took longer than {timeout} s") from None
        result = out / "result.json"
        if not result.is_file() or result.stat().st_size > RESULT_BYTES:
            tail = (output or b"").decode(errors="replace").strip()[-800:]
            raise ValueError("Validating the library outside the box gave no result" + (f": {tail}" if tail else ""))
        found = json.loads(result.read_text())
    return {**found, "seconds": round(time.monotonic() - started, 3)}


def owner_of(test, methods):
    """The method a test is parametrized with ([<id>], [<id>-...], [...-<id>]), or None."""
    return next((method for method in methods if f"[{method}]" in test or f"[{method}-" in test or f"-{method}]" in test), None)


def verdict(result, report, removed=()):
    """What the host's result means for the install: {refused_methods, library_failures, methods}. A method is refused when
    its conformance, one of its own tests (a test parametrized with its id, the library's, a protected or an earlier version's
    one) or a replay of one of its recorded runs fails; a failed test no method owns, and a problem that does not reproduce a
    recorded run, are the library's. An earlier version's test of a method the new version ``removed`` (one it owns, or one
    whose failure names it) does not count."""
    methods = {row["method_id"]: row for row in result.get("methods", [])}
    reported = {row.get("method_id"): row.get("conformance") for row in (report or {}).get("methods", [])}
    owners, library = {}, []
    for kind in ("tests", "protected", "earlier"):
        for row in (result.get(kind) or {}).get("results", []):
            if row["outcome"] != "failed":
                continue
            owner = owner_of(row["test"], methods)
            if kind == "earlier" and not owner and any(owner_of(row["test"], removed) or method in (row.get("detail") or "") for method in removed):
                continue
            test = row["test"] if kind != "earlier" else f"{row['test']} (an earlier version's test)"
            (owners.setdefault(owner, []) if owner else library).append({"test": test, "protected": kind == "protected"})
    for row in result.get("replays") or []:
        if row["outcome"] == "reproduced":
            continue
        what = f"does not reproduce run {row['trial_id']} at evaluation {row.get('at') or '?'}: {row.get('detail') or row['outcome']}"
        if row["kind"] == "method" and row["id"] in methods:
            owners.setdefault(row["id"], []).append({"test": what, "protected": False})
        elif row["kind"] == "problem":
            library.append({"test": f"problem {row['id']} {what}", "protected": False})
    refused, rows = [], []
    for method_id, row in sorted(methods.items()):
        failing = owners.get(method_id, [])
        name = row.get("failed_check") and f"conformance ({row['check']} on {row.get('problem_id')}): {row['failed_check']}"
        tests = [item["test"] for item in failing]
        rows.append({"method_id": method_id, "reported": reported.get(method_id, "not_reported"), "host": row["conformance"],
                     "check": row.get("check"), "problem_id": row.get("problem_id"), "failed_tests": tests,
                     **({"reason": row["reason"]} if row.get("reason") else {})})
        if row["conformance"] == "failed" or failing:
            refused.append({"method_id": method_id, "reported": reported.get(method_id, "not_reported"),
                            "failing": [*([name] if name else []), *tests]})
    failures = [item["test"] for item in library] + ([result["error"]] if result.get("error") else [])
    return {"refused_methods": refused, "library_failures": failures, "methods": rows}


def reproduced(result):
    """{methods, problems, runs} that reproduced their recorded runs, for the install's notice and card."""
    rows = result.get("replays") or []
    ok = lambda kind: sorted({row["id"] for row in rows if row["kind"] == kind} - {row["id"] for row in rows if row["kind"] == kind and row["outcome"] != "reproduced"})
    return {"methods": ok("method"), "problems": ok("problem"), "runs": len({row["trial_id"] for row in rows if row["outcome"] == "reproduced"})}


def public(result):
    """The host's result as the coder and the records see it: the library's tests counted, with each failing one and why (at
    most FAILURES of them); protected tests by name and outcome only."""
    tests, protected = result.get("tests"), result.get("protected")
    earlier = result.get("earlier")
    return {**{key: value for key, value in result.items() if key not in {"tests", "protected", "earlier"}},
            "tests": None if tests is None else {**{k: tests.get(k, 0) for k in ("passed", "failed", "skipped")},
                                                 "results": [row for row in tests.get("results", []) if row["outcome"] == "failed"][:FAILURES]},
            "earlier": None if earlier is None else {**{k: earlier.get(k, 0) for k in ("passed", "failed", "skipped")},
                                                     "results": [row for row in earlier.get("results", []) if row["outcome"] == "failed"][:FAILURES]},
            "protected": None if protected is None else {**{k: protected.get(k, 0) for k in ("passed", "failed", "skipped")},
                                                         "results": [{"test": row["test"], "outcome": row["outcome"]} for row in protected.get("results", [])]}}


def instances_of(workspace, campaign_id):
    """The problem instances conformance runs on: the campaign's current tasks, as {problem_id, configuration, fidelity}."""
    return [{"problem_id": task.get("problem_id"), "configuration": task.get("configuration") or {}, "fidelity": task.get("fidelity") or {}}
            for task in workspace.current_tasks(campaign_id) if task.get("problem_id")]


def earlier_tests(store, directory, name, files):
    """{<version>/<path under tests/>: bytes} of every earlier version's tests (test_*.py) the new version (``files``) does not
    hold unchanged, each with the helpers and conftest.py of its version's tests/ beside it (roadmap L4)."""
    from . import library_repository as repositories
    prefix = f"libraries/{name}/"
    found = {}
    for version in repositories.versions(store, name):
        try:
            old = repositories.files_at(repositories.path(directory, name), version["commit"], name)
        except ValueError:
            continue
        tests = {path[len(prefix):]: content for path, content in old.items() if path.startswith(prefix + "tests/")}
        changed = [path for path, content in tests.items() if PurePosixPath(path).name.startswith("test_") and path.endswith(".py")
                   and files.get(prefix + path) != content]
        if not changed:
            continue
        for path, content in tests.items():
            if path in changed or not PurePosixPath(path).name.startswith("test_"):
                found[f"{version['version']}/{path}"] = content
    return found


def earlier_protected(store, record, name):
    """{file name: source} of the protected tests of every other workspace whose library was ``name`` (roadmap L4): they stay
    with the library."""
    found = {}
    for row in store.list(PROTECTED):
        if row["workspace_id"] == record["id"]:
            continue
        try:
            other = store.get(row["workspace_id"], "development_workspace")
        except KeyError:
            continue
        if (other.get("library") or {}).get("name") == name:
            found[f"test_{row['workspace_id'][-8:]}_{row['name'][5:]}"] = row["content"]
    return found


def recorded_runs(workspace, methods=(), problems=(), *, per=REPLAY_RUNS, evaluations=REPLAY_EVALUATIONS, scanned=400):
    """What a kept method or problem replays (roadmap L4): for each, up to ``per`` of the lab's most recent runs with recorded
    evaluations ({kind, id, trial_id, campaign_id, problem, parameters, seed, schedule_steps, observations}): a method's runs of
    it, a problem's runs on it. The first ``evaluations`` observations, up to the first whose result is not known."""
    from optimization_framework.execution.worker import read_journal
    store, methods, problems = workspace.store, set(methods), set(problems)
    wanted = {("method", method): [] for method in methods} | {("problem", problem): [] for problem in problems}
    headers = list(reversed(store.list_trial_headers()))[:scanned]
    for header in headers:
        keys = [("method", header.get("algorithm"))] if header.get("algorithm") in methods else []
        if not keys and not problems:
            continue
        try:
            trial = store.get(header["id"], "trial")
        except KeyError:
            continue
        definition = (trial.get("problem") or {}).get("definition_id")
        keys += [("problem", definition)] if definition in problems else []
        keys = [key for key in keys if len(wanted[key]) < per]
        if not keys or not trial.get("problem"):
            continue
        try:
            journal = read_journal(workspace.job_dir(trial["id"]) / "observations.jsonl")
        except (OSError, ValueError):
            continue
        observed = []
        for row in journal:
            if row.get("status") not in {"ok", "failed", "infeasible"} or len(observed) >= evaluations:
                break
            observed.append({key: row.get(key) for key in ("candidate", "status", "objectives", "constraints")})
        if not observed:
            continue
        for kind, identity in keys:
            rows = observed if kind == "method" else [row for row in observed if row["status"] == "ok"]
            if rows:
                wanted[(kind, identity)].append({"kind": kind, "id": identity, "trial_id": trial["id"], "campaign_id": trial.get("campaign_id"),
                    "problem": trial["problem"], "parameters": trial.get("algorithm_config") or {}, "seed": trial.get("seed", 0),
                    "schedule_steps": trial.get("schedule_steps") or 0, "observations": rows})
    return [item for rows in wanted.values() for item in rows]


def refused_reason(store, method_id):
    """Why a method cannot be bound: the latest install that validated it refused it on the host; None otherwise."""
    for install in sorted(store.list("library_install"), key=lambda row: row.get("requested_at") or "", reverse=True):
        validation = install.get("host_validation") or {}
        if install.get("status") != "installed" or not any(row.get("method_id") == method_id for row in validation.get("methods", [])):
            continue
        refused = next((row for row in install.get("refused_methods") or [] if row["method_id"] == method_id), None)
        return (f"{method_id} failed validation outside the box ({'; '.join(refused['failing'])[:300]}) when "
                f"{install['package']} {install['version']} was installed ({install['id']}); deliver a fixed version") if refused else None
    return None


# Inside the sandbox ----------------------------------------------------------------------------------------------------------
class _Collector:
    """Each test's outcome by node id, and the short reason of a failure."""
    def __init__(self, root):
        self.root, self.results = root, {}

    def _name(self, nodeid):
        return nodeid[len(self.root) + 1:] if nodeid.startswith(self.root + "/") else nodeid

    def pytest_runtest_logreport(self, report):
        name = self._name(report.nodeid)
        if report.failed:
            crash = getattr(report.longrepr, "reprcrash", None)
            self.results[name] = {"test": name, "outcome": "failed", "detail": (crash.message if crash else str(report.longrepr))[:1000]}
        elif (self.results.get(name) or {}).get("outcome") != "failed" and (report.when == "call" or report.skipped):
            self.results[name] = {"test": name, "outcome": "skipped" if report.skipped else "passed"}

    def pytest_collectreport(self, report):
        if report.failed:
            name = self._name(report.nodeid) or "collection"
            self.results[name] = {"test": name, "outcome": "failed", "detail": str(report.longrepr)[-1000:]}


def _pytest(directory):
    try:
        import pytest
    except ImportError:
        return {"passed": 0, "failed": 1, "skipped": 0, "results": [{"test": "pytest", "outcome": "failed",
                "detail": "pytest is not installed in the lab (uv sync --inexact --extra dev)"}]}
    collector = _Collector(directory)
    code = pytest.main([directory, "-q", "-p", "no:cacheprovider", "--rootdir", directory, "--import-mode=importlib",
                        "-o", "addopts=", "-W", "ignore::pytest.PytestUnraisableExceptionWarning"], plugins=[collector])
    results = list(collector.results.values())
    if code not in (0, 1, 5) and not any(row["outcome"] == "failed" for row in results):
        results.append({"test": "pytest", "outcome": "failed", "detail": f"pytest stopped with exit code {int(code)}"})
    count = lambda outcome: sum(row["outcome"] == outcome for row in results)
    return {"passed": count("passed"), "failed": count("failed"), "skipped": count("skipped"), "results": results}


def _fits(method, instance):
    """Whether a plain-function method's conformance can run on an instance: the problems and candidates it names, as
    capability_reason() checks them. Explicit constraints are left to check_function(), which refuses an infeasible candidate,
    as the library's generated contract test runs it on its own problem."""
    return (not method.get("problem_ids") or instance.definition_id in method["problem_ids"]) and \
        instance.candidate_schema.representation in method["representations"]


def _instances(request, registry):
    """The problem instances conformance runs on, in order: the campaign's tasks on a problem the library provides, the
    library's own problems at their defaults, then the campaign's other tasks."""
    provided = set(request["problem_entry_points"])
    asked = [*(row for row in request["instances"] if row["problem_id"] in provided),
             *({"problem_id": problem_id, "configuration": {}, "fidelity": None} for problem_id in sorted(provided)),
             *(row for row in request["instances"] if row["problem_id"] not in provided)]
    found = []
    for row in asked:
        try:
            found.append(registry.resolve(row["problem_id"], row["configuration"], row.get("fidelity") or None))
        except Exception:   # a task the lab cannot resolve here, or a problem of the library's with no defaults
            continue
    return found


def _conformance(request):
    """Each method's conformance (check_function for a plain-function method, check for any other) on the first instance it
    runs on (_instances()); not_run when there is none."""
    from importlib import import_module
    from optimization_framework.evaluation.registry import problems
    from optimization_framework.optimizers.conformance import check, check_function
    from optimization_framework.optimizers.functions import FunctionPlugin
    from optimization_framework.optimizers.plugins import OptimizerPlugins
    from optimization_framework.optimizers.registry import capability_reason
    registry, rows = problems, []
    for problem_id, value in sorted(request["problem_entry_points"].items()):
        module, factory = value.split(":", 1)
        registry = registry.extended(getattr(import_module(module), factory)())
    instances = _instances(request, registry)
    if not request["entry_points"]:
        return rows
    plugins = OptimizerPlugins(entries=request["entry_points"])
    try:
        listed = plugins.methods()
    except Exception as exc:
        return [{"method_id": name, "conformance": "failed", "check": "listing", "failed_check": f"{type(exc).__name__}: {exc}"[:1000]}
                for name in request["entry_points"]]
    for method in listed:
        method_id = method["id"]
        plugin, _ = plugins.get(method_id)
        function = isinstance(plugin, FunctionPlugin)
        row = {"method_id": method_id, "check": "check_function" if function else "check"}
        instance = next((item for item in instances if capability_reason(method_id, item, plugins) is None), None)
        if instance is None and function:
            instance = next((item for item in instances if _fits(method, item)), None)
        if instance is None:
            rows.append({**row, "conformance": "not_run", "reason": "no problem of the library or task of the campaign that it runs on"})
            continue
        row["problem_id"] = instance.definition_id
        try:
            if function:
                check_function(plugin, method_id, instance, registry=registry)
            else:
                check(method_id, instance, optimizer_plugins=plugins)
            rows.append({**row, "conformance": "passed"})
        except Exception as exc:   # an AssertionError names the check; anything else is the method's own error
            rows.append({**row, "conformance": "failed", "failed_check": (str(exc) if isinstance(exc, AssertionError) else f"{type(exc).__name__}: {exc}")[:1000]})
    return rows


def _same(a, b):
    """Whether two recorded results agree: equal, or numbers within a relative 1e-9."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def _replays(request):
    """Replay each recorded run the request names on the new version (roadmap L4): a method proposes the recorded candidates,
    fed the recorded results; a problem evaluates them to the recorded results. One row each: {kind, id, trial_id, outcome
    (reproduced, diverged, not_listed, error), at, detail}."""
    from importlib import import_module
    from optimization_framework.contracts.problems import Observation, ProblemInstance
    from optimization_framework.evaluation.registry import problems
    from optimization_framework.optimizers.finish import MethodFinished
    from optimization_framework.optimizers.plugins import OptimizerPlugins
    registry = problems
    for problem_id, value in sorted(request["problem_entry_points"].items()):
        module, factory = value.split(":", 1)
        registry = registry.extended(getattr(import_module(module), factory)())
    plugins = OptimizerPlugins(entries=request["entry_points"]) if request["entry_points"] else None
    listed = {method["id"] for method in plugins.methods()} if plugins else set()
    rows = []
    for item in request["replays"]:
        row = {"kind": item["kind"], "id": item["id"], "trial_id": item["trial_id"], "campaign_id": item.get("campaign_id"),
               "outcome": "reproduced", "at": None, "detail": None}
        if item["kind"] == "method" and item["id"] not in listed:
            rows.append({**row, "outcome": "not_listed"})
            continue
        index, method = 0, None
        try:
            recorded = ProblemInstance(**item["problem"])
            if item["kind"] == "problem":
                instance = registry.resolve(item["id"], recorded.configuration, recorded.fidelity or None)
                evaluator = registry.evaluator(instance)
                name = instance.primary_objective.name
                for index, observation in enumerate(item["observations"], 1):
                    value = evaluator.evaluate(instance.candidate_schema.canonicalize(observation["candidate"])).objectives.get(name)
                    if not _same(value, (observation.get("objectives") or {}).get(name)):
                        rows.append({**row, "outcome": "diverged", "at": index,
                                     "detail": f"{name} is {value}, recorded {(observation.get('objectives') or {}).get(name)}"})
                        break
                else:
                    rows.append({**row, "at": index})
                continue
            # Made as conformance makes it, by the plug-in itself: the run was admitted when it ran.
            method = plugins.get(item["id"])[0].create(item["id"], recorded, dict(item["parameters"]), item["seed"])
            for index, observation in enumerate(item["observations"], 1):
                try:
                    proposal = method.propose(1)[0]
                except MethodFinished:
                    rows.append({**row, "outcome": "diverged", "at": index, "detail": "it finished where the recorded run went on"})
                    break
                candidate = recorded.candidate_schema.canonicalize(proposal.candidate)
                if candidate != recorded.candidate_schema.canonicalize(observation["candidate"]):
                    rows.append({**row, "outcome": "diverged", "at": index, "detail": "it proposed another candidate than the recorded run"})
                    break
                method.observe([Observation(id=f"replay_{index}", experiment_id=item["trial_id"], attempt_id="replay", request_id=f"replay_{index}",
                    proposal_id=proposal.id, candidate=candidate, status=observation["status"], objectives=observation.get("objectives") or {},
                    constraints=observation.get("constraints") or {}, fidelity=recorded.fidelity, evaluator_identity=recorded.evaluation_identity)])
            else:
                rows.append({**row, "at": index})
        except Exception as exc:   # the method or the problem failed on the recorded run: it does not reproduce it
            rows.append({**row, "outcome": "error", "at": index or 1, "detail": f"{type(exc).__name__}: {exc}"[:500]})
        finally:
            if method is not None:
                try:
                    method.close()
                except Exception:
                    pass
    return rows


def main(argv):
    import resource
    request = json.loads(argv[0])
    resource.setrlimit(resource.RLIMIT_AS, (request["memory_bytes"], request["memory_bytes"]))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sys.path.insert(0, LIBRARY)
    for name in request.get("dependencies") or []:
        sys.path.insert(1, f"{DEPENDENCIES}/{name}")
    result = {"tests": _pytest(LIBRARY), "protected": _pytest(TESTS) if request["protected"] else None,
              "earlier": _pytest(EARLIER) if request.get("earlier") else None}
    try:
        result["methods"] = _conformance(request)
    except Exception as exc:
        result["methods"], result["error"] = [], f"Conformance could not run: {type(exc).__name__}: {exc}"[:1000]
    if request.get("replays"):
        try:
            result["replays"] = _replays(request)
        except Exception as exc:
            result["replays"], result["error"] = [], f"Replaying recorded runs could not run: {type(exc).__name__}: {exc}"[:1000]
    Path(OUT, "result.json").write_text(json.dumps(result, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
