"""Artificial execution fixtures only: no historical market/archive loading."""
import copy
import importlib.util
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

from ops import issue1388_bband_rsi_v1 as draft

H = draft.HOUR


def bars(count=8, *, segment="A"):
    return [{"open_ts_ms": i * H, "close_ts_ms": (i + 1) * H, "available_ts_ms": (i + 1) * H,
             "segment_id": segment, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
            for i in range(count)]


def run(data, entries=(0,), exits=(), *, funding=(), end=None, start=0, symbol="ETH-USDT"):
    entry_flags = [i in entries for i in range(len(data))]
    exit_flags = [i in exits for i in range(len(data))]
    bound = draft.bind_bband_decisions(data, entry_flags, exit_flags)
    return draft.replay_bband_rsi(symbol, data, bound, funding, start_ms=start,
                                  end_ms=(len(data) * H if end is None else end), roundtrip_cost_bps=14.0)


class ExecutionFixtures(unittest.TestCase):
    def test_entry_waits_for_completed_signal_and_first_eligible_open(self):
        data = bars()
        data[0]["available_ts_ms"] = 2 * H + 1
        result = run(data)
        self.assertEqual(result["open_position"]["entry_ts_ms"], 3 * H)
        self.assertEqual(result["open_entry_cost_bps"], 7.0)
        self.assertEqual(len(result["orders"]), 1)

    def test_full_rsi_prefix_receipt_gates_signal(self):
        data = bars()
        data[0]["available_ts_ms"] = 4 * H + 1
        result = run(data, entries=(2,))
        self.assertEqual(result["open_position"]["entry_ts_ms"], 5 * H)
        bound = draft.bind_bband_decisions(data, [False, False, True] + [False] * 5, [False] * 8)
        self.assertEqual(bound[2]["signal_available_ts_ms"], 4 * H + 1)

    def test_delayed_signal_does_not_observe_unfilled_position_stop(self):
        data = bars()
        data[0]["available_ts_ms"] = 3 * H
        data[1].update(low=50.0, high=150.0)
        result = run(data)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["open_position"]["entry_ts_ms"], 3 * H)

    def test_rsi_exit_waits_for_all_dependencies_and_uses_actual_open(self):
        data = bars()
        data[2]["available_ts_ms"] = 4 * H + 1
        data[5].update(open=103.0, high=104.0, close=103.0)
        result = run(data, exits=(2,))
        self.assertEqual(result["trades"][0]["exit_ts_ms"], 5 * H)
        self.assertEqual(result["trades"][0]["exit_price"], 103.0)
        self.assertEqual(result["trades"][0]["exit_reason"], "NEXT_AVAILABLE_OPEN_RSI_EXIT")

    def test_constant_ten_percent_roi_and_twentyfive_percent_stop(self):
        data = bars()
        data[2].update(high=111.0)
        result = run(data)
        self.assertAlmostEqual(result["trades"][0]["exit_price"], 110.0)
        self.assertEqual(result["trades"][0]["exit_reason"], "INTRABAR_ROI")
        self.assertAlmostEqual(result["trades"][0]["gross_bps"], 1000.0)
        self.assertEqual(result["trades"][0]["cost_bps"], 14.0)

    def test_exact_roi_open_and_intrabar_boundaries_are_not_float_missed(self):
        for entry, target in ((100.0, 110.0), (123.45, 135.795)):
            for at_open in (False, True):
                with self.subTest(entry=entry, at_open=at_open):
                    data = bars()
                    for row in data:
                        row.update(open=entry, close=entry, high=entry + 1, low=entry - 1)
                    data[2]["high"] = target
                    if at_open:
                        data[2].update(open=target, low=entry * 0.7)
                    result = run(data)
                    self.assertEqual(result["trades"][0]["exit_price"], target)
                    self.assertEqual(result["trades"][0]["exit_reason"], "OPEN_ROI" if at_open else "INTRABAR_ROI")
                    self.assertEqual(len(result["trades"]), 1)

    def test_normal_open_ambiguous_candle_stop_first(self):
        data = bars()
        data[2].update(low=70.0, high=120.0)
        trade = run(data)["trades"][0]
        self.assertEqual(trade["exit_price"], 75.0)
        self.assertEqual(trade["exit_reason"], "INTRABAR_STOP_FIRST")
        self.assertAlmostEqual(trade["gross_bps"], -2500.0)

    def test_worse_open_stop_uses_actual_open(self):
        data = bars()
        data[2].update(open=70.0, low=60.0, high=120.0, close=100.0)
        trade = run(data)["trades"][0]
        self.assertEqual((trade["exit_ts_ms"], trade["exit_price"], trade["exit_reason"]), (2 * H, 70.0, "OPEN_STOP"))

    def test_better_open_roi_precedes_later_low_stop_ambiguity(self):
        data = bars()
        data[2].update(open=115.0, low=70.0, high=120.0, close=100.0)
        trade = run(data)["trades"][0]
        self.assertEqual((trade["exit_ts_ms"], trade["exit_price"], trade["exit_reason"]), (2 * H, 115.0, "OPEN_ROI"))

    def test_available_rsi_exit_collision_with_open_risk_executes_once(self):
        for opening, reason in ((70.0, "OPEN_STOP"), (115.0, "OPEN_ROI"), (103.0, "NEXT_AVAILABLE_OPEN_RSI_EXIT")):
            with self.subTest(opening=opening):
                data = bars()
                data[2].update(open=opening, low=min(opening, 99), high=max(opening, 101), close=100.0)
                result = run(data, exits=(1,))
                self.assertEqual(len(result["trades"]), 1)
                self.assertEqual(result["trades"][0]["exit_reason"], reason)
                self.assertEqual(len(result["orders"]), 2)

    def test_delayed_exit_cannot_close_replacement_position(self):
        data = bars(10)
        data[2]["available_ts_ms"] = 7 * H
        data[3].update(low=70.0)
        result = run(data, entries=(0, 4), exits=(2,))
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0]["exit_reason"], "INTRABAR_STOP_FIRST")
        self.assertEqual(result["open_position"]["entry_ts_ms"], 7 * H)
        self.assertIsNone(result["pending_exit"])

    def test_occupied_and_pending_entry_rejections_do_not_overwrite(self):
        data = bars()
        data[0]["available_ts_ms"] = 3 * H
        result = run(data, entries=(0, 1, 3))
        self.assertEqual(result["pending_entry_rejections"], 1)
        self.assertEqual(result["occupied_rejections"], 1)
        self.assertEqual(result["open_position"]["signal_open_ts_ms"], 0)

    def test_occupied_time_and_segment_gaps_preserve_state(self):
        for kind in ("time", "segment"):
            with self.subTest(kind=kind):
                data = bars()
                if kind == "time":
                    del data[3]
                else:
                    for row in data[3:]:
                        row["segment_id"] = "B"
                result = run(data, end=8 * H)
                self.assertEqual(result["disposition"], "BLOCKED_SOURCE_GAP")
                self.assertEqual(result["trades"], [])
                self.assertEqual(result["open_position"]["entry_ts_ms"], H)
                self.assertEqual(result["open_entry_cost_bps"], 7.0)
                self.assertIsNone(result["open_position"]["funding_bps_to_end_exclusive"])

    def test_pending_gap_preserves_unfilled_entry_without_fee(self):
        data = bars()
        data[0]["available_ts_ms"] = 4 * H
        del data[2]
        result = run(data, end=8 * H)
        self.assertEqual(result["disposition"], "BLOCKED_SOURCE_GAP")
        self.assertEqual(result["paid_trading_cost_bps"], 0.0)
        self.assertIsNotNone(result["pending_entry"])

    def test_unoccupied_gap_can_reset_and_start_new_segment(self):
        data = bars()
        del data[1]
        result = run(data, entries=(2,), end=8 * H)
        self.assertIsNone(result["gap_quarantine"])
        self.assertIsNotNone(result["open_position"])

    def test_end_open_entry_cost_retained_no_end_or_after_end_order(self):
        data = bars(9)
        data[8].update(open=200.0, low=50.0, high=300.0, close=200.0)
        result = run(data, end=8 * H)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["disposition"], "BLOCKED_TERMINAL_UNRESOLVED")
        self.assertEqual(result["open_entry_cost_bps"], 7.0)
        self.assertTrue(all(o["execution_ts_ms"] < 8 * H for o in result["orders"]))
        self.assertIsNone(result["account_nav"])

    def test_entry_available_exact_end_stays_unfilled(self):
        data = bars()
        data[0]["available_ts_ms"] = 8 * H
        result = run(data)
        self.assertEqual(result["orders"], [])
        self.assertIsNotNone(result["pending_entry"])
        self.assertEqual(result["unresolved_end"], 1)

    def test_end_signal_does_not_create_new_pending_order(self):
        result = run(bars(), entries=(7,))
        self.assertIsNone(result["pending_entry"])
        self.assertEqual(result["orders"], [])

    def test_last_bar_protective_touch_retained_without_end_fill(self):
        data = bars()
        data[7].update(low=70.0, high=120.0)
        result = run(data)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["terminal_protective_touch"]["reason"], "INTRABAR_STOP_FIRST")
        self.assertEqual(result["open_entry_cost_bps"], 7.0)
        self.assertIsNone(result["open_position"]["funding_bps_to_end_exclusive"])

    def test_late_protective_touch_preserves_exact_state_no_trade_fee_or_credit(self):
        data = bars()
        data[1]["available_ts_ms"] = 8 * H
        data[2].update(low=70.0, available_ts_ms=7 * H)
        funding = [{"symbol": "ETH-USDT", "fundingTime": 2 * H + H // 2,
                    "fundingRate": -0.002, "markPrice": 100.0}]
        result = run(data, exits=(1,), entries=(0, 4), funding=funding)
        self.assertEqual(result["disposition"], "BLOCKED_PROTECTIVE_TOUCH_CLOCK_UNRESOLVED")
        self.assertEqual(result["trades"], [])
        self.assertEqual(len(result["orders"]), 1)
        self.assertEqual(result["paid_trading_cost_bps"], 7.0)
        self.assertEqual(result["open_entry_cost_bps"], 7.0)
        self.assertIsNone(result["open_position"]["funding_bps_to_end_exclusive"])
        held = result["protective_touch_quarantine"]
        self.assertEqual(held["position"]["entry_identity"], result["open_position"]["entry_identity"])
        self.assertEqual(held["pending_exit"], result["pending_exit"])
        self.assertEqual(result["open_position"]["entry_ts_ms"], H)

    def test_signed_funding_credit_interior_adverse_boundaries_end_excluded(self):
        data = bars()
        funding = [{"symbol": "ETH-USDT", "fundingTime": stamp, "fundingRate": rate, "markPrice": 100.0}
                   for stamp, rate in ((H, -0.001), (2 * H, -0.002), (4 * H, 0.003), (8 * H, 0.5))]
        result = run(data, exits=(3,), funding=funding)
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["funding_bps"], 10.0)  # entry credit dropped, interior-20 + exit debit30
        self.assertAlmostEqual(trade["net_bps"], -24.0)
        self.assertEqual(trade["funding_settlements"], 2)
        negative_exit = copy.deepcopy(funding)
        negative_exit[2]["fundingRate"] = -0.003
        self.assertAlmostEqual(run(data, exits=(3,), funding=negative_exit)["trades"][0]["funding_bps"], -20.0)

    def test_open_funding_preserves_signed_credit_and_excludes_end(self):
        funding = [{"symbol": "ETH-USDT", "fundingTime": stamp, "fundingRate": rate, "markPrice": 100.0}
                   for stamp, rate in ((H, 0.001), (2 * H, -0.002), (8 * H, 0.5))]
        result = run(bars(), funding=funding)
        self.assertAlmostEqual(result["open_position"]["funding_bps_to_end_exclusive"], -10.0)
        self.assertFalse(result["funding_coverage_certified_by_helper"])

    def test_missing_funding_remains_unknown_not_zero(self):
        result = run(bars(), exits=(2,), funding=None)
        self.assertEqual(result["disposition"], "BLOCKED_MISSING_FUNDING")
        self.assertIsNone(result["trades"][0]["funding_bps"])
        self.assertIsNone(result["trades"][0]["net_bps"])

    def test_fee_paid_legs_reconcile_closed_plus_open(self):
        result = run(bars(10), entries=(0, 4), exits=(2,))
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["paid_trading_cost_bps"], 21.0)
        self.assertEqual(result["closed_trading_cost_bps"], 14.0)
        self.assertEqual(result["open_entry_cost_bps"], 7.0)
        self.assertEqual(result["economic_disposition"], "NOT_EVALUATED_NO_THRESHOLD_ADDED")
        self.assertFalse(result["source_profits_reproduced"])

    def test_invalid_funding_and_malformed_source_fail_before_execution(self):
        for invalid in ({"symbol": "BTC-USDT", "fundingTime": H, "fundingRate": 0, "markPrice": 100},
                        {"fundingTime": H, "fundingRate": 0, "markPrice": 100},
                        {"symbol": "ETH-USDT", "fundingTime": H, "fundingRate": True, "markPrice": 100}):
            with self.subTest(invalid=invalid), self.assertRaises(draft.DraftError):
                run(bars(), funding=[invalid])
        duplicate = {"symbol": "ETH-USDT", "fundingTime": H, "fundingRate": 0, "markPrice": 100}
        with self.assertRaises(draft.DraftError):
            run(bars(), funding=[duplicate, duplicate])
        data = bars()
        data[2]["low"] = 200.0
        with self.assertRaises(draft.DraftError):
            run(data)

    def test_signal_binding_types_lengths_and_clock_drift_reject(self):
        data = bars()
        for entries, exits in (([False] * 7, [False] * 8), ([1] * 8, [False] * 8), ([True] * 8, [True] * 8)):
            with self.subTest(entries=entries), self.assertRaises(draft.DraftError):
                draft.bind_bband_decisions(data, entries, exits)
        bound = draft.bind_bband_decisions(data, [True] + [False] * 7, [False] * 8)
        bound[0]["signal_available_ts_ms"] = 0
        with self.assertRaises(draft.DraftError):
            draft.replay_bband_rsi("ETH-USDT", data, bound, [], start_ms=0, end_ms=8 * H, roundtrip_cost_bps=14.0)


class SourceMappingFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read source code only and feed artificial hourly arrays. No market loader.
        from ops import issue1388_alpha_screen_v1
        cls.common = issue1388_alpha_screen_v1

    def test_pinned_common_entry_exact_typical_bband_and_strict_rsi(self):
        import pandas as pd
        data = pd.DataFrame(bars(40))
        for i in range(20, 40):
            price = 100.0 - (i - 19) * 2.0
            data.loc[i, ["open", "close", "high", "low"]] = [price, price, price + 1, price - 1]
        typical = (data.high + data.low + data.close) / 3
        lower = typical.rolling(20, min_periods=1).mean() - 2 * typical.rolling(20, min_periods=1).std(ddof=1)
        rsi = self.common._rsi(data.close, 14)
        expected = ((rsi < 30) & (data.close < lower)).fillna(False)
        actual = self.common.bband_rsi_entry_signals(data)
        self.assertEqual(actual.tolist(), expected.tolist())
        self.assertTrue(bool(actual.any()))
        self.assertTrue(bool(actual.iloc[20]))
        decisions = draft.bind_bband_decisions(data.to_dict("records"), actual.tolist(), draft.exit_flags_from_rsi14(rsi.tolist()))
        self.assertEqual([d["exit"] for d in decisions], rsi.gt(70).fillna(False).tolist())

    def test_strict_threshold_boundaries_and_constant_series_startup(self):
        import pandas as pd
        data = pd.DataFrame(bars(30))
        self.assertFalse(bool(self.common.bband_rsi_entry_signals(data).any()))
        self.assertEqual(draft.exit_flags_from_rsi14([float("nan"), 70.0, 70.0001]), [False, False, True])
        with patch.object(self.common, "_rsi", return_value=pd.Series(29.9999, index=data.index)):
            self.assertFalse(bool(self.common.bband_rsi_entry_signals(data).any()))  # close=lower exactly
            # Keep typical price exactly100 but set completed close just below lower.
            data.loc[29, ["high", "low", "close"]] = [101.000001, 99.0, 99.999999]
            self.assertTrue(bool(self.common.bband_rsi_entry_signals(data).iloc[29]))
        with patch.object(self.common, "_rsi", return_value=pd.Series(30.0, index=data.index)):
            self.assertFalse(bool(self.common.bband_rsi_entry_signals(data).iloc[29]))

    def test_exit_threshold_rejects_malformed_rsi_instead_of_signal(self):
        for value in (True, None, "bad", -1, 101, float("inf")):
            with self.subTest(value=value), self.assertRaises(draft.DraftError):
                draft.exit_flags_from_rsi14([value])


