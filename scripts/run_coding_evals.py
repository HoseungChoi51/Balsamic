#!/usr/bin/env python3
"""Coding evals: how well, how fast and at what cost the coding path builds a method from its proposal (roadmap J4).

Each scenario (evals/coding/scenarios/*.json) is one method of a library in this repository. The runner makes a source
repository without the method (its module, tests and specification withheld, its plug-in entry dropped, no history), starts a
lab on it in a temporary directory, records the proposal on a scratch campaign and asks the implementation lead, as the
researcher would, to build it in a coding workspace. It approves the go-ahead the agent asks for, waits for the workspace's
submission, and checks the delivered library outside the box: its tests/test_contract.py and conformance.check() on the
method.

  uv run python scripts/run_coding_evals.py --fake                    # plumbing only: scripted agents, a prepared library
  uv run python scripts/run_coding_evals.py --scenarios C1            # Pi in Docker, on the dev profile's model
  uv run python scripts/run_coding_evals.py --scenarios C1 --record-baseline
  uv run python scripts/run_coding_evals.py --scenarios C1 --harness-mode headless --record-baseline   # Pi headless (H2)

A real run needs Docker and the workspace image, calls a model and costs money. See evals/coding/README.md.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "evals" / "coding"
ENTRY_POINTS = "optimization_framework.optimizers"
CHECK_SECONDS = 600
# A fake run's agents answer at once; its waits poll quickly.
FAKE_POLL, REAL_POLL = 0.1, 5.0


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lead_evals = load_module(REPO / "scripts" / "run_lead_evals.py", "run_lead_evals_for_coding")


def load_scenarios(directory, selected=None):
    scenarios = [json.loads(path.read_text()) for path in sorted(Path(directory).glob("*.json"))]
    if selected:
        wanted = [item.strip() for item in selected.split(",") if item.strip()]
        scenarios = [s for s in scenarios if any(s["id"] == w or s["id"].split("-", 1)[0] == w for w in wanted)]
    return scenarios


# The source the workspace clones ---------------------------------------------------------------------------------------
def drop_method(text, method_id):
    """plugin.py without one method: its entry in METHODS and its module in the `from . import` line."""
    tree = ast.parse(text)
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    offset = lambda line, col: starts[line - 1] + len(text.splitlines(keepends=True)[line - 1].encode()[:col].decode())
    cuts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and not node.module:
            names = [alias.name for alias in node.names if alias.name != method_id]
            if len(names) < len(node.names):
                cuts.append((offset(node.lineno, node.col_offset), offset(node.end_lineno, node.end_col_offset), "from . import " + ", ".join(names)))
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == method_id:
                    end = offset(value.end_lineno, value.end_col_offset)
                    end += len(re.match(r"\s*,?\s*", text[end:]).group(0))
                    cuts.append((offset(key.lineno, key.col_offset), end, ""))
    if len(cuts) != 2:
        raise ValueError(f"plugin.py does not import and list {method_id} once each")
    for start, end, replacement in sorted(cuts, reverse=True):
        text = text[:start] + replacement + text[end:]
    ast.parse(text)
    return text


def build_source(source, scenario, target):
    """A repository of `source`'s HEAD without the scenario's method, as one commit: its history would hold the method."""
    target = Path(target)
    target.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", "HEAD"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive, check=True)
    for path in scenario["withhold"]:
        (target / path).unlink()
    plugin = target / scenario["library"] / "src" / scenario["library"].rsplit("/", 1)[-1].replace("-", "_") / "plugin.py"
    if plugin.exists():
        plugin.write_text(drop_method(plugin.read_text(), scenario["method_id"]))
    git = ["git", "-C", str(target), "-c", "user.name=Balsamic coding eval", "-c", "user.email=evals@balsamic.invalid"]
    subprocess.run(git[:3] + ["init", "-q", "-b", "main"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", f"Source for coding eval {scenario['id']}: {scenario['method_id']} withheld"], check=True)
    return target


# Checks outside the box ------------------------------------------------------------------------------------------------
def write_delivery(package, target):
    """The submission's files under `target`, at their repository paths; the library roots they form."""
    roots = set()
    for item in package["files"]:
        path = Path(item["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"A delivered path leaves the repository: {item['path']}")
        (target / path).parent.mkdir(parents=True, exist_ok=True)
        (target / path).write_text(item["content"])
        roots.add(target / Path(*path.parts[:2]) if path.parts[0] == "libraries" and len(path.parts) > 2 else target)
    return sorted(roots)


def plugins_of(root):
    """The library's optimizer plug-ins, from its pyproject.toml's entry points."""
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return (project.get("project", {}).get("entry-points", {}) or {}).get(ENTRY_POINTS, {})


def environment(root):
    src = root / "src"
    return {**os.environ, "GRATING_LLM_DISABLED": "true", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join([str(src if src.is_dir() else root), str(REPO / "src")])}


def pytest_counts(output):
    counts = {name: int(number) for number, name in re.findall(r"(\d+) (passed|failed|skipped|errors?)\b", output)}
    return {"passed": counts.get("passed", 0), "failed": counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0),
            "skipped": counts.get("skipped", 0)}


def run_pytest(root, target):
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(root), str(target)],
                              cwd=root, env=environment(root), capture_output=True, text=True, timeout=CHECK_SECONDS)
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": 0, "skipped": 0, "ok": False, "tail": f"timed out after {CHECK_SECONDS} s"}
    counts = pytest_counts(done.stdout.strip().splitlines()[-1] if done.stdout.strip() else "")
    return {**counts, "ok": done.returncode == 0 and counts["passed"] > 0, "tail": (done.stdout + done.stderr)[-3000:]}


