"""The curated Pi extensions each role's session loads, and the extension tools it may run (harness plan, Phase 4).

The list is a versioned file, agent-harness/extensions/allowlist.json (GRATING_PI_EXTENSIONS names another one, as the
evals do). It is part of the manifest, so a runtime keeps the set it was made with. The Balsamic extension is not listed:
the harness loads it first in every session.

    {"extensions": {"<name>": {"path": "session/<name>/index.ts", "tools": {"<tool>": {"read_only": true}}}},
     "roles": {"<role>": ["<name>", ...]}}
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[3] / "agent-harness" / "extensions" / "allowlist.json"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
TOOL = re.compile(r"[a-zA-Z0-9_-]{1,64}")


def allowlist_path():
    return Path(os.environ.get("GRATING_PI_EXTENSIONS") or DEFAULT)


@lru_cache(maxsize=8)
def _load(path, mtime):
    if mtime is None:
        return {}
    data = json.loads(Path(path).read_text())
    base = Path(path).resolve().parent
    extensions = {}
    for name, entry in (data.get("extensions") or {}).items():
        if not NAME.fullmatch(name):
            raise ValueError(f"Extension name {name!r} is not a lowercase word")
        location = (base / entry["path"]).resolve()
        if base not in location.parents:
            raise ValueError(f"Extension {name} lies outside {base}")
        tools = list(entry.get("tools") or {})
        if any(not TOOL.fullmatch(tool) for tool in tools):
            raise ValueError(f"Extension {name} names an invalid tool")
        extensions[name] = {"name": name, "path": str(location), "tools": tools}
    roles = {}
    for role, names in (data.get("roles") or {}).items():
        missing = [name for name in names if name not in extensions]
        if missing:
            raise ValueError(f"Role {role} lists unknown extensions: {', '.join(missing)}")
        roles[role] = [extensions[name] for name in names]
    return roles


def hosts_extensions(agent):
    """Whether the agent's session loads the Balsamic extension (and any): every agent's but one recorded for an implementation
    grant before roadmap H8, which never runs again (agents/tools.py refuses its turns)."""
    return not agent.get("grant_id")


def for_agent(agent):
    """The extensions the agent's session loads after the Balsamic one: [{name, path, tools}]."""
    if not hosts_extensions(agent):
        return []
    path = allowlist_path()
    mtime = path.stat().st_mtime if path.exists() else None
    return [dict(entry) for entry in _load(str(path), mtime).get(agent["role"], [])]


def tool_extension(agent, tool):
    """The extension that provides an allowlisted tool of this agent's role, or None when the role may not run it."""
    return next((entry["name"] for entry in for_agent(agent) if tool in entry["tools"]), None)
