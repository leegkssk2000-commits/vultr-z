import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import step7_kr3_winner_persistence_v1 as p


class Persistence(unittest.TestCase):
    def fixture(self, root, states):
        trials = []
        for i, state in enumerate(states):
            name = p.frozen.RUNS[i]
            t = dict(run=name, scope=p.frozen.SCOPE, actual_experiment_ordinal=61+i,
                     candidate_ordinal=45 if name.startswith('E-') else None,
                     specification_sha256='synthetic', status='RESERVED_BEFORE_REPLAY', retry_allowed=False)
            trials.append(t)
            folder = root/p.frozen.OUTPUT/name; folder.mkdir(parents=True)
            if state == 'COMPLETED':
                data = b'opaque synthetic result'; (folder/'RESULT.json.gz').write_bytes(data)
                r = dict(t, status=state, finished_unix_ns=123, artifact_sha256=hashlib.sha256(data).hexdigest())
                (folder/'RECEIPT.json').write_text(json.dumps(r))
            elif state == 'FAILED_CONSUMED':
                (folder/'FAILURE.json').write_text(json.dumps(dict(t, status=state, error='synthetic failure')))
        b = dict(trials=[{'old_history':True}]+trials, cumulative_actual=45, cumulative_actual_evaluations=60+len(states),
                 kr3_winner_repair_allocation=dict(scope_key=p.frozen.SCOPE, runs=list(p.frozen.RUNS),
                 used=len(states), max_executions=3, specification_sha256='synthetic'))
        path = root/p.frozen.BUDGET; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(b)); return path

    def test_completed_initial_reservations_settle_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=self.fixture(root,['COMPLETED']*3)
            a=p.settle(root); before=path.read_bytes(); p.settle(root)
            self.assertEqual(before,path.read_bytes())
            self.assertEqual([a[k] for k in ('used','completed','failed','running','remaining')],[3,3,0,0,0])
            b=json.loads(before); self.assertEqual(b['trials'][0],{'old_history':True})
            self.assertEqual((b['cumulative_actual'],b['cumulative_actual_evaluations']),(45,63))

    def test_failure_consumed_and_unknown_reservation_not_released(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); self.fixture(root,['COMPLETED','FAILED_CONSUMED','UNKNOWN'])
            a=p.settle(root)
            self.assertEqual([a[k] for k in ('used','completed','failed','running','remaining')],[3,1,1,1,0])

    def test_corrupt_result_does_not_rewrite_budget(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=self.fixture(root,['COMPLETED']); before=path.read_bytes()
            (root/p.frozen.OUTPUT/p.frozen.RUNS[0]/'RESULT.json.gz').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'RESULT_HASH_MISMATCH'):p.settle(root)
            self.assertEqual(before,path.read_bytes())

    def test_caller_finalizes_success_without_replaying_in_test(self):
        with patch.object(p.frozen,'execute',return_value=['synthetic']) as run, patch.object(p,'settle') as settle:
            self.assertEqual(p.execute({}, {}, 'unused'),['synthetic'])
            run.assert_called_once(); settle.assert_called_once()

    def test_caller_finalizes_failure_without_retry(self):
        with patch.object(p.frozen,'execute',side_effect=RuntimeError('synthetic')) as run, patch.object(p,'settle') as settle:
            with self.assertRaisesRegex(RuntimeError,'synthetic'):p.execute({}, {}, 'unused')
            run.assert_called_once(); settle.assert_called_once()


if __name__ == '__main__':unittest.main()