CONFORMANCE = """
import json, sys
from optimization_framework.evaluation.registry import problems
from optimization_framework.optimizers import conformance
from optimization_framework.optimizers.plugins import OptimizerPlugins
method, example, plugins = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
instance = next(e for e in problems.examples() if e["id"] == example)["instances"][0]
resolved = problems.get(instance["problem_id"]).resolve(instance["configuration"], instance["fidelity"])
print(json.dumps(conformance.check(method, resolved, optimizer_plugins=OptimizerPlugins(plugins))["checks"]))
"""


def run_conformance(root, method_id, example):
    try:
        done = subprocess.run([sys.executable, "-c", CONFORMANCE, method_id, example, json.dumps(plugins_of(root))], cwd=root,
                              env=environment(root), capture_output=True, text=True, timeout=CHECK_SECONDS)
    except subprocess.TimeoutExpired:
        return {"passed": False, "checks": [], "error": f"timed out after {CHECK_SECONDS} s"}
    if done.returncode:
        return {"passed": False, "checks": [], "error": (done.stderr or done.stdout)[-2000:]}
    checks = json.loads(done.stdout.strip().splitlines()[-1])
    return {"passed": bool(checks), "checks": checks, "error": None}


def check_delivery(submission, scenario, target):
    """The delivered library's contract test and the method's conformance, run here, outside the coding box."""
    roots = write_delivery(submission["package"], Path(target))
    root = next((r for r in roots if any(scenario["method_id"] in str(t) for t in [*plugins_of(r).values(), *plugins_of(r).keys()])
                 or (r / "tests" / "test_contract.py").exists()), roots[0] if roots else Path(target))
    contract_file = root / "tests" / "test_contract.py"
    if contract_file.exists():
        contract = {**run_pytest(root, contract_file), "names_method": scenario["method_id"] in contract_file.read_text()}
    else:
        contract = {"passed": 0, "failed": 0, "skipped": 0, "ok": False, "names_method": False, "tail": "tests/test_contract.py was not delivered"}
    tests = run_pytest(root, root / "tests") if (root / "tests").is_dir() else {"passed": 0, "failed": 0, "skipped": 0, "ok": False, "tail": "no tests delivered"}
    plugins = plugins_of(root)
    conformance = run_conformance(root, scenario["method_id"], scenario["example"]) if plugins else \
        {"passed": False, "checks": [], "error": f"no {ENTRY_POINTS} entry point in the delivered pyproject.toml"}
    return {"library": str(root.relative_to(target)) if root != Path(target) else ".", "plugins": plugins,
            "dependencies": (submission.get("manifest") or {}).get("dependencies", {}), "contract": contract, "tests": tests,
            "conformance": conformance, "passed": contract["ok"] and contract["names_method"] and conformance["passed"]}


# One scenario ----------------------------------------------------------------------------------------------------------
def seconds_between(start, end):
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 1) if start and end else None


