"""R4-C archive relinking; optimizer_v1, no evaluator access.

Rows are y, columns x. x-first means x is the fast traversal axis.
The trusted parent owns evaluation, timeout, physical costs and the exact cache.
"""
import hashlib
import json
import math
import pickle
import random
import time

H, W = 128, 256
MEAN = 'mean_plus1_transmission'
TE, TM, MIN = 'te_plus1_transmission', 'tm_plus1_transmission', 'min_plus1_transmission'


def distance(a, b):
    return (int.from_bytes(a, 'little') ^ int.from_bytes(b, 'little')).bit_count()


def corridor(a, b, origin, x_first, stop=lambda: False):
    oy, ox = origin
    ys = [(oy + y) % H for y in range(H)]
    xs = [(ox + x) % W for x in range(W)]
    cells = ((y * W + x for y in ys for x in xs) if x_first else
             (y * W + x for x in xs for y in ys))
    result = []
    for j, i in enumerate(cells):
        if j % 256 == 0 and stop():
            return ()
        if a[i] != b[i]:
            result.append(i)
    return tuple(result)


class Optimizer:
    def __init__(self, context):
        self.context = context

    def initialize(self, problem_descriptor, parameters, seed, declared_assets):
        if parameters or declared_assets:
            raise ValueError('R4-C has no tunable parameters or scored assets')
        p = problem_descriptor
        if p.get('candidate_schema', {}).get('dimensions') != H * W:
            raise ValueError('R4-C requires 128x256 full binary masks')
        # Published descriptors may expose selected public fields or full
        # configuration. Fixed 32768-dimensional R4-C supplies the shape when
        # those optional public grid keys are absent; reject any contradiction.
        layouts = [p] + [p.get(k, {}) for k in
                         ('configuration', 'public', 'public_descriptor')]
        for config in layouts:
            if not isinstance(config, dict):
                continue
            if (('grid_x' in config and config['grid_x'] != W) or
                    ('grid_y' in config and config['grid_y'] != H)):
                raise ValueError('Wrong row-major shape')
        self.objective_name = p['primary_objective']['name']
        self.objective_direction = p['primary_objective'].get('direction', 'maximize')
        self.scope = json.dumps(p, sort_keys=True, separators=(',', ':'), allow_nan=False)
        self.identity = p.get('evaluation_identity')
        self.fidelity = p.get('fidelity')
        self.rng = random.Random(seed)
        self.deadline = None  # Trusted worker owns deadlines and clean stopping.
        self.started = time.monotonic()
        self.prior_seconds = 0.
        self.cache, self.elite, self.spread = {}, [], []
        self.best = None
        self.pending = None
        self.phase, self.index, self.episode, self.stalls = 'init', 0, 1, 0
        self.a = self.b = None
        self.order = ()
        self.episode_best = None
        self.terminal = None
        self.unknown_forward = False
        self.counts = dict(requests=0, cache_hits=0, attempted=0, completed=0,
                           failures=0, physical_forward=0, backward=0, decisions=0,
                           episodes=0, injections=0)

    def expired(self):
        if self.deadline is not None and time.time() >= self.deadline:
            self.terminal = self.terminal or 'deadline'
        return self.terminal is not None

    def coarse(self):
        bits = [self.rng.getrandbits(1) for _ in range(128)]
        rows = []
        for y in range(H):
            if self.expired():
                return None
            rows.append(bytes(bits[(y // 16) * 16 + x // 16] for x in range(W)))
        return b''.join(rows)

    def local(self):
        side = self.rng.choice((1, 2, 4, 8, 16))
        y, x = self.rng.randrange(H), self.rng.randrange(W)
        m = bytearray(self.best[0])
        for dy in range(side):
            if self.expired():
                return None
            for dx in range(side):
                m[((y + dy) % H) * W + (x + dx) % W] ^= 1
        return bytes(m)

    def offer(self, entry):
        # entry=(immutable mask, actual mean, first completed insertion, metrics)
        if self.best is None or entry[1] > self.best[1]:
            self.best = entry
        old = self.elite
        unique = {e[0]: e for e in old}
        unique[entry[0]] = entry
        self.elite = sorted(unique.values(), key=lambda e: (-e[1], e[2]))[:4]
        excluded = {e[0] for e in self.elite}
        pool = {e[0]: e for e in self.spread + old + [entry] if e[0] not in excluded}
        chosen = []
        while pool:
            if self.expired():
                return
            references = self.elite + chosen
            e = max(pool.values(), key=lambda e: (min(distance(e[0], r[0]) for r in references), -e[2]))
            chosen.append(e)
            del pool[e[0]]
            if len(chosen) == 4:
                break
        self.spread = chosen

    def start_episode(self):
        self.a = self.best[0]
        self.episode_best = self.best[1]
        pool = self.elite if self.episode % 2 else self.spread
        pool = [e for e in pool if e[0] != self.a]
        if not pool:
            pool = [e for e in self.elite + self.spread if e[0] != self.a]
        self.index = 0
        if not pool:
            self.b, self.order, self.phase = None, (), 'local'
            return
        self.b = max(pool, key=lambda e: (distance(self.a, e[0]), -e[2]))[0]
        origin = self.rng.randrange(H), self.rng.randrange(W)
        self.order = corridor(self.a, self.b, origin, bool(self.rng.getrandbits(1)), self.expired)
        self.phase = 'corridor'

    def next_mask(self):
        while not self.expired():
            if self.phase == 'init':
                if self.index < 4:
                    return self.coarse()
                self.start_episode()
            elif self.phase == 'corridor':
                if self.index < 7:
                    m = bytearray(self.b)
                    n = ((self.index + 1) * len(self.order) + 7) // 8
                    for j, i in enumerate(self.order[:n]):
                        if j % 256 == 0 and self.expired():
                            return None
                        m[i] = self.a[i]
                    return bytes(m)
                self.phase, self.index = 'local', 0
            elif self.phase == 'local':
                if self.index < 4:
                    return self.local()
                self.counts['episodes'] += 1
                self.stalls = 0 if self.best[1] > self.episode_best else self.stalls + 1
                self.episode += 1
                if self.stalls == 2:
                    self.phase, self.index = 'inject', 0
                    self.counts['injections'] += 1
                else:
                    self.start_episode()
            elif self.phase == 'inject':
                if self.index < 2:
                    return self.coarse()
                self.stalls = 0
                self.start_episode()
        return None

    def propose(self, max_candidates):
        if max_candidates < 1 or self.expired():
            return []
        if self.pending is not None:
            raise ValueError('Only one outstanding proposal allowed')
        while not self.expired():
            m = self.next_mask()
            if m is None or self.expired():
                return []
            self.counts['requests'] += 1
            # Every algorithm request is exposed; worker owns the exact cache.
            pid = str(self.counts['requests'])
            self.pending = (pid, m, m in self.cache)
            return [{'id': pid, 'candidate': list(m)}]
        return []

    def observe(self, observations):
        for obs in observations:
            if hasattr(obs, 'model_dump'):
                obs = obs.model_dump(mode='json')
            if self.pending is None or obs['proposal_id'] != self.pending[0]:
                raise ValueError('Unexpected observation')
            _, m, hit = self.pending
            self.pending = None
            costs = obs.get('costs', {})
            physical = costs.get('solver_executions')
            if physical is not None:
                self.counts['physical_forward'] += physical
            else:
                self.unknown_forward = True
            worker_hit = bool(costs.get('cache_hits', 0))
            self.counts['cache_hits' if worker_hit else 'attempted'] += 1
            try:
                if obs.get('status') != 'ok':
                    raise ValueError('Failed evaluation')
                metrics = {k: float(v) for k, v in obs['objectives'].items()}
                if not all(math.isfinite(v) for v in metrics.values()):
                    raise ValueError('Nonfinite evaluation')
                raw = metrics[self.objective_name]
                score = raw if self.objective_direction == 'maximize' else -raw
            except (KeyError, TypeError, ValueError):
                self.counts['failures'] += 1
                self.terminal = 'evaluation_failed'
                return
            if not worker_hit:
                self.counts['completed'] += 1
            if not hit:
                # First successful insertion ordinal is independent of solver/cache.
                self.cache[m] = (m, score, len(self.cache) + 1, metrics)
            self.offer(self.cache[m])
            self.counts['decisions'] += 1
            self.index += 1

    def inspect(self):
        return {**self.counts, 'phase': self.phase, 'index': self.index,
                'episode': self.episode, 'stalls': self.stalls, 'terminal': self.terminal,
                'elite': [e[2] for e in self.elite], 'spread': [e[2] for e in self.spread],
                'best_objectives': dict(self.best[3]) if self.best else None,
                'full_optimizer_seconds': self.prior_seconds + time.monotonic() - self.started,
                'physical_forward_unknown': self.unknown_forward,
                'scope_sha256': hashlib.sha256(self.scope.encode()).hexdigest()}

    def checkpoint(self):
        state = dict(self.__dict__)
        state['prior_seconds'] = self.prior_seconds + time.monotonic() - self.started
        state.pop('started')
        return pickle.dumps(state, protocol=4)

    def restore(self, data):
        state = pickle.loads(data)
        if state['scope'] != self.scope:
            raise ValueError('Checkpoint evaluator scope mismatch')
        deadline = self.deadline
        self.__dict__.update(state)
        self.deadline = deadline
        self.started = time.monotonic()

    def export_artifacts(self):
        return []


def create_optimizer(context):
    return Optimizer(context)
