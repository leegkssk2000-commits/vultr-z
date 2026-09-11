"""Artificial artifact tests only; no historical replay, HTTP, or activation."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import squeeze_g5b_evidence_v1 as evidence

B = 1_800_000_000_000


def ident():
    value = {k: evidence.stable_sha(k) if k.endswith("sha") else k for k in evidence.IDENTITY_KEYS}
    value.update(evidence.FROZEN)
    value["fee_authority_sha"] = fee()["receipt_sha256"]
    return value


def artifact(raw, *, observed=B + 2_000_000, endpoint="/test-official-source", **extra):
    return evidence.seal({"raw": raw, "observed_ts": observed, "source_endpoint": endpoint,
                          "origin": "FORWARD_REAL", "proxy": False, "symbol": "BTC-USDT", **extra})


def fee():
    return artifact({"taker_fee_bps": "5.0"}, observed=B - 1000,
                    source_kind="OFFICIAL_TAKER_FEE", effective_from_ms=B - 100_000,
                    effective_until_ms=B + 10_000_000)


def depth(due, observed, mid):
    return artifact({"time": due + 1, "bids": [[str(mid - 1), "10"]],
                     "asks": [[str(mid + 1), "10"]]}, observed=observed,
                    endpoint="/openApi/swap/v2/quote/depth", requested_ts=due)


def bar(ts):
    return artifact({"bar_close_ts": ts, "open": "100", "high": "102", "low": "99",
                     "close": "101", "volume": "20"}, observed=ts,
                    endpoint="/openApi/swap/v3/quote/klines")


def fixture(status="CLOSED"):
    identity = ident()
    first_due = B + 300_000
    signal = bar(first_due)
    common = {**identity, "lot_id": "lot-root", "root_lot_id": "lot-root",
              "campaign_id": "campaign-root", "symbol": "BTC-USDT", "side": "long",
              "signal_sha": signal["receipt_sha256"]}
    legs = []
    remaining = 0.0
    for ordinal, (kind, due, mid, qty) in enumerate((
        ("ENTRY", first_due, 100, 3), ("PARTIAL", B + 900_000, 110, 1),
        ("FINAL_EXIT", B + 1_800_000, 120, 2),
    )):
        observed = due + 2
        px = mid + 1 if kind == "ENTRY" else mid - 1
        change = qty if kind == "ENTRY" else -qty
        legs.append({**common, "leg_id": "leg-" + str(ordinal), "kind": kind,
                     "leg_sequence": ordinal, "depth_consumed_base_before": 0.0,
                     "decision_ts": due, "due_open_ts": due, "observed_ts": observed,
                     "delay_ms": 2, "decision_bar": signal if ordinal == 0 else bar(due),
                     "depth": depth(due, observed, mid), "fee_authority": fee(),
                     "base_qty": qty, "normalized_qty": qty / 3, "notional": qty * px,
                     "fee_cash": qty * px * .0005, "slippage_cash": qty, "impact_cash": 0.0,
                     "remaining_qty_before": remaining, "remaining_qty_after": remaining + change,
                     "remaining_normalized_before": remaining / 3,
                     "remaining_normalized_after": (remaining + change) / 3,
                     "duplicate": 0, "lookahead": 0, "historical_backfill": False})
        remaining += change
    as_of = B + 1_800_002 if status != "CLOSED" else B + 1_801_002
    if status != "CLOSED":
        legs = legs[:2]
    campaign = {**common, "status": status, "initial_base_qty": 3,
                "initial_normalized_qty": 1, "remaining_base_qty": 0 if status == "CLOSED" else 2,
                "final_exit_ts": legs[-1]["observed_ts"] if status == "CLOSED" else None}
    if status != "CLOSED":
        campaign.update(mark_depth=depth(as_of - 2, as_of, 120), mark_fee_authority=fee())
    calendar = artifact({"coverage_start_ms": first_due, "coverage_end_ms": as_of,
                         "settlement_ts": [B + 750_000, B + 1_350_000]},
                        observed=as_of, source_kind="OFFICIAL_SETTLEMENT_CALENDAR")
    rows = []
    for ts, rate, qty in ((B + 750_000, .001, 3), (B + 1_350_000, -.002, 2)):
        rows.append({"ts_ms": ts, "qty_at_settlement": qty, "signed_cash": qty * 100 * rate,
                     "rate_source": artifact({"fundingTime": ts, "fundingRate": str(rate)},
                                             observed=ts + 1, endpoint="/openApi/swap/v2/quote/fundingRate"),
                     "mark_source": artifact({"time": ts, "markPrice": "100"}, observed=ts + 1)})
    funding = evidence.seal({"calendar": calendar, "rows": rows})
    path = artifact([{"open_ts": ts, "close_ts": ts + 300_000, "open": "100",
                      "high": "125", "low": "95", "close": "110"}
                     for ts in range(B + 600_000, B + 1_800_000, 300_000)],
                    observed=as_of, endpoint="/openApi/swap/v3/quote/klines", interval_ms=300_000)
    return campaign, legs, funding, path, identity, as_of


def run_fixture(data):
    campaign, legs, funding, path, identity, as_of = data
    return evidence.campaign_evidence(campaign, legs, funding, path, identity,
                                      boundary_ms=B, as_of_ms=as_of)


class SqueezeEvidenceTests(unittest.TestCase):
    def assertBlocked(self, data, reason):
        result = run_fixture(data)
        self.assertFalse(result["production_grade"], result)
        self.assertEqual(result["formal_fresh_T"], 0)
        self.assertTrue(any(reason in b for b in result["blockers"]), result["blockers"])
        self.assertTrue(all(v is None for v in result["metrics"].values()))

    def test_closed_accounting_signed_funding_partial_qty_and_full_cost(self):
        result = run_fixture(fixture())
        self.assertTrue(result["production_grade"], result["blockers"])
        self.assertEqual(result["formal_fresh_T"], 1)
        self.assertAlmostEqual(result["metrics"]["net_cash"], 43.775)
        self.assertAlmostEqual(result["metrics"]["funding_cash"], -.1)
        self.assertAlmostEqual(result["metrics"]["gross_mid_cash"], 50)
        self.assertAlmostEqual(result["metrics"]["slippage_cash"], 6)
        self.assertAlmostEqual(result["metrics"]["fee_cash"], .325)
        self.assertAlmostEqual(result["metrics"]["MFE_bps"], 2500)
        self.assertAlmostEqual(result["metrics"]["MAE_bps"], 500)

    def test_open_and_censored_mark_reserve_are_not_closed_credit(self):
        for status in ("OPEN", "CENSORED"):
            with self.subTest(status=status):
                result = run_fixture(fixture(status))
                self.assertTrue(result["production_grade"], result["blockers"])
                self.assertEqual(result["formal_fresh_T"], 0)
                self.assertAlmostEqual(result["metrics"]["remaining_mark_cash"], 240)
                self.assertAlmostEqual(result["metrics"]["remaining_exit_cost_cash"], 2.119)
                self.assertAlmostEqual(result["metrics"]["net_cash"], 43.775)

    def test_partial_leg_itself_never_formal_t(self):
        _, legs, _, _, identity, as_of = fixture()
        result = evidence.validate_leg(legs[1], identity, boundary_ms=B, as_of_ms=as_of)
        self.assertTrue(result["production_grade"], result["blockers"])
        self.assertEqual(result["formal_fresh_T"], 0)

    def test_equal_timestamp_partial_final_share_and_consume_raw_depth(self):
        data = list(fixture())
        campaign, legs = data[:2]
        shared = legs[1]["depth"]
        shared = evidence.seal({**shared, "raw": {**shared["raw"],
                               "bids": [[109, .5], [108, 1], [107, 2]]}})
        for leg, offset in ((legs[1], 0), (legs[2], 1)):
            leg.update(decision_ts=legs[1]["decision_ts"], due_open_ts=legs[1]["due_open_ts"],
                       observed_ts=legs[1]["observed_ts"], decision_bar=legs[1]["decision_bar"],
                       depth=shared, depth_consumed_base_before=offset)
            vwap = evidence.depth_vwap_base(shared["raw"]["bids"], leg["base_qty"], consumed_base_before=offset)
            leg.update(notional=leg["base_qty"] * vwap, fee_cash=leg["base_qty"] * vwap * .0005,
                       slippage_cash=leg["base_qty"] * (110 - vwap), impact_cash=leg["base_qty"] * (109 - vwap))
        campaign["final_exit_ts"] = legs[2]["observed_ts"]
        data[-1] = legs[2]["observed_ts"] + 1000
        data[2] = evidence.seal({**data[2], "rows": data[2]["rows"][:1]})
        data[2]["calendar"] = evidence.seal({**data[2]["calendar"], "observed_ts": data[-1]})
        data[2] = evidence.seal(data[2])
        data[3] = evidence.seal({**data[3], "raw": data[3]["raw"][:1], "observed_ts": data[-1]})
        result = run_fixture(data)
        self.assertTrue(result["production_grade"], result["blockers"])
        self.assertEqual(result["formal_fresh_T"], 1)
        self.assertAlmostEqual(result["metrics"]["net_cash"], -303 + 108.5 + 214.5 - (303 + 108.5 + 214.5) * .0005 - .3)
        legs[2]["depth_consumed_base_before"] = 0
        # Recompute claimed final cost to emulate a second fill reusing liquidity.
        legs[2].update(notional=216, fee_cash=216 * .0005, slippage_cash=4, impact_cash=2)
        self.assertBlocked(data, "DEPTH_BATCH_CONSUMPTION")

    def test_missing_components_never_become_zero_cost(self):
        for component in ("funding", "path", "depth", "fee_authority"):
            with self.subTest(component=component):
                data = list(fixture())
                if component in ("funding", "path"):
                    data[2 if component == "funding" else 3] = None
                else:
                    data[1][0][component] = None
                self.assertBlocked(data, "MISSING")

    def test_dev_proxy_is_rejected(self):
        data = fixture()
        data[1][0]["depth"] = evidence.seal({**data[1][0]["depth"], "proxy": True})
        self.assertBlocked(data, "DEPTH_PROXY")

    def test_unsealed_raw_depth_mutation_rejected(self):
        data = fixture()
        data[1][0]["depth"]["raw"]["asks"][0][0] = "999"
        self.assertBlocked(data, "DEPTH_HASH")

    def test_base_quantity_vwap_and_depth_exhaustion(self):
        self.assertAlmostEqual(evidence.depth_vwap_base([[100, 1], [110, 2]], 2), 105)
        with self.assertRaisesRegex(evidence.EvidenceError, "UNFILLED"):
            evidence.depth_vwap_base([[100, 1]], 2)

    def test_fee_authority_must_be_effective_and_observed_at_fill(self):
        for key, value, reason in (("effective_until_ms", B, "FEE_FROZEN_AUTHORITY_PARITY"),
                                   ("observed_ts", B + 10_000_000, "FEE_FUTURE")):
            with self.subTest(key=key):
                data = fixture()
                data[1][0]["fee_authority"] = evidence.seal({**data[1][0]["fee_authority"], key: value})
                self.assertBlocked(data, reason)

    def test_missing_funding_row_or_calendar_coverage_blocks(self):
        data = list(fixture())
        data[2] = evidence.seal({**data[2], "rows": data[2]["rows"][1:]})
        self.assertBlocked(data, "FUNDING_SETTLEMENT_COVERAGE")
        data = list(fixture())
        calendar = data[2]["calendar"]
        calendar = evidence.seal({**calendar, "raw": {**calendar["raw"], "coverage_start_ms": B + 600_000}})
        data[2] = evidence.seal({**data[2], "calendar": calendar})
        self.assertBlocked(data, "FUNDING_COVERAGE")

    def test_funding_zero_requires_explicit_complete_empty_calendar(self):
        data = list(fixture())
        calendar = data[2]["calendar"]
        calendar = evidence.seal({**calendar, "raw": {**calendar["raw"], "settlement_ts": []}})
        data[2] = evidence.seal({"calendar": calendar, "rows": []})
        result = run_fixture(data)
        self.assertTrue(result["production_grade"], result["blockers"])
        self.assertEqual(result["metrics"]["funding_cash"], 0)

    def test_funding_uses_remaining_quantity_and_preserves_credit_sign(self):
        data = list(fixture())
        data[2]["rows"][1]["qty_at_settlement"] = 3
        data[2] = evidence.seal(data[2])
        self.assertBlocked(data, "FUNDING_QTY_RECONCILIATION")
        data = list(fixture())
        data[2]["rows"][1]["signed_cash"] = .4
        data[2] = evidence.seal(data[2])
        self.assertBlocked(data, "FUNDING_CASH_RECONCILIATION")

    def test_duplicate_funding_or_path_rows_are_not_silently_deduped(self):
        data = list(fixture())
        data[2]["rows"].append(copy.deepcopy(data[2]["rows"][-1]))
        data[2] = evidence.seal(data[2])
        self.assertBlocked(data, "FUNDING_SETTLEMENT_COVERAGE")
        data = list(fixture())
        data[3]["raw"].append(copy.deepcopy(data[3]["raw"][-1]))
        data[3] = evidence.seal(data[3])
        self.assertBlocked(data, "PATH_CONTINUITY_OR_DUPLICATE")

    def test_partial_path_coverage_and_future_observation_fail(self):
        data = list(fixture())
        data[3]["raw"].pop(1)
        data[3] = evidence.seal(data[3])
        self.assertBlocked(data, "PATH_CONTINUITY_OR_DUPLICATE")
        data = list(fixture())
        data[3] = evidence.seal({**data[3], "observed_ts": data[-1] + 1})
        self.assertBlocked(data, "PATH_FUTURE")

    def test_preboundary_signal_rejected_even_if_observed_after_boundary(self):
        data = fixture()
        new_bar = evidence.seal({**data[1][0]["decision_bar"],
                                "raw": {**data[1][0]["decision_bar"]["raw"], "bar_close_ts": B}})
        data[1][0]["decision_bar"] = new_bar
        for row in [data[0], *data[1]]:
            row["signal_sha"] = new_bar["receipt_sha256"]
        self.assertBlocked(data, "ENTRY_SIGNAL_BOUNDARY_OR_SHA")

    def test_delayed_observation_is_recorded_without_backdating(self):
        data = fixture()
        data[1][0]["delay_ms"] = 0
        self.assertBlocked(data, "DELAY_RECONCILIATION")

    def test_decision_cannot_see_later_completed_bar(self):
        data = fixture()
        data[1][0]["decision_bar"] = evidence.seal({**data[1][0]["decision_bar"], "observed_ts": B + 900_000})
        self.assertBlocked(data, "DECISION_BAR_FUTURE")

    def test_frozen_identity_and_exact_config_hash_required(self):
        data = fixture()
        data[1][1]["config_sha"] = "f" * 64
        self.assertBlocked(data, "IDENTITY_PARITY")
        data = fixture()
        data[4]["candidate_ordinal"] = 83
        self.assertBlocked(data, "FROZEN_IDENTITY_DRIFT")

    def test_duplicate_leg_overclose_and_partial_qty_are_rejected(self):
        data = fixture()
        data[1].append(copy.deepcopy(data[1][-1]))
        self.assertBlocked(data, "LEG_DUPLICATE")
        data = fixture()
        data[1][1]["remaining_qty_after"] = 3
        self.assertBlocked(data, "REMAINING_AFTER_RECONCILIATION")
        data = fixture()
        data[0]["remaining_base_qty"] = 1
        self.assertBlocked(data, "CAMPAIGN_REMAINING_RECONCILIATION")

    def test_open_cannot_fabricate_final_exit_and_mark_must_be_current(self):
        data = fixture("OPEN")
        data[0]["final_exit_ts"] = data[-1]
        self.assertBlocked(data, "FINAL_EXIT_TIMESTAMP")
        data = fixture("CENSORED")
        data[0]["mark_depth"] = evidence.seal({**data[0]["mark_depth"], "observed_ts": data[-1] - 1})
        self.assertBlocked(data, "MARK_NOT_CURRENT")

    def test_reused_independent_lot_quantity_is_scaled(self):
        data = fixture()
        for row in [data[0], *data[1]]:
            row["lot_id"], row["campaign_id"] = "reuse-lot", "reuse-campaign"
        for row in data[1]:
            for key in ("base_qty", "normalized_qty", "notional", "fee_cash", "slippage_cash",
                        "remaining_qty_before", "remaining_qty_after", "remaining_normalized_before", "remaining_normalized_after"):
                row[key] /= 3
        data[0]["initial_base_qty"] /= 3
        data[0]["initial_normalized_qty"] /= 3
        for row in data[2]["rows"]:
            row["qty_at_settlement"] /= 3
            row["signed_cash"] /= 3
        data = list(data)
        data[2] = evidence.seal(data[2])
        result = run_fixture(data)
        self.assertTrue(result["production_grade"], result["blockers"])
        self.assertAlmostEqual(result["metrics"]["net_cash"], 43.775 / 3)

    def test_cash_claim_and_missing_remaining_values_fail(self):
        data = fixture()
        data[0]["claimed_net_cash"] = 10000
        self.assertBlocked(data, "CLAIMED_NET_RECONCILIATION")
        data = fixture()
        data[1][1]["remaining_qty_after"] = None
        self.assertBlocked(data, "REMAINING_AFTER_MISSING")

    def test_append_restart_noop_conflict_and_tampered_chain(self):
        result = run_fixture(fixture())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            ledger = evidence.EvidenceLedger(path)
            self.assertEqual(ledger.append(result), "APPENDED")
            before = path.read_bytes()
            self.assertEqual(evidence.EvidenceLedger(path).append(result), "NOOP")
            self.assertEqual(before, path.read_bytes())
            changed = copy.deepcopy(result)
            changed["metrics"]["net_cash"] = 999
            changed = evidence.seal(changed)
            with self.assertRaisesRegex(evidence.EvidenceError, "RECOMPUTATION_PARITY"):
                ledger.append(changed)
            event = json.loads(path.read_text())
            event["seq"] = 2
            path.write_text(json.dumps(evidence.seal(event)) + "\n")
            with self.assertRaisesRegex(evidence.EvidenceError, "LEDGER_CHAIN"):
                ledger.records()

    def test_closed_credit_cannot_be_repeated_at_later_asof(self):
        data = list(fixture())
        result = run_fixture(data)
        data[-1] += 1000
        later = run_fixture(data)
        with tempfile.TemporaryDirectory() as directory:
            ledger = evidence.EvidenceLedger(Path(directory) / "ledger.jsonl")
            ledger.append(result)
            with self.assertRaisesRegex(evidence.EvidenceError, "LEDGER_CLOSE_CONFLICT"):
                ledger.append(later)

    def test_late_actual_components_can_complete_previously_blocked_close_once(self):
        data = list(fixture())
        missing = list(data)
        missing[2] = None
        blocked = run_fixture(missing)
        self.assertEqual(blocked["formal_fresh_T"], 0)
        data[-1] += 1000
        complete = run_fixture(data)
        self.assertEqual(complete["formal_fresh_T"], 1)
        with tempfile.TemporaryDirectory() as directory:
            ledger = evidence.EvidenceLedger(Path(directory) / "ledger.jsonl")
            ledger.append(blocked)
            ledger.append(complete)
            self.assertEqual(sum(r["payload"]["formal_fresh_T"] for r in ledger.records()), 1)

    def test_resealed_zero_fee_is_not_the_frozen_cost_authority(self):
        data = fixture()
        for leg in data[1]:
            authority = leg["fee_authority"]
            leg["fee_authority"] = evidence.seal({**authority, "raw": {"taker_fee_bps": 0}})
            leg["fee_cash"] = 0
        self.assertBlocked(data, "FEE_FROZEN_AUTHORITY_PARITY")

    def test_path_extrema_witness_and_endpoint_unknowns_are_explicit(self):
        result = run_fixture(fixture())
        audit = result["path_audit"]
        self.assertEqual(audit["extrema_order"], "SAME_BAR_ORDER_UNKNOWN")
        self.assertFalse(audit["within_bar_extrema_order_observed"])
        self.assertEqual(audit["MFE_witness_bar_ms"], [B + 600_000, B + 900_000])
        self.assertEqual(audit["entry_partial_interval_excluded_ms"], [B + 300_002, B + 600_000])
        self.assertEqual(audit["exit_partial_interval_excluded_ms"], [B + 1_800_000, B + 1_800_002])

    def test_concurrent_same_record_writes_exactly_once(self):
        result = run_fixture(fixture())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            with ThreadPoolExecutor(max_workers=4) as pool:
                outputs = list(pool.map(lambda _: evidence.EvidenceLedger(path).append(result), range(8)))
            self.assertEqual(outputs.count("APPENDED"), 1)
            self.assertEqual(outputs.count("NOOP"), 7)
            self.assertEqual(len(evidence.EvidenceLedger(path).records()), 1)

    def test_renaming_lot_and_campaign_cannot_credit_same_source_signal_twice(self):
        data = fixture()
        result = run_fixture(data)
        for row in [data[0], *data[1]]:
            row["lot_id"], row["campaign_id"], row["root_lot_id"] = "renamed-lot", "renamed-campaign", "renamed-lot"
        renamed = run_fixture(data)
        self.assertEqual(renamed["formal_fresh_T"], 1)
        with tempfile.TemporaryDirectory() as directory:
            ledger = evidence.EvidenceLedger(Path(directory) / "ledger.jsonl")
            ledger.append(result)
            with self.assertRaisesRegex(evidence.EvidenceError, "LEDGER_SIGNAL_CREDIT_CONFLICT"):
                ledger.append(renamed)


if __name__ == "__main__":
    unittest.main()
