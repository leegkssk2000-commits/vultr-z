from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_STRUCTURAL_PREMIUM_MAIN_REPLAY_V1"
EXPECTED_LEDGER_SHA256 = "62a7d51a02b75ebfee5765d81d955d583d442c995604bb9d4a8a5e7e7a4e2fe3"
EXPECTED_TRADE_COUNT = 1951
MAIN = ("vwap_revert", "support_resistance")
RESERVE = ("liquidity_sweep", "trend_rider")
FILTER_ONLY = ("market_structure",)
R_FIELDS = (
    "realized_R_including_funding_estimate", "pnl_r", "realized_R", "realized_r", "net_R", "net_r"
)
IDENTITY_FIELDS = ("event_id", "position_id", "trade_id")
SIDE_FIELDS = ("side", "position_side", "direction")
WINDOW_FIELDS = ("window_id", "window", "split", "partition")
STRATEGY_FIELDS = ("strategy_id", "strategy", "strategy_name")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nested(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    for container in ("result", "execution_evidence", "market_context", "risk_context", "entry_features"):
        value = row.get(container)
        if isinstance(value, Mapping):
            for key in keys:
                if value.get(key) not in (None, ""):
                    return value[key]
    return None


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "bull", "1", "enter_long"}:
        return "long"
    if text in {"short", "sell", "bear", "-1", "enter_short"}:
        return "short"
    return "unknown"


def normalize_window(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "W1": "W1", "1M_W1": "W1", "TRAIN": "W1", "RESEARCH": "W1",
        "W2": "W2", "1M_W2": "W2", "FORWARD": "W2", "VALIDATION": "W2",
        "W3": "W3", "1M_W3": "W3", "DURABILITY": "W3", "TEST": "W3",
    }
    return aliases.get(text, "UNKNOWN")


def load_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    identities: list[str] = []
    parse_errors = 0
    unknown_side = 0
    unknown_window = 0
    missing_identity = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                source = json.loads(raw)
                if not isinstance(source, dict):
                    raise ValueError("row_not_object")
                identity = str(nested(source, IDENTITY_FIELDS) or "").strip()
                if not identity:
                    missing_identity += 1
                else:
                    identities.append(identity)
                side = normalize_side(nested(source, SIDE_FIELDS))
                window = normalize_window(nested(source, WINDOW_FIELDS))
                strategy = str(nested(source, STRATEGY_FIELDS) or "").strip()
                r_value = nested(source, R_FIELDS)
                r = float(r_value)
                if side == "unknown":
                    unknown_side += 1
                if window == "UNKNOWN":
                    unknown_window += 1
                rows.append({"identity": identity, "strategy_id": strategy, "side": side, "window": window, "r": r})
            except Exception:
                parse_errors += 1
    integrity = {
        "trade_count": len(rows),
        "parse_errors": parse_errors,
        "missing_identity": missing_identity,
        "duplicates": len(identities) - len(set(identities)),
        "unknown_side": unknown_side,
        "unknown_window": unknown_window,
    }
    return rows, integrity


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(row["r"]) for row in rows]
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg_win = gp / len(wins) if wins else 0.0
    avg_loss = gl / len(losses) if losses else 0.0
    equity = peak = max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trade_count": len(values),
        "net_R": sum(values),
        "profit_factor": gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0),
        "expectancy_R": sum(values) / len(values) if values else 0.0,
        "payoff_ratio": avg_win / avg_loss if avg_loss > 0 else (999.0 if avg_win > 0 else 0.0),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "avg_win_R": avg_win,
        "avg_loss_R": -avg_loss,
        "max_drawdown_R": max_dd,
    }


def slice_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {window: metrics([row for row in rows if row["window"] == window]) for window in ("W1", "W2", "W3")}
    out["ALL"] = metrics(rows)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    ledger_sha = file_sha(args.ledger)
    rows, integrity = load_rows(args.ledger)
    integrity_checks = {
        "ledger_sha_match": ledger_sha == EXPECTED_LEDGER_SHA256,
        "trade_count_match": integrity["trade_count"] == EXPECTED_TRADE_COUNT,
        "parse_errors_zero": integrity["parse_errors"] == 0,
        "missing_identity_zero": integrity["missing_identity"] == 0,
        "duplicates_zero": integrity["duplicates"] == 0,
        "unknown_side_zero": integrity["unknown_side"] == 0,
        "unknown_window_zero": integrity["unknown_window"] == 0,
    }
    if not all(integrity_checks.values()):
        state = "HOLD_STRUCTURAL_PREMIUM_LEDGER_INTEGRITY"
        receipt = {
            "schema_version": "zel.structural_premium.main_replay.v1",
            "version": VERSION,
            "state": state,
            "ledger_sha256": ledger_sha,
            "integrity": integrity,
            "integrity_checks": integrity_checks,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "protected_mutations": 0,
            "action": "hold",
        }
        receipt["receipt_sha256"] = stable_sha(receipt)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        return 2

    relevant = [row for row in rows if row["strategy_id"] in MAIN + RESERVE + FILTER_ONLY and row["side"] == "long"]
    main_rows = [row for row in relevant if row["strategy_id"] in MAIN]
    reserve_rows = [row for row in relevant if row["strategy_id"] in RESERVE]
    filter_rows = [row for row in relevant if row["strategy_id"] in FILTER_ONLY]
    per_strategy = {name: slice_metrics([row for row in rows if row["strategy_id"] == name and row["side"] == "long"]) for name in MAIN + RESERVE + FILTER_ONLY}
    main_metrics = slice_metrics(main_rows)
    universe_metrics = slice_metrics(relevant)
    gates: dict[str, Any] = {}
    blockers: list[str] = []
    for window in ("W1", "W2", "W3"):
        m = main_metrics[window]
        passed = m["trade_count"] >= 60 and m["net_R"] > 0 and m["profit_factor"] >= 1 and m["expectancy_R"] > 0 and m["payoff_ratio"] >= 1
        gates[window] = passed
        if not passed:
            blockers.append(f"{window}_ABSOLUTE_ECONOMIC_GATE_FAIL")
    survivor = all(gates.values())
    receipt = {
        "schema_version": "zel.structural_premium.main_replay.v1",
        "version": VERSION,
        "state": "PASS_STRUCTURAL_PREMIUM_MAIN_SURVIVOR" if survivor else "PASS_STRUCTURAL_PREMIUM_MAIN_REPLAY_NO_SURVIVOR",
        "ledger_sha256": ledger_sha,
        "integrity": integrity,
        "integrity_checks": integrity_checks,
        "contract": {
            "main": [f"{x}|enter_long" for x in MAIN],
            "reserve": [f"{x}|enter_long" for x in RESERVE],
            "filter_only": [f"{x}|enter_long" for x in FILTER_ONLY],
        },
        "counts": {
            "relevant_long": len(relevant),
            "main_long": len(main_rows),
            "reserve_long": len(reserve_rows),
            "filter_only_long": len(filter_rows),
        },
        "main": main_metrics,
        "relevant_universe": universe_metrics,
        "per_strategy": per_strategy,
        "gates": gates,
        "survivor": survivor,
        "blockers": blockers,
        "replay_kind": "IMMUTABLE_LEDGER_LEVEL_STRUCTURAL_PREMIUM_BASELINE",
        "source_regeneration_performed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold" if survivor else "route_change",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": receipt["state"], "main_trades": len(main_rows), "survivor": survivor, "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
