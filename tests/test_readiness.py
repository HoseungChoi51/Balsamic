"""The readiness files name the triage layer and the register rows of what they fixed (docs/incident-triage.md): the two
lines follow "What was wrong", the layer is one of the five or `none`, and each row they name is in docs/invariants.md."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs" / "readiness"
REGISTER = ROOT / "docs" / "invariants.md"
LAYERS = {"mandate", "budget", "evidence", "prompt", "UI", "none"}
# Written before triage existed; a later part that changes one says so in its own file.
BEFORE_TRIAGE = {"A1", "A3", "I1"}


def register_ids(text):
    return set(re.findall(r"^\| (INV-\d+) \|", text, re.MULTILINE))


def problems(text, known):
    """Everything wrong with a readiness file's two triage lines, one line each; empty when they hold or are absent."""
    lines = text.splitlines()
    layer = [index for index, line in enumerate(lines) if line.startswith("Layer:")]
    invariant = [index for index, line in enumerate(lines) if line.startswith("Invariant:")]
    if not layer and not invariant:
        return []
    if len(layer) != 1 or len(invariant) != 1:
        return ["needs one Layer: line and one Invariant: line"]
    found = []
    heading = next((index for index, line in enumerate(lines) if line.strip() == "## What was wrong"), None)
    following = next((index for index, line in enumerate(lines) if heading is not None and index > heading and line.startswith("## ")), len(lines))
    if heading is None or not heading < layer[0] < invariant[0] < following:
        found.append("Layer: and Invariant: belong under What was wrong, in that order")
    value = lines[layer[0]].removeprefix("Layer:").strip()
    name = re.match(r"`?(\w+)`?", value)
    if not name or name.group(1) not in LAYERS:
        found.append(f"layer {value!r} is not one of " + ", ".join(sorted(LAYERS)))
    elif value == name.group(0).rstrip("."):
        found.append("the layer needs its reason")
    value = lines[invariant[0]].removeprefix("Invariant:").strip()
    named = re.findall(r"INV-\d+", value)
    if not named and not re.match(r"none\W+\w", value.replace("`", "")):
        found.append(f"invariant {value!r} names no register row and does not say none and why")
    for identity in named:
        if identity not in known:
            found.append(f"{identity} is not in the register")
    return found


def files():
    return sorted(path for path in READINESS.glob("*.md") if path.name != "README.md")


@pytest.mark.parametrize("path", files(), ids=lambda path: path.stem)
def test_each_readiness_file_names_its_layer_and_rows(path):
    text = path.read_text(encoding="utf-8")
    assert problems(text, register_ids(REGISTER.read_text(encoding="utf-8"))) == []


def test_readiness_files_after_triage_use_the_two_lines():
    # I2 introduced the lines; it is the first file to use them.
    assert "Layer:" in (READINESS / "I2.md").read_text(encoding="utf-8")
    assert {path.stem for path in files()} >= BEFORE_TRIAGE | {"I2"}


def entry(body):
    return f"# X1 — Something\n\nState: implemented.\n\n## What was wrong\n\nIt broke.\n\n{body}\n\n## What changed\n"


KNOWN = {"INV-01", "INV-07"}
GOOD = {
    "a layer and a row": "Layer: mandate. It ran beyond the request.\nInvariant: INV-01 (updated).",
    "two rows": "Layer: `prompt`. Nothing above holds it.\nInvariant: INV-01, INV-07.",
    "none, with why": "Layer: none. A parsing bug in code that already held it.\nInvariant: none, the row already pins it.",
}
BROKEN = {
    "an unknown layer": ("Layer: model. Whatever.\nInvariant: INV-01.", "is not one of"),
    "a layer without its reason": ("Layer: budget\nInvariant: INV-01.", "needs its reason"),
    "a row the register lacks": ("Layer: budget. Over the cap.\nInvariant: INV-99.", "INV-99 is not in the register"),
    "none without why": ("Layer: UI. The page.\nInvariant: none", "does not say none and why"),
    "a lone layer line": ("Layer: UI. The page.", "needs one Layer: line and one Invariant: line"),
    "lines in the wrong order": ("Invariant: INV-01.\nLayer: UI. The page.", "belong under What was wrong"),
}


@pytest.mark.parametrize("case", GOOD)
def test_well_formed_lines_hold(case):
    assert problems(entry(GOOD[case]), KNOWN) == []


def test_a_file_without_the_lines_holds():
    assert problems(entry(""), KNOWN) == []


@pytest.mark.parametrize("case", BROKEN)
def test_each_broken_entry_fails(case):
    body, message = BROKEN[case]
    found = problems(entry(body), KNOWN)
    assert any(message in line for line in found), found


def test_lines_outside_what_was_wrong_fail():
    text = entry("") + "\nLayer: UI. The page.\nInvariant: INV-01.\n"
    assert any("belong under What was wrong" in line for line in problems(text, KNOWN))
