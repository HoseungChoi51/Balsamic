"""The work ticket of a coding workspace (roadmap H4): what the coding agent is asked to build, recorded once when the
workspace opens (a `development_ticket`) and written into its worktree beside the generated library (F4) as four files:
`TASK.md` (the ticket, readable), `AGENTS.md` and `CLAUDE.md` (the same house rules for any harness: what to build, how to
run the tests, how to submit, what not to touch) and `.balsamic/spec.json` (the ticket as JSON).

A ticket holds the proposals the workspace serves (title, mechanism, the METHODS key), the charter revision, the acceptance
tests as runnable pytest files (the generated library's own tests, F1 and F3, and any the implementation lead adds), the
names of the protected acceptance tests, the compute and model budget and the deadline of the go-ahead and mandate it opens
under, and the house rules. A protected test's source is kept on the host, as validation outside the box keeps it
(`library_validation.protect()`, H6, which runs it on every delivery), and never written into the worktree or the ticket.
An agent's ticket is checked as a commission's
specification is (`ImplementationBridge.check_self_contained()`): it needs acceptance tests, and its text names only the
records the coding agent can read.

The review: `diff_summary()` compares a delivered library with the base the ticket wrote (the generated files and the
implementation lead's tests): the files and lines changed, and the generated files and acceptance tests it touched."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import PurePosixPath

from pydantic import Field, field_validator, model_validator

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now

KIND = "development_ticket"
# What the ticket writes at the worktree's root; the coding agent's tests may not take these places.
FILES = ("TASK.md", "AGENTS.md", "CLAUDE.md", ".balsamic/spec.json")
RESERVED = {".balsamic", ".campaign", ".git", ".vscode", *FILES}


class AcceptanceTest(Contract):
    path: str = Field(min_length=4, max_length=300, description="A pytest file, repository-relative (libraries/<name>/tests/test_x.py)")
    content: str | None = Field(default=None, max_length=100_000, description="Its source when it is new: written into the worktree")

    @field_validator("path")
    @classmethod
    def inside(cls, value):
        pure = PurePosixPath(value)
        if pure.is_absolute() or str(pure) != value or "\\" in value or ".." in pure.parts or not value.endswith(".py"):
            raise ValueError("an acceptance test is a .py file named by its path in the repository, such as libraries/<name>/tests/test_x.py")
        if pure.parts[0] in RESERVED:
            raise ValueError(f"{value}: {pure.parts[0]} is Balsamic's")
        return value


class ProtectedTest(Contract):
    name: str = Field(pattern=r"^test_[A-Za-z0-9_]{1,80}\.py$", description="A pytest file name, test_<name>.py")
    content: str = Field(min_length=1, max_length=100_000)


class TicketInput(Contract):
    """The implementation lead's part of a ticket; Balsamic fills in the rest."""
    acceptance_tests: list[AcceptanceTest] = Field(default_factory=list, max_length=20)
    protected_tests: list[ProtectedTest] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def once(self):
        for label, names in (("acceptance_tests", [test.path for test in self.acceptance_tests]),
                             ("protected_tests", [test.name for test in self.protected_tests])):
            if len(set(names)) != len(names):
                raise ValueError(f"{label}: name each test once")
        return self


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def minutes(seconds):
    return f"{seconds / 3600:g} h" if seconds >= 7200 else f"{seconds / 60:.0f} min" if seconds >= 90 else f"{seconds:.0f} s"


def problem_of(charter, reference):
    """The charter's revision as the ticket states it: its title, summary and objective."""
    from optimization_framework.problem_charter.charter import parse, render, resolve
    parsed = parse(charter)
    objective = parsed.objective
    return {"id": reference["id"], "revision": reference["revision"], "title": parsed.title,
            "summary": render(parsed.summary, resolve(parsed)["values"], parsed).strip(),
            "objective": f"{objective.direction} {objective.name}" + (f" ({objective.units})" if objective.units.strip() else "") if objective else None}


def budget_of(record, consent=None, mandate=None):
    """The compute and model budget the work runs under: the go-ahead's worker time (its consent's, else its mandate's envelope),
    the mandate's model-spend envelope (None: none set), and the workspace's own CPU allowance."""
    worker = consent["worker_seconds"] if consent else mandate.compute.worker_seconds if mandate else None
    return {"mandate_id": mandate.id if mandate else None, "template": mandate.template if mandate else None,
            "consent_id": consent["id"] if consent else None, "worker_seconds": worker,
            "model_usd": mandate.model_usd if mandate else None, "cpu_seconds": record.get("cpu_budget_seconds")}


