import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.research.rebuild import step7_kr3_dev_evidence_v1 as e


class KR3DevEvidenceTests(unittest.TestCase):
    def test_numeric_formula_and_python_literals_not_comment_dates(self):
        rows=e.numeric_occurrences('hold=12\nrule="ema(close,20) > lag(close,1)"\nlabel="20260908"\n','p.py','h')
        self.assertEqual(sorted(r['value'] for r in rows),[1,12,20])
        self.assertTrue(all(r['development_justification_sha'] is None for r in rows))
        self.assertTrue(all(r['source_or_test_sha']=='h' for r in rows))

    def test_negative_literal_sign_is_preserved(self):
        rows=e.numeric_occurrences("sentinel=-1\nlimit=2\n", "p.py", "hash")
        self.assertEqual(sorted(row["value"] for row in rows),[-1,2])

    def test_native_signed_held_median_never_relabels_fixed_forward(self):
        trades=[{'side':'long','mfe_bps':x,'mae_bps':-x,'gross_bps':x-10,
                 'data_sha256':'d'} for x in [1,10,100]]
        result=e.stored_medians({'candidate':'KR3','period':'DEV2025',
            'views':{'FULL':{'trades':trades,'open_observations':[{}],'events':[1,2,3,4]}}})
        self.assertEqual(result['mfe_bps_median'],10)
        self.assertEqual(result['mae_bps_median_signed'],-10)
        self.assertEqual(result['mae_bps_median_magnitude'],10)
        self.assertEqual(result['open_tail_count'],1)
        self.assertIsNone(result['forward_move_bps_median'])
        self.assertFalse(result['launch_gate_pass'])

    def test_wrong_native_mae_sign_blocks(self):
        with self.assertRaisesRegex(ValueError,'SIGN_OR_POPULATION'):
            e.stored_medians({'candidate':'KR3','period':'DEV2025','views':{'FULL':{
                'trades':[{'side':'long','mfe_bps':2,'mae_bps':1}],
                'events':[],'open_observations':[]}}})

    def test_wrong_period_not_silently_read_as_dev(self):
        with self.assertRaisesRegex(ValueError,'METRIC_IDENTITY'):
            e.stored_medians({'candidate':'KR3','period':'SEEN2026'})

    def test_spec_rejects_changed_bytes_even_resealed(self):
        spec=e.freeze()
        spec['calendar_ms'][1]+=e.BAR
        spec=e.seal({k:v for k,v in spec.items() if k!='receipt_sha256'})
        with self.assertRaisesRegex(ValueError,'FROZEN_BYTES_OR_SCOPE_DRIFT'):
            e.verify_spec(spec)

    def test_unapproved_calendar_blocks_before_prefix_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,document in [(e.POLICY,{'data_ref':e.DATA_REF,
                 'development_interval_ms':[e.DEV_START,e.DEV_END+e.BAR],
                 'cost_binding_sha256':'cost'}),(e.PROBE_POLICY,{}),(e.STAGE,{})]:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(document))
            with patch.object(e.admission,'require_development',return_value={'receipt_sha256':'cost'}), \
                 patch.object(e.probe,'load_development') as load:
                with self.assertRaisesRegex(ValueError,'SOURCE_SCOPE'):
                    e.load_dev_slice(root/'missing-data',root=root)
                load.assert_not_called()


if __name__=='__main__': unittest.main()
