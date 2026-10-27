"""H12 R4-A optimizer_v1. Worker owns evaluation/cache/deadline/failure envelope.
Only propose/observe drive scientific state. No direct solves or shared seeds.
"""
import base64
import hashlib
import json
import math
import random
import time

ROWS, COLS = 128, 256
TE = 'te_plus1_transmission'
TM = 'tm_plus1_transmission'
MEAN = 'mean_plus1_transmission'
MIN = 'min_plus1_transmission'


class Expired(Exception):
    pass


def square_xor(mask, side, row, col, check=lambda: None):
    out = bytearray(mask)
    for dy in range(side):
        check()
        for dx in range(side):
            check()
            out[((row + dy) % ROWS) * COLS + (col + dx) % COLS] ^= 1
    return bytes(out)


def rectangle_rotate(mask, height, width, row, col, axis, sign, check=lambda: None):
    """Toroidal extraction; roll INTERNAL contents, not the rectangle origin."""
    out = bytearray(mask)
    for dy in range(height):
        check()
        for dx in range(width):
            check()
            sy = (dy - sign) % height if axis == 0 else dy
            sx = (dx - sign) % width if axis == 1 else dx
            out[((row + dy) % ROWS) * COLS + (col + dx) % COLS] = mask[
                ((row + sy) % ROWS) * COLS + (col + sx) % COLS]
    return bytes(out)


def paired_xor(mask, side, first, second, check=lambda: None):
    return square_xor(square_xor(mask, side, *first, check=check), side, *second, check=check)


