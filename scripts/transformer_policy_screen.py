"""Transformer-policy hypotheses for the 2D FLRL deflector, a quick screen, and a finalist shortlist.

Everything goes through the workspace's researcher command boundary (the same commands the
dashboard sends), so the hypotheses, experiments, costs and shortlist are ordinary campaign records.
No model call is made and no agent is activated.

  plan      print the hypotheses and trial settings
  create    create the hypotheses and queue the quick trials (idempotent: fixed command identities)
  status    show trial progress
  finalize  rank completed trials and record the three finalists
  pause-finals / resume-finals  pause or resume the long finalist runs (a paused run keeps its budget)
  continue-finals  move unfinished finalist runs to the current source: stop each one and continue its
                   learner state in a new trial for the rest of its wall-clock budget
"""
import argparse
import json
import pickle
import re
import statistics
import time
from pathlib import Path

from optimization_framework.cli import Session

TAG = "transformer-screen-v1"
SCORE = re.compile(r'"mean_plus1_transmission":([-+0-9.eE]+)')
TRIAL_FILES = None
ACTIVE = {"queued", "running", "pausing", "stopping"}
PENDING = ACTIVE | {"paused"}   # a paused run is expected back, so the wait is not over
PARTS = ("", "_continued", "_extended", "_extended2")   # a finalist's successive trials, by the end of their command identity
PAPER = ("Octavian FLRL manuscript and released code (jLabKAIST/flrl, commit 7838e71): PPO with a CNN feature "
         "extractor over four stacked Fourier level-set coefficient frames.")
SHARED = ("Everything except the policy's feature extractor and the stated settings is the reference method: "
          "Fourier level set with mode limits (8, 4), 128-step episodes and rollouts, four stacked frames, "
          "action scaling 0.01, PPO gamma 0.9, GAE 0.95, clip 0.4, three epochs.")

