#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory import a1_trendrider_lane_historical_bind_v1 as parent_bind
from backend.research.rebuild import a1_production_highwr_rolling_closed_collector_v1 as v1
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as wr80

SCHEMA = "zel.a1.production_highwr.rolling_closed.v2"
PRIMARY_DESCRIPTOR = v1.ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"


def _historical_primary_anchor(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reproduce the frozen parent boundary: first 24 by immutable entry_ts/symbol order."""
    ordered = sorted(
        (dict(x) for x in rows),
        key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")),
    )
    if len(ordered) < 24:
        raise RuntimeError(f"PRIMARY_PARENT_LT24:{len(ordered)}")
    return ordered[:24]


def _immutable_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return parent_bind._immutable_trade_identity(row)


def _frozen_primary_seed(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    frozen24 = _historical_primary_anchor(rows)
    selected: list[dict[str, Any]] = []
    non_us_count = 0
    anchor_matches = 0
    for row in frozen24:
        identity = _immutable_identity(row)
        is_anchor = identity == parent_bind.PRIMARY_REINTRODUCED_US_TRADE
        if is_anchor:
            anchor_matches += 1
        session = wr80.nonus._session(int(row.get("signal_ts") or 0))
        if session != "US":
            selected.append(dict(row))
            non_us_count += 1
        elif is_anchor:
            selected.append(dict(row))
    return selected, {
        "frozen_parent_count": len(frozen24),
        "non_us_selected_count": non_us_count,
        "reintroduced_us_trade_count": anchor_matches,
    }


def _prospective_primary_rule(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Prospective CLOSED lane rule; enrichment is allowed only for newly observed replay evidence."""
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        session = wr80.nonus._session(int(row.get("signal_ts") or 0))
        if session != "US" or str(row.get("chase_state")) == "COOLING_OR_FLAT":
            out.append(row)
    return out


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


def _assert_primary_seed_descriptor(
    primary_seed: Mapping[str, Any],
    seed: Sequence[Mapping[str, Any]],
    membership_counts: Mapping[str, int],
) -> dict[str, Any]:
    descriptor = _load_primary_descriptor()
    historical = descriptor.get("historical_source") if isinstance(descriptor.get("historical_source"), Mapping) else {}
    membership = descriptor.get("membership_authority") if isinstance(descriptor.get("membership_authority"), Mapping) else {}
    identity = membership.get("immutable_identity_authority") if isinstance(membership.get("immutable_identity_authority"), Mapping) else {}
    expected = descriptor.get("metrics") if isinstance(descriptor.get("metrics"), Mapping) else {}

    checks = {
        "upstream_receipt_sha": str(primary_seed.get("receipt_sha256") or "") == str(historical.get("upstream_receipt_sha256") or ""),
        "upstream_completed_trades": int(primary_seed.get("completed_trades") or 0) == int(membership.get("upstream_completed_trades") or 0) == 25,
        "frozen_prefix_count": int(membership_counts.get("frozen_parent_count") or 0) == int(membership.get("upstream_frozen_prefix_count") or 0) == 24,
        "selected_trade_count": len(seed) == int(membership.get("selected_trades") or 0) == 16,
        "non_us_selected_count": int(membership_counts.get("non_us_selected_count") or 0) == 15,
        "reintroduced_us_trade_count": int(membership_counts.get("reintroduced_us_trade_count") or 0) == 1,
        "legacy_digest_is_non_identity": str(membership.get("selected_trade_receipt_semantics") or "") == "LEGACY_ENRICHED_ROW_SNAPSHOT_NON_IDENTITY",
        "immutable_identity_fields": tuple(identity.get("identity_fields") or ()) == parent_bind.IDENTITY_FIELDS,
        "immutable_anchor": _immutable_identity(identity.get("reintroduced_us_trade") or {}) == parent_bind.PRIMARY_REINTRODUCED_US_TRADE,
        "no_current_feature_membership": identity.get("current_feature_recomputation_required") is False,
    }
    failed = [key for key, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError("PRIMARY_IMMUTABLE_MEMBERSHIP_DRIFT:" + ",".join(failed))

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
    seed, membership_counts = _frozen_primary_seed(raw)
    descriptor = _assert_primary_seed_descriptor(primary_seed, seed, membership_counts)
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
    eligible = v1._ordered(_prospective_primary_rule(current_rows))

    historical = descriptor["historical_source"]
    membership = descriptor["membership_authority"]
    seed_identity = [_immutable_identity(x) for x in seed]
    meta = {
        "boundary_utc": boundary,
        "symbols": list(symbols),
        "policy_path": str(v1.PRIMARY_POLICY.relative_to(v1.ROOT)),
        "historical_parent_order": "ENTRY_TS_SYMBOL_ASC_FIRST24",
        "historical_membership_authority": "IMMUTABLE_TRADE_IDENTITY",
        "historical_lane_membership": "DETERMINISTIC_NON_US_PLUS_EXACT_REINTRODUCED_US_TRADE",
        "prospective_lane_rule": "NON_US_OR_US_CHASE_COOLING_OR_FLAT",
        "exact_parent_descriptor_path": str(PRIMARY_DESCRIPTOR.relative_to(v1.ROOT)),
        "upstream_receipt_sha256": historical["upstream_receipt_sha256"],
        "legacy_enriched_selected_trade_receipt_sha256": membership.get("selected_trade_receipt_sha256"),
        "immutable_seed_trade_identity_sha256": v1._sha(seed_identity),
        "current_feature_recomputation_used_for_frozen_membership": False,
        "prospective_feature_enrichment_used": True,
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
    result["primary_seed_authority"] = "EXACT_PARENT_DESCRIPTOR_PLUS_IMMUTABLE_TRADE_IDENTITY"
    result["primary_historical_economics_rewrite_allowed"] = False
    result["primary_frozen_membership_uses_current_feature_recomputation"] = False
    result["receipt_sha256"] = v1._sha({key: value for key, value in result.items() if key != "receipt_sha256"})
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
    assert [x["exit_ts"] for x in anchor] != sorted(x["exit_ts"] for x in anchor), "test must distinguish entry vs exit ordering"
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
    descriptor = _load_primary_descriptor()
    identity = descriptor["membership_authority"]["immutable_identity_authority"]
    assert tuple(identity["identity_fields"]) == parent_bind.IDENTITY_FIELDS
    assert identity["current_feature_recomputation_required"] is False
    assert parent_bind.self_test() == 0
    assert v1.self_test() == 0
    print("PASS_A1_PRODUCTION_HIGHWR_ROLLING_CLOSED_COLLECTOR_V2_SELF_TEST")
    print("PASS_PRIMARY_FROZEN_MEMBERSHIP_USES_IMMUTABLE_TRADE_IDENTITY")
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
        "lanes": {key: {"state": value["state"], "delta_t": value["delta_t"], "T": value["rolling_completed_trades"]} for key, value in result["lanes"].items()},
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())