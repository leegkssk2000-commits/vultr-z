#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil
from backend.research.rebuild import a1_production_highwr_rolling_closed_collector_v1 as v1
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as wr80

SCHEMA = "zel.a1.production_highwr.rolling_closed.v2"
PRIMARY_DESCRIPTOR = v1.ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"


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


def _historical_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(x.get("net_bps") or 0.0) for x in rows]
    wins = [x for x in values if x > 0.0]
    losses = [-x for x in values if x < 0.0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    equity = peak = dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "completed_trades": len(values),
        "wins": len(wins),
        "win_rate": len(wins) / len(values) if values else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "max_drawdown_bps": dd,
        "profit_factor": gp / gl if gl > 0 else None,
        "payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
    }


def _load_primary_descriptor() -> dict[str, Any]:
    descriptor = v1._read(PRIMARY_DESCRIPTOR)
    if descriptor.get("schema_version") != "zel.a1.trend_rider.wr8125.exact_parent.v1":
        raise RuntimeError("PRIMARY_DESCRIPTOR_SCHEMA_DRIFT")
    if descriptor.get("state") != "EXACT_HISTORICAL_PARENT_FROZEN":
        raise RuntimeError("PRIMARY_DESCRIPTOR_STATE_DRIFT")
    if descriptor.get("lane_id") != "trend_rider_primary_wr8125" or descriptor.get("strategy_id") != "trend_rider":
        raise RuntimeError("PRIMARY_DESCRIPTOR_IDENTITY_DRIFT")
    if descriptor.get("selection_authority") is not False or descriptor.get("promotion_authority") is not False:
        raise RuntimeError("PRIMARY_DESCRIPTOR_AUTHORITY_DRIFT")
    if str(descriptor.get("execution_authority")) != "NONE" or str(descriptor.get("order_authority")) != "BLOCKED" or str(descriptor.get("live_trade_authority")) != "BLOCKED":
        raise RuntimeError("PRIMARY_DESCRIPTOR_EXECUTION_AUTHORITY_DRIFT")
    return descriptor


