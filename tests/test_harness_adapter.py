"""The coding box's harness adapter (roadmap H2): Pi in its terminal UI or headless, its stream mapped to the workspace record.

The fake harness is `tests/fixtures/harness/pi`, which replays `pi-json-stream.jsonl`: a stream recorded from a real
`pi --mode json` run (Pi 1.0.4, the harness's pinned version) against a scripted model endpoint, in the box's own setup:
the extension giving its tools, the balsamic-workspace MCP server configured by the adapter. Four assistant messages, three
tool calls (bash, campaign_checkpoint, mcp__balsamic__evidence); this machine's paths were rewritten to the box's.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_pi_development_workspaces import setup  # noqa: F401  (a fixture)
from test_workspace_cli import bridge

ROOT = Path(__file__).resolve().parents[1]
BOX = ROOT / 'deploy/implementation-workspace'
FAKES = ROOT / 'tests/fixtures/harness'
STREAM = FAKES / 'pi-json-stream.jsonl'
EXTENSION = ROOT / 'agent-harness/extensions/implementation.ts'
MODEL = ['--provider', 'centinels', '--model', 'gpt-6.1-sol']
REFUSED = ('The coding harness "claude-code" is not available: a coding workspace runs only pi. Another harness needs its own '
           "adapter, opted into per workspace on the researcher's own credentials mounted read-only.")


def node_can_fake_pi():
    """The fake harness loads the TypeScript extension as Node 22.18+ does natively, with module.registerHooks (22.15+)."""
    if not shutil.which('node'):
        return False
    probe = subprocess.run(['node', '-e', 'process.exit(require("node:module").registerHooks ? 0 : 1)'], capture_output=True)
    return probe.returncode == 0


needs_node = pytest.mark.skipif(not node_can_fake_pi(), reason='the adapter and the fake harness run on Node 22.18 or later, as the box does')


def recorded(record_type):
    return [json.loads(line) for line in STREAM.read_text().splitlines() if line.strip() and json.loads(line)['type'] == record_type]


def adapter(*args, env=None):
    return subprocess.run(['node', str(BOX / 'harness.mjs'), *args], env=env, capture_output=True, text=True, timeout=60)


def run_harness(tmp_path, driver, record, mode):
    """What start.sh does in the box, outside it: asks the adapter for tmux's command and runs it on the fake pi."""
    env = {**bridge(tmp_path, driver, record), 'PATH': f"{FAKES}:{os.environ['PATH']}", 'FAKE_PI_STREAM': str(STREAM),
           'FAKE_PI_LOG': str(tmp_path / f'pi-{mode}.log'), 'BALSAMIC_PI_EXTENSION': str(EXTENSION),
           'BALSAMIC_HARNESS_SESSIONS': str(tmp_path / f'sessions-{mode}'), 'BALSAMIC_WORKSPACE_REPO': str(tmp_path),
           'BALSAMIC_HARNESS_MODE': mode, 'BALSAMIC_HARNESS_ONCE': '1'}
    command = adapter('command', '--harness', 'pi', '--mode', mode, '--', *MODEL, env=env)
    assert command.returncode == 0, command.stderr
    result = subprocess.run(['bash', '-c', 'exec ' + command.stdout.strip()], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    [called] = [json.loads(line) for line in (tmp_path / f'pi-{mode}.log').read_text().splitlines()]
    return called


@needs_node
@pytest.mark.parametrize('mode', ['headless', 'tui'])
def test_a_recorded_pi_stream_maps_to_the_workspace_record_in_both_modes(setup, tmp_path, mode):
    from optimization_framework.agents.development_timeline import timeline
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement the method', 'request_key': mode,
                                      'harness_mode': mode})
    assert record['harness'] == {'name': 'pi', 'mode': mode}
    development.sync(cid)   # the opening instruction is in the box's incoming commands
    called = run_harness(tmp_path, driver, record, mode)
    development.sync(cid)

    # How the harness ran: headless, pi --mode json with the instruction on stdin; as its TUI, with the extension delivering it.
    if mode == 'headless':
        assert called['args'][:2] == ['--mode', 'json'] and called['args'][2:6] == MODEL and called['harness_mode'] == 'headless'
        assert '--extension' in called['args'] and called['args'][called['args'].index('--session') + 1].endswith('pi.jsonl')
        instruction = called['input']
    else:
        assert '--mode' not in called['args'] and called['args'][:4] == MODEL
        [delivered] = called['delivered']
        assert delivered['deliverAs'] == 'followUp'
        instruction = delivered['text']
    assert instruction.startswith('Developer instruction (takes precedence') and 'Implement the method' in instruction

    # The stream's events, in its order, between the receipts of the instruction it ran.
    saved = development.get(cid, record['id'])
    events = [e for e in development.events(cid, record['id'])['events'] if e['type'] != 'instruction']
    assert [e['type'] for e in events] == ['ready', 'receipt', 'agent_start', 'message', 'tool', 'message', 'tool', 'message', 'tool',
                                           'message', 'receipt', 'agent_settled']
    assert [e['payload']['tool'] for e in events if e['type'] == 'tool'] == ['bash', 'campaign_checkpoint', 'mcp__balsamic__evidence']
    [opening] = [c for c in workspace.store.list('development_command', cid) if c['workspace_id'] == record['id']]
    assert [e['payload'] for e in events if e['type'] == 'receipt'] == [{'command_id': opening['id'], 'status': 'accepted'},
                                                                       {'command_id': opening['id'], 'status': 'completed'}]
    assert workspace.store.get(opening['id'], 'development_command')['status'] == 'completed'

    # Its usage: each assistant message once, as recorded (4 calls; 1800+1176+1576+1976 input, 40+50+60+70 output).
    messages = [r['message'] for r in recorded('message_end') if r['message']['role'] == 'assistant']
    assert len(messages) == 4
    assert {key: saved['usage'][key] for key in ('subscription_calls', 'input', 'output', 'cacheRead', 'cacheWrite')} == {
        'subscription_calls': 4, 'input': 6528, 'output': 220, 'cacheRead': 3072, 'cacheWrite': 0}
    assert saved['status'] == 'idle' and saved['started_at'] and saved['activity'] == 'The library is generated; next I write objective.py.'
    work = [e for e in timeline(workspace.store, saved)['entries'] if e['kind'] == 'work']
    assert len(work) == 1 and work[0]['title'].endswith('3 tool calls') and work[0]['detail'] == saved['activity']


