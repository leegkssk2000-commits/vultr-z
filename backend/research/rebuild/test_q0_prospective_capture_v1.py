from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import g5_clean_runner_v1 as base
from . import q0_prospective_capture_v1 as capture


ENV = {
    "G5_CLEAN_RUNNER_OWNER_ID": capture.SOURCE_OWNER,
    "GITHUB_RUN_ID": "synthetic-run", "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_SHA": "a" * 40,
}
END = capture.CANONICAL_SEED_END_MS
STEP = base.INTERVAL_MS
FIRE = END + 2 * STEP


def raw(open_ts: int, **changes: object) -> dict:
    row = {"time": open_ts, "open": "100", "high": "110", "low": "90",
           "close": "105", "volume": "7.25"}
    row.update(changes)
    return row


def response(rows: list) -> dict:
    return {"code": 0, "data": rows}


def source(rows: list) -> dict:
    normalized = base.BingxSourceAdapter._decode(response(rows))
    return {"symbol": "BTC-USDT", "rows": normalized,
            "closed_rows": [r for r in normalized if r["bar_close_ts"] <= FIRE],
            "source_id": "BINGX", "stream_id": "same-operational-stream",
            "source_received_ts": FIRE + 10}


class SourceCaptureTests(unittest.TestCase):
    def test_real_adapter_same_request_count_order_params_and_result(self) -> None:
        contract = {"source": {"max_pages": 2, "page_limit": 3,
                    "minimum_warmup_bars": 2, "source_id": "BINGX", "stream_id": "fixed"}}
        pages = [(response([raw(END + 2 * STEP), raw(END + STEP), raw(END)]), FIRE + 10),
                 (response([raw(END - STEP), raw(END - 2 * STEP)]), FIRE + 11)]
        with patch.object(base.BingxSourceAdapter, "_request", side_effect=copy.deepcopy(pages)) as plain:
            expected = base.BingxSourceAdapter(contract).fetch("BTC-USDT", FIRE)
            expected_calls = plain.call_args_list
        recorder = capture.Capture(ENV)
        cls = capture.recording_adapter(base.BingxSourceAdapter, recorder)
        with patch.object(base.BingxSourceAdapter, "_request", side_effect=copy.deepcopy(pages)) as copied:
            actual = cls(contract).fetch("BTC-USDT", FIRE)
            self.assertEqual(copied.call_args_list, expected_calls)
            self.assertEqual(copied.call_count, 2)
        self.assertEqual(actual, expected)
        self.assertEqual(recorder.errors, [])
        self.assertEqual([r["bar_open_ts"] for r in recorder.records], [END, END + STEP])
        for record in recorder.records:
            self.assertEqual(record["source_bar_sha256"], base.sha_json(record["bar"]))
            self.assertEqual(record["raw_row_sha256"], base.sha_json(record["raw"]))
            self.assertEqual(record["observed_at_ms"], FIRE + 10)
            self.assertEqual(record["source_request_params"]["endTime"], FIRE)
            self.assertEqual(record["run_id"], "synthetic-run")
            self.assertEqual(record["source_commit"], "a" * 40)

    def test_closed_suffix_only_no_forming_or_seed_overwrite(self) -> None:
        rows = [raw(END - STEP), raw(END), raw(END + STEP), raw(END + 2 * STEP)]
        recorder = capture.Capture(ENV)
        recorder.fetched(source(rows), FIRE, [{"value": response(rows), "params": {},
                         "received_ms": FIRE + 1}], base.BingxSourceAdapter._decode)
        self.assertEqual([r["bar_open_ts"] for r in recorder.records], [END, END + STEP])
        self.assertTrue(all(r["bar_close_ts"] <= FIRE for r in recorder.records))

    def test_original_fetch_and_request_return_object_identity(self) -> None:
        expected_source = source([raw(END)])
        expected_request = (response([raw(END)]), FIRE + 1)

        class Original:
            _decode = staticmethod(base.BingxSourceAdapter._decode)

            def _request(self, params):
                return expected_request

            def fetch(self, symbol, scheduler_fire_ts):
                self.saved_request = self._request({"symbol": symbol})
                return expected_source

        recorder = capture.Capture(ENV)
        instance = capture.recording_adapter(Original, recorder)()
        actual = instance.fetch("BTC-USDT", FIRE)
        self.assertIs(actual, expected_source)
        self.assertIs(instance.saved_request, expected_request)

    def test_raw_decoder_omission_is_explicit_research_error(self) -> None:
        rows = [raw(END), raw(END + STEP, close="bad")]
        recorder = capture.Capture(ENV)
        recorder.fetched(source(rows), FIRE, [{"value": response(rows), "params": {},
                         "received_ms": FIRE + 1}], base.BingxSourceAdapter._decode)
        self.assertIn("SOURCE_RAW_ROW_DECODE_SKIPPED", {r["code"] for r in recorder.errors})
        self.assertEqual(len(recorder.records), 1)

    def test_missing_volume_cannot_be_fabricated_from_decoder_default(self) -> None:
        row = raw(END)
        del row["volume"]
        recorder = capture.Capture(ENV)
        recorder.fetched(source([row]), FIRE, [{"value": response([row]), "params": {},
                         "received_ms": FIRE + 1}], base.BingxSourceAdapter._decode)
        self.assertIn("SOURCE_RAW_VOLUME_MISSING", {r["code"] for r in recorder.errors})
        self.assertEqual(recorder.records, [])

    def test_raw_normalized_mismatch_not_claimed_as_parity(self) -> None:
        recorder = capture.Capture(ENV)
        recorder.fetched(source([raw(END)]), FIRE,
                         [{"value": response([raw(END, close="104")]), "params": {},
                           "received_ms": FIRE + 1}], base.BingxSourceAdapter._decode)
        self.assertEqual(recorder.records, [])
        self.assertEqual(recorder.errors[0]["code"], "SOURCE_RAW_NORMALIZED_PARITY_MISSING")

    def test_same_page_duplicate_uses_actual_earliest_received(self) -> None:
        rows = [raw(END)]
        recorder = capture.Capture(ENV)
        pages = [{"value": response(rows), "params": {}, "received_ms": FIRE + delay}
                 for delay in (20, 10)]
        recorder.fetched(source(rows), FIRE, pages, base.BingxSourceAdapter._decode)
        self.assertEqual(len(recorder.records), 1)
        self.assertEqual(recorder.records[0]["observed_at_ms"], FIRE + 10)

    def test_received_before_close_rejected_without_rewriting_clock(self) -> None:
        rows = [raw(END + STEP)]
        recorder = capture.Capture(ENV)
        recorder.fetched(source(rows), FIRE, [{"value": response(rows), "params": {},
                         "received_ms": FIRE - 1}], base.BingxSourceAdapter._decode)
        self.assertEqual(recorder.records, [])
        self.assertIn("SOURCE_RECEIVED_BEFORE_CLOSE", {r["code"] for r in recorder.errors})

    def test_first_contiguous_catchup_marks_older_bars_without_prior_gap_state(self) -> None:
        rows = [raw(END), raw(END + STEP)]
        fire = FIRE + STEP // 2
        recorder = capture.Capture(ENV)
        recorder.fetched(source(rows), fire, [{"value": response(rows), "params": {},
                         "received_ms": fire + 11}], base.BingxSourceAdapter._decode)
        self.assertEqual(recorder.errors, [])
        self.assertEqual([(r['bar_close_ts'], r['backfill']) for r in recorder.records],
                         [(END + STEP, True), (FIRE, False)])
        self.assertTrue(all(r['observed_at_ms'] == fire + 11 for r in recorder.records))
        self.assertEqual(recorder.packet(0)['backfill_rule'],
                         'BAR_CLOSE_BEFORE_FLOOR_SCHEDULER_FIRE_4H')

    def test_later_recapture_has_same_raw_and_source_hash_for_archive_noop(self) -> None:
        rows = [raw(END)]
        packets = []
        for fire in (END + STEP, END + 2 * STEP):
            recorder = capture.Capture(ENV)
            recorder.fetched(source(rows), fire, [{"value": response(rows), "params": {},
                             "received_ms": fire + 1}], base.BingxSourceAdapter._decode)
            packets.append(recorder.records[0])
        self.assertFalse(packets[0]['backfill'])
        self.assertTrue(packets[1]['backfill'])
        self.assertEqual(packets[0]['source_bar_sha256'], packets[1]['source_bar_sha256'])
        self.assertEqual(packets[0]['raw_row_sha256'], packets[1]['raw_row_sha256'])
        self.assertLess(packets[0]['observed_at_ms'], packets[1]['observed_at_ms'])

    def test_owner_and_run_must_be_bound(self) -> None:
        recorder = capture.Capture({})
        self.assertEqual({r["code"] for r in recorder.errors},
                         {"SOURCE_OWNER_UNBOUND", "SOURCE_RUN_UNBOUND"})

    def test_wrapper_once_restores_class_and_atomic_packet(self) -> None:
        original = base.BingxSourceAdapter
        with tempfile.TemporaryDirectory() as temp:
            args = ["capture", "--shadow", "--artifact-dir", temp]

            def shadow():
                self.assertIsNot(base.BingxSourceAdapter, original)
                return 0

            with patch.object(capture.sys, "argv", args), patch.dict(capture.os.environ, ENV, clear=True), \
                    patch.object(capture.binding, "main", side_effect=shadow) as run:
                self.assertEqual(capture.main(), 0)
            run.assert_called_once_with()
            self.assertIs(base.BingxSourceAdapter, original)
            value = json.loads((Path(temp) / capture.BATCH_NAME).read_text())
            seal = value.pop("receipt_sha256")
            self.assertEqual(seal, base.sha_json(value))
            self.assertEqual(value["original_shadow_exit_code"], 0)
            self.assertEqual(value["additional_source_requests"], 0)
            self.assertEqual(value["paid_ai_calls"], 0)
            self.assertEqual(value["execution"], "NONE")
            self.assertEqual(len(list(Path(temp).iterdir())), 1)

    def test_wrapper_preserves_failure_and_restores_class(self) -> None:
        original = base.BingxSourceAdapter
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(capture.sys, "argv", ["capture", "--shadow", "--artifact-dir", temp]), \
                    patch.object(capture.binding, "main", side_effect=RuntimeError("source failure")):
                with self.assertRaisesRegex(RuntimeError, "source failure"):
                    capture.main()
            self.assertIs(base.BingxSourceAdapter, original)
            self.assertFalse((Path(temp) / capture.BATCH_NAME).exists())

    def test_nonzero_base_code_is_preserved_without_success_packet(self) -> None:
        with patch.object(capture.sys, "argv", ["capture", "--shadow"]), \
                patch.object(capture.binding, "main", return_value=17), \
                patch.object(capture, "write_packet") as writer:
            self.assertEqual(capture.main(), 17)
        writer.assert_not_called()

    def test_research_capture_failure_does_not_drop_operating_success(self) -> None:
        with patch.object(capture.sys, "argv", ["capture", "--shadow"]), \
                patch.object(capture.binding, "main", return_value=0), \
                patch.object(capture, "write_packet", side_effect=OSError("synthetic disk error")), \
                patch.object(capture.sys, "stderr"):
            self.assertEqual(capture.main(), 0)

    def test_non_shadow_flags_delegate_without_installing_capture(self) -> None:
        original = base.BingxSourceAdapter
        with patch.object(capture.sys, "argv", ["capture", "--self-test", "--preflight"]), \
                patch.object(capture.binding, "main", return_value=0) as run, \
                patch.object(capture, "recording_adapter") as adapter:
            self.assertEqual(capture.main(), 0)
        run.assert_called_once_with()
        adapter.assert_not_called()
        self.assertIs(base.BingxSourceAdapter, original)


if __name__ == "__main__":
    unittest.main()
