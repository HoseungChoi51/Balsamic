"""Authenticated local Pi transport. No provider or credential fallback."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def service_token():
    filename = os.environ.get("GRATING_PI_TOKEN_FILE")
    if not filename:
        raise ValueError("Pi service is not configured")
    return Path(filename).read_text().strip()


class PiClient:
    def request(self, method, route, body=None, *, timeout=15):
        url = os.environ.get("GRATING_PI_URL", "http://127.0.0.1:8768")
        request = Request(url + route, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + service_token(), "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            try:
                detail = json.load(exc).get("detail", "Pi request failed")
            except ValueError:
                detail = "Pi request failed"
            raise ValueError(detail) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError("Pi service is unavailable; work is saved and will reconnect") from None

    def status(self):
        return self.request("GET", "/v1/status")

    def inspect(self, agent_id, after=0):
        return self.request("GET", f"/v1/agents/{agent_id}?after={after}")

    def submit(self, agent, run):
        origin = run.get("origin") or {}
        return self.request("POST", f"/v1/agents/{agent['id']}/runs", {
            "run_id": run["id"], "text": run["input"], "mode": run.get("mode", "follow_up"),
            "deadline_at": agent.get("deadline_at"),
            # A thread is a branch of the lead's session tree: the run says where in it the turn continues.
            "thread_id": origin.get("thread_id"), "leaf_entry_id": run.get("leaf_entry_id"),
            "branch_from_entry_id": run.get("branch_from_entry_id"), "summary": run.get("branch_summary"),
            "spec": {"provider": agent.get("provider") or "openai-codex", "model": agent["model"],
                     "effort": agent["reasoning_effort"], "role": agent["role"]}})

    def tree(self, agent_id):
        """The agent's session tree with the current leaf; None on a harness without session views."""
        return self.request("GET", f"/v1/agents/{agent_id}/tree", timeout=10)

    def entries(self, agent_id, *, after=None, leaf=None):
        query = "&".join(f"{key}={value}" for key, value in (("after", after), ("leaf", leaf)) if value)
        return self.request("GET", f"/v1/agents/{agent_id}/entries" + ("?" + query if query else ""), timeout=10)

    def context(self, agent_id, *, leaf=None):
        return self.request("GET", f"/v1/agents/{agent_id}/context" + (f"?leaf={leaf}" if leaf else ""), timeout=10)

    def set_leaf(self, agent_id, entry_id, summary=None):
        return self.request("POST", f"/v1/agents/{agent_id}/leaf", {"entry_id": entry_id, **({"summary": summary} if summary else {})})

    def export_branch(self, agent_id, *, leaf=None):
        return self.request("GET", f"/v1/agents/{agent_id}/export" + (f"?leaf={leaf}" if leaf else ""), timeout=30)

    def control(self, agent_id, action):
        return self.request("POST", f"/v1/agents/{agent_id}/control", {"action": action})

    def live(self, agent_ids):
        """What these agents are doing right now. Held by the harness in memory; it is shown, not saved."""
        return self.request("GET", "/v1/live?ids=" + ",".join(agent_ids), timeout=4)

    def complete(self, call_id, body, *, timeout=1800):
        """One model call outside any agent session, with the harness's sign-in and prices: a stage of the report writer."""
        return self.request("POST", f"/v1/complete/{call_id}", body, timeout=timeout)

    def forget(self, agent_id):
        """End the agent and delete its saved session; used when its campaign is removed."""
        return self.request("DELETE", f"/v1/agents/{agent_id}")
