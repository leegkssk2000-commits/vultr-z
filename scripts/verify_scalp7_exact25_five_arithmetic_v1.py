#!/usr/bin/env python3
"""Independently check saved exact25 result arithmetic; never run a strategy.

Only standard-library JSON/Decimal operations are used. Recorded fill ledger and
recorded price snapshots are the inputs. Unknown funding remains unknown.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

D = Decimal
ZERO = D(0)
EPS = D("1e-12")


def number(value):
    result = D(str(value))
    if not result.is_finite():
        raise ValueError("NONFINITE_NUMBER")
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Audit:
    def __init__(self):
        self.checks = 0
        self.error_count = 0
        self.errors = []

    def equal(self, label, actual, expected):
        self.checks += 1
        if actual is None or expected is None:
            valid = actual is expected
        elif isinstance(expected, bool) or isinstance(expected, str):
            valid = actual == expected
        elif isinstance(expected, (int, float, Decimal)):
            try:
                a, b = number(actual), number(expected)
                valid = abs(a - b) <= D("0.00000001") + abs(b) * D("0.0000000001")
            except (ValueError, TypeError, ArithmeticError):
                valid = False
        else:
            valid = actual == expected
        if not valid:
            self.error_count += 1
            if len(self.errors) < 80:
                self.errors.append(
                    {"field": label, "saved": actual, "recomputed": expected}
                )


def rebuild_episodes(ledger, multiplier):
    """Inventory accounting, with remaining-cost basis for each closing fill."""
    episodes = {}
    seen = set()
    previous = -1
    for row in ledger:
        if row["type"] != "FILL":
            raise ValueError("UNSUPPORTED_NON_FILL_LEDGER_EVENT")
        event = row["fill_id"]
        stamp = row["ts_ms"]
        if event in seen or stamp < previous or row["available_ts_ms"] < stamp:
            raise ValueError("DUPLICATE_OR_NONCAUSAL_LEDGER")
        seen.add(event)
        previous = stamp
        q, p, fee = (number(row[k]) for k in ("qty_base", "fill_price", "fee_usdt"))
        if q <= 0 or p <= 0 or fee < 0 or row["side"] not in (-1, 1):
            raise ValueError("INVALID_FILL")
        ep = row["position_episode_id"]
        if row["effect"] == "OPEN":
            if ep not in episodes:
                episodes[ep] = {
                    "episode_id": ep,
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "entry_ts_ms": stamp,
                    "quantity": ZERO,
                    "entry_value": ZERO,
                    "remaining": ZERO,
                    "basis_remaining": ZERO,
                    "gross_usdt": ZERO,
                    "cost_usdt": ZERO,
                    "closed": False,
                }
            item = episodes[ep]
            if item["closed"]:
                raise ValueError("CLOSED_EPISODE_REOPENED")
            item["quantity"] += q
            item["entry_value"] += q * p
            item["remaining"] += q
            item["basis_remaining"] += q * p
        elif row["effect"] == "CLOSE":
            item = episodes[ep]
            if q > item["remaining"] + EPS:
                raise ValueError("OVERCLOSE")
            cost_basis = item["basis_remaining"] / item["remaining"]
            item["gross_usdt"] += number(item["side"]) * q * (p - cost_basis)
            item["remaining"] -= q
            item["basis_remaining"] -= q * cost_basis
            if abs(item["remaining"]) < EPS:
                item["closed"] = True
                item["outcome_available_ts_ms"] = row["available_ts_ms"]
                item["exit_ts_ms"] = stamp
        else:
            raise ValueError("INVALID_FILL_EFFECT")
        if item["symbol"] != row["symbol"] or item["side"] != row["side"]:
            raise ValueError("EPISODE_BINDING_CHANGED")
        item["cost_usdt"] += fee * multiplier
        item["net_reference_usdt"] = item["gross_usdt"] - item["cost_usdt"]
    return list(episodes.values())


def cohort_stats(items):
    ordered = sorted(items, key=lambda x: x["outcome_available_ts_ms"])
    nets = [e["net_reference_usdt"] for e in ordered]
    gains = sum((n for n in nets if n > 0), ZERO)
    losses = -sum((n for n in nets if n < 0), ZERO)
    streak = maximum = 0
    for n in nets:
        streak = streak + 1 if n < 0 else 0
        maximum = max(maximum, streak)
    total = sum(nets, ZERO)
    return {
        "T_resolved": len(nets),
        "WR_resolved_pct": (
            D(100) * sum(n > 0 for n in nets) / len(nets) if nets else None
        ),
        "gross_resolved_usdt": sum((e["gross_usdt"] for e in ordered), ZERO),
        "cost_resolved_reference_usdt": sum((e["cost_usdt"] for e in ordered), ZERO),
        "net_resolved_reference_usdt": total,
        "net_per_trade_resolved_reference_usdt": total / len(nets) if nets else None,
        "PF_resolved_reference": gains / losses if losses else None,
        "PF_no_losses": bool(nets) and losses == 0,
        "MaxLS_resolved": maximum if nets else None,
    }


def rebuild_account(saved, ledger, initial_cash, multiplier, check):
    if saved is None:
        return []
    snapshots = saved["snapshots"]
    curve_saved = saved["valuation"]["curve"]
    check.equal("account.snapshot_curve_length", len(curve_saved), len(snapshots))
    positions = {}
    cursor = 0
    realized = fees = ZERO
    initial = number(initial_cash)
    peak = initial
    max_dd = ZERO
    curve = []
    previous = -1
    for idx, sample in enumerate(snapshots):
        stamp = sample["ts_ms"]
        if stamp <= previous:
            raise ValueError("UNSORTED_ACCOUNT_SNAPSHOTS")
        previous = stamp
        while cursor < len(ledger) and ledger[cursor]["ts_ms"] <= stamp:
            row = ledger[cursor]
            cursor += 1
            ep = row["position_episode_id"]
            q, price = number(row["qty_base"]), number(row["fill_price"])
            fees += number(row["fee_usdt"]) * multiplier
            if row["effect"] == "OPEN":
                pos = positions.setdefault(
                    ep,
                    {
                        "symbol": row["symbol"],
                        "side": row["side"],
                        "quantity": ZERO,
                        "basis": ZERO,
                    },
                )
                pos["quantity"] += q
                pos["basis"] += q * price
            else:
                pos = positions[ep]
                entry = pos["basis"] / pos["quantity"]
                realized += number(pos["side"]) * q * (price - entry)
                pos["quantity"] -= q
                pos["basis"] -= q * entry
                if abs(pos["quantity"]) < EPS:
                    del positions[ep]
        prefix = f"account.snapshot[{idx}]"
        check.equal(prefix + ".realized", sample["realized_gross_cum_usdt"], realized)
        check.equal(prefix + ".fees", sample["fees_cum_usdt"], fees)
        # Zero is only the model bookkeeping field, never actual funding evidence.
        check.equal(
            prefix + ".model_funding_placeholder",
            sample["funding_received_cum_usdt"],
            ZERO,
        )
        check.equal(prefix + ".external_flow", sample["external_flow_usdt"], ZERO)
        saved_positions = {p["position_episode_id"]: p for p in sample["positions"]}
        check.equal(
            prefix + ".position_ids", sorted(saved_positions), sorted(positions)
        )
        unrealized = ZERO
        for ep, pos in positions.items():
            stored = saved_positions.get(ep, {})
            check.equal(
                prefix + "." + ep + ".symbol", stored.get("symbol"), pos["symbol"]
            )
            check.equal(prefix + "." + ep + ".side", stored.get("side"), pos["side"])
            check.equal(
                prefix + "." + ep + ".quantity",
                stored.get("remaining_qty_base"),
                pos["quantity"],
            )
            average = pos["basis"] / pos["quantity"]
            check.equal(
                prefix + "." + ep + ".entry_price",
                stored.get("avg_entry_price"),
                average,
            )
            quote = sample["prices"][pos["symbol"]]
            if quote["ts_ms"] != stamp or quote["price_basis"] != "LAST_PRICE":
                raise ValueError("UNSYNCHRONIZED_OR_WRONG_PRICE_BASIS")
            unrealized += (
                number(pos["side"])
                * pos["quantity"]
                * (number(quote["price"]) - average)
            )
        cash = initial + realized - fees
        equity = cash + unrealized
        peak = max(peak, equity)
        dd = D(100) * (peak - equity) / peak
        max_dd = max(max_dd, dd)
        expected = {
            "ts_ms": stamp,
            "cash_usdt": cash,
            "unrealized_usdt": unrealized,
            "equity_usdt": equity,
            "peak_equity_usdt": peak,
            "drawdown_pct": dd,
        }
        if idx < len(curve_saved):
            for key, value in expected.items():
                check.equal(
                    f"account.curve[{idx}].{key}", curve_saved[idx].get(key), value
                )
        curve.append(expected)
    check.equal(
        "account.max_drawdown_pct", saved["valuation"]["max_drawdown_pct"], max_dd
    )
    check.equal(
        "account.initial_cash", saved["valuation"]["initial_cash_usdt"], initial
    )
    return curve


def audit_result(result, binding):
    check = Audit()
    check.equal("identity", result.get("identity_key"), binding["identity_key"])
    check.equal(
        "binding_sha256", result.get("binding_sha256"), binding["binding_sha256"]
    )
    check.equal(
        "full_execution_performed", result.get("full_execution_performed"), True
    )
    check.equal("data_kind", result.get("data_kind"), "GENUINE_RAW_HISTORY")
    check.equal("fresh_T", result.get("fresh_T"), 0)
    ledger = result["execution"]["ledger"]
    unknown = [
        e
        for e in result["execution"]["executions"]
        if e.get("state", e.get("status")) == "UNRESOLVED"
        or e.get("unresolved") is True
    ]
    check.equal(
        "unknown_execution_count", result.get("unknown_execution_count"), len(unknown)
    )
    scenarios = {}
    for multiplier in (1, 2):
        label = f"{multiplier}x"
        saved = result["cost_scenarios"][label]
        episodes = rebuild_episodes(ledger, multiplier)
        saved_ep = {e["episode_id"]: e for e in saved["episodes"]}
        check.equal(
            label + ".episode_ids",
            sorted(saved_ep),
            sorted(e["episode_id"] for e in episodes),
        )
        for episode in episodes:
            for key, value in episode.items():
                if key != "basis_remaining":
                    check.equal(
                        f"{label}.episode.{episode['episode_id']}.{key}",
                        saved_ep.get(episode["episode_id"], {}).get(key),
                        value,
                    )
        curve = rebuild_account(
            saved["account"], ledger, binding["initial_cash_usdt"], multiplier, check
        )
        cutoff = min(
            (e.get("unresolved_observed_ts_ms", 0) for e in unknown), default=2**63 - 1
        )
        check.equal(
            label + ".account_before_unknown",
            all(r["ts_ms"] < cutoff for r in curve),
            True,
        )
        windows_expected = [
            w for w in binding["windows"] if w["kind"] not in {"TRAIN", "CONTEXT"}
        ]
        check.equal(
            label + ".window_count", len(saved["windows"]), len(windows_expected)
        )
        windows_out = []
        for index, window in enumerate(windows_expected):
            start, end = window["start_ts_ms"], window["end_ts_ms"]
            cohort = [
                e
                for e in episodes
                if start <= e["entry_ts_ms"] < end
                and e["closed"]
                and e["outcome_available_ts_ms"] < end
            ]
            crossing = [
                e
                for e in episodes
                if start <= e["entry_ts_ms"] < end
                and (not e["closed"] or e["outcome_available_ts_ms"] >= end)
            ]
            carried = [
                e
                for e in episodes
                if e["entry_ts_ms"] < start
                and (not e["closed"] or e["outcome_available_ts_ms"] >= start)
            ]
            affected = [e for e in unknown if e.get("unresolved_from_ts_ms", 0) < end]
            complete = not (crossing or carried or affected)
            metrics = cohort_stats(cohort)
            metrics.update(
                {
                    "T_per_day_resolved": D(len(cohort)) * D(86400000) / D(end - start),
                    "cross_boundary_or_open_count": len(crossing),
                    "carry_in_count": len(carried),
                    "complete_window": complete,
                    "net_complete_reference_usdt": (
                        metrics["net_resolved_reference_usdt"] if complete else None
                    ),
                    "actual_historical_net_usdt": None,
                    "DD_pct": None,
                    "funding_status": "UNKNOWN_NOT_ZERO",
                }
            )
            samples = [p for p in curve if start <= p["ts_ms"] < end]
            if complete and samples:
                prior = [p for p in curve if p["ts_ms"] < start]
                peak = (
                    prior[-1]["equity_usdt"]
                    if prior
                    else number(binding["initial_cash_usdt"])
                )
                dd = ZERO
                for sample in samples:
                    peak = max(peak, sample["equity_usdt"])
                    if peak > 0:
                        dd = max(dd, D(100) * (peak - sample["equity_usdt"]) / peak)
                metrics["DD_pct"] = dd
            stored = saved["windows"][index] if index < len(saved["windows"]) else {}
            for key, value in {**window, **metrics}.items():
                if key != "cost_resolved_reference_usdt":
                    check.equal(
                        f"{label}.window.{window['name']}.{key}", stored.get(key), value
                    )
            windows_out.append(
                {**window, **metrics, "unknown_affected_count": len(affected)}
            )
        closed = [e for e in episodes if e["closed"]]
        summary = cohort_stats(closed)
        summary["open_episode_count"] = len(episodes) - len(closed)
        summary["unknown_execution_count"] = len(unknown)
        summary["all_fill_cost_reference_usdt"] = sum(
            (number(r["fee_usdt"]) * multiplier for r in ledger), ZERO
        )
        summary["complete_batch_net_reference_usdt"] = (
            summary["net_resolved_reference_usdt"]
            if not unknown and len(closed) == len(episodes)
            else None
        )
        summary["actual_historical_net_usdt"] = None
        scenarios[label] = {
            "windows": windows_out,
            "all_closed_episodes": summary,
            "sampled_account_max_dd_pct": max(
                (p["drawdown_pct"] for p in curve), default=None
            ),
        }
    a1, a2 = (result["cost_scenarios"][k]["account"] for k in ("1x", "2x"))
    if a1 is not None and a2 is not None:
        marks1 = [(s["ts_ms"], s["prices"]) for s in a1["snapshots"]]
        marks2 = [(s["ts_ms"], s["prices"]) for s in a2["snapshots"]]
        check.equal("cost2x.identical_snapshot_marks", marks2, marks1)
    return {
        "schema": "g4.exact25.independent_saved_arithmetic.v1",
        "status": "PASS" if check.error_count == 0 else "FAIL",
        "identity_key": result.get("identity_key"),
        "binding_sha256": binding["binding_sha256"],
        "check_count": check.checks,
        "error_count": check.error_count,
        "errors": check.errors,
        "ledger_rows": len(ledger),
        "cost_scenarios": scenarios,
        "new_economic_executions": 0,
        "model_or_loader_imported": False,
        "funding_status": "UNKNOWN_NOT_ZERO",
        "limits": [
            "Saved ledger and saved prices only; not an independent market replay.",
            "DD is sampled last-price reference NAV, not intrabar or liquidation DD.",
            "Complete metrics stay null for open/carry/unknown-affected windows.",
            "Actual historical account Net is unknown because funding is excluded.",
        ],
    }


def serial(value):
    if isinstance(value, Decimal):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("NONFINITE_OUTPUT")
        return result
    raise TypeError(type(value).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not {"audit", "audits"}.intersection(args.output.parts):
        parser.error("--output must be inside an audit or audits directory")
    stored_bytes = args.result.read_bytes()
    raw_bytes = (
        gzip.decompress(stored_bytes) if args.result.suffix == ".gz" else stored_bytes
    )
    result = json.loads(raw_bytes)
    binding = json.loads(args.freeze.read_text())
    report = audit_result(result, binding)
    report["inputs"] = {
        "result_path": str(args.result.resolve()),
        "result_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "result_storage_sha256": hashlib.sha256(stored_bytes).hexdigest(),
        "freeze_path": str(args.freeze.resolve()),
        "freeze_sha256": sha(args.freeze),
        "verifier_sha256": sha(__file__),
    }
    payload = (
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=serial,
        )
        + "\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        if args.output.read_text() != payload:
            raise FileExistsError("AUDIT_EXISTS_WITH_DIFFERENT_CONTENT")
    else:
        with args.output.open("x") as stream:
            stream.write(payload)
    print(
        json.dumps(
            {
                "status": report["status"],
                "checks": report["check_count"],
                "errors": report["error_count"],
                "output": str(args.output),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
