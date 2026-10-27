"""Guarantees of docs/invariants.md that code held but no test pinned: each test here is named by a `code` row."""
from pathlib import Path

import pytest

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Pins", autonomy="delegated", compute_budget_seconds=20000,
        validation_reserve_seconds=0, delegated_trial_seconds=1500, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    return workspace, campaign, workspace.current_tasks(campaign["id"])[0]


def send(workspace, campaign_id, identity, operation, payload, actor="manager"):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, **pins), actor=actor)


def run(task, hypothesis_id=None):
    return {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": 30,
            **({"hypothesis_id": hypothesis_id} if hypothesis_id else {})}


def test_an_agents_own_proposal_does_not_run_before_an_independent_concept_review(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "own", "hypothesis.create", {"title": "The agent's idea", "mechanism": "One step", "rationale": "r"})
    own = workspace.store.get("hypothesis_own", "hypothesis")
    assert own["requires_concept_review"] is True
    with pytest.raises(ValueError, match="independent conceptual review is required"):
        send(workspace, cid, "own_run", "trial.create", run(task, own["id"]))
    with pytest.raises(ValueError, match="independent conceptual review is required"):   # the researcher's go does not skip it either
        send(workspace, cid, "own_run_by_researcher", "trial.create", run(task, own["id"]), actor="researcher")
    send(workspace, cid, "asked", "hypothesis.create", {"title": "The researcher's idea", "mechanism": "m", "rationale": "r"}, actor="researcher")
    assert not workspace.store.get("hypothesis_asked", "hypothesis").get("requires_concept_review")
    send(workspace, cid, "asked_run", "trial.create", run(task, "hypothesis_asked"))


def test_only_the_researcher_endorses_a_finding_and_a_finding_cites_only_visible_evidence(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    send(workspace, cid, "probe", "trial.create", run(task))
    [trial] = workspace.store.list("trial", cid)
    finding = {"content": "Coordinate search reached its best design early.", "source_ids": [trial["id"]]}
    with pytest.raises(ValueError, match="Only the researcher can endorse"):
        send(workspace, cid, "endorsed", "finding.record", {**finding, "interpretation": "researcher_endorsed"})
    with pytest.raises(ValueError, match="outside the visible context"):
        send(workspace, cid, "unseen", "finding.record", {**finding, "source_ids": [trial["id"], "trial_of_another_campaign"]})
    send(workspace, cid, "observed", "finding.record", {**finding, "interpretation": "observation"})
    send(workspace, cid, "endorsed_by_researcher", "finding.record", {**finding, "interpretation": "researcher_endorsed"}, actor="researcher")
    assert {row["author"] for row in workspace.store.list("manager_note", cid) if row.get("kind") == "finding"} == {"manager", "researcher"}


def test_the_coding_box_rejects_private_networks_and_drops_its_capabilities_before_the_agent_starts():
    folder = ROOT / "deploy" / "implementation-workspace"
    assert 'ENTRYPOINT ["bash", "/opt/workspace/network.sh"]' in (folder / "Dockerfile").read_text()
    script = (folder / "network.sh").read_text()
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        assert network in script
    assert 'iptables -A OUTPUT -d "$network" -j REJECT' in script and "ip6tables -A OUTPUT -j REJECT" in script
    *_, last = [line for line in script.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert "start.sh" in last
    assert "exec setpriv" in script and "--bounding-set=-all" in script and "--ambient-caps=-all" in script


def egress_rules(tmp_path, hosts, resolved):
    """network.sh run against stubs: the iptables rules it writes, in order, for these allowed hosts and their addresses."""
    import os
    import subprocess
    bin_dir, log = tmp_path / "bin", tmp_path / "rules.log"
    bin_dir.mkdir()
    for name in ("iptables", "ip6tables"):
        (bin_dir / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {log}\n')
    (bin_dir / "setpriv").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "getent").write_text("#!/bin/sh\ncase \"$2\" in\n" + "".join(
        f'  {host}) printf "{"".join(f"{a} STREAM {host}\\n" for a in addresses)}";;\n' for host, addresses in resolved.items()) + "  *) exit 2;;\nesac\n")
    for path in bin_dir.iterdir():
        path.chmod(0o755)
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 192.0.2.53\n")
    subprocess.run(["bash", str(ROOT / "deploy/implementation-workspace/network.sh")], check=True, env={**os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}", "RESOLV_CONF": str(resolv), "EGRESS_HOSTS": " ".join(hosts)})
    return [line.split()[1:] for line in log.read_text().splitlines() if line.startswith("iptables ")]


def verdict(rules, address, port=443):
    """What the generated OUTPUT chain does with a new TCP connection to this address: the first rule that matches."""
    import ipaddress
    for rule in rules:
        if "conntrack" in rule:
            continue
        options = dict(zip(rule[::2], rule[1::2]))
        if "-d" in options and ipaddress.ip_address(address) not in ipaddress.ip_network(options["-d"]):
            continue
        if options.get("-p", "tcp") != "tcp" or ("--dport" in options and int(options["--dport"]) != port):
            continue
        return options["-j"]
    return "ACCEPT"   # the chain's default policy


def test_the_coding_box_reaches_only_its_allowed_hosts_and_dns(tmp_path):
    rules = egress_rules(tmp_path, ["chatgpt.com", "pypi.org", "files.pythonhosted.org", "nowhere.invalid"],
                         {"chatgpt.com": ["104.18.32.47"], "pypi.org": ["151.101.0.223", "151.101.64.223"],
                          "files.pythonhosted.org": ["151.101.1.63"]})
    for allowed in ("104.18.32.47", "151.101.0.223", "151.101.64.223", "151.101.1.63"):
        assert verdict(rules, allowed) == "ACCEPT"
    assert verdict(rules, "192.0.2.53", 53) == "ACCEPT"          # DNS, to the resolver only
    assert verdict(rules, "93.184.215.14") == "REJECT"            # another public host
    assert verdict(rules, "192.0.2.53", 443) == "REJECT"
    assert verdict(rules, "10.1.2.3") == "REJECT" and verdict(rules, "100.100.1.1") == "REJECT"
    # An allowed host that resolves to a private address stays unreachable, and no list at all allows nothing public.
    for name in ("private", "none"):
        (tmp_path / name).mkdir()
    assert verdict(egress_rules(tmp_path / "private", ["router.example"], {"router.example": ["10.0.0.5"]}), "10.0.0.5") == "REJECT"
    assert verdict(egress_rules(tmp_path / "none", [], {}), "151.101.0.223") == "REJECT"
