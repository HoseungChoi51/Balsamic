"""optimizer_v1 seam: proposals only, external trusted observations."""
import json
import math
from .common import inputs, permutation
from ._swap_core import SwapSearch


class Optimizer:
    def __init__(self, context, kind):
        self.n = context['dimensions']
        self.kind = kind

    def initialize(self, problem, parameters, seed, assets):
        if parameters:
            raise ValueError('no method parameters supported')
        schema = problem['candidate_schema']
        if schema['representation'] != 'permutation' or schema['dimensions'] != self.n:
            raise ValueError('permutation dimensions required')
        objective = problem['primary_objective']
        if objective['direction'] != 'minimize':
            raise ValueError('total tardiness must be minimized')
        self.objective = objective['name']
        self.problem = problem
        self.count, self.pending = 0, None
        self.search = SwapSearch(self.n, seed) if self.kind == 'swap' else None
        self.order = None
        if self.kind != 'swap':
            public = problem['public']
            p, d = inputs(public['processing'], public['due'])
            if len(p) != self.n:
                raise ValueError('public vectors must match dimensions')
            if self.kind == 'dp':
                from .subset_dp import solve
            else:
                from .due_date_insertion import solve
            self.order = list(solve(p, d).order)

    def propose(self, max_candidates=1):
        if type(max_candidates) is not int or max_candidates < 1:
            raise ValueError('positive batch size required')
        if self.pending is not None:
            raise ValueError('observe outstanding proposal first')
        if self.kind != 'swap' and self.count:
            return []
        candidate = self.search.ask().tolist() if self.search else list(self.order)
        self.pending = {'id': str(self.count), 'candidate': candidate}
        return [dict(self.pending)]

    def observe(self, observations):
        if self.pending is None or len(observations) != 1:
            raise ValueError('one outstanding observation required')
        obs = observations[0]
        if obs['proposal_id'] != self.pending['id'] or list(permutation(obs['candidate'], self.n)) != self.pending['candidate']:
            raise ValueError('observation does not match proposal')
        if obs['status'] != 'ok':
            raise ValueError('a successful finite observation is required')
        score = float(obs['objectives'][self.objective])
        if not math.isfinite(score):
            raise FloatingPointError('nonfinite objective')
        if self.search:
            self.search.tell(self.pending['candidate'], -score)
        self.count += 1
        self.pending = None

    def checkpoint(self):
        return json.dumps({'version': 1, 'kind': self.kind, 'problem': self.problem,
                           'count': self.count, 'pending': self.pending, 'order': self.order,
                           'search': self.search.state_dict() if self.search else None}, allow_nan=False).encode()

    def restore(self, checkpoint):
        state = json.loads(checkpoint)
        if state['version'] != 1 or state['kind'] != self.kind or state['problem'] != self.problem:
            raise ValueError('checkpoint belongs to another method/problem')
        self.count, self.pending, self.order = state['count'], state['pending'], state['order']
        if self.search:
            self.search.load_state_dict(state['search'])

    def inspect(self):
        return {'observations': self.count, 'pending': self.pending is not None,
                **(self.search.diagnostics() if self.search else {'finished': self.count > 0})}
