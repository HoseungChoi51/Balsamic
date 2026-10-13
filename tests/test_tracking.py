import json
from pathlib import Path
import time

import numpy as np
import pytest

pytest.importorskip("tensorboard")
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

from dqn_meent.config import ExperimentConfig, PhysicsConfig, TrainConfig
from dqn_meent.recorded import execute
from dqn_meent.tracking import JournalFollower, RunLogger
from dqn_meent.training import train

BEST = "efficiency/best_discovered_percent"


def record(decisions, best, reward=1.0):
    return {"step": decisions, "objective": best, "best_objective": best, "best_candidate": [1, 0, 1, 1],
            "evaluations": decisions, "solver_calls": decisions, "cache_hits": 0, "elapsed_seconds": float(decisions),
            "diagnostics": {"decisions": decisions, "reward": reward, "epsilon": .5}}


def append(journal, *records):
    with journal.open("a") as stream:
        for row in records:
            stream.write(json.dumps(row) + "\n")


def best_scalars(directory):
    if not Path(directory).exists():
        return []
    events = EventAccumulator(str(directory)).Reload()
    return events.Scalars(BEST) if BEST in events.Tags()["scalars"] else []


def test_live_logging_preserves_training_and_saves_matching_design(tmp_path):
    config = ExperimentConfig(PhysicsConfig(n_cells=4, fourier_order=1), TrainConfig(
        total_steps=8, horizon=3, batch_size=2, buffer_size=32,
        learning_starts=2, hidden_sizes=(8, 8), checkpoint_interval=4,
    ))
    plain = train(config, tmp_path / "plain")
    logged = train(config, tmp_path / "logged", tensorboard_dir=tmp_path / "events")
    for key in ("best_efficiency", "last_efficiency", "last_loss", "updates", "solver_calls", "cache_hits"):
        assert logged[key] == plain[key]
    np.testing.assert_array_equal(np.load(plain["best_design"]), np.load(logged["best_design"]))
    events = EventAccumulator(str(tmp_path / "events")).Reload()
    scalar = events.Scalars("efficiency/best_discovered_percent")[-1]
    assert scalar.step == 8
    assert scalar.value == pytest.approx(logged["best_efficiency"] * 100)
    assert events.Images("design/best_discovered")


def test_resumed_events_purge_steps_after_durable_checkpoint(tmp_path):
    config = ExperimentConfig()
    with RunLogger(tmp_path, config, budget=10, interval=1) as logger:
        logger.log(dict(step=4, best_efficiency=.4))
        logger.log(dict(step=5, best_efficiency=.9))
    with RunLogger(tmp_path, config, budget=10, resume_step=4, interval=1) as logger:
        logger.log(dict(step=5, best_efficiency=.5))
    events = EventAccumulator(str(tmp_path)).Reload().Scalars("efficiency/best_discovered_percent")
    assert [event.step for event in events] == [4, 5]
    assert [event.value for event in events] == pytest.approx([40, 50])


def test_follower_shows_rows_while_the_run_is_still_writing(tmp_path):
    journal, events = tmp_path / "metrics.jsonl", tmp_path / "events"
    with JournalFollower(journal, events, ExperimentConfig(), "dqn", budget=2, interval=1, poll_seconds=.01):
        append(journal, record(1, .1))
        with journal.open("a") as stream:
            stream.write('{"step": 2')  # an unfinished write is not an observation
        deadline = time.monotonic() + 30
        while not best_scalars(events) and time.monotonic() < deadline:
            time.sleep(.05)
        assert [event.step for event in best_scalars(events)] == [1]
    assert [event.step for event in best_scalars(events)] == [1]
    assert EventAccumulator(str(events)).Reload().Images("design/best_discovered")


def test_resumed_follower_skips_recorded_rows_and_purges_replayed_steps(tmp_path):
    journal, events = tmp_path / "metrics.jsonl", tmp_path / "events"
    config = ExperimentConfig()
    append(journal, record(1, .1), record(2, .2), record(3, .9))
    with JournalFollower(journal, events, config, "dqn", budget=4, interval=1, live=False):
        pass
    with JournalFollower(journal, events, config, "dqn", budget=4, resumed=True, interval=1, live=False):
        # Recovery from the checkpoint at decision 2 resets the episode, then repeats decision 3.
        append(journal, record(2, .2, reward=None), record(3, .3), record(4, .4))
    assert [event.step for event in best_scalars(events)] == [1, 2, 3, 4]
    assert [event.value for event in best_scalars(events)] == pytest.approx([10, 20, 30, 40])


def test_cli_run_follows_its_local_workspace_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    config = ExperimentConfig(PhysicsConfig(n_cells=4, fourier_order=1), TrainConfig(
        total_steps=4, horizon=3, batch_size=2, buffer_size=16, learning_starts=2, hidden_sizes=(8, 8), checkpoint_interval=2))
    result = execute(config, tmp_path / "run", method="random", budget=3, seed=7, wall_seconds=30,
        tensorboard_dir=tmp_path / "events")
    scalar = best_scalars(tmp_path / "events")[-1]
    assert scalar.step == 3
    assert scalar.value == pytest.approx(result["best_efficiency"] * 100)
