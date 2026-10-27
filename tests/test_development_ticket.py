"""The work ticket (roadmap H4): an agent opens a coding workspace on a `development_ticket` (the proposals with their METHODS
keys, the charter revision, acceptance tests as runnable files, protected tests kept on the host, the budget and the walls of
the request's mandate, and the house rules), checked as a commission's specification is; prepare() writes it into the worktree
as TASK.md, AGENTS.md, CLAUDE.md and .balsamic/spec.json and never writes a protected test there; and the implementation
lead reviews a delivery by its diff against the generated base."""
import json

import pytest

from optimization_framework.agents.development import DEVELOPMENT_INSTRUCTIONS
from optimization_framework.agents.development_runtime import DockerWorkspace
from optimization_framework.agents.development_ticket import FILES, PROTECTED, diff_summary, files
from optimization_framework.agents.tools import PiTools
from optimization_framework.campaigns import compute_consent, mandates
from optimization_framework.storage.sqlite import now
from test_development_generated_library import LIBRARY, charter_lab, opened  # noqa: F401  (the fixture)
from test_library_install import git
from test_pi_development_workspaces import TICKET, notices, outgoing, setup  # noqa: F401  (the fixture)
from test_problem_charter_scaffold import METHODS, OBJECTIVE

# DEVELOPMENT_INSTRUCTIONS at F4 (b86523f), before what the house rules say moved to AGENTS.md.
F4_WORDS, F4_CHARACTERS = 377, 2552
SECRET = "assert hidden_value == 42  # the protected check"
LEAD_TEST = "libraries/oven_trays/tests/test_acceptance.py"
OWN_TICKET = {"acceptance_tests": [{"path": LEAD_TEST, "content": "def test_four_trays():\n    assert True\n"}],
              "protected_tests": [{"name": "test_hidden.py", "content": "def test_hidden():\n    " + SECRET + "\n"}]}


def go_ahead(workspace, cid, **plan):
    return compute_consent.grant(workspace, {"id": "decision_go", "campaign_id": cid},
                                 {"plan": "Implement the methods", "wall_seconds": 3600, "worker_seconds": 1800, "coding_workspaces": 1, **plan})


def everything_under(directory):
    return "\n".join(path.read_text(errors="replace") for path in directory.rglob("*") if path.is_file())


def test_prepare_writes_the_four_files_for_a_ticket_and_a_second_prepare_keeps_the_coders_edits(charter_lab, tmp_path, monkeypatch):
    workspace, cid, development, driver, charter = charter_lab
    go_ahead(workspace, cid)
    record = opened(development, cid, hypothesis_ids=["hypothesis_greedy"], ticket=OWN_TICKET)
    ticket = workspace.store.get(record["ticket_id"], "development_ticket")
    assert [row["source"] for row in ticket["acceptance_tests"]] == ["generated"] * 3 + ["implementation lead"]
    assert ticket["protected_tests"] == ["test_hidden.py"] and SECRET not in json.dumps(ticket)
    # The protected test is kept on the host with the workspace, as validation outside the box (H6) reads it.
    [kept] = workspace.store.list(PROTECTED, cid)
    assert (kept["workspace_id"], kept["name"]) == (record["id"], "test_hidden.py") and SECRET in kept["content"]

    # The Docker driver's prepare, its worktree already made (no Docker here), writes the ticket beside the library.
    for name in ("GRATING_PI_AUTH_FILE", "GRATING_FLRL_REFERENCE"):
        monkeypatch.setenv(name, str(tmp_path / "absent"))
    box = DockerWorkspace(tmp_path / "boxes")
    repo = box.root(record) / "work" / "repo"
    (box.root(record) / "work" / "git").mkdir(parents=True)
    (repo / ".git").mkdir(parents=True)
    library = development.generated_library(record)[0]
    written = files(ticket)
    assert set(written) == {*FILES, LEAD_TEST}
    box.prepare(record, development.brief(record), [], library=library, ticket=written)
    task, agents, claude = ((repo / name).read_text() for name in ("TASK.md", "AGENTS.md", "CLAUDE.md"))
    spec = json.loads((repo / ".balsamic/spec.json").read_text())
    assert agents == claude == ticket["house_rules"] and "## What not to touch" in agents
    assert f"`{LIBRARY}/tests/test_contract.py` (generated)" in task and f"`{LEAD_TEST}` (implementation lead)" in task
    assert "`test_hidden.py`" in task and "Its METHODS key: `greedy_trays`" in task
    assert spec["id"] == ticket["id"] and spec["house_rules"] == "AGENTS.md"
    assert [row["path"] for row in spec["acceptance_tests"]][-1] == LEAD_TEST and "content" not in spec["acceptance_tests"][-1]
    assert (repo / LEAD_TEST).read_text() == OWN_TICKET["acceptance_tests"][0]["content"]
    assert (repo / LIBRARY / "oven_trays/data.py").exists()
    # Protected tests are never written there: not their source, not anywhere in the box's directories.
    assert SECRET not in everything_under(box.root(record))

    # The coder edits the ticket and the lead's test and removes CLAUDE.md; preparing again keeps its edits and restores the file.
    (repo / "TASK.md").write_text("# my notes\n")
    (repo / LEAD_TEST).write_text("def test_four_trays():\n    pass\n")
    (repo / "CLAUDE.md").unlink()
    box.prepare(record, development.brief(record), [], library=library, ticket=written)
    assert (repo / "TASK.md").read_text() == "# my notes\n" and (repo / LEAD_TEST).read_text().endswith("pass\n")
    assert (repo / "CLAUDE.md").read_text() == agents

    # Through a sync, the workspace's own driver gets the same four files, and the session brief is what AGENTS.md does not say.
    development.sync(cid)
    assert {name: (driver.repo(record) / name).read_bytes() for name in FILES} == {name: written[name] for name in FILES}
    brief = (driver.root(record) / "brief.md").read_text()
    assert "TASK.md" in brief and "AGENTS.md" in brief and "implementation-manifest.json" not in brief
    assert SECRET not in everything_under(driver.root(record))