@needs_node
def test_both_modes_report_the_same_events(setup, tmp_path):
    """The extension (TUI) and the adapter (headless) map Pi's events alike: what the host keeps of each is the same."""
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    workspace.store.put('hypothesis', {'id': 'hypothesis_two', 'campaign_id': cid, 'title': 'Second method', 'status': 'proposed',
                                       'mechanism': 'Another', 'algorithm': 'custom', 'algorithm_config': {}})
    kept = {}
    for mode, hypothesis in (('tui', 'hypothesis_dev'), ('headless', 'hypothesis_two')):
        record = development.create(cid, {'hypothesis_id': hypothesis, 'objective': 'Implement', 'request_key': mode, 'harness_mode': mode})
        development.sync(cid)
        (tmp_path / mode).mkdir()
        run_harness(tmp_path / mode, driver, record, mode)
        development.sync(cid)
        events = development.events(cid, record['id'])['events']
        kept[mode] = [(e['type'], e['payload']) for e in events if e['type'] in {'agent_start', 'message', 'tool', 'agent_settled'}]
    assert kept['tui'] == kept['headless'] and len(kept['tui']) == 9


def test_a_harness_other_than_pi_is_refused_with_the_text(setup, tmp_path, monkeypatch):
    from optimization_framework.agents import development_runtime
    from optimization_framework.agents.development_runtime import DockerWorkspace, harness
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    # Asked for: refused before anything is recorded.
    with pytest.raises(ValueError) as refused:
        development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'other', 'harness': 'claude-code'})
    assert REFUSED in str(refused.value)
    assert workspace.store.list('development_workspace', cid) == []
    with pytest.raises(ValueError, match='harness_mode'):
        development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'mode', 'harness_mode': 'gui'})
    # On a record (written another way): the host never starts it.
    commands = []
    monkeypatch.setattr(development_runtime, 'run', lambda args, **kwargs: commands.append(args) or '')
    monkeypatch.setattr(DockerWorkspace, 'inspect', lambda self, record: None)
    with pytest.raises(ValueError) as refused:
        DockerWorkspace(tmp_path / 'development').start({'id': 'development_other', 'harness': {'name': 'claude-code', 'mode': 'tui'}})
    assert str(refused.value) == REFUSED and commands == []
    assert harness() == {'name': 'pi', 'mode': 'tui'}
    # In the box: start.sh refuses it before it touches anything.
    home = tmp_path / 'home'
    box = subprocess.run(['bash', str(BOX / 'start.sh')], env={**os.environ, 'HOME': str(home), 'BALSAMIC_HARNESS': 'claude-code'},
                         capture_output=True, text=True, timeout=30)
    assert box.returncode == 78 and box.stderr.strip() == REFUSED and not home.exists()
    box = subprocess.run(['bash', str(BOX / 'start.sh')], env={**os.environ, 'HOME': str(home), 'BALSAMIC_HARNESS_MODE': 'gui'},
                         capture_output=True, text=True, timeout=30)
    assert box.returncode == 78 and 'tui, headless' in box.stderr and not home.exists()
    if shutil.which('node'):   # and so does the adapter
        for args in (('configure', '--harness', 'claude-code'), ('command', '--harness', 'claude-code', '--mode', 'tui'),
                     ('run', '--harness', 'claude-code')):
            result = adapter(*args)
            assert result.returncode == 1 and result.stderr.strip().endswith(REFUSED)