REFERENCE = {
    "key": "reference", "title": "Reference: FLRL PPO with the paper's CNN policy",
    "mechanism": "The released method unchanged: three 3x3 convolutions (32, 64, 128 channels) over the stacked "
                 "coefficient frames, global average pooling, then separate three-layer actor and critic heads. "
                 "PPO learning rate 3e-3.",
    "rationale": "The comparison baseline. It is the method every transformer variant must beat at equal evaluation budget.",
    "config": {"policy_network": "cnn"},
}
CANDIDATES = [
    {"key": "coef-64x2-lr3e-3", "title": "Coefficient-token transformer (64 wide, 2 layers) at the paper's learning rate",
     "mechanism": "Each Fourier coefficient is one token whose features are its four most recent values; a learned "
                  "position per coefficient; 2 pre-norm encoder layers, width 64, 4 heads, mean pooling. PPO learning rate 3e-3.",
     "rationale": "The direct swap: attention can relate any two Fourier modes in one layer, where a 3x3 convolution only "
                  "relates neighbours in the coefficient ordering. Keeping the paper's learning rate isolates the architecture change.",
     "risks": ["3e-3 is high for attention layers and may destabilize the policy."],
     "config": {"transformer_tokens": "coefficient", "transformer_width": 64, "transformer_layers": 2, "transformer_heads": 4,
                "ppo_learning_rate": 0.003}},
    {"key": "coef-64x2-lr3e-4", "title": "Coefficient-token transformer (64 wide, 2 layers) at a tenfold lower learning rate",
     "mechanism": "The same encoder as the paper-rate variant, with PPO learning rate 3e-4.",
     "rationale": "The paper fixes the learning rate for its CNN only. Transformers usually train at lower rates, so this "
                  "tests whether the rate, rather than the architecture, decides the outcome.",
     "risks": ["Learning may be too slow to show within a short budget."],
     "config": {"transformer_tokens": "coefficient", "transformer_width": 64, "transformer_layers": 2, "transformer_heads": 4,
                "ppo_learning_rate": 0.0003}},
    {"key": "coef-128x4-lr3e-4", "title": "Deeper, wider coefficient-token transformer (128 wide, 4 layers, 8 heads)",
     "mechanism": "Coefficient tokens with learned positions; 4 encoder layers, width 128, 8 heads, mean pooling. PPO learning rate 3e-4.",
     "rationale": "Tests whether more capacity helps represent interactions among the 85 level-set coefficients.",
     "risks": ["More parameters than the CNN; may need more data than a short run provides."],
     "config": {"transformer_tokens": "coefficient", "transformer_width": 128, "transformer_layers": 4, "transformer_heads": 8,
                "ppo_learning_rate": 0.0003}},
    {"key": "frame-128x2-lr1e-3", "title": "Frame-token transformer: attention across the four stacked frames",
     "mechanism": "Each of the four stacked frames is one token carrying all its coefficients; a learned position per "
                  "frame; 2 encoder layers, width 128, 4 heads, mean pooling. PPO learning rate 1e-3.",
     "rationale": "Asks whether the useful structure is temporal (how the design has been moving) rather than across coefficients.",
     "risks": ["Only four tokens: attention has little to select between, so this may reduce to an MLP."],
     "config": {"transformer_tokens": "frame", "transformer_width": 128, "transformer_layers": 2, "transformer_heads": 4,
                "ppo_learning_rate": 0.001}},
    {"key": "coef-mode-cls-lr1e-3", "title": "Coefficient tokens positioned by Fourier mode, read out through a summary token",
     "mechanism": "Coefficient tokens whose position is a projection of the mode itself (kx, ky, real or imaginary part) "
                  "instead of a learned table; a summary token is read out instead of mean pooling; 2 layers, width 64, "
                  "4 heads. PPO learning rate 1e-3.",
     "rationale": "Mode-based positions tell the policy which coefficients are harmonically related from the start; a "
                  "summary token lets it weight coefficients unequally.",
     "risks": ["The summary token starts uninformative and may slow early learning."],
     "config": {"transformer_tokens": "coefficient", "transformer_positions": "fourier_mode", "transformer_pooling": "cls",
                "transformer_width": 64, "transformer_layers": 2, "transformer_heads": 4, "ppo_learning_rate": 0.001}},
    {"key": "coef-32x1-lr3e-3", "title": "Minimal transformer (32 wide, 1 layer, 2 heads)",
     "mechanism": "Coefficient tokens with learned positions; a single encoder layer, width 32, 2 heads, mean pooling. PPO learning rate 3e-3.",
     "rationale": "Fewer parameters than the CNN: separates the effect of attention from the effect of capacity, and "
                  "should adapt fastest when evaluations are scarce.",
     "risks": ["May be too small to represent the design landscape."],
     "config": {"transformer_tokens": "coefficient", "transformer_width": 32, "transformer_layers": 1, "transformer_heads": 2,
                "ppo_learning_rate": 0.003}},
    {"key": "coefxframe-64x2-lr1e-3", "title": "Coefficient-by-frame tokens: joint attention over modes and time",
     "mechanism": "Every coefficient of every frame is its own token (340 tokens), positioned by Fourier mode plus a learned "
                  "frame position; 2 layers, width 64, 4 heads, mean pooling. PPO learning rate 1e-3.",
     "rationale": "The least constrained variant: the policy can relate any mode at any recent step to any other.",
     "risks": ["Longest sequence, so the costliest policy update; weakest built-in structure."],
     "config": {"transformer_tokens": "coefficient_frame", "transformer_positions": "fourier_mode", "transformer_width": 64,
                "transformer_layers": 2, "transformer_heads": 4, "ppo_learning_rate": 0.001}},
]
for item in CANDIDATES:
    item["config"] = {"policy_network": "transformer", **item["config"]}
METHODS = [REFERENCE, *CANDIDATES]


def connect(arguments):
    return Session(directory=arguments.workspace, url=arguments.workspace_url, journal=arguments.journal)


def campaign_of(session, arguments):
    state = session.state(arguments.campaign)
    if not state["campaign"]:
        raise SystemExit("No campaign found")
    tasks = [task for task in state["tasks"] if not task.get("archived")]
    if len(tasks) != 1:
        raise SystemExit("Expected exactly one current task")
    return state["campaign"]["id"], tasks[0], state


