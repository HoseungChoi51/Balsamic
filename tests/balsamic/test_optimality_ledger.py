"""Bounds and optimality on the Evolution page (roadmap N13): per task the best value, the best bound and the gap; a strategy
whose proof is checked is fully assessed and gets no more time; a proof nothing checks reads as a claim."""
from optimization_framework.storage.sqlite import now

from support import command

MAIN = "thread_main_demo"


def strategy(client, campaign, title):
    return command(client, "hypothesis.create", campaign["id"], {"title": title, "mechanism": "m", "rationale": "r", "algorithm": "random"},
                   campaign["version"], origin={"thread_id": MAIN})["outcome"]["hypothesis"]


def finished(workspace, task, hypothesis_id, algorithm, best, *, proved=False, bound=None, seed=0):
    result = {"best_objective": best, "evaluations": 10, "scientific_complete": True, "method_finished": proved, "status": "completed",
              **({"proved_optimal": True} if proved else {}), **({"best_bound": bound} if bound is not None else {})}
    return workspace.store.put("trial", {"id": f"trial_{hypothesis_id}_{seed}", "campaign_id": "demo", "task_id": task["id"], "algorithm": algorithm,
        "status": "completed", "seed": seed, "max_steps": 10, "wall_seconds": 60, "execution_seconds": 5, "hypothesis_id": hypothesis_id,
        "control_revision": 0, "created_at": now(), "problem": task["problem"], "result": result}, "trial.evidence_cataloged")


def test_the_evolution_page_shows_bound_gap_and_proof_and_a_checked_proof_ends_the_assessment(client, workspace, campaign):
    task = workspace.current_tasks("demo")[0]
    minimizing = task["problem"]["primary_objective"]["direction"] == "minimize"
    better, worse = (1.0, 2.0) if minimizing else (2.0, 1.0)
    exact, claimer, bounded, wrong = (strategy(client, campaign, title) for title in ("Enumerate", "Exact DP", "Branch and bound", "Greedy proof"))
    finished(workspace, task, exact["id"], "enumerate", better, proved=True)
    finished(workspace, task, claimer["id"], "random", better, proved=True, seed=1)
    finished(workspace, task, bounded["id"], "random", worse, bound=better, seed=2)
    finished(workspace, task, wrong["id"], "random", worse, proved=True, seed=3)
    body = client.get("/api/v1/campaigns/demo/evolution").json()
    summary, = body["optimality"]
    assert summary["task_id"] == task["id"] and summary["best_value"] == better and summary["best_bound"] == better and summary["gap"] == 0
    assert summary["optimum"] == {"value": better, "status": "checked", "claimed_by": ["enumerate", "random"], "checked_by": "enumerate"}
    rows = {row["id"]: row for row in body["nodes"]}
    assert rows[exact["id"]]["proof"]["status"] == "checked" and rows[exact["id"]]["proof"]["fully_assessed"] is True
    assert rows[claimer["id"]]["proof"]["checked_by"] == "enumerate" and rows[claimer["id"]]["stage"] == "extended"
    assert rows[wrong["id"]]["proof"]["status"] == "contradicted" and rows[wrong["id"]]["stage"] == "screening"
    assert rows[bounded["id"]]["proof"] is None
    # A checked proof on a deterministic evaluator: more time cannot change it, so an allocation is refused; replicating is not.
    refused = command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": exact["id"], "worker_seconds": 30, "rationale": "more"},
                      campaign["version"], expect=None)
    assert "proved" in str(refused) and "more time cannot improve it" in str(refused)
    command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": exact["id"], "worker_seconds": 30, "rationale": "another seed",
                                                            "replicate": True}, campaign["version"])


def test_a_proof_nothing_checks_reads_as_claimed_and_does_not_end_the_assessment(client, workspace, campaign):
    task = workspace.current_tasks("demo")[0]
    alone = strategy(client, campaign, "Exact DP")
    finished(workspace, task, alone["id"], "random", 3.0, proved=True)
    body = client.get("/api/v1/campaigns/demo/evolution").json()
    row = next(row for row in body["nodes"] if row["id"] == alone["id"])
    assert row["proof"]["status"] == "claimed" and row["proof"]["fully_assessed"] is False and row["stage"] == "screening"
    assert body["optimality"][0]["optimum"] == {"value": 3.0, "status": "claimed", "claimed_by": ["random"]}
