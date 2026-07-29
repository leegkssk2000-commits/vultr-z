from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}
REQUIRED_TRADE_FIELDS = {
    "trade_id", "source_ledger_id", "source_row_id", "source_row_sha",
    "strategy_id", "material_id", "team", "symbol", "regime", "window_id",
    "gross_pnl_r", "fee_r", "slippage_r", "funding_r",
    "source_sha", "candidate_sha", "data_sha", "window_sha", "manifest_sha",
}
SHA_FIELDS = {
    "source_row_sha", "source_sha", "candidate_sha", "data_sha", "window_sha", "manifest_sha",
}


class AttributionProjectionError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AttributionProjectionError("JSON_OBJECT_REQUIRED")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AttributionProjectionError(f"STRING_REQUIRED:{name}")
    return value.strip()


def require_sha(value: Any, name: str) -> str:
    result = require_string(value, name).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise AttributionProjectionError(f"SHA256_REQUIRED:{name}")
    return result


def require_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AttributionProjectionError(f"NUMBER_REQUIRED:{name}")
    result = float(value)
    if not math.isfinite(result):
        raise AttributionProjectionError(f"NUMBER_NOT_FINITE:{name}")
    return result


def normalize_trade(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AttributionProjectionError(f"TRADE_OBJECT_REQUIRED:{index}")
    trade = dict(value)
    missing = sorted(REQUIRED_TRADE_FIELDS - set(trade))
    if missing:
        raise AttributionProjectionError(f"TRADE_FIELDS_MISSING:{','.join(missing)}")

    row: dict[str, Any] = {}
    for name in sorted(REQUIRED_TRADE_FIELDS - SHA_FIELDS - {"gross_pnl_r", "fee_r", "slippage_r", "funding_r"}):
        row[name] = require_string(trade[name], f"trades[{index}].{name}")
    for name in sorted(SHA_FIELDS):
        row[name] = require_sha(trade[name], f"trades[{index}].{name}")
    for name in ("gross_pnl_r", "fee_r", "slippage_r", "funding_r"):
        row[name] = require_number(trade[name], f"trades[{index}].{name}")

    cost = row["fee_r"] + row["slippage_r"] + row["funding_r"]
    row["cost_r"] = round(cost, 10)
    row["net_pnl_r"] = round(row["gross_pnl_r"] - cost, 10)
    row["lineage_sha"] = sha256({
        "source_ledger_id": row["source_ledger_id"],
        "source_row_id": row["source_row_id"],
        "source_row_sha": row["source_row_sha"],
        "source_sha": row["source_sha"],
        "candidate_sha": row["candidate_sha"],
        "data_sha": row["data_sha"],
        "window_sha": row["window_sha"],
        "manifest_sha": row["manifest_sha"],
    })
    row["projection_row_sha"] = sha256(row)
    return row


def build_projection(payload: dict[str, Any]) -> dict[str, Any]:
    for key, expected in SAFETY.items():
        if payload.get(key) != expected:
            raise AttributionProjectionError(f"SAFETY_MISMATCH:{key}")
    if payload.get("projection_only") is not True:
        raise AttributionProjectionError("PROJECTION_ONLY_REQUIRED")
    if payload.get("source_ledger_mutated") is not False:
        raise AttributionProjectionError("SOURCE_LEDGER_MUTATION_FORBIDDEN")
    if payload.get("runtime_append_enabled") is not False:
        raise AttributionProjectionError("RUNTIME_APPEND_FORBIDDEN")
    trades = payload.get("trades")
    if not isinstance(trades, list) or not trades:
        raise AttributionProjectionError("TRADES_REQUIRED")

    rows = [normalize_trade(trade, index) for index, trade in enumerate(trades)]
    trade_ids = [row["trade_id"] for row in rows]
    source_rows = [(row["source_ledger_id"], row["source_row_id"]) for row in rows]
    projection_shas = [row["projection_row_sha"] for row in rows]
    if len(set(trade_ids)) != len(trade_ids):
        raise AttributionProjectionError("DUPLICATE_TRADE_ID")
    if len(set(source_rows)) != len(source_rows):
        raise AttributionProjectionError("DUPLICATE_SOURCE_LEDGER_ROW")
    if len(set(projection_shas)) != len(projection_shas):
        raise AttributionProjectionError("DUPLICATE_PROJECTION_ROW")

    aggregation: defaultdict[tuple[str, str], dict[str, float | int]] = defaultdict(
        lambda: {"gross": 0.0, "cost": 0.0, "net": 0.0, "trades": 0}
    )
    dimensions = (
        ("strategy", "strategy_id"),
        ("material", "material_id"),
        ("team", "team"),
        ("symbol", "symbol"),
        ("regime", "regime"),
        ("window", "window_id"),
    )
    for row in rows:
        for dimension, field in dimensions:
            bucket = aggregation[(dimension, row[field])]
            bucket["gross"] = float(bucket["gross"]) + row["gross_pnl_r"]
            bucket["cost"] = float(bucket["cost"]) + row["cost_r"]
            bucket["net"] = float(bucket["net"]) + row["net_pnl_r"]
            bucket["trades"] = int(bucket["trades"]) + 1

    attribution = {
        f"{dimension}:{key}": {
            "gross_pnl_r": round(float(values["gross"]), 10),
            "cost_r": round(float(values["cost"]), 10),
            "net_pnl_r": round(float(values["net"]), 10),
            "trades": int(values["trades"]),
        }
        for (dimension, key), values in sorted(aggregation.items())
    }
    total_net = round(sum(row["net_pnl_r"] for row in rows), 10)
    strategy_net = {
        key.split(":", 1)[1]: values["net_pnl_r"]
        for key, values in attribution.items()
        if key.startswith("strategy:")
    }
    leave_one_out = {
        strategy_id: round(total_net - strategy_value, 10)
        for strategy_id, strategy_value in sorted(strategy_net.items())
    }

    result = {
        "schema_version": "strategy11.attribution_projection.v1",
        "status": "PASS_STRATEGY_ATTRIBUTION_LEDGER",
        "input_sha": sha256(payload),
        "trade_count": len(rows),
        "total_net_pnl_r": total_net,
        "rows": rows,
        "attribution": attribution,
        "leave_one_strategy_out_net_r": leave_one_out,
        "projection_sha": sha256({
            "source_rows": source_rows,
            "projection_rows": projection_shas,
            "attribution": attribution,
        }),
        "pnl_ssot": "SOURCE_LEDGER",
        "projection_only": True,
        "append_only_evidence": True,
        "runtime_append_enabled": False,
        "runtime_bound": False,
        "source_ledger_mutated": False,
        "formal_ledger_mutated": False,
        **SAFETY,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_projection(read_json(args.input))
        write_json(args.output, result)
        print(result["status"])
        return 0
    except Exception as exc:
        write_json(args.output, {
            "schema_version": "strategy11.attribution_projection.v1",
            "status": "HOLD_STRATEGY_ATTRIBUTION_LEDGER",
            "blockers": [str(exc)[:1000]],
            "pnl_ssot": "SOURCE_LEDGER",
            "projection_only": True,
            "runtime_append_enabled": False,
            "runtime_bound": False,
            "source_ledger_mutated": False,
            "formal_ledger_mutated": False,
            **SAFETY,
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
