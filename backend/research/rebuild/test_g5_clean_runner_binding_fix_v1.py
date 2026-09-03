from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as legacy
from backend.research.rebuild import g5_clean_runner_binding_fix_v1 as fixed
from backend.research.rebuild import g5_clean_runner_v1 as base


class G5CleanRunnerBindingFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.artifact_dir = Path(cls.tmp.name)
        cls.diagnosis = fixed.install(cls.artifact_dir)
        cls.contract = base.read_json(base.CONTRACT_PATH)
        cls.freeze = base.read_json(base.FREEZE_PATH)
        cls.adapter = base.FrozenStrategyAdapter(cls.contract, cls.freeze)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_root_cause_and_canonical_owner_are_locked(self) -> None:
        self.assertEqual(self.diagnosis["first_zero_stage"], "RAW_SIGNAL_EMISSION")
        self.assertEqual(self.diagnosis["pre_fix_latest_signal_count"], 0)
        self.assertEqual(self.diagnosis["pre_fix_latest_opened"], 0)
        self.assertEqual(self.diagnosis["pre_fix_latest_ledger_written"], 0)
        self.assertEqual(self.diagnosis["previous_keltner_child_id"], fixed.OLD_KELTNER_CHILD)
        self.assertEqual(self.diagnosis["current_keltner_child_id"], fixed.KELTNER_CHILD)
        self.assertGreaterEqual(self.diagnosis["canonical_v2_keltner_closed_T_observed"], 5)
        self.assertFalse(self.diagnosis["historical_backfill_performed"])
        self.assertEqual(self.diagnosis["formal_credit"], 0)

    def test_keltner_matches_canonical_v2_dsl_without_extra_classifier(self) -> None:
        canonical = fixed._read(fixed.CANONICAL_V2_PATH)
        specs = {
            row["parent_strategy_id"]: row["executable_spec"]
            for row in canonical["children"]
        }
        rows = base.synthetic_bars(380)
        old_rows = [
            {
                "ts": row["bar_open_ts"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for row in rows
        ]
        engines = {}
        for strategy_id, spec in specs.items():
            _, engine = legacy._features(old_rows, spec)
            engine.validate(spec["entry_rule"])
            engines[strategy_id] = (engine, spec["entry_rule"])

        emitted = 0
        for i in range(239, len(rows)):
            sliced = rows[: i + 1]
            for strategy_id in ("keltner_trend", "supertrend_pullback", "break_and_continue"):
                engine, rule = engines[strategy_id]
                expected = bool(engine.eval(rule, i))
                actual = bool(self.adapter.evaluate(strategy_id, sliced)["signal"])
                self.assertEqual(expected, actual, (strategy_id, i))
                if strategy_id == "keltner_trend" and actual:
                    emitted += 1
        self.assertGreater(emitted, 0)

        keltner = next(
            row for row in self.contract["active_strategies"]
            if row["strategy_id"] == "keltner_trend"
        )
        self.assertEqual(keltner["child_id"], fixed.KELTNER_CHILD)
        self.assertEqual(keltner["entry_rule"], fixed.EXPECTED_RULE)
        self.assertIsNone(keltner["classifier_rule"])

    def test_prebinding_child_rows_cannot_satisfy_corrected_shadow_gate(self) -> None:
        close_ts = 1_800_000_000_000
        telemetry = {
            field: close_ts for field in base.TELEMETRY_FIELDS
        }
        with tempfile.TemporaryDirectory() as raw:
            store = base.StateStore(Path(raw) / "state.jsonl")
            strategies = {
                row["strategy_id"]: row
                for row in self.contract["active_strategies"]
            }
            missing_current_key = None
            for symbol in self.contract["source"]["symbols"]:
                for strategy_id, strategy in strategies.items():
                    child_id = strategy["child_id"]
                    if symbol == "BTC-USDT" and strategy_id == "keltner_trend":
                        child_id = fixed.OLD_KELTNER_CHILD
                        missing_current_key = base.state_key(strategy, symbol, close_ts)
                    key = "|".join((strategy_id, child_id, symbol, str(close_ts)))
                    store.transition(key, "NEW", {
                        "strategy_id": strategy_id,
                        "child_id": child_id,
                    })
                    store.transition(key, "EVALUATED", {
                        "strategy_id": strategy_id,
                        "child_id": child_id,
                        "symbol": symbol,
                        "signal_bar_close_ts": close_ts,
                        "source_seen": True,
                        "closed_bar": True,
                        "evaluated": True,
                        "correct_child": child_id == strategy["child_id"],
                        "duplicate": 0,
                        "lookahead": 0,
                        "telemetry": telemetry,
                    })

            complete, current_evaluated = fixed.current_binding_complete_closes(self.contract, store)
            self.assertEqual(complete, [])
            self.assertEqual(current_evaluated, 20)
            self.assertIsNotNone(missing_current_key)

            strategy = strategies["keltner_trend"]
            store.transition(missing_current_key, "NEW", {
                "strategy_id": "keltner_trend",
                "child_id": strategy["child_id"],
            })
            store.transition(missing_current_key, "EVALUATED", {
                "strategy_id": "keltner_trend",
                "child_id": strategy["child_id"],
                "symbol": "BTC-USDT",
                "signal_bar_close_ts": close_ts,
                "source_seen": True,
                "closed_bar": True,
                "evaluated": True,
                "correct_child": True,
                "duplicate": 0,
                "lookahead": 0,
                "telemetry": telemetry,
            })
            complete, current_evaluated = fixed.current_binding_complete_closes(self.contract, store)
            self.assertEqual(complete, [close_ts])
            self.assertEqual(current_evaluated, 21)

    def test_effective_preflight_remains_fail_closed(self) -> None:
        result = base.validate_contract_assets()
        self.assertEqual(result["state"], "CLEAN_RUNNER_PREFLIGHT_PASS")
        self.assertEqual(result["binding_epoch"], fixed.BINDING_EPOCH)
        self.assertTrue(result["canonical_keltner_v2_binding"])
        self.assertTrue(result["noncanonical_classifier_absent"])
        self.assertEqual(self.contract["mode"], "SHADOW_NO_CREDIT")
        self.assertEqual(self.contract["authority"]["formal_credit"], 0)
        self.assertFalse(self.contract["fresh_acceptor"]["fresh_credit_without_data_stale_authority"])
        self.assertTrue(self.contract["ledger"]["historical_backfill_forbidden"])


if __name__ == "__main__":
    unittest.main()
