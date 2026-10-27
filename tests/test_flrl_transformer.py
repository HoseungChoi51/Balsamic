"""Transformer policies for the FLRL PPO: same loop as the reference, a different feature extractor."""
import pytest

torch = pytest.importorskip('torch')
pytest.importorskip('meent')

from dqn_meent.flrl_ppo import ActorCritic, TransformerFeatures
from dqn_meent.problem_2d import Meent2DProblem
from optimization_framework.optimizers.registry import create, validate_parameters
from test_flrl_optimizers import parameters, problem, step

VARIANTS = [
    {},
    {'transformer_tokens': 'frame', 'transformer_width': 32, 'transformer_layers': 1, 'transformer_heads': 2},
    {'transformer_tokens': 'coefficient_frame', 'transformer_positions': 'fourier_mode', 'transformer_pooling': 'cls'},
    {'transformer_positions': 'fourier_mode', 'transformer_pooling': 'cls', 'transformer_feedforward': 4},
]


@pytest.fixture(autouse=True)
def one_thread():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def settings(variant):
    return {**parameters('flrl_ppo'), 'policy_network': 'transformer', **variant}


@pytest.mark.parametrize('variant', VARIANTS)
def test_transformer_policy_trains_on_real_meent_and_continues_exactly(variant):
    instance = problem(); evaluator = Meent2DProblem().evaluator(instance)
    optimizer = create('flrl_ppo', instance, settings(variant), seed=42, schedule_steps=40)
    assert isinstance(optimizer.ppo.network.features, TransformerFeatures)
    for _ in range(3): step(optimizer, evaluator, instance)
    checkpoint = optimizer.checkpoint(); evaluator_state = evaluator.checkpoint()
    expected = []
    for _ in range(7):
        proposal, measured = step(optimizer, evaluator, instance)
        expected.append((proposal.model_dump(), measured.objectives, optimizer.inspect()))
    resumed = create('flrl_ppo', instance, settings(variant), seed=42, schedule_steps=40)
    resumed.restore(checkpoint)
    evaluator.restore(evaluator_state)
    for proposal, objectives, diagnostics in expected:
        actual, measured = step(resumed, evaluator, instance)
        assert actual.model_dump() == proposal
        assert measured.objectives == objectives
        assert resumed.inspect() == diagnostics
    assert optimizer.ppo.updates > 0 and optimizer.ppo.last_loss != 0


def test_tokens_see_each_coefficient_and_frame_in_the_recorded_order():
    # Two frames of three coefficients; the history is frame-major: [frame 0 | frame 1].
    features = TransformerFeatures(3, 2, (1, 0), {'transformer_width': 8, 'transformer_heads': 2, 'transformer_layers': 1})
    seen = {}
    features.embed.register_forward_hook(lambda module, inputs, output: seen.update(tokens=inputs[0]))
    features(torch.tensor([[1., 2., 3., 10., 20., 30.]]))
    assert seen['tokens'].tolist() == [[[1., 10.], [2., 20.], [3., 30.]]]
    # Modes (kx, ky, imaginary part) for Nx = 1, Ny = 0: cos x, constant, sin x.
    assert features.modes.tolist() == [[1., 0., 0.], [0., 0., 0.], [1., 0., 1.]]


def test_reference_policy_and_its_initialization_are_untouched():
    def build(**options):
        torch.manual_seed(5)
        return ActorCritic(40, 10, frames=4, cnn=True, **options)
    reference, explicit = build(), build(transformer=None, modes=(2, 1))
    assert isinstance(reference.features, torch.nn.Sequential)
    for a, b in zip(reference.parameters(), explicit.parameters(), strict=True):
        assert torch.equal(a, b)


def test_transformer_settings_are_validated_before_any_work():
    instance = problem()
    validate_parameters('flrl_ppo', instance, settings({}))
    with pytest.raises(ValueError, match='policy_network'):
        validate_parameters('flrl_ppo', instance, {**parameters('flrl_ppo'), 'transformer_width': 64})
    with pytest.raises(ValueError, match='divisible'):
        validate_parameters('flrl_ppo', instance, settings({'transformer_width': 30, 'transformer_heads': 4}))
    with pytest.raises(ValueError):
        validate_parameters('flrl_ppo', instance, settings({'transformer_tokens': 'pixels'}))
