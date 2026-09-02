from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as legacy
from backend.research.rebuild import g5_clean_runner_v1 as clean


class CleanRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = clean.read_json(clean.CONTRACT_PATH)
        cls.freeze = clean.read_json(clean.FREEZE_PATH)
        cls.adapter = clean.FrozenStrategyAdapter(cls.contract, cls.freeze)
        cls.rows = clean.synthetic_bars(330)

    def test_frozen_strategy_semantic_parity_with_legacy_dsl(self) -> None:
        legacy_contract = json.loads(
            (clean.ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json").read_text()
        )
        specs = {row["parent_strategy_id"]: row["executable_spec"] for row in legacy_contract["children"]}
        old_rows = [
            {
                "ts": row["bar_open_ts"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for row in self.rows
        ]
        legacy_engines = {}
        for strategy_id, spec in specs.items():
            _, engine = legacy._features(old_rows, spec)
            engine.validate(spec["entry_rule"])
            legacy_engines[strategy_id] = (engine, spec["entry_rule"])

        for i in range(239, len(self.rows)):
            sliced = self.rows[: i + 1]
            for strategy_id in ("supertrend_pullback", "break_and_continue"):
                engine, rule = legacy_engines[strategy_id]
                old_signal = bool(engine.eval(rule, i))
                new_signal = bool(self.adapter.evaluate(strategy_id, sliced)["signal"])
                self.assertEqual(old_signal, new_signal, (strategy_id, i))

            engine, rule = legacy_engines["keltner_trend"]
            old_parent = bool(engine.eval(rule, i))
            closes = [float(row["close"]) for row in sliced]
            old_classifier = (
                abs(clean.full_history_ema(closes, 20, i) - clean.full_history_ema(closes, 50, i))
                / max(clean.atr14(sliced, i), 1e-12)
                < 0.5
            )
            new_signal = bool(self.adapter.evaluate("keltner_trend", sliced)["signal"])
            self.assertEqual(old_parent and old_classifier, new_signal, ("keltner_trend", i))

    def test_latest_closed_bar_exactly_once_and_no_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = clean.StateStore(Path(raw) / "state.jsonl")
            close_ts = int(self.rows[-1]["bar_close_ts"])
            source = {
                "symbol": "BTC-USDT",
                "rows": self.rows,
                "closed_rows": self.rows,
                "source_received_ts": close_ts + 1,
                "source_id": self.contract["source"]["source_id"],
                "stream_id": self.contract["source"]["stream_id"],
            }
            first = clean.evaluate_latest_bar(
                contract=self.contract,
                adapter=self.adapter,
                store=store,
                source=source,
                scheduler_fire_ts=close_ts + 1,
            )
            first_count = len(store.records())
            second = clean.evaluate_latest_bar(
                contract=self.contract,
                adapter=self.adapter,
                store=store,
                source=source,
                scheduler_fire_ts=close_ts + 1,
            )
            self.assertEqual(first["new"], 3)
            self.assertEqual(second["noop"], 3)
            self.assertEqual(len(store.records()), first_count)
            evaluated = [row for row in store.records() if row["status"] == "EVALUATED"]
            self.assertEqual(len(evaluated), 3)
            self.assertTrue(all(row["payload"]["symbol"] == "BTC-USDT" for row in evaluated))
            self.assertTrue(all(row["payload"]["formal_credit"] == 0 for row in evaluated))

    def test_canary_and_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            exactly, canary = clean.run_canary(Path(raw))
            self.assertEqual(exactly["state"], "CLEAN_RUNNER_EXACTLY_ONCE_PASS")
            self.assertEqual(canary["state"], "CLEAN_RUNNER_CANARY_PASS")
            self.assertEqual(canary["formal_credit"], 0)

    def test_forming_bar_and_gap_fail_closed(self) -> None:
        with self.assertRaises(clean.IntegrityError):
            clean.verify_recent_continuity("BTC-USDT", [self.rows[0], self.rows[2]])
        with tempfile.TemporaryDirectory() as raw:
            store = clean.StateStore(Path(raw) / "state.jsonl")
            close_ts = int(self.rows[-1]["bar_close_ts"])
            source = {
                "symbol": "BTC-USDT",
                "rows": self.rows,
                "closed_rows": self.rows,
                "source_received_ts": close_ts,
                "source_id": self.contract["source"]["source_id"],
                "stream_id": self.contract["source"]["stream_id"],
            }
            with self.assertRaises(clean.IntegrityError):
                clean.evaluate_latest_bar(
                    contract=self.contract,
                    adapter=self.adapter,
                    store=store,
                    source=source,
                    scheduler_fire_ts=close_ts - 1,
                )

    def test_hash_chain_tamper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "state.jsonl"
            store = clean.StateStore(path)
            store.transition("a|b|c|1", "NEW", {"value": 1})
            text = path.read_text().replace('"value":1', '"value":2')
            path.write_text(text)
            with self.assertRaises(clean.IntegrityError):
                store.records()

    def test_restart_between_close_and_ledger_recovers_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = clean.StateStore(root / "state.jsonl")
            ledger = clean.EconomicLedger(root / "ledger.jsonl")
            strategy = next(row for row in self.contract["active_strategies"] if row["strategy_id"] == "keltner_trend")
            key = clean.state_key(strategy, "BTC-USDT", 15_400_000)
            economic = clean._canary_economic_row()
            economic.update({
                "trade_id": "RECOVERY_TRADE",
                "strategy_id": strategy["strategy_id"],
                "child_id": strategy["child_id"],
                "strategy_sha": strategy["strategy_sha"],
                "entry_sha": strategy["entry_sha"],
                "exit_sha": strategy["exit_sha"],
                "config_sha": strategy["config_sha"],
                "source_id": self.contract["source"]["source_id"],
            })
            store.transition(key, "NEW", {"bar_key": economic["bar_key"], "closed_confirmed": True})
            store.transition(key, "EVALUATED", {
                "strategy_id": strategy["strategy_id"],
                "child_id": strategy["child_id"],
                "symbol": "BTC-USDT",
                "signal": True,
                "side": "long",
                "signal_bar_open_ts": economic["signal_bar_open_ts"],
                "signal_bar_close_ts": economic["signal_bar_close_ts"],
                "bar_key": economic["bar_key"],
                "source_bar_sha256": "CANARY",
            })
            store.transition(key, "TRADE_OPENED", {
                "trade_id": economic["trade_id"],
                "entry_ts": economic["entry_ts"],
                "entry_price": economic["entry_price"],
                "exit_due_ts": economic["exit_ts"],
            })
            store.transition(key, "TRADE_CLOSED", {
                "trade_id": economic["trade_id"],
                "exit_ts": economic["exit_ts"],
                "exit_price": economic["exit_price"],
                "economic_row": economic,
                "economic_payload_sha256": clean.sha_json(economic),
                "formal_credit": 0,
            })
            source = {
                "BTC-USDT": {
                    "rows": self.rows,
                    "closed_rows": self.rows,
                    "source_id": self.contract["source"]["source_id"],
                }
            }
            counts = clean.process_trade_lifecycle(
                contract=self.contract,
                store=clean.StateStore(root / "state.jsonl"),
                ledger=clean.EconomicLedger(root / "ledger.jsonl"),
                source_by_symbol=source,
                acceptor=clean.FreshAcceptor(self.contract),
            )
            self.assertEqual(counts["ledger_written"], 1)
            self.assertEqual(len(ledger.records()), 1)
            self.assertEqual(clean.latest_status(store.state_rows()[key]), "LEDGER_WRITTEN")


if __name__ == "__main__":
    unittest.main()
