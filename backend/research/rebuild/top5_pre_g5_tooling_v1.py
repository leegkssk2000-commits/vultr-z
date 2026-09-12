#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "zel.top5.pre_g5.tooling.v1"
ATTRIBUTION_CATEGORIES = {
    "ENTRY_QUALITY",
    "REGIME",
    "LOSS_TAIL",
    "WINNER_DAMAGE",
    "OCCUPANCY",
    "SYMBOL_CONCENTRATION",
    "EVENT_CONCENTRATION",
    "COST_SENSITIVITY",
    "EXIT_LIFECYCLE",
    "SOURCE_OR_EXECUTION_INTEGRITY",
}


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _float(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"MISSING_OR_INVALID_{key.upper()}")
    return float(value)


def preregister_accelerator(
    *,
    lane: str,
    official_boundary_ms: int,
    accelerator_boundary_ms: int,
    ranked_snapshot: list[dict[str, Any]],
    snapshot_observed_ms: int,
    top_n: int = 12,
) -> dict[str, Any]:
    """Create an outcome-blind, isolated accelerator cohort contract.

    This never changes the official cohort. The caller supplies a pre-outcome
    liquidity snapshot; only symbol and quote_volume are admissible selectors.
    """
    if accelerator_boundary_ms <= official_boundary_ms:
        raise ValueError("ACCELERATOR_BOUNDARY_MUST_BE_LATER")
    if snapshot_observed_ms >= accelerator_boundary_ms:
        raise ValueError("LIQUIDITY_SNAPSHOT_MUST_PRECEDE_BOUNDARY")
    if top_n < 1:
        raise ValueError("TOP_N_MUST_BE_POSITIVE")
    forbidden = {"pnl", "net", "return", "wr", "win_rate", "pf", "payoff", "expectancy"}
    clean: list[tuple[str, float]] = []
    seen: set[str] = set()
    for row in ranked_snapshot:
        if forbidden.intersection(row):
            raise ValueError("OUTCOME_FIELD_FORBIDDEN_IN_UNIVERSE_SELECTION")
        symbol = row.get("symbol")
        qv = row.get("quote_volume")
        if not isinstance(symbol, str) or not symbol.endswith("-USDT"):
            raise ValueError("INVALID_USDT_PERPETUAL_SYMBOL")
        if symbol in seen:
            raise ValueError("DUPLICATE_SYMBOL_IN_LIQUIDITY_SNAPSHOT")
        if isinstance(qv, bool) or not isinstance(qv, (int, float)) or float(qv) < 0 or not math.isfinite(float(qv)):
            raise ValueError("INVALID_QUOTE_VOLUME")
        seen.add(symbol)
        clean.append((symbol, float(qv)))
    clean.sort(key=lambda x: (-x[1], x[0]))
    selected = [s for s, _ in clean[:top_n]]
    if not selected:
        raise ValueError("EMPTY_ACCELERATOR_UNIVERSE")
    core = {
        "schema": SCHEMA,
        "kind": "ACCELERATOR_PREREGISTRATION",
        "lane": lane,
        "selection_method": "top_crypto_usdt_perpetuals_by_preoutcome_24h_quote_volume",
        "snapshot_observed_ms": snapshot_observed_ms,
        "official_boundary_ms": official_boundary_ms,
        "accelerator_boundary_ms": accelerator_boundary_ms,
        "symbols": selected,
        "top_n": top_n,
        "formal_credit_isolated": True,
        "merge_into_official_cohort": False,
        "historical_backfill": False,
        "post_result_symbol_exception": False,
        "official_cohort_mutated": False,
    }
    return {**core, "contract_sha256": sha256_json(core)}


