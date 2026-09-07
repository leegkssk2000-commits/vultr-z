"""Arithmetic fixture only: missing/open origins never trigger counterfactual replay."""
import unittest
from unittest.mock import patch
from backend.research.rebuild import top5_cumulative_v1 as c

class FactorialTests(unittest.TestCase):
    def test_stored_closed_intersection_and_nonadditive_interaction(self):
        views={}
        for name,net in [('P',10),('TPR1_FULL',14),('TPP1_FIXED',13),('FIXED',20)]:
            views[name]={'common':('C',{'net_bps':net}),'open':('O',{}),'missing':('C',{'net_bps':999})}
        del views['FIXED']['missing']
        with patch.object(c.metrics,'index',side_effect=lambda v:v):
            out=c.factorial(views)
        self.assertEqual(out['count'],1)
        self.assertEqual(out['totals'],{'extension':4,'protection':3,'interaction':3})
        self.assertEqual(out['missing_path_replays'],0)
        self.assertFalse(out['full_delta_is_additive'])
