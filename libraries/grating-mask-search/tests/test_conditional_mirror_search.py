"""Mock-only conformance; no physics imports or evaluations."""
import copy
import time
import unittest
from unittest.mock import patch
from grating_mask_search.conditional_mirror_search import Mirror, GRIDS, TE, TM, MIN


def optimizer(seed=9):
    m = Mirror()
    m.initialize(dict(configuration=dict(grid_y=128, grid_x=256),
                      fidelity=dict(rcwa_order_x=10, rcwa_order_y=5),
                      primary_objective=dict(name='mean')), dict(absolute_deadline=time.time()+3600), seed, [])
    return m


def observe(m, proposal, score=0.25, **kwargs):
    o = dict(proposal_id=proposal['id'], candidate=proposal['candidate'], status='ok',
             objectives={TE:score, TM:score, MIN:score, 'mean':score},
             fidelity=m.fidelity, evaluator_identity='canonical-mock-identity', costs={'solver_executions':2})
    o.update(kwargs)
    m.observe([o])


class Conformance(unittest.TestCase):
    def test_frozen_shared_bg_sign_threshold(self):
        m = optimizer()
        p0 = m.p[:]
        bg = m.propose()[0]
        bits = m.batch['bg'][:]
        chosen = m.batch['selected'][:]
        self.assertEqual(len(set(chosen)), 16)
        observe(m, bg, .2)
        for k, i in enumerate(chosen):
            arm = m.propose()[0]
            self.assertEqual(m.p, p0)
            changed = sum(a != b for a,b in zip(bg['candidate'], arm['candidate']))
            self.assertEqual(changed, 256)
            observe(m, arm, .4)
            self.assertEqual(m.p, p0)
        threshold = m.propose()[0]
        self.assertEqual(m.counters['batches'], 0)
        for i in chosen:
            self.assertEqual(m.p[i] > .5, bits[i] == 0)
        observe(m, threshold)
        self.assertEqual(m.counters['batches'], 1)
        self.assertEqual(m.counters['requests'], 18)
        self.assertEqual(m.counters['physical_forward'], 36)
        self.assertEqual(m.counters['backward'], 0)

    def test_partial_and_threshold_discard_archive(self):
        for n in (4, 17):
            m = optimizer()
            for _ in range(n):
                observe(m, m.propose()[0], .3)
            if n == 17:
                m.propose()  # provisional threshold update not completed
            m.deadline = time.time()-1
            self.assertEqual(m.propose() if not m.pending else [], [])
            m._alive()
            self.assertEqual(m.p, [.5]*128)
            self.assertIsNotNone(m.best)
            self.assertEqual(m.counters['batches'], 0)

    def test_wrap_distinct(self):
        m = optimizer()
        m.perm = list(range(128))
        m.cursor = 125
        self.assertTrue(m._begin())
        self.assertEqual(m.batch['selected'][:3], [125,126,127])
        self.assertEqual(len(set(m.batch['selected'])),16)

    def test_reset_precedence_and_refinement_schedule(self):
        m = optimizer()
        m.stage, m.no_new = 3,3
        m._begin()
        m.batch.update(phase=17, fresh=False)
        m._consume(.2, False)
        self.assertEqual(m.level, 0)
        self.assertEqual(m.counters['resets'], 1)
        self.assertEqual(m.stage, 0)
        for level in range(8):
            m.p = [0.3 if i%2 else .7 for i in range(len(m.p))]
            before = m._expand([int(x>=.5) for x in m.p])
            m.stage = 3
            m._begin()
            m.batch.update(phase=17)
            m._consume(.2, True)
            self.assertEqual(m.level, level+1)
            self.assertEqual(m._expand([int(x>=.5) for x in m.p]), before)
            self.assertEqual(len(m.p), GRIDS[level+1][0]*GRIDS[level+1][1])
        m.stage=3
        m._begin()
        m.batch.update(phase=17)
        m._consume(.2, True)
        self.assertEqual(m.stage,0)
        self.assertEqual(m.level,8)

    def test_exact_cache_internal_transition_and_deadline(self):
        m = optimizer()
        proposal=m.propose()[0]
        observe(m,proposal)
        mask=bytes(proposal['candidate'])
        first=m.best
        m.batch['phase']=0  # exercise same exact BG through cache
        follow=m.propose()[0]
        self.assertEqual(m.counters['cache_hits'],0)
        self.assertEqual(m.counters['attempted'],2)
        self.assertEqual(m.counters['requests'],2)
        self.assertEqual(follow['candidate'],proposal['candidate'])
        self.assertIsInstance(next(iter(m.cache)),bytes)
        self.assertIsInstance(m.cache[mask],tuple)
        observe(m,follow)
        self.assertEqual(m.best,first) # earliest tied insertion
        m.deadline=time.time()-1
        self.assertEqual(m.propose(),[])
        self.assertEqual(m.status,'deadline')
        self.assertEqual(m.counters['batches'],0)

    def test_failures_nonfinite_context(self):
        for mode in ('failure','nan'):
            m=optimizer()
            q=m.propose()[0]
            if mode=='failure':
                observe(m,q,status='evaluation_failed')
            elif mode=='nan':
                observe(m,q,float('nan'))
            self.assertEqual(m.status,'evaluation_failed')
            self.assertEqual(m.counters['failures'],1)
            self.assertEqual(m.counters['attempted'],m.counters['completed']+1)
            self.assertEqual(m.p,[.5]*128)
            self.assertEqual(m.propose(),[])

    def test_checkpoint_determinism_pending_and_cache(self):
        m=optimizer()
        for _ in range(7):
            observe(m,m.propose()[0])
        q=m.propose()[0]
        blob=m.checkpoint()
        n=Mirror()
        n.restore(blob)
        self.assertEqual(n.checkpoint(),blob)
        observe(m,q)
        observe(n,q)
        for _ in range(40):
            a,b=m.propose(),n.propose()
            self.assertEqual(a,b)
            observe(m,a[0])
            observe(n,b[0])
            self.assertEqual(m.p,n.p)
            self.assertEqual(m.events,n.events)
            self.assertEqual(m.cache,n.cache)

    def test_four_real_batches_refine_only_after_threshold(self):
        m=optimizer()
        for _ in range(72):
            q=m.propose()[0]
            observe(m,q,.1 + (sum(q['candidate']) % 100)/1000)
        self.assertEqual(m.counters['batches'],4)
        self.assertEqual(m.level,1)
        self.assertEqual(m.stage,0)
        self.assertEqual(m.counters['requests'],72)
        self.assertLessEqual(m.counters['attempted'],72)
        self.assertGreater(len(m.visited[0]),0)

    def test_published_scalar_context_and_worker_cache(self):
        m=Mirror()
        m.initialize({'primary_objective':{'name':'mean'}}, {}, 9, [])
        for _ in range(72):
            q=m.propose()[0]
            m.observe([dict(proposal_id=q['id'], candidate=q['candidate'],
                            status='ok',objectives={'mean':.3},
                            costs={'cache_hits':1,'solver_executions':0})])
        self.assertEqual(m.counters['batches'],4)
        self.assertEqual(m.counters['resets'],1)
        self.assertEqual(m.level,0)
        self.assertEqual(m.counters['cache_hits'],72)
        self.assertEqual(m.counters['physical_forward'],0)
        self.assertIsNone(m.inspect()['best']['TE'])
        self.assertIsNone(m.inspect()['best']['TM'])
        n=Mirror()
        n.restore(m.checkpoint())
        self.assertEqual(m.propose(),n.propose())

    def test_expired_initialization_no_solution(self):
        m=optimizer()
        m.deadline=0
        self.assertEqual(m.propose(),[])
        self.assertIsNone(m.inspect()['best'])
        self.assertEqual(m.counters['attempted'],0)


if __name__=='__main__':
    unittest.main()
