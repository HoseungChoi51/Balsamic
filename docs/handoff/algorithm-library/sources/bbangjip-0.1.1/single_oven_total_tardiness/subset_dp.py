"""One-shot optimizer_v1, using only the public problem descriptor."""
import json

from .methods import solve
from .objective import order_data


class Optimizer:
    def initialize(self, problem, parameters, seed, assets):
        if parameters:
            raise ValueError('subset DP has no configurable parameters')
        names, p, d, _ = order_data(problem['public'])
        if problem['candidate_schema']['dimensions'] != len(names):
            raise ValueError('descriptor dimension differs from n_orders')
        self.order, self.bound = solve(p, d)
        self.phase = 'ready'

    def propose(self, max_candidates=1):
        if max_candidates < 1:
            raise ValueError('max_candidates must be positive')
        if self.phase == 'done':
            return []
        if self.phase == 'pending':
            raise ValueError('observe outstanding proposal first')
        self.phase = 'pending'
        return [{'id': 'subset_dp_optimum', 'candidate': list(self.order)}]

    def observe(self, observations):
        if self.phase != 'pending' or len(observations) != 1 or observations[0]['proposal_id'] != 'subset_dp_optimum':
            raise ValueError('observation does not match pending proposal')
        self.phase = 'done'

    def checkpoint(self):
        return json.dumps({'version': 1, 'order': self.order, 'bound': self.bound,
                           'phase': self.phase}, allow_nan=False).encode()

    def restore(self, checkpoint):
        state = json.loads(checkpoint)
        if state['version'] != 1 or state['order'] != self.order or state['bound'] != self.bound:
            raise ValueError('incompatible checkpoint')
        if state['phase'] not in ('ready', 'pending', 'done'):
            raise ValueError('invalid checkpoint phase')
        self.phase = state['phase']

    def inspect(self):
        return {'phase': self.phase, 'best_bound': self.bound,
                'proved_optimal': True, 'subsets': 1 << len(self.order)}


def create_optimizer(context):
    return Optimizer()
