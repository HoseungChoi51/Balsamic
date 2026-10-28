"""A one-shot reviewer's input reads what the asker cites under the read tools' rule (roadmap T1 with V4): a locked
confirmation cell it cites reads as its status, and its result reaches the input only after release."""
import json

from optimization_framework.agents import calls

from test_locked_confirmation_reads import finish, locked, scores   # noqa: F401  (the fixture)


def test_a_locked_trial_the_asker_cites_is_withheld_from_the_reviewers_input(locked):
    workspace, campaign, lead, turn, prototype, cells, protocol = locked
    workspace.store.put("hypothesis", {"id": "h1", "campaign_id": campaign["id"], "title": "H1", "mechanism": "Coordinate search.",
                                       "algorithm": "coordinate", "requires_concept_review": True, "created_at": "2026-10-27T10:00:00+00:00"})
    cited = [cell["id"] for cell in cells] + [prototype["id"]]

    def evidence():
        content = calls.assemble(workspace, campaign["id"], "proposal_reviewer", "Is H1 worth confirming?", cited, "h1")
        return {item["record_id"]: item for item in content["assignment"]["evidence"]}, json.dumps(content)

    before, text = evidence()
    assert not scores(cells) & set(text.replace(",", " ").replace("}", " ").replace("]", " ").split())
    assert all(before[cell["id"]]["record"]["protected_evidence"] and "result" not in before[cell["id"]]["record"] for cell in cells)
    assert '"best_objective' in json.dumps(before[prototype["id"]]["record"])   # the prototype is not locked
    workspace.confirmations.release(protocol, authority="manager")
    after, text = evidence()
    assert all("protected_evidence" not in json.dumps(after[cell["id"]]["record"]) and '"best_objective' in json.dumps(after[cell["id"]]["record"])
               for cell in cells)
