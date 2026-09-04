from __future__ import annotations

import unittest
from copy import deepcopy

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as bridge


class FakeProvider:
    def __init__(self, depths=None, funding_rows=None, path_rows=None):
        self.depths = list(depths or [])
        self.funding_rows = list(funding_rows or [])
        self.path_rows = list(path_rows or [])

    def depth(self, symbol: str, reference_notional: float):
        if not self.depths:
            raise RuntimeError("NO_FAKE_DEPTH")
        row = dict(self.depths.pop(0))
        row.setdefault("schema_version", "zel.g5.forward_real_depth_snapshot.v1")
        row.setdefault("symbol", symbol)
        row.setdefault("requested_at_ms", row["observed_at_ms"])
        row.setdefault("reference_notional_usdt", reference_notional)
        row.setdefault("source_endpoint", "/openApi/swap/v2/quote/depth")
        row.setdefault("point_in_time", True)
        unsigned = dict(row); unsigned.pop("snapshot_sha256", None)
        row["snapshot_sha256"] = bridge.stable(unsigned)
        return row

    def funding(self, symbol: str):
        body = {
            "schema_version": "zel.g5.forward_real_funding_snapshot.v1",
            "symbol": symbol,
            "requested_at_ms": 1,
            "observed_at_ms": 2,
            "rows": [dict(x) for x in self.funding_rows],
            "source_endpoint": "/openApi/swap/v2/quote/fundingRate",
            "signed_rates_preserved": True,
        }
        body["snapshot_sha256"] = bridge.stable(body)
        return body

    def path5m(self, symbol: str, start_ms: int, end_ms: int):
        body = {
            "schema_version": "zel.g5.forward_real_path5m.v1",
            "symbol": symbol,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "interval_ms": bridge.FIVE_MIN_MS,
            "rows": [dict(x) for x in self.path_rows],
        }
        body["path_sha256"] = bridge.stable(body)
        return body


def effective(max_hold=12):
    return {
        "active_strategies": [{
            "strategy_id": "keltner_trend",
            "child_id": "keltner_replacement_trend_pull_long_4h_h12_v2",
            "strategy_sha": "s",
            "entry_sha": "e",
            "exit_sha": "x",
            "config_sha": "c",
            "side": "long",
            "exit_rule": "time_stop",
            "max_hold_bars": max_hold,
        }]
    }


def cost():
    return {
        "state": "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY",
        "fee": {"taker_fee_bps_one_way": 5.0},
        "slippage_impact": {"reference_notional_usdt": 10000.0},
    }


def signal(event_ms: int, signal_close_ms: int, record_sha="sigsha"):
    return {
        "event_ts": bridge.iso_ms(event_ms),
        "record_sha256": record_sha,
        "status": "EVALUATED",
        "payload": {
            "strategy_id": "keltner_trend",
            "child_id": "keltner_replacement_trend_pull_long_4h_h12_v2",
            "symbol": "BTC-USDT",
            "side": "long",
            "signal": True,
            "result": "SIGNAL_EMITTED",
            "signal_bar_close_ts": signal_close_ms,
            "correct_child": True,
            "duplicate": 0,
            "lookahead": 0,
        },
    }


def depth(ts: int, mid=100.0, buy=100.05, sell=99.95):
    return {
        "observed_at_ms": ts,
        "bid": 99.9,
        "ask": 100.1,
        "mid": mid,
        "buy_vwap": buy,
        "sell_vwap": sell,
        "point_in_time": True,
    }


def path_row(ts=1, high=102.0, low=98.0):
    return {"ts_ms": ts, "open": 100.0, "high": high, "low": low, "close": 101.0}


