import os
import unittest


class P0P2BackendSafetyTest(unittest.TestCase):
    def test_live_executor_is_blocked(self):
        from engine.exec_live import exec_live

        result = exec_live.place(symbol="BTCUSDT", side="buy")
        self.assertFalse(result["ok"])
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["status"], "blocked")

    def test_force_live_still_selects_disabled_executor(self):
        from engine.runner import select_exec

        old = os.environ.get("FORCE_MODE")
        os.environ["FORCE_MODE"] = "live"
        try:
            result = select_exec().place(symbol="BTCUSDT", side="buy")
        finally:
            if old is None:
                os.environ.pop("FORCE_MODE", None)
            else:
                os.environ["FORCE_MODE"] = old
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["mode"], "live_disabled")

    def test_shadow_executor_is_non_live(self):
        from engine.exec_shadow import exec_shadow

        result = exec_shadow.place({"symbol": "BTCUSDT", "side": "buy"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["mode"], "paper")

    def test_p0_p2_gate_blocks_higher_features(self):
        from engine.runner import gate_status, ok_auto_promote

        gate = gate_status()
        self.assertFalse(gate["execution_allowed"])
        self.assertFalse(gate["live_execution_enabled"])
        self.assertTrue(gate["higher_roadmap_blocked"])
        self.assertFalse(ok_auto_promote({}))

    def test_live_state_update_is_rejected(self):
        from engine.utils.state import load_state, update_mode

        mode, _ = load_state()
        self.assertIn(mode, {"paper", "shadow"})
        self.assertFalse(update_mode("live"))


if __name__ == "__main__":
    unittest.main()
