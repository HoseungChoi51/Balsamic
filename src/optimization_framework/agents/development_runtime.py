"""Docker boundary for full Pi development. No Docker socket enters a workspace."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "grating-implementation-workspace:pi-1.3.0"
# The coding agent's model when the workspace records none: the OpenAI Codex subscription, as before campaigns chose models.
LEGACY_MODEL = {"provider": "openai-codex", "model": "gpt-6-sol", "effort": "xhigh"}
# What the container's network refuses (deploy/implementation-workspace/network.sh), and its own loopback.
UNREACHABLE = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16")]
# The hosts each provider Pi knows itself is served from, with its sign-in refresh; a custom provider's is its baseUrl's.
PROVIDER_HOSTS = {"openai-codex": ["chatgpt.com", "auth.openai.com"], "openai": ["api.openai.com"],
                  "anthropic": ["api.anthropic.com", "console.anthropic.com"], "google": ["generativelanguage.googleapis.com"],
                  "openrouter": ["openrouter.ai"], "groq": ["api.groq.com"], "mistral": ["api.mistral.ai"], "xai": ["api.x.ai"]}
PACKAGE_INDEX = ["pypi.org", "files.pythonhosted.org"]
# What a workspace gets when its request names no limits, and the researcher's ceilings when the launcher sets none.
LIMITS = {"cpus": 4.0, "memory_gb": 8.0, "gpus": 0}


def ceilings():
    """The most a workspace may ask for, set by the researcher (the launcher's development_max_*); no GPU unless they allow one."""
    found = {}
    for key, default in LIMITS.items():
        raw = os.environ.get("GRATING_DEVELOPMENT_MAX_" + key.upper())
        try:
            found[key] = type(default)(float(raw)) if raw else default
        except ValueError:
            found[key] = default
        if found[key] < 0 or (key != "gpus" and not found[key]):   # never an unlimited container
            found[key] = default
    return found


def model_hosts(model):
    """The hosts the coding agent's model is reached at, or ValueError for a provider whose host Balsamic does not know."""
    provider = (model or LEGACY_MODEL)["provider"]
    endpoint = custom_provider(provider)
    host = urlparse((endpoint or {}).get("baseUrl") or "").hostname
    if host:
        return [host]
    if provider in PROVIDER_HOSTS:
        return list(PROVIDER_HOSTS[provider])
    raise ValueError(f"The coding workspace's network allows only named hosts, and Balsamic does not know where the model provider "
                     f"{provider} is served from. Name its host in egress_hosts")


def package_index():
    """The package index the box installs from: a configured mirror (GRATING_PACKAGE_INDEX_URL), else PyPI."""
    host = urlparse(os.environ.get("GRATING_PACKAGE_INDEX_URL", "")).hostname
    return [host] if host else list(PACKAGE_INDEX)


def egress(model, named=()):
    """The box's egress allowlist (decision 18), by why each host is on it. A provider whose host is unknown needs it named."""
    try:
        hosts = model_hosts(model)
    except ValueError:
        if not named:
            raise
        hosts = []
    return {"model": hosts, "package_index": package_index(), "named": sorted(set(named))}


def allowed_hosts(record):
    """Every host the box may reach; a workspace recorded before the allowlist gets its model's and the package index."""
    found = record.get("egress") or egress(record.get("model"))
    return list(dict.fromkeys([*found["model"], *found["package_index"], *found["named"]]))


def models_file():
    """The Pi models.json the harness takes custom providers from (agent-harness/src/runtime.ts, modelsFile); None in locked mode.
    For a profile with a catalogue (models.template.json), the file the harness resolved from it, which only the harness can
    write: it alone is given the endpoints' variables (issue #70)."""
    if os.environ.get("GRATING_PI_MODELS_FILE"):
        return Path(os.environ["GRATING_PI_MODELS_FILE"])
    if not os.environ.get("GRATING_PI_PROFILE"):
        return None
    profile = Path(os.environ["GRATING_PI_PROFILE"])
    own = profile / "models.json"
    if own.exists():
        return own
    resolved = profile / "tmp" / "models.json"
    return resolved if (profile / "models.template.json").exists() and resolved.exists() else Path.home() / ".pi/agent/models.json"


def custom_provider(provider):
    """A custom provider's definition (a LiteLLM router, a local server), or None for one Pi knows itself."""
    path = models_file()
    try:
        return json.loads(path.read_text()).get("providers", {}).get(provider) if path else None
    except (OSError, ValueError):
        return None


def reachable(provider, endpoint):
    """Refuse a provider the container cannot reach: its network allows public addresses only."""
    host = urlparse(endpoint.get("baseUrl") or "").hostname
    if not host:
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None, socket.AF_INET)}
    except OSError as exc:
        raise ValueError(f"The coding workspace's model provider {provider} ({host}) does not resolve: {exc}")
    if any(ipaddress.ip_address(a) in network for a in addresses for network in UNREACHABLE):
        raise ValueError(f"The coding workspace cannot reach the model provider {provider} at {endpoint['baseUrl']}: its network allows "
                         "public addresses only. Give the campaign a model on a public endpoint, or commission the implementation instead")