def _drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for x in values:
        equity += x
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _concentration(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    by: dict[str, float] = defaultdict(float)
    for row in rows:
        key = str(row.get(field, "UNKNOWN"))
        by[key] += _float(row, "net_bps")
    positive_total = sum(v for v in by.values() if v > 0)
    top_key, top_value = (None, 0.0)
    if by:
        top_key, top_value = max(by.items(), key=lambda kv: abs(kv[1]))
    return {
        "contribution_bps": dict(sorted(by.items())),
        "top_abs_contributor": top_key,
        "top_abs_contribution_bps": top_value,
        "positive_contribution_concentration_pct": (100.0 * max((v for v in by.values() if v > 0), default=0.0) / positive_total) if positive_total > 0 else None,
    }


def closed_t_accounting(
    rows: list[dict[str, Any]],
    *,
    threshold_authority: str | None,
    parent_digest: str,
    rule_digest: str,
    source_digest: str,
    cost_digest: str,
) -> dict[str, Any]:
    """Deterministic no-credit accounting for finalized CLOSED T only."""
    if not rows:
        return {
            "schema": "zel.top5.g5a.fresh_accounting.v1",
            "state": "WAIT_NEW_T",
            "formal_credit_granted": False,
            "terminal_pass": False,
            "rows_T": 0,
        }
    ordered = sorted(rows, key=lambda r: (int(r.get("exit_ts", -1)), str(r.get("trade_id", ""))))
    ids: set[str] = set()
    nets: list[float] = []
    cost2: list[float] = []
    losses: list[float] = []
    exposure_symbol_days = 0.0
    for row in ordered:
        if row.get("status") != "CLOSED" or row.get("censored") is True or row.get("unknown_exit") is True:
            raise ValueError("ACCOUNTING_REQUIRES_FINALIZED_CLOSED_ROWS")
        trade_id = row.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id or trade_id in ids:
            raise ValueError("DUPLICATE_OR_MISSING_TRADE_ID")
        ids.add(trade_id)
        net = _float(row, "net_bps")
        nets.append(net)
        if row.get("cost2_net_bps") is not None:
            c2 = _float(row, "cost2_net_bps")
        else:
            gross = _float(row, "gross_bps")
            cost = _float(row, "cost_bps")
            c2 = gross - 2.0 * cost
        cost2.append(c2)
        if net < 0:
            losses.append(net)
        if row.get("exposure_symbol_days") is not None:
            exposure_symbol_days += _float(row, "exposure_symbol_days")
    wins = [x for x in nets if x > 0]
    losing = [x for x in nets if x < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losing)
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else None)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss_abs = (-sum(losing) / len(losing)) if losing else None
    payoff = (avg_win / avg_loss_abs) if avg_win is not None and avg_loss_abs and avg_loss_abs > 0 else None
    sorted_losses = sorted(losses)
    tail_n = max(1, math.ceil(len(sorted_losses) * 0.10)) if sorted_losses else 0
    loss_tail = {
        "worst_loss_bps": sorted_losses[0] if sorted_losses else None,
        "bottom10_mean_bps": (sum(sorted_losses[:tail_n]) / tail_n) if tail_n else None,
        "loss_count": len(sorted_losses),
    }
    core = {
        "rows_T": len(ordered),
        "win_T": len(wins),
        "loss_T": len(losing),
        "wr_pct": 100.0 * len(wins) / len(ordered),
        "net_bps": sum(nets),
        "expectancy_bps_per_T": sum(nets) / len(ordered),
        "pf": pf,
        "payoff": payoff,
        "cost2_net_bps": sum(cost2),
        "marked_dd_bps": _drawdown(nets),
        "loss_tail": loss_tail,
        "exposure_symbol_days": exposure_symbol_days,
        "symbol_concentration": _concentration(ordered, "symbol"),
        "regime_concentration": _concentration(ordered, "regime"),
        "parent_digest": parent_digest,
        "rule_digest": rule_digest,
        "source_digest": source_digest,
        "cost_digest": cost_digest,
        "rows_digest": sha256_json(ordered),
    }
    state = "ACCOUNTED_WAIT_AUTHORITY" if not threshold_authority else "ACCOUNTED_NO_AUTOMATIC_PASS"
    return {
        "schema": "zel.top5.g5a.fresh_accounting.v1",
        "state": state,
        "threshold_authority": threshold_authority,
        "formal_credit_granted": False,
        "terminal_pass": False,
        **core,
        "accounting_digest": sha256_json(core),
    }