class Optimizer:
    supports_failure_observations = True

    def __init__(self, context=None):
        self.context = context or {}

    def initialize(self, problem_descriptor, parameters, seed, declared_assets):
        if declared_assets:
            raise ValueError('H12 declares no shared scored seeds or assets')
        p = dict(parameters)
        # These are envelope settings, never algorithm tuning knobs.
        schema = problem_descriptor.get('candidate_schema', {})
        if schema.get('dimensions', ROWS * COLS) != ROWS * COLS:
            raise ValueError('H12 requires full 128x256 binary masks')
        self.parameters = p
        self.problem = problem_descriptor
        self.identity = json.dumps([problem_descriptor, p.get('evaluation_context')], sort_keys=True)
        self.rng = random.Random(seed)
        self.started = time.monotonic()
        self.elapsed_before = 0.
        self.cache = {}  # completed-score audit only; WORKER owns physical cache lookup
        self.best = self.current = None
        self.best_metrics = self.current_metrics = None
        self.pending = None
        self.phase = 'initialization'
        self.init_done = self.index = self.rejected = self.stall = 0
        self.sequence = 0
        self.request_log = []
        self.termination = None
        self.counters = dict.fromkeys((
            'requests', 'cache_hits', 'attempted_uncached_dual_calls',
            'completed_uncached_dual_calls', 'failures', 'physical_forward_work',
            'unknown_physical_forward_calls', 'backward_calls', 'proposal_requests',
            'initialization_draws', 'restart_draws', 'restarts', 'accepts',
            'rejects', 'neighborhood_switches', 'archive_improvements'), 0)

    def check(self):
        # Researcher rescope: deadlines and blocking-call supervision belong to worker.
        pass

    def coarse(self):
        self.check()
        rows = []
        for _ in range(8):
            self.check()
            bits = []
            for _ in range(16):
                self.check()
                bits.append(self.rng.randrange(2))
            row = bytes(bits)
            expanded = b''.join(bytes([v]) * 16 for v in row)
            rows.extend([expanded] * 16)
        return b''.join(rows)

    def origin(self):
        return self.rng.randrange(ROWS), self.rng.randrange(COLS)

    def generate(self):
        self.check()
        if self.index == 0:
            return square_xor(self.current, self.rng.choice((1, 2, 4, 8, 16)), *self.origin(), check=self.check)
        if self.index == 1:
            return rectangle_rotate(self.current, self.rng.choice((4, 8, 16, 32)),
                                    self.rng.choice((4, 8, 16, 32)), *self.origin(),
                                    self.rng.randrange(2), self.rng.choice((-1, 1)), check=self.check)
        return paired_xor(self.current, self.rng.choice((1, 2, 4, 8)), self.origin(), self.origin(), check=self.check)

    def consume(self, mask, metrics, kind):
        # Archive uses exact score superiority, not the current-state tolerance.
        improved = self.best_metrics is None or metrics[0] > self.best_metrics[0]
        if improved:
            self.best, self.best_metrics = mask, metrics
            self.counters['archive_improvements'] += 1
        if kind == 'initialization':
            if self.current_metrics is None or metrics[0] > self.current_metrics[0]:
                self.current, self.current_metrics = mask, metrics
            self.init_done += 1
            if self.init_done == 4:
                self.phase = 'proposal'
        elif kind == 'restart':
            self.current, self.current_metrics = mask, metrics
            self.index = self.rejected = self.stall = 0
            self.phase = 'proposal'
            self.counters['restarts'] += 1
        else:
            self.stall = 0 if improved else self.stall + 1
            if metrics[0] - self.current_metrics[0] > 1e-12:
                self.current, self.current_metrics = mask, metrics
                self.index = self.rejected = 0
                self.counters['accepts'] += 1
            else:
                self.rejected += 1
                self.counters['rejects'] += 1
            # Restart overrides a simultaneous neighborhood switch.
            if self.stall >= 96:
                self.index = self.rejected = self.stall = 0
                self.phase = 'restart'
            elif self.rejected >= 16:
                self.index = (self.index + 1) % 3
                self.rejected = 0
                self.counters['neighborhood_switches'] += 1

    def propose(self, max_candidates=1):
        if max_candidates < 1 or self.pending is not None:
            raise ValueError('One outstanding proposal required')
        if self.termination:
            return []
        try:
            while True:  # Hits are real algorithm requests, never duplicate retries.
                self.check()
                kind = self.phase
                if kind in ('initialization', 'restart'):
                    self.check()
                    mask = self.coarse()
                    self.counters['initialization_draws' if kind == 'initialization' else 'restart_draws'] += 1
                else:
                    mask = self.generate()
                    self.counters['proposal_requests'] += 1
                self.check()
                self.check()  # cache lookup and cached request loop are deadline bounded
                self.counters['requests'] += 1
                hit = False  # Never bypass canonical worker request/observation lifecycle.
                self.request_log.append({'ordinal': self.counters['requests'], 'kind': kind,
                    'mask_sha256': hashlib.sha256(mask).hexdigest(), 'cache_hit': hit,
                    'neighborhood': self.index, 'rejections_before': self.rejected,
                    'stall_before': self.stall, 'outcome': 'cached' if hit else 'pending'})
                self.check()  # final package-side check before requesting a solve
                self.sequence += 1
                proposal_id = 'h12_' + str(self.sequence)
                self.pending = (proposal_id, mask, kind)
                self.counters['attempted_uncached_dual_calls'] += 1
                return [{'id': proposal_id, 'candidate': list(mask),
                         'metadata': {'h12_kind': kind, 'h12_neighborhood': self.index}}]
        except Expired:
            return []

    def observe(self, observations):
        if len(observations) != 1 or self.pending is None:
            raise ValueError('Expected one pending observation')
        obs = observations[0]
        if hasattr(obs, 'model_dump'):
            obs = obs.model_dump(mode='json')
        pid, mask, kind = self.pending
        if obs.get('proposal_id') != pid or bytes(obs['candidate']) != mask:
            raise ValueError('Observation does not match pending full mask')
        self.pending = None
        worker_hit = bool(obs.get('costs', {}).get('cache_hits', 0) or obs.get('cache_hit', False))
        if worker_hit:
            self.counters['cache_hits'] += 1
            self.counters['attempted_uncached_dual_calls'] -= 1
        self.request_log[-1]['cache_hit'] = worker_hit
        work = obs.get('costs', {}).get('solver_executions')
        if work is None:
            self.counters['unknown_physical_forward_calls'] += 1
        elif isinstance(work, (int, float)) and math.isfinite(work) and work >= 0:
            self.counters['physical_forward_work'] += work
        else:
            self.counters['unknown_physical_forward_calls'] += 1
        try:
            if obs.get('status') != 'ok':
                raise ValueError('Failed evaluation')
            o = obs['objectives']
            if TE in o and TM in o:
                te, tm = float(o[TE]), float(o[TM])
                mean = (te + tm) / 2
                metrics = (mean, te, tm, min(te, tm))
                if not all(math.isfinite(x) for x in metrics):
                    raise ValueError('Nonfinite score')
            else:
                name = self.problem.get('primary_objective', {}).get('name', MEAN)
                mean = float(o[name] if name in o else next(iter(o.values())))
                if not math.isfinite(mean):
                    raise ValueError('Nonfinite scalar score')
                metrics = (mean, None, None, None)  # generic mocks; no fabricated polarization data
        except (KeyError, TypeError, ValueError, OverflowError):
            self.request_log[-1]['outcome'] = 'failed'
            self.counters['failures'] += 1
            self.termination = 'evaluation_failure'
            return
        self.request_log[-1]['outcome'] = 'completed'
        self.request_log[-1]['objectives'] = self.metric_dict(metrics)
        if not worker_hit:
            self.counters['completed_uncached_dual_calls'] += 1
        self.cache[mask] = metrics
        self.consume(mask, metrics, kind)

    def inspect(self):
        return {**self.counters, 'phase': self.phase, 'neighborhood': self.index,
                'rejection_count': self.rejected, 'no_gain_requests': self.stall,
                'initialization_completed': self.init_done, 'cache_entries': len(self.cache),
                'termination': self.termination, 'has_solution': self.best is not None,
                'best_objectives': self.metric_dict(self.best_metrics),
                'worker_seconds': self.elapsed_before + time.monotonic() - self.started,
                'worker_timing_scope': 'package elapsed diagnostic only; worker owns full accounting, cache, deadline, failure and timeout envelope'}

    @staticmethod
    def metric_dict(metrics):
        return dict(zip((MEAN, TE, TM, MIN), metrics)) if metrics else None

    def export_artifacts(self):
        # Kinds are the catalog's: the best mask is a solution, the request log a diagnostic of the search.
        events = {'kind': 'learner_diagnostics', 'format': 'h12-request-log-v1', 'media_type': 'application/json',
                  'data': list(self.request_log)}
        if self.best is None:
            return [events]
        return [{'kind': 'solution', 'format': 'h12-best-binary-v1', 'media_type': 'application/json',
                 'data': {'shape': [ROWS, COLS], 'candidate': list(self.best),
                          'objectives': self.metric_dict(self.best_metrics)}}, events]

    def checkpoint(self):
        def encode(value):
            if isinstance(value, bytes):
                return {'bytes': base64.b64encode(value).decode()}
            if isinstance(value, tuple):
                return {'tuple': [encode(x) for x in value]}
            if isinstance(value, dict):
                return {'dict': [[encode(k), encode(v)] for k, v in value.items()]}
            if isinstance(value, list):
                return [encode(x) for x in value]
            if isinstance(value, float) and math.isinf(value):
                return {'infinity': value > 0}
            return value
        state = dict(self.__dict__)
        state.pop('rng')
        state['rng_state'] = self.rng.getstate()
        state['elapsed_before'] = self.elapsed_before + time.monotonic() - self.started
        return json.dumps(encode(state), allow_nan=False).encode()

    def restore(self, raw):
        def decode(value):
            if isinstance(value, dict):
                if 'bytes' in value:
                    return base64.b64decode(value['bytes'])
                if 'tuple' in value:
                    return tuple(decode(x) for x in value['tuple'])
                if 'dict' in value:
                    return {decode(k): decode(v) for k, v in value['dict']}
                if 'infinity' in value:
                    return math.inf if value['infinity'] else -math.inf
            if isinstance(value, list):
                return [decode(x) for x in value]
            return value
        state = decode(json.loads(raw))
        if state['identity'] != self.identity:
            raise ValueError('Frozen evaluator/problem identity changed')
        rng_state = state.pop('rng_state')
        self.__dict__.update(state)
        self.rng = random.Random()
        self.rng.setstate(rng_state)
        self.started = time.monotonic()


def create_optimizer(context):
    return Optimizer(context)
