import unittest
from unittest.mock import patch


class _RecorderExec:
    def __init__(self):
        self.orders = []

    def place(self, order):
        self.orders.append(order)
        return {
            "ok": True,
            "status": "accepted_test",
            "execution_allowed": False,
            "order": order,
        }


class TeamBotHierarchyTest(unittest.TestCase):
    def _roles(self, *, sbot_veto=False):
        return {
            "LBot": {"state": "lead_or_support"},
            "MBot": {"state": "method_confirm"},
            "OBot": {"state": "observer"},
            "SBot": {"state": "safety_guard", "veto": sbot_veto},
        }

    def _decision(self, *, team="Alpha", side="buy", approved=True, sbot_veto=False):
        return {
            "team": team,
            "side": side,
            "approved": approved,
            "roles": self._roles(sbot_veto=sbot_veto),
        }

    def test_exact_team_layout_is_restored(self):
        from engine.team_layer import TEAM_LAYOUT

        self.assertEqual(
            TEAM_LAYOUT,
            {
                "Alpha": {"lead": "LBot", "support": "MBot", "watcher": "OBot", "guard": "SBot"},
                "Beta": {"lead": "MBot", "support": "LBot", "watcher": "OBot", "guard": "SBot"},
                "Gamma": {"lead": "OBot", "support": "MBot", "watcher": "LBot", "guard": "SBot"},
                "Delta": {"lead": "SBot", "support": "OBot", "watcher": "MBot", "reserve": "LBot"},
            },
        )

    def test_raw_strategy_signal_cannot_reach_executor_without_team_decision(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(["breakout"], "BTCUSDT", df=[None] * 120)

        self.assertEqual(recorder.orders, [])
        self.assertFalse(result["breakout"]["signal"]["execution_eligible"])
        self.assertEqual(result["breakout"]["execution"]["reason"], "team_bot_hierarchy_required")

    def test_all_four_team_bot_roles_are_required(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision()
        decision["roles"].pop("OBot")
        result = authorize_team_signal(raw, decision)

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "missing_team_bot_roles")
        self.assertEqual(result["missing_roles"], ["OBot"])

    def test_sbot_veto_is_fail_closed(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        result = authorize_team_signal(raw, self._decision(sbot_veto=True))

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "sbot_veto")

    def test_zbot_cannot_replace_missing_team_bot(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision()
        decision["roles"].pop("LBot")
        decision["ZBot"] = {"approved": True, "role": "advisor"}
        result = authorize_team_signal(raw, decision)

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["missing_roles"], ["LBot"])
        self.assertEqual(result["zbot_authority"], "advisor_only")

    def test_team_approved_signal_is_only_executor_input(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        decision = self._decision(team="Alpha", side="buy")
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(
                ["breakout"],
                "BTCUSDT",
                qty=0.01,
                df=[None] * 120,
                team_decision=decision,
            )

        self.assertEqual(len(recorder.orders), 1)
        order = recorder.orders[0]
        self.assertEqual(order["signal"]["execution_authority"], "team_bot_consensus")
        self.assertEqual(order["signal"]["team"], "Alpha")
        self.assertEqual(order["signal"]["strategy_signal"], raw)
        self.assertNotEqual(order["signal"], raw)
        self.assertEqual(result["breakout"]["signal"]["next_layer"], "z_os_risk_execution")

    def test_run_once_is_raw_candidate_only(self):
        from engine.runner import run_once

        raw = {"side": "sell", "confidence": 0.7, "source": "breakout"}
        with patch("engine.router.route", return_value=raw):
            result = run_once(["breakout"])

        self.assertEqual(result["breakout"]["raw_signal"], raw)
        self.assertFalse(result["breakout"]["execution_eligible"])
        self.assertEqual(result["breakout"]["execution_authority"], "none")
        self.assertEqual(result["breakout"]["next_layer"], "team_bot")


if __name__ == "__main__":
    unittest.main()