def build(record, proposals, keys, *, library=None, problem=None, why=None, given=None, consent=None, mandate=None):
    """The ticket of a workspace record serving ``proposals`` under their METHODS ``keys``: the generated ``library`` (F4), or
    None and ``why`` not; the charter revision (``problem``); the implementation lead's tests (``given``, a TicketInput); the
    budget of the go-ahead (``consent``) and ``mandate`` it opens under; and the box's walls as the record holds them (H5,
    `DevelopmentWorkspaces.walls()`: its wall time to the deadline, its limits and the hosts it may reach)."""
    given = given or TicketInput()
    commission = record.get("commission")
    prefix = f"libraries/{library['name']}/" if library else None
    generated = {prefix + path for path in library["files"]} if library else set()
    tests = [{"path": prefix + path, "source": "base version" if library.get("base") else "generated"} for path in sorted(library["files"])
             if PurePosixPath(path).parent == PurePosixPath("tests") and PurePosixPath(path).name.startswith("test_")] if library else []
    for test in given.acceptance_tests:
        if test.path in generated and test.content is not None:
            raise ValueError(f"{test.path} is a file of the generated library: name it without content, or put the new test at another path")
        if test.path in {row["path"] for row in tests}:
            continue
        tests.append({"path": test.path, "source": "commission" if commission else "implementation lead",
                      **({"content": test.content, "sha256": sha256(test.content.encode())} if test.content is not None else {})})
    if commission and not tests:   # a commission names the library's contract test when nothing else gives one (roadmap H7)
        tests.append({"path": f"libraries/{library_name(commission)}/tests/test_contract.py", "source": "commission"})
    targets = [prefix.rstrip("/")] if prefix else []
    targets += [row["path"] for row in tests if not (prefix and row["path"].startswith(prefix))]
    ticket = {"id": "development_ticket_" + content_hash([record["id"]])[:24], "kind": KIND, "campaign_id": record["campaign_id"],
        "workspace_id": record["id"], "created_at": now(), "title": record.get("title") or record["id"], "objective": record.get("objective") or "",
        "proposals": [{"hypothesis_id": row["id"], "title": row.get("title") or row["id"], "mechanism": str(row.get("mechanism") or ""),
                       "method_key": keys[row["id"]] if library else None} for row in proposals],
        "charter": problem,
        "library": {"name": library["name"], "package": library["package"], "path": prefix, "fixed": list(library["fixed"]),
                    "filled": [f"{prefix}{library['package']}/{name}" for name in ("objective.py", "methods.py")],
                    **({"base": library["base"]} if library.get("base") else {})} if library else None,
        "no_library": why if problem and not library else None,
        "acceptance_tests": tests, "test_command": "uv run pytest " + " ".join(targets) if targets else None,
        "protected_tests": list(commission["protected_tests"]) if commission else [test.name for test in given.protected_tests],
        "evidence_ids": list(record.get("evidence_ids") or []), "budget": budget_of(record, consent, mandate),
        "deadline": {"wall_seconds": record.get("wall_seconds"), "at": mandate.deadline_at if mandate else None},
        "limits": record.get("limits"), "egress": record.get("egress")}
    if commission:
        ticket["commission"] = {key: commission.get(key) for key in ("kind", "name", "compute_seconds", "spec", "fixtures", "task_id")}
        ticket["commission"]["library"] = None if library else library_name(commission)
    ticket["house_rules"] = house_rules(ticket)
    return ticket


def library_name(commission):
    """The library a commission builds when no charter generates one: its specification's name as a directory name."""
    name = re.sub(r"[^a-z0-9]+", "-", str(commission.get("name") or "").lower()).strip("-")[:60].strip("-")
    return name if name[:1].isalnum() else ("library-" + name).rstrip("-")


def spec(ticket):
    """`.balsamic/spec.json`: the ticket, its tests by path and digest and its house rules by file (their text is in those files)."""
    return {**{key: value for key, value in ticket.items() if key != "content_hash"}, "house_rules": "AGENTS.md",
            "acceptance_tests": [{key: value for key, value in row.items() if key != "content"} for row in ticket["acceptance_tests"]]}


