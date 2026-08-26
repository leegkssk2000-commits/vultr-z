#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_production_highwr_rolling_closed_collector_v1 as v1
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as wr80

SCHEMA = "zel.a1.production_highwr.rolling_closed.v2"


def _historical_primary_anchor(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reproduce the immutable Primary 81.25 lane authority: entry_ts/symbol first 24."""
    ordered = sorted(
        (dict(x) for x in rows),
        key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")),
    )
    if len(ordered) < 24:
        raise RuntimeError(f"PRIMARY_PARENT_LT24:{len(ordered)}")
    return ordered[:24]


def _primary_rule(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(x) for x in rows
        if str(x.get("session")) != "US" or str(x.get("chase_state")) == "COOLING_OR_FLAT"
    ]


def _primary_source(primary_seed: Mapping[str, Any], lane: Mapping[str, Any]):
    if str(primary_seed.get("strategy_id")) != "trend_rider" or int(primary_seed.get("completed_trades") or 0) != 25:
        raise RuntimeError("PRIMARY_SEED_25T_REQUIRED")

    raw = [dict(x) for x in primary_seed.get("trades") or []]
    frozen24 = _historical_primary_anchor(raw)
    wr80._enrich(dict(primary_seed), frozen24)
    if any(bool(x.get("feature_missing")) for x in frozen24):
        raise RuntimeError("PRIMARY_SEED_FEATURE_MISSING")
    seed = _primary_rule(frozen24)
    defects = v1._validate_seed_headline(lane, seed)
    if defects:
        raise RuntimeError("PRIMARY_SEED_HEADLINE_MISMATCH:" + ";".join(defects))

    boundary = str(primary_seed.get("boundary_utc") or "")
    symbols = v1._source_symbols(primary_seed)
    if not boundary or not symbols:
        raise RuntimeError("PRIMARY_SEED_SOURCE_BINDING_MISSING")

    current = v1._run_replay("trend_rider", v1.PRIMARY_POLICY, boundary, symbols)
    current_rows = [dict(x) for x in current.get("trades") or []]
    wr80._enrich(current, current_rows)
    if any(bool(x.get("feature_missing")) for x in current_rows):
        raise RuntimeError("PRIMARY_CURRENT_FEATURE_MISSING")

    # Re-prove that the immutable historical 16T anchor is still reproduced exactly.
    current_anchor = _primary_rule(_historical_primary_anchor(current_rows))
    seed_ids = {v1.a4.trade_identity(x) for x in seed}
    current_anchor_ids = {v1.a4.trade_identity(x) for x in current_anchor}
    if current_anchor_ids != seed_ids:
        raise RuntimeError(
            "PRIMARY_IMMUTABLE_ANCHOR_DRIFT:"
            f"seed={v1._sha(sorted(seed_ids))}:current={v1._sha(sorted(current_anchor_ids))}"
        )

    eligible = v1._ordered(_primary_rule(current_rows))
    meta = {
        "boundary_utc": boundary,
        "symbols": list(symbols),
        "policy_path": str(v1.PRIMARY_POLICY.relative_to(v1.ROOT)),
        "historical_parent_order": "ENTRY_TS_SYMBOL_ASC_FIRST24",
        "historical_lane_rule": "session!=US OR chase_state==COOLING_OR_FLAT",
        "immutable_anchor_trade_identity_sha256": v1._sha(sorted(seed_ids)),
    }
    return seed, eligible, meta


def run(primary_seed_path: Path, broad_artifact_dir: Path, out: Path, previous_path: Path | None = None) -> dict[str, Any]:
    # v1 owns append-only merge/metrics/source bindings; v2 replaces only the proven-wrong Primary seed ordering.
    original = v1._primary_source
    v1._primary_source = _primary_source
    try:
        result = v1.run(primary_seed_path, broad_artifact_dir, out, previous_path)
    finally:
        v1._primary_source = original

    result["schema_version"] = SCHEMA
    result["compat_base_schema"] = v1.SCHEMA
    result["primary_seed_authority"] = "ENTRY_TS_SYMBOL_ASC_FIRST24"
    result["receipt_sha256"] = v1._sha({k: val for k, val in result.items() if k != "receipt_sha256"})
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    rows = [
        {"entry_ts": 30 - i, "symbol": f"S{i:02d}", "exit_ts": i}
        for i in range(25)
    ]
    anchor = _historical_primary_anchor(rows)
    expected = sorted(rows, key=lambda x: (x["entry_ts"], x["symbol"]))[:24]
    assert [(x["entry_ts"], x["symbol"]) for x in anchor] == [(x["entry_ts"], x["symbol"]) for x in expected]
    assert [(x["exit_ts"]) for x in anchor] != sorted(x["exit_ts"] for x in anchor), "test must distinguish entry vs exit ordering"
    assert v1.self_test() == 0
    print("PASS_A1_PRODUCTION_HIGHWR_ROLLING_CLOSED_COLLECTOR_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary-seed", type=Path)
    ap.add_argument("--broad-artifact-dir", type=Path)
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_production_highwr_rolling_closed_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.primary_seed is None or args.broad_artifact_dir is None:
        raise SystemExit("PRIMARY_SEED_AND_BROAD_ARTIFACT_DIR_REQUIRED")
    result = run(args.primary_seed, args.broad_artifact_dir, args.out, args.previous)
    print(json.dumps({
        "state": result["state"],
        "schema": result["schema_version"],
        "total_delta_t": result["total_delta_t"],
        "lanes": {k: {"state": v["state"], "delta_t": v["delta_t"], "T": v["rolling_completed_trades"]} for k, v in result["lanes"].items()},
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
