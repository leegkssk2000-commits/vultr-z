"""Synthetic-only regression tests; no market-file reads or economic run budget."""
from copy import deepcopy
from dataclasses import asdict
import math
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_common_engine_v1 as e

COST = {"fee_bps": 10.0, "spread_bps": 1.0, "impact_bps": 2.0,
        "funding_proxy_bps": 1.0, "actual_funding": False}
SHAS = {"B_COMMON": "b-source", "P_COMMON": "p-source"}


def bars(n=160, oscillating=False):
    out = []
    for i in range(n):
        op = 100.0 + (0.08*i + 2.0*math.sin(i/5.0) if oscillating else 0.0)
        cl = op + (0.2*math.cos(i/3.0) if oscillating else 0.0)
        out.append({"ts_ms": (1_780_000_000_000//e.HOUR+i)*e.HOUR,
                    "open": op, "close": cl, "high": max(op, cl)+1.0,
                    "low": min(op, cl)-1.0, "volume": 10.0})
    return out


def signal(rows, i=64, *, symbol="BTC-USDT", side="long", sl=90., tp=None, p=True):
    intent = {"strategy_id": "trend_rider", "symbol": symbol, "side": side, "no_trade": False,
              "signal_ts": rows[i]["ts_ms"], "sl": sl, "tp": tp, "timeout": {"bars": 48},
              "risk_size": {"risk_fraction_of_equity": .005},
              "exposure": {"notional_fraction_of_equity": .15, "cap": .15},
              "pyramiding": {"enabled": False}, "cooldown": {"bars": 2},
              "verified_round_trip_cost_bps": 14.0}
    lanes = {}
    for lane in e.LANES:
        own = deepcopy(intent)
        feature_body = {"strategy_id": "trend_rider", "symbol": symbol,
                        "signal_ts": rows[i]["ts_ms"], "close": rows[i]["close"],
                        "atr": 1.0, "values": {}}
        sha_body = dict(feature_body)
        if lane == "P_COMMON":
            sha_body.update(changed_axis=e.primary.AXIS, context_transform=e.primary.CONTEXT_TRANSFORM)
        feature_sha = e.digest(sha_body)
        feature = {**feature_body, "fresh": True, "feature_sha": feature_sha}
        own["feature_sha"] = feature_sha
        if lane == "P_COMMON" and not p:
            own["no_trade"] = True
        lanes[lane] = {"intent": own, "intent_sha": e.digest(own),
                       "feature": feature, "feature_sha": feature_sha}
    out = {"symbol": symbol, "signal_index": i, "signal_ts": rows[i]["ts_ms"],
            "decision_ts": rows[i]["ts_ms"]+e.HOUR, "side": side,
            "snapshot_sha": e.digest([symbol, i, side]),
            "input_prefix_sha": e.digest(rows[:i+1]), "b_actionable": True,
            "p_actionable": p, "b_only": not p, "lanes": lanes}
    out["snapshot_sha"] = e.digest({key: value for key, value in out.items() if key != "snapshot_sha"})
    return out


class CausalFeatures(unittest.TestCase):
    def test_exact_original_B_P_feature_intent_parity(self):
        rows = bars(90, True)
        signals = e.build_signals({"BTC-USDT": rows}, COST, SHAS)
        self.assertEqual([x["signal_index"] for x in signals], list(range(64, 90)))
        for i in (64, 65, 75, 89):
            snap = signals[i-64]
            for lane, owner, cfg in (
                ("B_COMMON", e.broad, e.broad.TrendPolicyConfig()),
                ("P_COMMON", e.primary, e.primary.TrendRiderTransitionFreshnessConfig()),
            ):
                feature = owner.compute_trend_rider_feature(
                    rows[:i+1], symbol="BTC-USDT", now_ts_ms=rows[i]["ts_ms"], config=cfg)
                intent = owner.build_trend_rider_intent(
                    feature, policy_source_sha=SHAS[lane], verified_round_trip_cost_bps=14., config=cfg)
                self.assertEqual(snap["lanes"][lane]["feature"], asdict(feature))
                self.assertEqual(snap["lanes"][lane]["intent"], asdict(intent))
                self.assertEqual(snap["lanes"][lane]["intent_sha"], intent.sha)
            self.assertEqual(snap["decision_ts"], snap["signal_ts"]+e.HOUR)

    def test_prefix_future_mutation_cannot_change_any_prior_snapshot(self):
        rows = bars(100, True)
        old = e.build_signals({"BTC-USDT": rows[:85]}, COST, SHAS)
        modified = deepcopy(rows)
        for row in modified[85:]:
            for key in ("open", "high", "low", "close"):
                row[key] *= 20
        full = e.build_signals({"BTC-USDT": modified}, COST, SHAS)
        self.assertEqual(old, full[:len(old)])

    def test_build_no_network_and_P_subset_with_fresh_B_only_empty(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("NETWORK_FORBIDDEN")):
            snapshots = e.build_signals({"BTC-USDT": bars(100, True)}, COST, SHAS)
        for snap in snapshots:
            self.assertFalse(snap["p_actionable"] and not snap["b_actionable"])
            if snap["b_only"]:
                features = snap["lanes"]["P_COMMON"]["feature"]["values"]
                side = snap["side"]
                self.assertFalse(features[side+"_transition_fresh"])

    def test_cadence_duplicate_symbol_clock_and_negative_volume_fail_closed(self):
        original = bars(80)
        for changed, error in (
            (original[:70]+original[71:], "COMMON_GAP_OR_CLOCK"),
            (original[:70]+[original[69]]+original[71:], "BAR_TS_NON_MONOTONIC_OR_DUPLICATE"),
        ):
            with self.assertRaisesRegex(ValueError, error):
                e.build_signals({"BTC-USDT": changed}, COST, SHAS)
        shifted = deepcopy(original)
        for row in shifted:
            row["ts_ms"] += e.HOUR
        with self.assertRaisesRegex(ValueError, "CLOCK_MISMATCH"):
            e.build_signals({"BTC-USDT": original, "ETH-USDT": shifted}, COST, SHAS)
        negative = deepcopy(original)
        negative[-1]["volume"] = -1
        with self.assertRaisesRegex(ValueError, "VOLUME_NEGATIVE"):
            e.build_signals({"BTC-USDT": negative}, COST, SHAS)


class CommonReplay(unittest.TestCase):
    def replay(self, rows, signals, end=150, start=64, lane="B_COMMON"):
        return e.replay(signals, {"BTC-USDT": rows}, "SYNTHETIC", start, end, lane, COST)

    def test_native_SL_precedes_TP_same_bar(self):
        rows = bars()
        rows[65].update(high=103., low=97.)
        out = self.replay(rows, [signal(rows, sl=98., tp=102.)])
        campaign = out["campaigns"][0]
        self.assertEqual(campaign["exit_reason"], "SL")
        self.assertEqual(campaign["exit"], 98.)
        self.assertEqual(campaign["net_bps"], -214.)
        self.assertEqual(campaign["cost2_net_bps"], -228.)

    def test_native_gap_optimism_preserved_disclosed_not_silently_repaired(self):
        for side, sl, open_price in (("long", 99., 95.), ("short", 101., 105.)):
            rows = bars()
            rows[65].update(open=open_price, close=open_price, high=open_price+1, low=open_price-1)
            out = self.replay(rows, [signal(rows, side=side, sl=sl)])
            campaign = out["campaigns"][0]
            self.assertEqual(campaign["entry"], open_price)
            self.assertEqual(campaign["exit"], sl)
            self.assertTrue(campaign["native_stop_gap_optimism"])
            self.assertEqual(out["metrics"]["gap_optimism_T"], 1)

    def test_timeout_48_includes_49_bars_and_final_timeout_remains_open(self):
        rows = bars()
        completed = self.replay(rows, [signal(rows)], end=115)["campaigns"][0]
        self.assertEqual(completed["exit_reason"], "TIMEOUT")
        self.assertEqual(completed["exit_index"], 113)
        self.assertEqual(completed["hold_hours"], 49.)
        censored = self.replay(rows, [signal(rows)], end=114)["campaigns"][0]
        self.assertEqual(censored["status"], "OPEN_CENSORED")
        self.assertIsNone(censored["exit_reason"])
        self.assertEqual(censored["terminal_reserve_bps"], 14.)

    def test_final_bar_native_stop_completes_and_cost_never_double_charged(self):
        rows = bars()
        rows[113].update(low=89.)
        out = self.replay(rows, [signal(rows)], end=114)
        self.assertEqual(out["campaigns"][0]["status"], "COMPLETED")
        self.assertEqual(out["campaigns"][0]["cost_bps"], 14.)
        self.assertEqual(out["metrics"]["terminal_net_bps"], -1014.)

    def test_ownership_equal_boundary_rejected_next_bar_allowed_and_duplicates_raise(self):
        rows = bars()
        rows[65].update(low=89.)
        signals = [signal(rows, i=i) for i in (64, 65, 66, 67)]
        out = self.replay(rows, signals)
        self.assertEqual([x["status"] for x in out["events"]],
                         ["COMPLETED", "OWNERSHIP_REJECTED", "OWNERSHIP_REJECTED", "COMPLETED"])
        self.assertEqual([x["entry_index"] for x in out["campaigns"]], [65, 68])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SIGNAL"):
            self.replay(rows, signals+[signals[0]])

    def test_each_partition_starts_flat_but_final_signal_does_not_fill(self):
        rows = bars(200)
        first = self.replay(rows, [signal(rows, 90), signal(rows, 99)], end=100)
        self.assertEqual(first["campaigns"][0]["status"], "OPEN_CENSORED")
        self.assertEqual(first["events"][-1]["status"], "UNFILLED_BOUNDARY_SIGNAL")
        second = self.replay(rows, [signal(rows, 90), signal(rows, 100)], start=100, end=160)
        self.assertEqual(len(second["campaigns"]), 1)
        self.assertEqual(second["campaigns"][0]["entry_index"], 101)

    def test_future_prices_do_not_enter_earlier_partition_marks_or_fills(self):
        rows = bars()
        snap = signal(rows)
        before = self.replay(rows, [snap], end=90)
        changed = deepcopy(rows)
        for row in changed[90:]:
            row.update(open=1000., close=1000., high=2000., low=.01)
        after = self.replay(changed, [snap], end=90)
        self.assertEqual(before, after)

    def test_union_P_priority_dedup_and_B_only_rejection(self):
        rows = bars()
        snapshots = [signal(rows, 64, p=True), signal(rows, 120, p=False)]
        out = self.replay(rows, snapshots, lane=lambda s: "P_COMMON" if s["p_actionable"] else None)
        self.assertEqual(len(out["campaigns"]), 1)
        self.assertEqual(out["campaigns"][0]["selected_lane"], "P_COMMON")
        self.assertEqual(out["metrics"]["quality_gate_rejected_signals"], 1)

    def test_open_mark_full_cost_reserve_equity_bridge_and_inputs_unchanged(self):
        rows = bars()
        rows[89].update(close=102., high=103.)
        snapshots = [signal(rows)]
        original = deepcopy((rows, snapshots, COST))
        out = self.replay(rows, snapshots, end=90)
        self.assertEqual(out["metrics"]["terminal_net_bps"], 186.)
        self.assertEqual(out["metrics"]["cost2_terminal_net_bps"], 172.)
        self.assertEqual(out["equity"][-1]["equity_net_bps"], 186.)
        self.assertEqual(out["metrics"]["symbol_hours"], 25.)
        self.assertEqual((rows, snapshots, COST), original)

    def test_bad_clock_cost_or_native_config_fail_closed(self):
        rows = bars()
        for field, value, message in (("decision_ts", 0, "CLOCK_BINDING"),):
            snap = signal(rows)
            snap[field] = value
            with self.assertRaisesRegex(ValueError, message):
                self.replay(rows, [snap])
        for field, value, message in (("timeout", {"bars": 47}, "TIMEOUT_DRIFT"),
                                      ("verified_round_trip_cost_bps", 13., "COST_DRIFT"),
                                      ("cooldown", {"bars": 1}, "OWNERSHIP_DRIFT")):
            snap = signal(rows)
            snap["lanes"]["B_COMMON"]["intent"][field] = value
            snap["lanes"]["B_COMMON"]["intent_sha"] = e.digest(snap["lanes"]["B_COMMON"]["intent"])
            snap["snapshot_sha"] = e.digest({key: value for key, value in snap.items() if key != "snapshot_sha"})
            with self.assertRaisesRegex(ValueError, message):
                self.replay(rows, [snap])
        with self.assertRaisesRegex(ValueError, "DEV_PROXY_ONLY"):
            e.validate_cost({**COST, "actual_funding": True})

    def test_saved_sha_and_lane_bindings_reject_tampering(self):
        rows = bars()
        snap = signal(rows)
        snap["lanes"]["B_COMMON"]["intent"]["sl"] = 99.
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_SHA_MISMATCH"):
            self.replay(rows, [snap])
        snap["snapshot_sha"] = e.digest({k: v for k, v in snap.items() if k != "snapshot_sha"})
        with self.assertRaisesRegex(ValueError, "INTENT_SHA_MISMATCH"):
            self.replay(rows, [snap])
        snap = signal(rows)
        snap["b_only"] = True
        snap["snapshot_sha"] = e.digest({k: v for k, v in snap.items() if k != "snapshot_sha"})
        with self.assertRaisesRegex(ValueError, "ACTIONABLE_IDENTITY_BINDING"):
            self.replay(rows, [snap])
        snap = signal(rows)
        snap["lanes"]["P_COMMON"]["feature"]["atr"] = 999.
        snap["snapshot_sha"] = e.digest({k: v for k, v in snap.items() if k != "snapshot_sha"})
        with self.assertRaisesRegex(ValueError, "FEATURE_SHA_MISMATCH"):
            self.replay(rows, [snap])

    def test_same_bar_stop_counts_exposure_and_saved_marks_bridge(self):
        rows = bars()
        rows[65]["low"] = 89.
        out = self.replay(rows, [signal(rows)])
        self.assertEqual(out["metrics"]["max_concurrent_symbols"], 1)
        self.assertEqual(out["metrics"]["symbol_hours"], 1.)
        campaign = out["campaigns"][0]
        self.assertEqual(len(campaign["mark_path"]), 1)
        self.assertEqual(campaign["mark_path"][-1]["net_bps"], campaign["terminal_net_bps"])


if __name__ == "__main__":
    unittest.main()
