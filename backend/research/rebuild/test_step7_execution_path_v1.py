import copy
import unittest
from backend.research.rebuild.step7_execution_path_v1 import source_dispatch_allowed, ALLOCATION, MERGE_TITLE, WORKFLOW


class ContinuationDispatchTests(unittest.TestCase):
    def setUp(self):
        self.b = {'source_bundle_used':1, 'additional_source_allocations':[{
            'allocation_id':ALLOCATION, 'status':'RESERVED', 'used_batches':0, 'max_batches':1,
            'maximum_seconds':86400, 'http_max':2000, 'new_raw_bytes_max':1073741824,
            'merge_commit_title':MERGE_TITLE}]}
        self.c = {'event':'push','ref':'refs/heads/master','attempt':1,'message':MERGE_TITLE+'\n\nMerge details', 'sha':'fixed', 'run_id':10}
        self.r = [{'event':'push','head_sha':'fixed','path':WORKFLOW,'id':10}]

    def test_original_consumed_plus_explicit_additional_is_required(self):
        self.assertEqual(source_dispatch_allowed(self.c,self.b,self.r)['allocation_id'],ALLOCATION)
        for patch in ({'source_bundle_used':0},{'additional_source_allocations':[]}):
            b=copy.deepcopy(self.b);b.update(patch)
            with self.assertRaises(ValueError):source_dispatch_allowed(self.c,b,self.r)

    def test_old_merge_retries_or_second_run_cannot_consume_additional(self):
        for patch in ({'message':'Merge STEP7 task-c28e09b57c612762'},{'attempt':2},{'event':'pull_request'},{'run_id':11}):
            c=dict(self.c,**patch)
            with self.assertRaises(ValueError):source_dispatch_allowed(c,self.b,self.r)

    def test_consumed_renamed_or_excessive_allocation_rejected(self):
        for patch in ({'status':'EXECUTED'},{'used_batches':1},{'allocation_id':'renamed'},{'max_batches':2},{'http_max':2001},{'maximum_seconds':86401},{'new_raw_bytes_max':1073741825}):
            b=copy.deepcopy(self.b);b['additional_source_allocations'][0].update(patch)
            with self.assertRaises(ValueError):source_dispatch_allowed(self.c,b,self.r)
