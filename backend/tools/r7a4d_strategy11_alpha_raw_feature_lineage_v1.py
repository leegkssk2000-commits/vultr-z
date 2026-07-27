from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_ALPHA_RAW_FEATURE_LINEAGE_V1"
EXPECTED_KEYS = {
    "expected_return", "expected_return_pct", "forecast_return", "forecast_return_pct",
    "expected_r", "forecast_r", "predicted_return", "predicted_return_pct",
    "edge", "edge_pct", "signal_score", "expected_alpha", "expected_alpha_pct",
}
REQUIRED_LINEAGE_KEYS = {
    "trade_id", "strategy_source_sha", "candidate_config_sha", "market_file_sha256",
    "source_run_id", "source_head_sha", "window_id", "symbol", "signal_ts", "entry_ts",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sorted_trades(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in payload.get("trades", []) if isinstance(row, Mapping)]
    return sorted(rows, key=lambda row: (
        str(row.get("window_id")), str(row.get("symbol")), str(row.get("entry_ts")),
        str(row.get("exit_ts")), str(row.get("trade_id")),
    ))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.alpha_root).resolve()
    out = Path(args.out).resolve()
    a_path = root / "INCUMBENT_CONTROL" / "replay-A.json"
    b_path = root / "INCUMBENT_CONTROL" / "replay-B.json"
    summary_path = root / "summary.json"

    replay_a = load(a_path)
    replay_b = load(b_path)
    authority = load(summary_path)
    trades_a = sorted_trades(replay_a)
    trades_b = sorted_trades(replay_b)

    sha_a = stable_sha(trades_a)
    sha_b = stable_sha(trades_b)
    parity = sha_a == sha_b and len(trades_a) == len(trades_b)

    all_feature_keys: set[str] = set()
    missing_features: list[str] = []
    missing_lineage: list[dict[str, Any]] = []
    signal_after_entry: list[str] = []
    expected_scalar_rows = 0
    rows: list[dict[str, Any]] = []

    for trade in trades_a:
        trade_id = str(trade.get("trade_id") or "")
        features = trade.get("features")
        feature_map = dict(features) if isinstance(features, Mapping) else {}
        if not feature_map:
            missing_features.append(trade_id)
        all_feature_keys.update(str(key) for key in feature_map)
        matched_expected = sorted(set(map(str, feature_map)) & EXPECTED_KEYS)
        if matched_expected:
            expected_scalar_rows += 1
        absent = sorted(key for key in REQUIRED_LINEAGE_KEYS if trade.get(key) in (None, ""))
        if absent:
            missing_lineage.append({"trade_id": trade_id, "missing": absent})
        signal_ts = str(trade.get("signal_ts") or "")
        entry_ts = str(trade.get("entry_ts") or "")
        if signal_ts and entry_ts and signal_ts > entry_ts:
            signal_after_entry.append(trade_id)
        rows.append({
            "trade_id": trade_id,
            "window_id": trade.get("window_id"),
            "symbol": trade.get("symbol"),
            "signal_ts": trade.get("signal_ts"),
            "entry_ts": trade.get("entry_ts"),
            "feature_count": len(feature_map),
            "feature_sha256": stable_sha(feature_map) if feature_map else None,
            "feature_keys": sorted(map(str, feature_map)),
            "matched_expected_return_keys": matched_expected,
            "market_file_sha256": trade.get("market_file_sha256"),
            "strategy_source_sha": trade.get("strategy_source_sha"),
            "candidate_config_sha": trade.get("candidate_config_sha"),
        })

    trade_count = len(trades_a)
    feature_complete = trade_count > 0 and not missing_features
    lineage_complete = trade_count > 0 and not missing_lineage and not signal_after_entry
    blockers: list[str] = []
    if not parity:
        blockers.append("REPLAY_A_B_PARITY_FAIL")
    if trade_count == 0:
        blockers.append("RAW_ALPHA_TRADES_MISSING")
    if missing_features:
        blockers.append("RAW_FEATURE_SNAPSHOT_INCOMPLETE")
    if missing_lineage:
        blockers.append("PER_TRADE_LINEAGE_INCOMPLETE")
    if signal_after_entry:
        blockers.append("SIGNAL_ENTRY_ORDER_INVALID")

    state = "PASS_FEATURE_LINEAGE" if not blockers else "HOLD"
    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "strategy_id": "alpha_combo",
        "source_authority": {
            "pr": 211,
            "run_id": 30278422559,
            "artifact": "s11-alpha-cost-aware-stop-v1-30278422559-attempt-1",
            "artifact_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            "replay_a_file_sha256": hashlib.sha256(a_path.read_bytes()).hexdigest(),
            "replay_b_file_sha256": hashlib.sha256(b_path.read_bytes()).hexdigest(),
            "authority_state": authority.get("state"),
        },
        "audit": {
            "trade_count": trade_count,
            "replay_a_ledger_sha256": sha_a,
            "replay_b_ledger_sha256": sha_b,
            "replay_parity": parity,
            "trades_with_nonempty_features": trade_count - len(missing_features),
            "feature_snapshot_completeness_pct": 0.0 if not trade_count else (trade_count - len(missing_features)) / trade_count * 100.0,
            "per_trade_lineage_completeness_pct": 0.0 if not trade_count else (trade_count - len(missing_lineage)) / trade_count * 100.0,
            "feature_key_count": len(all_feature_keys),
            "feature_keys": sorted(all_feature_keys),
            "expected_return_scalar_rows": expected_scalar_rows,
            "expected_return_scalar_present": expected_scalar_rows > 0,
            "gemini_profile_feature_omission_confirmed": feature_complete,
            "feature_lineage_pass": feature_complete and lineage_complete and parity,
        },
        "blockers": blockers,
        "next": "BUILD_LEAKAGE_SAFE_EXPECTED_R_ESTIMATOR" if state == "PASS_FEATURE_LINEAGE" else "HOLD_RAW_LINEAGE_REPAIR",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write(out / "summary.json", result)
    write(out / "feature_lineage_rows.json", {"rows": rows})
    print(json.dumps({"state": state, "trades": trade_count, "feature_keys": len(all_feature_keys), "expected_scalar_rows": expected_scalar_rows, "blockers": blockers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
