from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import zel_ema_ribbon_intratrade_path_audit_v1 as audit

VERSION = "ZEL_EMA_PATH_SEMANTICS_RECONCILIATION_V1"
SCHEMA = "zel.ema_path_semantics_reconciliation.receipt.v1"
EXPECTED_TRADES = 424
PRICE_MODES = ("high_low", "close", "open_close")
SLICE_MODES = ("inclusive", "exclude_entry", "exclude_exit", "exclude_both")
INITIAL_RISK_USDT_KEYS = ("initial_risk_usdt", "risk_usdt", "initial_risk")
QUANTITY_KEYS = ("quantity", "qty", "position_qty", "size_coin", "base_qty", "contracts")
NOTIONAL_KEYS = ("notional_usdt", "position_notional_usdt", "position_size_usdt", "notional", "position_notional")


def stable_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> float | None:
    return audit.finite(value)


def first_number(row: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    return audit.first_number(row, keys)[1]


def side(row: Mapping[str, Any]) -> str:
    return audit.normalized_side(row)


def event_id(row: Mapping[str, Any]) -> str:
    return audit.event_id(row)


def window_id(row: Mapping[str, Any]) -> str:
    return audit.window_id(row)


def symbol(row: Mapping[str, Any]) -> str:
    return audit.symbol(row)


def entry_price(row: Mapping[str, Any]) -> float | None:
    return first_number(row, audit.ENTRY_PRICE_KEYS)


def exit_price(row: Mapping[str, Any]) -> float | None:
    return first_number(row, audit.EXIT_PRICE_KEYS)


def realized_r(row: Mapping[str, Any]) -> float | None:
    return first_number(row, audit.REALIZED_R_KEYS)


def ledger_mfe(row: Mapping[str, Any]) -> float | None:
    return first_number(row, audit.MFE_R_KEYS)


def ledger_mae(row: Mapping[str, Any]) -> float | None:
    return first_number(row, audit.MAE_R_KEYS)


def resolve_file(data_root: Path, row: Mapping[str, Any]) -> Path:
    return audit.resolve_file(data_root, row)


def risk_candidates(row: Mapping[str, Any], entry: float, exit_px: float | None) -> dict[str, float]:
    output: dict[str, float] = {}
    source, stop_risk = audit.risk_distance(row, entry)
    if stop_risk is not None and stop_risk > 0:
        output[f"stop_distance:{source}"] = stop_risk

    explicit = first_number(row, audit.RISK_DISTANCE_KEYS)
    if explicit is not None and explicit > 0:
        output["explicit_price_distance"] = abs(explicit)

    risk_usdt = first_number(row, INITIAL_RISK_USDT_KEYS)
    quantity = first_number(row, QUANTITY_KEYS)
    notional = first_number(row, NOTIONAL_KEYS)
    if risk_usdt is not None and risk_usdt > 0 and quantity is not None and quantity > 0:
        output["risk_usdt_div_quantity"] = risk_usdt / quantity
    if risk_usdt is not None and risk_usdt > 0 and notional is not None and notional > 0:
        output["risk_usdt_times_entry_div_notional"] = risk_usdt * entry / notional

    stop_value = first_number(row, audit.STOP_PRICE_KEYS)
    if stop_value is not None and 0 < abs(stop_value) < 0.20:
        output["stop_field_as_fraction_of_entry"] = abs(stop_value) * entry
    if stop_value is not None and 0 < abs(stop_value) < 20.0:
        output["stop_field_as_percent_of_entry"] = abs(stop_value) / 100.0 * entry

    outcome = realized_r(row)
    if exit_px is not None and outcome is not None and abs(outcome) > 1e-9:
        implied = abs(exit_px - entry) / abs(outcome)
        if implied > 0 and math.isfinite(implied):
            output["diagnostic_exit_implied"] = implied
    return {key: value for key, value in output.items() if value > 0 and math.isfinite(value)}


def slice_frame(frame: Any, entry_index: int, exit_index: int, mode: str):
    start = entry_index + (1 if mode in {"exclude_entry", "exclude_both"} else 0)
    stop = exit_index + (0 if mode in {"exclude_exit", "exclude_both"} else 1)
    if stop <= start:
        return frame.iloc[0:0].copy()
    return frame.iloc[start:stop].copy()


def price_excursions(path: Any, mode: str, trade_side: str, entry: float) -> tuple[float | None, float | None]:
    if path.empty:
        return None, None
    if mode == "high_low":
        maximum = finite(path["high"].max())
        minimum = finite(path["low"].min())
    elif mode == "close":
        maximum = finite(path["close"].max())
        minimum = finite(path["close"].min())
    elif mode == "open_close":
        maximum = max(value for value in (finite(path["open"].max()), finite(path["close"].max())) if value is not None)
        minimum = min(value for value in (finite(path["open"].min()), finite(path["close"].min())) if value is not None)
    else:
        raise RuntimeError(f"UNKNOWN_PRICE_MODE:{mode}")
    if maximum is None or minimum is None:
        return None, None
    if trade_side == "long":
        return max(0.0, maximum - entry), min(0.0, minimum - entry)
    if trade_side == "short":
        return max(0.0, entry - minimum), min(0.0, entry - maximum)
    return None, None


def candidate_key(price_mode: str, slice_mode: str, risk_mode: str) -> str:
    return f"{price_mode}|{slice_mode}|{risk_mode}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    rows = audit.read_rows(args.terminal_root / "trades.jsonl.gz")
    if len(rows) != EXPECTED_TRADES:
        raise RuntimeError(f"TRADE_COUNT_MISMATCH:{len(rows)}")
    engine = load_module(args.engine, "zel_ema_path_semantics_engine")
    manifest_result = engine.validate_data_manifest(args.data_root, "1m")
    manifest = manifest_result[0] if isinstance(manifest_result, tuple) else manifest_result
    if not isinstance(manifest, Mapping):
        raise RuntimeError("DATA_MANIFEST_INVALID")
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in list(manifest.get("files") or []):
        if isinstance(file_row, Mapping):
            file_map[(str(file_row.get("window_id") or file_row.get("window") or "unknown"), str(file_row.get("symbol") or "").upper())] = file_row

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(window_id(row), symbol(row))].append(row)

    errors: dict[str, dict[str, Any]] = defaultdict(lambda: {"mfe_abs": [], "mae_abs": [], "count": 0, "entry_known": True})
    mapping_failures: list[str] = []
    risk_mode_coverage: dict[str, int] = defaultdict(int)
    row_contracts: dict[str, dict[str, float]] = {}

    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            mapping_failures.extend("LANE_FILE_MISSING" for _ in lane_rows)
            continue
        frame = engine.frame_from_csv(resolve_file(args.data_root, file_row))
        index_by_timestamp: dict[int, int] = {}
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch = audit.parse_timestamp(engine.pd, value)
            if epoch is not None:
                index_by_timestamp[epoch] = index
        for row in lane_rows:
            entry = entry_price(row)
            exit_px = exit_price(row)
            trade_side = side(row)
            mfe = ledger_mfe(row)
            mae = ledger_mae(row)
            entry_epoch = audit.parse_timestamp(engine.pd, audit.first_text(row, audit.ENTRY_TS_KEYS)[1])
            exit_epoch = audit.parse_timestamp(engine.pd, audit.first_text(row, audit.EXIT_TS_KEYS)[1])
            entry_index = index_by_timestamp.get(entry_epoch) if entry_epoch is not None else None
            exit_index = index_by_timestamp.get(exit_epoch) if exit_epoch is not None else None
            if entry is None or trade_side not in {"long", "short"} or mfe is None or mae is None or entry_index is None or exit_index is None or exit_index < entry_index:
                mapping_failures.append("ROW_CONTRACT_OR_TIMESTAMP_INVALID")
                continue
            risks = risk_candidates(row, entry, exit_px)
            row_contracts[event_id(row)] = risks
            for risk_mode in risks:
                risk_mode_coverage[risk_mode] += 1
            for slice_mode in SLICE_MODES:
                path = slice_frame(frame, entry_index, exit_index, slice_mode)
                if path.empty:
                    continue
                for price_mode in PRICE_MODES:
                    favorable, adverse = price_excursions(path, price_mode, trade_side, entry)
                    if favorable is None or adverse is None:
                        continue
                    for risk_mode, risk in risks.items():
                        key = candidate_key(price_mode, slice_mode, risk_mode)
                        reconstructed_mfe = favorable / risk
                        reconstructed_mae = adverse / risk
                        errors[key]["mfe_abs"].append(abs(reconstructed_mfe - mfe))
                        errors[key]["mae_abs"].append(abs(reconstructed_mae - mae))
                        errors[key]["count"] += 1
                        errors[key]["entry_known"] = risk_mode != "diagnostic_exit_implied"

    candidates: list[dict[str, Any]] = []
    for key, value in errors.items():
        count = int(value["count"])
        mfe_values = list(value["mfe_abs"])
        mae_values = list(value["mae_abs"])
        if count == 0:
            continue
        price_mode, slice_mode, risk_mode = key.split("|", 2)
        mean_mfe = sum(mfe_values) / len(mfe_values)
        mean_mae = sum(mae_values) / len(mae_values)
        candidates.append({
            "candidate_id": key,
            "price_mode": price_mode,
            "slice_mode": slice_mode,
            "risk_mode": risk_mode,
            "entry_known_risk": bool(value["entry_known"]),
            "coverage_count": count,
            "coverage_pct": count / EXPECTED_TRADES * 100.0,
            "mfe_mean_abs_error_R": mean_mfe,
            "mae_mean_abs_error_R": mean_mae,
            "combined_mean_abs_error_R": (mean_mfe + mean_mae) / 2.0,
            "mfe_max_abs_error_R": max(mfe_values),
            "mae_max_abs_error_R": max(mae_values),
        })
    candidates.sort(key=lambda row: (-row["coverage_count"], row["combined_mean_abs_error_R"], row["candidate_id"]))
    complete = [row for row in candidates if row["coverage_count"] == EXPECTED_TRADES]
    best = min(complete, key=lambda row: row["combined_mean_abs_error_R"]) if complete else None
    best_entry_known = min((row for row in complete if row["entry_known_risk"]), key=lambda row: row["combined_mean_abs_error_R"], default=None)

    exact_threshold = 0.05
    exact = bool(best and best["mfe_mean_abs_error_R"] <= exact_threshold and best["mae_mean_abs_error_R"] <= exact_threshold)
    entry_known_exact = bool(best_entry_known and best_entry_known["mfe_mean_abs_error_R"] <= exact_threshold and best_entry_known["mae_mean_abs_error_R"] <= exact_threshold)
    blockers: list[str] = []
    if mapping_failures:
        blockers.append("ROW_OR_TIMESTAMP_MAPPING_INCOMPLETE")
    if best is None:
        blockers.append("NO_COMPLETE_SEMANTICS_CANDIDATE")
    elif not exact:
        blockers.append("NO_EXACT_LEDGER_SEMANTICS_MATCH")
    if not entry_known_exact:
        blockers.append("NO_ENTRY_KNOWN_EXACT_RISK_BASIS")

    state = "PASS_EMA_PATH_SEMANTICS_RECONCILED" if not blockers else "HOLD_EMA_PATH_SEMANTICS_UNRESOLVED"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": audit.STRATEGY_ID,
        "trade_count": len(rows),
        "price_modes": list(PRICE_MODES),
        "slice_modes": list(SLICE_MODES),
        "risk_mode_coverage": dict(sorted(risk_mode_coverage.items())),
        "mapping_failure_count": len(mapping_failures),
        "mapping_failure_counts": dict(sorted(__import__('collections').Counter(mapping_failures).items())),
        "candidate_count": len(candidates),
        "best_candidate": best,
        "best_entry_known_candidate": best_entry_known,
        "top_candidates": candidates[:20],
        "exact_match_threshold_R": exact_threshold,
        "exact_match": exact,
        "entry_known_exact_match": entry_known_exact,
        "blockers": blockers,
        "contract_identification_uses_all_windows": True,
        "strategy_selection_performed": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "raw_price_data_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "RUN_EMA_TRAILING_W1_TOURNAMENT" if not blockers else "TRACE_EXACT_MFE_MAE_UPDATE_ORDER",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