def create(arguments):
    with connect(arguments) as session:
        campaign_id, task, _ = campaign_of(session, arguments)
        extra = json.loads(arguments.extra_config)
        for method in METHODS:
            outcome = session.command("hypothesis.create", campaign_id, {
                "title": method["title"], "mechanism": method["mechanism"] + " " + SHARED,
                "rationale": method["rationale"], "risks": method.get("risks", []), "sources": [PAPER],
                "assumptions": ["A short run ranks policies only roughly; see the screen's stated budget."],
                "algorithm": "flrl_ppo", "algorithm_config": {**method["config"], **extra}, "status": "investigating",
            }, identity=f"{TAG}_hypothesis_{method['key']}")
            hypothesis_id = outcome["hypothesis_id"]
            for seed in arguments.seeds:
                trial = session.command("trial.create", campaign_id, {
                    "task_id": task["id"], "algorithm": "flrl_ppo", "algorithm_config": {**method["config"], **extra},
                    "seed": seed, "max_steps": arguments.evaluations, "wall_seconds": arguments.wall_seconds,
                    "hypothesis_id": hypothesis_id,
                    "question": f"Quick screen ({arguments.evaluations} evaluations, seed {seed}): does replacing the paper's "
                                "CNN policy with this transformer change early search progress at equal evaluation budget?",
                }, identity=f"{TAG}_trial_{method['key']}_s{seed}")
                print(f"{method['key']:26s} seed {seed}: hypothesis {hypothesis_id}  trial {trial['trial_id']}", flush=True)


def receipt(session, identity):
    path = Path(session.journal) / f"{identity}.json"
    # A request the workspace has not accepted yet (rejected, or its reply was lost) has no receipt.
    saved = json.loads(path.read_text()) if path.is_file() else {}
    return saved["receipt"]["outcome"] if "receipt" in saved else None


def journal(session, trial_id):
    """Per-evaluation objective values of one trial, in order.

    Read from the trial's own observation journal on disk. Each record carries a full
    32,768-cell mask, so the score is picked out of the line instead of parsing it.
    """
    directory = TRIAL_FILES / trial_id if TRIAL_FILES else session.workspace.job_dir(trial_id)
    values = []
    with (directory / "observations.jsonl").open() as stream:
        for line in stream:
            match = SCORE.search(line)
            if match and '"status":"ok"' in line:
                values.append(float(match.group(1)))
    return values


def rows(session, arguments, stage="trial"):
    """The screening trials ("trial") or the long finalist runs ("final") this script queued."""
    campaign_id, task, state = campaign_of(session, arguments)
    trials = {trial["id"]: trial for trial in state["trials"]}
    result = []
    for method in METHODS:
        hypothesis = receipt(session, f"{TAG}_hypothesis_{method['key']}")
        identities = ([f"{TAG}_trial_{method['key']}_s{seed}" for seed in range(64)] if stage == "trial"
                      else [f"{TAG}_final_{method['key']}{part}" for part in PARTS])
        for part, identity in enumerate(identities, 1):
            created = receipt(session, identity)
            if created is None:
                continue
            trial = trials[created["trial_id"]]
            # A resumed trial still carries the result of its paused attempt; its live progress is newer.
            progress = (trial.get("progress") if trial["status"] in ACTIVE else None) or trial.get("result") or trial.get("progress") or {}
            result.append({"key": method["key"], "title": method["title"], "trial_id": trial["id"],
                           "part": part if stage == "final" else 1,
                           "hypothesis_id": hypothesis["hypothesis_id"], "status_revision": hypothesis["hypothesis"]["status_revision"],
                           "seed": trial["seed"], "status": trial["status"], "evaluations": progress.get("evaluations"),
                           "best": progress.get("best_objective"), "elapsed": progress.get("elapsed_seconds"),
                           "updates": (progress.get("diagnostics") or {}).get("training_updates"),
                           "reason": progress.get("reason") or trial.get("reason"), "study_id": trial.get("study_id")})
    return campaign_id, result


def show(result):
    for row in sorted(result, key=lambda r: (r["key"], r["seed"], r["part"])):
        best = "-" if row["best"] is None else f"{100 * row['best']:.2f}%"
        label = row["key"] + ("", " (continued)", " (extended)", " (extended again)")[row["part"] - 1]
        print(f"{label:26s} seed {row['seed']}  {row['status']:10s} evaluations {row['evaluations']}  best {best}  "
              f"updates {row['updates']}  {row['elapsed'] or 0:.0f} s")
    done = sum(row["status"] not in PENDING for row in result)
    print(f"{done}/{len(result)} finished", flush=True)
    return result


def status(arguments):
    with connect(arguments) as session:
        for stage in ("trial", "final"):
            result = rows(session, arguments, stage)[1]
            if result:
                print(f"== {'screen' if stage == 'trial' else 'finalist runs'} ==")
                show(result)