def test_the_house_rules_say_what_the_instructions_no_longer_do_and_the_instructions_are_shorter(charter_lab):
    workspace, cid, development, driver, _ = charter_lab
    record = opened(development, cid)
    rules = workspace.store.get(record["ticket_id"], "development_ticket")["house_rules"]
    for step in ("## What to build", "oven_trays/objective.py", "oven_trays/methods.py", "## How to run the tests", "uv run pytest libraries/oven_trays",
                 "balsamic-workspace check", "## How to submit", "implementation-manifest.json", "Raise the version", "campaign_submit",
                 "balsamic-workspace submit", "The delivery report", "## What not to touch", "`charter.json` and `oven_trays/data.py`",
                 "docs/optimizer-plugins.md", "optimizer_v1"):
        assert step in rules, step
    # What moved to AGENTS.md left the coding agent's own instructions, which are now shorter than at F4.
    for moved in ("objective.py", "methods.py", "implementation-manifest.json", "Raise the version", "The delivery report", "optimizer_v1"):
        assert moved not in DEVELOPMENT_INSTRUCTIONS
    assert len(DEVELOPMENT_INSTRUCTIONS.split()) < F4_WORDS and len(DEVELOPMENT_INSTRUCTIONS) < F4_CHARACTERS
    assert "TASK.md" in DEVELOPMENT_INSTRUCTIONS and "AGENTS.md" in DEVELOPMENT_INSTRUCTIONS


def test_a_ticket_without_acceptance_tests_is_refused_by_check_self_contained(setup):
    workspace, campaign, development, driver = setup
    cid = campaign["id"]
    go_ahead(workspace, cid)
    # A campaign without a charter has no generated library, so no generated tests: the implementation lead must name one.
    request = {"hypothesis_id": "hypothesis_dev", "objective": "Implement", "request_key": "bare"}
    bare = development.ticket({"id": "development_x", "campaign_id": cid, "hypothesis_id": "hypothesis_dev", "title": "Test method",
                               "objective": "Implement", "evidence_ids": []})
    assert bare["acceptance_tests"] == []
    with pytest.raises(ValueError, match="names no acceptance tests"):
        workspace.implementations.check_self_contained(bare)
    with pytest.raises(ValueError, match="names no acceptance tests"):
        development.create(cid, request, actor="lead")
    assert workspace.store.list("development_workspace", cid) == [] and workspace.store.list("development_ticket", cid) == []
    assert workspace.store.list("compute_consent", cid)[0]["used_workspaces"] == 0   # nothing was charged
    # A ticket naming a record the coding agent cannot read is refused; given as evidence, it is readable.
    artifact = "artifact_pi_tool_86f8269f855f5ffdb0b6c927c295bc7c"
    workspace.store.put("agent_artifact", {"id": artifact, "campaign_id": cid, "content": "The step rule"})
    cited = {**request, "objective": f"Implement the step rule of {artifact}", "ticket": TICKET}
    with pytest.raises(ValueError, match=f"names campaign records \\({artifact}\\) that the coding agent cannot read"):
        development.create(cid, cited, actor="lead")
    record = development.create(cid, {**cited, "evidence_ids": [artifact]}, actor="lead")
    ticket = workspace.store.get(record["ticket_id"], "development_ticket")
    assert ticket["acceptance_tests"] == [{"path": "libraries/test-method/tests/test_contract.py", "source": "implementation lead"}]
    assert ticket["test_command"] == "uv run pytest libraries/test-method/tests/test_contract.py"


