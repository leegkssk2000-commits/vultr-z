"""Synthetic integration only; not a DEV economic run or model allocation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dev_runner as runner
from reference import fixture_run

HERE=Path(__file__).parent


class RunnerTests(unittest.TestCase):
    def test_two_cost_columns_single_ledger(self):
        rows=[{'net1_bp':80,'net2_bp':60},{'net1_bp':-30,'net2_bp':-50}]
        one=runner.metrics(rows,'net1_bp'); two=runner.metrics(rows,'net2_bp')
        self.assertEqual(one['sum_trade_bps']-two['sum_trade_bps'],20*one['T'])
        self.assertEqual(two['exit_order_trade_bps_DD'],50)
        self.assertEqual(two['PF'],1.2)

    def test_censored_exposure_not_zero_or_dropped(self):
        bars=[{'timestamp_ms':i*3600000,'open':100,'high':110,'low':90,'close':95} for i in range(241)]
        result={'trades':[],'events':[], 'censored':[{'kind':'OPEN_POSITION','entry_index':240,'mark_gross_bp':-500}],
                'state':'OPEN','ambiguous_entry_targets':0}
        m={'symbols':['BTC-USDT'],'tick_sizes':{'BTC-USDT':1},'dev_start_ms':240*3600000,'dev_end_ms':241*3600000}
        with patch.object(runner,'run',return_value=copy.deepcopy(result)):
            report=runner.evaluate({'bars_by_symbol':{'BTC-USDT':bars},'limitations':[]},m)
        self.assertEqual(report['cost2']['T'],0)
        self.assertEqual(report['frequency']['entry_count_including_censored'],1)
        self.assertEqual(report['censored'][0]['hypothetical_mark_liquidation']['net2_bp'],-540)
        self.assertEqual(report['disposition'],'INCOMPLETE_CENSORED_NO_PROMOTION')

    def test_claim_prevents_duplicate_before_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir()
            manifest=root/'input.json'; manifest.write_text(json.dumps({'snapshot_root':str(source)}))
            (root/(runner.CANDIDATE+'.claim.json')).write_text('{}')
            with patch.object(runner,'preflight',return_value={}), patch.object(runner,'evaluate',side_effect=AssertionError('must not run')):
                code=runner.main(['dev','--manifest',str(manifest),'--input-sha256',runner.sha(manifest),'--claim-dir',str(root),'--out',str(root/'result.json')])
            self.assertEqual(code,2)
            self.assertFalse((root/'result.json').exists())

    def test_manifest_race_rejected_before_claim_or_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir()
            manifest=root/'input.json'; manifest.write_text(json.dumps({'snapshot_root':str(source)}))
            expected=runner.sha(manifest)
            def changed(*args, **kwargs):
                manifest.write_text(json.dumps({'snapshot_root':str(source),'tick_sizes':{'BTC-USDT':999}}))
                return {}
            with patch.object(runner,'preflight',side_effect=changed),patch.object(runner,'evaluate',side_effect=AssertionError('must not run')):
                code=runner.main(['dev','--manifest',str(manifest),'--input-sha256',expected,'--claim-dir',str(root),'--out',str(root/'result.json')])
            self.assertEqual(code,2)
            self.assertFalse((root/(runner.CANDIDATE+'.claim.json')).exists())

    def test_output_in_source_rejected_before_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir()
            manifest=root/'input.json'; manifest.write_text(json.dumps({'snapshot_root':str(source)}))
            with patch.object(runner,'preflight',return_value={}),patch.object(runner,'evaluate',side_effect=AssertionError('must not run')):
                code=runner.main(['dev','--manifest',str(manifest),'--input-sha256',runner.sha(manifest),'--claim-dir',str(root),'--out',str(source/'result.json')])
            self.assertEqual(code,2)
            self.assertFalse((root/(runner.CANDIDATE+'.claim.json')).exists())


if __name__=='__main__':
    unittest.main()