def g5b_successor_template(
    *,
    lane: str,
    g5a_terminal_pass: bool,
    g5a_terminal_observed_ms: int,
    g5b_boundary_ms: int,
    parent_digest: str,
    rule_digest: str,
    source_digest: str,
    cost_digest: str,
) -> dict[str, Any]:
    if not g5a_terminal_pass:
        raise ValueError("G5B_FORBIDDEN_WITHOUT_EXPLICIT_G5A_TERMINAL_PASS")
    if g5b_boundary_ms <= g5a_terminal_observed_ms:
        raise ValueError("G5B_BOUNDARY_MUST_BE_LATER_THAN_G5A_TERMINAL_OBSERVATION")
    core = {
        "schema": "zel.top5.g5b.successor_template.v1",
        "lane": lane,
        "g5b_boundary_ms": g5b_boundary_ms,
        "parent_digest": parent_digest,
        "rule_digest": rule_digest,
        "source_digest": source_digest,
        "cost_digest": cost_digest,
        "historical_backfill": False,
        "reuse_g5a_credit": False,
        "formal_credit": 0,
        "selection_mutation": False,
        "state": "G5B_TEMPLATE_PREREGISTERED_WAIT_FUTURE",
    }
    return {**core, "template_digest": sha256_json(core)}


def fail_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize already-tagged diagnostics; never emits a candidate or rule."""
    totals: dict[str, dict[str, float | int]] = {k: {"rows": 0, "net_bps": 0.0} for k in sorted(ATTRIBUTION_CATEGORIES)}
    untagged = 0
    for row in rows:
        tags = row.get("diagnostic_tags") or []
        if not isinstance(tags, list):
            raise ValueError("DIAGNOSTIC_TAGS_MUST_BE_LIST")
        clean = set(tags)
        if not clean:
            untagged += 1
        if not clean.issubset(ATTRIBUTION_CATEGORIES):
            raise ValueError("UNKNOWN_FAIL_ATTRIBUTION_CATEGORY")
        net = _float(row, "net_bps")
        for tag in clean:
            totals[tag]["rows"] = int(totals[tag]["rows"]) + 1
            totals[tag]["net_bps"] = float(totals[tag]["net_bps"]) + net
    core = {
        "schema": "zel.top5.g5a.fail_attribution.v1",
        "diagnostic_only": True,
        "fresh_rows_may_select_candidate": False,
        "candidate": None,
        "categories": totals,
        "untagged_rows": untagged,
        "rows_digest": sha256_json(rows),
    }
    return {**core, "attribution_digest": sha256_json(core)}


def collector_integrity(
    *,
    rows: list[dict[str, Any]],
    cursor_ms: int | None,
    now_ms: int,
    stale_after_ms: int,
    expected_parent_digest: str,
    expected_rule_digest: str,
    expected_source_digest: str,
    expected_cost_digest: str,
    state_parent_digest: str | None,
    state_rule_digest: str | None,
    state_source_digest: str | None,
    state_cost_digest: str | None,
    expected_bar_interval_ms: int | None = None,
    observed_bar_open_ms: list[int] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    ids = [r.get("trade_id") for r in rows]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        blockers.append("DUPLICATE_OR_MISSING_TRADE_ID")
    if cursor_ms is None or now_ms - cursor_ms > stale_after_ms:
        blockers.append("STALE_CURSOR")
    expected = {
        "parent": expected_parent_digest,
        "rule": expected_rule_digest,
        "source": expected_source_digest,
        "cost": expected_cost_digest,
    }
    actual = {
        "parent": state_parent_digest,
        "rule": state_rule_digest,
        "source": state_source_digest,
        "cost": state_cost_digest,
    }
    for key in expected:
        if not actual[key] or actual[key] != expected[key]:
            blockers.append(f"{key.upper()}_DIGEST_DRIFT")
    if any(r.get("unknown_exit") is True for r in rows):
        blockers.append("UNKNOWN_EXIT")
    if any(r.get("status") != "CLOSED" or r.get("censored") is True for r in rows):
        blockers.append("OPEN_OR_CENSORED_ROWS")
    gaps: list[tuple[int, int]] = []
    if expected_bar_interval_ms and observed_bar_open_ms:
        bars = sorted(set(int(x) for x in observed_bar_open_ms))
        for a, b in zip(bars, bars[1:]):
            if b - a != expected_bar_interval_ms:
                gaps.append((a, b))
        if gaps:
            blockers.append("SOURCE_BAR_GAP")
    return {
        "schema": "zel.top5.g5a.collector_integrity.v1",
        "state": "PASS" if not blockers else "BLOCKED",
        "blockers": sorted(set(blockers)),
        "gap_pairs": gaps,
        "synthetic_repair": False,
        "backfill": False,
        "formal_credit_mutated": False,
        "rows_digest": sha256_json(rows),
    }


def _self_test() -> None:
    snap = [
        {"symbol": "BTC-USDT", "quote_volume": 100.0},
        {"symbol": "ETH-USDT", "quote_volume": 90.0},
        {"symbol": "SOL-USDT", "quote_volume": 80.0},
    ]
    acc = preregister_accelerator(
        lane="TrendRider Unified",
        official_boundary_ms=100,
        accelerator_boundary_ms=300,
        ranked_snapshot=snap,
        snapshot_observed_ms=200,
        top_n=3,
    )
    assert acc["symbols"] == ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
    rows = [
        {"trade_id": "a", "status": "CLOSED", "symbol": "BTC-USDT", "regime": "r1", "exit_ts": 1, "gross_bps": 100.0, "cost_bps": 10.0, "net_bps": 90.0, "exposure_symbol_days": 1.0},
        {"trade_id": "b", "status": "CLOSED", "symbol": "ETH-USDT", "regime": "r2", "exit_ts": 2, "gross_bps": -40.0, "cost_bps": 10.0, "net_bps": -50.0, "exposure_symbol_days": 2.0},
    ]
    acct = closed_t_accounting(rows, threshold_authority=None, parent_digest="p", rule_digest="r", source_digest="s", cost_digest="c")
    assert acct["net_bps"] == 40.0 and acct["cost2_net_bps"] == 20.0
    assert acct["state"] == "ACCOUNTED_WAIT_AUTHORITY" and acct["terminal_pass"] is False
    try:
        g5b_successor_template(lane="x", g5a_terminal_pass=False, g5a_terminal_observed_ms=1, g5b_boundary_ms=2, parent_digest="p", rule_digest="r", source_digest="s", cost_digest="c")
        raise AssertionError("G5B fail-closed guard missing")
    except ValueError as exc:
        assert "G5B_FORBIDDEN" in str(exc)
    attr = fail_attribution([{**rows[1], "diagnostic_tags": ["LOSS_TAIL", "REGIME"]}])
    assert attr["candidate"] is None and attr["diagnostic_only"] is True
    integ = collector_integrity(rows=rows, cursor_ms=10, now_ms=20, stale_after_ms=100, expected_parent_digest="p", expected_rule_digest="r", expected_source_digest="s", expected_cost_digest="c", state_parent_digest="p", state_rule_digest="r", state_source_digest="s", state_cost_digest="c")
    assert integ["state"] == "PASS"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        _self_test()
        print("PASS_TOP5_PRE_G5_TOOLING_V1")
        return 0
    print(json.dumps({"schema": SCHEMA, "state": "LIBRARY_ONLY_NO_FORMAL_CREDIT"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
