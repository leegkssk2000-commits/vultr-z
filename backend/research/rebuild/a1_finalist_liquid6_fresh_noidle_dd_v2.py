#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_finalist_liquid6_fresh_noidle_v1 as base
from backend.research.rebuild.a1_multisymbol_realized_dd_v1 import realized_drawdown_bps

DD_FIELD = "realized_exit_bucket_max_drawdown_bps"
DD_AUTHORITY = "EXIT_TIMESTAMP_BUCKET_ASC"
_original_metric = base.metric


def authoritative_metric(receipt: Mapping[str, Any], key: str) -> float | None:
    if key == "max_drawdown_bps":
        trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
        return float(realized_drawdown_bps(trades))
    return _original_metric(receipt, key)


def relabel_dd(result: dict[str, Any]) -> dict[str, Any]:
    targets = result.get("targets") if isinstance(result.get("targets"), dict) else {}
    for row in targets.values():
        if not isinstance(row, dict):
            continue
        retro = row.get("retrospective_liquid6_qualifier")
        fresh = row.get("fresh")
        for section in (retro, fresh):
            if not isinstance(section, dict):
                continue
            value = section.pop("max_drawdown_bps", None)
            section[DD_FIELD] = value
            section["drawdown_ordering_authority"] = DD_AUTHORITY
            section["legacy_symbol_append_dd_used"] = False
    result["drawdown_integrity"] = {
        "state": "PASS_MULTISYMBOL_REALIZED_DD_AUTHORITY_BOUND",
        "authoritative_field": DD_FIELD,
        "ordering_authority": DD_AUTHORITY,
        "simultaneous_exit_ordering": "NET_PNL_AGGREGATED_PER_EXIT_TS",
        "append_order_independent": True,
        "legacy_symbol_append_dd_used": False,
    }
    return result


def run(out: Path) -> dict[str, Any]:
    base.metric = authoritative_metric
    try:
        result = base.run(out)
    finally:
        base.metric = _original_metric
    result = relabel_dd(result)
    result["receipt_sha256"] = base.stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake = {
        "trades": [
            {"symbol": "BTC-USDT", "exit_ts": 2, "net_bps": 100.0},
            {"symbol": "BTC-USDT", "exit_ts": 4, "net_bps": -120.0},
            {"symbol": "ETH-USDT", "exit_ts": 1, "net_bps": -100.0},
            {"symbol": "ETH-USDT", "exit_ts": 3, "net_bps": 150.0},
        ],
        "metrics": {"max_drawdown_bps": 220.0, "net_pnl_bps": 30.0},
    }
    assert authoritative_metric(fake, "max_drawdown_bps") == 120.0
    assert authoritative_metric(fake, "net_pnl_bps") == 30.0
    sample = {
        "targets": {
            "x": {
                "retrospective_liquid6_qualifier": {"max_drawdown_bps": 120.0},
                "fresh": {"max_drawdown_bps": 10.0},
            }
        }
    }
    relabel_dd(sample)
    assert sample["targets"]["x"]["fresh"][DD_FIELD] == 10.0
    assert "max_drawdown_bps" not in sample["targets"]["x"]["fresh"]
    assert sample["drawdown_integrity"]["append_order_independent"] is True
    print("PASS_A1_FINALIST_LIQUID6_FRESH_NOIDLE_DD_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_liquid6_fresh_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "dd_authority": result["drawdown_integrity"],
        "targets": {
            sid: {
                "state": row["state"],
                "boundary": row["frozen_liquid6_fresh_boundary_utc"],
                "retro_trades": row["retrospective_liquid6_qualifier"]["completed_trades"],
                "retro_realized_dd_bps": row["retrospective_liquid6_qualifier"][DD_FIELD],
                "fresh_trades": row["fresh"]["completed_trades"],
                "fresh_realized_dd_bps": row["fresh"][DD_FIELD],
                "fresh_max_loss_streak": row["fresh"]["max_consecutive_losses"],
                "stall": row["pace"]["sample_stall_triggered"],
            }
            for sid, row in result["targets"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
