import time
import unittest
from grating_mask_search.elite_spread_relinking import Optimizer, corridor, distance, H, W, MEAN, TE, TM, MIN


def make(seed=3, deadline=None):
    o = Optimizer({'absolute_deadline': deadline})
    o.initialize({'candidate_schema': {'dimensions': H*W},
                  'configuration': {'grid_x': W, 'grid_y': H},
                  'fidelity': {'rcwa_order_x': 10, 'rcwa_order_y': 5},
                  'primary_objective': {'name': MEAN}, 'evaluation_identity': 'mock'}, {}, seed, [])
    return o


def reply(o, score=0.5, status='ok'):
    o.observe([{'proposal_id': o.pending[0], 'status': status,
                'objectives': dict(zip((MEAN, TE, TM, MIN), [score]*4)),
                'costs': {'solver_executions': 1}}])


def mask(i):
    b = bytearray(H*W)
    b[i] = 1
    return bytes(b)


class Tests(unittest.TestCase):
    def test_archive_ties_evictions_bounds_reentry(self):
        o = make()
        entries = [(mask(i), float(i), i+1, (float(i),)*4) for i in range(20)]
        for e in entries:
            o.offer(e)
            self.assertLessEqual(len(o.elite), 4)
            self.assertLessEqual(len(o.spread), 4)
            self.assertFalse({e[0] for e in o.elite} & {e[0] for e in o.spread})
        self.assertEqual([e[1] for e in o.elite], [19.,18.,17.,16.])
        self.assertEqual([e[2] for e in o.spread], [1,2,3,4])
        o.offer(entries[6])  # discarded cache-requested entry reenters bounded pool
        self.assertEqual(len(o.spread), 4)
        t = make()
        for i in range(8):
            t.offer((mask(i), 1., i, (1.,)*4))
        self.assertEqual([e[2] for e in t.elite], [0,1,2,3])
        self.assertEqual([e[2] for e in t.spread], [4,5,6,7])
        self.assertEqual(t.best[2], 0)

    def test_corridor_spatial_order_and_frozen_parents(self):
        a = bytes(H*W)
        b = bytes([1])*(H*W)
        self.assertEqual(corridor(a,b,(127,255),True)[:3], (32767,32512,32513))
        self.assertEqual(corridor(a,b,(127,255),False)[:3], (32767,255,511))
        o = make()
        o.offer((a,2.,1,(2.,)*4)); o.offer((b,1.,2,(1.,)*4))
        o.start_episode()
        frozen = (o.a,o.b,o.order)
        first = o.next_mask()
        self.assertEqual(sum(first), H*W - (H*W)//8)
        o.offer((mask(5),3.,3,(3.,)*4))
        self.assertEqual((o.a,o.b,o.order), frozen)
        self.assertEqual(o.best[0],mask(5))

    def test_latest_best_local(self):
        o = make(); o.offer((bytes(H*W),0.,1,(0.,)*4))
        o.phase = 'local'
        o.propose(1); reply(o,1.)
        latest = o.best[0]
        proposed = bytes(o.propose(1)[0]['candidate'])
        self.assertIn(distance(latest, proposed), [1,4,16,64,256])

    def test_injection_partial_initialization_failure_deadline(self):
        o = make(); o.propose(1); reply(o)
        o.deadline = time.time()-1
        self.assertEqual(o.propose(1), [])
        self.assertIsNotNone(o.best)
        self.assertEqual(o.counts['episodes'],0)
        f = make(); f.propose(1); reply(f, float('nan'))
        self.assertEqual(f.counts['failures'],1)
        self.assertIsNone(f.best); self.assertFalse(f.cache)
        self.assertEqual(f.propose(1), [])
        o = make(); o.propose(1); reply(o)
        o.start_episode(); o.index = 4; o.phase = 'local'; o.stalls = 1
        m = o.next_mask()
        self.assertEqual(o.phase,'inject'); self.assertEqual(o.index,0)
        self.assertEqual(o.counts['episodes'],1)
        self.assertEqual(o.counts['injections'],1)
        o.propose(1); reply(o); o.propose(1); reply(o)
        self.assertEqual(o.index,2)
        o.next_mask()
        self.assertNotEqual(o.phase,'inject'); self.assertEqual(o.stalls,0)
        self.assertEqual(o.counts['injections'],1)

    def test_internal_cache_transitions_and_checkpoint(self):
        o = make(); o.propose(1); reply(o)
        # A one-difference corridor has seven copies of endpoint A, all hits.
        a = o.best[0]; b = bytearray(a); b[0] ^= 1; b = bytes(b)
        o.offer((b,0.,2,(0.,)*4))
        o.cache[b] = (b,0.,2,(0.,)*4)
        o.start_episode()
        p = o.propose(1)
        self.assertEqual(o.phase,'corridor')
        self.assertEqual(bytes(p[0]['candidate']), a)
        self.assertEqual(o.counts['requests'],2)
        # Worker cache observations are exposed, offered, and charged as hits.
        for _ in range(7):
            o.observe([{'proposal_id': o.pending[0], 'status': 'ok',
                        'objectives': dict(zip((MEAN, TE, TM, MIN), [.5]*4)),
                        'costs': {'cache_hits': 1, 'solver_executions': 0}}])
            o.propose(1)
        self.assertEqual(o.counts['cache_hits'],7)
        self.assertEqual(o.phase,'local')
        self.assertEqual(o.counts['decisions'],8)
        clone = make(); clone.restore(o.checkpoint())
        reply(o,0.6); reply(clone,0.6)
        self.assertEqual(o.propose(1),clone.propose(1))
        self.assertEqual(o.counts,clone.counts)
        self.assertEqual(o.rng.getstate(),clone.rng.getstate())
        wrong = make(); wrong.scope = 'wrong'
        with self.assertRaises(ValueError): wrong.restore(o.checkpoint())

    def test_published_context_scalar_and_worker_cache(self):
        o = Optimizer({})
        o.initialize({'candidate_schema': {'dimensions': H*W},
                      'public': {'grid_x': W, 'grid_y': H},
                      'primary_objective': {'name': MEAN, 'direction': 'maximize'}}, {}, 7, [])
        p = o.propose(1)[0]
        o.observe([{'proposal_id': p['id'], 'status': 'ok',
                    'objectives': {MEAN: .4}, 'costs': {}}])
        self.assertEqual(o.inspect()['best_objectives'], {MEAN: .4})
        self.assertNotIn(TE, o.inspect()['best_objectives'])
        # Force no algorithm behavior: inspect/checkpoint do not advance RNG.
        state = o.checkpoint(); clone = Optimizer({})
        clone.initialize({'candidate_schema': {'dimensions': H*W},
                          'public': {'grid_x': W, 'grid_y': H},
                          'primary_objective': {'name': MEAN, 'direction': 'maximize'}}, {}, 7, [])
        clone.restore(state)
        self.assertEqual(o.propose(1), clone.propose(1))

    def test_published_grid_layouts_and_scalar_replay(self):
        base = {'candidate_schema': {'dimensions': H*W},
                'primary_objective': {'name': MEAN, 'direction': 'maximize'}}
        layouts = [{}, {'grid_x': W, 'grid_y': H}]
        layouts += [{key: {'grid_x': W, 'grid_y': H}} for key in
                    ('configuration', 'public', 'public_descriptor')]
        layouts += [{'configuration': {}, 'public': {'grid_x': W, 'grid_y': H}}]
        for layout in layouts:
            with self.subTest(layout=layout):
                descriptor = {**base, **layout}
                a, b = Optimizer({}), Optimizer({})
                for o in (a,b): o.initialize(descriptor, {}, 7, [])
                for i in range(6):
                    pa, pb = a.propose(1)[0], b.propose(1)[0]
                    self.assertEqual(pa,pb)
                    for o,p in ((a,pa),(b,pb)):
                        o.observe([{'proposal_id': p['id'], 'status': 'ok',
                                    'objectives': {MEAN: i/6}}])
                state = a.checkpoint()
                expected = a.propose(1)
                b.restore(state)
                self.assertEqual(expected,b.propose(1))
        for key in ('configuration','public','public_descriptor'):
            with self.assertRaises(ValueError):
                Optimizer({}).initialize({**base,key:{'grid_x':128}}, {},7,[])
        with self.assertRaises(ValueError):
            Optimizer({}).initialize({**base,'candidate_schema':{'dimensions':8}}, {},7,[])

    def test_coarse(self):
        o = make(); m = o.coarse()
        for y in range(H):
            for x in range(W):
                self.assertEqual(m[y*W+x],m[(y//16)*16*W+(x//16)*16])


if __name__ == '__main__':
    unittest.main()
