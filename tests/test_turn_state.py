"""The state block and the static manifest (harness plan, Phase 2): a role's instructions and tools do not change with the
campaign; what changes reaches the next turn in the state block, which is saved on the run."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "balsamic"))
from support import QUADRATIC, activate_team, command, submitted  # noqa: E402

from optimization_framework.agents.tools import PiTools  # noqa: E402
from optimization_framework.agents.turn_state import CUT, HEADER, LIMIT  # noqa: E402
from optimization_framework.storage.sqlite import now  # noqa: E402

MAIN = "thread_main_demo"
FULL = {"objective": {"text": "Maximise efficiency"}, "knobs": {"text": "period 300-600 nm"}, "observables": {"text": "first-order efficiency"},
        "noise": {"text": "fabrication tolerance 5 nm"}, "constraints": {"text": "period below the wavelength"}, "confounders": {"text": "solver mesh"},
        "open_questions": {"text": "none remaining"}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from balsamic.app import create_app
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path / "workspace", start_workers=False)
    with TestClient(app) as client:
        workspace = app.state.workspace
        campaign = command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Design a deflector with higher efficiency"}, 0)["outcome"]["campaign"]
        command(client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": {"objective": FULL["objective"]}}, campaign["version"])
        lead = activate_team(client, workspace, campaign, monkeypatch)
        yield SimpleNamespace(client=client, workspace=workspace, lead=lead, tools=PiTools(workspace.pi), monkeypatch=monkeypatch)


def version(env):
    return env.workspace.store.get("demo", "campaign")["version"]


def say(env, text, thread=MAIN, page_agent=None):
    payload = {"message": text, **({"page_agent": page_agent} if page_agent else {"thread_id": thread})}
    receipt = command(env.client, "agent.message", "demo", payload, version(env), **({} if page_agent else {"origin": {"thread_id": thread}}))
    return submitted(env.workspace, "pi_run_" + receipt["id"])


def open_gate(env):
    from optimization_framework.problem_charter.service import KIND
    w = env.workspace
    command(env.client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": FULL}, version(env))
    env.monkeypatch.setattr(w.problem_imports, "create", lambda values: {"id": "import_1", "status": "collecting"})
    env.monkeypatch.setattr(w.problem_imports, "start", lambda import_id: None)
    command(env.client, "problem_note.adopt", "demo", {"note_id": "note_demo", "revision": w.store.get("note_demo", "problem_note")["current_revision"]}, version(env))
    w.store.put(KIND, {"id": "charter_x", "campaign_id": "demo", "status": "confirmed", "revision": 1, "charter": {}, "created_at": now()})
    note = w.store.get("note_demo", "problem_note"); note["charter_id"] = "charter_x"; w.store.put("problem_note", note)
    command(env.client, "campaign.update", "demo", {"tasks": [QUADRATIC]}, version(env))


def add_library_entry(env):
    from balsamic.library.signature import signature_of
    env.workspace.store.put("library_entry", {"id": "library_winner", "campaign_id": None, "signature": signature_of(env.workspace, "demo"),
        "strategy": {"title": "Winner", "algorithm": "random"}, "evidence": {"best_score": 0.91}, "origin_campaign_id": "earlier", "created_at": now()})


CHANGES = [
    ("gate closed -> open", open_gate),
    ("autopilot off -> on", lambda env: command(env.client, "autopilot.set", "demo", {"enabled": True, "compute_cap_seconds": 600, "rationale": "overnight"}, version(env))),
    ("a library entry added", add_library_entry),
    ("an experiment-rules revision", lambda env: command(env.client, "experiments.rules", "demo",
        {"max_concurrent": 2, "short_run_seconds": 900, "expected_revision": 0, "rationale": "GPU memory"}, version(env))),
    ("a resource-level change", lambda env: env.workspace.admission.set_level("aggressive", authority="researcher", reason="The other job ended")),
]


def team(env):
    """The lead's turn and a turn of each page agent whose instructions carried campaign state."""
    lead_run = say(env, "Where do we stand?")
    agents = {"lead": (env.lead, lead_run)}
    for role in ("experiment_operator", "resource_planner"):
        run = say(env, "Wait for my next message.", page_agent=role)
        agents[role] = (env.workspace.store.get(run["agent_id"], "agent_session"), run)
    return agents


def snapshot(env, agents):
    manifests = {role: env.tools.manifest(agent["id"], run["id"]) for role, (agent, run) in agents.items()}
    states = {role: env.tools.turn_state(agent["id"], run["id"])["text"] for role, (agent, run) in agents.items()}
    return manifests, states


def test_manifest_is_static_across_campaign_state(env):
    agents = team(env)
    before, _ = snapshot(env, agents)
    for label, change in CHANGES:
        change(env)
        after, _ = snapshot(env, agents)
        for role in agents:
            assert after[role]["instructions"] == before[role]["instructions"], f"{role}'s instructions changed with {label}"
            assert after[role]["tools"] == before[role]["tools"], f"{role}'s tools changed with {label}"


