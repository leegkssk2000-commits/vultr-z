"""Synthetic source-journal durability checks; no market economics run."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from backend.research.rebuild import q0_prospective_archive_v1 as archive


I, D = archive.INTERVAL, archive.DAY


def seed():
    return archive.initial_state(["BTC", "ETH"], 0, D, 3 * D,
                                 {"steps": 0, "open_positions": ["preserved"]})


def record(symbol="BTC", stamp=0, price=100, observed=None, **extra):
    bar = {"bar_open_ts": stamp, "bar_close_ts": stamp + I,
           "open": price, "high": price + 1, "low": price - 1,
           "close": price, "volume": 10}
    return {"symbol": symbol, "bar": bar, "raw": {"original": price},
            "observed_at_ms": stamp + I if observed is None else observed,
            "source_owner": archive.SOURCE_OWNER, "run_id": "synthetic-run",
            "source_commit": "f" * 40, **extra}


def basket(stamp=0):
    return [record(symbol, stamp) for symbol in ("BTC", "ETH")]


def update(engine, baskets, state):
    engine["steps"] += len(baskets)
    engine["last_cursor"] = state["cursor_ms"]
    return engine


class SourceIngestTest(unittest.TestCase):
    def test_same_value_recollection_is_noop(self):
        first, baskets, _ = archive.ingest(seed(), basket())
        duplicate = basket()
        for row in duplicate:
            row.update(run_id="other-run", observed_at_ms=2 * I)
        second, fresh, summary = archive.ingest(first, duplicate)
        self.assertEqual(first, second)
        self.assertEqual(fresh, [])
        self.assertEqual(summary["duplicates"], 2)
        self.assertEqual(len(baskets), 1)

    def test_conflict_preserves_both_and_holds_all_baskets(self):
        first, _, _ = archive.ingest(seed(), basket())
        conflict = record(price=101)
        second, baskets2, summary = archive.ingest(first, [conflict] + basket(I))
        self.assertEqual(second["records"]["BTC:0"]["bar"]["close"], 100)
        self.assertEqual(len(second["quarantine"]), 1)
        self.assertEqual(second["cursor_ms"], I)
        self.assertEqual(baskets2, [])
        self.assertEqual(summary["status"], "CONFLICT_HOLD")
        third, _, _ = archive.ingest(second, [conflict])
        self.assertEqual(second, third)

    def test_out_of_order_source_waits_then_releases_contiguous_baskets(self):
        first, baskets1, summary = archive.ingest(seed(), basket(I))
        self.assertEqual(baskets1, [])
        self.assertEqual(summary["status"], "GAP_HOLD")
        self.assertEqual(first["cursor_ms"], 0)
        second, baskets2, _ = archive.ingest(first, basket())
        self.assertEqual([row["bar_close_ts"] for row in baskets2], [I, 2 * I])
        self.assertTrue(baskets2[0]["quality"]["backfill"])
        self.assertFalse(baskets2[0]["quality"]["evidence_admissible"])
        self.assertTrue(baskets2[0]["quality"]["out_of_order"])
        self.assertFalse(baskets2[1]["quality"]["backfill"])
        self.assertTrue(baskets2[1]["quality"]["delayed"])
        self.assertFalse(baskets2[1]["quality"]["evidence_admissible"])
        self.assertEqual(second["unresolved_gaps"], [])
        self.assertEqual(len(second["gap_history"]), 2)

    def test_unordered_complete_single_batch_not_false_backfill(self):
        _, rows, summary = archive.ingest(seed(), basket(I) + basket())
        self.assertEqual(summary["status"], "CONTIGUOUS")
        self.assertFalse(any(row["quality"]["backfill"] for row in rows))

    def test_partial_symbol_gap_does_not_advance_or_drop_open_state(self):
        first, rows, summary = archive.ingest(seed(), [record()] + basket(I))
        self.assertEqual(rows, [])
        self.assertEqual(summary["gap_keys"], 1)
        self.assertEqual(first["engine_state"]["open_positions"], ["preserved"])

    def test_lag_is_preserved_without_labeling_regular_poll_backfill(self):
        source = basket()
        for row in source:
            row["observed_at_ms"] += 3_600_000
        state, rows, _ = archive.ingest(seed(), source)
        self.assertEqual(state["records"]["BTC:0"]["recorded_lag_ms"], 3_600_000)
        self.assertFalse(rows[0]["quality"]["backfill"])
        self.assertEqual(rows[0]["observed_at_ms"], I + 3_600_000)

    def test_invalid_row_rejects_whole_transaction_purely(self):
        original = seed()
        bad = record("ETH", observed=I - 1)
        with self.assertRaisesRegex(RuntimeError, "UNCLOSED"):
            archive.ingest(original, [record(), bad])
        self.assertEqual(original, seed())

    def test_bad_time_ohlcv_owner_and_provenance_rejected(self):
        malformed = []
        item = record(); item["bar"]["volume"] = -1; malformed.append(item)
        item = record(); item["bar"]["high"] = 99; malformed.append(item)
        item = record(); item["bar"]["close"] = float("nan"); malformed.append(item)
        item = record(); item["source_owner"] = "other"; malformed.append(item)
        item = record(); item["raw"] = {}; malformed.append(item)
        item = record(); item["source_commit"] = None; malformed.append(item)
        item = record(); item["bar"]["bar_open_ts"] = 1; malformed.append(item)
        for item in malformed:
            with self.subTest(item=item), self.assertRaises(RuntimeError):
                archive.ingest(seed(), [item])

    def test_future_and_warmup_namespaces_and_frozen_end(self):
        initial = archive.initial_state(["BTC", "ETH"], 0, D, 2 * D)
        rows = [row for stamp in range(0, 2 * D + I, I) for row in basket(stamp)]
        state, emitted, _ = archive.ingest(initial, rows)
        self.assertEqual(state["records"]["BTC:0"]["namespace"], "WARMUP_CAPTURE")
        self.assertEqual(state["records"][f"BTC:{D}"]["namespace"], "FUTURE_OBSERVATION")
        self.assertEqual(state["records"][f"BTC:{2 * D}"]["namespace"], "AFTER_FROZEN_WINDOW")
        self.assertEqual(state["cursor_ms"], 2 * D)
        self.assertEqual(len(emitted), 12)


class DurableTransactionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, generation, rows, **kw):
        return archive.transact(self.root, generation, rows, update,
                                initial=seed(), **kw)

    def test_restart_rebuilds_source_and_engine_from_committed_deltas(self):
        first, _ = self.write(0, basket())
        second, receipt = self.write(1, basket(I))
        self.assertEqual(archive.load(self.root), second)
        self.assertEqual(second["engine_state"]["steps"], 2)
        self.assertEqual(len(list((self.root / "transactions").glob("*.json"))), 2)
        payload = json.loads((self.root / "transactions" /
                              (receipt["transaction_sha256"] + ".json")).read_text())
        self.assertNotIn("initial", payload)
        self.assertNotIn("records", payload["checkpoint"])
        self.assertEqual(len(payload["source_delta"]["accepted"]), 2)
        self.assertEqual(payload["previous_sha256"], first["head"])

    def test_duplicate_does_not_create_generation_or_model_step(self):
        before, _ = self.write(0, basket())
        after, receipt = self.write(1, basket())
        self.assertEqual(before, after)
        self.assertFalse(receipt["committed"])
        self.assertEqual(len(list((self.root / "transactions").glob("*.json"))), 1)

    def test_crash_before_pointer_unpublished_orphan_retried_exactly_once(self):
        before, _ = self.write(0, basket())
        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_CRASH_AFTER_BATCH"):
            self.write(1, basket(I), crash_at="after_batch")
        self.assertEqual(archive.load(self.root), before)
        after, _ = self.write(1, basket(I))
        self.assertEqual(after["engine_state"]["steps"], 2)
        self.assertEqual(after["generation"], 2)
        self.assertEqual(len(list((self.root / "transactions").glob("*.json"))), 2)

    def test_crash_after_pointer_retry_cannot_duplicate_model_trade(self):
        self.write(0, basket())
        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_CRASH_AFTER_POINTER"):
            self.write(1, basket(I), crash_at="after_pointer")
        committed = archive.load(self.root)
        after, receipt = self.write(2, basket(I))
        self.assertEqual(committed, after)
        self.assertEqual(after["engine_state"]["steps"], 2)
        self.assertFalse(receipt["committed"])

    def test_stale_concurrent_writer_cannot_overwrite_new_cursor(self):
        first, _ = self.write(0, basket())
        with self.assertRaisesRegex(RuntimeError, "STALE_WRITER"):
            self.write(0, basket(I))
        self.assertEqual(archive.load(self.root), first)

    def test_model_failure_publishes_no_source_or_cursor(self):
        before, _ = self.write(0, basket())
        def broken(engine, rows, state):
            raise RuntimeError("synthetic model failure")
        with self.assertRaisesRegex(RuntimeError, "synthetic model failure"):
            archive.transact(self.root, 1, basket(I), broken)
        self.assertEqual(archive.load(self.root), before)

    def test_hash_tampering_fails_closed(self):
        _, receipt = self.write(0, basket())
        path = self.root / "transactions" / (receipt["transaction_sha256"] + ".json")
        path.write_text(path.read_text().replace('"steps":1', '"steps":9'))
        with self.assertRaisesRegex(RuntimeError, "HASH_MISMATCH"):
            archive.load(self.root)

    def test_conflict_and_gap_history_survive_restart(self):
        self.write(0, basket(I))
        recovered, _ = self.write(1, basket())
        conflict, _ = self.write(2, [record(price=105)])
        loaded = archive.load(self.root)
        self.assertEqual(loaded, conflict)
        self.assertEqual(len(loaded["quarantine"]), 1)
        self.assertEqual(loaded["gap_history"], recovered["gap_history"])
        self.assertEqual(loaded["engine_state"]["open_positions"], ["preserved"])


if __name__ == "__main__":
    unittest.main()