if __name__ == "__main__":
    unittest.main()

import json
import hashlib
import pandas as pd
import pytest
from ops import issue1388_alpha_screen_v1 as common


def common_market(monkeypatch):
    monkeypatch.setattr(common, 'START_MS', 0)
    monkeypatch.setattr(common, 'END_MS', 16 * H)
    data = pd.DataFrame(bars(16))
    data['volume'] = 1.0
    market = {'frames': {s: data.copy() for s in common.SYMBOLS},
              'costs': {s: 14.0 for s in common.SYMBOLS},
              'six_funding': {s: [{'symbol': s, 'fundingTime': t, 'fundingRate': '0.0001', 'markPrice': '100'} for t in [0, 8 * H]] for s in common.SYMBOLS}}
    monkeypatch.setattr(common, 'bband_rsi_entry_signals', lambda f: pd.Series([True] + [False] * (len(f)-1), index=f.index))
    monkeypatch.setattr(common, '_rsi', lambda c, n: pd.Series([0.0, 80.0] + [50.0] * (len(c)-2), index=c.index))
    return market


def test_common_dispatch_actual_six_costed_ledgers_and_independent_audit(monkeypatch):
    market = common_market(monkeypatch)
    monkeypatch.setattr(common, 'replay_symbol', lambda *a: pytest.fail('wrongmodel'))
    value = common.screen(market, common.PROFILES[common.BBAND_RSI_ID])
    assert value['cost_1x']['T'] == 6
    assert set(value['symbol_accounting']) == set(common.SYMBOLS)
    assert value['disposition'] == 'REJECT_ECONOMIC_EARLY'
    assert value['cost_1x'] == common.summarize(value['trades'], 1)
    assert value['cost_2x'] == common.summarize(value['trades'], 2)
    common.audit_bband_result(value, market)


