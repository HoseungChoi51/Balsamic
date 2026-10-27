"""Numeric claim checks (roadmap K2): the numbers an agent writes, and whether any of its evidence holds them.

A written number matches when an evidence number rounds to it at the precision written (0.94 and 0.9375), directly or as
a percentage (93.75% and 0.9375). Nothing is refused: the numbers no evidence matches are saved beside the claim as
`unverified_numbers` and shown as a badge. Rounding, units and counts make some badges false; the evals measure the rate."""
from bisect import bisect_left
import json
import math
import re
from typing import NamedTuple

# What is not a claimed quantity: code, links, dates and times, versions, and identifiers with digits (record ids, H01, S16).
NOT_QUANTITIES = re.compile("|".join([
    r"```.*?```", r"`[^`\n]*`",
    r"\]\([^)\s]*\)", r"\b[a-z][a-z0-9+.-]*://\S+", r"(?<![\w&])#[A-Za-z][\w/.-]*",
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b",
    r"\b\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\b",
    r"\bv?\d+(?:\.\d+){2,}\b", r"\bv\d+(?:\.\d+)?\b",
    r"\b[A-Za-z_][\w-]*\d[\w-]*",
]), re.S)
NUMBER = re.compile(r"(?<![\w.])([+\-−]?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?:[eE]([+\-−]?\d+))?(\s?%)?(?!\w|\.\d)")
# Evidence is walked to this many numbers at most; a journal of evaluations holds far more than any claim cites.
EVIDENCE_LIMIT = 200_000


class Number(NamedTuple):
    text: str
    value: float
    tolerance: float
    percent: bool
    signed: bool


def _parse(match):
    sign, whole, decimals, exponent, percent = match.groups()
    decimals = decimals or ""
    power = int(exponent.replace("−", "-")) if exponent else 0
    value = float(whole.replace(",", "") + ("." + decimals if decimals else "")) * 10.0 ** power
    if sign in {"-", "−"}:
        value = -value
    return Number(match.group(0).strip(), value, 0.5 * 10.0 ** (power - len(decimals)), bool(percent), bool(sign))


def numbers(text):
    """The quantities a text states: decimals, numbers with thousands separators, percentages, scientific notation and signs.

    Numbers in record ids, dates, times, versions, links and code spans are skipped, and so are integers below 10 (counts)."""
    if not isinstance(text, str) or not text:
        return []
    plain = NOT_QUANTITIES.sub(lambda match: " " * len(match.group(0)), text)
    found = []
    for match in NUMBER.finditer(plain):
        number = _parse(match)
        if not match.group(3) and not match.group(4) and not number.percent and abs(number.value) < 10:
            continue
        found.append(number)
    return found


class Evidence:
    """The numbers in records, receipts and texts, sorted for lookup. A percentage in a text also counts as its fraction."""
    def __init__(self, *sources):
        values = []

        def walk(value):
            if len(values) >= EVIDENCE_LIMIT:
                return
            if isinstance(value, bool) or value is None:
                return
            if isinstance(value, (int, float)):
                if math.isfinite(value):
                    values.append(float(value))
            elif isinstance(value, str):
                for match in NUMBER.finditer(value):
                    number = _parse(match)
                    values.append(number.value)
                    if number.percent:
                        values.append(number.value / 100)
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    walk(item)
        for source in sources:
            walk(source)
        self.signed = sorted(values)
        self.magnitudes = sorted(abs(value) for value in values)

    def __len__(self):
        return len(self.signed)

    def holds(self, number):
        """Whether an evidence number rounds to the written one, directly or (for a percentage) as a fraction times 100.
        A number written without a sign may be a magnitude: prose says "fell by 3.2" of a change of -3.2."""
        targets = [(number.value, number.tolerance)]
        if number.percent:
            targets.append((number.value / 100, number.tolerance / 100))
        values = self.signed if number.signed else self.magnitudes
        for target, tolerance in targets:
            low = target - tolerance * (1 + 1e-9) - 1e-12 * abs(target)
            position = bisect_left(values, low)
            if position < len(values) and values[position] <= target + tolerance * (1 + 1e-9) + 1e-12 * abs(target):
                return True
        return False


def unverified(text, evidence):
    """The numbers of a text that no evidence matches, as written, each once. `evidence` is an Evidence, or the records,
    receipts and texts to read numbers from."""
    if not isinstance(evidence, Evidence):
        evidence = Evidence(evidence)
    missing = []
    for number in numbers(text):
        if number.text not in missing and not evidence.holds(number):
            missing.append(number.text)
    return missing


def request_runs(store, run):
    """The runs of the request a run belongs to: the turn that was asked and the notice turns that continue it."""
    root = ((run.get("origin") or {}).get("root") or {}).get("run_id") or run["id"]
    runs = [row for row in store.list_agent_runs(run["agent_id"])
            if row["id"] == root or ((row.get("origin") or {}).get("root") or {}).get("run_id") == root]
    return runs if any(row["id"] == run["id"] for row in runs) else [*runs, run]


def receipts(store, run_ids):
    """The tool results of these runs, compute's among them: each one is evidence a claim may cite."""
    run_ids = list(dict.fromkeys(run_ids))
    if not run_ids:
        return []
    with store.connection() as db:
        rows = db.execute("SELECT data FROM records WHERE kind='agent_tool_receipt' AND json_extract(data,'$.run_id') IN "
                          f"({','.join('?' * len(run_ids))})", run_ids).fetchall()
    found = []
    for (data,) in rows:
        receipt = json.loads(data)
        result = receipt.get("result")
        if receipt.get("tool") == "yield_work":   # an earlier reply is the agent's own words, not evidence
            continue
        if not (isinstance(result, dict) and result.get("error") and result.get("executed") is False):
            found.append(result)
    return found