def files(ticket):
    """{repository path: bytes} that prepare() writes into the worktree: the four files, and the implementation lead's acceptance
    tests that come with their source. Nothing protected is among them: the ticket holds only the protected tests' names."""
    rules = ticket["house_rules"].encode()
    found = {"TASK.md": task(ticket).encode(), "AGENTS.md": rules, "CLAUDE.md": rules,
             ".balsamic/spec.json": (json.dumps(spec(ticket), indent=2) + "\n").encode()}
    for row in ticket["acceptance_tests"]:
        if row.get("content") is not None:
            found[row["path"]] = row["content"].encode()
    return found


def task(ticket):
    """TASK.md: the ticket as the coding agent reads it."""
    lines = [f"# Work ticket: {ticket['title']}", "", ticket["objective"], ""]
    problem, library = ticket.get("charter"), ticket.get("library")
    if ticket.get("commission"):
        lines += commission_lines(ticket["commission"])
    if problem:
        lines += ["## The problem", "", f"{problem['title']}. {problem['summary']}", ""]
        if problem.get("objective"):
            lines += [f"Objective: {problem['objective']}.", ""]
        lines += [f"Charter `{problem['id']}`, revision {problem['revision']}. " + (
            f"The library is in `{library['path']}`: the version the lab runs, which you build on (below)." if library and library.get("base") else
            f"The library generated from it is in `{library['path']}`; its README says what to write." if library else
            f"No library could be generated from it ({ticket.get('no_library')}): build one as docs/optimizer-plugins.md describes."), ""]
    if library and library.get("base"):
        lines += base_lines(library)
    lines += ["## Proposals", ""]
    if not ticket["proposals"]:
        lines += ["None: this work builds the evaluator, not a method.", ""]
    for row in ticket["proposals"]:
        lines += [f"### {row['title']} (`{row['hypothesis_id']}`)", ""]
        if row.get("method_key"):
            lines += [f"Its METHODS key: `{row['method_key']}` with `\"hypothesis_id\": \"{row['hypothesis_id']}\"`.", ""]
        lines += [row["mechanism"].strip() or "(No mechanism is written.)", ""]
    lines += ["## Acceptance tests", ""]
    if ticket.get("test_command"):
        lines += [f"Done means `{ticket['test_command']}` passes, with these among its tests:", ""]
    lines += [f"- `{row['path']}` ({row['source']})" for row in ticket["acceptance_tests"]] or ["- None named."]
    if ticket["protected_tests"]:
        lines += ["", "Balsamic also runs protected acceptance tests outside this workspace on every delivery: "
                  + ", ".join(f"`{name}`" for name in ticket["protected_tests"]) + ". You see their names and outcomes, never their source."]
    lines += ["", "## Budget, deadline and walls", ""] + budget_lines(ticket)
    if ticket["evidence_ids"]:
        lines += ["", "## Evidence", "", "`.campaign/evidence.json` holds: " + ", ".join(f"`{value}`" for value in ticket["evidence_ids"]) + "."]
    return "\n".join(lines) + "\n"


def base_lines(library):
    """TASK.md's section on the version a workspace builds on (roadmap L3, decision 25): its methods, and what a new version keeps."""
    base = library["base"]
    methods = base.get("methods") or []
    lines = ["## What you build on", "", f"`{library['path']}` holds {base['package']} {base['version']}, the version the lab runs, with "
             f"{len(methods)} method{'s' if len(methods) != 1 else ''}" + (": " + ", ".join(f"`{method}`" for method in methods) if methods else "")
             + (f" and the problem{'s' if len(base.get('problems') or []) != 1 else ''} " + ", ".join(f"`{p}`" for p in base["problems"])
                if base.get("problems") else "") + ". Other campaigns use them.", "",
             "- Keep every method and problem, and keep what each does: Balsamic refuses a version that removes or changes one a campaign uses.",
             f"- A changed behaviour is a new method under a new name (such as `{(methods or ['foo'])[0]}_v2`); a changed scoring function is a "
             "new problem id. Add your methods beside the existing ones, with their tests; keep the existing tests.",
             f"- Raise the version above {base['version']}.", ""]
    return lines


