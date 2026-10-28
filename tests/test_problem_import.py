"""Problem examples and the importer: safe uploads, confined agent reads, reviewable drafts."""
import io
import json
import tarfile
import zipfile
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from balsamic.app import create_app
from optimization_framework.contracts.problem_imports import ProblemExample
from optimization_framework.problem_import.files import ImportError_, ImportFolder, check_git_url, docx_text
from optimization_framework.problem_import.service import ImportCreate, ImportMessage, ProblemImports


class FakePi:
    def __init__(self):
        self.submitted, self.controls, self.runs, self.events = [], [], {}, []

    def status(self):
        return {"configured": True, "mode": "dev", "defaults": {"provider": "deepseek", "model": "deepseek-v4-pro", "effort": None},
                "providers": {"deepseek": {"auth": "api_key", "billing": "api"}},
                "models": [{"provider": "deepseek", "id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "thinking_levels": ["off", "high", "max"]}]}

    def submit(self, agent, run):
        self.submitted.append((agent, run))
        self.runs[run["id"]] = {"status": "running"}

    def inspect(self, agent_id, after=0):
        events = [event for event in self.events if event["seq"] > after]
        return {"runs": self.runs, "events": events, "cursor": events[-1]["seq"] if events else after}

    def control(self, agent_id, action):
        self.controls.append((agent_id, action))


def zipped(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def flrl_setup():
    from optimization_framework.evaluation.registry import problems
    example = next(item for item in problems.examples() if item["id"].startswith("flrl"))
    return deepcopy(example["instances"][0])


def draft(**changes):
    return {"title": "FLRL deflector", "summary": "2D dual-polarization deflector.", "objective": "Maximize mean TE/TM +1 efficiency.",
            "instances": [flrl_setup()], "assumptions": ["Normal incidence"], "open_questions": ["Silicon index source"],
            "citations": [{"source": "documents/paper.md.txt", "location": "line 1", "quote": "75 degrees"}], **changes}


def test_installed_examples_offer_both_meent_problems_and_validate(tmp_path):
    with TestClient(create_app(tmp_path, start_workers=False)) as client:
        examples = client.get("/api/v1/problem-examples").json()["examples"]
    ids = {example["id"] for example in examples}
    assert {"meent_grating_1100nm_50deg", "flrl_2d_deflector_1050nm_75deg"} <= ids
    for example in examples:
        for setup in ProblemExample.model_validate(example).instances:
            assert setup.task_input().problem is not None
    flrl = next(example for example in examples if example["id"].startswith("flrl"))
    assert flrl["campaign"]["autonomy"] == "delegated" and "/home/" not in flrl["campaign"]["objective"]


def test_archives_cannot_escape_and_credentials_are_not_copied(tmp_path):
    folder = ImportFolder(tmp_path / "import").create()
    def upload(name, raw):
        path = folder.archive_upload(name)
        path.write_bytes(raw)
        return folder.add_archive(name, path)
    with pytest.raises(ImportError_, match="escapes"):
        upload("bad.zip", zipped({"../evil.py": "x"}))
    summary = upload("code.zip", zipped({"src/model.py": "def score(): pass", ".env": "KEY=1",
        "pkg/.ssh/id_rsa": "secret", "node_modules/x.js": "x", "data/big.bin": b"\0" * (6 * 1024**2)}))
    # Large files are kept and flagged; the agent decides whether they matter.
    assert summary["files"] == 2 and summary["large_files"] == 1 and (folder.code / "data/big.bin").stat().st_size == 6 * 1024**2
    assert {row["path"] for row in summary["skipped"]} == {".env", "pkg/.ssh/id_rsa", "node_modules/x.js"}
    listed = {row["path"]: row for row in folder.listing("code", depth=3)["entries"]}
    assert listed["code/data/big.bin"] == {"path": "code/data/big.bin", "type": "file", "bytes": 6 * 1024**2, "large": True, "binary": True}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        link = tarfile.TarInfo("link"); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"
        archive.addfile(link)
        data = b"print(1)"; info = tarfile.TarInfo("run.py"); info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    summary = upload("code.tar.gz", buffer.getvalue())
    assert summary["files"] == 1 and not (folder.code / "link").exists()


def test_local_folders_exclude_account_settings_and_secrets(tmp_path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    project = home / "Work" / "flrl"
    (project / ".git").mkdir(parents=True)
    (project / "train.py").write_text("print('train')")
    (project / "secrets.json").write_text("{}")
    (project / ".git" / "config").write_text("[core]")
    folder = ImportFolder(tmp_path / "import").create()
    for path, message in ((home / ".ssh", "credentials"), (home, "home folder"), (tmp_path / "elsewhere", "does not exist")):
        with pytest.raises(ImportError_, match=message):
            folder.add_folder(str(path), home=home)
    summary = folder.add_folder(str(project), home=home)
    assert summary["files"] == 1 and (folder.code / "train.py").exists() and not (folder.code / ".git").exists()


def test_git_sources_are_limited_to_network_urls():
    check_git_url("https://github.com/kc-ml2/FLRL.git")
    check_git_url("git@github.com:kc-ml2/FLRL.git")
    for url in ("file:///etc", "/home/chs/repo", "ext::sh -c touch", "-uhttps://x/y", "http://example.com/repo"):
        with pytest.raises(ImportError_):
            check_git_url(url)


def test_document_text_keeps_locations_and_agent_reads_stay_inside(tmp_path):
    body = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>Period 525 nm</w:t></w:r></w:p><w:p><w:r><w:t>TE and TM</w:t></w:r></w:p></w:body></w:document>')
    assert docx_text("s.docx", zipped({"word/document.xml": body})) == "[para 1] Period 525 nm\n[para 2] TE and TM"
    folder = ImportFolder(tmp_path / "import").create()
    folder.add_document("paper.md", b"# Deflector\nThe target angle is 75 degrees.\n")
    assert folder.read("documents/paper.md.txt")["text"].splitlines()[1] == "2: The target angle is 75 degrees."
    assert folder.search("75 degrees")["matches"][0]["path"] == "documents/paper.md.txt"
    (folder.code / "data.csv").write_text("x\n" * 1_500_000 + "needle\n")
    found = folder.search("needle")
    assert found["matches"] == [] and found["skipped_large_files"][0]["path"] == "code/data.csv"
    assert folder.search("needle", "code/data.csv")["matches"][0]["line"] == 1_500_001
    page = folder.read("code/data.csv", start_line=1_499_999, max_lines=5)
    assert page["text"].splitlines() == ["1499999: x", "1500000: x", "1500001: needle"] and not page["more"]
    for path in ("../uploads/document-paper.md", "/etc/passwd", "documents/../../uploads"):
        with pytest.raises(ValueError):
            folder.read(path)
    with pytest.raises(ImportError_, match="supported documents"):
        folder.add_document("tool.exe", b"MZ")


def test_import_produces_a_reviewable_charter_through_the_harness(tmp_path):
    from optimization_framework.execution.service import Workspace
    workspace, pi = Workspace(tmp_path), FakePi()
    imports = ProblemImports(workspace, client=pi)
    workspace.problem_imports = imports
    with pytest.raises(ValueError, match="not available"):
        imports.create(ImportCreate(provider="deepseek", model="unknown"))
    record = imports.create(ImportCreate(provider="deepseek", model="deepseek-v4-pro", effort="high", notes="Use the 2D condition"))
    with pytest.raises(ValueError, match="at least one document"):
        imports.start(record["id"])
    imports.add_document(record["id"], "paper.md", b"The target angle is 75 degrees.")
    record = imports.start(record["id"])
    agent, run = pi.submitted[0]
    assert agent["role"] == "formulator" and agent["id"] == record["id"] and "documents/paper.md.txt" in run["input"]
    with pytest.raises(ValueError, match="only before the import starts"):
        imports.add_document(record["id"], "late.md", b"x")
    manifest = imports.manifest(record["id"], run["id"])
    assert {tool["name"] for tool in manifest["tools"]} == {"files_list", "file_read", "files_search", "problem_catalog",
        "charter_read", "charter_check", "charter_submit", "question_ask", "charter_propose", "panel_render"}
    assert "Formulating a scientific optimization problem" in manifest["instructions"]
    # No extension: the formulator has no yield_work, so the reminder to call it would cost a model call per run (roadmap P3).
    assert manifest["extension_host"] is False
    catalog = imports.call(record["id"], run["id"], "c1", "problem_catalog", {})
    assert "meent_2d_dual_polarization_deflector" in {adapter["problem_id"] for adapter in catalog["adapters"]}
    assert "error" in imports.call(record["id"], run["id"], "c2", "file_read", {"path": "../uploads/document-paper.md"})
    assert "error" in imports.call(record["id"], run["id"], "c3", "charter_read", {})
    charter = deepcopy(next(item for item in problems_examples() if item["id"].startswith("flrl"))["charter"])
    checked = imports.call(record["id"], run["id"], "c4", "charter_check", {"charter": charter})
    assert checked["blocking"] == 1 and checked["saved"] is False
    assert "error" in imports.call(record["id"], run["id"], "c5", "charter_submit", {"charter": {"title": ""}})
    saved = imports.call(record["id"], run["id"], "c6", "charter_submit", {"charter": charter})
    assert saved["saved"] and saved["blocking"] == 1
    assert saved["values"] == checked["values"]   # saving returns what a check would: no separate check call is needed
    charter_id = imports.get(record["id"])["charter_id"]
    asked = imports.call(record["id"], run["id"], "c7", "question_ask", {"questions": [
        {"id": "incidence", "question": "Is the incidence normal?", "options": ["Yes", "No, give the angle"], "about": ["incident_angle_deg"]}]})
    assert asked["asked"] == 1
    pi.events = [{"seq": 1, "type": "assistant.message", "text": "Formulated the FLRL deflector.", "billing": "api",
                  "usage": {"input": 1000, "output": 200, "cacheRead": 0, "reasoning": 50, "cost_usd": 0.01}}]
    pi.runs[run["id"]] = {"status": "completed", "result": {"text": "Formulated; one open question."}}
    record = imports.sync(record["id"])
    assert record["status"] == "ready" and record["reply"] == "Formulated; one open question."
    assert record["usage"]["calls"] == 1 and record["usage"]["charged_usd"] == 0.01
    assert any("Read ../uploads" in row["text"] for row in record["activity"])
    # Answering the last open question starts the formulator's next turn.
    view = workspace.charters.view(charter_id)
    workspace.charters.answer(charter_id, "incidence", "Yes, normal incidence", expected_revision=view["revision"])
    assert "round 1 of 2" in pi.submitted[-1][1]["input"] and "do not ask again what the answers already cover" in pi.submitted[-1][1]["input"]
    assert "Yes, normal incidence" in pi.submitted[-1][1]["input"] and imports.get(record["id"])["status"] == "running"
    pi.runs[pi.submitted[-1][1]["id"]] = {"status": "completed", "result": {"text": "Revised."}}
    imports.sync(record["id"])
    # A request in words becomes a proposal whose numbers are computed, not stated.
    workspace.charters.request(charter_id, "Set the period to 1100 nm")
    run_id = pi.submitted[-1][1]["id"]
    assert "Set the period to 1100 nm" in pi.submitted[-1][1]["input"]
    proposed = imports.call(record["id"], run_id, "c8", "charter_propose", {"request": "", "options": [
        {"label": "Change the angle", "reason": "Keeps the wavelength",
         "changes": [{"op": "solve", "input": "target_angle_deg", "target": "period_x_nm", "value": 1100}]}]})
    assert "options" in proposed, proposed
    angle = next(row for row in proposed["options"][0]["changes"] if row["name"] == "target_angle_deg")
    assert angle["after"] == "72.6586°"
    assert workspace.charters.view(charter_id)["proposals"][0]["request"] == "Set the period to 1100 nm"
    assert workspace.charters.view(charter_id)["proposals"][0]["asked"] == "Set the period to 1100 nm"   # the researcher's own words, for the page


def problems_examples():
    from optimization_framework.evaluation.registry import problems
    return problems.examples()


def test_a_written_statement_alone_starts_the_formulator_and_a_charter_gets_one_on_request(tmp_path):
    from optimization_framework.execution.service import Workspace
    from optimization_framework.agents import tiers
    workspace, pi = Workspace(tmp_path), FakePi()
    imports = ProblemImports(workspace, client=pi)
    workspace.problem_imports = imports
    tiers.save(workspace.store, tiers.TierSettings.model_validate({"tiers": [
        {"id": "strong", "label": "Strong", "model": {"provider": "deepseek", "model": "deepseek-v4-pro", "effort": "max"}}],
        "roles": {"formulator": "strong"}}))
    record = imports.create(ImportCreate(provider="deepseek", model="deepseek-v4-pro",
                                         statement="Maximize the yield of a flow reaction.\nTemperature 60-120 C."))
    assert record["title"] == "Maximize the yield of a flow reaction." and record["documents"][0]["text_file"] == "documents/statement.md.txt"
    imports.start(record["id"])
    assert "documents/statement.md.txt" in pi.submitted[-1][1]["input"]
    example = next(item for item in imports.examples() if item["id"].startswith("flrl"))
    charter = workspace.charters.from_example(example["id"])
    assert charter["import_id"] is None and charter["source"]["kind"] == "example"
    workspace.charters.request(charter["id"], "Use 1100 nm")
    formulator = workspace.charters.get(charter["id"])["import_id"]
    assert formulator and imports.get(formulator)["charter_id"] == charter["id"] and pi.submitted[-1][0]["id"] == formulator


def test_api_billed_import_stops_at_its_budget(tmp_path):
    from optimization_framework.execution.service import Workspace
    workspace, pi = Workspace(tmp_path), FakePi()
    imports = ProblemImports(workspace, client=pi)
    record = imports.create(ImportCreate(provider="deepseek", model="deepseek-v4-pro", budget_usd=0.05))
    imports.add_document(record["id"], "paper.md", b"text")
    imports.start(record["id"])
    pi.events = [{"seq": 1, "type": "assistant.message", "billing": "api", "usage": {"cost_usd": 0.06}}]
    record = imports.sync(record["id"])
    assert record["status"] == "stopped" and "budget" in record["error"] and pi.controls == [(record["id"], "stop")]


def test_harness_callbacks_for_importers_reach_the_importer(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("secret-token")
    monkeypatch.setenv("GRATING_PI_TOKEN_FILE", str(token))
    app = create_app(tmp_path / "workspace", start_workers=False)
    with TestClient(app) as client:
        imports = app.state.workspace.problem_imports
        imports._client = FakePi()
        record = client.post("/api/v1/problem-imports", json={"provider": "deepseek", "model": "deepseek-v4-pro"}).json()
        uploaded = client.put(f"/api/v1/problem-imports/{record['id']}/documents/paper.md", content=b"Angle 75 degrees")
        assert uploaded.status_code == 200 and uploaded.json()["documents"][0]["text_file"] == "documents/paper.md.txt"
        run_id = client.post(f"/api/v1/problem-imports/{record['id']}/start").json()["runs"][0]
        headers = {"Authorization": "Bearer secret-token"}
        manifest = client.post("/api/internal/pi/manifest", json={"agent_id": record["id"], "run_id": run_id}, headers=headers).json()
        assert "charter_submit" in {tool["name"] for tool in manifest["tools"]}
        found = client.post("/api/internal/pi/tool", headers=headers, json={"agent_id": record["id"], "run_id": run_id,
            "call_id": "c1", "name": "files_search", "arguments": {"pattern": "75"}}).json()
        assert found["matches"][0]["line"] == 1
        assert client.post("/api/internal/pi/tool", json={"agent_id": record["id"], "run_id": run_id,
            "call_id": "c2", "name": "files_list", "arguments": {}}).status_code == 401


def test_importer_uses_the_tier_assigned_to_its_role(tmp_path):
    from optimization_framework.agents import tiers
    from optimization_framework.execution.service import Workspace
    workspace, pi = Workspace(tmp_path), FakePi()
    tiers.save(workspace.store, tiers.TierSettings.model_validate({"tiers": [
        {"id": "strong", "label": "Strong", "model": {"provider": "deepseek", "model": "deepseek-v4-pro", "effort": "max"}},
        {"id": "fast", "label": "Fast", "model": {"provider": "deepseek", "model": "deepseek-v4-pro", "effort": "off"}}],
        "roles": {"problem_importer": "strong"}}))
    imports = ProblemImports(workspace, client=pi)
    record = imports.create(ImportCreate())
    assert (record["tier"], record["model"]["effort"]) == ("strong", "max")
    assert imports.create(ImportCreate(tier="fast"))["model"]["effort"] == "off"
    with pytest.raises(ValueError, match="model tier"):
        imports.create(ImportCreate(tier="missing"))


def test_questions_left_unanswered_go_to_the_formulator_as_decisions_to_record(tmp_path):
    """The researcher is not expected to know every answer: a round can be sent with questions open, and the formulator is
    told to decide each from the answers and the sources, record an assumption, and never ask it again."""
    from optimization_framework.execution.service import Workspace
    workspace, pi = Workspace(tmp_path), FakePi()
    imports = ProblemImports(workspace, client=pi)
    workspace.problem_imports = imports
    record = imports.create(ImportCreate(provider="deepseek", model="deepseek-v4-pro"))
    imports.add_document(record["id"], "paper.md", b"The target angle is 75 degrees.")
    record = imports.start(record["id"])
    run = pi.submitted[0][1]
    charter = deepcopy(next(item for item in problems_examples() if item["id"].startswith("flrl"))["charter"])
    imports.call(record["id"], run["id"], "c1", "charter_submit", {"charter": charter})
    charter_id = imports.get(record["id"])["charter_id"]
    imports.call(record["id"], run["id"], "c2", "question_ask", {"questions": [
        {"id": "incidence", "question": "Is the incidence normal?", "options": ["Yes", "No, give the angle"]},
        {"id": "polarization", "question": "Which polarization matters?", "options": ["Both equally", "TE only"]}]})
    pi.runs[run["id"]] = {"status": "completed", "result": {"text": "Two open questions."}}
    imports.sync(record["id"])
    view = workspace.charters.view(charter_id)
    workspace.charters.answer(charter_id, "incidence", "Yes", expected_revision=view["revision"])
    assert len(pi.submitted) == 1   # one still open: nothing is sent by itself
    view = workspace.charters.view(charter_id)
    assert [row["message"] for row in view["findings"] if row["code"] == "question.open"] == ["Open question: Which polarization matters?"]
    workspace.charters.send_answers(charter_id, expected_revision=view["revision"])
    prompt = pi.submitted[-1][1]["input"]
    assert "Answer: Yes" in prompt and "left these unanswered" in prompt and "Which polarization matters?" in prompt
    assert "do not ask them again" in prompt and "Record each decision as an assumption" in prompt and "drop the question" in prompt
    view = workspace.charters.view(charter_id)
    left = next(q for q in view["charter"]["questions"] if q["id"] == "polarization")
    assert left["sent"] and left["answer"] is None
    assert [row["message"] for row in view["findings"] if row["code"] == "question.open"] == ["Left to the formulator to decide: Which polarization matters?"]
    # The formulator's revised draft that keeps the question keeps it as left to it, not as open to the researcher again.
    draft = deepcopy(view["charter"]); draft["questions"] = [q for q in draft["questions"] if q["id"] == "polarization"]
    run_id = pi.submitted[-1][1]["id"]
    imports.call(record["id"], run_id, "c3", "charter_submit", {"charter": draft})
    assert workspace.charters.view(charter_id)["charter"]["questions"][0]["sent"] is True


def formulator_at_work(tmp_path):
    """A formulator that has saved a charter with one open question and is still working in the same run."""
    from optimization_framework.execution.service import Workspace
    workspace, pi = Workspace(tmp_path), FakePi()
    imports = ProblemImports(workspace, client=pi)
    workspace.problem_imports = imports
    record = imports.create(ImportCreate(provider="deepseek", model="deepseek-v4-pro"))
    imports.add_document(record["id"], "paper.md", b"The target angle is 75 degrees.")
    record = imports.start(record["id"])
    run_id = pi.submitted[0][1]["id"]
    charter = deepcopy(next(item for item in problems_examples() if item["id"].startswith("flrl"))["charter"])
    imports.call(record["id"], run_id, "c1", "charter_submit", {"charter": charter})
    imports.call(record["id"], run_id, "c2", "question_ask", {"questions": [
        {"id": "incidence", "question": "Is the incidence normal?", "options": ["Yes", "No, give the angle"], "about": ["incident_angle_deg"]}]})
    return workspace, pi, imports, record, run_id, imports.get(record["id"])["charter_id"]


def test_the_researchers_input_waits_while_the_formulator_works(tmp_path):
    """What the page showed while the formulator was revising (an old question, an old suggestion, an old proposal) could be
    acted on, and the formulator then went on from a charter that had drifted. Now every input waits until it is done."""
    from balsamic.panels.service import _bound
    from optimization_framework.problem_charter.service import NOT_LISTENING
    workspace, pi, imports, record, run_id, charter_id = formulator_at_work(tmp_path)
    charters = workspace.charters
    proposed = imports.call(record["id"], run_id, "c3", "charter_propose", {"request": "Tidy", "options": [
        {"label": "Change the angle", "reason": "r", "changes": [{"op": "solve", "input": "target_angle_deg", "target": "period_x_nm", "value": 1100}]}]})
    view = charters.view(charter_id)
    assert view["formulator"] == {"status": "running", "listening": False}
    assert _bound(lambda _: view, {"charter": charter_id, "question": "incidence"})["listening"] is False, "a panel field waits too"
    revision, attempts = view["revision"], [
        lambda: charters.answer(charter_id, "incidence", "Yes", expected_revision=revision),
        lambda: charters.edit(charter_id, [{"op": "set", "path": "quantities.wavelength_nm.value", "value": 1100}], expected_revision=revision),
        lambda: charters.accept_assumptions(charter_id, expected_revision=revision),
        lambda: charters.waive(charter_id, "any", "a reason", expected_revision=revision),
        lambda: charters.send_answers(charter_id, expected_revision=revision),
        lambda: charters.request(charter_id, "Set the period to 1100 nm"),
        lambda: charters.decide(proposed["proposed"], 0),
        lambda: charters.confirm(charter_id, expected_revision=revision)]
    for attempt in attempts:
        with pytest.raises(ValueError, match="revising this charter"):
            attempt()
    assert charters.get(charter_id)["revision"] == revision and len(pi.submitted) == 1, "nothing changed, nothing was sent"
    assert NOT_LISTENING.endswith("nothing was changed.")
    # Its turn ends: the next input brings its status up to date and is taken.
    pi.runs[run_id] = {"status": "completed", "result": {"text": "Saved; one question."}}
    charters.answer(charter_id, "incidence", "Yes", expected_revision=revision)
    assert charters.view(charter_id)["formulator"] == {"status": "running", "listening": False}, "the answer started its next turn"
    assert "Answer: Yes" in pi.submitted[-1][1]["input"]


def test_the_formulator_recommends_only_what_can_run(tmp_path):
    """token-sharing: the formulator recommended keeping exact grids "and leave execution blocked", and the researcher took it."""
    workspace, pi, imports, record, run_id, charter_id = formulator_at_work(tmp_path)
    ask = lambda options, unrunnable, key: imports.call(record["id"], run_id, key, "question_ask", {"questions": [
        {"id": "grids_" + key, "question": "The lab cannot pass a different grid per variable. How should the grids be handled?",
         "options": options, "unrunnable_options": unrunnable}]})
    wait, rounding = "Keep the exact grids and leave execution blocked until the lab supports them", "The evaluator rounds each variable to its grid"
    assert "first option, shown as recommended" in ask([wait, rounding], [0], "k1")["error"]
    assert "never recommended" in ask([rounding, wait + " (recommended)"], [1], "k2")["error"]
    assert "does not have" in ask([rounding, wait], [2], "k3")["error"]
    # A runnable option first; and when every option leaves nothing able to run, none is recommended and the question may stand.
    asked = imports.call(record["id"], run_id, "k4", "question_ask", {"questions": [
        {"id": "grids", "question": "How should the grids be handled?", "options": [rounding, wait], "unrunnable_options": [1]},
        {"id": "evaluator", "question": "Who supplies the evaluator?", "options": [wait, "Wait for the vendor's code"], "unrunnable_options": [0, 1]}]})
    assert asked["asked"] == 2, asked
    saved = {q["id"]: q for q in workspace.charters.get(charter_id)["charter"]["questions"]}
    assert saved["grids"]["unrunnable_options"] == [1] and saved["evaluator"]["unrunnable_options"] == [0, 1]
    # A proposal's option that leaves checks open is shown after one that leaves none.
    proposed = imports.call(record["id"], run_id, "c9", "charter_propose", {"request": "Grids", "options": [
        {"label": "Wait for the lab", "reason": "Exact grids", "blocking_reason": "Nothing runs until the lab passes grids",
         "changes": [{"op": "set", "path": "quantities.wavelength_nm.value", "value": 1100}]},
        {"label": "Round in the evaluator", "reason": "Runs now", "changes": [{"op": "set", "path": "quantities.wavelength_nm.value", "value": 1050}]}]})
    assert [option["label"] for option in proposed["options"]] == ["Round in the evaluator", "Wait for the lab"]
