import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from audit import admitted, metrics, overlap_count, trade_net


def row(n, *, sym="BTC-USDT", signal=100, entry=110, exit=120, gross=100, cost=20):
    return {
        "closed_trade_id": str(n),
        "symbol": sym,
        "side": "long",
        "signal_ts": signal,
        "entry_ts": entry,
        "exit_ts": exit,
        "gross_bps": gross,
        "cost_bps": cost,
        "net_bps": gross - cost,
    }


class G5AccountantTest(unittest.TestCase):
    def test_simple_cost(self):
        self.assertEqual(trade_net(row("a"), 2), 60)

    def test_cost_math_corruption_rejected(self):
        a = row("a")
        a["net_bps"] += 1
        with self.assertRaisesRegex(ValueError, "PARITY"):
            trade_net(a, 2)

    def test_boundary_strict(self):
        a = row("a", signal=99)
        self.assertEqual(admitted([a], 100, 150, 0), [])

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            admitted([row("x"), row("x")], 100, 150, 2)

    def test_count_mismatch(self):
        with self.assertRaisesRegex(ValueError, "G5_CLOSED_T_COUNT"):
            admitted([row("x")], 100, 150, 2)

    def test_incomplete_trade_rejected(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_TIME"):
            admitted([row("x", entry=130, exit=120)], 100, 150, 1)

    def test_future_exit_rejected(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_TIME"):
            admitted([row("x", exit=160)], 100, 150, 1)

    def test_non_long_rejected(self):
        x = row("x")
        x["side"] = "short"
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_SIDE"):
            admitted([x], 100, 150, 1)

    def test_excluding_winning_trades(self):
        a, b, c = (
            row("a", gross=120),
            row("b", sym="ETH-USDT", gross=80),
            row("c", sym="SOL-USDT", gross=-40),
        )
        r = metrics([a, b, c], 2)
        self.assertAlmostEqual(r["Net_sum_trade_bps"], 40)
        self.assertAlmostEqual(r["Net_excluding_top2_trade_bps"], -80)

    def test_overlap(self):
        a = row("a", entry=110, exit=120)
        b = row("b", entry=115, exit=130)
        c = row("c", sym="ETH-USDT", entry=120, exit=140)
        self.assertEqual(overlap_count([a], [b, c])["overlapping_trade_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
