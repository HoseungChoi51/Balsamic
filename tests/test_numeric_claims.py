"""Numeric claim checks (roadmap K2): a number in a finding, a reply or a report claim that none of its evidence holds is
saved as unverified and shown as a badge; nothing is refused."""
import pytest

from optimization_framework.analysis.claims import Evidence, numbers, unverified
from optimization_framework.campaigns.findings import view

from test_compute_tool import finished_trial, lead_turn, receipt
from test_invariant_pins import lab, run, send  # noqa: F401  (the fixture and the command helper)
from test_page_agents import call, finish
from test_report_pipeline import app, scripted_model, start  # noqa: F401  (the fixture)


def written(text):
    return [number.text for number in numbers(text)]


def test_numbers_are_extracted_and_ids_dates_versions_links_code_and_counts_are_skipped():
    assert written("Rates of 0.005 and -3.2, 93.75% of 32,768 cells, 1.5e-3 and −4.1e+02, 12 runs, a 5% margin") == [
        "0.005", "-3.2", "93.75%", "32,768", "1.5e-3", "−4.1e+02", "12", "5%"]
    assert written("trial_ab12cd and H01 on 2026-10-27T12:30:00Z, at 14:05, v1.2 and 3.10.4, "
                   "[run](#experiments/trial_77), https://example.org/a?b=55 and `x = 0.77`, 3 seeds of 7") == []
    [number] = numbers("a mean of -0.250")
    assert number.value == -0.25 and number.tolerance == pytest.approx(0.0005) and number.signed


def test_a_number_matches_evidence_that_rounds_to_it_at_the_precision_written_or_as_a_percentage():
    evidence = Evidence({"result": {"best_objective": 0.9375, "evaluations": 32768}}, "a gain of -12.5% on 3 seeds")
    assert unverified("93.75%, 0.94, 0.9375, 94% and 32,768", evidence) == []
    assert unverified("0.95, 0.93 and 32,700", evidence) == ["0.95", "0.93", "32,700"]
    # A sign written must match; a number written without one may be a magnitude, as prose says "fell by 12.5%".
    assert unverified("fell by 12.5% (-0.125), not +12.5%", evidence) == ["+12.5%"]
    assert unverified("1/n is 0.0000305, or 3.05e-5", [1 / 32768]) == []


def test_a_finding_with_a_number_in_none_of_its_sources_is_saved_with_unverified_numbers(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "probe", "trial.create", run(task))
    [trial] = workspace.store.list("trial", cid)
    workspace.store.put("trial", {**trial, "status": "completed", "result": {"best_objective": 0.8231, "evaluations": 32768}})
    guessed = send(workspace, cid, "guessed", "finding.record", {"statement": "evidence", "source_ids": [trial["id"]],
        "content": "Coordinate search reached 0.823 in 32,768 evaluations; restarts would reach 0.95."})["outcome"]
    assert guessed["unverified_numbers"] == ["0.95"] and "compute" in guessed["note"]
    assert workspace.store.get(guessed["finding_id"], "manager_note")["unverified_numbers"] == ["0.95"]
    sourced = send(workspace, cid, "sourced", "finding.record", {"statement": "evidence", "source_ids": [trial["id"]],
        "content": "Coordinate search reached 0.82 in 32,768 evaluations."})["outcome"]
    assert "unverified_numbers" not in sourced and "unverified_numbers" not in workspace.store.get(sourced["finding_id"], "manager_note")
    # Files lists the badge with the finding.
    listed = {row["id"]: row for row in view(workspace.store, cid)["findings"]}
    assert listed[guessed["finding_id"]]["unverified_numbers"] == ["0.95"] and "unverified_numbers" not in listed[sourced["finding_id"]]
    # The researcher's own findings are theirs: not checked.
    own = send(workspace, cid, "own", "finding.record", {"source_ids": [trial["id"]], "content": "I expect 0.99."}, actor="researcher")["outcome"]
    assert "unverified_numbers" not in workspace.store.get(own["finding_id"], "manager_note")


def test_a_compute_receipt_of_the_request_sources_a_finding_and_the_reply_is_badged_on_its_message(tmp_path, monkeypatch):
    w, c, lead, turn = lead_turn(tmp_path, monkeypatch)
    trial = finished_trial(w, c)
    computed = call(w, lead, turn, 'compute', {'expression': '1 - best', 'values': {'best': {'record_id': trial['id'], 'pointer': '/best_objective'}}}, 'gap')
    assert computed['value'] == pytest.approx(0.18)
    recorded = call(w, lead, turn, 'campaign_command', {'operation': 'finding.record', 'request_key': 'gap', 'payload': {
        'statement': 'evidence', 'source_ids': [trial['id']], 'content': 'The best run, 0.82, is 0.18 from 1.'}}, 'record')
    finding = w.store.get(recorded['outcome']['finding_id'], 'manager_note')
    assert 'unverified_numbers' not in finding, finding
    # The reply: 0.82 from the record, 0.18 from compute; 0.25 from nowhere.
    reply = call(w, lead, turn, 'yield_work', {'disposition': 'complete', 'summary': 'Answered', 'evidence_ids': [trial['id']],
        'report': 'The best run scores 0.82, 0.18 from 1, about 0.25 better than the first run.'}, 'reply')
    assert reply['unverified_numbers'] == ['0.25']
    assert receipt(w, lead, turn, 'reply')['result']['unverified_numbers'] == ['0.25']
    finish(w, lead, turn, text='')
    [message] = [m for m in w.store.list('message', c['id']) if m.get('run_id') == turn['id']]
    assert message['content'].startswith('The best run scores 0.82') and message['unverified_numbers'] == ['0.25']


def test_a_report_claim_whose_number_is_in_no_supporting_receipt_is_listed_on_its_stage(app, monkeypatch):
    scripted_model(monkeypatch, claim="Annealing reached 0.71 within 1,000 evaluations, against 0.64 for DQN.")
    job = app.state.report_writer.start(evidence={"budgets": [100, 1000], "best": {"annealing": 0.7104}},
                                        brief="Annealing looks strong.", background=False)
    assert job["status"] == "completed", job.get("error")
    stage = app.state.workspace.store.get(job["id"] + "_investigate_2", "report_writer_stage")
    assert stage["unverified_numbers"] == {"c1": ["0.64"]}
    [claim] = app.state.reports.get(job["result_id"])["revision"]["editorial"]["claims"]
    assert claim["unverified_numbers"] == ["0.64"]