def test_common_six_funding_archive_identity_and_complete_window():
    data = common.load_six_funding()
    assert set(data) == set(common.SYMBOLS)
    for symbol, rows in data.items():
        assert len(rows) == 465
        assert all(r['symbol'] == symbol for r in rows)
        assert rows[0]['fundingTime'] == common.START_MS
        assert rows[-1]['fundingTime'] == common.END_MS - 8 * H


def test_common_missing_symbol_funding_blocks_before_any_signal(monkeypatch):
    market = common_market(monkeypatch)
    del market['six_funding']['SOL-USDT']
    monkeypatch.setattr(common, 'bband_rsi_entry_signals', lambda *a: pytest.fail('signal beforeallfunding'))
    with pytest.raises(common.ScreenError, match='SIX_FUNDING_REQUIRED_BEFORE_MODEL'):
        common.screen(market, common.PROFILES[common.BBAND_RSI_ID])


def test_funding_raw_and_external_receipt_rehash_cannot_change_pinned_archive(monkeypatch, tmp_path):
    for symbol in common.SYMBOLS:
        for kind in ['RAW', 'RECEIPT']:
            n = symbol.split('-')[0] + '_FUNDING_' + kind + '.json'
            (tmp_path/n).write_bytes((common.INTAKE_PATH.parent/n).read_bytes())
    raw = tmp_path/'XRP_FUNDING_RAW.json'
    value = json.loads(raw.read_bytes()); value['data'][0]['fundingRate'] = '0.999'
    raw.write_text(json.dumps(value))
    path = tmp_path/'XRP_FUNDING_RECEIPT.json'
    receipt = json.loads(path.read_bytes()); receipt['raw_sha256'] = hashlib.sha256(raw.read_bytes()).hexdigest()
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr(common, 'INTAKE_PATH', tmp_path/'INTAKE.json')
    with pytest.raises(common.ScreenError, match='FUNDING_INPUT_HASH_DRIFT:XRP'):
        common.load_six_funding()