class Run:
    def __init__(self, stack, scenario, campaign_id, poll):
        self.stack, self.scenario, self.campaign_id, self.poll = stack, scenario, campaign_id, poll
        self.store = stack.workspace.store
        self.vars = {"campaign_id": campaign_id, "method_id": scenario["method_id"], "title": scenario["proposal"]["title"]}
        self.approved, self.answered, self.timed_out = [], [], False

    def agents(self):
        return {a["id"]: a for a in self.store.list("agent_session", self.campaign_id)}

    def submissions(self):
        return sorted(self.store.list("development_submission", self.campaign_id), key=lambda row: row["created_at"])

    def researcher_turn(self):
        """What the researcher does while waiting: approve a go-ahead, answer a question with the scenario's standing answer."""
        for decision in self.store.list("decision", self.campaign_id):
            if decision.get("status") == "pending" and decision["id"] not in self.approved:
                self.stack.command(self.campaign_id, "decision.resolve", {"decision_id": decision["id"], "choice": decision["options"][0]["id"],
                    "comment": "Approved in the coding eval", "expected_resolution_revision": decision.get("resolution_revision", 0)})
                self.approved.append(decision["id"])
        for question in self.store.list("agent_question", self.campaign_id):
            if question["status"] == "pending" and question["id"] not in self.answered:
                self.stack.command(self.campaign_id, "agent.message", {"message": self.scenario["answer"], "question_id": question["id"]})
                self.answered.append(question["id"])
        for question in self.store.list("development_question", self.campaign_id):
            if question["status"] == "pending" and question["id"] not in self.answered:
                self.stack.workspace.pi.development.message(self.campaign_id, question["workspace_id"], {"message": self.scenario["answer"],
                    "mode": "steer", "request_key": "eval-answer-" + question["id"], "question_id": question["id"]})
                self.answered.append(question["id"])

    def wait_for_submission(self, timeout_s):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.researcher_turn()
            if self.submissions():
                return self.submissions()[0]
            time.sleep(self.poll)
        self.timed_out = True
        return None

    def metrics(self, asked_at):
        agents = self.agents()
        runs = self.store.list("agent_run", self.campaign_id)
        workspaces = self.store.list("development_workspace", self.campaign_id)
        commands = self.store.list("development_command", self.campaign_id)
        submissions = self.submissions()
        workspace = workspaces[0] if workspaces else {}
        usage = workspace.get("usage") or {}
        return {
            "seconds_to_workspace": seconds_between(asked_at, workspace.get("created_at")),
            "seconds_to_submission": seconds_between(asked_at, submissions[0]["created_at"] if submissions else None),
            "lead_turns": sum((agents.get(r["agent_id"]) or {}).get("role") in {"lead", "implementation_lead"} for r in runs),
            # Relayed: what the agents wrote to the coding agent after its assignment, and the workspace's notices to the agents.
            "messages_to_coding_agent": sum(c["operation"] == "message" and c["actor"] not in {"researcher", "system"}
                                            and not c["request_key"].startswith("initial-") for c in commands),
            "notices_from_workspace": sum(r["id"].startswith("pi_development_") for r in runs),
            "researcher_approvals": len(self.approved), "researcher_answers": len(self.answered),
            "submissions": len(submissions), "workspace_status": workspace.get("status"), "harness": workspace.get("harness"),
            "coding_agent": {key: usage.get(key, 0) for key in ("subscription_calls", "input", "output", "cacheRead", "cacheWrite",
                                                                 "api_cost_usd", "container_cpu_seconds")},
            **lead_evals.Context.usage(self)}

    def stop(self):
        development = self.stack.workspace.pi.development
        for record in self.store.list("development_workspace", self.campaign_id):
            if record.get("desired_status") != "stopped":
                try:
                    development.control(self.campaign_id, record["id"], {"action": "stop", "request_key": "eval-stop",
                                                                        "expected_revision": record["control_revision"]})
                    development.sync(self.campaign_id)
                except Exception:
                    pass
        lead_evals.stop(self.stack, self)


