import copy
import unittest
from unittest.mock import patch
from backend.research.rebuild import top5_diverse_batch_preparation_v1 as x
from backend.research.rebuild.test_top5_development_repair_v1 import fixture


def parent(lane):
    return next(c for c in x.old.read(x.old.FREEZE)['children'] if c['lane_id']==lane)


class Preparation(unittest.TestCase):
    def test_remove_only_one_gate_and_preserve_parent(self):
        p=parent(x.KELTNER);before=copy.deepcopy(p);c,delay=x.candidate_spec(p)
        self.assertEqual(p,before);self.assertEqual(delay,0)
        c['executable_spec']['entry_rule']=p['executable_spec']['entry_rule']
        self.assertEqual(c,p)

    def test_removed_gate_signal_set_is_superset_and_prefix_causal(self):
        rows=fixture(340,14_400_000);p=parent(x.KELTNER);c,_=x.candidate_spec(p)
        a=x.causal_signals(rows,p['executable_spec']);b=x.causal_signals(rows,c['executable_spec'])
        self.assertTrue(set(a)<=set(b))
        for length in (280,310):
            self.assertEqual([i for i in b if i<length],x.causal_signals(rows[:length],c['executable_spec']))

    def test_delay_retains_dsl_and_moves_fill_exactly_one_bar(self):
        p=parent(x.SUPERTREND);c,delay=x.candidate_spec(p)
        self.assertEqual(c,p);self.assertEqual(delay,1)
        rows=fixture(300,14_400_000)
        base=x.replay_prepared_rows(rows,p,selected_signals=[240])['trades'][0]
        child=x.replay_prepared_rows(rows,p,candidate=True,selected_signals=[240])['trades'][0]
        self.assertEqual(base['signal_ts'],child['signal_ts'])
        self.assertEqual(child['entry_index'],base['entry_index']+1)
        self.assertEqual(child['entry_price'],rows[242]['open'])
        self.assertEqual(child['exit_index']-child['entry_index'],11)

    def test_shared_ownership_blocks_waiting_and_held_signals(self):
        r=x.replay_prepared_rows(fixture(300,14_400_000),parent(x.SUPERTREND),candidate=True,selected_signals=[240,241,250])
        self.assertEqual(len(r['trades']),1)
        self.assertEqual([e['reason'] for e in r['exclusions']],['SIGNAL_DURING_OPEN']*2)

    def test_budget_blocks_before_any_data_or_economic_call(self):
        with patch.object(x.old.common,'evaluate_development_events',side_effect=AssertionError('MUST_NOT_RUN')):
            with self.assertRaisesRegex(RuntimeError,'NEW_TRIAL_ALLOCATION_NOT_ESTABLISHED'):
                x.require_existing_allocation()

    def test_renaming_proposal_cannot_restore_trial_credit(self):
        proposal=x.old.read(x.PROPOSAL);proposal['proposal_id']='NEW_NAME';proposal['allocated_new_trials']=2
        with patch.object(x.old,'read',return_value=proposal):
            with self.assertRaisesRegex(RuntimeError,'UNREVIEWED'):
                x.require_existing_allocation()


if __name__=='__main__':unittest.main()