def wait(session, arguments, stage):
    # One session for the whole wait: a local workspace schedules work only while it is open.
    while True:
        try:
            result = rows(session, arguments, stage)[1]
        except Exception as error:   # a service restart or a slow reply must not end an overnight wait
            print(f"waiting: {type(error).__name__}: {error}", flush=True)
            time.sleep(arguments.poll)
            continue
        if result and all(row["status"] not in PENDING for row in result):
            return show(result)
        if arguments.verbose:
            show(result); print("---", flush=True)
        time.sleep(arguments.poll)


def ranking(session, arguments):
    """Mean best efficiency over seeds; the late-run average shows whether the policy itself improved."""
    campaign_id, result = rows(session, arguments)
    if any(row["status"] != "completed" for row in result):
        raise SystemExit("Every screening trial must have completed before finalists are chosen: "
                         + ", ".join(f"{row['key']}/s{row['seed']}={row['status']}" for row in result if row["status"] != "completed"))
    table = []
    for method in METHODS:
        mine = sorted((row for row in result if row["key"] == method["key"]), key=lambda row: row["seed"])
        traces = [journal(session, row["trial_id"]) for row in mine]
        table.append({"key": method["key"], "title": method["title"], "hypothesis_id": mine[0]["hypothesis_id"],
                      "status_revision": mine[0]["status_revision"], "study_id": mine[0]["study_id"],
                      "bests": [row["best"] for row in mine], "mean_best": statistics.mean(row["best"] for row in mine),
                      "first_128_mean": statistics.mean(statistics.mean(trace[:128]) for trace in traces),
                      "last_128_mean": statistics.mean(statistics.mean(trace[-128:]) for trace in traces),
                      "seconds": statistics.mean(row["elapsed"] for row in mine),
                      "prototype": max(mine, key=lambda row: row["best"])})
    reference = next(row for row in table if row["key"] == "reference")
    candidates = sorted((row for row in table if row["key"] != "reference"),
                        key=lambda row: (row["mean_best"], row["last_128_mean"]), reverse=True)
    return campaign_id, reference, candidates


