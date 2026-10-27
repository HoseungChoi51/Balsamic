"""The coding box's balsamic-workspace CLI writes events the host's receive() accepts (roadmap H1)."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from test_pi_development_workspaces import REPORT, setup  # noqa: F401  (setup is a fixture)

CLI = Path(__file__).resolve().parents[1] / 'deploy/implementation-workspace/balsamic-workspace.mjs'
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='the CLI runs on Node, which the workspace image has')


def bridge(tmp_path, driver, record):
    # The container's /bridge: in/ is the host's incoming/, out/ its outgoing/.
    path = tmp_path / 'bridge'
    path.mkdir(exist_ok=True)
    for inside, host in (('in', 'incoming'), ('out', 'outgoing')):
        if not (path / inside).exists():
            (path / inside).symlink_to(driver.root(record) / host)
    return {**os.environ, 'GRATING_DEVELOPMENT_BRIDGE': str(path)}


def cli(env, *args):
    result = subprocess.run(['node', str(CLI), *args], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_cli_reports_progress_asks_and_submits_through_the_same_bridge(setup, tmp_path):
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'cli'})
    development.sync(cid)
    env = bridge(tmp_path, driver, record)

    cli(env, 'checkpoint', '--summary', 'Testing', '--phase', 'testing', '--eta', '8', '--tests', '30/2', '--remaining', 'seed replay')
    development.sync(cid)
    saved = development.public(development.get(cid, record['id']))
    assert saved['phase'] == 'testing' and saved['tests'] == {'passed': 30, 'failed': 2, 'skipped': 0}
    assert saved['estimate']['remaining_minutes'] == 8 and saved['checkpoints'][0]['remaining'] == ['seed replay']

    cli(env, 'ask', 'Should the seed be configurable?')
    development.sync(cid)
    [question] = development.public(development.get(cid, record['id']))['questions']
    assert question['question'] == 'Should the seed be configurable?' and question['status'] == 'pending'

    report = tmp_path / 'report.json'
    report.write_text(json.dumps(REPORT))
    child = subprocess.Popen(['node', str(CLI), 'submit', 'b' * 40, '--report', str(report)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    events = driver.root(record) / 'outgoing/events'
    for _ in range(200):
        if any(events.glob('*.json')):
            break
        time.sleep(0.05)
    development.sync(cid)
    out, err = child.communicate(timeout=60)
    assert child.returncode == 0, err
    [submission] = workspace.store.list('development_submission', cid)
    assert submission['commit'] == 'b' * 40 and submission['report']['verdict'] == 'ready_with_limits'
    assert json.loads(out)['submission_id'] == submission['id']
