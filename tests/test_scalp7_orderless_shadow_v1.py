"""Work B runtime counterexamples; artificial fixtures, no economic execution."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from backend.research.rebuild.scalp7_source_clock_v3 import await_native_time
from backend.research.rebuild import scalp7_fresh_source_v2 as source_reader
from ops import scalp7_orderless_shadow_v1 as runtime
from ops import scalp7_orderless_signals_v1 as signals

TF = runtime.TF
DAY = 86_400_000
BASE = 100 * DAY
SYMBOL = "BTC-USDT"


def settings():
    fit = dict(train_start_ms=0, train_end_ms=90 * DAY,
               last_fit_observation_ms=90 * DAY - 3_600_000,
               train_rows=2160, training_feature_sha256="a" * 64,
               disp_q67=.01, meanabs_q85=.03, vol_q25=.8, vol_q67=1.1)
    fit["sha256"] = runtime.digest(fit)
    return dict(costs={SYMBOL: 8.}, fit=fit,
        clock=dict(max_quote_request_ms=100, max_pair_skew_ms=10,
                   max_quote_gap_ms=TF * 10), sources=[],
        nav=None, capital=None, leverage=None, cost_assumption="FIXTURE_RESERVE")


def frame(*opens):
    return pd.DataFrame([dict(open_ts_ms=x, close_ts_ms=x + TF,
        available_ts_ms=x + TF, segment_id="fixture", open=100.,
        high=102., low=98., close=100., volume=1.,
        regime="PANIC_DISPERSION", regime_available_ts_ms=x + TF,
        regime_fit_end_ts_ms=settings()["fit"]["last_fit_observation_ms"],
        regime_spec_sha256=settings()["fit"]["sha256"]) for x in opens])


def quote(stamp, bid=99., ask=100.):
    walls = iter([stamp, stamp])
    monos = iter([0, 0])
    proof = await_native_time(stamp - 1, stamp,
        clock_ms=lambda: next(walls), monotonic_ns=lambda: next(monos),
        sleep=lambda _: None)
    return dict(symbol=SYMBOL, bid=bid, ask=ask, requested_at_ms=stamp - 1,
        received_at_ms=stamp, source_ts_ms=stamp - 1, usable_at_ms=stamp,
        clock_proof=proof, quote_id=str(stamp), receipt_sha256="b" * 64)


def minute_frame(start, end, received):
    return pd.DataFrame([dict(timestamp_ms=opened, open=100., high=102.,
        low=98., close=100., volume=1., received_at_ms=received)
        for opened in range(start, end, 60_000)])


def fixture_signal(state, *, version, symbol, frame, asof_ms, **_):
    """Only signal generation is replaced; the existing paper engine stays real."""
    key = version + ":" + symbol
    last = int(frame.iloc[-1].close_ts_ms)
    if state.get(key) == last:
        return dict(status="DUPLICATE", signal=None)
    first = key not in state
    state[key] = last
    signal = dict(identity=version, lane="fixture", timeframe_min=30,
        symbol=symbol, side=1, signal_open_ts_ms=last - TF,
        signal_ts_ms=last, stop_price=95., max_hold_bars=4,
        segment_id="fixture") if first else None
    return dict(status="SIGNAL" if signal else "NO_SIGNAL", signal=signal)


class PublicBoundaryTests(unittest.TestCase):
    def test_environment_reexec_removes_credentials_and_python_injection(self):
        env = dict(PATH="/usr/bin", HTTPS_PROXY="http://proxy.invalid",
                   BINGX_API_KEY="fixture-secret", AWS_SECRET_ACCESS_KEY="fixture-secret",
                   PYTHONPATH="/untrusted", HOME="/credential-home")
        with patch.dict(os.environ, env, clear=True), patch.object(runtime.os, "chdir"), \
             patch.object(runtime.os, "execve", side_effect=RuntimeError("REEXEC")) as exe:
            with self.assertRaisesRegex(RuntimeError, "REEXEC"):
                runtime.main(["--out", "unused", "--source", "unused"])
        child_env = exe.call_args.args[2]
        self.assertEqual(set(child_env), {"PATH", "HTTPS_PROXY", "ZEL_ORDERLESS_SCRUBBED"})
        self.assertEqual(child_env["ZEL_ORDERLESS_SCRUBBED"], "1")

    def test_scrub_marker_cannot_bypass_credential_removal(self):
        with patch.dict(os.environ, {"ZEL_ORDERLESS_SCRUBBED": "1", "BINGX_API_KEY": "fixture"}, clear=True), \
             patch.object(runtime, "Shadow") as ctor:
            with self.assertRaisesRegex(ValueError, "UNSCRUBBED_ENVIRONMENT_BLOCKED"):
                runtime.main(["--out", "unused", "--source", "unused"])
        ctor.assert_not_called()

    def test_only_exact_public_get_endpoints_and_receipts(self):
        feed = runtime.PublicFeed()
        response = Mock(status=200)
        response.read.return_value = b'{"code":0}'
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        feed.opener = Mock()
        feed.opener.open.return_value = context
        for endpoint in runtime.ENDPOINTS:
            status, body = feed(runtime.PUBLIC + endpoint + "?symbol=BTC-USDT&limit=2")
            self.assertEqual((status, body), (200, b'{"code":0}'))
            request = feed.opener.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.data)
            self.assertFalse(any("key" in k.lower() or k.lower() == "authorization"
                                 for k in request.headers))
        self.assertEqual(len(feed.receipts), 2)
        self.assertTrue(all(x["method"] == "GET" and not x["auth_headers"] for x in feed.receipts))
        self.assertTrue(all(len(x["body_sha256"]) == 64 for x in feed.receipts))
        self.assertTrue(all(x["exchange_code"] == 0 for x in feed.receipts))
        response.read.return_value = b'{"code":100410,"msg":"retry"}'
        self.assertEqual(feed(runtime.PUBLIC + "/openApi/swap/v3/quote/klines")[1],
                         response.read.return_value)
        self.assertEqual(feed.receipts[-1]["exchange_code"], 100410)
        before = feed.opener.open.call_count
        paths = ["http://open-api.bingx.com/openApi/swap/v3/quote/klines",
                 "https://open-api.bingx.com.evil/openApi/swap/v3/quote/klines",
                 "https://user@open-api.bingx.com/openApi/swap/v3/quote/klines",
                 runtime.PUBLIC + "/openApi/swap/v2/trade/order",
                 runtime.PUBLIC + "/openApi/swap/v3/quote/klines?signature=fixture",
                 runtime.PUBLIC + "/openApi/swap/v3/quote/klines#fragment"]
        for url in paths:
            with self.subTest(url=url), self.assertRaises(ValueError):
                feed(url)
        self.assertEqual(feed.opener.open.call_count, before)
        with self.assertRaisesRegex(ValueError, "REDIRECT_BLOCKED"):
            runtime.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid")

    def test_audit_blocks_order_auth_and_credential_files(self):
        with patch.object(runtime.sys, "addaudithook") as install:
            evidence = runtime.install_audit_boundary()
        hook = install.call_args.args[0]
        allowed = runtime.PUBLIC + "/openApi/swap/v3/quote/klines?symbol=BTC-USDT"
        hook("urllib.Request", (allowed, None, {}, "GET"))
        self.assertEqual(evidence["public_get_calls"], 1)
        for url, body, headers, method in [
            (runtime.PUBLIC + "/openApi/swap/v2/trade/order", None, {}, "GET"),
            (allowed, None, {}, "POST"), (allowed, b"x", {}, "GET"),
            (allowed, None, {"X-bx-apikey": "fixture"}, "GET"),
            (allowed + "&signature=fixture", None, {}, "GET"),
        ]:
            with self.subTest(url=url, method=method), self.assertRaises(ValueError):
                hook("urllib.Request", (url, body, headers, method))
        for path in ("/tmp/.env", "/tmp/.env.production", "/tmp/.ssh/config", "/tmp/key.pem", "/tmp/key.key"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "CREDENTIAL_FILE_BLOCKED"):
                hook("open", (path, "r", 0))
        self.assertEqual(evidence["order_calls"], 0)
        self.assertEqual(evidence["credential_file_reads"], 0)


class SourceRetryTests(unittest.TestCase):
    """Synthetic HTTP/clock fixtures only; no network or economic replay."""

    def receipt(self, code=100410):
        return dict(source=runtime.PUBLIC + "/openApi/swap/v3/quote/klines",
                    http_status=200, exchange_code=code, body_sha256="a" * 64)

    def run_cli(self, failures, *, max_seconds=7200, clock_after_sleep=None):
        shadow = Mock()
        shadow.state = dict(http_receipts=[], accounts={"original": dict(pending={}, positions={})})
        shadow.report.return_value = dict(state="DEVELOPMENT_OBSERVATION")
        shadow.source_frames.return_value = ({}, {})
        feed = SimpleNamespace(receipts=[])
        clock = [0.0]
        calls = []

        def collect(*_, **__):
            calls.append(clock[0])
            index = len(calls) - 1
            if index < len(failures):
                error, receipt = failures[index]
                if receipt is not None:
                    feed.receipts.append(receipt)
                raise error
            clock[0] = max_seconds  # Successful cycle reaches the bounded end.

        def sleep(delay):
            clock[0] = clock_after_sleep if clock_after_sleep is not None else clock[0] + delay

        with patch.dict(os.environ, {"ZEL_ORDERLESS_SCRUBBED": "1"}, clear=True), \
             patch.object(runtime, "install_audit_boundary", return_value={"order_calls": 0}), \
             patch.object(runtime, "Shadow", return_value=shadow), \
             patch.object(runtime, "PublicFeed", return_value=feed), \
             patch.object(source_reader, "collect_once", side_effect=collect), \
             patch.object(runtime.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(runtime.time, "sleep", side_effect=sleep) as sleeper, \
             patch("builtins.print"):
            code = runtime.main(["--out", "fixture-out", "--source", "fixture-source",
                                 "--collect", "--max-seconds", str(max_seconds)])
        shadow.close.assert_called_once()
        return code, shadow, sleeper, calls

    def rejection(self):
        return source_reader.SourceDataError("FRESH_SOURCE_RESPONSE_REJECTED")

    def test_transient_retry_preserves_error_receipt_and_advances_only_after_success(self):
        code, shadow, sleeper, calls = self.run_cli([(self.rejection(), self.receipt())])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [0, 10])
        sleeper.assert_called_once_with(10)
        shadow.advance.assert_called_once()
        self.assertEqual(shadow.state["http_receipts"], [self.receipt()])
        self.assertEqual(shadow.state["last_error"]["reason"], "FRESH_SOURCE_RESPONSE_REJECTED")
        self.assertEqual(shadow.state["source_retry_events"][0]["disposition"], "WAIT_SOURCE_RETRY")
        self.assertEqual(shadow.state["accounts"], {"original": dict(pending={}, positions={})})

    def test_repeated_error_exhausts_three_retries_and_publishes_hold(self):
        code, shadow, sleeper, calls = self.run_cli([(self.rejection(), self.receipt())] * 4)
        self.assertEqual(code, 2)
        self.assertEqual(calls, [0, 10, 40, 100])
        self.assertEqual([x.args[0] for x in sleeper.call_args_list], [10, 30, 60])
        shadow.advance.assert_not_called()
        self.assertEqual(len(shadow.state["http_receipts"]), 4)
        self.assertEqual(shadow.atomic.call_args.args[1]["state"], "HOLD")
        self.assertEqual(shadow.state["source_retry_events"][-1]["disposition"], "HOLD_RETRY_BUDGET")

    def test_other_exchange_codes_integrity_and_auth_failures_never_retry(self):
        for error, receipt in [(self.rejection(), self.receipt(100001)),
                               (self.rejection(), None),
                               (ValueError("SHADOW_STATE_HASH_MISMATCH"), self.receipt()),
                               (ValueError("AUDIT_NON_PUBLIC_GET_BLOCKED"), self.receipt()),
                               (source_reader.SourceDataError("FRESH_NORMALIZED_RAW_MISMATCH"), self.receipt())]:
            with self.subTest(error=str(error), receipt=receipt):
                code, shadow, sleeper, calls = self.run_cli([(error, receipt)])
                self.assertEqual(code, 2)
                self.assertEqual(len(calls), 1)
                sleeper.assert_not_called()
                shadow.advance.assert_not_called()
                self.assertEqual(shadow.atomic.call_args.args[1]["state"], "HOLD")

    def test_unbounded_or_insufficient_time_does_not_enable_retry(self):
        for bound in (0, 5, 10):
            with self.subTest(bound=bound):
                code, shadow, sleeper, calls = self.run_cli([(self.rejection(), self.receipt())], max_seconds=bound)
                self.assertEqual(code, 2)
                sleeper.assert_not_called()
                shadow.advance.assert_not_called()

    def test_oversleep_never_starts_another_request_after_deadline(self):
        code, shadow, sleeper, calls = self.run_cli([(self.rejection(), self.receipt())],
                                                   max_seconds=20, clock_after_sleep=21)
        self.assertEqual(code, 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(shadow.atomic.call_args.args[1]["state"], "HOLD")
        shadow.advance.assert_not_called()


class RuntimeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out, self.source = Path(self.tmp.name) / "out", Path(self.tmp.name) / "source"
        self.patchers = [patch.object(runtime, "existing_settings", side_effect=settings),
            patch.object(runtime.time, "time", return_value=(BASE - 1) / 1000),
            patch.object(signals, "callbacks", return_value=SimpleNamespace()),
            patch.object(signals, "bind_causal_context", side_effect=lambda frames, _: frames)]
        for item in self.patchers:
            item.start()
            self.addCleanup(item.stop)
        self.shadows = []
        self.addCleanup(lambda: [s.close() for s in self.shadows])
        self.shadow = self.make()

    def make(self, **kwargs):
        result = runtime.Shadow(self.out, self.source, fixture=kwargs.get("fixture", True),
                               warmup_source=kwargs.get("warmup_source"))
        self.shadows.append(result)
        return result

    def setup_warmup(self):
        self.shadow.close()
        self.out = Path(self.tmp.name) / "warmup-out"
        seed = Path(self.tmp.name) / "seed"
        for path, start in ((self.source, BASE - TF), (seed, BASE - 123 * TF)):
            path.mkdir()
            (path / "IDENTITY.json").write_text(json.dumps({"start_ms": start}))
            (path / "CURSOR.json").write_text(json.dumps({"fixture": str(path)}))
        self.shadow = self.make(warmup_source=seed)
        warmup = minute_frame(BASE - 123 * TF, BASE - TF, BASE - 50)
        current = minute_frame(BASE - TF, BASE, BASE + 50)
        data = {seed: {SYMBOL: warmup}, self.source: {SYMBOL: current}}
        return seed, data

    def ingest(self, shadow=None, now=BASE + 100, quotes=None, data=None):
        target = shadow or self.shadow
        target.advance({SYMBOL: data if data is not None else frame(BASE - TF)},
                       now=now, quotes=quotes, witness={"fixture": True})

    def test_atomic_restart_duplicate_input_and_four_separate_accounts(self):
        with patch.object(signals, "on_bar", side_effect=fixture_signal), \
             patch.object(signals, "decide_entry"):
            self.ingest()
            first = deepcopy(self.shadow.state)
            self.ingest()
            self.assertEqual(self.shadow.state["market"], first["market"])
            self.assertEqual(self.shadow.state["decisions"], first["decisions"])
            self.assertEqual(self.shadow.state["accounts"], first["accounts"])
            self.assertEqual(len(self.shadow.state["accounts"]), 4)
            self.assertEqual(len({id(x) for x in self.shadow.state["accounts"].values()}), 4)
            self.shadow.close()
            restored = self.make()
            self.assertEqual(restored.state, self.shadow.state)
            self.ingest(restored)
            self.assertEqual(len(restored.state["market"]), 1)
            self.assertEqual(len(restored.state["decisions"]), 4)
            persisted = json.loads(restored.path.read_bytes())
            signature = persisted.pop("state_sha256")
            self.assertEqual(signature, runtime.digest(persisted))

    def test_failed_atomic_write_rolls_back_memory_and_preserves_disk(self):
        before, disk = deepcopy(self.shadow.state), self.shadow.path.read_bytes()
        with patch.object(signals, "on_bar", side_effect=fixture_signal), \
             patch.object(self.shadow, "atomic", side_effect=OSError("fixture_disk_failure")):
            with self.assertRaisesRegex(OSError, "fixture_disk_failure"):
                self.ingest()
        self.assertEqual(self.shadow.state, before)
        self.assertEqual(self.shadow.path.read_bytes(), disk)

    def test_retry_repair_does_not_accept_or_rewrite_old_code_pins(self):
        self.shadow.state["code_pins"]["ops/scalp7_orderless_shadow_v1.py"] = "0" * 64
        self.shadow.save()
        disk = self.shadow.path.read_bytes()
        self.shadow.close()
        with self.assertRaisesRegex(ValueError, "SHADOW_CODE_CHANGED"):
            self.make()
        self.assertEqual(self.shadow.path.read_bytes(), disk)

    def test_simultaneous_writer_and_state_tamper_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "OWNER_ALREADY_RUNNING"):
            self.make()
        self.shadow.close()
        state = json.loads(self.shadow.path.read_bytes())
        state["order_calls"] = 1
        self.shadow.path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "STATE_HASH_MISMATCH"):
            self.make()

    def test_future_duplicate_and_changed_market_bars_are_atomic_fail_closed(self):
        with patch.object(signals, "on_bar", side_effect=fixture_signal):
            self.ingest()
            original = deepcopy(self.shadow.state)
            cases = []
            future = frame(BASE - TF)
            future.loc[0, "available_ts_ms"] = BASE + 200
            cases.append((future, "FUTURE_SOURCE_OBSERVATION"))
            cases.append((pd.concat([frame(BASE - TF)] * 2, ignore_index=True), "ORDERED_UNIQUE"))
            changed = frame(BASE - TF)
            changed.loc[0, "close"] = 101.
            cases.append((changed, "COMMITTED_MARKET_BAR_CHANGED"))
            for value, reason in cases:
                with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                    self.ingest(data=value)
                self.assertEqual(self.shadow.state, original)

    def test_actual_signal_gap_halts_each_version_without_virtual_fill(self):
        self.ingest(data=frame(BASE - TF))
        self.ingest(now=BASE + 2 * TF, data=frame(BASE - TF, BASE + TF))
        for version in signals.VERSIONS:
            self.assertEqual(self.shadow.state["status"][version + ":" + SYMBOL], "UNKNOWN")
            record = next(x for x in reversed(self.shadow.state["decisions"]) if x["version"] == version)
            self.assertEqual(record["signal_result"]["reason"], "MISSING_OR_REORDERED_BAR")
            account = self.shadow.state["accounts"][version]
            self.assertFalse(account["pending"] or account["positions"] or account["trades"])

    def test_unknown_pending_is_held_across_duplicate_while_other_versions_enter(self):
        held_version = signals.VERSIONS[0]

        def first_unknown(state, **kwargs):
            if kwargs["version"] == held_version:
                return dict(status="UNKNOWN", reason="FIXTURE_SOURCE_GAP", signal=None)
            return fixture_signal(state, **kwargs)

        with patch.object(signals, "on_bar", side_effect=fixture_signal), \
             patch.object(signals, "decide_entry"):
            self.ingest()
            waiting = deepcopy(self.shadow.state["accounts"][held_version]["pending"])
            with patch.object(signals, "on_bar", side_effect=first_unknown):
                self.ingest(now=BASE + 110, quotes={SYMBOL: quote(BASE + 110)})
            self.ingest(now=BASE + 120, quotes={SYMBOL: quote(BASE + 120)})
        for version, account in self.shadow.state["accounts"].items():
            if version == held_version:
                self.assertEqual(account["pending"], waiting)
                self.assertFalse(account["positions"] or account["trades"])
                self.assertEqual(self.shadow.state["status"][version + ":" + SYMBOL], "UNKNOWN")
            else:
                self.assertEqual(len(account["positions"]), 1)

    def test_unknown_open_position_is_preserved_without_stop_or_fill(self):
        with patch.object(signals, "on_bar", side_effect=fixture_signal), \
             patch.object(signals, "decide_entry"):
            self.ingest()
            self.ingest(now=BASE + 110, quotes={SYMBOL: quote(BASE + 110)})
            self.ingest(now=BASE + 115, quotes={SYMBOL: quote(BASE + 115)})
            marks = {v: next(iter(a["positions"].values()))["unrealized_gross_bps"]
                     for v, a in self.shadow.state["accounts"].items()}
            with patch.object(signals, "on_bar", return_value=dict(status="UNKNOWN", signal=None)):
                self.ingest(now=BASE + 120, quotes={SYMBOL: quote(BASE + 120, 94., 95.)})
            self.ingest(now=BASE + 130, quotes={SYMBOL: quote(BASE + 130, 92., 93.)})
        for version, account in self.shadow.state["accounts"].items():
            position = next(iter(account["positions"].values()))
            self.assertEqual(position["status"], "HOLD_UNRESOLVED_SIGNAL_SOURCE")
            self.assertEqual(position["entry_price"], 100.)
            self.assertIsNone(position["pending_exit"])
            self.assertFalse(account["trades"])
            self.assertEqual(position["unrealized_gross_bps"], marks[version])

    def test_warmup_actual_receipts_are_preserved_and_historical_rows_get_no_credit(self):
        seed, data = self.setup_warmup()
        original = {p: x[SYMBOL].copy(deep=True) for p, x in data.items()}
        with patch.object(source_reader, "load_observed_minutes", side_effect=lambda path: data[path]):
            frames, witness = self.shadow.source_frames(BASE + 100)
        combined = frames[SYMBOL]
        self.assertEqual(len(combined), 123)
        self.assertEqual(combined.available_ts_ms.iloc[:-1].tolist(), [BASE - 50] * 122)
        self.assertEqual(combined.available_ts_ms.iloc[-1], BASE + 50)
        self.assertEqual(combined.fresh_observed.tolist(), [False] * 122 + [True])
        self.assertEqual(witness["warmup"]["availability"], "ACTUAL_HTTP_RECEIPTS_UNMODIFIED")
        for path in (seed, self.source):
            pd.testing.assert_frame_equal(data[path][SYMBOL], original[path])
        with patch.object(signals, "on_bar", return_value=dict(status="NO_SIGNAL", signal=None)):
            self.shadow.advance(frames, now=BASE + 100, witness=witness)
        market = self.shadow.state["market"]
        self.assertEqual(len(market), 1)
        self.assertEqual(market[0]["close_ts_ms"], BASE)
        self.assertEqual(market[0]["received_at_ms"], BASE + 50)
        self.assertFalse(market[0]["formal_fresh_credit"])
        self.assertEqual(self.shadow.report()["closed_T"], 0)
        self.assertFalse(any(a["pending"] or a["positions"] for a in self.shadow.state["accounts"].values()))

    def test_warmup_overlap_and_future_receipts_fail_closed(self):
        seed, data = self.setup_warmup()
        original = data[seed][SYMBOL]
        overlapping = minute_frame(BASE - TF, BASE, BASE + 50)
        future = original.copy(deep=True)
        future.loc[0, "received_at_ms"] = BASE + 101
        for invalid in (overlapping, future):
            data[seed] = {SYMBOL: invalid}
            with patch.object(source_reader, "load_observed_minutes", side_effect=lambda path: data[path]):
                with self.assertRaisesRegex(ValueError, "WARMUP_UNAVAILABLE_OR_OVERLAPPING"):
                    self.shadow.source_frames(BASE + 100)
            self.assertFalse(self.shadow.state["market"] or self.shadow.state["decisions"])
            self.assertIsNone(self.shadow.state["warmup_identity_sha256"])
            self.assertIsNone(self.shadow.state["warmup_cursor_sha256"])

    def test_warmup_pins_persist_and_changed_cursor_or_identity_is_rejected(self):
        seed, data = self.setup_warmup()
        with patch.object(source_reader, "load_observed_minutes", side_effect=lambda path: data[path]):
            self.shadow.source_frames(BASE + 100)
        self.shadow.save()
        self.shadow.close()
        restored = self.make(warmup_source=seed)
        self.assertEqual(restored.state["warmup_cursor_sha256"], self.shadow.state["warmup_cursor_sha256"])
        for filename in ("CURSOR.json", "IDENTITY.json"):
            path = seed / filename
            body = path.read_bytes()
            path.write_bytes(body + b" ")
            with patch.object(source_reader, "load_observed_minutes", side_effect=lambda path: data[path]) as load:
                with self.assertRaisesRegex(ValueError, "WARMUP_SOURCE_CHANGED"):
                    restored.source_frames(BASE + 100)
                self.assertEqual(load.call_args_list[0].args, (self.source,))
                self.assertEqual(load.call_count, 1)
            path.write_bytes(body)

    def test_source_and_warmup_snapshot_races_are_rejected_before_admission(self):
        seed, data = self.setup_warmup()
        for racing in (self.source, seed):
            cursor = racing / "CURSOR.json"
            original = cursor.read_bytes()

            def load(path):
                if path == racing:
                    cursor.write_bytes(original + b" ")
                return data[path]

            with patch.object(source_reader, "load_observed_minutes", side_effect=load):
                with self.assertRaisesRegex(ValueError, "SNAPSHOT_CHANGED"):
                    self.shadow.source_frames(BASE + 100)
            self.assertFalse(self.shadow.state["market"] or self.shadow.state["decisions"])
            cursor.write_bytes(original)

    def test_initialization_failure_releases_writer_lock_for_retry(self):
        self.shadow.close()
        with patch.object(runtime, "existing_settings", side_effect=ValueError("FIXTURE_SOURCE_UNAVAILABLE")):
            with self.assertRaisesRegex(ValueError, "FIXTURE_SOURCE_UNAVAILABLE"):
                self.make()
        resumed = self.make()
        self.assertEqual(resumed.state, self.shadow.state)

    def test_missing_latest_closed_bar_holds_existing_pending(self):
        with patch.object(signals, "on_bar", side_effect=fixture_signal), \
             patch.object(signals, "decide_entry"):
            self.ingest()
            pending = {v: deepcopy(x["pending"]) for v, x in self.shadow.state["accounts"].items()}
            self.ingest(now=BASE + TF + 110, quotes={SYMBOL: quote(BASE + TF + 110)})
        for version, account in self.shadow.state["accounts"].items():
            self.assertEqual(account["pending"], pending[version])
            self.assertFalse(account["positions"])
            self.assertEqual(self.shadow.state["status"][version + ":" + SYMBOL],
                             "UNKNOWN_MISSING_LATEST_CLOSED_BAR")

    def test_actual_paper_entry_stop_later_fill_cost_and_no_fresh_credit(self):
        with patch.object(signals, "on_bar", side_effect=fixture_signal), \
             patch.object(signals, "decide_entry") as decision:
            self.ingest()
            self.ingest(now=BASE + 110, quotes={SYMBOL: quote(BASE + 110)})
            self.assertEqual(decision.call_count, 4)
            for account in self.shadow.state["accounts"].values():
                position = next(iter(account["positions"].values()))
                self.assertEqual(position["entry_price"], 100.)
                self.assertEqual(position["entry_ts_ms"], BASE + 110)
                self.assertIsNone(position["quantity"])
                self.assertIsNone(position["NAV"])
            self.ingest(now=BASE + 120, quotes={SYMBOL: quote(BASE + 120, 94., 95.)})
            self.assertEqual(self.shadow.report()["closed_T"], 0)
            self.ingest(now=BASE + 130, quotes={SYMBOL: quote(BASE + 130, 92., 93.)})
            for account in self.shadow.state["accounts"].values():
                row = account["trades"][0]
                self.assertEqual(row["reason"], "OBSERVED_HARD_STOP")
                self.assertAlmostEqual(row["gross_bps"], -800.)
                self.assertAlmostEqual(row["net_bps"], -808.)
                self.assertEqual(row["cost_bps"], 8.)
                self.assertEqual(row["evidence_kind"], "FIXTURE")
                self.assertFalse(row["formal_fresh_credit"] or row["account_or_exchange_fill"])
                self.assertEqual(row["order_authority"], "BLOCKED")
            report = self.shadow.report()
            self.assertEqual(report["closed_T"], 4)
            self.assertEqual(report["order_calls"], 0)
            self.assertIsNone(report["NAV"])

    def test_stop_and_restart_preserve_open_virtual_positions_without_fake_close(self):
        with patch.object(signals, "on_bar", side_effect=fixture_signal), \
             patch.object(signals, "decide_entry"):
            self.ingest()
            self.ingest(now=BASE + 110, quotes={SYMBOL: quote(BASE + 110)})
            accounts = deepcopy(self.shadow.state["accounts"])
            self.shadow.stop()
            self.shadow.close()
            restored = self.make()
            self.assertEqual(restored.state["accounts"], accounts)
            self.assertEqual(restored.report()["state"], "STOPPED")
            self.assertEqual(restored.report()["closed_T"], 0)
            self.assertEqual(restored.report()["open_virtual_positions"], 4)
            with self.assertRaisesRegex(ValueError, "SHADOW_STOPPED"):
                self.ingest(restored, now=BASE + 120)


if __name__ == "__main__":
    unittest.main()
