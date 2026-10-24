import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen import decision, screen

H = 3600_000


def t(symbol, signal, available, gross, cost=10):
    return dict(
        symbol=symbol,
        signal_ts_ms=signal,
        entry_ts_ms=signal,
        outcome_available_ts_ms=available,
        gross_bps=gross,
        cost_bps=cost,
        identity="K",
        side=1,
    )


class Causal(unittest.TestCase):
    def test_two_past_losses_block(self):
        accepted = [t("A", 0, 2 * H, -100), t("B", 1 * H, 3 * H, -100)]
        self.assertTrue(decision(t("C", 4 * H, 5 * H, 10), accepted)[0])

    def test_unavailable_loss_cannot_block(self):
        accepted = [t("A", 0, 2 * H, -100), t("B", 1 * H, 6 * H, -100)]
        self.assertFalse(decision(t("C", 4 * H, 5 * H, 10), accepted)[0])

    def test_equal_timestamp_not_known(self):
        accepted = [t("A", 0, 2 * H, -100), t("B", 1 * H, 4 * H, -100)]
        self.assertFalse(decision(t("C", 4 * H, 5 * H, 10), accepted)[0])

    def test_expired_first_loss_not_counted(self):
        accepted = [t("A", 0, H, -100), t("B", 23 * H, 24 * H, -100)]
        self.assertFalse(decision(t("C", 26 * H, 27 * H, 10), accepted)[0])

    def test_expired_embargo(self):
        accepted = [t("A", 0, H, -100), t("B", 10 * H, 11 * H, -100)]
        self.assertFalse(decision(t("C", 24 * H, 25 * H, 10), accepted)[0])

    def test_positive_before_cutoff_not_loss(self):
        accepted = [t("A", 0, 2 * H, -100), t("B", 1 * H, 3 * H, 100)]
        self.assertFalse(decision(t("C", 4 * H, 5 * H, 10), accepted)[0])

    def test_blocked_counterfactual_cannot_trigger(self):
        rows = [
            t("A", 0, 2 * H, -100),
            t("B", 1 * H, 3 * H, -100),
            t("C", 4 * H, 5 * H, -100),
            t("D", 16 * H, 17 * H, 100),
        ]
        kept, removed, _ = screen(rows)
        self.assertEqual([x["symbol"] for x in removed], ["C"])
        self.assertIn("D", [x["symbol"] for x in kept])

    def test_uses_cost2(self):
        accepted = [t("A", 0, H, 15), t("B", 0, 2 * H, 15)]
        self.assertTrue(decision(t("C", 3 * H, 4 * H, 15), accepted)[0])

    def test_past_but_too_old_not_counted(self):
        accepted = [t("A", 0, H, -100), t("B", 0, 2 * H, -100)]
        self.assertFalse(decision(t("C", 30 * H, 31 * H, 15), accepted)[0])

    def test_never_leaks_future_truth_in_same_bar(self):
        a = t("A", 0, 2 * H, -100)
        b = t("B", 0, 2 * H, -100)
        self.assertFalse(decision(t("C", 2 * H, 3 * H, 100), [a, b])[0])


if __name__ == "__main__":
    unittest.main()