def commission_lines(commission):
    """TASK.md's section on a commission (roadmap H7): what it asks for, and its frozen specification as the coding agent may read it."""
    spec = dict(commission.get("spec") or {})
    what = ("the evaluator of a task: a library that provides its problem, with the objective written in it" if commission["kind"] == "evaluator"
            else "a method for the proposal below")
    lines = ["## The commission", "", f"This work was commissioned: {what}. Its specification is frozen: implement it as written, and say "
             "in your delivery report what you could not.", "", "Mechanism:", "", str(spec.pop("mechanism", "")).strip(), "",
             "Acceptance criteria, each to be shown by a test of the library:", ""]
    lines += [f"- {criterion}" for criterion in spec.pop("acceptance_criteria", [])] + [""]
    if commission.get("library"):
        lines += [f"Build it as the library `libraries/{commission['library']}/`.", ""]
    if commission.get("fixtures"):
        lines += [f"Balsamic holds {commission['fixtures']} independent numerical fixtures of this evaluator outside the workspace and "
                  "checks them on every delivery, as a protected test.", ""]
    lines += ["The rest of the specification:", "", "```json", json.dumps(spec, indent=2, sort_keys=True), "```", ""]
    return lines


def budget_lines(ticket):
    budget, deadline, limits, egress = (ticket.get(key) or {} for key in ("budget", "deadline", "limits", "egress"))
    found = []
    if budget.get("worker_seconds") is not None:
        found.append(f"- Compute: the researcher's go-ahead ({(budget.get('template') or 'compute').replace('_', ' ')} mandate) allows "
                     f"{minutes(budget['worker_seconds'])} of worker time in all, for everything its plan names.")
    if budget.get("model_usd") is not None:
        found.append(f"- Model spend: ${budget['model_usd']:.2f} for the request's agents.")
    if budget.get("cpu_seconds") is not None:
        found.append(f"- CPU allowance: {minutes(budget['cpu_seconds'])} of container CPU; the workspace pauses when it is spent.")
    if deadline.get("wall_seconds"):
        found.append(f"- Deadline: {minutes(deadline['wall_seconds'])} of wall time from the workspace's first start; then it pauses, "
                     "with your session saved.")
    if deadline.get("at"):
        found.append(f"- The request's deadline: {deadline['at'][:16].replace('T', ' ')} UTC.")
    if limits:
        found.append(f"- Limits: {limits['cpus']:g} CPUs, {limits['memory_gb']:g} GB of memory, "
                     + (f"{limits['gpus']} GPU{'s' if limits['gpus'] != 1 else ''}." if limits.get("gpus") else "no GPU."))
    if egress:
        hosts = [*egress.get("model", []), *egress.get("package_index", []), *egress.get("named", [])]
        found.append("- Network: only " + ", ".join(hosts) + "; nothing else is reachable.")
    return found or ["- None set: container CPU is measured."]