@pytest.mark.parametrize('field', ['gross_bps','net_bps','funding_settlements'])
def test_coherent_saved_trade_outer_rehash_tamper_is_rejected(monkeypatch, field):
    market = common_market(monkeypatch)
    value = common.screen(market, common.PROFILES[common.BBAND_RSI_ID])
    value['trades'][0][field] += 1
    value['cost_1x'] = common.summarize(value['trades'], 1)
    value['cost_2x'] = common.summarize(value['trades'], 2)
    value['result_sha256'] = common.digest({k:v for k,v in value.items() if k != 'result_sha256'})
    with pytest.raises(common.ScreenError, match='BBAND_SAVED_EXIT_GROSS_FUNDING'):
        common.audit_bband_result(value, market)


def bband_activation(market, head):
    profile = common.PROFILES[common.BBAND_RSI_ID]
    receipt = common.source_receipt(market, profile)
    proof = {'period_ms': [common.START_MS,common.END_MS], 'source_inventory_sha256': common.SOURCE_INVENTORY_SHA256,
             'economic_screen_consumed': 0, 'order_authority': 'BLOCKED', 'receipts': {'60':receipt},
             'candidates':{common.BBAND_RSI_ID:{**common.source_binding(profile), 'timeframe_min':60,
                 'signal_rules':profile['signal_rules'], 'source_exact_episodes':6}}}
    proof['result_sha256'] = common.digest(proof)
    base = 'research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/'
    files = ['ops/issue1388_alpha_screen_v1.py','ops/issue1388_bband_rsi_v1.py',base+'BBAND_EXECUTION_CONTRACT.json']
    files += [base+s.split('-')[0]+'_FUNDING_'+kind+'.json' for s in common.SYMBOLS for kind in ['RAW','RECEIPT']]
    return {'schema':'zel.issue1388.alpha_screen_activation.v1','issue':1388,'candidate_id':common.BBAND_RSI_ID,
            'token':profile['activation_token'],'reviewed_source_sha':head,**common.source_binding(profile),
            'source_inventory_sha256':common.SOURCE_INVENTORY_SHA256,'cost_sha256':common.COST_SHA256,
            'period_ms':[common.START_MS,common.END_MS],'timeframe_min':60,'global_heavy_group':common.GLOBAL_HEAVY_GROUP,
            'order_authority':'BLOCKED','promotion':False,'density_preflight':proof,'funding_hashes':common.six_funding_hashes(),
            'source_files_sha256':{n:common.file_sha256(common.ROOT/n) for n in files}}


