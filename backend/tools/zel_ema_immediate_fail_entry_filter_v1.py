from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import zel_grid_entry_regime_fork_v1 as grid

VERSION = "ZEL_EMA_IMMEDIATE_FAIL_ENTRY_FILTER_V1"
SCHEMA = "zel.ema.immediate_fail_entry_filter.receipt.v1"
STRATEGY_ID = "ema_ribbon_scalp"
EXPECTED_TRADES = 424
EXPECTED_TERMINAL_SHA256 = "62a7d51a02b75ebfee5765d81d955d583d442c995604bb9d4a8a5e7e7a4e2fe3"
EXPECTED_ENGINE_SHA256 = "14fc2600f3ca0dae4bf17e9768461661cf07ef7f1aa5934c317baac95b52fc50"
CONTEXT_PATH = Path("/home/z/z/tools/q4r3_exact25_market_context_collector.py")
CONTEXT_SHA256 = "408ee3edf3899ad626e25f01be19d447af16d4a033996fb5d2c76a516efe82ca"
DERIVE_PATH = Path("/home/z/z/tools/q4r3_exact25_preentry_method_context_capture.py")
DERIVE_SHA256 = "1ad1cc721a88cef9f8c08a8ed1727736d61ad036495f5b650f798332ad7b684c"
WINDOWS = ("1m_w1", "1m_w2", "1m_w3")
SELECTION_WINDOW = "1m_w1"
MIN_RETENTION_PCT = 60.0
MIN_CONFIRMATION_TRADES = 20


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def entry_side(row: Mapping[str, Any]) -> str:
    return grid.text(row, ("side", "direction"), "missing").lower()


def entry_session(epoch_ns: int) -> str:
    hour = datetime.fromtimestamp(epoch_ns / 1_000_000_000, tz=timezone.utc).hour
    if hour < 6:
        return "utc_00_06"
    if hour < 12:
        return "utc_06_12"
    if hour < 18:
        return "utc_12_18"
    return "utc_18_24"


def immediate_fail(row: Mapping[str, Any]) -> bool:
    realized = grid.number(row, ("realized_R", "net_R", "pnl_r", "net_reference_R"))
    mfe = finite(row.get("MFE_R") or row.get("mfe_R") or row.get("mfe_r"))
    return realized < 0 and mfe is not None and mfe < 0.25


