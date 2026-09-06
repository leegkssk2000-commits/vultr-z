"""Allocation and boundaries are independent from an economic study pass."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import q0_risk_entry_v1 as x


class StudyTests(unittest.TestCase):
    def test_positive_but_inferior_to_same_exposure_control_is_not_promising(self):
        r=x.study_decision(100,50,200,80,60,40,30,[-2,5])
        self.assertEqual(r['decision'],'DEV_REJECT')
        self.assertFalse(r['study_goal_met']);self.assertFalse(r['formal_pass'])

    def test_broad_interval_prevents_confirmatory_promising_label(self):
        r=x.study_decision(200,50,100,50,60,20,30,[-2,5])
        self.assertTrue(r['study_goal_met']);self.assertEqual(r['decision'],'DEV_INCONCLUSIVE')
        self.assertEqual(r['research_reference'],'Q0')

    def test_mixed_tradeoff_and_negative_cost_stress_are_distinct(self):
        r=x.study_decision(200,50,100,80,60,20,30,[-2,5])
        self.assertEqual(r['decision'],'DEV_INCONCLUSIVE_TRADEOFF')
        r=x.study_decision(200,-1,100,50,60,20,30,[1,5])
        self.assertEqual(r['decision'],'DEV_REJECT')

    def test_identical_results_are_not_improvement_and_never_formal_pass(self):
        for vals,decision in [((100,50,100,60,60,30,30,[0,0]),'DEV_REJECT'),((200,50,100,50,60,20,30,[1,5]),'DEV_PROMISING_NO_CREDIT')]:
            r=x.study_decision(*vals);self.assertEqual(r['decision'],decision)
            self.assertFalse(r['formal_pass']);self.assertFalse(r['operating_adoption'])
            self.assertFalse(r['signal_prediction_improvement_claimed'])

    def test_consumed_trial_stops_before_read_or_calculation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/x.OUTPUT;out.mkdir(parents=True);(out/'receipt.json').write_text('{}')
            with patch.object(x,'ROOT',root),patch.object(x,'authorize',return_value=({}, {}, {}, {})),patch.object(x.prior.inputs,'load_inputs') as loader:
                with self.assertRaisesRegex(RuntimeError,'ALLOCATION_CONSUMED'):x.run(root/'DATA')
                loader.assert_not_called()

    def test_wrong_data_cost_or_symbols_stops_before_weights(self):
        c={'data_sha256':'D','cost_sha256':'C','symbols':['S']}
        for p,f in [({'combined_data_sha256':'X','cost_binding_sha256':'C'},{'S':[]}),({'combined_data_sha256':'D','cost_binding_sha256':'X'},{'S':[]}),({'combined_data_sha256':'D','cost_binding_sha256':'C'},{'Z':[]})]:
            with tempfile.TemporaryDirectory() as folder,patch.object(x,'ROOT',Path(folder)),patch.object(x,'authorize',return_value=(c,{},{},{})),patch.object(x.prior.inputs,'load_inputs',return_value=(p,{},f,{},{})),patch.object(x.weights,'market_state') as calc:
                with self.assertRaisesRegex(RuntimeError,'DATA_COST_UNIVERSE'):x.run(Path(folder))
                calc.assert_not_called()

    def test_reproduction_is_immutable_and_does_not_reallocate(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(x,'ROOT',Path(folder)):
            (Path(folder)/x.OUTPUT).mkdir(parents=True)
            x.write_artifact('synthetic.json.gz',{'net':1},False)
            x.write_artifact('synthetic.json.gz',{'net':1},True)
            with self.assertRaisesRegex(RuntimeError,'REPRODUCTION_DRIFT'):x.write_artifact('synthetic.json.gz',{'net':2},True)
        self.assertEqual(x.BUDGET['previous_applications'],25)
        self.assertEqual(x.BUDGET['cumulative_after_measurement'],26)
        self.assertEqual(x.BUDGET['fixed_control_new_strategy_trials'],0)
        self.assertEqual(x.BUDGET['reproduction_new_trials'],0)


if __name__=='__main__':unittest.main()