def run_scenario(stack, scenario, *, model, poll, timeout_s, out):
    campaign_id = f"eval_{scenario['id'].split('-', 1)[0].lower()}_{uuid.uuid4().hex[:6]}"
    example = scenario["example"]
    from optimization_framework.evaluation.registry import problems
    instance = next(e for e in problems.examples() if e["id"] == example)["instances"][0]
    stack.command(campaign_id, "campaign.create", {"name": f"Coding eval {scenario['id']}", "objective": f"Implement {scenario['method_id']}",
        "tasks": [{"name": example, "problem_id": instance["problem_id"], "configuration": instance["configuration"], "fidelity": instance["fidelity"]}],
        "compute_budget_seconds": 3600, "validation_reserve_seconds": 0, "implementation_compute_budget_seconds": 3600,
        "llm_budget_usd": scenario.get("llm_budget_usd", 5)})
    run = Run(stack, scenario, campaign_id, poll)
    result = {"id": scenario["id"], "method_id": scenario["method_id"], "campaign_id": campaign_id, "error": None, "delivery": None}
    started, asked_at = time.monotonic(), None
    try:
        receipt = stack.command(campaign_id, "hypothesis.create", scenario["proposal"])
        run.vars["hypothesis_id"] = receipt["outcome"]["hypothesis_id"]
        stack.command(campaign_id, "agent.activate", {**({"model": model} if model else {})})
        from optimization_framework.storage.sqlite import now
        asked_at = now()
        stack.command(campaign_id, "agent.message", {"message": scenario["say"].format(**run.vars), "page_agent": "implementation_lead"})
        submission = run.wait_for_submission(timeout_s)
        if submission:
            result["submission"] = {"id": submission["id"], "commit": submission["commit"], "report": submission.get("report"),
                                    "files": [f["path"] for f in submission["package"]["files"]]}
            result["delivery"] = check_delivery(submission, scenario, out / "delivered" / scenario["id"])
    except Exception as exc:   # a broken run is a failed scenario, not a crashed suite
        result["error"] = f"{type(exc).__name__}: {exc}"[:2000]
    finally:
        run.stop()
    result["metrics"] = {**run.metrics(asked_at), "seconds": round(time.monotonic() - started, 1)}
    result["timed_out"] = run.timed_out
    result["passed"] = bool(result["delivery"] and result["delivery"]["passed"]) and not result["error"]
    result["status"] = "pass" if result["passed"] else "timeout" if run.timed_out else "fail"
    return result


# The suite -------------------------------------------------------------------------------------------------------------
def summary_markdown(results, baseline=None):
    lines = [f"# Coding evals · {results['mode']} · {results['commit']}", "",
             f"- Started {results['started_at']}, {results['seconds']} s; model {results['model'] or 'profile default'}; "
             f"pi {results.get('harness_mode') or 'tui'}", "",
             "| Scenario | Status | To submission | Lead turns | To coding agent | Notices | Model $ | Coding agent calls | Contract | Conformance |"
             + (" Baseline |" if baseline else ""),
             "|---|---|---|---|---|---|---|---|---|---|" + ("---|" if baseline else "")]
    for row in results["scenarios"]:
        m, d = row["metrics"], row["delivery"] or {}
        contract = d.get("contract") or {}
        line = (f"| {row['id']} | {row['status']} | {m['seconds_to_submission'] if m['seconds_to_submission'] is not None else '—'} s | "
                f"{m['lead_turns']} | {m['messages_to_coding_agent']} | {m['notices_from_workspace']} | ${m['cost_usd']:.4f} | "
                f"{m['coding_agent']['subscription_calls']} | {contract.get('passed', 0)} passed, {contract.get('failed', 0)} failed | "
                f"{'passed' if (d.get('conformance') or {}).get('passed') else 'failed'} |")
        if baseline:
            old = baseline.get("scenarios", {}).get(row["id"])
            line += " — |" if not old else f" {old['status']}, {old['metrics']['seconds_to_submission']} s{' **regressed**' if old['passed'] and not row['passed'] else ''} |"
        lines.append(line)
    problems = [(row["id"], row["error"]) for row in results["scenarios"] if row["error"]]
    problems += [(row["id"], ((row["delivery"] or {}).get("conformance") or {}).get("error")) for row in results["scenarios"]
                 if ((row["delivery"] or {}).get("conformance") or {}).get("error")]
    if problems:
        lines += ["", "## Errors", ""] + [f"- {scenario}: {str(error)[:500]}" for scenario, error in problems]
    lines += ["", "The delivered libraries are under `delivered/<scenario>/`; read one diff against the original library for quality."]
    return "\n".join(lines) + "\n"