def test_common_input_start_model_each_save_audit_persist_fixture(monkeypatch,tmp_path):
    market = common_market(monkeypatch)
    value = bband_activation(market,'a'*40)
    path = tmp_path/'activation.json';path.write_text(json.dumps(value))
    monkeypatch.setattr(common,'current_head',lambda:'a'*40)
    for k,v in [('GITHUB_RUN_ATTEMPT','1'),('GITHUB_EVENT_NAME','push'),('ISSUE1388_GLOBAL_HEAVY_GROUP',common.GLOBAL_HEAVY_GROUP)]:monkeypatch.setenv(k,v)
    sequence=[]
    def load(*args): sequence.append('input');return market
    def record(ref,name,value,parent):
        sequence.append(name)
        if name=='STARTED.json': assert sequence==['input','STARTED.json']
        else:
            assert (tmp_path/'output/RESULT.json').exists()
            common.audit_bband_result(value['result'],market)
        return 'b'*40
    monkeypatch.setattr(common,'load_market',load)
    monkeypatch.setattr(common,'create_record',record)
    result=common.execute(Path('/ARTIFICIAL_ONLY'),path,tmp_path/'output')
    assert result['state']=='COMPLETE_PERSISTED_AND_AUDITED'
    assert result['economic_table']['1x']['T']==6
    assert sequence==['input','STARTED.json','RESULT.json']
    assert (tmp_path/'output/SOL_FUNDING_RAW.json').exists()
    assert (tmp_path/'output/PERSISTED.json').exists()
    with pytest.raises(common.ScreenError,match='OUTPUT_DIRECTORY_ALREADY_EXISTS'):
        common.execute(Path('/ARTIFICIAL_ONLY'),path,tmp_path/'output')


def test_changed_preflight_funding_binding_has_no_start_claim(monkeypatch,tmp_path):
    market=common_market(monkeypatch)
    value=bband_activation(market,'a'*40)
    value['funding_hashes']['XRP-USDT']['raw']='0'*64
    path=tmp_path/'activation.json';path.write_text(json.dumps(value))
    monkeypatch.setattr(common,'current_head',lambda:'a'*40)
    for k,v in [('GITHUB_RUN_ATTEMPT','1'),('GITHUB_EVENT_NAME','push'),('ISSUE1388_GLOBAL_HEAVY_GROUP',common.GLOBAL_HEAVY_GROUP)]:monkeypatch.setenv(k,v)
    monkeypatch.setattr(common,'load_market',lambda *a:market)
    monkeypatch.setattr(common,'create_record',lambda *a:pytest.fail('mustnotclaim'))
    with pytest.raises(common.ScreenError,match='BBAND_PREFLIGHT_INPUT_FUNDING'):
        common.execute(Path('/ARTIFICIAL_ONLY'),path,tmp_path/'output')


