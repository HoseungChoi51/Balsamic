"""A campaign's rules for its experiments, and runs hidden from the Experiments page.

The rules are the experiment operator's standing instructions, which the researcher can edit: how runs are named,
where short runs end and long runs begin, how many of the campaign's runs may go at once (the scheduler enforces it,
inside the workspace's worker ceiling), and how runs are chosen and ordered so that unpromising candidates cost little.
Hiding a run takes it off the Experiments page and nothing else: its records stay, and findings and reports may cite it.
"""
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract
from optimization_framework.storage.sqlite import now

NAMING = "{stage} · {proposal} · {method} · seed {seed}"
STRATEGY = """Screening different strategies: give each the shortest run that can tell it apart from the others, with the same
number of evaluations for all and two seeds each. Compare them at matched cost (comparison.report). Keep the best third and give
those three times the budget; repeat until one or two remain or the differences are smaller than the spread between seeds. Stop
a run early when its best-so-far curve stays below another strategy's at the same cost, and say why.
Tuning one strategy: start from a small spread of settings (config_suggest with no observations), run them at the screening
length, then ask config_suggest for the next settings from the scores so far, a few at a time. Stop when a round brings no
improvement larger than the spread between seeds.
Order: the runs that decide the most go first (queue priority); a long run only for a strategy that survived screening.
Before deciding about a strategy you do not understand, read its proposal, or ask the lead agent (lead_ask)."""


# What a run's entry and the list of runs can show. Each is drawn by the application itself; an agent only chooses among them.
SECTIONS = ("design", "curve", "objectives", "numbers", "settings", "files", "question")
COLUMNS = ("thumbnail", "name", "method", "seed", "status", "best", "objectives", "evaluations", "time", "completion")


class DesignView(Contract):
    """How a design is drawn: a two-dimensional mask image (rows x cols, row by row), a one-dimensional strip, a table of its
    values (only for a few), or not at all."""
    render: Literal["mask", "strip", "table", "none"]
    rows: int | None = Field(default=None, ge=1, le=4096)
    cols: int | None = Field(default=None, ge=1, le=4096)
    on_label: str = Field(default="1", max_length=40, description="What a cell of value 1 is, e.g. silicon")
    off_label: str = Field(default="0", max_length=40, description="What a cell of value 0 is, e.g. air")


class Presentation(Contract):
    """What the list of runs and a run's entry show, in order. Sections: design (the best design, drawn as DesignView says),
    curve (the best score so far of the primary objective against curve_x; other objectives are not drawn as curves), objectives
    (the best design's value of each objective), numbers (evaluations, solver executions, worker time, completion), settings (method,
    seed, parameters), files (the run's spec, result and metrics files), question. Columns: thumbnail (a small drawing of the best
    design), name, method, seed, status, best (primary objective), objectives (the others), evaluations, time, completion."""
    list_columns: list[Literal[COLUMNS]] = Field(min_length=1, max_length=10)
    entry_sections: list[Literal[SECTIONS]] = Field(min_length=1, max_length=7)
    design: DesignView
    curve_x: Literal["evaluations", "elapsed_seconds"] = "evaluations"
    objectives: list[str] = Field(default_factory=list, max_length=12, description="The objectives to show beside the primary one; empty shows all")
    rationale: str = Field(default="", max_length=2000, description="Why this suits the problem")


class ExperimentRulesInput(Contract):
    """Change some of the rules; what is left out stays as it is."""
    naming: str | None = Field(default=None, min_length=1, max_length=300,
        description="How a run is named, in its question's first line. Fields: {stage} (Screen, Tune or Long), {proposal}, {method}, {seed}")
    short_run_seconds: float | None = Field(default=None, gt=0, le=86400,
        description="Runs allotted less than this are short runs (screening); runs allotted this or more are long runs")
    max_concurrent: int | None = Field(default=None, ge=0, le=64,
        description="How many of this campaign's runs may go at once; 0 removes the limit. The workspace's worker ceiling still applies")
    strategy: str | None = Field(default=None, min_length=1, max_length=8000, description="How runs are chosen and ordered")
    presentation: Presentation | None = Field(default=None, description="What the list of runs and a run's entry show")
    expected_revision: int = Field(ge=0)
    rationale: str = Field(min_length=1, max_length=2000)


