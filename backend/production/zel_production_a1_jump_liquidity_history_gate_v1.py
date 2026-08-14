from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

POLICY_SCHEMA = "zel.production_a1_jump_liquidity_history_gate_policy.v1"
TEMPLATE_SCHEMA = "zel.production_a1_jump_liquidity_source_template.v1"
ROW_SCHEMA = "zel.production_bingx_ws_microstructure_row.v1"
HEARTBEAT_SCHEMA = "zel.production_bingx_ws_microstructure_heartbeat.v1"
DEFAULT_POLICY = Path("config/zel_production_a1_jump_liquidity_history_gate_v1.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return dict(value)


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("A1_JUMP_HISTORY_POLICY_SCHEMA_INVALID")
    if policy.get("family") != "jump_liquidity_state_switch":
        raise RuntimeError("A1_JUMP_HISTORY_FAMILY_INVALID")
    if policy.get("role") != "A1_PROSPECTIVE_SOURCE_QUALITY_GATE_ONLY":
        raise RuntimeError("A1_JUMP_HISTORY_ROLE_DRIFT")
    if int(policy.get("bucket_ms") or 0) != 5000:
        raise RuntimeError("A1_JUMP_HISTORY_BUCKET_INVALID")
    if int(policy.get("runtime_min_elapsed_ms") or 0) < 900000:
        raise RuntimeError("A1_JUMP_HISTORY_RUNTIME_WINDOW_TOO_SHORT")
    if int(policy.get("calibration_min_elapsed_ms") or 0) < int(policy.get("runtime_min_elapsed_ms") or 0):
        raise RuntimeError("A1_JUMP_HISTORY_CALIBRATION_WINDOW_INVALID")
    if not 0 < float(policy.get("coverage_min_pct") or 0) <= 100:
        raise RuntimeError("A1_JUMP_HISTORY_COVERAGE_INVALID")
    if int(policy.get("max_gap_ms") or 0) < int(policy.get("bucket_ms") or 0):
        raise RuntimeError("A1_JUMP_HISTORY_GAP_INVALID")
    if int(policy.get("heartbeat_stale_ms") or 0) <= 0:
        raise RuntimeError("A1_JUMP_HISTORY_STALE_INVALID")
    symbols = policy.get("symbols")
    if symbols != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("A1_JUMP_HISTORY_SYMBOLS_INVALID")
    if policy.get("economic_replay_allowed_by_this_gate") is not False:
        raise RuntimeError("A1_JUMP_HISTORY_ECONOMIC_AUTHORITY_FORBIDDEN")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("A1_JUMP_HISTORY_SELECTION_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("A1_JUMP_HISTORY_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("A1_JUMP_HISTORY_LIVE_FORBIDDEN")
    return dict(policy)


def validate_template(template: Mapping[str, Any]) -> dict[str, Any]:
    if template.get("schema_version") != TEMPLATE_SCHEMA:
        raise RuntimeError("A1_JUMP_SOURCE_TEMPLATE_SCHEMA_INVALID")
    if template.get("family") != "jump_liquidity_state_switch" or template.get("template_ready") is not True:
        raise RuntimeError("A1_JUMP_SOURCE_TEMPLATE_NOT_READY")
    if template.get("numeric_signal_thresholds_frozen") is not False:
        raise RuntimeError("A1_JUMP_SOURCE_TEMPLATE_SIGNAL_THRESHOLD_DRIFT")
    if template.get("economic_signal_enabled") is not False:
        raise RuntimeError("A1_JUMP_SOURCE_TEMPLATE_ECONOMIC_SIGNAL_FORBIDDEN")
    if set((template.get("sources") or {}).keys()) != {"l2_order_book", "volume", "ohlcv"}:
        raise RuntimeError("A1_JUMP_SOURCE_TEMPLATE_SOURCE_SET_INVALID")
    return dict(template)


def evaluate(
    policy: Mapping[str, Any],
    template: Mapping[str, Any],
    heartbeat: Mapping[str, Any] | None,
    rows: list[Mapping[str, Any]],
    *,
    now_ms: int | None = None,
    runtime_source_sha256: str | None = None,
    runtime_policy_sha256: str | None = None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    src = validate_template(template)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    defects: list[str] = []
    malformed = 0
    duplicates = 0
    by_symbol: dict[str, list[dict[str, Any]]] = {s: [] for s in cfg["symbols"]}
    seen: set[tuple[str, int]] = set()

    for raw in rows:
        try:
            if raw.get("schema_version") != ROW_SCHEMA:
                raise ValueError("schema")
            symbol = str(raw.get("symbol") or "")
            bucket = int(raw.get("bucket_start_ms") or 0)
            if symbol not in by_symbol or bucket <= 0:
                raise ValueError("key")
            for key in ("depth_messages", "trade_messages", "kline_messages"):
                if int(raw.get(key) or 0) < 0:
                    raise ValueError(key)
            if raw.get("execution_authority") != "NONE" or raw.get("order_authority") != "BLOCKED":
                raise ValueError("authority")
            if raw.get("live_trade_authority") != "BLOCKED" or raw.get("exchange_order_submitted") is not False:
                raise ValueError("live")
            key = (symbol, bucket)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            by_symbol[symbol].append(dict(raw))
        except Exception:
            malformed += 1

    if malformed and cfg.get("require_zero_malformed_rows"):
        defects.append(f"MALFORMED_ROWS:{malformed}")
    if duplicates and cfg.get("require_zero_duplicate_buckets"):
        defects.append(f"DUPLICATE_BUCKETS:{duplicates}")

    hb = dict(heartbeat) if isinstance(heartbeat, Mapping) else None
    hb_age = None
    if not hb or hb.get("schema_version") != HEARTBEAT_SCHEMA:
        defects.append("HEARTBEAT_MISSING_OR_SCHEMA_INVALID")
    else:
        hb_age = now - int(hb.get("updated_at_ms") or 0)
        if hb_age > int(cfg["heartbeat_stale_ms"]):
            defects.append(f"HEARTBEAT_STALE_MS:{hb_age}")
        if int(hb.get("parse_errors_total") or 0) != 0 and cfg.get("require_zero_parse_errors"):
            defects.append(f"PARSE_ERRORS:{int(hb.get('parse_errors_total') or 0)}")
        if hb.get("execution_authority") != "NONE" or hb.get("order_authority") != "BLOCKED":
            defects.append("HEARTBEAT_EXECUTION_AUTHORITY_DRIFT")
        if hb.get("live_trade_authority") != "BLOCKED" or hb.get("exchange_order_submitted") is not False:
            defects.append("HEARTBEAT_LIVE_AUTHORITY_DRIFT")
        if runtime_source_sha256 and hb.get("source_sha256") != runtime_source_sha256:
            defects.append("COLLECTOR_SOURCE_SHA_MISMATCH")
        if runtime_policy_sha256 and hb.get("policy_sha256") != runtime_policy_sha256:
            defects.append("COLLECTOR_POLICY_SHA_MISMATCH")

    symbol_stats: dict[str, Any] = {}
    runtime_ready = True
    calibration_ready = True
    for symbol, values in by_symbol.items():
        values.sort(key=lambda x: int(x["bucket_start_ms"]))
        count = len(values)
        if count == 0:
            symbol_stats[symbol] = {"row_count": 0, "coverage_pct": 0.0, "elapsed_ms": 0}
            runtime_ready = calibration_ready = False
            continue
        buckets = [int(x["bucket_start_ms"]) for x in values]
        first, last = buckets[0], buckets[-1]
        span = last - first + int(cfg["bucket_ms"])
        expected = max(1, int(math.floor((last - first) / int(cfg["bucket_ms"]))) + 1)
        coverage = count / expected * 100.0
        gaps = [b - a for a, b in zip(buckets, buckets[1:])]
        max_gap = max(gaps) if gaps else int(cfg["bucket_ms"])
        depth_rows = sum(1 for x in values if int(x.get("depth_messages") or 0) > 0)
        trade_rows = sum(1 for x in values if int(x.get("trade_messages") or 0) > 0)
        kline_rows = sum(1 for x in values if int(x.get("kline_messages") or 0) > 0)
        latest_age = now - (last + int(cfg["bucket_ms"]))
        stats = {
            "row_count": count,
            "first_bucket_ms": first,
            "last_bucket_ms": last,
            "elapsed_ms": span,
            "expected_bucket_count": expected,
            "coverage_pct": round(coverage, 6),
            "max_gap_ms": max_gap,
            "latest_bucket_age_ms": latest_age,
            "depth_rows": depth_rows,
            "trade_rows": trade_rows,
            "kline_rows": kline_rows,
        }
        symbol_stats[symbol] = stats
        quality = coverage >= float(cfg["coverage_min_pct"]) and max_gap <= int(cfg["max_gap_ms"]) and latest_age <= int(cfg["heartbeat_stale_ms"])
        streams = (
            (not cfg.get("require_depth_stream") or depth_rows > 0)
            and (not cfg.get("require_trade_stream") or trade_rows > 0)
            and (not cfg.get("require_kline_stream") or kline_rows > 0)
        )
        runtime_ready = runtime_ready and quality and streams and span >= int(cfg["runtime_min_elapsed_ms"])
        calibration_ready = calibration_ready and quality and streams and span >= int(cfg["calibration_min_elapsed_ms"])

    if defects:
        state = "HOLD_A1_JUMP_SOURCE_INTEGRITY"
        source_ready = False
        calibration_ready = False
    elif calibration_ready:
        state = "PASS_A1_JUMP_CALIBRATION_SOURCE_READY"
        source_ready = True
    elif runtime_ready:
        state = "PASS_A1_JUMP_RUNTIME_SOURCE_READY"
        source_ready = True
    else:
        state = "HOLD_A1_JUMP_SOURCE_HISTORY_ACCUMULATING"
        source_ready = False

    return {
        "schema_version": "zel.production_a1_jump_liquidity_history_gate_receipt.v1",
        "state": state,
        "family": "jump_liquidity_state_switch",
        "source_template_sha256": hashlib.sha256(json.dumps(src, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "template_ready": True,
        "source_ready": source_ready,
        "calibration_ready": bool(calibration_ready and not defects),
        "economic_replay_allowed": False,
        "history_gate_decision_scope": "SOURCE_QUALITY_ONLY",
        "heartbeat_age_ms": hb_age,
        "symbol_stats": symbol_stats,
        "malformed_row_count": malformed,
        "duplicate_bucket_count": duplicates,
        "integrity_defects": defects,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate prospective jump-liquidity source history only")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = _load(ns.policy)
    cfg = validate_policy(policy)
    template = _load(Path(str(cfg["source_template_path"])))
    heartbeat_path = Path(str(cfg["heartbeat_path"]))
    heartbeat = _load(heartbeat_path) if heartbeat_path.is_file() else None
    history_path = Path(str(cfg["history_path"]))
    rows: list[Mapping[str, Any]] = []
    if history_path.is_file():
        for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, Mapping):
                    rows.append(value)
                else:
                    rows.append({"_malformed": True})
            except Exception:
                rows.append({"_malformed": True})
    collector_source = Path(str(cfg["collector_source_path"]))
    collector_policy = Path(str(cfg["collector_policy_path"]))
    receipt = evaluate(
        policy,
        template,
        heartbeat,
        rows,
        runtime_source_sha256=_sha(collector_source) if collector_source.is_file() else None,
        runtime_policy_sha256=_sha(collector_policy) if collector_policy.is_file() else None,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 2 if receipt["integrity_defects"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
