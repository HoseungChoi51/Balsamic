"""Read saved evidence into per-condition and combined reports; never run physics or training."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import statistics
import time

import numpy as np


PROFILES = ("P", "C", "S", "T", "H", "TH", "D", "A", "I", "G", "L")
LABELS = {"P": "Public learner reconstruction", "C": "Earlier combined learner",
          "S": "Double DQN plus low rate and clipping", "T": "Hard target every 2000 actions",
          "H": "Finite horizon with clock", "TH": "Finite horizon plus hard target",
          "D": "Double DQN", "A": "ReLU", "I": "Default initialization",
          "G": "Gradient clipping", "L": "Lower learning rate"}
COHORTS = ("P", "selected", "hc", "refine")
COHORT_LABELS = {"P": "Reconstructed P", "selected": "Selected DQN", "hc": "Restart HC", "refine": "Refined HC"}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value if isinstance(value, str) else json.dumps(value, indent=2, allow_nan=False)+"\n")
    temporary.replace(path)


def stats(values):
    return dict(n=len(values), mean=statistics.mean(values), minimum=min(values), maximum=max(values),
                median=statistics.median(values), sd=statistics.stdev(values) if len(values)>1 else None) if values else None


def number(value, digits=4):
    return f"{value:.{digits}f}" if value is not None else "—"


def mean_sd(value):
    if not value:
        return "—"
    return f"{value['mean']:.4f} ± {value['sd']:.4f}" if value["sd"] is not None else f"{value['mean']:.4f} (one seed)"


def link(target, output):
    return os.path.relpath(target, output)


def valid(row, order):
    return row.get("status") == "completed" and row.get("converged") and f"efficiency_F{order}" in row


def cohort(rows, seeds, order):
    group = sorted([r for r in rows if valid(r, order)], key=lambda r: r["seed"])
    return dict(complete=[r["seed"] for r in group] == list(seeds), seeds=[r["seed"] for r in group],
                efficiency=stats([r[f"efficiency_F{order}"]*100 for r in group]),
                full_action_runs=sum(bool(r.get("summary", {}).get("completed")) for r in group),
                capped_seeds=[r["seed"] for r in group if r.get("budget_stop_reason") == "wall_time_limit"],
                extreme_q_runs=sum(r.get("stability_diagnostic") == "persistent_extreme_q" for r in group),
                inference=stats([r["final_inference_mean"]*100 for r in group if "final_inference_mean" in r]),
                worker_hours=stats([r["logical_worker_seconds"]/3600 for r in group]),
                search_solves=stats([r["logical_search_solves"] for r in group]))


def comparison_ready(status, groups, references, errors):
    return (status.get("stage") == "finished" and not status.get("active") and not errors
            and all(groups[k]["complete"] for k in COHORTS)
            and bool(references) and all(r.get("converged") for r in references))


def audit_run(root, job, row, inputs):
    """Validate saved configuration, budget, final geometry, and convergence evidence."""
    run = Path(job["run"])
    inputs[str(run / "outcome.json")] = digest(run / "outcome.json")
    assert row["id"] == job["id"] and row["seed"] == job["seed"]
    assert Path(row["source_module"]) == root / "source/src/dqn_meent/__init__.py"
    if row["status"] != "completed" or job["kind"] == "references":
        return
    assert read(run / "config.json") == job["config"]
    summary = read(run / "summary.json")
    assert summary == row["summary"]
    if job["kind"] == "train":
        step = summary["steps"]
        if summary["completed"]:
            assert step == job["budget"]
        else:
            assert row["budget_stop_reason"] == "wall_time_limit" and 0 < step < job["budget"]
            assert job["runtime_cap_active"] and not row["action_budget_complete"]
            assert row["wall_seconds_since_launch"] <= job["max_dqn_seconds"] + 1
        if job.get("max_dqn_seconds"):
            assert job["deadline"]-job["launched_epoch"] <= job["max_dqn_seconds"] + 1e-6
            assert row["wall_seconds_since_launch"] <= job["max_dqn_seconds"] + 1
    else:
        assert summary["completed"] and summary["evaluation_requests"] == job["budget"]
        step = job["budget"]*(2 if job["kind"] == "refine" else 1)
    snapshot = read(run / "snapshots" / f"{step:09d}.json")
    design = np.load(run / "best_design.npy", allow_pickle=False)
    assert design.shape == (64,) and set(design.tolist()) <= {0, 1}
    assert design.tolist() == read(run / "best_design.json")["design"]
    saved = snapshot["search"] if job["kind"] == "train" else snapshot
    assert saved["design"] == design.tolist()
    assert abs(saved["best_F40"]-summary["best_efficiency"]) < 1e-10
    validation = read(run / "final-validation.json")
    orders = validation["results"]
    expected = [160,320] if job["phase"] == "development" else [40,160,320,480]
    assert [r["order"] for r in orders] == expected
    delta = abs(orders[-1]["efficiency"]-orders[-2]["efficiency"])
    assert validation["converged"] == row["converged"] == (delta <= .0001)
    for entry in orders:
        assert abs(entry["efficiency"]-row[f"efficiency_F{entry['order']}"]) < 1e-12
    if job["kind"] == "refine":
        provenance = read(run / "provenance.json")
        prefix = root / "prefixes" / f"hc-s{job['seed']}"
        assert Path(provenance["source_run"]) == prefix
        assert provenance["source_snapshot"]["design"] == read(prefix / "best_design.json")["design"]
        assert int(provenance["upstream_cost_at_start"]["step"]) == job["budget"]
    for name in ("config.json", "summary.json", "best_design.npy", "final-validation.json"):
        inputs[str(run / name)] = digest(run / name)
    row["validation_delta_pp"] = delta*100


def summarize_case(root, supplement):
    root = root.resolve()
    manifest = read(root / "manifest.json")
    condition = manifest.get("condition", dict(wavelength_nm=1100, angle_deg=70))
    key = f"wl{condition['wavelength_nm']}-ang{condition['angle_deg']}"
    paper = next(c for c in supplement["conditions"] if all(c[k] == v for k,v in condition.items()))
    status = read(root / "status.json", {})
    selection = read(root / "selection.json", {})
    selected = selection.get("selected_profile")
    hashes = read(root / "source-sha256.json")
    inputs = {str(root / "manifest.json"): digest(root / "manifest.json")}
    errors = []
    for path, expected in hashes.items():
        if digest(root / "source" / path) != expected:
            errors.append(f"Frozen source hash mismatch: {path}")
    if hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest() != manifest["source_sha256"]:
        errors.append("Frozen source manifest hash mismatch")
    jobs = [read(p) for p in sorted((root / "jobs").glob("*.json"))]
    rows = []
    for job in jobs:
        row = read(Path(job["run"]) / "outcome.json")
        if row is None:
            continue
        try:
            assert job["config"]["physics"] == manifest["profile_configs"]["P"]["physics"]
            assert job["config"]["training"]["seed"] == job["seed"]
            audit_run(root, job, row, inputs)
        except Exception as error:
            errors.append(f"{job['id']}: {type(error).__name__}: {error}")
        summary = row.get("summary", {})
        upstream = read(Path(row["run"]) / "provenance.json", {}).get("upstream_cost_at_start", {}) if job["kind"] == "refine" else {}
        row["logical_worker_seconds"] = row.get("elapsed_seconds", 0)+float(upstream.get("elapsed_seconds", 0))
        row["logical_search_solves"] = summary.get("solver_calls", 0)+int(upstream.get("solver_calls", 0))
        row["search_requests"] = summary.get("evaluations", summary.get("evaluation_requests", 0))
        row["logical_requests"] = row["search_requests"]+int(upstream.get("step", 0))
        row["validation_cost"] = read(Path(row["run"]) / "validation-cost.json", {})
        rows.append(row)
    ref_job = next((r for r in rows if r["kind"] == "references" and r["status"] == "completed"), None)
    refs = read(root / "reference-results.json", []) if ref_job else []
    if refs:
        inputs[str(root / "reference-results.json")] = digest(root / "reference-results.json")
        if len(refs) != ref_job["reference_count"]:
            errors.append("Reference validation count differs from its completed outcome")
    reference = next((r for r in refs if r["method"] == "paper"), None)
    for r in refs:
        path = Path(r["path"])
        orders = r["results"]
        delta = abs(orders[-1]["efficiency"]-orders[-2]["efficiency"])
        if r["converged"] != (delta <= .0001) or any(abs(s["efficiency"]-r[f"efficiency_F{s['order']}"])>1e-12 for s in orders):
            errors.append(f"Inconsistent saved reference validation: {path}")
        if r.get("sha256") and digest(path) != r["sha256"]:
            errors.append(f"Reference geometry hash mismatch: {path}")
        if r["method"] == "paper" and np.load(path).tolist() != [int(c) for c in "".join(paper["design_rows"])]:
            errors.append("Published geometry differs from Table S3 transcription")
    groups = {}
    grouped_rows = {}
    for label in COHORTS:
        if label in {"P", "selected"}:
            profile = "P" if label == "P" else selected
            subset = [r for r in rows if r["phase"] == "confirmation" and r["profile"] == profile]
        else:
            subset = [r for r in rows if r["kind"] == label]
        grouped_rows[label] = subset
        groups[label] = cohort(subset, manifest["confirmation_seeds"], 480)
    development = {p: cohort([r for r in rows if r["phase"] == "development" and r["profile"] == p],
                             manifest["development_seeds"], 320) for p in PROFILES}
    if selected:
        candidates=[]
        for profile,value in development.items():
            if value["complete"]:
                elapsed=sum(r.get("elapsed_seconds",0) for r in rows if r["phase"]=="development" and r["profile"]==profile)
                candidates.append((value["efficiency"]["median"],value["efficiency"]["maximum"],elapsed,profile))
        if candidates:
            highest=max(c[0] for c in candidates)
            tied=[c for c in candidates if c[0]>=highest-.05]
            expected=sorted(tied,key=lambda c:(-c[1],c[2],c[3]))[0][3]
            if expected != selected:
                errors.append(f"Selection differs from saved development rule: expected {expected}, recorded {selected}")
        for row in rows:
            if row["phase"] == "confirmation" and datetime.fromisoformat(row["started_utc"]) < datetime.fromisoformat(selection["selected_utc"]):
                errors.append("Confirmation started before profile selection was frozen")
        inputs[str(root / "selection.json")] = digest(root / "selection.json")
    complete = comparison_ready(status, groups, refs, errors) and not manifest["smoke"]
    prior_hc = [r["efficiency_F480"]*100 for r in refs if r["method"] != "paper" and r.get("converged")]
    current_hc = [r["efficiency_F480"]*100 for r in rows if r["kind"] in {"hc", "refine"} and valid(r,480)]
    benchmark = max(prior_hc+current_hc) if prior_hc or current_hc else None
    gains = [r["efficiency_F480"]*100-benchmark for r in grouped_rows["selected"] if valid(r,480)] if benchmark is not None else []
    decision = dict(complete=complete, benchmark_percent=benchmark, margin_feasible=benchmark is not None and benchmark+.5<100,
                    selected_seeds_above_margin=sum(x>.5 for x in gains), selected_seeds_above_tolerance=sum(x>.01 for x in gains),
                    verdict="pending" if status.get("stage") != "finished" else "inconclusive_execution")
    if complete:
        decision["verdict"] = ("margin_exceeds_physical_headroom" if not decision["margin_feasible"] else
            "reproducible_rl_advantage" if decision["selected_seeds_above_margin"]>=3 else
            "isolated_improvement" if decision["selected_seeds_above_margin"] else "no_demonstrated_reproducible_advantage")
        saved = read(root / "decision.json", {})
        if saved and saved["verdict"] != decision["verdict"]:
            errors.append("Derived verdict differs from the campaign decision")
            decision.update(complete=False, verdict="audit_failed")
    rotations = set()
    for row in grouped_rows["refine"]:
        if valid(row,480):
            design = np.load(Path(row["run"])/"best_design.npy").tolist()
            rotations.add(min(tuple(design[i:]+design[:i]) for i in range(len(design))))
    train_rows = [r for r in rows if r["kind"] == "train"]
    totals = dict(completed_worker_hours=sum(r.get("elapsed_seconds",0) for r in rows)/3600,
        development_worker_hours=sum(r.get("elapsed_seconds",0) for r in rows if r["phase"]=="development")/3600,
        confirmation_worker_hours=sum(r.get("elapsed_seconds",0) for r in rows if r["phase"]=="confirmation")/3600,
        search_requests=sum(r["search_requests"] for r in rows),
        search_solves=sum(r.get("summary",{}).get("solver_calls",0) for r in rows),
        validation_solves=sum(r["validation_cost"].get("rcwa_calls",0) for r in rows),
        full_dqn_runs=sum(r.get("summary",{}).get("completed",False) for r in train_rows),
        capped_dqn_runs=sum(r.get("budget_stop_reason")=="wall_time_limit" and r["status"]=="completed" for r in train_rows))
    return dict(key=key, root=str(root), label=f"{condition['wavelength_nm']} nm / {condition['angle_deg']}°",
        condition=condition, status=status, manifest=manifest, selected=selected, paper=paper, paper_reference=reference,
        groups=groups, development=development, decision=decision, totals=totals, rows=rows,
        outcome_counts=dict(Counter(r["status"] for r in rows)), current_job_count=len(jobs),
        final_validation_delta_pp=max([r["validation_delta_pp"] for r in rows if r["phase"]!="development" and "validation_delta_pp" in r], default=None),
        refined_same_up_to_translation=len(rotations)==1 and groups["refine"]["complete"],
        audit=dict(errors=errors, passed=not errors, outcome_records=len(rows), frozen_files=len(hashes), input_sha256=inputs))


def crossing_evidence(case):
    """Measured checkpoints, without treating absent crossings as zero time."""
    selected = case["groups"]["selected"]["efficiency"]
    if not case["decision"]["complete"] or selected is None:
        return []
    # Compare at the same Fourier order using fresh selected endpoints.
    threshold = max(r["efficiency_F320"]*100 for r in case["rows"] if r["phase"]=="confirmation" and r["profile"]==case["selected"] and valid(r,480))
    result = []
    for row in case["rows"]:
        if row["kind"] not in {"hc","refine"} or not valid(row,480):
            continue
        run = Path(row["run"])
        snapshots = [read(p) for p in sorted((run/"snapshots").glob("*.json")) if p.stem.isdigit()]
        prefix_seconds = 0
        if row["kind"] == "refine":
            provenance = read(run/"provenance.json")["upstream_cost_at_start"]
            prefix_seconds = float(provenance["elapsed_seconds"])
            parent = Path(case["root"])/"control"/f"hc-s{row['seed']}"/"snapshots"
            snapshots = [read(p) for p in sorted(parent.glob("*.json")) if p.stem.isdigit() and int(p.stem)<=int(provenance["step"])] + snapshots
        first = next((s for s in snapshots if s["validation"]["converged"] and s["validation"]["efficiency_F320"]*100>threshold+.01), None)
        if first:
            seconds = float(first["cost"]["elapsed_seconds"])
            if row["kind"]=="refine" and first["step"]>int(provenance["step"]):
                seconds += prefix_seconds
            result.append(dict(method=row["kind"],seed=row["seed"],requests=first["step"],minutes=seconds/60,
                               efficiency_percent=first["validation"]["efficiency_F320"]*100,threshold_percent=threshold))
    return result


def case_report(case, output):
    directory = output/case["key"]
    directory.mkdir(parents=True, exist_ok=True)
    root = Path(case["root"])
    g, d, p = case["groups"], case["decision"], case["paper"]
    complete = d["complete"]
    state = "completed comparison" if complete else "queued" if not case["rows"] else "interim evidence only"
    lines = [f"# DQN and hill climbing at {case['condition']['wavelength_nm']} nm and {case['condition']['angle_deg']} degrees", "",
        f"Updated {datetime.now(timezone.utc).isoformat()}. Status: **{state}**. "
        f"Saved outcomes: {len(case['rows'])}/{case['current_job_count']} currently scheduled jobs. "
        + ("Confirmation jobs are scheduled after development; this denominator may still increase. "
           if case["status"].get("stage") != "finished" else "") +
        f"Outcome statuses: {case['outcome_counts']}.", ""]
    if complete:
        selected = g["selected"]["efficiency"]
        refined = g["refine"]["efficiency"]
        lines += [f"Selected profile **{case['selected']}** reached **{mean_sd(selected)}%**, best **{selected['maximum']:.4f}%**, "
                  f"over five fresh seeds. Refined HC reached **{mean_sd(refined)}%**, best **{refined['maximum']:.4f}%**. "
                  f"Selected DQN minus refined HC is **{selected['mean']-refined['mean']:+.4f} pp** in mean efficiency. "
                  f"The strongest HC benchmark is **{d['benchmark_percent']:.4f}%**; "
                  f"{d['selected_seeds_above_margin']}/5 selected seeds exceed it by 0.5 pp and "
                  f"{d['selected_seeds_above_tolerance']}/5 exceed it by 0.01 pp. "
                  f"Bounded verdict: **{d['verdict']}**.", ""]
        if selected["maximum"] < min(g["hc"]["efficiency"]["minimum"], refined["minimum"])-.01:
            lines += ["Every fresh HC/control result exceeds every fresh selected-DQN result by more than the numerical tolerance. "
                      "The ordering therefore does not depend on the 0.5 pp success margin or on one exceptional HC seed.", ""]
    else:
        lines += ["**No final DQN versus HC conclusion is available for this case.** Completed development runs "
                  "are exploratory; they cannot replace the selected profile's five fresh confirmation seeds. "
                  "The report updates as new saved outcomes arrive.", ""]
    if not case["audit"]["passed"]:
        lines += ["**Evidence audit failed; numerical comparisons are provisional.** " + "; ".join(case["audit"]["errors"]), ""]
    lines += ["## Published results and fresh confirmation", "",
        "| Method | Valid seeds | Mean ± sample SD (%) | Maximum (%) | Full scheduled budgets |",
        "|---|---:|---:|---:|---:|",
        f"| Published DQN | 3 | {p['mean_percent'][-1]} ± {p['std_percent'][-1]} | {p['max_percent'][-1]} | Reported 2 million |"]
    ref = case["paper_reference"]
    if ref:
        lines.append(f"| Published geometry reevaluated at F480 | 1 geometry | — | {ref['efficiency_F480']*100:.4f} | — |")
    for name in COHORTS:
        if name=="selected" and case["selected"]=="P":
            continue
        v = g[name]
        name_label = COHORT_LABELS[name] + (f" ({case['selected']})" if name=="selected" and case["selected"] else "")
        values = v["efficiency"]
        lines.append(f"| {name_label} | {len(v['seeds'])}/5 | {mean_sd(values)} | "
                     f"{number(values['maximum'] if values else None)} | {v['full_action_runs']}/{len(v['seeds'])} |")
    lines += ["", "All new results above use F480; SD is across independent search seeds. A partial cohort is "
              "explicitly counted and is not a completed comparison. Published statistics use three runs and an "
              "unspecified SD convention. P and selected DQN share one confirmation cohort if P was selected.", ""]
    if ref:
        lines += [f"The published geometry differs from its Table S2 peak by "
                  f"**{ref['efficiency_F480']*100-p['max_percent'][-1]:+.4f} pp** in this optical model. "
                  "This checks the design and forward model, not the learning procedure.", ""]
    if g["P"]["complete"]:
        v = g["P"]["efficiency"]
        lines += [f"Fresh P differs from the reported DQN by **{v['mean']-p['mean_percent'][-1]:+.4f} pp** in mean "
                  f"and **{v['maximum']-p['max_percent'][-1]:+.4f} pp** in maximum. "
                  f"P's sample SD is **{v['sd']:.4f} pp**, versus the paper's reported **{p['std_percent'][-1]} pp**. "
                  "These are descriptive comparisons, not a test of equality to an unknown paper population.", ""]
    if g["refine"]["complete"]:
        v = g["refine"]["efficiency"]
        lines += [f"The completed refined-HC cohort has a mean **{v['mean']-p['max_percent'][-1]:+.4f} pp** "
                  f"relative to the paper's reported DQN maximum. The paper's two greedy maxima were "
                  f"{p['max_percent'][0]}% and {p['max_percent'][1]}%; its adjoint/GLOnet maxima were "
                  f"{p['max_percent'][2]}% and {p['max_percent'][3]}%. Those historical optimizers were not rerun. "
                  "Restart HC and perturbation-based refinement are stronger controls than the paper's particular greedy implementations.", ""]
        if case["refined_same_up_to_translation"]:
            lines += ["All five refined-HC geometries are identical up to a cyclic shift. This explains the nearly "
                      "identical efficiencies but does not establish global optimality.", ""]
    if d["benchmark_percent"] is not None:
        lines += [f"The primary target is **>{d['benchmark_percent']+.5:.4f}%**. " +
                  ("It remains below 100%, so the original margin is physically possible (attainability is unproved)." if d["margin_feasible"] else
                   "It is at or above 100%, making this margin unusable. The actual gaps and 0.01 pp crossings remain the relevant descriptive evidence."), ""]
    lines += ["## Development ablations and implementation differences", "",
        "| Profile | Change | Valid seeds | Mean ± sample SD at F320 (%) | Maximum (%) | Capped seeds | Extreme Q flags |",
        "|---|---|---:|---:|---:|---|---:|"]
    for profile,v in case["development"].items():
        s = v["efficiency"]
        lines.append(f"| {profile} | {LABELS[profile]} | {len(v['seeds'])}/3 | {mean_sd(s)} | "
                     f"{number(s['maximum'] if s else None)} | {v['capped_seeds']} | {v['extreme_q_runs']}/{len(v['seeds'])} |")
    lines += ["", "Development values use F320 and remain separate from fresh confirmation. Profiles with fewer "
              "than three valid seeds cannot yet support the planned development comparison. Completed time-limited "
              "runs remain eligible under the authorized effort rule; they are not full-action replications.", ""]
    pdev = case["development"]["P"]
    if pdev["complete"]:
        for profile in ("C","T","H","D","I"):
            v = case["development"][profile]
            if v["complete"]:
                lines += [f"{profile} ({LABELS[profile]}) changes the development mean relative to P by "
                          f"**{v['efficiency']['mean']-pdev['efficiency']['mean']:+.4f} pp**. "
                          f"Persistent extreme-Q flags: {v['extreme_q_runs']}/3, versus {pdev['extreme_q_runs']}/3 for P. "
                          + ("C changes multiple learner choices, so this gap cannot be attributed to one mechanism." if profile=="C" else
                             "T changes both target mixing and update frequency, so it cannot identify those effects separately." if profile=="T" else
                             "This is a small development comparison, not independent confirmation of a universal ranking."), ""]
    lines += ["P follows the pinned released learner on MEENT: the release is not a verified copy of the original "
              "2022 execution, and MEENT replaces RETICOLO. Matching the published geometry cannot guarantee "
              "identical solver behavior throughout training. Absence of extreme Q inflation does not establish "
              "Bellman convergence. The cubed-efficiency cumulative reward also differs from directly maximizing "
              "the best geometry encountered.", "", "## Effort and policy quality", "",
              "| Cohort | Mean logical worker hours | Mean actual search solves | Final policy episode-best mean range at F160 (%) |",
              "|---|---:|---:|---:|"]
    for name in COHORTS:
        if name=="selected" and case["selected"]=="P": continue
        v = g[name]
        inf = v["inference"]
        lines.append(f"| {COHORT_LABELS[name]} | {number(v['worker_hours']['mean'] if v['worker_hours'] else None,3)} | "
                     f"{number(v['search_solves']['mean'] if v['search_solves'] else None,0)} | "
                     + (f"{inf['minimum']:.4f}–{inf['maximum']:.4f} |" if inf else "— |"))
    t = case["totals"]
    lines += ["", f"Recorded saved outcomes used **{t['completed_worker_hours']:.2f} summed worker hours**, "
              f"including {t['development_worker_hours']:.2f} DQN development hours and "
              f"{t['confirmation_worker_hours']:.2f} DQN confirmation hours. DQN full-action completions: "
              f"**{t['full_dqn_runs']}**; valid time-capped completions: **{t['capped_dqn_runs']}**. "
              f"Search requests: {t['search_requests']:,}; actual search solves: {t['search_solves']:,}; "
              f"validation solves: {t['validation_solves']:,}. Active-run expenditure is omitted from these totals.", "",
              "Refined-HC method costs include its own HC prefix; physical totals charge each shared prefix once. "
              "DQN targets two million actions plus reset evaluations; HC has two million logical search requests. "
              "Time includes instrumentation and concurrent execution. These are not equal-wall-time trials, "
              "and full-budget runtime alone does not measure time to comparable quality. Frozen-policy inference "
              "is independent of training and cannot be substituted for the best search discovery.", ""]
    if case["manifest"].get("max_dqn_seconds"):
        lines += ["The three-hour allowance includes final diagnostics; the full-budget exploration schedule is "
                  "retained. A truncated P run tests bounded effort, not failure of the full paper procedure. "
                  "Full and capped seeds are identified in the per-run evidence CSV.", ""]
    crossings = crossing_evidence(case)
    if complete:
        lines += ["## HC time to the selected DQN quality", "",
                  "These are the first saved checkpoints exceeding the best fresh selected-DQN endpoint at F320 "
                  "by more than 0.01 pp. They bound crossing time from above; absent crossings are not zero time. "
                  "HC and refined HC share the first-million-request prefix within each seed, so a crossing "
                  "in that prefix appears in both logical methods and is not two independent observations.", "",
                  "| Method | Seed | Logical requests | Recorded minutes | F320 efficiency (%) |",
                  "|---|---:|---:|---:|---:|"]
        for r in crossings:
            lines.append(f"| {r['method']} | {r['seed']} | {r['requests']:,} | {r['minutes']:.2f} | {r['efficiency_percent']:.4f} |")
        lines += ["", f"Observed crossings: {len(crossings)}/10 HC control trajectories.", ""]
    lines += ["## Evidence and figures", "",
              f"Audit: **{'passed' if case['audit']['passed'] else 'failed'}**, covering {case['audit']['outcome_records']} saved outcomes "
              f"and {case['audit']['frozen_files']} frozen source hashes. Largest saved final F320/F480 change: "
              f"**{number(case['final_validation_delta_pp'],6)} pp**. Required tolerance: 0.01 pp. "
              "An audit of saved convergence evidence is not an independent electromagnetic solver check.", "",
              "[Machine-readable evidence](evidence.json) · [Per-run CSV](per-run.csv).", "",
              f"[Frozen experiment protocol]({link(root/'source/docs/replication-extension-20260930.md' if case['manifest'].get('max_dqn_seconds') else root/'source/docs/replication-ablation-1100nm-70deg.md',directory)}) "
              f"· [Raw campaign]({link(root,directory)}).", ""]
    figures = root / ("paper-style" if case["manifest"].get("max_dqn_seconds") else "paper-style-20260930")
    if (figures/"README.md").exists():
        lines += [f"[Individual paper-format figures]({link(figures/'README.md',directory)}) · "
                  f"[Combined figure PDF]({link(figures/'all-methods.pdf',directory)}).", ""]
    else:
        lines += ["Individual paper-format figures will be linked after the campaign finishes rendering them.", ""]
    write(directory/"report.md", "\n".join(lines))
    write(directory/"evidence.json", {k:v for k,v in case.items() if k!="rows"} | dict(crossings=crossings))
    with (directory/"per-run.csv").open("w",newline="") as stream:
        columns=["id","phase","profile","kind","seed","status","converged","efficiency_F320","efficiency_F480",
                 "actions","action_budget_complete","budget_stop_reason","logical_requests","logical_search_solves","logical_worker_seconds","run"]
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction="ignore")
        writer.writeheader()
        for r in case["rows"]:
            writer.writerow(dict(r, actions=r.get("summary",{}).get("steps"),
                action_budget_complete=r.get("summary",{}).get("completed"),
                budget_stop_reason=r.get("budget_stop_reason","action_budget" if r.get("summary",{}).get("completed") else "")))


def aggregate(cases):
    finished = [c for c in cases if c["decision"]["complete"] and c["audit"]["passed"]]
    gaps = [c["groups"]["selected"]["efficiency"]["mean"]-c["groups"]["refine"]["efficiency"]["mean"] for c in finished]
    return dict(complete_cases=[c["key"] for c in finished], planned_cases=len(cases), all_cases_complete=len(finished)==len(cases),
        reproducible_rl_wins=sum(c["decision"]["verdict"]=="reproducible_rl_advantage" for c in finished),
        margin_infeasible_cases=sum(not c["decision"]["margin_feasible"] for c in finished),
        selected_mean_below_refined_cases=sum(g<-.01 for g in gaps),
        selected_mean_above_refined_cases=sum(g>.01 for g in gaps),
        equal_case_mean_gap_pp=statistics.mean(gaps) if len(gaps)>1 else None,
        selected_vs_refined_mean_gaps_pp=gaps)


def plot(cases, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(13,8),layout="constrained")
    for ax,c in zip(axes.flat,cases,strict=True):
        ax.set_title(c["label"],fontsize=13)
        if not c["decision"]["complete"]:
            ax.axis("off")
            message="Queued" if not c["rows"] else "Fresh confirmation pending"
            if c["status"].get("stage")=="finished": message="Incomplete or unresolved evidence"
            ax.text(.5,.55,message,transform=ax.transAxes,ha="center",fontsize=13)
            ax.text(.5,.4,"Excluded from combined conclusions",transform=ax.transAxes,ha="center",fontsize=10)
            continue
        for y,(name,color) in enumerate(zip(COHORTS,("#7f6f49","#26759d","#499579","#9c5c46"))):
            profile="P" if name=="P" else c["selected"]
            rows=[r for r in c["rows"] if valid(r,480) and
                  ((name in {"P","selected"} and r["phase"]=="confirmation" and r["profile"]==profile) or
                   (name in {"hc","refine"} and r["kind"]==name))]
            vals=[r["efficiency_F480"]*100 for r in rows]
            v=c["groups"][name]["efficiency"]
            ax.scatter(vals,y+np.linspace(-.12,.12,len(vals)),s=28,color=color,zorder=3)
            ax.errorbar(v["mean"],y,xerr=v["sd"],fmt="D",color="black",ms=4,capsize=3,zorder=4)
        if c["paper_reference"]:
            ax.axvline(c["paper_reference"]["efficiency_F480"]*100,color="#777",ls="--",lw=1)
        ax.set(yticks=range(4),yticklabels=["Reconstructed P",f"Selected {c['selected']}","Restart HC","Refined HC"],
               ylim=(3.6,-.6),xlabel="Absolute +1 efficiency at F480 (%)")
        ax.grid(axis="x",alpha=.2)
    fig.suptitle("Completed replication evidence by condition\nDots: five fresh seeds; diamonds: mean ± sample SD; dashed: published geometry",fontsize=13)
    for ext in ("png","pdf"): fig.savefig(output/f"case-comparison.{ext}",dpi=170)
    plt.close(fig)


def suite_report(cases, output):
    combined=aggregate(cases)
    complete=[c for c in cases if c["key"] in combined["complete_cases"]]
    lines=["# Combined analysis of DQN and hill climbing replication", "",
        f"Updated {datetime.now(timezone.utc).isoformat()}. **{len(complete)}/{len(cases)} conditions have completed, "
        "audited fresh-seed comparisons.** This includes the original 1100 nm / 70° study and the three authorized extensions. "
        "Each case has its own report; unfinished cases are excluded from combined conclusions.", ""]
    if complete:
        lines += [f"Across the {len(complete)} completed conditions, **{combined['reproducible_rl_wins']}** demonstrate "
                  "the prescribed reproducible DQN advantage over the strongest HC benchmark. "
                  f"Selected-DQN mean efficiency is below refined HC by more than 0.01 pp in "
                  f"**{combined['selected_mean_below_refined_cases']}/{len(complete)}** completed conditions. "
                  f"The 0.5 pp margin is physically unusable in {combined['margin_infeasible_cases']} completed conditions.", ""]
    if not combined["all_cases_complete"]:
        lines += ["**The comprehensive four-condition conclusion is pending.** A completed baseline or development "
                  "cohort is evidence about that cohort, not a completed DQN confirmation. Counts below are descriptive "
                  "and must not be presented as a four-case success or failure rate.", ""]
    elif combined["selected_mean_below_refined_cases"]==len(cases) and combined["reproducible_rl_wins"]==0:
        lines += ["**For all four studied configurations, the tested DQN revisions do not justify their added "
                  "complexity through higher final design quality over refined HC at the allowed effort.** "
                  "This supports choosing HC for these fixed optimization tasks. It does not refute the "
                  "paper's feasible geometries, all RL approaches, or the full-action procedure in cases "
                  "where DQN was time-limited. Full-budget timing and time to comparable quality remain "
                  "separate questions in the case reports.", ""]
    elif combined["all_cases_complete"]:
        wins=[c["label"] for c in complete if c["decision"]["verdict"]=="reproducible_rl_advantage"]
        lines += [f"**The completed evidence is condition dependent.** The prescribed reproducible RL advantage "
                  f"occurs in: {', '.join(wins) if wins else 'none of the four cases'}. "
                  "Smaller observed gains, stability changes, and cases limited by the physical ceiling are "
                  "reported separately. Neither one winning condition nor one failed condition establishes "
                  "a universal optimizer ranking.", ""]
    lines += ["## Case by case evidence", "",
        "| Condition | Comparison status | P mean / best (%) | Selected mean / best (%) | Refined HC mean / best (%) | Selected mean minus refined HC (pp) | Report |",
        "|---|---|---:|---:|---:|---:|---|"]
    for c in cases:
        ready=c["decision"]["complete"]
        def cell(key):
            v=c["groups"][key]["efficiency"]
            prefix=f"{c['selected']}: " if key=="selected" else ""
            return f"{prefix}{v['mean']:.4f} / {v['maximum']:.4f}" if ready and v else "Pending"
        a,b=c["groups"]["selected"]["efficiency"],c["groups"]["refine"]["efficiency"]
        gap=a["mean"]-b["mean"] if ready else None
        state="Complete" if ready else "Queued" if not c["rows"] else "Interim"
        lines.append(f"| {c['label']} | {state} | {cell('P')} | {cell('selected')} | {cell('refine')} | "
                     f"{number(gap)} | [Analysis]({c['key']}/report.md) |")
    lines += ["", "![Completed comparisons and explicitly pending cases](case-comparison.png)", "",
              "[Download the comparison PDF](case-comparison.pdf). Axes differ by condition. P and selected markers "
              "refer to the same cohort if P is selected; they do not add independent replicates.", ""]
    if combined["equal_case_mean_gap_pp"] is not None:
        lines += [f"Giving each completed condition equal weight, the selected-DQN minus refined-HC mean gap is "
                  f"**{combined['equal_case_mean_gap_pp']:+.4f} pp**. This is a descriptive average of within-case "
                  "differences; the chosen conditions are not a random sample, and their seeds are not pooled "
                  "into one significance test.", ""]
    lines += ["## Provisional evidence from unfinished cases", ""]
    for c in cases:
        if c["decision"]["complete"] or not c["rows"]: continue
        p=c["development"]["P"]
        refined=c["groups"]["refine"]
        text=f"**{c['label']}:** {len(c['rows'])} saved outcomes; profile selection " + (f"is {c['selected']}. " if c["selected"] else "is pending. ")
        if p["complete"]:
            text+=f"Completed P development: {mean_sd(p['efficiency'])}% at F320; best {p['efficiency']['maximum']:.4f}%. "
        if refined["complete"]:
            text+=f"Completed refined HC: {mean_sd(refined['efficiency'])}% at F480; best {refined['efficiency']['maximum']:.4f}%. "
        lines += [text+"These values are not added to the completed-case comparison above.", ""]
    lines += ["## What this says about the paper", "",
        "Assess three claims separately. Published-geometry reevaluation tests optical feasibility. Fresh P "
        "tests whether the reconstructed learner attains the paper's efficiency and repeatability. Selected "
        "DQN versus fresh HC tests practical value over stronger conventional controls. Success on the first "
        "does not imply either of the others.", "",
        "The original 1100/70 case was already an exception to the paper's maximum-efficiency advantage: "
        "its DQN maximum was 78.5%, while adjoint and GLOnet were each 84%. The added 1100/50, 900/70, "
        "and 1000/70 conditions address reported DQN wins. Conclusions about those wins require their "
        "completed confirmation evidence. The source is the repository's Table S2 transcription and the "
        "original paper mapping; historical adjoint/GLOnet optimizers were not rerun.", "",
        "A strong HC result above the published DQN is evidence that the paper's particular greedy controls "
        "did not establish superiority over all conventional search. It does not falsify the published "
        "geometry or prove that RL cannot improve on HC. This experiment concerns one fixed design task per "
        "condition; it does not measure transfer or amortized policy reuse across tasks.", "",
        "## Implementation and budget effects", "",
        "The table below compares completed three-seed development cohorts with P within each condition. "
        "Gaps are mean F320 efficiency differences in percentage points. A completed development cohort in "
        "an interim case remains exploratory and does not enter the final cross-case verdict.", "",
        "| Condition | Case status | P mean (%) | C minus P | T minus P | H minus P | D minus P | I minus P |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for c in cases:
        base=c["development"]["P"]
        if not base["complete"]: continue
        differences=[]
        for profile in ("C","T","H","D","I"):
            value=c["development"][profile]
            differences.append(f"{value['efficiency']['mean']-base['efficiency']['mean']:+.4f}" if value["complete"] else "Pending")
        lines.append(f"| {c['label']} | {'Complete' if c['decision']['complete'] else 'Interim'} | "
                     f"{base['efficiency']['mean']:.4f} | "+" | ".join(differences)+" |")
    lines += ["", "Large negative C-minus-P gaps together with Q inflation in C support the inference that "
        "the earlier combined implementation was a poor proxy for the released learner. This does not "
        "attribute the entire gap to one change. T jointly changes target mixing and update frequency; "
        "C jointly changes several choices. Allowed time caps can also make action counts unequal; the "
        "individual reports identify affected seeds.", "",
        "The original study completed every two-million-action DQN run without truncation. Extensions allow "
        "two million actions or three hours per DQN, with final diagnostics inside that cap. Full and capped "
        "runs remain separately labeled, and the exploration schedule is not compressed. A capped failure "
        "cannot alone reject the paper's full-budget procedure. HC keeps its two-million-request budget. "
        "Runtime, solver calls, and the much larger total DQN tuning effort must accompany efficiency claims; "
        "these are not equal-wall-time or equal-total-tuning-cost comparisons.", "",
        "## Evidence and update process", "",
        "[Combined evidence JSON](evidence.json) contains saved results and their audit status. Every case includes "
        "raw-source hashes, numerical checks, per-seed results, costs, policy inference, and links to its "
        "individual paper-format figures when available. Analysis reads completed outcomes and runs no "
        "training, optimization, or electromagnetic solves. It updates after new outcomes or figure bundles appear.", ""]
    write(output/"report.md", "\n".join(lines))
    write(output/"evidence.json",dict(updated_utc=datetime.now(timezone.utc).isoformat(), aggregate=combined,
        cases=[{k:v for k,v in c.items() if k not in {"rows","manifest"}} for c in cases],
        new_training_runs=0,new_search_runs=0,new_physics_solves=0))
    plot(cases,output)
    return combined


def fingerprint(roots):
    entries=[]
    for root in roots:
        paths=[root/n for n in ("manifest.json","selection.json","results.json","decision.json","figure-status.json")]
        for p in (root/"jobs").glob("*.json"):
            job=read(p)
            outcome=Path(job["run"])/"outcome.json"
            if outcome.exists(): paths.append(outcome)
        for p in paths:
            if p.exists(): entries.append((str(p),p.stat().st_mtime_ns,p.stat().st_size))
        state=read(root/"status.json",{})
        entries.append((str(root),state.get("stage")))
    return hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--extension",type=Path)
    parser.add_argument("--original",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--watch",action="store_true")
    args=parser.parse_args()
    repository=args.repository.resolve()
    extension=(args.extension or repository/"runs/replication-extension-20260930").resolve()
    original=(args.original or repository/"runs/replication-20260920-1100nm-70deg").resolve()
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR",str(output/"matplotlib-cache"))
    lock=(output/"analysis.lock").open("w")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    roots=[original,*[extension/name for name in ("wl1100-ang50","wl900-ang70","wl1000-ang70")]]
    supplement=read(original/"source/data/paper_2022_supplement.json")
    previous=read(output/"watch-status.json",{})
    old=previous.get("fingerprint") if previous.get("analyzer_sha256")==digest(__file__) else None
    while True:
        signature=fingerprint(roots)
        batch=read(extension/"status.json",{})
        terminal=batch.get("stage") in {"completed","finished_with_missing_results","interrupted"}
        if signature!=old or not args.watch:
            cases=[summarize_case(root,supplement) for root in roots]
            for case in cases: case_report(case,output)
            combined=suite_report(cases,output)
            old=signature
            print(json.dumps(dict(updated_utc=datetime.now(timezone.utc).isoformat(),complete_cases=combined["complete_cases"],
                outcomes={c['key']:len(c['rows']) for c in cases},audit_errors={c['key']:c['audit']['errors'] for c in cases})),flush=True)
        write(output/"watch-status.json",dict(checked_utc=datetime.now(timezone.utc).isoformat(),fingerprint=old,
            stage="finished" if terminal else "watching" if args.watch else "snapshot",batch_stage=batch.get("stage"),
            analyzer_sha256=digest(__file__)))
        if not args.watch or terminal: break
        time.sleep(60)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