class TrialHideInput(Contract):
    trial_ids: list[str] = Field(min_length=1, max_length=200)
    hidden: bool = True
    reason: str = Field(default="Obsolete", min_length=1, max_length=2000)


def identity(campaign_id):
    return "experiment_rules_" + campaign_id


def design_shape(problem):
    """(dimensions, rows, cols) of a problem's design: rows and cols when its settings name a grid that the design fills."""
    schema, settings = (problem or {}).get("candidate_schema") or {}, (problem or {}).get("configuration") or {}
    dimensions = schema.get("dimensions")
    for x, y in (("grid_x", "grid_y"), ("nx", "ny"), ("cols", "rows")):
        if isinstance(settings.get(x), int) and isinstance(settings.get(y), int) and settings[x] * settings[y] == dimensions:
            return dimensions, settings[y], settings[x]   # stored row by row: grid_y rows of grid_x cells
    return dimensions, None, None


def pack_labels(problem):
    """The labels of a design's cells that the problem's pack declares (e.g. silicon and air); none for a problem without a
    pack, or one that is not installed."""
    from optimization_framework.evaluation.registry import problems
    name = (problem or {}).get("definition_id")
    if not name or name not in problems.ids():
        return {}
    pack = problems.pack(name)
    labels = pack.presentation.labels if pack is not None else {}
    return {key: labels[key] for key in ("on_label", "off_label") if key in labels}


def default_presentation(problem):
    """A presentation that fits any problem: a grid design as an image, a short binary one as a strip, a few values as a table,
    and never thousands of values listed one by one."""
    dimensions, rows, cols = design_shape(problem)
    binary = ((problem or {}).get("candidate_schema") or {}).get("representation") == "binary"
    if rows:
        design = {"render": "mask", "rows": rows, "cols": cols}
    elif binary and dimensions and dimensions <= 2048:
        design = {"render": "strip"}
    elif dimensions and dimensions <= 40:
        design = {"render": "table"}
    else:
        design = {"render": "none"}
    design.update(pack_labels(problem))
    columns = (["thumbnail"] if design["render"] in {"mask", "strip"} else []) + ["name", "method", "status", "best", "evaluations", "time"]
    return Presentation(list_columns=columns, entry_sections=["design", "curve", "objectives", "numbers", "settings", "files", "question"],
                        design=DesignView(**design), rationale="Default: drawn from the problem's description.").model_dump(mode="json", exclude={"schema_version"})


def _problem(store, campaign_id):
    tasks = [task for task in store.list("task", campaign_id) if not task.get("archived") and task.get("problem")]
    return tasks[0]["problem"] if tasks else None


def defaults():
    from optimization_framework.execution.runtime_profile import gate_seconds
    # The runtime gate already separates the runs that need a measured evaluator from the quick ones.
    return {"naming": NAMING, "short_run_seconds": gate_seconds() or 600.0, "max_concurrent": None, "strategy": STRATEGY}


def current(store, campaign_id):
    """The campaign's rules, or the defaults (revision 0) when none were saved. The presentation, until one is chosen, is drawn
    from the problem."""
    try:
        rules = store.get(identity(campaign_id), "experiment_rules")
    except KeyError:
        rules = {"id": identity(campaign_id), "campaign_id": campaign_id, "revision": 0, **defaults(), "updated_by": None, "updated_at": None}
    if not rules.get("presentation"):
        rules = {**rules, "presentation": default_presentation(_problem(store, campaign_id)), "presentation_chosen": False}
    return rules