def _assert_primary_seed_descriptor(primary_seed: Mapping[str, Any], seed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    descriptor = _load_primary_descriptor()
    historical = descriptor.get("historical_source") if isinstance(descriptor.get("historical_source"), Mapping) else {}
    membership = descriptor.get("membership_authority") if isinstance(descriptor.get("membership_authority"), Mapping) else {}
    expected = descriptor.get("metrics") if isinstance(descriptor.get("metrics"), Mapping) else {}

    if str(primary_seed.get("receipt_sha256") or "") != str(historical.get("upstream_receipt_sha256") or ""):
        raise RuntimeError("PRIMARY_UPSTREAM_RECEIPT_SHA_DRIFT")
    if int(primary_seed.get("completed_trades") or 0) != int(membership.get("upstream_completed_trades") or 0):
        raise RuntimeError("PRIMARY_UPSTREAM_T_DRIFT")
    selected_digest = hashutil.sha([dict(x) for x in seed])
    if selected_digest != str(membership.get("selected_trade_receipt_sha256") or ""):
        raise RuntimeError(
            "PRIMARY_SELECTED_TRADE_RECEIPT_DRIFT:"
            f"{selected_digest}!={membership.get('selected_trade_receipt_sha256')}"
        )

    observed = _historical_metrics(seed)
    tolerances = {
        "completed_trades": 0.0,
        "wins": 0.0,
        "win_rate": 1e-12,
        "net_pnl_bps": 1e-9,
        "net_expectancy_bps": 1e-9,
        "max_drawdown_bps": 1e-9,
        "profit_factor": 1e-9,
        "payoff": 1e-9,
    }
    defects: list[str] = []
    for key, tol in tolerances.items():
        got, want = observed.get(key), expected.get(key)
        if key in ("completed_trades", "wins"):
            if int(got or 0) != int(want or 0):
                defects.append(f"{key}:{got}!={want}")
        elif got is None or want is None or abs(float(got) - float(want)) > tol:
            defects.append(f"{key}:{got}!={want}")
    if defects:
        raise RuntimeError("PRIMARY_DESCRIPTOR_METRIC_DRIFT:" + ";".join(defects))
    return descriptor


def _primary_source(primary_seed: Mapping[str, Any], lane: Mapping[str, Any]):
    if str(primary_seed.get("strategy_id")) != "trend_rider" or int(primary_seed.get("completed_trades") or 0) != 25:
        raise RuntimeError("PRIMARY_SEED_25T_REQUIRED")

    raw = [dict(x) for x in primary_seed.get("trades") or []]
    frozen24 = _historical_primary_anchor(raw)
    wr80._enrich(dict(primary_seed), frozen24)
    if any(bool(x.get("feature_missing")) for x in frozen24):
        raise RuntimeError("PRIMARY_SEED_FEATURE_MISSING")
    seed = _primary_rule(frozen24)
    descriptor = _assert_primary_seed_descriptor(primary_seed, seed)
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

    # Re-prove immutable membership by trade identity. Current replay economics are never allowed
    # to rewrite the historical seed's sealed values.
    current_anchor = _primary_rule(_historical_primary_anchor(current_rows))
    seed_ids = {v1.a4.trade_identity(x) for x in seed}
    current_anchor_ids = {v1.a4.trade_identity(x) for x in current_anchor}
    if current_anchor_ids != seed_ids:
        raise RuntimeError(
            "PRIMARY_IMMUTABLE_ANCHOR_DRIFT:"
            f"seed={v1._sha(sorted(seed_ids))}:current={v1._sha(sorted(current_anchor_ids))}"
        )

    eligible = v1._ordered(_primary_rule(current_rows))
    historical = descriptor["historical_source"]
    membership = descriptor["membership_authority"]
    meta = {
        "boundary_utc": boundary,
        "symbols": list(symbols),
        "policy_path": str(v1.PRIMARY_POLICY.relative_to(v1.ROOT)),
        "historical_parent_order": "ENTRY_TS_SYMBOL_ASC_FIRST24",
        "historical_lane_rule": "session!=US OR chase_state==COOLING_OR_FLAT",
        "exact_parent_descriptor_path": str(PRIMARY_DESCRIPTOR.relative_to(v1.ROOT)),
        "upstream_receipt_sha256": historical["upstream_receipt_sha256"],
        "selected_trade_receipt_sha256": membership["selected_trade_receipt_sha256"],
        "immutable_anchor_trade_identity_sha256": v1._sha(sorted(seed_ids)),
        "historical_economics_rewrite_allowed": False,
    }
    return seed, eligible, meta


def _previous_for_v1(previous: Mapping[str, Any]) -> dict[str, Any]:
    """Project a persisted v2 receipt onto the v1 merge schema without touching sealed lane data."""
    compat = dict(previous)
    schema = str(compat.get("schema_version") or "")
    if schema == SCHEMA:
        compat["schema_version"] = v1.SCHEMA
    elif schema != v1.SCHEMA:
        raise RuntimeError(f"PREVIOUS_SCHEMA_UNSUPPORTED:{schema}")
    return compat


def run(primary_seed_path: Path, broad_artifact_dir: Path, out: Path, previous_path: Path | None = None) -> dict[str, Any]:
    # v1 owns append-only merge/metrics/source bindings; v2 replaces only the Primary seed authority.
    previous_for_v1 = previous_path
    with tempfile.TemporaryDirectory(prefix="a1-highwr-prev-") as td:
        if previous_path is not None and previous_path.is_file():
            previous = _previous_for_v1(v1._read(previous_path))
            previous_for_v1 = Path(td) / "previous_v1_compat.json"
            previous_for_v1.write_text(
                json.dumps(previous, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )

        original = v1._primary_source
        v1._primary_source = _primary_source
        try:
            result = v1.run(primary_seed_path, broad_artifact_dir, out, previous_for_v1)
        finally:
            v1._primary_source = original

    result["schema_version"] = SCHEMA
    result["compat_base_schema"] = v1.SCHEMA
    result["primary_seed_authority"] = "EXACT_PARENT_DESCRIPTOR_PLUS_ENTRY_TS_SYMBOL_ASC_FIRST24"
    result["primary_historical_economics_rewrite_allowed"] = False
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
    stats = _historical_metrics([
        {"net_bps": 100.0}, {"net_bps": -40.0}, {"net_bps": 60.0}, {"net_bps": -10.0},
    ])
    assert stats["completed_trades"] == 4 and stats["wins"] == 2
    assert abs(float(stats["net_pnl_bps"]) - 110.0) < 1e-12
    assert abs(float(stats["max_drawdown_bps"]) - 40.0) < 1e-12
    sample_previous = {
        "schema_version": SCHEMA,
        "lanes": {"lane": {"closed_trades": [{"closed_trade_id": "sealed"}]}},
    }
    compat = _previous_for_v1(sample_previous)
    assert compat["schema_version"] == v1.SCHEMA
    assert compat["lanes"]["lane"]["closed_trades"][0]["closed_trade_id"] == "sealed"
    assert sample_previous["schema_version"] == SCHEMA
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
