import csv

import numpy as np

from dqn_meent.config import ExperimentConfig, PhysicsConfig
from dqn_meent.experiments import baseline
from optimization_framework.execution.worker import read_journal


def test_recorded_prefix_matches_standalone_shorter_search(tmp_path):
    config = ExperimentConfig(physics=PhysicsConfig(n_cells=4, fourier_order=1))
    full = baseline(config, tmp_path / "full", "hillclimb", 20, 7)
    prefix = baseline(config, tmp_path / "short", "hillclimb", 10, 7)
    def rows(run):
        with (tmp_path / run / "metrics.csv").open() as stream:
            return [{key: row[key] for key in ("step", "efficiency", "best_efficiency", "solver_calls", "cache_hits")}
                    for row in csv.DictReader(stream)]
    assert len(rows("full")) == 20 and rows("full")[:10] == rows("short")
    journal = [row for row in read_journal(tmp_path / "full/metrics.jsonl") if row["step"] <= 10]
    tenth = journal[-1]
    assert tenth["best_objective"] == prefix["best_efficiency"]
    assert tenth["solver_calls"] == prefix["solver_calls"]
    # A row gives the best design only where it changed.
    best = [row["best_candidate"] for row in journal if "best_candidate" in row][-1]
    np.testing.assert_array_equal(best, np.load(tmp_path / "short/best_design.npy"))
    assert full["seed"] == prefix["seed"] == 7
