"""Host ask/tell wrapper. No evaluation, charging, caching or deadline ownership here."""
import copy
from math import isclose


class OneShot:
    def __init__(self, name, instance, problem):
        from .methods import METHODS
        if name not in METHODS:
            raise ValueError('unknown oven method')
        self.name, self.instance, self.problem = name, instance, problem
        self.result, self.phase, self.verified = None, 'new', False

    def propose(self, max_candidates=1):
        from optimization_framework.contracts.problems import Proposal
        from optimization_framework.optimizers.finish import MethodFinished
        if max_candidates < 1:
            raise ValueError('positive batch size required')
        if self.phase == 'pending':
            raise ValueError('observe outstanding proposal first')
        if self.phase == 'done':
            raise MethodFinished('one construction evaluated')
        from .methods import construct
        self.result = construct(self.name, self.problem)
        self.phase = 'pending'
        return [Proposal(id='oven_candidate', candidate=self.result['order'])]

    def observe(self, observations):
        from .objective import objective, permutation
        if self.phase != 'pending' or len(observations) != 1:
            raise ValueError('one outstanding observation required')
        o = observations[0]
        if o.proposal_id != 'oven_candidate' or permutation(o.candidate, self.problem.dimensions) != self.result['order']:
            raise ValueError('observation does not match proposal')
        # Proof is checked with the actual evaluator arithmetic, never a synthetic score.
        independently_scored = objective(self.problem, self.result['order'])
        observed = o.objectives.get(self.instance.primary_objective.name)
        self.verified = (o.status == 'ok' and o.evaluator_identity == self.instance.evaluation_identity
                         and observed is not None
                         and isclose(observed, independently_scored, rel_tol=1e-12, abs_tol=1e-12)
                         and isclose(self.result['objective'], independently_scored, rel_tol=1e-12, abs_tol=1e-12))
        self.phase = 'done'

    def inspect(self):
        shown = {'phase': self.phase, 'evaluations': int(self.phase == 'done')}
        if self.result is not None:
            shown.update({k: v for k, v in self.result.items() if k not in ('order', 'objective')})
        if self.name == 'oven_subset_dp' and self.verified:
            shown.update(bound=self.result['objective'], proved_optimal=True)
        return shown

    def checkpoint(self):
        return copy.deepcopy(dict(identity=self.instance.evaluation_identity, method=self.name,
                                  phase=self.phase, result=self.result, verified=self.verified))

    def restore(self, state):
        if state.get('identity') != self.instance.evaluation_identity or state.get('method') != self.name:
            raise ValueError('checkpoint belongs to another method or evaluator identity')
        if state.get('phase') not in ('new', 'pending', 'done'):
            raise ValueError('invalid checkpoint phase')
        self.phase, self.result, self.verified = state['phase'], copy.deepcopy(state['result']), state['verified']

    def export_artifacts(self):
        return []

    def close(self):
        pass