def run(args, *, timeout=45, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or "Workspace command failed")[-2000:])
    return result.stdout


def write_library(repo, library):
    """The generated library's files under `libraries/<name>/` of the worktree, each written only when absent, so a recovered
    workspace keeps what its coding agent changed. {repo-relative path: sha256 of the generated bytes}, which the install
    compares the delivered library with (decision 9)."""
    hashes = {}
    for path, content in sorted(library["files"].items()):
        relative = f"libraries/{library['name']}/{path}"
        target = Path(repo) / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        hashes[relative] = hashlib.sha256(content).hexdigest()
    return hashes


def references_note(directory):
    """The brief's line on the references this workspace holds; nothing when it holds none."""
    found = sorted(path.name for path in Path(directory).iterdir() if not path.name.endswith(".commit")) if Path(directory).is_dir() else []
    if not found:
        return ""
    return "\n\n## References\n\n" + "\n".join(f"- `/references/{name}`" for name in found) + "\n"


class DockerWorkspace:
    def __init__(self, directory, image=None, source=None):
        """source: the repository a workspace clones, this checkout unless given (the coding evals give one without the method)."""
        self.directory = Path(directory)
        self.image = image or os.environ.get("GRATING_DEVELOPMENT_IMAGE", IMAGE)
        self.source = Path(source) if source else ROOT

    def root(self, record):
        return self.directory / record["id"]

    def name(self, record):
        return "grating-" + record["id"]

    def capability(self):
        if not shutil.which("docker"):
            return {"available": False, "reason": "Docker is not installed"}
        try:
            run(["docker", "image", "inspect", self.image], timeout=10)
            return {"available": True, "image": self.image}
        except ValueError as exc:
            missing = "no such image" in str(exc).lower()
            return {"available": False, "image": self.image,
                    "reason": f"The workspace image is not built: docker build -t {self.image} deploy/implementation-workspace" if missing else str(exc)}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "reason": str(exc), "image": self.image}

    def inspect(self, record):
        result = subprocess.run(["docker", "inspect", self.name(record)], capture_output=True, text=True, timeout=10)
        if result.returncode:
            return None
        data = json.loads(result.stdout)[0]
        ports = data.get("NetworkSettings", {}).get("Ports", {}).get("8080/tcp") or []
        state = data["State"]
        return {"running": state["Running"], "paused": state.get("Paused", False),
                "port": int(ports[0]["HostPort"]) if ports else None, "pid": state["Pid"],
                "image_id": data["Image"], "container_id": data["Id"]}

    def configure_pi(self, record, root):
        """The coding agent runs on the campaign's model: that provider's sign-in only and, for a custom provider, its
        endpoint from the researcher's Pi configuration. No other provider's credentials enter."""
        model = record.get("model") or LEGACY_MODEL
        provider, endpoint = model["provider"], custom_provider(model["provider"])
        if endpoint:
            reachable(provider, endpoint)
        pi_home = root / "home/.pi/agent"
        pi_home.mkdir(parents=True, exist_ok=True)
        if not (pi_home / "settings.json").exists():
            (pi_home / "settings.json").write_text(json.dumps({"defaultProjectTrust": "always", "defaultProvider": provider,
                "defaultModel": model["model"], **({"defaultThinkingLevel": model["effort"]} if model.get("effort") else {}),
                "compaction": {"enabled": True}, "telemetry": {"enabled": False}}))
        if endpoint and not (pi_home / "models.json").exists():
            (pi_home / "models.json").write_text(json.dumps({"providers": {provider: endpoint}}, indent=2))
        auth_file = Path(os.environ.get("GRATING_PI_AUTH_FILE", str(Path.home() / ".pi/agent/auth.json")))
        if auth_file.exists() and not (pi_home / "auth.json").exists():
            auth = json.loads(auth_file.read_text())
            if auth.get(provider):
                target = root / "incoming/auth.json"
                target.write_text(json.dumps({provider: auth[provider]}))
                target.chmod(0o600)

    def prepare(self, record, brief, evidence, library=None):
        """The workspace's directories, worktree, references and `.campaign/` brief; with ``library`` ({name, files}), the
        library generated from the campaign's charter under `libraries/<name>/` (write_library). Returns its hashes."""
        root = self.root(record)
        for name in ("work", "home", "incoming/commands", "incoming/results", "outgoing/events", "references"):
            (root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.configure_pi(record, root)
        work = root / "work"
        if not (work / "git").exists():
            run(["git", "clone", "--bare", "--no-local", "--single-branch", str(self.source), str(work / "git")], timeout=120)
        if not (work / "repo/.git").exists():
            (work / "repo").mkdir(exist_ok=True, mode=0o700)
            branch = "implementation/" + record["id"]
            exists = subprocess.run(["git", f"--git-dir={work / 'git'}", "show-ref", "--verify", "--quiet",
                                     "refs/heads/" + branch], capture_output=True).returncode == 0
            run(["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--entrypoint", "git",
                 "--mount", f"type=bind,src={work},dst=/work", self.image,
                 "--git-dir=/work/git", "worktree", "add",
                 *(["/work/repo", branch] if exists else ["-b", branch, "/work/repo", "HEAD"])], timeout=60)
        repo = work / "repo"
        self.references(root)
        context = repo / ".campaign"
        context.mkdir(exist_ok=True)
        # Do not replace developer-edited context when recovering an existing workspace.
        for name, content in {"assignment.md": brief + references_note(root / "references"), "evidence.json": json.dumps(evidence, indent=2),
                              "checkpoint.md": "# Development checkpoint\n\nRecord decisions, tests, remaining work, and blockers here.\n"}.items():
            if not (context / name).exists():
                (context / name).write_text(content)
        vscode = repo / ".vscode"
        vscode.mkdir(exist_ok=True)
        settings = {
            "terminal.integrated.profiles.linux": {
                "Pi implementation": {"path": "tmux", "args": ["attach-session", "-t", "implementation"]},
                "Development shell": {"path": "bash"}},
            "terminal.integrated.defaultProfile.linux": "Pi implementation",
            "terminal.integrated.enablePersistentSessions": True,
            "workbench.startupEditor": "none", "security.workspace.trust.enabled": False,
        }
        if not (vscode / "settings.json").exists():
            (vscode / "settings.json").write_text(json.dumps(settings, indent=2))
        return write_library(repo, library) if library else None

    def references(self, root):
        """Reference code only: no host working files, credentials, or campaign databases."""
        flrl = Path(os.environ.get("GRATING_FLRL_REFERENCE", str(ROOT.parent / "flrl")))
        if (flrl / ".git").exists() and not (root / "references/flrl").exists():
            target = root / "references/flrl"
            target.mkdir()
            archive = root / "references/flrl.tar"
            run(["git", "-C", str(flrl), "archive", "--output", str(archive), "HEAD"])
            import tarfile
            with tarfile.open(archive) as tar:
                tar.extractall(target, filter="data")
            archive.unlink()
            (root / "references/flrl.commit").write_text(run(["git", "-C", str(flrl), "rev-parse", "HEAD"]))
        # Optional paper PDF; set GRATING_PAPER_REFERENCE or the launcher's `paper_reference`.
        paper = Path(os.environ.get("GRATING_PAPER_REFERENCE", "")).expanduser()
        if paper.name and paper.is_file() and paper.stat().st_size < 50 * 1024 * 1024:
            target = root / "references/paper.pdf"
            if not target.exists():
                shutil.copy2(paper, target)
            extracted = root / "references/paper.txt"
            if not extracted.exists():
                from pypdf import PdfReader
                text = "\n\n".join(f"# Page {index + 1}\n{page.extract_text() or ''}"
                                   for index, page in enumerate(PdfReader(str(target)).pages))
                if len(text.encode()) <= 5 * 1024 * 1024:
                    extracted.write_text(text)

    def start(self, record):
        current = self.inspect(record)
        if current:
            if current["paused"]:
                run(["docker", "unpause", self.name(record)])
            elif not current["running"]:
                run(["docker", "start", self.name(record)])
            return self.inspect(record)
        root = self.root(record)
        args = ["docker", "run", "-d", "--init", "--name", self.name(record),
                "--label", "grating.development=" + record["id"], "--restart", "unless-stopped",
                *self.limit_args(record), "--pids-limit", "1024", "--read-only",
                "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "--cap-add", "SETUID", "--cap-add", "SETGID",
                "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,nodev,size=2g",
                "--tmpfs", "/run:rw,nosuid,nodev,size=16m", "-p", "127.0.0.1::8080"]
        for source, target, readonly in [(root / "work", "/work", False), (root / "home", "/home/developer", False),
                (root / "incoming", "/bridge/in", True), (root / "outgoing", "/bridge/out", False),
                (root / "references", "/references", True),
                (ROOT / "agent-harness/extensions/implementation.ts", "/opt/workspace/extension.ts", True),
                (ROOT / "deploy/implementation-workspace/balsamic-workspace.mjs", "/opt/workspace/balsamic-workspace.mjs", True)]:
            args += ["--mount", f"type=bind,src={source},dst={target}" + (",readonly" if readonly else "")]
        model = record.get("model") or LEGACY_MODEL
        args += ["-e", f"PI_PROVIDER={model['provider']}", "-e", f"PI_MODEL={model['model']}", "-e", f"PI_THINKING={model.get('effort') or ''}"]
        args += ["-e", "EGRESS_HOSTS=" + " ".join(allowed_hosts(record))]
        args += ["-e", f"WORKSPACE_UID={os.getuid()}", "-e", f"WORKSPACE_GID={os.getgid()}", self.image]
        run(args, timeout=60)
        return self.inspect(record)

    @staticmethod
    def limit_args(record):
        """The container's limits from the workspace's record (today's 4 CPUs and 8 GB for one recorded before); no GPU unless named."""
        limits = {**LIMITS, **(record.get("limits") or {})}
        return ["--cpus", f"{limits['cpus']:g}", "--memory", f"{limits['memory_gb'] * 1024:.0f}m",
                *(["--gpus", str(limits["gpus"])] if limits["gpus"] else [])]

    def pause(self, record):
        current = self.inspect(record)
        if current and current["running"] and not current["paused"]:
            run(["docker", "pause", self.name(record)])

    def stop(self, record):
        current = self.inspect(record)
        if current and current["paused"]:
            run(["docker", "unpause", self.name(record)])
        if current and current["running"]:
            run(["docker", "stop", "-t", "10", self.name(record)])

    def cpu_seconds(self, state):
        if not state or not state.get("pid"):
            return None
        try:
            relative = next(line.split(":", 2)[2] for line in Path(f"/proc/{state['pid']}/cgroup").read_text().splitlines() if line.startswith("0::"))
            stats = dict(line.split() for line in (Path("/sys/fs/cgroup") / relative.lstrip("/") / "cpu.stat").read_text().splitlines())
            return int(stats["usage_usec"]) / 1e6
        except (OSError, StopIteration, KeyError):
            return None

    def snapshot(self, record, commit, manifest_path):
        import re
        from pathlib import PurePosixPath
        from .development import submission_manifest
        from optimization_framework.implementations.models import Package
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("Submit the full 40-character Git commit hash")
        def git(*args):
            return run(["docker", "exec", "--user", f"{os.getuid()}:{os.getgid()}", self.name(record),
                        "git", "--no-replace-objects", "-C", "/work/repo", *args], timeout=10)
        def inside(path):
            p = PurePosixPath(path)
            if p.is_absolute() or str(p) != path or ".." in p.parts or "\\" in path:
                raise ValueError("Submission paths must stay in the repository")
            return path
        def read(path):
            output = git("show", commit + ":" + inside(path))
            if len(output.encode()) > 1048576:
                raise ValueError("Submitted file exceeds the package transport limit")
            return output
        # No manifest committed: one is derived from the commit's single library.
        present = bool(git("ls-tree", "--name-only", commit, "--", inside(manifest_path)).strip())
        manifest, ignored = submission_manifest(read(manifest_path) if present else None,
                                                git("ls-tree", "-r", "--name-only", commit, "--", "libraries").splitlines())
        package = Package(contract=manifest.contract, entrypoint=manifest.entrypoint,
                          files=[{"path": p, "content": read(p)} for p in manifest.files])
        return package.model_dump(), manifest.model_dump(), ignored
