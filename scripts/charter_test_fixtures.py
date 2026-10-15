"""Write frontend/tests/fixtures/reactor-charter.json from the real charter service.

The browser test of the New campaign page replays these views, so every value, text, finding and
difference it shows was computed by the service. The problem is the flow reactor of
tests/test_problem_charter.py. Run from the repository root after changing the charter service:

    .venv/bin/python scripts/charter_test_fixtures.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_problem_charter import reactor  # noqa: E402
from optimization_framework.execution.service import Workspace  # noqa: E402


def main():
    charters = Workspace(tempfile.mkdtemp()).charters
    draft = reactor()
    draft["quantities"]["pressure_bar"].update(origin="assumed", citation=None,
                                               note="The statement gives no back pressure; 5 bar is usual for this solvent")
    draft["questions"] = [{"id": "objective_basis", "question": "Is yield measured as isolated yield or by HPLC area?",
                           "options": ["Isolated yield", "HPLC area percent"], "about": ["isolated_yield"]}]
    record = charters.create(draft, source={"kind": "example", "id": "reactor_example", "name": "Flow reactor", "campaign": {
        "name": "Flow reactor study", "research_question": "Which ligand gives the best yield?", "compute_budget_seconds": 7200, "autonomy": "guided"}})
    cid = record["id"]
    out = {"id": cid, "initial": charters.view(cid)}
    flow = [{"op": "set", "path": "quantities.flow_rate_ml_min.value", "value": 4}]
    out["preview_flow4"] = charters.preview(cid, flow)
    charters.edit(cid, flow, expected_revision=1)
    out["saved"] = charters.view(cid)
    charters.answer(cid, "objective_basis", "Isolated yield", expected_revision=2)
    out["answered"] = charters.view(cid)
    charters.accept_assumptions(cid, ["pressure_bar"], expected_revision=3)
    out["ready"] = charters.view(cid)
    proposal = charters.propose(cid, "Make the residence time 200 s", [
        {"label": "Slower flow", "reason": "Keeps the reactor; the pump allows it",
         "changes": [{"op": "solve", "input": "flow_rate_ml_min", "target": "residence_time_s", "value": 200}]},
        {"label": "Larger reactor", "reason": "Keeps the flow rate",
         "changes": [{"op": "set", "path": "quantities.reactor_volume_ml.value", "expression": "200 * flow_rate_ml_min / 60"}]}], run_id="r1")
    out["proposed"], out["proposal_id"] = charters.view(cid), proposal["id"]
    charters.decide(proposal["id"], 0)
    out["accepted"] = charters.view(cid)
    out["confirmed"] = charters.confirm(cid, expected_revision=out["accepted"]["revision"])
    (ROOT / "frontend/tests/fixtures/reactor-charter.json").write_text(json.dumps(out, indent=1))
    print({key: (view["revision"], view["blocking"]) for key, view in out.items() if isinstance(view, dict) and "revision" in view and "blocking" in view})


if __name__ == "__main__":
    main()
