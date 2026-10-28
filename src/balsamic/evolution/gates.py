"""The evidence gates on a ledger row (roadmap V5): each gate's state, its evidence, and what would open it when closed.

Two transitions are gated for agents (decisions 14 to 16): a stop as inferior needs an adequate assessment (V2), and a
finalist needs the problem's fidelity check on the best score (V3), which every library entry needs too, the researcher's
included. A closed gate says why and what opens it: the missing runs, the check to run, or the researcher's waiver.
The stop outcome (V1) is the row's `stop`, with its evidence ids.
"""
from optimization_framework.campaigns import promotion
from optimization_framework.campaigns.assessment import waived

FIDELITY_WORDS = {"passed": "passed", "waived": "waived by the researcher", "failed": "failed", "not_checked": "not checked",
                  "not_required": "not required for this problem"}


def fidelity_of(workspace, hypothesis):
    """The fidelity state of the proposal's best score with its words, or None when its problem cannot be described here."""
    try:
        state = promotion.fidelity_state(workspace, hypothesis)
    except Exception:   # a problem this server cannot resolve declares nothing it could check
        return None
    names = ", ".join(check["recipe_id"] for check in state["checks"])
    return {**promotion.record(state), "checks": state["checks"],
            "words": FIDELITY_WORDS[state["state"]] + (f": {names}" if names else "")}


def assessment_gate(workspace, hypothesis, assessment, trial_ids):
    """Whether an agent may stop the proposal as inferior: open when adequately assessed or waived by the researcher."""
    if assessment["adequate"]:
        return {"gate": "assessment", "transition": "stop as inferior", "state": "open", "words": assessment["words"], "evidence_ids": trial_ids}
    waiver = waived(workspace, hypothesis)
    if waiver is not None:
        return {"gate": "assessment", "transition": "stop as inferior", "state": "waived", "words": assessment["words"],
                "waiver_id": waiver["id"], "evidence_ids": trial_ids}
    runs = assessment.get("missing_runs") or 0
    return {"gate": "assessment", "transition": "stop as inferior", "state": "closed", "words": assessment["words"], "evidence_ids": trial_ids,
            "why": "An agent's stop as inferior is refused: " + "; ".join(assessment["missing"]) + ".",
            "unlock": {"runs": f"Run the missing configurations or seeds ({runs} run{'s' if runs != 1 else ''}), or stop it as under-evaluated."
                       if runs else "Run its configurations to the horizon, or stop it as under-evaluated.",
                       "check": None, "waive": bool(trial_ids)}}


def fidelity_gate(fidelity):
    """Whether an agent may make the proposal a finalist, and anyone publish it: open when its best score passed, was
    waived by the researcher, or its problem declares no check."""
    evidence = [identity for check in fidelity["checks"] for identity in (check["validation_result_id"], check["waiver_id"]) if identity]
    base = {"gate": "fidelity", "transition": "finalist and library", "words": FIDELITY_WORDS[fidelity["state"]],
            "evidence_ids": ([fidelity["trial_id"]] if fidelity["trial_id"] else []) + evidence}
    if fidelity["state"] in promotion.OPEN:
        return {**base, "state": "waived" if fidelity["state"] == "waived" else "open"}
    if fidelity["trial_id"] is None:
        return {**base, "state": "closed", "why": "An agent cannot make it a finalist, nor anyone publish it: it has no measured run to check.",
                "unlock": {"runs": "Run it first.", "check": None, "waive": False}}
    pending = [check for check in fidelity["checks"] if check["state"] not in promotion.OPEN]
    failed = [check["recipe_id"] for check in pending if check["state"] == "failed"]
    unchecked = next((check for check in pending if check["state"] == "not_checked"), None)
    why = (f"{', '.join(failed)} failed on its best run: the score does not hold at higher fidelity." if failed else
           f"{', '.join(check['recipe_id'] for check in pending)} has not been checked on its best run (score {fidelity['score']}).")
    return {**base, "state": "closed", "why": "An agent cannot make it a finalist, nor anyone publish it. " + why,
            "unlock": {"runs": None, "waive": True,
                       "check": {"trial_id": fidelity["trial_id"], "recipe_id": unchecked["recipe_id"], "parameters": unchecked["parameters"]}
                       if unchecked else None}}


def gates(workspace, hypothesis, assessment, fidelity, trial_ids):
    """The row's gates. A stopped proposal has no stop left to gate; its fidelity still gates the library."""
    out = []
    if hypothesis.get("status") != "archived":
        out.append(assessment_gate(workspace, hypothesis, assessment, trial_ids))
    if fidelity is not None:
        out.append(fidelity_gate(fidelity))
    return out
