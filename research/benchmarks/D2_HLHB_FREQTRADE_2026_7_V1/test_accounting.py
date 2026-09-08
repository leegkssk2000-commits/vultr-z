"""Synthetic accounting checks; no observed market input or engine runs."""
import unittest
from accounting import BAR_MS, cost, cost_breakdown, digest, metrics, normalize_engine, normalize_saved, verify_cost_binding


class AccountingTests(unittest.TestCase):
    def packet(self):
        return {"costs": {"BTC-USDT": {"fee_bps": 10., "spread_bps": 1., "impact_bps": 2., "funding_p95_per_settlement_bps": 10.}},
                "rows_by": {"BTC-USDT": [{"bar_close_ts": i*BAR_MS, "close": p} for i, p in [(1, 100.), (2, 90.), (3, 105.)]]}}

    def raw(self, reason="force_exit"):
        return {"pair": "BTC/USDT", "open_date": 0, "close_date": BAR_MS, "open_rate": 100., "close_rate": 90.,
                "exit_reason": reason, "profit_ratio": -.101, "profit_abs": -101., "fee_open": .0005, "fee_close": .0005}

    def test_inherited_cost_floor_boundary_and_binding(self):
        c = self.packet()["costs"]
        b = c["BTC-USDT"]
        self.assertEqual(cost(0, 0, b), 20.)
        self.assertEqual(cost(0, 2*BAR_MS, b), 23.)
        self.assertEqual(cost(2*BAR_MS, 2*BAR_MS, b), 20.)
        self.assertEqual(verify_cost_binding(c, digest(c))["sha256"], digest(c))
        with self.assertRaisesRegex(ValueError, "COST_BINDING"):
            verify_cost_binding(c)

    def test_force_exit_remains_open_mark_engine_pnl_is_separate(self):
        p = self.packet(); ts = normalize_engine([self.raw()], p, 3*BAR_MS)
        self.assertFalse(ts[0]["closed"])
        self.assertEqual(ts[0]["exit_price"], 105.)
        self.assertEqual(ts[0]["engine"]["profit_abs"], -101.)
        m = metrics(ts, p, 0, 3*BAR_MS)
        self.assertEqual((m["closed"], m["open"]), (0, 1))
        self.assertIsNone(m["win_rate"])
        self.assertAlmostEqual(m["terminal_net"], 477.)
        self.assertAlmostEqual(m["mark4h_DD"], 1023.)

    def test_intrabar_cost_has_settlement_bounds(self):
        t = normalize_engine([self.raw("stop_loss")], self.packet(), 3*BAR_MS)[0]
        self.assertEqual(t["cost_lower_bps"], 20.)
        self.assertEqual(t["cost_bps"], 23.)
        self.assertEqual(t["exit_ts"]-t["exit_ts_lower"], BAR_MS)
        self.assertEqual(t["cost_breakdown_lower"]["fee_bps"], t["cost_breakdown_upper"]["fee_bps"])

    def test_native_mismatched_cost_is_rejected(self):
        row = {"symbol": "BTC-USDT", "entry_ts": 0, "exit_ts": BAR_MS, "entry_price": 100., "exit_price": 90.,
               "gross_bps": -1000., "net_bps": -1019., "cost_bps": 19., "cost2x_net_bps": -1038.}
        with self.assertRaisesRegex(ValueError, "NATIVE_COST_FORMULA"):
            normalize_saved({"trades": [row]}, self.packet())

    def test_missing_active_mark_fails(self):
        p = self.packet(); ts = normalize_engine([self.raw()], p, 3*BAR_MS)
        p["rows_by"]["OTHER-USDT"] = [{"bar_close_ts": BAR_MS+1, "close": 100.}]
        with self.assertRaisesRegex(ValueError, "MISSING_ACTIVE"):
            metrics(ts, p, 0, 3*BAR_MS)


if __name__ == "__main__":
    unittest.main()