def update(store, campaign_id, payload, actor):
    values = ExperimentRulesInput(**payload)
    rules = current(store, campaign_id)
    if values.expected_revision != rules["revision"]:
        raise ValueError(f"The experiment rules changed (revision {rules['revision']}); read them again")
    changes = {key: getattr(values, key) for key in ("naming", "short_run_seconds", "max_concurrent", "strategy") if getattr(values, key) is not None}
    if values.presentation is not None:
        view = values.presentation.design
        dimensions, _, _ = design_shape(_problem(store, campaign_id))
        if view.render == "mask" and (not view.rows or not view.cols or dimensions and view.rows * view.cols != dimensions):
            raise ValueError(f"A mask image needs rows x cols equal to the design's {dimensions} values")
        if view.render == "table" and dimensions and dimensions > 200:
            raise ValueError(f"A table of {dimensions} values is unreadable; draw the design or leave it out")
        changes["presentation"] = values.presentation.model_dump(mode="json", exclude={"schema_version"})
        changes["presentation"]["rationale"] = changes["presentation"]["rationale"] or values.rationale
        changes["presentation_chosen"] = True
    if changes.get("max_concurrent") == 0:
        changes["max_concurrent"] = None
    if not changes:
        raise ValueError("Name at least one rule to change")
    rules.update(changes, revision=rules["revision"] + 1, updated_by=actor, updated_at=now(), rationale=values.rationale)
    return store.put("experiment_rules", rules, "experiments.rules_changed")


ACTIVE = {"queued", "running", "pausing", "stopping"}


def hide(store, campaign_id, payload, actor):
    """Take finished runs off the Experiments page, or put them back. A run still at work is stopped first."""
    values = TrialHideInput(**payload)
    trials = [store.get(trial_id, "trial") for trial_id in dict.fromkeys(values.trial_ids)]
    if any(trial["campaign_id"] != campaign_id for trial in trials):
        raise ValueError("A run belongs to another campaign")
    if busy := [trial["id"] for trial in trials if trial["status"] in ACTIVE]:
        raise ValueError("Stop these runs before hiding them: " + ", ".join(busy[:5]))
    changed = []
    for trial in trials:
        if bool(trial.get("hidden")) == values.hidden:
            continue
        if values.hidden:
            trial["hidden"] = {"by": actor, "reason": values.reason, "at": now()}
        else:
            trial.pop("hidden", None)
        store.put("trial", trial, "trial.hidden" if values.hidden else "trial.shown")
        changed.append(trial["id"])
    return {"changed": changed, "hidden": values.hidden}


def check_trial_ids(store, campaign_id):
    """Runs that check rather than search: runtime-profile probes. (Validation, recipes and diagnostics carry their own marks.)"""
    return {trial_id for profile in store.list("runtime_profile", campaign_id) for level in profile.get("levels", []) for trial_id in level["trial_ids"]}


def run_kind(trial, threshold, probes, chain_seconds=None) -> Literal["short", "long", "check"]:
    """Where a run is listed: a check (validation, recipe, diagnostic, speed probe), or a short or a long run by its allotted time.
    A continued run counts with the runs it continues."""
    if trial.get("recipe") or trial.get("algorithm") == "validate" or trial.get("diagnostic_grant_id") or trial["id"] in probes:
        return "check"
    return "long" if (chain_seconds or trial.get("wall_seconds") or 0) >= threshold else "short"


def classify(trials, threshold, probes):
    """run_kind for each run. The parts of a continued run are listed together, by the time allotted to all of them."""
    by_id = {trial["id"]: trial for trial in trials}
    def root(trial):
        seen = set()
        while not trial.get("recipe") and trial.get("parent_trial_id") in by_id and trial["id"] not in seen:
            seen.add(trial["id"]); trial = by_id[trial["parent_trial_id"]]
        return trial["id"]
    roots = {trial["id"]: root(trial) for trial in trials}
    chains = {}
    for trial in trials:
        chains[roots[trial["id"]]] = chains.get(roots[trial["id"]], 0) + (trial.get("wall_seconds") or 0)
    return {trial["id"]: run_kind(trial, threshold, probes, chains[roots[trial["id"]]]) for trial in trials}
