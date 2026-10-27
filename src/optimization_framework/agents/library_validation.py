"""Validation outside the box (roadmap H6): before a delivered library's install counts, the host runs on the exact commit's
files, in a sandbox with no network, what the coding agent only reported: the library's own tests (the generated contract
tests among them, F3), conformance for each method (`check_function` for a plain-function method, `check` for any other),
and the protected acceptance tests kept on the host, which the box never saw.

The host writes the commit's files into a fresh directory, starts this module with `python -m` under bubblewrap (no network,
a read-only view of the lab's Python and Balsamic, nothing of the lab's data), and reads one result file back. A method whose
own tests or conformance fail is refused; a failure no method owns (a broken objective, a collection error) refuses the
library. Protected tests come back as names and outcomes only: their source and their failure text stay on the host.
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
PROTECTED = "development_protected_test"
# Inside the sandbox.
LIBRARY, TESTS, OUT = "/library", "/protected", "/out"


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
def _sites():
    """What the sandboxed Python needs to read: its installation, the lab's environment, and the directories its .pth files
    name (Balsamic's own source, the lab's installed libraries). Nothing else of the host."""
    found = {Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).resolve().parents[1]}
    for site in {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}:
        found.add(Path(site))
        for pth in Path(site).glob("*.pth"):
            for line in pth.read_text(errors="replace").splitlines():
                if line.strip() and not line.startswith(("#", "import")) and Path(line.strip()).is_dir():
                    found.add(Path(line.strip()))
    found.add(Path(__file__).resolve().parents[2])   # the directory that holds optimization_framework
    return sorted({path.resolve() for path in found if path.exists()})


def command(library, protected, out, request):
    """The bubblewrap command: no network, no host environment, read-only system and Python, the library and the protected
    tests read-only, and only the result directory writable."""
    bwrap = shutil.which("bwrap")
    if not bwrap or sys.platform != "linux":
        raise ValidationUnavailable("Validating a library outside the box needs Linux and bubblewrap (bwrap): install bubblewrap")
    args = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in ("/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin", "/etc/ld.so.cache", "/etc/localtime"):
        args += ["--ro-bind-try", path, path]
    for path in _sites():
        args += ["--ro-bind", str(path), str(path)]
    args += ["--ro-bind", str(library), LIBRARY, "--ro-bind", str(protected), TESTS, "--bind", str(out), OUT, "--chdir", LIBRARY]
    environment = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                   "PYTHONHASHSEED": "0", "GRATING_LLM_DISABLED": "true", "MPLBACKEND": "Agg", "OPENBLAS_NUM_THREADS": "1",
                   "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    for key, value in environment.items():
        args += ["--setenv", key, value]
    return [*args, "--", sys.executable, "-B", "-s", "-m", __name__, json.dumps(request)]


def run(files, name, *, instances=(), protected=None, timeout=TIMEOUT_SECONDS):
    """Validate libraries/<name>/ as {path: bytes} (the exact commit's): the result, with `seconds` it took. ValidationUnavailable
    when the sandbox cannot run, ValueError when it ran and gave no result."""
    from .library_install import GROUP, PROBLEMS
    import tomllib
    prefix = f"libraries/{name}/"
    project = tomllib.loads(files[prefix + "pyproject.toml"].decode()).get("project") or {}
    groups = project.get("entry-points") or {}
    request = {"entry_points": groups.get(GROUP) or {}, "problem_entry_points": groups.get(PROBLEMS) or {},
               "instances": list(instances), "protected": bool(protected), "memory_bytes": MEMORY_BYTES}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="balsamic-validation-") as temporary:
        library, tests, out = (Path(temporary) / part for part in ("library", "protected", "out"))
        for directory in (library, tests, out):
            directory.mkdir()
        for path, content in files.items():
            relative = PurePosixPath(path).relative_to(prefix)
            (library / relative).parent.mkdir(parents=True, exist_ok=True)
            (library / relative).write_bytes(content)
        for test, source in (protected or {}).items():
            (tests / test).write_text(source)
        process = subprocess.Popen(command(library, tests, out, request), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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


def verdict(result, report):
    """What the host's result means for the install: {refused_methods, library_failures, methods}. A method is refused when
    its conformance or one of its own tests (a test parametrized with its id, the library's or a protected one) fails; a
    failed test no method owns is the library's."""
    methods = {row["method_id"]: row for row in result.get("methods", [])}
    reported = {row.get("method_id"): row.get("conformance") for row in (report or {}).get("methods", [])}
    owners, library = {}, []
    for kind in ("tests", "protected"):
        for row in (result.get(kind) or {}).get("results", []):
            if row["outcome"] != "failed":
                continue
            owner = next((method for method in methods if f"[{method}]" in row["test"] or f"[{method}-" in row["test"]
                          or f"-{method}]" in row["test"]), None)
            (owners.setdefault(owner, []) if owner else library).append({"test": row["test"], "protected": kind == "protected"})
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


def public(result):
    """The host's result as the coder and the records see it: protected tests by name and outcome only."""
    protected = result.get("protected")
    return {**{key: value for key, value in result.items() if key != "protected"},
            "protected": None if protected is None else {**{k: protected[k] for k in ("passed", "failed", "skipped")},
                                                         "results": [{"test": row["test"], "outcome": row["outcome"]} for row in protected.get("results", [])]}}


def instances_of(workspace, campaign_id):
    """The problem instances conformance runs on: the campaign's current tasks, as {problem_id, configuration, fidelity}."""
    return [{"problem_id": task.get("problem_id"), "configuration": task.get("configuration") or {}, "fidelity": task.get("fidelity") or {}}
            for task in workspace.current_tasks(campaign_id) if task.get("problem_id")]


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


def _conformance(request):
    """Each method's conformance on the first instance it can run: the library's own problems, then the campaign's tasks."""
    from importlib import import_module
    from optimization_framework.evaluation.registry import problems
    from optimization_framework.optimizers.conformance import check, check_function
    from optimization_framework.optimizers.functions import FunctionPlugin
    from optimization_framework.optimizers.plugins import OptimizerPlugins
    from optimization_framework.optimizers.registry import capability_reason
    registry, rows, instances = problems, [], []
    for problem_id, value in sorted(request["problem_entry_points"].items()):
        module, factory = value.split(":", 1)
        adapter = getattr(import_module(module), factory)()
        registry = registry.extended(adapter)
    for row in request["instances"]:
        try:
            instances.append(registry.resolve(row["problem_id"], row["configuration"], row["fidelity"] or None))
        except Exception:   # a task this library does not provide or the lab cannot resolve here
            continue
    for problem_id in sorted(request["problem_entry_points"]):
        try:
            instances.append(registry.resolve(problem_id, {}, None))
        except Exception:
            continue
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


def main(argv):
    import resource
    request = json.loads(argv[0])
    resource.setrlimit(resource.RLIMIT_AS, (request["memory_bytes"], request["memory_bytes"]))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sys.path.insert(0, LIBRARY)
    result = {"tests": _pytest(LIBRARY), "protected": _pytest(TESTS) if request["protected"] else None}
    try:
        result["methods"] = _conformance(request)
    except Exception as exc:
        result["methods"], result["error"] = [], f"Conformance could not run: {type(exc).__name__}: {exc}"[:1000]
    Path(OUT, "result.json").write_text(json.dumps(result, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