def house_rules(ticket):
    """AGENTS.md and CLAUDE.md, the same for any harness: what to build, how to run the tests, how to submit, what not to touch."""
    library = ticket.get("library")
    named = (ticket.get("commission") or {}).get("library")
    command = ticket.get("test_command") or "uv run pytest libraries/<name>"
    target = library["path"].rstrip("/") if library else f"libraries/{named or '<name>'}"
    lines = ["# House rules", "", "This is a Balsamic coding workspace. TASK.md is your work ticket: the proposals to implement, the problem, "
             "the acceptance tests, the budget and the deadline. `.balsamic/spec.json` holds the same ticket as JSON.", "",
             "## What to build", ""]
    if library and library.get("base"):
        package = library["package"]
        lines += [f"The library `{target}/` at {library['base']['package']} {library['base']['version']}, the version the lab runs: add a "
                  f"method per proposal beside the existing ones (in `{package}/methods.py` under the METHODS key TASK.md gives it, for a "
                  "library generated from a charter), keep every existing method and what it does, and raise the version. TASK.md says what "
                  "you build on."]
    elif library:
        package = library["package"]
        lines += [f"The library `{target}/`, generated from the charter (its README says what to write):",
                  f"1. Write the objective in `{package}/objective.py`.",
                  f"2. Write one function per proposal in `{package}/methods.py`, under the METHODS key TASK.md gives it.",
                  "A method that needs its own state, batches or checkpoints follows the optimizer_v1 package contract instead: see "
                  "docs/optimizer-plugins.md."]
    else:
        lines += [f"A library under `{target}/` for the proposals in TASK.md, on the optimizer_v1 package contract as "
                  "docs/optimizer-plugins.md describes: a module per method, its own tests and `tests/test_contract.py`."]
    lines += ["", "## How to run the tests", "",
              f"`{command}` runs the acceptance tests TASK.md lists, Balsamic's contract checks (`tests/test_contract.py`) among them. "
              f"`balsamic-workspace check {target}` runs a library's tests and gives the counts for your report. Done means they pass.", "",
              "## How to submit", "",
              "1. Commit the library with an `implementation-manifest.json` holding `files` (the library's repository-relative paths), "
              "exact `dependencies` and a `test_summary`.",
              "2. Raise the version in its `pyproject.toml` with every new delivery: the lab loads new code only when the version changes.",
              "3. Submit the full commit hash with your delivery report: `campaign_submit`, or `balsamic-workspace submit <commit> --report <file>`.", "",
              "The delivery report: your verdict (ready only when every method is implemented, its conformance check passed, no test fails "
              "and nothing is limited; ready_with_limits with the limitations; not_ready with what must happen next), each method's id, "
              "proposal, state, tests and conformance, the totals of your test run with its command, and the next actions with who does "
              "each. The researcher reads it as the outcome of your work. Balsamic installs the library when you deliver it (unless you "
              "report it not ready), so installing is nobody's next action.", "",
              "## What not to touch", ""]
    if library:
        lines.append(f"- `charter.json` and `{library['package']}/data.py` stay as generated: Balsamic refuses a library whose data no "
                     "longer matches the charter revision.")
    lines += ["- The acceptance tests TASK.md lists: make them pass; do not weaken or remove them.",
              "- TASK.md, AGENTS.md, CLAUDE.md and `.balsamic/`: they are Balsamic's, and say what was asked."]
    if ticket["protected_tests"]:
        lines.append("- Balsamic runs protected acceptance tests outside this workspace on every delivery; you see their names and "
                     "outcomes, never their source.")
    return "\n".join(lines) + "\n"


# The review ------------------------------------------------------------------------------------------------------------------
def lines_changed(old, new):
    """(lines added, lines removed) from one version of a file to another; (None, None) for a file that is not text."""
    try:
        before = old.decode().splitlines() if old is not None else []
        after = new.decode().splitlines() if new is not None else []
    except UnicodeDecodeError:
        return None, None
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=len(before) * len(after) > 25_000_000)
    added = removed = 0
    for tag, start, end, first, last in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed += end - start
        if tag in {"replace", "insert"}:
            added += last - first
    return added, removed


def diff_summary(base, delivered, *, hashes=None, ticket=None, limit=50):
    """What a delivery changed from the base the ticket wrote: ``base`` and ``delivered`` are {path: bytes}; ``hashes`` the
    generated files' sha256 (a generated file whose content is not in ``base`` is compared by its hash, its lines unknown).
    Files and lines changed, and the generated files (other than the two the coding agent fills), the charter's fixed files
    and the acceptance tests it touched."""
    hashes = dict(hashes or {})
    library = (ticket or {}).get("library") or {}
    known = set(base) | set(hashes)
    rows = []
    for path in sorted(known | set(delivered)):
        old, new = base.get(path), delivered.get(path)
        if path in base and old == new or path not in base and path in hashes and new is not None and sha256(new) == hashes[path]:
            continue
        status = "removed" if new is None else "changed" if path in known else "added"
        added, removed = lines_changed(old, new) if path in base or path not in known else (None, None)
        rows.append({"path": path, "status": status, "lines_added": added, "lines_removed": removed,
                     "base": "generated" if path in hashes else "ticket" if path in base else None})
    touched = {row["path"] for row in rows}
    filled = set(library.get("filled") or [])
    return {"files_changed": len(rows), "lines_added": sum(row["lines_added"] or 0 for row in rows),
            "lines_removed": sum(row["lines_removed"] or 0 for row in rows),
            "generated_files_touched": sorted(path for path in touched & set(hashes) if path not in filled),
            "fixed_files_touched": sorted(touched & set(library.get("fixed") or [])),
            "acceptance_tests_touched": sorted(touched & {row["path"] for row in (ticket or {}).get("acceptance_tests", [])}),
            "files": rows[:limit], **({"files_not_listed": len(rows) - limit} if len(rows) > limit else {})}
