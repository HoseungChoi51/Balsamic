"""Stand-ins for --fake coding evals: the agents' turns, played through the real gateway by tests/fake_harness.py, and a coding
workspace that submits a prepared library instead of running Pi in Docker. They check the runner's plumbing and its outside
checks, not a model or a coding agent.

The implementation lead asks for the go-ahead, opens the workspace once it has it, on a work ticket whose acceptance test is
the one the request names, and reports the delivery; the lead
acknowledges the workspace's notices. The workspace submits the original library (the method's own module included), so the
contract test and conformance pass on it."""
import json
from pathlib import Path
import re


def implementation_lead(turn):
    memory = turn.memory
    if not memory.get("hypothesis_id"):
        memory["hypothesis_id"] = re.search(r"hypothesis_\w+", turn.text).group(0)
        memory["method_id"] = re.search(r"method id `(\w+)`", turn.text).group(1)
        # The test the request says the library has to pass is the work ticket's acceptance test (roadmap H4).
        memory["tests"] = re.findall(r"libraries/[\w.\-]+/tests/test_\w+\.py", turn.text)
        turn.call("mandate_propose", template="screen", plan=f"One coding workspace to build {memory['method_id']} as a library: "
                  "the proposal names no installed method", hypothesis_ids=[memory["hypothesis_id"]], wall_seconds=3600,
                  worker_seconds=3600, coding_workspaces=1, meanwhile="Nothing waits on it")
        return turn.finish("I asked for your go-ahead to open the coding workspace.", summary="Asked for the go-ahead", disposition="waiting")
    if not memory.get("workspace_id"):
        opened = turn.call("implementation_workspace_create", hypothesis_id=memory["hypothesis_id"], request_key="build",
                           objective=f"Implement the proposal as a library with the method id {memory['method_id']}.",
                           ticket={"acceptance_tests": [{"path": path} for path in memory["tests"]]})
        memory["workspace_id"] = opened.get("id")
        return turn.finish("The coding workspace is open.", summary="Opened the workspace", disposition="waiting")
    return turn.finish("The coding agent delivered its library.", summary="Delivered")


def lead(turn):
    return turn.finish("", summary="Noted", disposition="waiting") if turn.notice else turn.finish("Noted.")


TURNS = {"implementation_lead": implementation_lead, "lead": lead}


def play(turn):
    return TURNS.get(turn.role, lead)(turn)


class PreparedWorkspace:
    """The workspace driver's interface (agents/development_runtime.py DockerWorkspace): once started, it reports ready and
    submits the library at `library` (a directory of the source checkout) as one commit."""
    COMMIT = "c0de" * 10

    def __init__(self, directory, library, repository):
        self.directory, self.library, self.repository = Path(directory), Path(library), Path(repository)
        self.image = "prepared-library"

    def root(self, record):
        return self.directory / record["id"]

    def name(self, record):
        return "prepared-" + record["id"]

    def capability(self):
        return {"available": True, "image": self.image}

    def prepare(self, record, brief, evidence, ticket=None, references=()):
        from optimization_framework.agents.development_runtime import write_ticket
        root = self.root(record)
        for name in ("incoming/commands", "incoming/results", "outgoing/events"):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / "brief.md").write_text(brief)
        write_ticket(root / "work" / "repo", ticket)   # the work ticket, where the Docker driver writes it into the worktree

    def start(self, record):
        events = self.root(record) / "outgoing/events"
        if not (self.root(record) / "submitted").exists():
            (events / "0001-ready.json").write_text(json.dumps({"type": "ready", "payload": {"session_id": "prepared", "tools": []}}))
            (events / "0002-submission.json").write_text(json.dumps({"type": "submission", "payload": {
                "commit": self.COMMIT, "manifest_path": "implementation-manifest.json", "notes": "The prepared library"}}))
            (self.root(record) / "submitted").touch()
        return self.inspect(record)

    def inspect(self, record):
        return {"running": True, "paused": False, "port": None, "pid": None}

    def cpu_seconds(self, state):
        return None

    def pause(self, record):
        pass

    def stop(self, record):
        pass

    def files(self):
        return sorted(str(path.relative_to(self.repository)) for path in self.library.rglob("*")
                      if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")

    def snapshot(self, record, commit, manifest_path):
        files = self.files()
        manifest = {"contract": "optimizer_v1", "entrypoint": "plugin:GratingMaskSearchPlugin", "files": files, "dependencies": {},
                    "test_summary": "The prepared library"}
        package = {"contract": "optimizer_v1", "entrypoint": manifest["entrypoint"],
                   "files": [{"path": path, "content": (self.repository / path).read_text()} for path in files]}
        return package, manifest, []   # no manifest keys ignored