class G5ForwardRealBridgeTest(unittest.TestCase):
    def test_01_first_run_only_activates_and_consumes_zero_old_signal(self):
        old = signal(900, 800)
        rows, evidence, canonical, status = bridge.process(
            source_rows=[old], bridge_rows=[], bridge_evidence=[], canonical_evidence=[],
            effective=effective(), cutover={"production_ready": True, "clean_runner_authority": True},
            stale={"authority_created": True, "data_stale_authority_allowed": True}, cost=cost(),
            provider=FakeProvider(), current_ms=1000, fee_authority_sha="fee-sha",
        )
        self.assertEqual(status["state"], "ACTIVATED_FUTURE_ONLY_WAIT_NEXT_SIGNAL")
        self.assertEqual(status["new_opens"], 0)
        self.assertEqual(rows[0]["kind"], "ACTIVATED")
        self.assertEqual(rows[0]["payload"]["preexisting_signals_consumed"], 0)
        self.assertEqual(evidence, [])
        self.assertEqual(canonical, [])

    def test_02_preactivation_signal_never_opens_after_activation(self):
        rows = []
        bridge.bridge_event(rows, kind="ACTIVATED", payload={"activation_ts_ms": 1000}, event_ts_ms=1000)
        provider = FakeProvider(depths=[depth(1200)])
        rows, _, _, status = bridge.process(
            source_rows=[signal(999, 900)], bridge_rows=rows, bridge_evidence=[], canonical_evidence=[],
            effective=effective(), cutover={"production_ready": True, "clean_runner_authority": True},
            stale={"authority_created": True, "data_stale_authority_allowed": True}, cost=cost(),
            provider=provider, current_ms=1200, fee_authority_sha="fee-sha",
        )
        self.assertEqual(status["new_opens"], 0)
        self.assertFalse(any(row["kind"] == "OPENED_PROVENANCE" for row in rows))

    def test_03_future_signal_captures_point_in_time_open_with_nonnull_size(self):
        rows = []
        bridge.bridge_event(rows, kind="ACTIVATED", payload={"activation_ts_ms": 1000}, event_ts_ms=1000)
        provider = FakeProvider(depths=[depth(2200)])
        rows, _, _, status = bridge.process(
            source_rows=[signal(1500, 1400)], bridge_rows=rows, bridge_evidence=[], canonical_evidence=[],
            effective=effective(), cutover={"production_ready": True, "clean_runner_authority": True},
            stale={"authority_created": True, "data_stale_authority_allowed": True}, cost=cost(),
            provider=provider, current_ms=2200, fee_authority_sha="fee-sha",
        )
        self.assertEqual(status["new_opens"], 1)
        opened = next(row["payload"] for row in rows if row["kind"] == "OPENED_PROVENANCE")
        self.assertEqual(opened["notional"], 10000.0)
        self.assertGreater(opened["qty"], 0)
        self.assertTrue(opened["entry_depth"]["point_in_time"])
        self.assertEqual(opened["exchange_order_submitted"], False)
        self.assertEqual(opened["order_authority"], "BLOCKED")

    def _opened_rows(self, *, hold_bars=1, entry_ts=2000, signal_close=1000):
        rows = []
        bridge.bridge_event(rows, kind="ACTIVATED", payload={"activation_ts_ms": 500}, event_ts_ms=500)
        d = FakeProvider(depths=[depth(entry_ts)])
        rows, _, _, _ = bridge.process(
            source_rows=[signal(800, signal_close)], bridge_rows=rows, bridge_evidence=[], canonical_evidence=[],
            effective=effective(max_hold=hold_bars), cutover={"production_ready": True, "clean_runner_authority": True},
            stale={"authority_created": True, "data_stale_authority_allowed": True}, cost=cost(),
            provider=d, current_ms=entry_ts, fee_authority_sha="fee-sha",
        )
        return rows

    def test_04_due_close_builds_production_grade_and_appends_canonical(self):
        signal_close = 1_000_000
        entry_ts = 1_100_000
        rows = self._opened_rows(hold_bars=1, entry_ts=entry_ts, signal_close=signal_close)
        due = signal_close + bridge.FOUR_HOURS_MS
        exit_ts = due + 1000
        funding_ts = entry_ts + bridge.EIGHT_HOURS_MS  # outside this short hold, so no settlement required
        provider = FakeProvider(
            depths=[depth(exit_ts, mid=102.0, buy=102.05, sell=101.95)],
            funding_rows=[{"ts_ms": funding_ts, "rate": 0.0001}],
            path_rows=[path_row(entry_ts + bridge.FIVE_MIN_MS)],
        )
        rows, evidence, canonical, status = bridge.process(
            source_rows=[signal(800, signal_close)], bridge_rows=rows, bridge_evidence=[], canonical_evidence=[],
            effective=effective(max_hold=1), cutover={"production_ready": True, "clean_runner_authority": True},
            stale={"authority_created": True, "data_stale_authority_allowed": True}, cost=cost(),
            provider=provider, current_ms=exit_ts, fee_authority_sha="fee-sha",
        )
        self.assertEqual(status["new_closes"], 1)
        self.assertEqual(status["new_production_grade_T"], 1)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(canonical), 1)
        row = evidence[0]
        self.assertTrue(row["production_grade"])
        self.assertEqual(row["production_fail_closed_reasons"], [])
        self.assertEqual(row["economic_origin"], "FORWARD_REAL")
        self.assertTrue(row["execution_provenance"]["intrabar_order_observed"])
        self.assertIsNotNone(row["trade"]["MFE_bps"])
        self.assertIsNotNone(row["trade"]["MAE_bps"])
        bridge.validate_evidence_row(row)

    def test_05_long_positive_signed_funding_is_cost(self):
        self.assertAlmostEqual(bridge.signed_funding_cost_bps("long", [{"rate": 0.0001}, {"rate": -0.00002}]), 0.8)

    def test_06_short_funding_sign_is_inverse(self):
        self.assertAlmostEqual(bridge.signed_funding_cost_bps("short", [{"rate": 0.0001}]), -1.0)

    def test_07_hold_ge_8h_without_settlement_fails_closed(self):
        opened = {
            "trade_id": "t", "strategy_id": "keltner_trend", "child_id": "c", "symbol": "BTC-USDT", "side": "long",
            "signal_bar_close_ts": 1, "source_signal_record_sha256": "s", "entry_ts": 1000,
            "entry_depth": FakeProvider(depths=[depth(1000)]).depth("BTC-USDT", 10000.0),
            "entry_delay_ms": 0, "exit_due_ts": 1000 + bridge.EIGHT_HOURS_MS,
            "notional": 10000.0, "qty": 100.0,
        }
        exit_depth = FakeProvider(depths=[depth(1000 + bridge.EIGHT_HOURS_MS + 1, mid=101)]).depth("BTC-USDT", 10000)
        funding = FakeProvider(funding_rows=[]).funding("BTC-USDT")
        path = FakeProvider(path_rows=[path_row(2000)]).path5m("BTC-USDT", 1000, int(exit_depth["observed_at_ms"]))
        row = bridge.evidence_row(opened=opened, exit_depth=exit_depth, funding_snapshot=funding, path=path, fee_one_way_bps=5.0, fee_authority_sha="fee", cutover_ready=True, stale_ready=True)
        self.assertFalse(row["production_grade"])
        self.assertIn("SIGNED_FUNDING_SETTLEMENT_LINEAGE_MISSING", row["production_fail_closed_reasons"])

    def test_08_missing_data_stale_authority_fails_closed(self):
        opened = {
            "trade_id": "t2", "strategy_id": "keltner_trend", "child_id": "c", "symbol": "BTC-USDT", "side": "long",
            "signal_bar_close_ts": 1, "source_signal_record_sha256": "s", "entry_ts": 1000,
            "entry_depth": FakeProvider(depths=[depth(1000)]).depth("BTC-USDT", 10000.0),
            "entry_delay_ms": 0, "exit_due_ts": 2000, "notional": 10000.0, "qty": 100.0,
        }
        ex = FakeProvider(depths=[depth(2000, mid=101)]).depth("BTC-USDT", 10000)
        fu = FakeProvider(funding_rows=[]).funding("BTC-USDT")
        pa = FakeProvider(path_rows=[path_row(1500)]).path5m("BTC-USDT", 1000, 2000)
        row = bridge.evidence_row(opened=opened, exit_depth=ex, funding_snapshot=fu, path=pa, fee_one_way_bps=5, fee_authority_sha="fee", cutover_ready=True, stale_ready=False)
        self.assertFalse(row["production_grade"])
        self.assertIn("DATA_STALE_AUTHORITY_MISSING", row["production_fail_closed_reasons"])

    def test_09_duplicate_source_signal_is_idempotent_after_open(self):
        rows = []
        bridge.bridge_event(rows, kind="ACTIVATED", payload={"activation_ts_ms": 1000}, event_ts_ms=1000)
        sig = signal(1500, 1400)
        provider = FakeProvider(depths=[depth(2000)])
        rows, _, _, _ = bridge.process(source_rows=[sig], bridge_rows=rows, bridge_evidence=[], canonical_evidence=[], effective=effective(), cutover={"production_ready": True, "clean_runner_authority": True}, stale={"authority_created": True, "data_stale_authority_allowed": True}, cost=cost(), provider=provider, current_ms=2000, fee_authority_sha="fee")
        rows2 = deepcopy(rows)
        rows2, _, _, status = bridge.process(source_rows=[sig], bridge_rows=rows2, bridge_evidence=[], canonical_evidence=[], effective=effective(), cutover={"production_ready": True, "clean_runner_authority": True}, stale={"authority_created": True, "data_stale_authority_allowed": True}, cost=cost(), provider=FakeProvider(), current_ms=2100, fee_authority_sha="fee")
        self.assertEqual(status["new_opens"], 0)
        self.assertEqual(sum(1 for row in rows2 if row["kind"] == "OPENED_PROVENANCE"), 1)

    def test_10_bridge_chain_tamper_is_rejected(self):
        rows = []
        bridge.bridge_event(rows, kind="ACTIVATED", payload={"activation_ts_ms": 1000}, event_ts_ms=1000)
        rows[0]["payload"]["activation_ts_ms"] = 999
        with self.assertRaisesRegex(RuntimeError, "BRIDGE_STATE_HASH"):
            bridge.validate_bridge_chain(rows)

    def test_11_contract_is_future_only_and_authority_blocked(self):
        contract = bridge.read_json(bridge.CONTRACT_PATH)
        bridge.validate_contract(contract)
        self.assertTrue(contract["activation"]["historical_backfill_forbidden"])
        self.assertEqual(contract["authority"]["order"], "BLOCKED")
        self.assertEqual(contract["authority"]["live"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