def test_exported_funding_hash_bundle_has_no_mutable_alias_to_frozen_policy():
    original = copy.deepcopy(common.OTHER_FUNDING_HASHES)
    value = common.six_funding_hashes()
    value['XRP-USDT']['raw'] = '0' * 64
    assert common.OTHER_FUNDING_HASHES == original
    assert common.six_funding_hashes()['XRP-USDT']['raw'] == original['XRP-USDT']['raw']


@pytest.mark.parametrize("tamper", ["late_exit", "fake_entry", "fake_exit_signal", "exit_before_entry"])
def test_coherent_clock_rewrite_with_outer_rehash_is_rejected(monkeypatch,tamper):
    market=common_market(monkeypatch)
    value=common.screen(market,common.PROFILES[common.BBAND_RSI_ID])
    for saved in value['symbol_accounting'].values():
        entry,exit_=saved['orders'][:2]
        trade=saved['trades'][0]
        if tamper=='late_exit':
            exit_['execution_ts_ms'] += H;trade['exit_ts_ms'] += H
        elif tamper=='fake_entry':
            entry['signal_open_ts_ms'] += H
        elif tamper=='fake_exit_signal':
            exit_['signal_open_ts_ms'] += H
        else:
            exit_['execution_ts_ms']=0;trade['exit_ts_ms']=0
    value['trades']=sorted([t for x in value['symbol_accounting'].values() for t in x['trades']],key=lambda t:(t['exit_ts_ms'],t['symbol']))
    value['cost_1x']=common.summarize(value['trades'],1)
    value['cost_2x']=common.summarize(value['trades'],2)
    value['result_sha256']=common.digest({k:v for k,v in value.items() if k!='result_sha256'})
    with pytest.raises(common.ScreenError,match='BBAND_SAVED_(SOURCE_SIGNAL|EARLIEST_CAUSAL|EXECUTION_CHRONOLOGY)'):
        common.audit_bband_result(value,market)


def _rewrite_saved_result(value):
    value['trades'] = sorted(
        [trade for saved in value['symbol_accounting'].values() for trade in saved['trades']],
        key=lambda trade: (trade['exit_ts_ms'], trade['symbol']),
    )
    value['cost_1x'] = common.summarize(value['trades'], 1)
    value['cost_2x'] = common.summarize(value['trades'], 2)
    value['census']['completed'] = len(value['trades'])
    value['result_sha256'] = common.digest({k: v for k, v in value.items() if k != 'result_sha256'})


def _set_frame_prices(market, index, **prices):
    for frame in market['frames'].values():
        for field, value in prices.items():
            frame.loc[index, field] = value


def test_audit_rejects_trade_injected_from_entry_signal_discarded_while_occupied(monkeypatch):
    market = common_market(monkeypatch)
    _set_frame_prices(market, 2, open=110.0, high=111.0, low=109.0, close=110.0)
    _set_frame_prices(market, 3, open=121.0, high=122.0, low=120.0, close=121.0)
    monkeypatch.setattr(common, 'bband_rsi_entry_signals', lambda frame:
                        pd.Series([True, True] + [False] * (len(frame) - 2), index=frame.index))
    monkeypatch.setattr(common, '_rsi', lambda close, period: pd.Series(50.0, index=close.index))
    value = common.screen(market, common.PROFILES[common.BBAND_RSI_ID])
    assert len(value['trades']) == len(common.SYMBOLS)
    for symbol, saved in value['symbol_accounting'].items():
        clocks = {'signal_open_ts_ms': H, 'signal_close_ts_ms': 2 * H,
                  'signal_available_ts_ms': 2 * H}
        identity = f'{symbol}:{2 * H}:{H}'
        saved['orders'].extend([
            {'kind': 'ENTRY', 'execution_ts_ms': 2 * H, 'price': 110.0, 'quantity': 1,
             'cost_bps': 7.0, 'entry_identity': identity, **clocks},
            {'kind': 'EXIT', 'execution_ts_ms': 3 * H, 'price': 121.0, 'quantity': 1,
             'cost_bps': 7.0, 'entry_identity': identity, 'reason': 'OPEN_ROI'},
        ])
        saved['trades'].append({
            'identity': common.BBAND_RSI_ID, 'entry_identity': identity, 'symbol': symbol,
            'side': 'LONG', 'entry_ts_ms': 2 * H, 'entry_price': 110.0,
            'entry_cost_bps': 7.0, **clocks, 'exit_ts_ms': 3 * H, 'exit_price': 121.0,
            'exit_reason': 'OPEN_ROI', 'exit_time_kind': 'OBSERVED_OPEN',
            'gross_bps': 1000.0, 'cost_bps': 14.0, 'funding_bps': 0.0,
            'funding_settlements': 0, 'net_bps': 986.0,
        })
        saved['paid_trading_cost_bps'] += 14.0
        saved['closed_trading_cost_bps'] += 14.0
    _rewrite_saved_result(value)
    with pytest.raises(common.ScreenError, match='BBAND_SAVED_FIRST_ADMISSIBLE_ENTRY'):
        common.audit_bband_result(value, market)


