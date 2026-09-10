import unittest
from copy import deepcopy
from backend.research.rebuild import c63_initial_failure_f_verify_v1 as v

class MetadataBoundaryTests(unittest.TestCase):
    def test_both_namespaces_and_no_mutation(self):
        for label in v.study.VARIANTS:
            raw={'S':dict(audit=dict(variant=label,rule=v.study.child.RULES[label]))}
            charged=dict(variant='M1',trades=[dict(net_bps=-123.456)],metrics={'net':-123.456})
            before=deepcopy((raw,charged));out=v.bind_candidate_metadata(charged,raw,'M1')
            self.assertEqual(out,dict(charged,variant=label));self.assertEqual(before,(raw,charged))
    def test_wrong_rule_lane_or_mixed_candidate_rejected(self):
        raw={'S':dict(audit=dict(variant='F_ONLY',rule=v.study.child.RULES['F_ONLY']))}
        for lane,charged in [('R',{'variant':'M1'}),('M1',{'variant':'F_ONLY'})]:
            with self.assertRaises(ValueError):v.bind_candidate_metadata(charged,raw,lane)
        for other in (dict(variant='B20_F',rule=v.study.child.RULES['B20_F']),dict(variant='F_ONLY',rule='wrong')):
            mixed=dict(raw,X=dict(audit=other))
            with self.assertRaises(ValueError):v.bind_candidate_metadata({'variant':'M1'},mixed,'M1')
if __name__=='__main__':unittest.main()
