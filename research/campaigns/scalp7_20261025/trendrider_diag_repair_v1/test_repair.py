from __future__ import annotations

import unittest

import funding_signed_reprice_v1 as fund
import trend_and_cost_gate_v1 as gates


def bars(n: int = 110, falling: bool = False):
    rows = []
    for i in range(n):
        close = 100 - i * 0.25 if falling else 100 + i * 0.25
        rows.append(
            {
                "ts_ms": i * 3600000,
                "open": close + 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1,
            }
        )
    return rows


class SourceAndTrendTests(unittest.TestCase):
    def test_adx_no_future_bar(self):
        base = bars(85, falling=True)
        a = gates.wilder_adx_di(base[:70])
        base[75]["high"] = 10000
        base[79]["low"] = 0.001
        b = gates.wilder_adx_di(base)
        for j in range(30, 70):
            self.assertEqual(a["ADX"][j], b["ADX"][j])
            self.assertEqual(a["DI+"][j], b["DI+"][j])
            self.assertEqual(a["DI-"][j], b["DI-"][j])

    def test_wilder_bear_trend_synthetic(self):
        f = gates.wilder_adx_di(bars(110, falling=True))
        self.assertGreaterEqual(float(f["ADX"][90]), 25)
        self.assertGreater(float(f["DI-"][90]), float(f["DI+"][90]))

    def test_adx_min_28_bars(self):
        x = gates.wilder_adx_di(bars(25))
        self.assertFalse(gates.qualified_bearish_dmi(index=20, features=x))

    def test_fee_floor_exact_10_bps(self):
        self.assertTrue(
            gates.valid_fee_stop_minimum(
                {
                    "entry": 100,
                    "intent_geometry": {"sl": 99.8999},
                }
            )
        )
        self.assertFalse(
            gates.valid_fee_stop_minimum(
                {
                    "entry": 100,
                    "intent_geometry": {"sl": 99.91},
                }
            )
        )
        self.assertFalse(
            gates.valid_fee_stop_minimum(
                {
                    "entry": 100,
                    "intent_geometry": {"sl": 100.01},
                }
            )
        )

    def test_fee_floor_does_not_require_future_net_or_losers(self):
        item = {"entry": 100, "intent_geometry": {"sl": 99.80}}
        self.assertTrue(gates.valid_fee_stop_minimum(item))
        item["net_bps"] = -10000
        item["future_winner"] = True
        self.assertTrue(gates.valid_fee_stop_minimum(item))


class FundingBoundaryTests(unittest.TestCase):
    def test_positive_rate_long_pays_short_receives(self):
        data = {"BTC-USDT": [(3600000, 1.5)]}
        for side, result in (("long", 1.5), ("short", -1.5)):
            signed, amb, pess, diag = fund.funding_components(
                side=side,
                symbol="BTC-USDT",
                entry_ms=0,
                terminal_open_ms=7200000,
                effective_closed_at=10800000,
                funding=data,
            )
            self.assertEqual(signed, result)
            self.assertEqual(amb, 0)
            self.assertEqual(pess, 3 if side == "long" else 0)

    def test_negative_rate_short_pays_long_receives(self):
        data = {"BTC-USDT": [(3600000, -2.0)]}
        for side, result in (("long", -2.0), ("short", 2.0)):
            signed, amb, pess, _ = fund.funding_components(
                side=side,
                symbol="BTC-USDT",
                entry_ms=0,
                terminal_open_ms=7200000,
                effective_closed_at=10800000,
                funding=data,
            )
            self.assertEqual(signed, result)
            self.assertEqual(amb, 0)
            self.assertEqual(pess, 4 if side == "short" else 0)

    def test_funding_on_possible_exit_boundary_not_definite(self):
        data = {"BTC-USDT": [(7200000, 2.0)]}
        certain, amb, pess, diag = fund.funding_components(
            side="long",
            symbol="BTC-USDT",
            entry_ms=0,
            terminal_open_ms=7200000,
            effective_closed_at=10800000,
            funding=data,
        )
        self.assertEqual(certain, 0)
        self.assertEqual(amb, 2)
        self.assertEqual(pess, 4)
        self.assertEqual(diag["funding_events_certain"], 0)
        self.assertEqual(diag["funding_events_possible_boundary"], 1)

    def test_start_boundary_not_definite(self):
        data = {"BTC-USDT": [(3600000, 2.0)]}
        certain, amb, pess, _ = fund.funding_components(
            side="short",
            symbol="BTC-USDT",
            entry_ms=3600000,
            terminal_open_ms=7200000,
            effective_closed_at=10800000,
            funding=data,
        )
        self.assertEqual(certain, 0)
        self.assertEqual(amb, 0)
        self.assertEqual(pess, 0)

    def test_no_funding_outside_holding_interval(self):
        data = {"BTC-USDT": [(-3600000, 2.0), (10800001, -4.0)]}
        c, a, p, _ = fund.funding_components(
            side="short",
            symbol="BTC-USDT",
            entry_ms=0,
            terminal_open_ms=7200000,
            effective_closed_at=10800000,
            funding=data,
        )
        self.assertEqual((c, a, p), (0, 0, 0))

    def test_source_none_across_absent_window_not_fabricated(self):
        data = {"ETHFI-USDT": []}
        c, a, p, _ = fund.funding_components(
            side="long",
            symbol="ETHFI-USDT",
            entry_ms=0,
            terminal_open_ms=3600000,
            effective_closed_at=7200000,
            funding=data,
        )
        self.assertEqual((c, a, p), (0, 0, 0))

    def test_bad_exit_temporal_order_rejected(self):
        with self.assertRaises(RuntimeError):
            fund.funding_components(
                side="long",
                symbol="BTC-USDT",
                entry_ms=7200000,
                terminal_open_ms=3600000,
                effective_closed_at=7200000,
                funding={"BTC-USDT": []},
            )


if __name__ == "__main__":
    unittest.main()