def test_audit_rejects_skipped_early_stop_rewritten_as_later_roi(monkeypatch):
    market = common_market(monkeypatch)
    _set_frame_prices(market, 2, low=75.0)
    _set_frame_prices(market, 4, high=110.0)
    monkeypatch.setattr(common, '_rsi', lambda close, period: pd.Series(50.0, index=close.index))
    value = common.screen(market, common.PROFILES[common.BBAND_RSI_ID])
    assert value['cost_1x']['Gross_bps'] == -2500.0 * len(common.SYMBOLS)
    for saved in value['symbol_accounting'].values():
        order = saved['orders'][1]
        trade = saved['trades'][0]
        order.update(execution_ts_ms=5 * H, price=110.0, reason='INTRABAR_ROI')
        trade.update(exit_ts_ms=5 * H, exit_price=110.0, exit_reason='INTRABAR_ROI',
                     gross_bps=1000.0, funding_bps=0.0, funding_settlements=0,
                     net_bps=986.0)
    value['disposition'] = 'SCREEN_SURVIVOR_PENDING_FULL'
    _rewrite_saved_result(value)
    with pytest.raises(common.ScreenError, match='BBAND_SAVED_FIRST_EXIT_OR_SOURCE_GAP'):
        common.audit_bband_result(value, market)


def test_audit_rejects_later_flat_entry_when_earlier_admissible_trade_is_dropped(monkeypatch):
    market = common_market(monkeypatch)
    _set_frame_prices(market, 2, open=110.0, high=111.0, low=99.0, close=100.0)
    _set_frame_prices(market, 6, open=110.0, high=111.0, low=109.0, close=110.0)
    monkeypatch.setattr(common, 'bband_rsi_entry_signals', lambda frame:
                        pd.Series([True, False, False, False, True] + [False] * (len(frame) - 5),
                                  index=frame.index))
    monkeypatch.setattr(common, '_rsi', lambda close, period: pd.Series(50.0, index=close.index))
    value = common.screen(market, common.PROFILES[common.BBAND_RSI_ID])
    assert all(len(saved['trades']) == 2 for saved in value['symbol_accounting'].values())
    for saved in value['symbol_accounting'].values():
        saved['orders'] = saved['orders'][2:]
        saved['trades'] = saved['trades'][1:]
        saved['paid_trading_cost_bps'] = 14.0
        saved['closed_trading_cost_bps'] = 14.0
    _rewrite_saved_result(value)
    with pytest.raises(common.ScreenError, match='BBAND_SAVED_FIRST_ADMISSIBLE_ENTRY'):
        common.audit_bband_result(value, market)


def test_audit_rejects_closed_trade_crossing_occupied_source_segment_gap(monkeypatch):
    market = common_market(monkeypatch)
    _set_frame_prices(market, 4, open=110.0, high=111.0, low=109.0, close=110.0)
    monkeypatch.setattr(common, '_rsi', lambda close, period: pd.Series(50.0, index=close.index))
    value = common.screen(market, common.PROFILES[common.BBAND_RSI_ID])
    assert all(saved['trades'][0]['exit_ts_ms'] == 4 * H
               for saved in value['symbol_accounting'].values())
    for frame in market['frames'].values():
        frame.loc[2:, 'segment_id'] = 'B'
    with pytest.raises(common.ScreenError, match='BBAND_SAVED_FIRST_EXIT_OR_SOURCE_GAP'):
        common.audit_bband_result(value, market)