def phenotype(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    failed = [row for row in rows if immediate_fail(row)]
    loss = -sum(
        grid.number(row, ("realized_R", "net_R", "pnl_r", "net_reference_R"))
        for row in failed
    )
    return {
        "trade_count": len(rows),
        "immediate_fail_count": len(failed),
        "immediate_fail_rate_pct": len(failed) / len(rows) * 100.0 if rows else None,
        "immediate_fail_gross_loss_R": loss,
    }


def metric_pass(base: Mapping[str, Any], candidate: Mapping[str, Any], *, minimum_trades: int | None = None) -> tuple[bool, list[str]]:
    change = grid.delta(base, candidate)
    blockers: list[str] = []
    if change["retention_pct"] < MIN_RETENTION_PCT:
        blockers.append("RETENTION_BELOW_MIN")
    if minimum_trades is not None and int(candidate.get("trade_count") or 0) < minimum_trades:
        blockers.append("CONFIRMATION_SAMPLE_LT_MIN")
    if float(change["delta_net_R"]) <= 0:
        blockers.append("NET_R_NOT_IMPROVED")
    if float(change["delta_max_drawdown_R"]) < 0:
        blockers.append("MAX_DD_WORSE")
    if change["delta_profit_factor"] is None or float(change["delta_profit_factor"]) < 0:
        blockers.append("PROFIT_FACTOR_WORSE_OR_UNDEFINED")
    return not blockers, blockers


def evaluate(*, engine_path: Path, terminal_root: Path, data_root: Path) -> dict[str, Any]:
    trades_path = terminal_root / "trades.jsonl.gz"
    source_checks = {
        "terminal_sha_match": grid.file_sha(trades_path) == EXPECTED_TERMINAL_SHA256,
        "engine_sha_match": grid.file_sha(engine_path) == EXPECTED_ENGINE_SHA256,
        "context_sha_match": grid.file_sha(CONTEXT_PATH) == CONTEXT_SHA256,
        "derive_sha_match": grid.file_sha(DERIVE_PATH) == DERIVE_SHA256,
    }
    if not all(source_checks.values()):
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_checks}")

    rows = grid.read_rows(trades_path, STRATEGY_ID)
    if len(rows) != EXPECTED_TRADES:
        raise RuntimeError(f"TRADE_COUNT_MISMATCH:{len(rows)}")

    engine = grid.load_module(engine_path, "zel_ema_immediate_fail_engine")
    context_mod = grid.load_module(CONTEXT_PATH, "zel_ema_immediate_fail_context")
    derive_mod = grid.load_module(DERIVE_PATH, "zel_ema_immediate_fail_derive")
    compute_context = getattr(context_mod, "compute_context", None)
    derive_regime = getattr(derive_mod, "derive_regime", None)
    if not callable(compute_context) or not callable(derive_regime):
        raise RuntimeError("CONTEXT_CALLABLE_MISSING")

    report = json.loads((terminal_root / "report.json").read_text(encoding="utf-8"))
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")
    engine.init_worker(str(Path(source_root_raw)), str(data_root), "1m")
    manifest = engine._WORKER_MANIFEST
    files = list(manifest.get("files") or []) if isinstance(manifest, Mapping) else []
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in files:
        if isinstance(file_row, Mapping):
            file_map[(grid.text(file_row, ("window_id", "window"), "unknown"), grid.text(file_row, ("symbol",)).upper())] = file_row

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(grid.window_id(row), grid.symbol(row))].append(row)

    features: dict[str, dict[str, str]] = {}
    unmatched: list[str] = []
    duplicate_timestamp_count = 0
    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            unmatched.extend("LANE_FILE_MISSING" for _ in lane_rows)
            continue
        frame = engine.frame_from_csv(grid.resolve_path(data_root, file_row))
        index_by_epoch: dict[int, int] = {}
        duplicate_epochs: set[int] = set()
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch = grid.epoch_ns(engine.pd, value)
            if epoch is None:
                continue
            if epoch in index_by_epoch:
                duplicate_epochs.add(epoch)
            index_by_epoch[epoch] = index
        duplicate_timestamp_count += len(duplicate_epochs)

        for row in lane_rows:
            eid = grid.event_id(row)
            epoch = grid.epoch_ns(engine.pd, row.get("entry_ts") or row.get("entry_time"))
            index = index_by_epoch.get(epoch) if epoch is not None else None
            if index is None or epoch is None:
                unmatched.append("ENTRY_TIMESTAMP_NOT_FOUND")
                continue
            prefix = frame.iloc[max(0, index - int(engine.FRAME_LIMIT) + 1): index + 1].copy()
            if len(prefix) < 14 or grid.epoch_ns(engine.pd, prefix["timestamp"].iloc[-1]) != epoch:
                unmatched.append("ENTRY_PREFIX_INVALID")
                continue
            try:
                context = compute_context(f"{lane[0]}:{lane[1]}", prefix, None, None, None)
                regime = str(derive_regime(context) or "missing")
            except Exception as exc:
                unmatched.append(f"CONTEXT_ERROR:{type(exc).__name__}")
                continue
            if regime not in {"range", "trend_long", "trend_short", "transition"}:
                unmatched.append("REGIME_INVALID")
                continue
            side = entry_side(row)
            if side not in {"long", "short"}:
                unmatched.append("SIDE_INVALID")
                continue
            features[eid] = {
                "entry_regime": regime,
                "side": side,
                "utc_session": entry_session(epoch),
            }

    reconstruction_pass = len(features) == EXPECTED_TRADES and not unmatched and duplicate_timestamp_count == 0
    if not reconstruction_pass:
        return {
            "schema_version": SCHEMA,
            "version": VERSION,
            "state": "HOLD_EMA_IMMEDIATE_FAIL_FEATURE_RECONSTRUCTION_INCOMPLETE",
            "strategy_id": STRATEGY_ID,
            "source_checks": source_checks,
            "trade_count": len(rows),
            "reconstructed_count": len(features),
            "unmatched_count": len(unmatched),
            "unmatched_reason_counts": dict(Counter(unmatched)),
            "duplicate_timestamp_count": duplicate_timestamp_count,
            "selection_authority": False,
            "promotion_authority": False,
            "canonical_mutated": False,
            "runtime_mutated": False,
            "formal_ledger_mutated": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
            "next": "RESOLVE_SINGLE_PREENTRY_FEATURE_BLOCKER",
        }

    by_window = {window: [row for row in rows if grid.window_id(row) == window] for window in WINDOWS}
    baseline_metrics = {window: grid.metrics(by_window[window]) for window in WINDOWS}
    baseline_metrics["all"] = grid.metrics(rows)
    baseline_phenotype = {window: phenotype(by_window[window]) for window in WINDOWS}
    baseline_phenotype["all"] = phenotype(rows)

    selection_rows = by_window[SELECTION_WINDOW]
    atomic_rules: list[tuple[str, str]] = []
    for dimension in ("entry_regime", "side", "utc_session"):
        values = sorted({features[grid.event_id(row)][dimension] for row in selection_rows})
        atomic_rules.extend((dimension, value) for value in values)

    candidates: list[dict[str, Any]] = []
    for dimension, value in atomic_rules:
        kept_by_window: dict[str, list[dict[str, Any]]] = {}
        blocked_by_window: dict[str, list[dict[str, Any]]] = {}
        for window in WINDOWS:
            kept_by_window[window] = [row for row in by_window[window] if features[grid.event_id(row)][dimension] != value]
            blocked_by_window[window] = [row for row in by_window[window] if features[grid.event_id(row)][dimension] == value]
        metrics = {window: grid.metrics(kept_by_window[window]) for window in WINDOWS}
        metrics["all"] = grid.metrics([row for window in WINDOWS for row in kept_by_window[window]])
        deltas = {window: grid.delta(baseline_metrics[window], metrics[window]) for window in (*WINDOWS, "all")}
        w1_pass, w1_blockers = metric_pass(baseline_metrics[SELECTION_WINDOW], metrics[SELECTION_WINDOW])
        candidates.append({
            "candidate_id": f"BLOCK_{dimension.upper()}_{value.upper()}",
            "rule": {"block_dimension": dimension, "block_value": value},
            "w1_pass": w1_pass,
            "w1_blockers": w1_blockers,
            "metrics": metrics,
            "delta": deltas,
            "blocked_phenotype": {window: phenotype(blocked_by_window[window]) for window in WINDOWS},
            "kept_phenotype": {window: phenotype(kept_by_window[window]) for window in WINDOWS},
            "selection_scope": "W1_ONLY",
            "production_applied": False,
        })

    eligible = [row for row in candidates if row["w1_pass"]]
    eligible.sort(key=lambda row: (
        -float(row["delta"][SELECTION_WINDOW]["delta_net_R"]),
        -float(row["delta"][SELECTION_WINDOW]["delta_max_drawdown_R"]),
        -float(row["delta"][SELECTION_WINDOW]["delta_profit_factor"] or -999.0),
        row["candidate_id"],
    ))
    selected = eligible[0] if eligible else None

    confirmation: dict[str, Any] = {}
    holdout_pass = False
    if selected is not None:
        holdout_pass = True
        for window in ("1m_w2", "1m_w3"):
            passed, blockers = metric_pass(
                baseline_metrics[window],
                selected["metrics"][window],
                minimum_trades=MIN_CONFIRMATION_TRADES,
            )
            confirmation[window] = {"pass": passed, "blockers": blockers}
            holdout_pass = holdout_pass and passed
        all_pass, all_blockers = metric_pass(
            baseline_metrics["all"], selected["metrics"]["all"], minimum_trades=MIN_CONFIRMATION_TRADES
        )
        confirmation["all"] = {"pass": all_pass, "blockers": all_blockers}
        holdout_pass = holdout_pass and all_pass

    blockers: list[str] = []
    if selected is None:
        blockers.append("NO_W1_CAUSAL_ENTRY_FILTER_PASS")
    elif not holdout_pass:
        blockers.append("FROZEN_ENTRY_FILTER_FAILED_W2_W3")
    state = "PASS_EMA_IMMEDIATE_FAIL_ENTRY_FILTER_READY" if not blockers else "HOLD_EMA_IMMEDIATE_FAIL_ENTRY_FILTER_REJECTED"

    candidates.sort(key=lambda row: (
        not row["w1_pass"],
        -float(row["delta"][SELECTION_WINDOW]["delta_net_R"]),
        row["candidate_id"],
    ))
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": STRATEGY_ID,
        "source_checks": source_checks,
        "trade_count": len(rows),
        "terminal_event_id_set_sha256": grid.stable_sha(sorted(grid.event_id(row) for row in rows)),
        "reconstructed_count": len(features),
        "duplicate_timestamp_count": duplicate_timestamp_count,
        "baseline_metrics": baseline_metrics,
        "baseline_immediate_fail_phenotype": baseline_phenotype,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_candidate": selected,
        "confirmation": confirmation,
        "holdout_pass": holdout_pass,
        "blockers": blockers,
        "immediate_fail_definition": "realized_R<0 and ledger_MFE_R<0.25; diagnostic only, never used as entry feature",
        "causal_entry_dimensions": ["entry_regime_reconstructed_at_entry", "side", "utc_session"],
        "selection_window": SELECTION_WINDOW,
        "holdout_windows": ["1m_w2", "1m_w3"],
        "selection_authority": False,
        "promotion_authority": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "context_facts_published": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "RUN_EXACT_SOURCE_REPLAY_FOR_FROZEN_ENTRY_FILTER"
            if not blockers
            else "REJECT_IMMEDIATE_FAIL_ENTRY_FILTER_AND_TEST_TIME_STOP"
        ),
    }
    receipt["receipt_sha256"] = grid.stable_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    receipt = evaluate(engine_path=args.engine, terminal_root=args.terminal_root, data_root=args.data_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "selected": (receipt.get("selected_candidate") or {}).get("candidate_id"),
        "holdout_pass": receipt.get("holdout_pass"),
        "blockers": receipt.get("blockers"),
        "next": receipt["next"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
