import unittest
from copy import deepcopy
from backend.research.rebuild.step7_campaign_v1 import source_dispatch_allowed
class DispatchTests(unittest.TestCase):
 def setUp(self):
  self.c={'event':'push','ref':'refs/heads/master','attempt':1,'message':'fixed merge\n\nbody','selection_sha256':'s','sha':'h','run_id':7}
  self.b={'source_reservation':{'status':'RESERVED','max_bundles':1,'merge_commit_title':'fixed merge','selection_sha256':'s'}}
  self.r=[{'id':7,'head_sha':'h','event':'push','path':'.github/workflows/step7-parent-survivor-v1.yml'}]
 def test_first_push(self):self.assertTrue(source_dispatch_allowed(self.c,self.b,self.r))
 def test_rerun_and_second_push_denied(self):
  for c,r in [({**self.c,'attempt':2},self.r),({**self.c,'run_id':8},self.r+[{**self.r[0],'id':8}])]:
   with self.assertRaises(AssertionError):source_dispatch_allowed(c,self.b,r)
 def test_wrong_scope_or_closed_reservation(self):
  for c in ({**self.c,'event':'pull_request'},{**self.c,'message':'other merge'},{**self.c,'selection_sha256':'other'}):
   with self.assertRaises(AssertionError):source_dispatch_allowed(c,self.b,self.r)
  b=deepcopy(self.b);b['source_reservation']['status']='DONE'
  with self.assertRaises(AssertionError):source_dispatch_allowed(self.c,b,self.r)
