"""The CUDA solver checkout must reproduce the installed CPU evaluator.

Run with GRATING_MEENT_2D_SOURCE naming the checkout; skipped otherwise.
"""
import os

import numpy as np
import pytest

pytest.importorskip("meent")
torch = pytest.importorskip("torch")

from dqn_meent.fourier import FourierGeometry
from dqn_meent.problem_2d import Meent2DProblem
from optimization_framework.execution.source import runtime_identity
from test_meent_2d_problem import configuration

SOURCE = os.environ.get("GRATING_MEENT_2D_SOURCE")
pytestmark = pytest.mark.skipif(not SOURCE or not torch.cuda.is_available(),
                                reason="needs GRATING_MEENT_2D_SOURCE and a CUDA device")


def test_cuda_checkout_matches_installed_cpu_scores_and_gradients(monkeypatch):
    adapter = Meent2DProblem()
    # 91 harmonics: large enough for the checkout's mixed-precision eigensolver route.
    instance = adapter.resolve(configuration(), {"rcwa_order_x": 6, "rcwa_order_y": 3})
    geometry = FourierGeometry(2, 1, 16, 8)
    rng = np.random.default_rng(3)
    coefficients = [rng.normal(size=geometry.dimensions) for _ in range(3)]
    monkeypatch.delenv("GRATING_MEENT_2D_SOURCE")
    reference = adapter.evaluator(instance)
    assert "meent_2d_source" not in runtime_identity()
    monkeypatch.setenv("GRATING_MEENT_2D_SOURCE", SOURCE)
    accelerated = adapter.evaluator(instance)
    assert runtime_identity()["meent_2d_source"].split("@")[0] == os.path.basename(os.path.normpath(os.path.expanduser(SOURCE)))
    for vector in coefficients:
        expected, measured = reference.evaluate(geometry.mask(vector)), accelerated.evaluate(geometry.mask(vector))
        for name, value in expected.objectives.items():
            assert measured.objectives[name] == pytest.approx(value, abs=1e-9)
        assert measured.metadata["meent"]["device"] == "cuda"
        assert measured.metadata["meent"]["source"] == runtime_identity()["meent_2d_source"]
        assert set(expected.metadata["meent"]) == {"version", "energy_totals"}
        request = geometry.gradient_request(vector, 8.0)
        a, b = reference.relaxed_gradient(request), accelerated.relaxed_gradient(request)
        np.testing.assert_allclose(b["gradient"], a["gradient"], rtol=0, atol=1e-7)
        assert b["mean"] == pytest.approx(a["mean"], abs=1e-9)
