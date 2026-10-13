"""Optional live TensorBoard metrics and atomic best-design snapshots."""
from dataclasses import asdict
import json
import logging
from pathlib import Path
import threading

import numpy as np

from .lifecycle import metric_row


def _summary_writer():
    try:
        from torch.utils.tensorboard import SummaryWriter
    except ImportError as error:
        raise ImportError("TensorBoard logging requires PyTorch: uv sync --extra learners") from error
    return SummaryWriter


def save_best_design(directory, config, design, efficiency, step):
    directory = Path(directory)
    design = np.asarray(design, dtype=np.uint8)
    temporary = directory / "best_design.npy.tmp"
    with temporary.open("wb") as stream:
        np.save(stream, design)
    temporary.replace(directory / "best_design.npy")
    temporary = directory / "best_design.json.tmp"
    temporary.write_text(json.dumps({
        "efficiency": float(efficiency), "step_at_save": int(step),
        "physics": asdict(config.physics), "period_nm": config.physics.period_nm,
        "design": design.tolist(),
    }, indent=2, allow_nan=False) + "\n")
    temporary.replace(directory / "best_design.json")


class RunLogger:
    def __init__(self, directory, config, budget, resume_step=None, interval=100):
        self.writer = None
        self.budget = budget
        self.interval = interval
        self.last_row = None
        self.last_logged_step = None
        if directory is not None:
            self.writer = _summary_writer()(
                str(directory), flush_secs=5,
                purge_step=resume_step + 1 if resume_step is not None else None,
            )
            self.writer.add_text("experiment/config", "```json\n" + json.dumps(config.to_dict(), indent=2) + "\n```", resume_step or 0)

    def __enter__(self):
        return self

    def log(self, row, force=False):
        self.last_row = dict(row)
        step = int(row["step"])
        if self.writer is None or (not force and step % self.interval):
            return
        fields = {
            "efficiency": ("efficiency/current_percent", 100),
            "best_efficiency": ("efficiency/best_discovered_percent", 100),
            "loss": ("learning/td_loss", 1),
            "epsilon": ("learning/epsilon", 1),
            "reward": ("learning/reward", 1),
            "solver_calls": ("compute/rcwa_calls", 1),
            "cache_hits": ("compute/cache_hits", 1),
            "elapsed_seconds": ("compute/elapsed_seconds", 1),
            "episode": ("learning/episode", 1),
        }
        for field, (tag, scale) in fields.items():
            value = row.get(field)
            if value is not None and value != "":
                self.writer.add_scalar(tag, float(value) * scale, step)
        self.writer.add_scalar("progress/completed_percent", 100 * step / self.budget, step)
        elapsed = row.get("elapsed_seconds", 0)
        if elapsed > 0:
            self.writer.add_scalar("compute/steps_per_second", step / elapsed, step)
        self.last_logged_step = step

    def design(self, design, step):
        if self.writer is not None:
            pixels = np.tile((255 * (1 - np.asarray(design, dtype=np.uint8)))[None, :], (16, 1))
            self.writer.add_image("design/best_discovered", pixels, step, dataformats="HW")
            self.writer.flush()

    def __exit__(self, exc_type, exc, traceback):
        if self.writer is not None:
            if self.last_row and self.last_logged_step != self.last_row["step"]:
                self.log(self.last_row, force=True)
            self.writer.close()


class JournalFollower:
    """Mirror a worker's metrics journal into TensorBoard while it is being written.

    The journal remains the experiment record and these events are a disposable
    view of it, so following a run cannot change its numbers. A resumed run
    starts after the rows already recorded and purges the steps it replays.
    """

    def __init__(self, journal, directory, config, method, budget, resumed=False,
                 live=True, interval=100, poll_seconds=5):
        self.journal, self.directory = Path(journal), directory
        self.config, self.method, self.budget = config, method, budget
        self.resumed, self.live, self.interval, self.poll_seconds = resumed, live, interval, poll_seconds
        self.logger = self.thread = self.best = None
        self.stop = threading.Event()
        self.offset = 0
        if directory is not None:
            _summary_writer()  # a missing dependency must fail before any work starts
            if resumed and self.journal.exists():
                self.offset = self.journal.stat().st_size

    def __enter__(self):
        if self.directory is not None and self.live:
            self.thread = threading.Thread(target=self._poll, name="tensorboard-journal", daemon=True)
            self.thread.start()
        return self

    def _poll(self):
        while not self.stop.wait(self.poll_seconds):
            self.sync()

    def sync(self):
        # The view is optional: it must never fail the run it is showing.
        try:
            if not self.journal.exists():
                return
            with self.journal.open("rb") as stream:
                stream.seek(self.offset)
                for raw in stream:
                    if not raw.endswith(b"\n"):
                        break  # an unfinished write is read once it is complete
                    self.offset += len(raw)
                    try:
                        record = json.loads(raw)
                    except ValueError:
                        continue
                    self._record(record)
        except Exception:
            logging.getLogger(__name__).exception("TensorBoard journal projection failed")

    def _record(self, record):
        row = metric_row(record, self.method)
        if row is None:
            return
        if self.logger is None:
            self.logger = RunLogger(self.directory, self.config, self.budget,
                                    resume_step=row["step"] - 1 if self.resumed else None, interval=self.interval)
        best = row["best_efficiency"]
        improved = best is not None and (self.best is None or best > self.best)
        self.logger.log(row, force=improved)
        if improved:
            self.best = best
            self.logger.design(record["best_candidate"], row["step"])

    def __exit__(self, exc_type, exc, traceback):
        if self.directory is None:
            return
        self.stop.set()
        if self.thread is not None:
            self.thread.join()
        self.sync()
        if self.logger is not None:
            self.logger.__exit__(exc_type, exc, traceback)