def finalize(session, arguments):
    campaign_id, reference, candidates = ranking(session, arguments)
    finalists = [reference, *candidates[:2]]
    for row in finalists:
        session.command("hypothesis.status", campaign_id, {"hypothesis_id": row["hypothesis_id"], "status": "finalist",
            "expected_status_revision": row["status_revision"]}, identity=f"{TAG}_finalist_{row['key']}")
    shortlist = session.command("finalist.set", campaign_id, {
        "study_id": reference["study_id"], "trial_ids": [row["prototype"]["trial_id"] for row in finalists],
        "label": "Reference CNN and the two best transformer policies from the quick screen"}, identity=f"{TAG}_shortlist")
    summary = {"ranking": [{k: row[k] for k in ("key", "title", "mean_best", "bests", "first_128_mean", "last_128_mean", "seconds")}
                           for row in [reference, *candidates]],
               "finalists": [row["key"] for row in finalists], "shortlist_id": shortlist["finalist_selection_id"]}
    (Path(session.journal) / "screen-summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1), flush=True)
    return finalists


def finals(session, arguments):
    """One long run per finalist, bounded by wall-clock time, on a seed the screen did not use."""
    campaign_id, task, _ = campaign_of(session, arguments)
    chosen = json.loads((Path(session.journal) / "screen-summary.json").read_text())["finalists"]
    for method in (m for key in chosen for m in METHODS if m["key"] == key):
        hypothesis_id = receipt(session, f"{TAG}_hypothesis_{method['key']}")["hypothesis_id"]
        trial = session.command("trial.create", campaign_id, {
            "task_id": task["id"], "algorithm": "flrl_ppo", "algorithm_config": method["config"], "seed": arguments.final_seed,
            "max_steps": arguments.final_evaluations, "wall_seconds": arguments.final_wall_seconds, "hypothesis_id": hypothesis_id,
            "question": f"Finalist run ({arguments.final_wall_seconds / 3600:g} wall-clock hours, fresh seed {arguments.final_seed}): "
                        "how far does this policy take the design when given a full search?",
        }, identity=f"{TAG}_final_{method['key']}")
        print(f"finalist {method['key']:26s} trial {trial['trial_id']}", flush=True)


def control(session, arguments, action):
    """Pause the unfinished finalist runs, or put the paused ones back in the queue."""
    campaign_id, result = rows(session, arguments, "final")
    trials = {trial["id"]: trial for trial in session.state(arguments.campaign)["trials"]}
    for row in result:
        if row["status"] in ({"queued", "running"} if action == "pause" else {"paused"}):
            session.command("trial.control", campaign_id, {"trial_id": row["trial_id"], "action": action,
                "expected_control_revision": trials[row["trial_id"]]["control_revision"]})
            print(f"{action} {row['key']:26s} trial {row['trial_id']}", flush=True)


def saved_state(session, trial_id, name):
    """Write the learner and search state of a trial's latest checkpoint to a file a new trial can start from."""
    from optimization_framework.storage.artifacts import LocalArtifactStore
    directory = TRIAL_FILES / trial_id
    pointer = json.loads((directory / "checkpoints/latest.json").read_text())
    manifest = json.loads((directory / "checkpoints" / (pointer["id"] + ".json")).read_text())
    with LocalArtifactStore(directory / "artifacts").checkpoint_stream(manifest) as stream:
        state = pickle.load(stream)
    saved = (Path(session.journal) / f"{TAG}_state_{name}.pkl").resolve()
    saved.write_bytes(pickle.dumps(state["optimizer"], protocol=pickle.HIGHEST_PROTOCOL))
    return state, saved


def continue_finals(session, arguments):
    """Continue each unfinished finalist run under the current source.

    A trial's source is frozen when it is queued, so a running trial cannot pick up a faster
    evaluator. Its learner and search state are saved to a file instead, the trial is stopped,
    and a new trial warm-starts from that file for the wall-clock time the first one had left.
    """
    campaign_id, result = rows(session, arguments, "final")
    task = campaign_of(session, arguments)[1]
    continued = {row["key"] for row in result if row["part"] == 2}
    # Rerunning is safe: a run already stopped for its continuation is picked up where the last call ended.
    for row in (r for r in result if r["part"] == 1 and r["status"] in PENDING | {"stopped"} and r["key"] not in continued):
        trial_id = row["trial_id"]
        current = lambda: next(t for t in session.state(arguments.campaign)["trials"] if t["id"] == trial_id)
        if current()["status"] in {"queued", "running"}:
            session.command("trial.control", campaign_id, {"trial_id": trial_id, "action": "pause",
                                                           "expected_control_revision": current()["control_revision"]})
        while current()["status"] not in {"paused", "stopped"}:
            time.sleep(5)
        state, saved = saved_state(session, trial_id, row["key"])
        remaining = arguments.final_wall_seconds - state["elapsed_seconds"]
        print(f"{row['key']}: saved the state after {state['step']} evaluations and {state['elapsed_seconds']:.0f} s; "
              f"{remaining:.0f} s remain", flush=True)
        if remaining < 60:
            continue
        if current()["status"] != "stopped":
            session.command("trial.control", campaign_id, {"trial_id": trial_id, "action": "stop",
                                                           "expected_control_revision": current()["control_revision"]})
        method = next(m for m in METHODS if m["key"] == row["key"])
        trial = session.command("trial.create", campaign_id, {
            "task_id": task["id"], "algorithm": "flrl_ppo", "algorithm_config": {**method["config"], "warm_start_state": str(saved)},
            "seed": arguments.final_seed, "max_steps": arguments.final_evaluations, "wall_seconds": remaining,
            "hypothesis_id": row["hypothesis_id"],
            "question": f"Finalist run, continued: trial {trial_id} was stopped after {state['step']} evaluations and "
                        f"{state['elapsed_seconds']:.0f} s so that its learner state could go on under the current source "
                        f"(one solve per design instead of two) for the remaining {remaining:.0f} s of its three hours.",
        }, identity=f"{TAG}_final_{row['key']}_continued")
        print(f"{row['key']}: stopped {trial_id}, continued as {trial['trial_id']}", flush=True)


def extend_finals(session, arguments):
    """Give every finalist more wall-clock time, as a new trial that goes on from where its last one ended.

    The workspace restores the last trial's final saved state under the current source. It refuses
    unless that source has been shown to reproduce the trial's recorded results (evaluator.equivalence).
    """
    campaign_id, result = rows(session, arguments, "final")
    for key in dict.fromkeys(row["key"] for row in result):
        last = max((row for row in result if row["key"] == key), key=lambda row: row["part"])
        if last["part"] == len(PARTS):
            continue   # already extended; rerunning is safe
        if last["status"] in PENDING:
            raise SystemExit(f"{key}: trial {last['trial_id']} has not finished")
        trial = session.command("trial.continue", campaign_id, {"trial_id": last["trial_id"], "wall_seconds": arguments.extension_wall_seconds},
                                identity=f"{TAG}_final_{key}{PARTS[-1]}")
        print(f"{key}: extended from {last['trial_id']} as {trial['trial_id']}", flush=True)


def report(session, arguments):
    campaign_id, result = rows(session, arguments, "final")
    table = []
    for key in dict.fromkeys(row["key"] for row in result):
        parts = sorted((row for row in result if row["key"] == key), key=lambda row: row["part"])
        traces = [journal(session, part["trial_id"]) for part in parts]
        trace = [value for values in traces for value in values]
        best_at = lambda count: max(trace[:count]) if len(trace) >= count else None
        row = parts[-1]
        table.append({**{k: row[k] for k in ("key", "title", "status", "reason")},
                      "trial_ids": [part["trial_id"] for part in parts],
                      "evaluations": len(trace), "evaluations_by_part": [len(values) for values in traces],
                      "best": max(trace) if trace else None, "best_by_part": [max(values, default=None) for values in traces],
                      "elapsed": sum(part["elapsed"] or 0 for part in parts),
                      "updates": [part["updates"] for part in parts],
                      "best_after": {str(count): best_at(count) for count in (1024, 2048, 4096, 8192, 16384, 24576, 32768, 49152, 65536, 98304, 131072)},
                      "last_1024_mean": statistics.mean(trace[-1024:]) if trace else None})
    table.sort(key=lambda row: row["best"] or 0, reverse=True)
    (Path(session.journal) / "finalist-summary.json").write_text(json.dumps(table, indent=1))
    print(json.dumps(table, indent=1), flush=True)


def auto(arguments):
    """Screen -> shortlist -> long finalist runs -> summary. Safe to rerun: every command has a fixed identity."""
    with connect(arguments) as session:
        wait(session, arguments, "trial")
        finalize(session, arguments)
        finals(session, arguments)
        wait(session, arguments, "final")
        report(session, arguments)
    (Path(arguments.journal) / "DONE").write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--workspace", type=Path)
    group.add_argument("--workspace-url")
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--campaign")
    parser.add_argument("action", choices=["plan", "create", "status", "wait-screen", "finalize", "finals", "pause-finals", "resume-finals", "continue-finals", "extend-finals",
                                           "wait-finals", "report", "auto"])
    parser.add_argument("--evaluations", type=int, default=1024)
    parser.add_argument("--wall-seconds", type=float, default=1800)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--final-seed", type=int, default=100)
    parser.add_argument("--final-wall-seconds", type=float, default=10800)
    parser.add_argument("--final-evaluations", type=int, default=1000000)
    parser.add_argument("--extension-wall-seconds", type=float, default=10800)
    parser.add_argument("--poll", type=float, default=30)
    parser.add_argument("--trial-files", type=Path, help="The workspace's trials directory, when connected by URL on the same host")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--extra-config", default="{}", help="JSON merged into every method's settings (rehearsals only)")
    arguments = parser.parse_args()
    global TRIAL_FILES
    TRIAL_FILES = arguments.trial_files
    if arguments.action == "plan":
        print(json.dumps([{"key": m["key"], "title": m["title"], "config": m["config"]} for m in METHODS], indent=1))
    elif arguments.action in {"create", "status", "auto"}:
        {"create": create, "status": status, "auto": auto}[arguments.action](arguments)
    else:
        with connect(arguments) as session:
            {"wait-screen": lambda: wait(session, arguments, "trial"), "finalize": lambda: finalize(session, arguments),
             "finals": lambda: finals(session, arguments), "wait-finals": lambda: wait(session, arguments, "final"),
             "pause-finals": lambda: control(session, arguments, "pause"),
             "continue-finals": lambda: continue_finals(session, arguments),
             "extend-finals": lambda: extend_finals(session, arguments),
             "resume-finals": lambda: control(session, arguments, "resume"),
             "report": lambda: report(session, arguments)}[arguments.action]()


if __name__ == "__main__":
    main()