def test_turn_state_reflects_changes_immediately(env):
    agents = team(env)
    _, state = snapshot(env, agents)
    assert state["lead"].startswith(HEADER) and "Gate: closed. Next: complete the problem note (#note). Not written yet: Knobs" in state["lead"]
    assert "Autopilot: off." in state["lead"] and "Library" not in state["lead"] and "Turn: a request" in state["lead"]
    assert "experiment rules (revision 0)" in state["experiment_operator"] and "balanced resource level" in state["resource_planner"]
    rule = ("Compute thresholds (the researcher's): work up to 60 s starts freely; up to 5 min, it starts with a notice to them; "
            "longer than 5 min (the go-ahead threshold), and any coding workspace, waits for their go-ahead.")
    assert all(rule in text for text in state.values()), "every standing agent reads the researcher's compute thresholds"
    expected = {"gate closed -> open": ("lead", "Gate: open; the problem is defined."), "autopilot off -> on": ("lead", "Autopilot: on, cap 600 worker seconds"),
                "a library entry added": ("lead", "Library (strategies that won earlier campaigns of this problem): Winner (library_winner, best 0.91, same problem"),
                "an experiment-rules revision": ("experiment_operator", "Short runs are allotted less than 900 seconds"),
                "a resource-level change": ("resource_planner", "aggressive resource level")}
    for label, change in CHANGES:
        change(env)
        role, text = expected[label]
        assert text in snapshot(env, agents)[1][role], label
    assert "experiment rules (revision 1)" in snapshot(env, agents)[1]["experiment_operator"]


def test_thread_pins_reach_the_next_turn_in_that_thread_only(env):
    first = say(env, "Start here.")
    fork = command(env.client, "thread.fork", "demo", {"thread_id": MAIN, "message_id": "message_" + first["id"].removeprefix("pi_run_")},
                   version(env))["outcome"]["thread"]
    task_note = env.workspace.store.get("note_demo", "problem_note")
    command(env.client, "thread.pin", "demo", {"thread_id": MAIN, "record_id": task_note["id"]}, version(env), origin={"thread_id": MAIN})
    command(env.client, "thread.pin", "demo", {"thread_id": MAIN, "record_id": "demo", "excluded": True}, version(env), origin={"thread_id": MAIN})
    main_run, fork_run = say(env, "Use the note."), say(env, "Elsewhere.", thread=fork["id"])
    main_state = env.tools.turn_state(env.lead["id"], main_run["id"])["text"]
    fork_state = env.tools.turn_state(env.lead["id"], fork_run["id"])["text"]
    assert f"Thread: {MAIN}" in main_state and "Pinned in this thread (1):\n- note_demo · problem_note · Demo · drafting" in main_state
    assert "Records the researcher set aside in this thread (leave them out unless asked): demo" in main_state
    assert f"Thread: {fork['id']}" in fork_state and "note_demo" not in fork_state and "set aside" not in fork_state
    # The lead's own thread_pin reaches the same block.
    from optimization_framework.agents.tools import PiTools
    PiTools(env.workspace.pi).call(env.lead["id"], fork_run["id"], "pin", "thread_pin", {"record_id": "note_demo"})
    assert "Pinned in this thread (1):\n- note_demo" in env.tools.turn_state(env.lead["id"], fork_run["id"])["text"]


def test_turn_state_is_saved_on_the_run_and_capped(env):
    run = say(env, "Hello")
    state = env.tools.turn_state(env.lead["id"], run["id"])
    saved = env.workspace.store.get(run["id"], "agent_run")["turn_state"]
    assert saved["text"] == state["text"] and saved["hash"] == state["hash"] and saved["at"]
    assert env.tools.turn_state(env.lead["id"], run["id"])["hash"] == state["hash"], "the same state gives the same text"
    # Many long questions and pins: whole lines up to the cap, the rest named as left out; at most five questions and ten pins.
    for index in range(12):
        env.workspace.store.put("agent_question", {"id": f"question_{index:02d}", "campaign_id": "demo", "agent_id": env.lead["id"], "status": "pending",
                                                   "question": "Which tolerance? " + "x" * 400, "created_at": now()})
        env.workspace.store.put("hypothesis", {"id": f"hypothesis_{index:02d}", "campaign_id": "demo", "title": "Strategy " + "y" * 300, "status": "proposed", "created_at": now()})
        command(env.client, "thread.pin", "demo", {"thread_id": MAIN, "record_id": f"hypothesis_{index:02d}"}, version(env), origin={"thread_id": MAIN})
    text = env.tools.turn_state(env.lead["id"], run["id"])["text"]
    assert len(text) <= LIMIT and text.count("- question_") == 5 and "Open questions to the researcher (12):" in text
    assert text.count("- hypothesis_") <= 10
    # A long block is cut at a whole line and says so.
    from optimization_framework.agents.turn_state import cap
    cut = cap(["z" * 900] * 5)
    assert len(cut) <= LIMIT and cut.endswith(CUT) and cut.count("z" * 900) == 3
    # Assistants of one assignment get no block.
    child = env.tools.call(env.lead["id"], run["id"], "delegate", "delegate", {"role": "methodology_specialist", "objective": "Check", "request_key": "k"})
    assert env.tools.turn_state(child["agent_id"], submitted(env.workspace, child["run_id"])["id"])["text"] == ""


def test_the_gateway_serves_the_state_block_with_the_token(env, tmp_path):
    token = "t" * 40
    (tmp_path / "pi.token").write_text(token)
    env.monkeypatch.setenv("GRATING_PI_TOKEN_FILE", str(tmp_path / "pi.token"))
    run = say(env, "Hello")
    body = {"agent_id": env.lead["id"], "run_id": run["id"]}
    assert env.client.post("/api/internal/pi/turn_state", json=body).status_code == 401
    served = env.client.post("/api/internal/pi/turn_state", json=body, headers={"Authorization": "Bearer " + token}).json()
    assert served["text"].startswith(HEADER) and "Gate: closed" in served["text"]
    assert env.workspace.store.get(run["id"], "agent_run")["turn_state"]["hash"] == served["hash"]
    assert env.client.post("/api/internal/pi/turn_state", json={"agent_id": "import_agent_x", "run_id": "r"},
                           headers={"Authorization": "Bearer " + token}).json() == {"text": ""}
