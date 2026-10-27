"""Algorithm families in proposals and prompts (roadmap N15): a proposal names its family, a proposal without a method
records none instead of hillclimb, and the prompts ask for different families and for the problem's known results."""
import pytest

from support import command

MAIN = "thread_main_demo"
FAMILIES = ("exact", "solver", "constructive", "local_search", "learning", "hybrid")


def create(client, campaign, title, expect=200, **extra):
    return command(client, "hypothesis.create", campaign["id"], {"title": title, "mechanism": "m", "rationale": "r", **extra}, campaign["version"],
                   origin={"thread_id": MAIN}, expect=expect)


def test_a_proposal_stores_its_family_and_the_ledger_and_lineage_carry_it(client, workspace, campaign):
    dp = create(client, campaign, "Subset DP over due dates", family="exact", algorithm="random")["outcome"]["hypothesis"]
    assert workspace.store.get(dp["id"], "hypothesis")["family"] == "exact"
    other = create(client, campaign, "Plain restarts")["outcome"]["hypothesis"]
    assert other["family"] is None, "the family is left unstated, not guessed"
    body = client.get("/api/v1/campaigns/demo/evolution").json()
    assert {row["id"]: row["family"] for row in body["nodes"]} == {dp["id"]: "exact", other["id"]: None}
    assert {node["id"]: node["family"] for node in body["layout"]} == {dp["id"]: "exact", other["id"]: None}
    page = client.get("/api/v1/campaigns/demo/hypotheses").json()
    assert next(h for h in page["hypotheses"] if h["id"] == dp["id"])["family"] == "exact"
    assert client.get(f"/api/v1/hypotheses/{dp['id']}").json()["hypothesis"]["family"] == "exact"


def test_a_family_outside_the_list_is_refused_and_the_lead_can_correct_one(client, workspace, campaign):
    refused = create(client, campaign, "Quantum annealing", family="quantum", expect=None)
    assert refused.get("status") != "applied" and "family" in str(refused)
    made = create(client, campaign, "Greedy by ratio")["outcome"]["hypothesis"]
    receipt = command(client, "hypothesis.edit", campaign["id"], {"hypothesis_id": made["id"], "family": "constructive", "reason": "it is a greedy rule"},
                      workspace.store.get("demo", "campaign")["version"])
    assert receipt["outcome"]["fields"] == ["family"]
    assert workspace.store.get(made["id"], "hypothesis")["family"] == "constructive"


def test_a_proposal_without_a_method_is_unchosen_and_cannot_run_until_one_is_chosen(client, workspace, campaign):
    made = create(client, campaign, "Branch and bound", family="exact")["outcome"]["hypothesis"]
    assert made["algorithm"] == "unchosen" and made["algorithm_chosen"] is False and made["executable"] is False
    readiness = workspace.implementations.readiness(workspace.store.get(made["id"], "hypothesis"))
    assert readiness["state"] == "unchosen" and readiness["runnable"] is False and "choose one" in readiness["reason"]
    stated = create(client, campaign, "Stated unchosen", algorithm="unchosen")["outcome"]["hypothesis"]
    assert stated["algorithm_chosen"] is False, "writing unchosen is not a choice"
    refused = command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": made["id"], "worker_seconds": 30, "rationale": "a look"},
                      workspace.store.get("demo", "campaign")["version"], expect=None)
    assert "No method is chosen" in str(refused)
    command(client, "hypothesis.edit", campaign["id"], {"hypothesis_id": made["id"], "algorithm": "random"}, workspace.store.get("demo", "campaign")["version"])
    chosen = workspace.store.get(made["id"], "hypothesis")
    assert chosen["algorithm"] == "random" and chosen["algorithm_chosen"] is True
    assert workspace.implementations.readiness(chosen)["runnable"] is True
    outcome = command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": made["id"], "worker_seconds": 30, "rationale": "a look"},
                      workspace.store.get("demo", "campaign")["version"])["outcome"]
    assert outcome["how"] == "trial.create"


def test_the_diversify_prompt_asks_for_different_families_and_says_why_one_is_left_out():
    from balsamic.evolution.generate import PROMPTS
    prompt = PROMPTS["diversify"].format(count=3, parents="the recorded proposals")
    assert all(family in prompt for family in FAMILIES)
    assert "exact or problem-specific method" in prompt and "why a family is left out" in prompt and "set each one's family" in prompt


@pytest.mark.parametrize("role,procedure,needles", [
    ("lead", "proposal-fields", ("`family`", "`exact`", "`local_search`", "`unchosen`", "instance sizes")),
    ("lead", "problem-formulation", ("Known results", "complexity", "literature specialist", "with sources")),
])
def test_the_procedures_ask_for_the_family_and_the_known_results(workspace, role, procedure, needles):
    text = " ".join(workspace.procedures.read(role, procedure)["text"].split())
    assert all(needle in text for needle in needles), procedure
    assert "hillclimb" not in text


def test_the_specialists_judge_scale_and_look_up_known_algorithms():
    from pathlib import Path
    import optimization_framework.agents as agents
    roles = Path(agents.__file__).parent / "roles"
    methodology = (roles / "methodology_specialist.md").read_text()
    assert "family" in methodology and "grows with the instance sizes" in methodology and "search methods" not in methodology
    assert "known algorithms" in (roles / "literature_specialist.md").read_text()
