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

    def _risk_decision(self, *, approved=True, execution_eligible=True):
        return {
            "authority": "z_os_risk_gate",
            "approved": approved,
            "execution_eligible": execution_eligible,
            "checks": {"source": "test_contract_only"},
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

    def test_team_approval_alone_cannot_reach_executor_without_zos_risk(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        decision = self._decision(team="Alpha", side="buy")
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(
                ["breakout"],
                "BTCUSDT",
                df=[None] * 120,
                team_decision=decision,
            )

        self.assertEqual(recorder.orders, [])
        self.assertEqual(result["breakout"]["team_signal"]["execution_authority"], "team_bot_consensus")
        self.assertEqual(result["breakout"]["execution"]["reason"], "z_os_risk_gate_required")

    def test_only_team_plus_zos_risk_signal_reaches_executor(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        decision = self._decision(team="Alpha", side="buy")
        risk = self._risk_decision()
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(
                ["breakout"],
                "BTCUSDT",
                qty=0.01,
                df=[None] * 120,
                team_decision=decision,
                risk_decision=risk,
            )

        self.assertEqual(len(recorder.orders), 1)
        order = recorder.orders[0]
        self.assertEqual(order["signal"]["execution_authority"], "z_os_risk_gate")
        self.assertEqual(order["signal"]["team_signal"]["execution_authority"], "team_bot_consensus")
        self.assertEqual(order["signal"]["team_signal"]["strategy_signal"], raw)
        self.assertEqual(order["signal"]["team"], "Alpha")
        self.assertEqual(result["breakout"]["signal"]["next_layer"], "executor")

    def test_invalid_zos_risk_authority_is_blocked(self):
        from engine.risk_unit import authorize_execution
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        team_signal = authorize_team_signal(raw, self._decision())
        risk = self._risk_decision()
        risk["authority"] = "strategy"
        result = authorize_execution(team_signal, risk)

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "invalid_z_os_risk_authority")

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
