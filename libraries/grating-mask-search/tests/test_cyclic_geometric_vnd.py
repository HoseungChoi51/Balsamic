"""Author mock tests only. No physical evaluations."""
import unittest
from unittest.mock import patch
from grating_mask_search import cyclic_geometric_vnd as h


def make(seed=42):
    obj = h.create_optimizer({})
    obj.initialize({'candidate_schema': {'dimensions':32768}, 'primary_objective':{'name':'mock_score'}}, {}, seed, [])
    return obj


def observe(obj, proposal, value=.5, hit=False, actual=False):
    objectives = {h.MEAN:value,h.TE:value-.1,h.TM:value+.1} if actual else {'mock_score':value}
    obj.observe([{'proposal_id':proposal['id'],'candidate':proposal['candidate'],
                  'status':'ok','objectives':objectives,
                  'costs':{'solver_executions':0 if hit else 1,'cache_hits':int(hit)}}])


class Conformance(unittest.TestCase):
    def test_toroidal_square_pair(self):
        mask=bytes(32768)
        out=h.square_xor(mask,2,127,255)
        self.assertEqual({i for i,x in enumerate(out) if x},{32767,32512,255,0})
        self.assertEqual(h.square_xor(out,2,127,255),mask)
        self.assertEqual(h.paired_xor(mask,8,(127,255),(127,255)),mask)
        self.assertEqual(sum(h.paired_xor(mask,2,(0,0),(0,1))),4)

    def test_internal_rotation(self):
        mask=bytes((r*7+c*3+c//3)%2 for r in range(128) for c in range(256))
        for axis in (0,1):
            for sign in (-1,1):
                out=h.rectangle_rotate(mask,8,4,125,254,axis,sign)
                expected=bytearray(mask)
                rect=[[mask[((125+y)%128)*256+(254+x)%256] for x in range(4)] for y in range(8)]
                for y in range(8):
                    for x in range(4):
                        expected[((125+y)%128)*256+(254+x)%256]=rect[(y-sign)%8 if axis==0 else y][(x-sign)%4 if axis==1 else x]
                self.assertEqual(out,bytes(expected))
                self.assertEqual(h.rectangle_rotate(out,8,4,125,254,axis,-sign),mask)

    def test_coarse_rng(self):
        a,b=make(),make()
        x=a.coarse()
        self.assertEqual(x,b.coarse())
        self.assertNotEqual(x,a.coarse())
        for y in range(128):
            for c in range(256):
                self.assertEqual(x[y*256+c],x[(y//16)*16*256+(c//16)*16])

    def test_worker_hit_requests_16_96_restart(self):
        obj=make()
        for _ in range(4):
            observe(obj,obj.propose()[0])
        best=obj.best
        indices=[]
        with patch.object(obj,'generate',side_effect=lambda:obj.current):
            for i in range(96):
                indices.append(obj.index)
                p=obj.propose()[0]
                self.assertEqual(len(p['candidate']),32768)
                observe(obj,p,hit=True)
        self.assertEqual(indices,[0]*16+[1]*16+[2]*16+[0]*16+[1]*16+[2]*16)
        self.assertEqual(obj.phase,'restart')
        self.assertEqual(obj.counters['neighborhood_switches'],5)
        self.assertEqual(obj.counters['requests'],100)
        self.assertEqual(obj.counters['cache_hits'],96)
        self.assertEqual(obj.counters['attempted_uncached_dual_calls'],4)
        observe(obj,obj.propose()[0],.1)
        self.assertEqual(obj.current_metrics[0],.1)
        self.assertEqual(obj.best,best)
        self.assertEqual((obj.index,obj.rejected,obj.stall),(0,0,0))
        self.assertEqual(obj.counters['restarts'],1)
        self.assertEqual(len(obj.request_log),101)

    def test_partial_init_ties_actual_metrics(self):
        obj=make()
        p=obj.propose()[0]
        observe(obj,p,actual=True)
        best=obj.best
        self.assertTrue(obj.inspect()['has_solution'])
        self.assertEqual(obj.init_done,1)
        self.assertEqual(obj.export_artifacts()[0]['data']['candidate'],p['candidate'])
        observe(obj,obj.propose()[0],actual=True)
        self.assertEqual(obj.best,best)
        self.assertEqual(obj.inspect()['best_objectives'][h.TE],.4)

    def test_scalar_no_fabricated_polarization(self):
        obj=make()
        observe(obj,obj.propose()[0],.7)
        self.assertEqual(obj.best_metrics,(.7,None,None,None))

    def test_acceptance_and_archive_tolerance(self):
        obj=make()
        for _ in range(4): observe(obj,obj.propose()[0])
        best=obj.best
        other=h.square_xor(best,1,0,0)
        obj.consume(other,(.5+5e-13,None,None,None),'proposal')
        self.assertEqual(obj.best,other)
        self.assertEqual(obj.current,best)
        obj.consume(other,(.6,None,None,None),'proposal')
        self.assertEqual(obj.current,other)
        self.assertEqual((obj.index,obj.rejected,obj.stall),(0,0,0))

    def test_failure_no_archive(self):
        for status,value in [('evaluation_failed',.4),('ok',float('nan'))]:
            obj=make(); p=obj.propose()[0]
            obj.observe([{'proposal_id':p['id'],'candidate':p['candidate'],'status':status,
                          'objectives':{'mock_score':value},'costs':{}}])
            self.assertIsNone(obj.best)
            self.assertEqual(obj.counters['failures'],1)
            self.assertEqual(obj.propose(),[])

    def test_checkpoint(self):
        a,b=make(),make()
        for _ in range(4): observe(a,a.propose()[0])
        b.restore(a.checkpoint())
        for _ in range(20):
            pa,pb=a.propose()[0],b.propose()[0]
            self.assertEqual(pa,pb)
            observe(a,pa); observe(b,pb)
        self.assertTrue(all(isinstance(k,bytes) and isinstance(v,tuple) for k,v in a.cache.items()))


if __name__=='__main__': unittest.main()