def test_the_researchers_own_workspace_and_a_charter_campaigns_need_no_tests_from_the_lead(charter_lab):
    workspace, cid, development, driver, _ = charter_lab
    go_ahead(workspace, cid)
    # The generated library's own tests (F1, F3) are the acceptance tests of a campaign made from a charter.
    record = development.create(cid, {"hypothesis_id": "hypothesis_dev", "objective": "Implement", "request_key": "lead"}, actor="lead")
    ticket = workspace.store.get(record["ticket_id"], "development_ticket")
    assert [row["path"] for row in ticket["acceptance_tests"]] == [f"{LIBRARY}/tests/test_{name}.py" for name in ("contract", "methods", "problem")]
    with pytest.raises(ValueError, match="is a file of the generated library"):
        development.create(cid, {"hypothesis_id": "hypothesis_greedy", "objective": "Implement", "request_key": "clash",
                                 "ticket": {"acceptance_tests": [{"path": f"{LIBRARY}/tests/test_contract.py", "content": "x = 1\n"}]}})
    with pytest.raises(ValueError, match="is Balsamic's"):
        development.create(cid, {"hypothesis_id": "hypothesis_greedy", "objective": "Implement", "request_key": "reserved",
                                 "ticket": {"acceptance_tests": [{"path": ".balsamic/test_x.py"}]}})
    # The researcher's own workspace is opened on a ticket too, and is not refused for its tests.
    workspace.store.put("campaign", {k: v for k, v in workspace.store.get(cid, "campaign").items() if k != "charter"})
    own = development.create(cid, {"hypothesis_id": "hypothesis_greedy", "objective": "Implement", "request_key": "own"})
    assert workspace.store.get(own["ticket_id"], "development_ticket")["acceptance_tests"] == []


def test_the_ticket_carries_the_budget_deadline_and_walls_of_the_requests_mandate(setup):
    workspace, campaign, development, driver = setup
    cid = campaign["id"]
    root = {"thread_id": "thread_main", "message_id": "message_ask", "run_id": "run_ask"}
    decision = workspace.store.put("decision", {"id": "decision_screen", "campaign_id": cid, "title": "Screen", "question": "Screen",
        "status": "resolved", "requested_by": "lead", "audience": "researcher", "created_at": now(), "request_root": root,
        "approval_request": {"kind": "mandate", "template": "screen", "plan": "Build the method", "wall_seconds": 5400, "worker_seconds": 900,
                             "coding_workspaces": 1, "hypothesis_ids": ["hypothesis_dev"], "egress_hosts": ["github.com"],
                             "model_usd": 2.5, "deadline_minutes": 600}})
    outcome = mandates.approve(workspace, decision)
    record = development.create(cid, {"hypothesis_id": "hypothesis_dev", "objective": "Implement", "request_key": "walls", "ticket": TICKET,
                                      "cpu_budget_seconds": 7200}, actor="lead", root=root, asked=root)
    ticket = workspace.store.get(record["ticket_id"], "development_ticket")
    assert ticket["budget"] == {"mandate_id": outcome["mandate_id"], "template": "screen", "consent_id": outcome["consent_id"],
                                "worker_seconds": 900, "model_usd": 2.5, "cpu_seconds": 7200}
    assert ticket["deadline"]["wall_seconds"] == 5400 and ticket["deadline"]["at"]
    # The hosts the researcher approved with the mandate are the workspace's when it names none (H5's allowlist).
    assert record["egress"]["named"] == ["github.com"] and ticket["egress"] == record["egress"] and ticket["limits"] == record["limits"]
    development.sync(cid)
    task = (driver.repo(record) / "TASK.md").read_text()
    for line in ("allows 15 min of worker time", "Model spend: $2.50", "CPU allowance: 2 h", "Deadline: 90 min of wall time",
                 "The request's deadline:", "Limits: 4 CPUs, 8 GB of memory, no GPU.", "github.com; nothing else is reachable"):
        assert line in task, line


