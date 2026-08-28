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
    def _roles(self, *, sbot_veto=False):
        return {
            "LBot": {"participated": True, "state": "lead_or_support"},
            "MBot": {"participated": True, "state": "method_confirm"},
            "OBot": {"participated": True, "state": "observer"},
            "SBot": {"participated": True, "state": "safety_guard", "veto": sbot_veto},
        }

    def _decision(
        self,
        raw,
        *,
        strategy="breakout",
        team="Alpha",
        side="buy",
        approved=True,
        sbot_veto=False,
    ):
        from engine.team_layer import build_candidate_id

        return {
            "team": team,
            "strategy": strategy,
            "candidate_id": build_candidate_id(strategy, raw),
            "side": side,
            "approved": approved,
            "roles": self._roles(sbot_veto=sbot_veto),
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

    def _team_signal(self, raw, *, strategy="breakout"):
        from engine.team_layer import authorize_team_signal

        return authorize_team_signal(
            raw,
            self._decision(raw, strategy=strategy, side=raw["side"]),
            strategy_name=strategy,
        )

    def _execution_signal(self, raw, *, strategy="breakout"):
        from engine.risk_unit import authorize_execution

        team_signal = self._team_signal(raw, strategy=strategy)
        return authorize_execution(team_signal, self._risk_decision(raw, strategy=strategy))

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
        decision = self._decision(raw)
        decision["roles"].pop("OBot")
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "missing_team_bot_roles")
        self.assertEqual(result["missing_roles"], ["OBot"])

    def test_empty_role_payload_is_not_participation_evidence(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["roles"]["OBot"] = {}
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "invalid_team_bot_evidence")
        self.assertEqual(result["invalid_roles"], ["OBot"])

    def test_sbot_veto_is_fail_closed(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        result = authorize_team_signal(
            raw,
            self._decision(raw, sbot_veto=True),
            strategy_name="breakout",
        )

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "sbot_veto")

    def test_sbot_must_supply_explicit_non_veto_evidence(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["roles"]["SBot"].pop("veto")
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "sbot_non_veto_evidence_required")

    def test_zbot_cannot_replace_missing_team_bot(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["roles"].pop("LBot")
        decision["ZBot"] = {"approved": True, "role": "advisor"}
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["missing_roles"], ["LBot"])
        self.assertEqual(result["zbot_authority"], "advisor_only")

    def test_team_decision_must_match_exact_candidate_identity(self):
        from engine.team_layer import authorize_team_signal

        raw = {"side": "buy", "confidence": 0.8, "source": "breakout"}
        decision = self._decision(raw)
        decision["candidate_id"] = "wrong-candidate"
        result = authorize_team_signal(raw, decision, strategy_name="breakout")

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "team_candidate_identity_mismatch")

    def test_shared_approval_is_not_reused_across_multiple_strategies(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "shared-test"}
        decision = self._decision(raw, strategy="breakout")
        risk = self._risk_decision(raw, strategy="breakout")
        with patch("engine.router.route", return_value=raw), patch("engine.runner.select_exec", return_value=recorder):
            result = run_and_trade(
                ["breakout", "ema_cross"],
                "BTCUSDT",
                df=[None] * 120,
                team_decision=decision,
                risk_decision=risk,
            )

        self.assertEqual(recorder.orders, [])
        self.assertEqual(result["breakout"]["execution"]["reason"], "team_bot_hierarchy_required")
        self.assertEqual(result["ema_cross"]["execution"]["reason"], "team_bot_hierarchy_required")

    def test_team_approval_alone_cannot_reach_executor_without_zos_risk(self):
        from engine.runner import run_and_trade

        recorder = _RecorderExec()
        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        decision = self._decision(raw, team="Alpha", side="buy")
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
        decision = self._decision(raw, team="Alpha", side="buy")
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
        order = recorder.orders[0]
        self.assertEqual(order["signal"]["execution_authority"], "z_os_risk_gate")
        self.assertEqual(order["signal"]["team_signal"]["execution_authority"], "team_bot_consensus")
        self.assertEqual(order["signal"]["team_signal"]["strategy_signal"], raw)
        self.assertEqual(order["signal"]["team"], "Alpha")
        self.assertEqual(order["signal"]["candidate_id"], decision["candidate_id"])
        self.assertEqual(result["breakout"]["signal"]["next_layer"], "executor")

    def test_invalid_zos_risk_authority_is_blocked(self):
        from engine.risk_unit import authorize_execution

        raw = {"side": "buy", "confidence": 0.9, "source": "breakout"}
        team_signal = self._team_signal(raw)
        risk = self._risk_decision(raw)
        risk["authority"] = "strategy"
        result = authorize_execution(team_signal, risk)

        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["reason"], "invalid_z_os_risk_authority")

    def test_order_router_rejects_raw_strategy_signal(self):
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

    def test_run_once_is_raw_candidate_only_and_exposes_candidate_id(self):
        from engine.runner import run_once
        from engine.team_layer import build_candidate_id

        raw = {"side": "sell", "confidence": 0.7, "source": "breakout"}
        with patch("engine.router.route", return_value=raw):
            result = run_once(["breakout"])

        self.assertEqual(result["breakout"]["raw_signal"], raw)
        self.assertEqual(result["breakout"]["candidate_id"], build_candidate_id("breakout", raw))
        self.assertFalse(result["breakout"]["execution_eligible"])
        self.assertEqual(result["breakout"]["execution_authority"], "none")
        self.assertEqual(result["breakout"]["next_layer"], "team_bot")


if __name__ == "__main__":
    unittest.main()
