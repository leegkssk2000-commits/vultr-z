from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.production import zel_production_a1_jump_liquidity_history_gate_v1 as history_gate

POLICY_SCHEMA = "zel.production_a1_jump_liquidity_calibration_policy.v1"
SEAL_SCHEMA = "zel.production_a1_jump_liquidity_calibration_seal.v1"
DEFAULT_POLICY = Path("config/zel_production_a1_jump_liquidity_calibration_v1.json")
AUTOPSY_PATH = Path("config/zel_production_a1_jump_liquidity_autopsy_v1.json")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return dict(value)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise RuntimeError("A1_JUMP_CALIBRATION_EMPTY_QUANTILE_INPUT")
    if not 0.0 <= q <= 1.0:
        raise RuntimeError("A1_JUMP_CALIBRATION_QUANTILE_INVALID")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    weight = pos - lo
    return xs[lo] * (1.0 - weight) + xs[hi] * weight


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("A1_JUMP_CALIBRATION_POLICY_SCHEMA_INVALID")
    if policy.get("family") != "jump_liquidity_state_switch":
        raise RuntimeError("A1_JUMP_CALIBRATION_FAMILY_INVALID")
    if policy.get("role") != "A1_SOURCE_ONLY_THRESHOLD_AND_FALSIFICATION_CALIBRATION":
        raise RuntimeError("A1_JUMP_CALIBRATION_ROLE_DRIFT")
    if policy.get("symbols") != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("A1_JUMP_CALIBRATION_SYMBOLS_INVALID")
    if int(policy.get("bucket_ms") or 0) != 5000:
        raise RuntimeError("A1_JUMP_CALIBRATION_BUCKET_INVALID")
    if int(policy.get("calibration_elapsed_ms") or 0) < 21_600_000:
        raise RuntimeError("A1_JUMP_CALIBRATION_WINDOW_TOO_SHORT")
    expected_q = {
        "jump_abs_return_bps": 0.975,
        "trade_quote_notional": 0.80,
        "abs_trade_imbalance": 0.80,
        "abs_book_imbalance": 0.80,
        "total_depth_top20": 0.20,
        "spread_bps": 0.80,
    }
    if policy.get("threshold_quantiles") != expected_q:
        raise RuntimeError("A1_JUMP_CALIBRATION_QUANTILE_CONTRACT_DRIFT")
    if policy.get("falsification_horizons_sec") != [5, 15, 30, 60]:
        raise RuntimeError("A1_JUMP_CALIBRATION_HORIZON_CONTRACT_DRIFT")
    if policy.get("horizon_policy") != "FIXED_VECTOR_NO_BEST_HORIZON_SELECTION_FROM_PNL":
        raise RuntimeError("A1_JUMP_CALIBRATION_HORIZON_POLICY_INVALID")
    expected_controls = ["DIRECTION_FLIP", "PLUS_ONE_BUCKET_DELAY", "TIMESTAMP_SHIFT_PLACEBO", "MATCHED_NON_EVENT"]
    if policy.get("negative_controls") != expected_controls:
        raise RuntimeError("A1_JUMP_CALIBRATION_CONTROL_SET_DRIFT")
    for key in ("threshold_selection_uses_future_returns", "threshold_selection_uses_pnl", "threshold_selection_uses_winrate", "economic_outcomes_inspected", "parameter_search", "economic_replay_allowed_by_calibration"):
        if policy.get(key) is not False:
            raise RuntimeError(f"A1_JUMP_CALIBRATION_FORBIDDEN_FLAG:{key}")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("A1_JUMP_CALIBRATION_SELECTION_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("A1_JUMP_CALIBRATION_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("A1_JUMP_CALIBRATION_LIVE_FORBIDDEN")
    for key in ("source_history_gate_policy_path", "source_template_path", "source_history_path", "seal_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"A1_JUMP_CALIBRATION_PATH_MISSING:{key}")
    return dict(policy)


def _load_history(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, Mapping):
            rows.append(dict(value))
    return rows


def _history_gate_receipt(calibration_policy: Mapping[str, Any]) -> dict[str, Any]:
    gate_policy = _load(Path(str(calibration_policy["source_history_gate_policy_path"])))
    cfg = history_gate.validate_policy(gate_policy)
    template = _load(Path(str(calibration_policy["source_template_path"])))
    heartbeat_path = Path(str(cfg["heartbeat_path"]))
    heartbeat = _load(heartbeat_path) if heartbeat_path.is_file() else None
    rows = _load_history(Path(str(calibration_policy["source_history_path"])))
    source_path = Path(str(cfg["collector_source_path"]))
    collector_policy_path = Path(str(cfg["collector_policy_path"]))
    return history_gate.evaluate(
        gate_policy,
        template,
        heartbeat,
        rows,
        runtime_source_sha256=_sha(source_path) if source_path.is_file() else None,
        runtime_policy_sha256=_sha(collector_policy_path) if collector_policy_path.is_file() else None,
    )


def _select_prefix(rows: list[dict[str, Any]], symbols: list[str], elapsed_ms: int) -> tuple[int, int, dict[str, list[dict[str, Any]]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if symbol in by_symbol and row.get("schema_version") == history_gate.ROW_SCHEMA:
            by_symbol[symbol].append(row)
    for values in by_symbol.values():
        values.sort(key=lambda x: int(x.get("bucket_start_ms") or 0))
        if not values:
            raise RuntimeError("A1_JUMP_CALIBRATION_SYMBOL_HISTORY_EMPTY")
    start = max(int(by_symbol[s][0]["bucket_start_ms"]) for s in symbols)
    end = start + elapsed_ms
    selected: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        selected[symbol] = [r for r in by_symbol[symbol] if start <= int(r.get("bucket_start_ms") or 0) < end]
        if not selected[symbol] or int(selected[symbol][-1].get("bucket_end_ms") or 0) < end:
            raise RuntimeError(f"A1_JUMP_CALIBRATION_PREFIX_INCOMPLETE:{symbol}")
    return start, end, selected


def _symbol_thresholds(rows: list[dict[str, Any]], quantiles: Mapping[str, float]) -> dict[str, Any]:
    abs_returns: list[float] = []
    notionals: list[float] = []
    abs_trade_imbalance: list[float] = []
    abs_book_imbalance: list[float] = []
    total_depth: list[float] = []
    spreads: list[float] = []
    prev_mid: float | None = None
    for row in rows:
        mid = _finite(row.get("mid_last"))
        if mid is not None and mid > 0 and prev_mid is not None and prev_mid > 0:
            abs_returns.append(abs((mid / prev_mid - 1.0) * 10000.0))
        if mid is not None and mid > 0:
            prev_mid = mid
        value = _finite(row.get("trade_quote_notional"))
        if value is not None and value >= 0:
            notionals.append(value)
        value = _finite(row.get("trade_imbalance"))
        if value is not None:
            abs_trade_imbalance.append(abs(value))
        value = _finite(row.get("imbalance_top20_mean"))
        if value is not None:
            abs_book_imbalance.append(abs(value))
        bid = _finite(row.get("bid_qty_top20_last"))
        ask = _finite(row.get("ask_qty_top20_last"))
        if bid is not None and ask is not None and bid >= 0 and ask >= 0:
            total_depth.append(bid + ask)
        value = _finite(row.get("spread_bps_mean"))
        if value is not None and value >= 0:
            spreads.append(value)
    inputs = {
        "jump_abs_return_bps": abs_returns,
        "trade_quote_notional": notionals,
        "abs_trade_imbalance": abs_trade_imbalance,
        "abs_book_imbalance": abs_book_imbalance,
        "total_depth_top20": total_depth,
        "spread_bps": spreads,
    }
    if any(not values for values in inputs.values()):
        missing = [key for key, values in inputs.items() if not values]
        raise RuntimeError(f"A1_JUMP_CALIBRATION_FEATURE_EMPTY:{','.join(missing)}")
    return {
        "sample_counts": {key: len(values) for key, values in inputs.items()},
        "jump_abs_return_bps_q975": _quantile(abs_returns, float(quantiles["jump_abs_return_bps"])),
        "trade_quote_notional_q80": _quantile(notionals, float(quantiles["trade_quote_notional"])),
        "abs_trade_imbalance_q80": _quantile(abs_trade_imbalance, float(quantiles["abs_trade_imbalance"])),
        "abs_book_imbalance_q80": _quantile(abs_book_imbalance, float(quantiles["abs_book_imbalance"])),
        "total_depth_top20_q20": _quantile(total_depth, float(quantiles["total_depth_top20"])),
        "spread_bps_q80": _quantile(spreads, float(quantiles["spread_bps"])),
    }


def build_seal(policy: Mapping[str, Any]) -> dict[str, Any]:
    cfg = validate_policy(policy)
    gate_receipt = _history_gate_receipt(cfg)
    if gate_receipt.get("state") != "PASS_A1_JUMP_CALIBRATION_SOURCE_READY" or gate_receipt.get("calibration_ready") is not True:
        return {
            "schema_version": SEAL_SCHEMA,
            "state": "HOLD_A1_JUMP_CALIBRATION_SOURCE_NOT_READY",
            "family": cfg["family"],
            "history_gate_state": gate_receipt.get("state"),
            "history_gate_receipt_sha256": _canonical_sha(gate_receipt),
            "economic_outcomes_inspected": False,
            "threshold_selection_uses_future_returns": False,
            "threshold_selection_uses_pnl": False,
            "economic_replay_allowed": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "protected_mutations": 0,
        }
    history = _load_history(Path(str(cfg["source_history_path"])))
    start, end, selected = _select_prefix(history, list(cfg["symbols"]), int(cfg["calibration_elapsed_ms"]))
    canonical_prefix = [row for symbol in cfg["symbols"] for row in selected[symbol]]
    canonical_prefix.sort(key=lambda x: (int(x.get("bucket_start_ms") or 0), str(x.get("symbol") or "")))
    thresholds = {
        symbol: _symbol_thresholds(selected[symbol], cfg["threshold_quantiles"])
        for symbol in cfg["symbols"]
    }
    return {
        "schema_version": SEAL_SCHEMA,
        "state": "PASS_A1_JUMP_SOURCE_ONLY_CALIBRATION_SEALED",
        "family": cfg["family"],
        "role": cfg["role"],
        "calibration_start_bucket_ms": start,
        "calibration_end_bucket_ms_exclusive": end,
        "economic_evaluation_start_bucket_ms": end,
        "calibration_elapsed_ms": int(cfg["calibration_elapsed_ms"]),
        "symbols": list(cfg["symbols"]),
        "thresholds_by_symbol": thresholds,
        "event_taxonomy": cfg["event_taxonomy"],
        "falsification_horizons_sec": cfg["falsification_horizons_sec"],
        "horizon_policy": cfg["horizon_policy"],
        "negative_controls": cfg["negative_controls"],
        "history_prefix_row_count": len(canonical_prefix),
        "history_prefix_sha256": _canonical_sha(canonical_prefix),
        "history_gate_receipt_sha256": _canonical_sha(gate_receipt),
        "source_template_sha256": _sha(Path(str(cfg["source_template_path"]))),
        "calibration_policy_sha256": _sha(DEFAULT_POLICY),
        "autopsy_policy_sha256": _sha(AUTOPSY_PATH),
        "threshold_selection_uses_future_returns": False,
        "threshold_selection_uses_pnl": False,
        "threshold_selection_uses_winrate": False,
        "economic_outcomes_inspected": False,
        "parameter_search": False,
        "economic_replay_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }


def persist_or_verify(seal_path: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    if candidate.get("state") != "PASS_A1_JUMP_SOURCE_ONLY_CALIBRATION_SEALED":
        return dict(candidate)
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    if seal_path.exists():
        existing = _load(seal_path)
        identity = ("calibration_policy_sha256", "history_prefix_sha256", "source_template_sha256", "autopsy_policy_sha256")
        if existing.get("schema_version") != SEAL_SCHEMA or any(existing.get(k) != candidate.get(k) for k in identity):
            return {
                "schema_version": SEAL_SCHEMA,
                "state": "HOLD_A1_JUMP_CALIBRATION_IMMUTABILITY_MISMATCH",
                "existing_seal_sha256": _sha(seal_path),
                "candidate_sha256": _canonical_sha(candidate),
                "economic_outcomes_inspected": False,
                "economic_replay_allowed": False,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED",
                "exchange_order_submitted": False,
                "protected_mutations": 0,
            }
        out = dict(existing)
        out["seal_reused_immutable"] = True
        out["seal_file_sha256"] = _sha(seal_path)
        return out
    try:
        with seal_path.open("x", encoding="utf-8") as handle:
            json.dump(dict(candidate), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
    except FileExistsError:
        return persist_or_verify(seal_path, candidate)
    out = dict(candidate)
    out["seal_reused_immutable"] = False
    out["seal_file_sha256"] = _sha(seal_path)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Freeze source-only jump-liquidity thresholds without inspecting future returns or PnL")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = _load(ns.policy)
    candidate = build_seal(policy)
    result = persist_or_verify(Path(str(policy["seal_path"])), candidate)
    print(json.dumps(result, sort_keys=True))
    return 2 if str(result.get("state") or "").startswith("HOLD_A1_JUMP_CALIBRATION_IMMUTABILITY") else 0


if __name__ == "__main__":
    raise SystemExit(main())