def test_implementation_workspace_inspect_returns_the_diff_summary(charter_lab):
    workspace, cid, development, driver, _ = charter_lab
    go_ahead(workspace, cid)
    lead_id = workspace.pi.configuration(cid)["lead_id"]
    opener = workspace.pi.page_agent(cid, "implementation_lead")
    record = development.create(cid, {"hypothesis_id": "hypothesis_dev", "objective": "Implement", "request_key": "review", "ticket": OWN_TICKET},
                                actor="lead", opener={"agent_id": opener["id"], "role": opener["role"]})
    development.sync(cid)
    repo = driver.repo(record)
    # The coder fills the two files it writes, changes the harness and a line of the lead's test, adds a module, and delivers.
    (repo / LIBRARY / "oven_trays/objective.py").write_text(OBJECTIVE)
    (repo / LIBRARY / "oven_trays/methods.py").write_text(METHODS)
    with (repo / LIBRARY / "oven_trays/harness.py").open("a") as harness:
        harness.write("# the coder's note\n")
    (repo / LEAD_TEST).write_text("def test_four_trays():\n    pass\n")
    (repo / LIBRARY / "oven_trays/helpers.py").write_text("def helper():\n    return 1\n")
    git("init", "-q", cwd=repo)
    git("add", ".", cwd=repo)
    git("-c", "user.name=coder", "-c", "user.email=coder@lab", "commit", "-q", "-m", "Delivery", cwd=repo)
    commit = git("rev-parse", "HEAD", cwd=repo)
    git("clone", "-q", "--bare", str(repo), str(driver.root(record) / "work" / "git"), cwd=repo.parent)
    outgoing(driver, record, "deliver", "submission", {"commit": commit, "manifest_path": "implementation-manifest.json"})
    development.sync(cid)

    run = {"id": "run_review", "origin": {"thread_id": "thread_main"}}
    inspected = PiTools(workspace.pi)._execute(opener, run, "implementation_workspace_inspect", {"workspace_id": record["id"]}, "call_review")
    review, diff = inspected["review"], inspected["review"]["diff"]
    assert review["commit"] == commit and review["protected_tests"] == ["test_hidden.py"] and review["host_validation"] is None
    assert (diff["library"], diff["source"]) == ("oven_trays", "commit")
    rows = {row["path"].removeprefix(LIBRARY + "/"): row for row in diff["files"]}
    assert set(rows) == {"oven_trays/objective.py", "oven_trays/methods.py", "oven_trays/harness.py", "oven_trays/helpers.py", "tests/test_acceptance.py"}
    assert (rows["oven_trays/harness.py"]["status"], rows["oven_trays/harness.py"]["lines_added"], rows["oven_trays/harness.py"]["lines_removed"]) == ("changed", 1, 0)
    assert (rows["oven_trays/helpers.py"]["status"], rows["oven_trays/helpers.py"]["lines_added"], rows["oven_trays/helpers.py"]["base"]) == ("added", 2, None)
    assert (rows["tests/test_acceptance.py"]["lines_added"], rows["tests/test_acceptance.py"]["lines_removed"], rows["tests/test_acceptance.py"]["base"]) == (1, 1, "ticket")
    assert diff["files_changed"] == 5 and diff["lines_added"] == sum(row["lines_added"] for row in rows.values())
    # Generated files touched: not the two the coder fills; the charter's fixed files untouched; the lead's test touched.
    assert diff["generated_files_touched"] == [f"{LIBRARY}/oven_trays/harness.py"] and diff["fixed_files_touched"] == []
    assert diff["acceptance_tests_touched"] == [LEAD_TEST]
    # The ticket the review is against, without the texts it holds; and the delivery's notice already says what it changed.
    assert inspected["ticket"]["protected_tests"] == ["test_hidden.py"] and inspected["ticket"]["library"] == f"{LIBRARY}/"
    [notice] = [run for run in notices(workspace, cid, opener["id"]) if "submitted as" in run["input"]]
    assert "It changes 5 files of oven_trays" in notice["input"] and "oven_trays/harness.py" in notice["input"]
    assert not [run for run in notices(workspace, cid, lead_id) if "submitted as" in run["input"]]


def test_the_diff_summary_compares_by_hash_where_the_generated_bytes_are_gone():
    base = {"lib/a.py": b"one\ntwo\n"}
    hashes = {"lib/a.py": "x", "lib/b.py": __import__("hashlib").sha256(b"kept\n").hexdigest(), "lib/c.py": "y"}
    summary = diff_summary(base, {"lib/a.py": b"one\nthree\n", "lib/b.py": b"kept\n", "lib/c.py": b"changed\n", "lib/d.bin": b"\xff\xfe"},
                           hashes=hashes, ticket={"library": {"filled": [], "fixed": ["lib/c.py"]}, "acceptance_tests": []})
    rows = {row["path"]: row for row in summary["files"]}
    assert set(rows) == {"lib/a.py", "lib/c.py", "lib/d.bin"}   # b.py has the generated bytes
    assert (rows["lib/a.py"]["lines_added"], rows["lib/a.py"]["lines_removed"]) == (1, 1)
    assert (rows["lib/c.py"]["status"], rows["lib/c.py"]["lines_added"]) == ("changed", None)   # its generated content is not at hand
    assert rows["lib/d.bin"]["lines_added"] is None and summary["fixed_files_touched"] == ["lib/c.py"]
    assert summary["generated_files_touched"] == ["lib/a.py", "lib/c.py"]