def test_the_box_is_started_with_its_harness_and_the_adapter_mounted_read_only(setup, tmp_path, monkeypatch):
    from optimization_framework.agents import development_runtime
    from optimization_framework.agents.development import WorkspaceCreate, request_hash
    from optimization_framework.agents.development_runtime import DockerWorkspace
    workspace, campaign, development, driver = setup
    monkeypatch.setenv('GRATING_DEVELOPMENT_HARNESS_MODE', 'headless')   # the lab's default for new workspaces
    record = development.create(campaign['id'], {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'lab'})
    assert record['harness'] == {'name': 'pi', 'mode': 'headless'}
    commands = []
    monkeypatch.setattr(development_runtime, 'run', lambda args, **kwargs: commands.append(args) or '')
    monkeypatch.setattr(DockerWorkspace, 'inspect', lambda self, record: None)
    DockerWorkspace(tmp_path / 'development').start(record)
    [started] = commands
    assert {'BALSAMIC_HARNESS=pi', 'BALSAMIC_HARNESS_MODE=headless'} <= set(started)
    assert f"type=bind,src={ROOT / 'deploy/implementation-workspace/harness.mjs'},dst=/opt/workspace/harness.mjs,readonly" in started
    commands.clear()
    DockerWorkspace(tmp_path / 'development').start({'id': 'development_old'})   # recorded before H2: Pi's TUI, as before
    assert {'BALSAMIC_HARNESS=pi', 'BALSAMIC_HARNESS_MODE=tui'} <= set(commands[0])
    # A request that names the one harness is the same request as one that names none (workspaces opened before keep their key).
    plain = {'hypothesis_id': 'hypothesis_dev', 'request_key': 'k'}
    assert request_hash(WorkspaceCreate.model_validate({**plain, 'harness': 'pi'})) == request_hash(WorkspaceCreate.model_validate(plain))
    assert request_hash(WorkspaceCreate.model_validate({**plain, 'harness_mode': 'headless'})) != request_hash(WorkspaceCreate.model_validate(plain))


def test_a_failed_headless_run_shows_as_the_workspaces_last_error_and_in_its_history(setup):
    from optimization_framework.agents.development_timeline import timeline
    from test_pi_development_workspaces import outgoing
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'fails', 'harness_mode': 'headless'})
    development.sync(cid)
    error = 'No credential for provider centinels\nRun pi auth to sign in'
    for key, kind, payload in [('e1', 'agent_start', {}), ('e2', 'harness_error', {'harness': 'pi', 'exit_code': 1, 'signal': None, 'error': error}),
                               ('e3', 'agent_settled', {'interrupted': False})]:
        outgoing(driver, record, key, kind, payload)
    development.sync(cid)
    saved = development.public(development.get(cid, record['id']))
    assert saved['last_error_at'] and saved['status'] == 'idle'
    [failed] = [e for e in timeline(workspace.store, development.get(cid, record['id']))['entries'] if e['kind'] == 'harness']
    assert failed['title'] == "The coding agent's run failed: No credential for provider centinels" and failed['tone'] == 'bad'
    assert failed['detail'] == error


@needs_node
def test_the_adapter_points_pi_at_the_mcp_server_and_keeps_its_terminal_command(tmp_path):
    home = tmp_path / 'home'
    (home / '.pi/agent').mkdir(parents=True)
    (home / '.pi/agent/mcp.json').write_text(json.dumps({'mcpServers': {'docs': {'url': 'https://example.com/mcp'}}}))
    env = {**os.environ, 'HOME': str(home)}
    for _ in range(2):   # every start writes it again, the same
        assert adapter('configure', '--harness', 'pi', env=env).returncode == 0
    servers = json.loads((home / '.pi/agent/mcp.json').read_text())['mcpServers']
    assert servers['docs'] == {'url': 'https://example.com/mcp'}
    balsamic = servers['balsamic']
    # A local stdio server: the box's egress gains nothing for it.
    assert balsamic['args'] == [str(BOX / 'balsamic-workspace.mjs'), 'mcp'] and 'url' not in balsamic and balsamic['exposure'] == 'direct'
    # The extension gives Pi checkpoint and submit: their MCP twins are hidden, ask, check and evidence are Pi's through MCP.
    assert balsamic['toolExposure'] == {'checkpoint': 'hidden', 'submit': 'hidden'}
    # A file someone made unreadable is left as it is: the box starts, without the server.
    (home / '.pi/agent/mcp.json').write_text('{"mcpServers": {')
    kept = adapter('configure', '--harness', 'pi', env=env)
    assert kept.returncode == 0 and 'left as it is' in kept.stderr and (home / '.pi/agent/mcp.json').read_text() == '{"mcpServers": {'
    # The terminal UI runs as it did before the adapter; headless, tmux runs the adapter's runner.
    tui = adapter('command', '--harness', 'pi', '--mode', 'tui', '--', *MODEL, '--thinking', 'xhigh', env=env).stdout.strip()
    assert tui == 'pi --provider centinels --model gpt-6.1-sol --thinking xhigh --session /work/sessions/pi.jsonl --extension /opt/workspace/extension.ts'
    headless = adapter('command', '--harness', 'pi', '--mode', 'headless', '--', *MODEL, env=env).stdout.strip()
    assert headless.endswith(f"{BOX / 'harness.mjs'} run --harness pi -- --provider centinels --model gpt-6.1-sol")
