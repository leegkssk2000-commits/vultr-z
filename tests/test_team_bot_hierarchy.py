import unittest
from unittest.mock import patch


class _RecorderExec:
    def __init__(self):
        self.orders = []

    def place(self, order=None, **kwargs):
        payload = dict(order or {})
        payload.update(kwargs)
        self.orders.append(payload)
        return {
            "ok": True,
            "status": "accepted_test",
            "execution_allowed": False,
            "order": payload,
        }


class TeamBotHierarchyTest(unittest.TestCase):
    def _team_bots(self):
        return {
            "support": {"bot": "support-1", "participated": True},
            "watchers": [
                {"bot": "watcher-1", "participated": True},
                {"bot": "watcher-2", "participated": True},
                {"bot": "watcher-3", "participated": True},
            ],
            "helper": {"bot": "helper-1", "participated": True},
        }

    def _decision(self, raw, *, strategy="breakout", team="Alpha", side=None, approved=True):
        from engine.team_layer import build_candidate_id

        return {
            "team": team,
            "strategy": strategy,
            "candidate_id": build_candidate_id(strategy, raw),
            "side": side or raw["side"],
            "approved": approved,
            "team_bots": self._team_bots(),
        }

    def _risk_decision(self, raw, *, strategy="breakout", approved=True, execution_eligible=True):
        from engine.team_layer import build_candidate_id

        return {
            "authority": "z_os_risk_gate",
            "strategy": strategy,
            "candidate_id": build_candidate_id(strategy, raw),
            "approved": approved,
            "execution_eligible": execution_eligible,
            "checks": {"source": "test_contract_only"},
        }

    def _execution_signal(self, raw, *, strategy="breakout"):
        from engine.risk_unit import authorize_execution
        from engine.team_layer import authorize_team_signal

        team_signal = authorize_team_signal(
            raw,
            self._decision(raw, strategy=strategy),
            strategy_name=strategy,
        )
        return authorize_execution(team_signal, self._risk_decision(raw, strategy=strategy))

    def test_preserved_team_topology_is_one_support_three_watchers_one_helper(self):
        from engine.team_layer import TEAM_TOPOLOGY

        self.assertEqual(TEAM_TOPOLOGY, {"support": 1, "watchers": 3, "helper": 1})

    def test_exactly_three_watchers_are_required(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["team_bots"]["watchers"].pop()
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "watcher_count_mismatch")
        self.assertEqual(result["detail"], {"expected": 3, "actual": 2})

    def test_every_slot_requires_concrete_bot_and_participation(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["team_bots"]["support"] = {"bot": "support-1", "participated": False}
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "invalid_support_bot_evidence")

    def test_same_bot_cannot_fill_multiple_slots(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["team_bots"]["helper"]["bot"] = "watcher-1"
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "duplicate_team_bot_identity")

    def test_team_decision_must_match_exact_candidate(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["candidate_id"] = "wrong-candidate"
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "team_candidate_identity_mismatch")

    def test_raw_strategy_signal_cannot_reach_executor(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(["breakout"], "BTCUSDT", df=[None] * 120)

        self.assertEqual(recorder.orders, [])
        self.assertEqual(result["breakout"]["execution"]["reason"], "team_bot_hierarchy_required")

    def test_team_approval_alone_cannot_reach_executor_without_zos_risk(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(
                ["breakout"],
                "BTCUSDT",
                df=[None] * 120,
                team_decision=self._decision(raw),
            )

        self.assertEqual(recorder.orders, [])
        self.assertEqual(result["breakout"]["team_signal"]["execution_authority"], "team_bot_consensus")
        self.assertEqual(result["breakout"]["execution"]["reason"], "z_os_risk_gate_required")

    def test_shared_approval_is_not_reused_across_multiple_strategies(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "shared-test"}
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(
                ["breakout", "ema_cross"],
                "BTCUSDT",
                df=[None] * 120,
                team_decision=self._decision(raw, strategy="breakout"),
                risk_decision=self._risk_decision(raw, strategy="breakout"),
            )

        self.assertEqual(recorder.orders, [])
        self.assertEqual(result["breakout"]["execution"]["reason"], "team_bot_hierarchy_required")
        self.assertEqual(result["ema_cross"]["execution"]["reason"], "team_bot_hierarchy_required")

    def test_team_plus_zos_risk_signal_is_the_only_runner_executor_input(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        decision = self._decision(raw)
        risk = self._risk_decision(raw)
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
        signal = recorder.orders[0]["signal"]
        self.assertEqual(signal["execution_authority"], "z_os_risk_gate")
        self.assertEqual(signal["team_signal"]["execution_authority"], "team_bot_consensus")
        self.assertEqual(signal["candidate_id"], decision["candidate_id"])
        self.assertEqual(result["breakout"]["signal"]["next_layer"], "executor")

    def test_order_router_rejects_raw_signal_even_if_caller_bypasses_runner(self):
        from engine.order_router import handle_signal

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        with patch("engine.order_router.select_exec", return_value=recorder):
            result = handle_signal("BTCUSDT", raw, base_qty=1.0)

        self.assertEqual(recorder.orders, [])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "z_os_risk_not_execution_eligible")

    def test_order_router_accepts_only_final_zos_authorized_signal(self):
        from engine.order_router import handle_signal

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        signal = self._execution_signal(raw)
        with patch("engine.order_router.select_exec", return_value=recorder):
            result = handle_signal("BTCUSDT", signal, base_qty=2.0)

        self.assertEqual(len(recorder.orders), 1)
        self.assertEqual(recorder.orders[0]["side"], "buy")
        self.assertAlmostEqual(recorder.orders[0]["qty"], 1.8)
        self.assertEqual(recorder.orders[0]["meta"]["candidate_id"], signal["candidate_id"])
        self.assertEqual(result["status"], "accepted_test")


if __name__ == "__main__":
    unittest.main()
