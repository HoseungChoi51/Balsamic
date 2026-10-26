"""H13 / immutable R4-B. No evaluator imports or physical execution authority."""
import base64
import hashlib
import json
import math
import random
import time
import zlib

EVENTS_SHOWN = 20
GRIDS = ((8, 16), (16, 16), (16, 32), (32, 32), (32, 64),
         (64, 64), (64, 128), (128, 128), (128, 256))
TE = 'te_plus1_transmission'
TM = 'tm_plus1_transmission'
MIN = 'min_plus1_transmission'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def create_optimizer(context):
    return Mirror(context)


class Mirror:
    def __init__(self, context=None):
        self.context = context or {}

    def initialize(self, problem_descriptor, parameters, seed, declared_assets):
        self.started = time.time()
        self.problem = problem_descriptor
        self.parameters = parameters
        # Compatibility rescope: worker owns deadline, physical fidelity and costs.
        self.deadline = parameters.get('absolute_deadline')
        if self.deadline is not None and (not isinstance(self.deadline, (int, float)) or not math.isfinite(self.deadline)):
            raise ValueError('Optional absolute_deadline must be finite epoch seconds')
        self.mono_deadline = (time.monotonic() + max(0, self.deadline - time.time())
                              if self.deadline is not None else None)
        self.fidelity = problem_descriptor.get('fidelity')
        self.identity = None
        self.rng = random.Random(seed)
        self.level = self.stage = self.no_new = 0
        self.p = [0.5] * 128
        self.perm = []
        self.cursor = 0
        self.cache = {}  # exact bytes -> immutable tuple (J, TE, TM, min, ordinal)
        self.best = None
        self.pending = None
        self.batch = None
        self.events = []
        self.visited = [set() for _ in GRIDS]
        self.status = 'running'
        self.counters = dict(requests=0, cache_hits=0, attempted=0, completed=0,
                             failures=0, physical_forward=0, backward=0,
                             batches=0, resets=0, refinements=0, decisions=0)
        self._alive()

    def _alive(self):
        if self.status != 'running':
            return False
        if self.deadline is not None and (time.time() >= self.deadline or time.monotonic() >= self.mono_deadline):
            self._stop('deadline')
            return False
        return True

    def _stop(self, reason):
        # Threshold interruption also discards its provisional probability update.
        if self.batch is not None:
            self.p = self.batch['old'][:]
        self.batch = None
        self.status = reason

    def _shuffle(self):
        if not self._alive():
            return False
        self.perm = list(range(len(self.p)))
        self.rng.shuffle(self.perm)
        self.cursor = 0
        return self._alive()

    def _begin(self):
        if not self._alive():
            return False
        old = self.p[:]
        bg = []
        for p in old:
            if not self._alive():
                return False
            bg.append(int(self.rng.random() < p))
        selected = []
        seen = set()
        while len(selected) < 16:
            if not self._alive():
                return False
            if self.cursor == len(self.perm) and not self._shuffle():
                return False
            i = self.perm[self.cursor]
            self.cursor += 1
            if i not in seen:
                seen.add(i)
                selected.append(i)
        self.batch = dict(old=old, bg=bg, selected=selected, phase=0,
                          scores=[], fresh=False, updated=False)
        self.events.append(dict(event='begin', level=self.level, selected=selected[:]))
        return True

    def _expand(self, bits):
        rows, cols = GRIDS[self.level]
        sy, sx = 128 // rows, 256 // cols
        out = bytearray()
        for y in range(rows):
            if not self._alive():
                return None
            row = b''.join(bytes([b]) * sx for b in bits[y * cols:(y + 1) * cols])
            out.extend(row * sy)
        return bytes(out)

    def _mask(self):
        b = self.batch
        phase = b['phase']
        bits = b['bg'][:]
        if 1 <= phase <= 16:
            bits[b['selected'][phase - 1]] ^= 1
        elif phase == 17:
            if not b['updated']:
                # Every delta uses the SAME frozen BG and orientation forced1-forced0.
                new = b['old'][:]
                for k, i in enumerate(b['selected']):
                    if not self._alive():
                        return None
                    delta = b['scores'][k + 1] - b['scores'][0]
                    if b['bg'][i]:
                        delta = -delta
                    p = b['old'][i]
                    x = math.log(p / (1 - p)) + 0.5 * delta
                    q = 1 / (1 + math.exp(-max(-700, min(700, x))))
                    new[i] = max(0.05, min(0.95, q))
                self.p = new
                b['updated'] = True
            bits = [int(p >= 0.5) for p in self.p]
        return self._expand(bits)

    def propose(self, max_candidates=1):
        if self.pending:
            raise ValueError('One outstanding proposal only')
        if max_candidates < 1:
            raise ValueError('Positive candidate capacity required')
        while self._alive():
            if self.batch is None and not self._begin():
                break
            mask = self._mask()
            if mask is None or not self._alive():
                break
            self.counters['requests'] += 1
            self.counters['decisions'] += 1
            # Worker owns cache execution; every logical request is emitted.
            hit = False
            self.events.append(dict(event='request', ordinal=self.counters['requests'],
                                    level=self.level, phase=self.batch['phase'],
                                    mask_sha256=hashlib.sha256(mask).hexdigest(),
                                    cache_hit=hit, evaluator_identity=self.identity))
            if not self._alive():
                break
            ident = 'h13_' + str(self.counters['requests'])
            self.pending = (ident, mask)
            self.counters['attempted'] += 1
            return [dict(id=ident, candidate=list(mask), metadata=dict(
                level=self.level, phase=self.batch['phase']))]
        return []

    def observe(self, observations):
        if not self.pending or len(observations) != 1:
            raise ValueError('One matching observation required')
        o = observations[0]
        ident, mask = self.pending
        if o['proposal_id'] != ident:
            raise ValueError('Proposal mismatch')
        self.pending = None
        costs = o.get('costs', {})
        # Only report exposed forward work, never invent dual-call solver costs.
        self.counters['physical_forward'] += costs.get('solver_executions') or 0
        try:
            if o['status'] != 'ok':
                raise ValueError('Physical evaluation failure')
            if bytes(o['candidate']) != mask:
                raise ValueError('Candidate mismatch')
            identity = o.get('evaluator_identity')
            metrics = o['objectives']
            primary = self.problem['primary_objective']['name']
            reported = float(metrics[primary])
            if not math.isfinite(reported):
                raise ValueError('Nonfinite objective')
            if TE in metrics and TM in metrics:
                te, tm = float(metrics[TE]), float(metrics[TM])
                score = (te + tm) / 2
                minimum = float(metrics.get(MIN, min(te, tm)))
                if not all(math.isfinite(x) for x in (te, tm, minimum, score)):
                    raise ValueError('Nonfinite physical metrics')
                if not math.isclose(score, reported, rel_tol=1e-12, abs_tol=1e-12) or not math.isclose(minimum, min(te, tm), abs_tol=1e-12):
                    raise ValueError('Not actual mean TE/TM with separate minimum')
            else:
                # Generic mock scalar is not a fabricated polarization measurement.
                score, te, tm, minimum = reported, None, None, None
        except (ValueError, KeyError, TypeError, OverflowError):
            self.counters['failures'] += 1
            self.events.append(dict(event='failure', proposal_id=ident, costs=costs.copy()))
            self._stop('evaluation_failed')
            return
        self.identity = identity
        self.counters['completed'] += 1
        self.counters['cache_hits'] += int(bool(costs.get('cache_hits', 0)))
        self.events.append(dict(event='completion', proposal_id=ident,
                                evaluator_identity=identity, mean=score, TE=te, TM=tm,
                                minimum=minimum, costs=costs.copy()))
        record = (score, te, tm, minimum, self.counters['completed'])
        if mask not in self.cache:
            self.cache[mask] = record
            if self.best is None or score > self.cache[self.best][0]:
                self.best = mask
        # Valid completed calls survive expiry, but interrupted updates never do.
        if not self._alive():
            return
        self._consume(score, not bool(costs.get('cache_hits', 0)))

    def _consume(self, score, fresh):
        b = self.batch
        b['scores'].append(score)
        b['fresh'] |= fresh
        if 1 <= b['phase'] <= 16:
            self.visited[self.level].add(b['selected'][b['phase'] - 1])
        b['phase'] += 1
        if b['phase'] != 18:
            return
        if not self._alive():
            return
        self.counters['batches'] += 1
        self.stage += 1
        self.no_new = 0 if b['fresh'] else self.no_new + 1
        self.batch = None
        event = dict(event='complete', level=self.level, stage=self.stage,
                     no_new=self.no_new, visited=len(self.visited[self.level]))
        self.events.append(event)
        if self.no_new == 4:
            self.p = [0.5] * len(self.p)
            self.stage = self.no_new = 0
            self.perm, self.cursor = [], 0
            self.counters['resets'] += 1
            self.events.append(dict(event='reset', level=self.level))
        elif self.stage == 4:
            if self.level < len(GRIDS) - 1:
                rows, cols = GRIDS[self.level]
                nr, nc = GRIDS[self.level + 1]
                parent = self.p
                new = []
                for y in range(nr):
                    if not self._alive():
                        return
                    new.extend(parent[(y * rows // nr) * cols + x * cols // nc] for x in range(nc))
                self.p = new
                self.level += 1
                self.counters['refinements'] += 1
                self.events.append(dict(event='refine', level=self.level))
                self.perm, self.cursor = [], 0
                self.no_new = 0
            self.stage = 0

    def inspect(self):
        # Bounded: the host records this after every evaluation, so the whole event log and the best mask (in the host's
        # progress already) made each record grow with the run. The last EVENTS_SHOWN events and the count are shown.
        return dict(status=self.status, counters=self.counters.copy(),
                    decisions=self.counters['decisions'], level=self.level,
                    grid=GRIDS[self.level], stage=self.stage, no_new=self.no_new,
                    visited=[len(v) for v in self.visited], events=self.events[-EVENTS_SHOWN:], events_total=len(self.events),
                    best=None if self.best is None else dict(
                        mean=self.cache[self.best][0], TE=self.cache[self.best][1],
                        TM=self.cache[self.best][2], minimum=self.cache[self.best][3]),
                    worker_wall_seconds=time.time() - self.started,
                    timing_authority='parent full-worker accounting includes RPC and physical calls')

    def checkpoint(self):
        state = self.__dict__.copy()
        state.pop('rng')
        state.pop('mono_deadline')
        state['rng_state'] = self.rng.getstate()
        enc = lambda b: base64.b64encode(b).decode('ascii')
        state['cache'] = [[enc(k), v] for k, v in self.cache.items()]
        state['best'] = None if self.best is None else enc(self.best)
        state['pending'] = None if self.pending is None else [self.pending[0], enc(self.pending[1])]
        state['visited'] = [sorted(v) for v in self.visited]
        payload = canonical(state).encode()
        return zlib.compress(canonical(dict(version=1, sha256=hashlib.sha256(payload).hexdigest(), state=state)).encode())

    def restore(self, data):
        wrapper = json.loads(zlib.decompress(data))
        state = wrapper['state']
        if wrapper['version'] != 1 or hashlib.sha256(canonical(state).encode()).hexdigest() != wrapper['sha256']:
            raise ValueError('Checkpoint integrity mismatch')
        def tuples(x):
            return tuple(tuples(v) for v in x) if isinstance(x, list) else x
        rng = random.Random()
        rng.setstate(tuples(state.pop('rng_state')))
        dec = base64.b64decode
        state['cache'] = {dec(k): tuple(v) for k, v in state['cache']}
        state['best'] = None if state['best'] is None else dec(state['best'])
        state['pending'] = None if state['pending'] is None else (state['pending'][0], dec(state['pending'][1]))
        state['visited'] = [set(v) for v in state['visited']]
        self.__dict__ = state
        self.rng = rng
        self.mono_deadline = (time.monotonic() + max(0, self.deadline - time.time())
                              if self.deadline is not None else None)
        self._alive()

    def export_artifacts(self):
        return []

    def close(self):
        if self.status == 'running':
            self._stop('closed')