def baseline_record(results):
    keep = ("method_id", "status", "passed", "timed_out", "metrics")
    return {"commit": results["commit"], "mode": results["mode"], "harness_mode": results.get("harness_mode") or "tui", "model": results["model"],
            "recorded_at": results["started_at"],
            "scenarios": {row["id"]: {**{key: row[key] for key in keep}, "contract": ((row["delivery"] or {}).get("contract") or {}).get("ok", False),
                                      "conformance": ((row["delivery"] or {}).get("conformance") or {}).get("passed", False),
                                      "verdict": ((row.get("submission") or {}).get("report") or {}).get("verdict")}
                          for row in results["scenarios"]}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fake", action="store_true", help="scripted agents and a workspace that submits the prepared library: no model, no Docker")
    parser.add_argument("--model", help="provider/model[:effort] for agent.activate; default: the dev profile's")
    parser.add_argument("--scenarios", help="comma-separated ids or prefixes (C1, C2-conditional-mirror-search)")
    parser.add_argument("--timeout", type=float, help="seconds to wait for a submission (default: the scenario's own)")
    parser.add_argument("--out", type=Path, help="output directory (default runs/coding-evals/<timestamp>)")
    parser.add_argument("--source", type=Path, default=REPO, help="checkout whose lab, harness and HEAD are run (default: this one)")
    parser.add_argument("--profile", type=Path, help="Pi dev profile (default <source>/agent-harness/profiles/dev)")
    parser.add_argument("--secrets", default=os.environ.get("BALSAMIC_SECRETS", str(Path.home() / ".config/balsamic/secrets.env")))
    parser.add_argument("--record-baseline", nargs="?", const="", help="also write the summary to evals/coding/baselines/<commit>.json (or the path given)")
    parser.add_argument("--compare", type=Path, help="a baseline file to compare with in summary.md")
    parser.add_argument("--harness-mode", choices=("tui", "headless"), default="tui",
                        help="how the workspace runs Pi: its terminal UI (the default) or headless, pi --mode json (roadmap H2)")
    args = parser.parse_args(argv)
    scenarios = load_scenarios(EVALS / "scenarios", args.scenarios)
    if not scenarios:
        raise SystemExit("No scenario matches")
    out = args.out or REPO / "runs" / "coding-evals" / (time.strftime("%Y%m%d-%H%M%S") + ("-fake" if args.fake else ""))
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    results = {"mode": "fake" if args.fake else "real", "harness_mode": args.harness_mode, "commit": lead_evals.git_commit(source),
               "source": str(source), "model": args.model,
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "scenarios": []}
    fakes = load_module(EVALS / "fakes.py", "coding_eval_fakes") if args.fake else None
    started = time.monotonic()
    saved = {key: os.environ.get(key) for key in ("GRATING_DEVELOPMENT_ENABLED", "GRATING_AUTO_INSTALL", "GRATING_DEVELOPMENT_HARNESS_MODE")}
    # Workspaces on, in the harness mode asked for; nothing delivered is installed in the eval's lab: the checks run on the delivery itself.
    os.environ.update(GRATING_DEVELOPMENT_ENABLED="true", GRATING_AUTO_INSTALL="false", GRATING_DEVELOPMENT_HARNESS_MODE=args.harness_mode)
    try:
        with tempfile.TemporaryDirectory(prefix="coding-evals-") as root, \
                lead_evals.Stack(root, fake=args.fake, source=source, profile=args.profile or source / "agent-harness" / "profiles" / "dev",
                                 secrets_file=args.secrets, log=print) as stack:
            from optimization_framework.agents.development import DevelopmentWorkspaces
            from optimization_framework.agents.development_runtime import DockerWorkspace
            if args.fake:
                stack.fake_play = fakes.play
            for scenario in scenarios:
                directory = Path(root) / "development" / scenario["id"]
                if args.fake:
                    driver = fakes.PreparedWorkspace(directory, source / scenario["library"], source)
                else:
                    driver = DockerWorkspace(directory, source=build_source(source, scenario, Path(root) / "sources" / scenario["id"]))
                    capability = driver.capability()
                    if not capability["available"]:
                        raise SystemExit(f"The coding workspace cannot start: {capability['reason']}")
                stack.workspace.pi.development = DevelopmentWorkspaces(stack.workspace.pi, driver=driver)
                result = run_scenario(stack, scenario, model=lead_evals.parse_model(args.model), poll=FAKE_POLL if args.fake else REAL_POLL,
                                      timeout_s=args.timeout or scenario.get("timeout_s", 14400), out=out)
                print(f"{scenario['id']}: {result['status']}" + (f" ({result['error']})" if result["error"] else ""), flush=True)
                results["scenarios"].append(result)
            if not args.fake:
                log = Path(root) / "harness.log"
                if log.exists():
                    (out / "harness.log").write_text(log.read_text()[-200000:])
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
    results["seconds"] = round(time.monotonic() - started, 1)
    baseline = json.loads(args.compare.read_text()) if args.compare else None
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (out / "summary.md").write_text(summary_markdown(results, baseline))
    if args.record_baseline is not None:
        # A headless run's baseline sits beside the terminal UI's of the same commit.
        suffix = "" if args.harness_mode == "tui" else "-" + args.harness_mode
        path = Path(args.record_baseline) if args.record_baseline else EVALS / "baselines" / f"{results['commit']}{suffix}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(baseline_record(results), indent=2) + "\n")
        print(f"baseline: {path}")
    print(f"results: {out / 'summary.md'}")
    return 0 if all(row["passed"] for row in results["scenarios"]) else 1


if __name__ == "__main__":
    sys.exit(main())
