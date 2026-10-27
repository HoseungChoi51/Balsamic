"""docs/invariants.md keeps its promises: a `code` row names tests that exist, a `prompt` row names eval scenarios that exist,
and no row is ambiguous. A guarantee that loses its test fails here rather than silently."""
import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "invariants.md"
SCENARIOS = ROOT / "evals" / "lead" / "scenarios"
COLUMNS = ["ID", "Guarantee", "State", "Where", "Pinned by", "Closed by"]
STATES = {"code", "prompt", "none"}
# INV-01 to INV-32 keep their numbers; a row added later is keyed by its part (INV-B3-1), so parallel parts never collide.
ID = re.compile(r"INV-(\d{2,}|[A-Z]\d+-\d+)")
LAST_NUMBERED = 32


def cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def rows(text):
    """The register's rows, each a dict by column; the table is the one whose header is COLUMNS."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("|") and cells(line) == COLUMNS:
            break
    else:
        raise ValueError("No table with the columns " + " | ".join(COLUMNS))
    found = []
    for line in lines[index + 2:]:
        if not line.lstrip().startswith("|"):
            break
        values = cells(line)
        found.append(dict(zip(COLUMNS, values)) if len(values) == len(COLUMNS) else {"ID": values[0], "malformed": len(values)})
    return found


def defined_tests(path):
    """Node ids a test file defines: its functions, and the methods of its classes as Class::method."""
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.update(f"{node.name}::{item.name}" for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return names


def scenario_ids(folder):
    return {json.loads(path.read_text(encoding="utf-8"))["id"] for path in folder.glob("*.json")}


def problems(text, root=ROOT, scenarios=SCENARIOS):
    """Everything wrong with a register, one line each; empty when it holds."""
    found, seen, files, known = [], set(), {}, scenario_ids(scenarios)
    for row in rows(text):
        identity = row["ID"]
        if "malformed" in row:
            found.append(f"{identity}: {row['malformed']} cells, not {len(COLUMNS)}")
            continue
        if identity in seen:
            found.append(f"{identity}: the id repeats")
        seen.add(identity)
        form = ID.fullmatch(identity)
        if not form:
            found.append(f"{identity}: an id is INV-<number> or INV-<part>-<n>")
        elif form.group(1).isdigit() and int(form.group(1)) > LAST_NUMBERED:
            found.append(f"{identity}: a new row takes an id keyed by its part, INV-<part>-<n>")
        state = row["State"]
        if state not in STATES:
            found.append(f"{identity}: state {state!r} is not one of code, prompt, none")
        pins = re.findall(r"`([^`]+)`", row["Pinned by"])
        tests = [pin for pin in pins if "::" in pin]
        named = [pin for pin in pins if "::" not in pin]
        for pin in tests:
            path, _, name = pin.partition("::")
            name = name.split("[", 1)[0]   # a parametrized case pins its function
            if path not in files:
                files[path] = defined_tests(root / path) if (root / path).is_file() else None
            if files[path] is None:
                found.append(f"{identity}: {path} does not exist")
            elif name not in files[path]:
                found.append(f"{identity}: {path} defines no {name}")
        for scenario in named:
            if scenario not in known:
                found.append(f"{identity}: no eval scenario {scenario}")
        if state == "code" and not tests:
            found.append(f"{identity}: a code row names no pinning test")
        if state == "prompt" and not named:
            found.append(f"{identity}: a prompt row names no eval scenario")
    if not seen:
        found.append("The register has no rows")
    return found


def test_the_register_holds():
    assert problems(REGISTER.read_text(encoding="utf-8")) == []


def test_the_register_holds_the_seeded_guarantees():
    register = rows(REGISTER.read_text(encoding="utf-8"))
    states = {row["State"] for row in register}
    assert len(register) >= 25 and states == STATES
    # The guarantees the roadmap's part I1 seeded, by where they are enforced or which part closes them.
    text = REGISTER.read_text(encoding="utf-8")
    for anchor in ("compute_consent.py", "_request", "INSTRUCTIONS", "page_work", "grant_mandate()", "guidance_pin", "_within_llm_budget()",
                   "readiness()", "| T1 |", "| T2 |", "| V1 |", "| V2 |", "promotion.py", "freeze()", "| V4 |", "| K2 |",
                   "library/service.py", "findings.py", "library_install.py", "| H6 |", "network.sh", "| H5 |", "test_layering.py",
                   "NAMES_A_DOMAIN", "test_harness_contract.py"):
        assert anchor in text, anchor


HEADER = "| ID | Guarantee | State | Where | Pinned by | Closed by |\n|---|---|---|---|---|---|\n"
GOOD = {
    "code": "| INV-X1-1 | Holds | code | `a.py` `f()` | `tests/test_invariants.py::test_the_register_holds` | |",
    "method": "| INV-X1-2 | Holds | code | `a.py` | `tests/fixture_pins.py::TestHeld::test_method` | |",
    "prompt": "| INV-X1-3 | Asked | prompt | instructions | `S3-narrow-request` | R3 |",
    "none": "| INV-X1-4 | Hoped | none | | | V1 |",
    "numbered": "| INV-05 | Held before the keyed ids | none | | | |",
}
BROKEN = {
    "a code row without a test": ("| INV-Y1-1 | Holds | code | `a.py` | | |", "names no pinning test"),
    "a code row pinned only by a scenario": ("| INV-Y1-1 | Holds | code | `a.py` | `S3-narrow-request` | |", "names no pinning test"),
    "a test file that does not exist": ("| INV-Y1-1 | Holds | code | `a.py` | `tests/test_gone.py::test_x` | |", "tests/test_gone.py does not exist"),
    "a test the file does not define": ("| INV-Y1-1 | Holds | code | `a.py` | `tests/test_invariants.py::test_gone` | |", "defines no test_gone"),
    "a method its class does not define": ("| INV-Y1-1 | Holds | code | `a.py` | `tests/fixture_pins.py::TestHeld::test_gone` | |", "defines no TestHeld::test_gone"),
    "a method named as a function": ("| INV-Y1-1 | Holds | code | `a.py` | `tests/fixture_pins.py::test_method` | |", "defines no test_method"),
    "a prompt row without a scenario": ("| INV-Y1-1 | Asked | prompt | instructions | | |", "names no eval scenario"),
    "a scenario that does not exist": ("| INV-Y1-1 | Asked | prompt | instructions | `S99-gone` | |", "no eval scenario S99-gone"),
    "a repeated id": ("| INV-X1-1 | Again | none | | | |", "INV-X1-1: the id repeats"),
    "an unknown state": ("| INV-Y1-1 | Holds | enforced | `a.py` | `tests/test_invariants.py::test_the_register_holds` | |", "state 'enforced'"),
    "a numbered id past the last numbered row": ("| INV-33 | Holds | none | | | |", "INV-33: a new row takes an id keyed by its part"),
    "an id of another form": ("| B3-1 | Holds | none | | | |", "B3-1: an id is INV-<number> or INV-<part>-<n>"),
    "a row with a missing cell": ("| INV-Y1-1 | Holds | code | `tests/test_invariants.py::test_the_register_holds` | |", "5 cells"),
}


@pytest.fixture
def fixture_root(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_invariants.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "tests" / "fixture_pins.py").write_text("class TestHeld:\n    def test_method(self):\n        pass\n", encoding="utf-8")
    return tmp_path


def test_a_well_formed_fixture_table_holds(fixture_root):
    assert problems(HEADER + "\n".join(GOOD.values()) + "\n", fixture_root) == []


@pytest.mark.parametrize("case", BROKEN, ids=list(BROKEN))
def test_each_broken_fixture_table_fails(fixture_root, case):
    row, expected = BROKEN[case]
    found = problems(HEADER + "\n".join([*GOOD.values(), row]) + "\n", fixture_root)
    assert len(found) == 1 and expected in found[0], found


def test_a_page_without_the_register_table_fails():
    with pytest.raises(ValueError, match="No table"):
        problems("| ID | Guarantee |\n|---|---|\n| INV-X1-1 | Holds |\n")
    assert problems(HEADER) == ["The register has no rows"]
