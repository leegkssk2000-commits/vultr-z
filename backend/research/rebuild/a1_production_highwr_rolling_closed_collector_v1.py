#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from backend.research.rebuild import a1_a4_exact_parent_repair_batch_v1 as a4
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as wr80
from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/rebuild/a1_production_highwr_top5_ssot_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
BREAK_MAIN = ROOT / "backend/research/rebuild/a1_break_and_continue_production_main_v1.json"
A4_LATEST = ROOT / "backend/research/rebuild/a1_a4_exact_parent_repair_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_production_highwr_rolling_closed_latest.json"
SCHEMA = "zel.a1.production_highwr.rolling_closed.v1"
SOURCE_KIND = "PROSPECTIVE_POLICY_REPLAY_CLOSED"
VALUE_SEMANTICS = "FIRST_OBSERVED_REPLAY_VALUE_SEALED"
PRIMARY_POLICY = ROOT / "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py"
A4_SYMBOLS = (
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "1INCH-USDT", "ETHFI-USDT",
    "HYPE-USDT", "BCH-USDT", "APE-USDT", "1000PEPE-USDT", "DOGE-USDT", "LINK-USDT",
)
EXPECTED_LANES = (
    "trend_rider_primary_wr8125",
    "trend_rider_broad_wr7000",
    "break_and_continue_main",
    "keltner_trend_main",
    "supertrend_pullback_main",
)
CLOSED_IDENTITY_FIELDS = (
    "symbol",
    "signal_ts",
    "entry_ts",
    "exit_ts",
    "side",
)
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _immutable_trade_identity(trade: Mapping[str, Any]) -> dict[str, Any]:
    return {field: trade.get(field) for field in CLOSED_IDENTITY_FIELDS}


def _immutable_trade_key(trade: Mapping[str, Any]) -> str:
    return _sha(_immutable_trade_identity(trade))


def _trade_id(lane_id: str, trade: Mapping[str, Any]) -> str:
    return _sha({"lane_id": lane_id, **_immutable_trade_identity(trade)})


def _seal_trade(lane_id: str, trade: Mapping[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(dict(trade))
    row["closed_trade_id"] = _trade_id(lane_id, row)
    row["lane_id"] = lane_id
    row["value_semantics"] = VALUE_SEMANTICS
    return row


def _ordered(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(x) for x in rows),
        key=lambda x: (
            int(x.get("exit_ts") or 0), int(x.get("signal_ts") or 0),
            str(x.get("symbol") or ""), int(x.get("entry_ts") or 0), str(x.get("intent_sha") or ""),
        ),
    )


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = _ordered(rows)
    values = [float(x.get("net_bps") or 0.0) for x in ordered]
    wins = [x for x in values if x > 0.0]
    losses = [-x for x in values if x < 0.0]
    buckets: dict[int, float] = {}
    for row in ordered:
        ts = int(row.get("exit_ts") or 0)
        buckets[ts] = buckets.get(ts, 0.0) + float(row.get("net_bps") or 0.0)
    equity = peak = dd = 0.0
    for ts in sorted(buckets):
        equity += buckets[ts]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "completed_trades": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "max_drawdown_bps": dd,
        "drawdown_ordering_authority": "EXIT_TIMESTAMP_BUCKET_ASC",
    }


def _source_symbols(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    source = receipt.get("source") if isinstance(receipt.get("source"), Mapping) else {}
    raw = source.get("symbols") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            name = str(item.get("symbol") or "").strip()
        else:
            name = str(item).strip()
        if name:
            out.append(name)
    return tuple(dict.fromkeys(out))


def _lane_rows(ssot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {
        str(x.get("lane_id")): dict(x)
        for x in ssot.get("production_top5") or []
        if isinstance(x, Mapping) and x.get("lane_id")
    }
    if tuple(rows) != EXPECTED_LANES:
        raise RuntimeError(f"TOP5_LANE_ORDER_DRIFT:{tuple(rows)}")
    return rows


def _validate_seed_headline(lane: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], *, pnl_tol: float = 0.05) -> list[str]:
    stats = _metrics(rows)
    defects: list[str] = []
    expected_n = int(lane.get("completed_trades") or 0)
    expected_wins = int(lane.get("wins") or round(float(lane.get("win_rate") or 0.0) * expected_n))
    if stats["completed_trades"] != expected_n:
        defects.append(f"SEED_COUNT:{stats['completed_trades']}!={expected_n}")
    if stats["wins"] != expected_wins:
        defects.append(f"SEED_WINS:{stats['wins']}!={expected_wins}")
    expected_wr = lane.get("win_rate")
    if expected_wr is not None and stats["win_rate"] is not None and abs(float(stats["win_rate"]) - float(expected_wr)) > 1e-12:
        defects.append(f"SEED_WR:{stats['win_rate']}!={expected_wr}")
    expected_pnl = lane.get("net_pnl_bps")
    if expected_pnl is not None and abs(float(stats["net_pnl_bps"]) - float(expected_pnl)) > pnl_tol:
        defects.append(f"SEED_PNL:{stats['net_pnl_bps']}!={expected_pnl}")
    return defects


def _inventory_policy(strategy_id: str) -> Path:
    inv = _read(INVENTORY)
    row = (inv.get("strategies") or {}).get(strategy_id)
    if not isinstance(row, Mapping):
        raise RuntimeError(f"INVENTORY_STRATEGY_MISSING:{strategy_id}")
    path = ROOT / str(row.get("policy_owner") or "")
    if not path.is_file():
        raise RuntimeError(f"POLICY_OWNER_MISSING:{strategy_id}:{path}")
    return path


def _canonical_boundary(strategy_id: str) -> str:
    ledger = _read(LEDGER)
    row = (ledger.get("strategies") or {}).get(strategy_id)
    if not isinstance(row, Mapping):
        raise RuntimeError(f"LEDGER_STRATEGY_MISSING:{strategy_id}")
    boundary = str(row.get("prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError(f"PROSPECTIVE_BOUNDARY_MISSING:{strategy_id}")
    return boundary


def _run_replay(strategy_id: str, policy_path: Path, boundary: str, symbols: Sequence[str]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"rolling_closed_{strategy_id}_") as td:
        out = Path(td) / "receipt.json"
        receipt, _ = run_terminal_shadow(
            strategy_id=strategy_id,
            policy_path=policy_path,
            fresh_boundary_utc=boundary,
            out=out,
            symbols=symbols,
        )
    if list(receipt.get("integrity_defects") or []):
        raise RuntimeError(f"REPLAY_INTEGRITY:{strategy_id}:{receipt.get('integrity_defects')}")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError(f"REPLAY_LOOKAHEAD:{strategy_id}")
    source_gate = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
    if str(source_gate.get("state") or "") == "FAIL":
        raise RuntimeError(f"REPLAY_SOURCE_QUALITY:{strategy_id}:{source_gate.get('defects')}")
    return receipt


def _find_receipt_by_sha(root: Path, receipt_sha: str, completed: int) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in root.rglob("*.json"):
        try:
            obj = _read(path)
        except Exception:
            continue
        stack: list[Any] = [obj]
        while stack:
            item = stack.pop()
            if isinstance(item, Mapping):
                if str(item.get("receipt_sha256") or "") == receipt_sha and int(item.get("completed_trades") or 0) == completed:
                    matches.append(dict(item))
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    unique = {_sha(x): x for x in matches}
    if len(unique) != 1:
        raise RuntimeError(f"EXACT_SEED_RECEIPT_REQUIRED:{receipt_sha}:{len(unique)}")
    return next(iter(unique.values()))


def _candidate(repair: Mapping[str, Any], strategy_id: str, candidate_id: str) -> dict[str, Any]:
    strategy = (repair.get("strategies") or {}).get(strategy_id)
    if not isinstance(strategy, Mapping):
        raise RuntimeError(f"A4_STRATEGY_MISSING:{strategy_id}")
    rows = [dict(x) for x in strategy.get("candidates") or [] if isinstance(x, Mapping)]
    matches = [x for x in rows if str(x.get("candidate_id")) == candidate_id]
    if len(matches) != 1:
        raise RuntimeError(f"A4_SOURCE_CANDIDATE_REQUIRED:{strategy_id}:{candidate_id}:{len(matches)}")
    return matches[0]


def _identity_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return a4.stable(sorted(a4.trade_identity(x) for x in rows))


def _first_identity_prefix(rows: Sequence[Mapping[str, Any]], n: int, expected_digest: str) -> list[dict[str, Any]]:
    ordered = _ordered(rows)
    if len(ordered) < n:
        raise RuntimeError(f"REGENERATED_SEED_TOO_SHORT:{len(ordered)}<{n}")
    seed = ordered[:n]
    digest = _identity_digest(seed)
    if digest != expected_digest:
        raise RuntimeError(f"REGENERATED_SEED_IDENTITY_MISMATCH:{digest}!={expected_digest}")
    return seed


def _primary_source(primary_seed: Mapping[str, Any], lane: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if str(primary_seed.get("strategy_id")) != "trend_rider" or int(primary_seed.get("completed_trades") or 0) != 25:
        raise RuntimeError("PRIMARY_SEED_25T_REQUIRED")
    seed_raw = _ordered([dict(x) for x in primary_seed.get("trades") or []])
    # Historical authority is the first 24 parent trades, then the frozen non-US OR US chase-cooling rule.
    frozen24 = seed_raw[:24]
    wr80._enrich(dict(primary_seed), frozen24)
    if any(bool(x.get("feature_missing")) for x in frozen24):
        raise RuntimeError("PRIMARY_SEED_FEATURE_MISSING")
    seed = [x for x in frozen24 if str(x.get("session")) != "US" or str(x.get("chase_state")) == "COOLING_OR_FLAT"]
    defects = _validate_seed_headline(lane, seed)
    if defects:
        raise RuntimeError("PRIMARY_SEED_HEADLINE_MISMATCH:" + ";".join(defects))

    boundary = str(primary_seed.get("boundary_utc") or "")
    symbols = _source_symbols(primary_seed)
    if not boundary or not symbols:
        raise RuntimeError("PRIMARY_SEED_SOURCE_BINDING_MISSING")
    current = _run_replay("trend_rider", PRIMARY_POLICY, boundary, symbols)
    current_rows = _ordered([dict(x) for x in current.get("trades") or []])
    wr80._enrich(current, current_rows)
    if any(bool(x.get("feature_missing")) for x in current_rows):
        raise RuntimeError("PRIMARY_CURRENT_FEATURE_MISSING")
    eligible = [x for x in current_rows if str(x.get("session")) != "US" or str(x.get("chase_state")) == "COOLING_OR_FLAT"]
    meta = {"boundary_utc": boundary, "symbols": list(symbols), "policy_path": str(PRIMARY_POLICY.relative_to(ROOT))}
    return seed, eligible, meta


def _broad_source(artifact_dir: Path, lane: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    receipt_sha = str(lane.get("source_receipt_sha256") or "")
    seed_receipt = _find_receipt_by_sha(artifact_dir, receipt_sha, int(lane["completed_trades"]))
    seed = _ordered([dict(x) for x in seed_receipt.get("trades") or []])
    defects = _validate_seed_headline(lane, seed)
    if defects:
        raise RuntimeError("BROAD_SEED_HEADLINE_MISMATCH:" + ";".join(defects))
    policy_raw = str(seed_receipt.get("policy_path") or "")
    policy = ROOT / policy_raw
    boundary = str(seed_receipt.get("boundary_utc") or "")
    symbols = _source_symbols(seed_receipt)
    if not policy.is_file() or not boundary or not symbols:
        raise RuntimeError("BROAD_SEED_SOURCE_BINDING_MISSING")
    current = _run_replay("trend_rider", policy, boundary, symbols)
    eligible = _ordered([dict(x) for x in current.get("trades") or []])
    meta = {"boundary_utc": boundary, "symbols": list(symbols), "policy_path": policy_raw, "seed_receipt_sha256": receipt_sha}
    return seed, eligible, meta


def _break_source(lane: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    source = _read(BREAK_MAIN)
    seed = _ordered([dict(x) for x in source.get("trades") or []])
    defects = _validate_seed_headline(lane, seed)
    if defects:
        raise RuntimeError("BREAK_SEED_HEADLINE_MISMATCH:" + ";".join(defects))
    boundary = str(source.get("boundary_utc") or "")
    symbols = _source_symbols(source) or A4_SYMBOLS
    current = _run_replay("break_and_continue", _inventory_policy("break_and_continue"), boundary, symbols)
    eligible = [dict(x) for x in current.get("trades") or [] if a4.keep_session_price_discovery(x, {}, {})]
    seed_ids = {_immutable_trade_key(x) for x in seed}
    current_ids = {_immutable_trade_key(x) for x in eligible}
    if len(seed_ids) != len(seed):
        raise RuntimeError("BREAK_SEED_IMMUTABLE_IDENTITY_DUPLICATE")
    if not seed_ids.issubset(current_ids):
        raise RuntimeError("BREAK_SEED_NOT_SUBSET_OF_CURRENT_REPLAY_IMMUTABLE_IDENTITY")
    meta = {
        "boundary_utc": boundary,
        "symbols": list(symbols),
        "axis": "SESSION_PRICE_DISCOVERY_OWNER_ONLY",
        "seed_membership_authority": "IMMUTABLE_CLOSED_TRADE_IDENTITY",
    }
    return seed, _ordered(eligible), meta


def _a4_candidate_economics_defects(
    lane: Mapping[str, Any], candidate: Mapping[str, Any], seed: Sequence[Mapping[str, Any]], *, tol: float = 1e-6,
) -> list[str]:
    defects = _validate_seed_headline(lane, seed, pnl_tol=tol)
    observed = _metrics(seed)
    expected = candidate.get("metrics") if isinstance(candidate.get("metrics"), Mapping) else {}
    pairs = (
        ("completed_trades", "trades"),
        ("win_rate", "win_rate"),
        ("net_pnl_bps", "net_pnl_bps"),
        ("net_expectancy_bps", "net_expectancy_bps"),
        ("profit_factor", "profit_factor"),
        ("payoff", "payoff"),
        ("max_drawdown_bps", "drawdown_bps"),
    )
    for observed_key, expected_key in pairs:
        got = observed.get(observed_key)
        want = expected.get(expected_key)
        if observed_key == "completed_trades":
            if int(got or 0) != int(want or 0):
                defects.append(f"CANDIDATE_{observed_key}:{got}!={want}")
        elif got is None or want is None:
            if got != want:
                defects.append(f"CANDIDATE_{observed_key}:{got}!={want}")
        elif abs(float(got) - float(want)) > tol:
            defects.append(f"CANDIDATE_{observed_key}:{got}!={want}")
    return defects


def _a4_display_source(lane: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    strategy_id = str(lane["strategy_id"])
    candidate_id = str(lane.get("source_candidate_id") or "")
    repair = _read(A4_LATEST)
    candidate = _candidate(repair, strategy_id, candidate_id)
    expected_digest = str(candidate.get("trade_identity_sha256") or "")
    expected_n = int(lane.get("completed_trades") or 0)
    if str(candidate.get("candidate_sha256") or "") != str(lane.get("source_candidate_sha256") or ""):
        raise RuntimeError(f"A4_SOURCE_CANDIDATE_SHA_DRIFT:{strategy_id}")
    if str(candidate.get("parent_receipt_sha256") or "") != str(lane.get("source_parent_receipt_sha256") or ""):
        raise RuntimeError(f"A4_SOURCE_PARENT_SHA_DRIFT:{strategy_id}")
    if int(candidate.get("completed_trades") or 0) != expected_n:
        raise RuntimeError(f"A4_SOURCE_CANDIDATE_COUNT_DRIFT:{strategy_id}")
    boundary = _canonical_boundary(strategy_id)
    current = _run_replay(strategy_id, _inventory_policy(strategy_id), boundary, A4_SYMBOLS)
    eligible = _ordered([dict(x) for x in current.get("trades") or [] if a4.keep_session_price_discovery(x, {}, {})])
    if len(eligible) < expected_n:
        raise RuntimeError(f"REGENERATED_SEED_TOO_SHORT:{len(eligible)}<{expected_n}")
    seed = eligible[:expected_n]
    immutable_ids = {_immutable_trade_key(x) for x in seed}
    if len(immutable_ids) != expected_n:
        raise RuntimeError(f"A4_SEED_IMMUTABLE_IDENTITY_DUPLICATE:{strategy_id}")
    legacy_digest = _identity_digest(seed)
    legacy_digest_match = legacy_digest == expected_digest
    if not legacy_digest_match:
        defects = _a4_candidate_economics_defects(lane, candidate, seed)
        if defects:
            raise RuntimeError(f"A4_IMMUTABLE_REBIND_ECONOMICS_MISMATCH:{strategy_id}:" + ";".join(defects))
        membership_authority = "EXACT_CANDIDATE_METADATA_PLUS_IMMUTABLE_PREFIX_PLUS_ECONOMIC_EQUIVALENCE"
    else:
        membership_authority = "LEGACY_A4_TRADE_IDENTITY_DIGEST"
    meta = {
        "boundary_utc": boundary,
        "symbols": list(A4_SYMBOLS),
        "axis": "SESSION_PRICE_DISCOVERY_OWNER_ONLY",
        "source_candidate_id": candidate_id,
        "source_candidate_sha256": candidate.get("candidate_sha256"),
        "source_parent_receipt_sha256": candidate.get("parent_receipt_sha256"),
        "source_trade_identity_sha256": expected_digest,
        "legacy_trade_identity_digest_match": legacy_digest_match,
        "seed_membership_authority": membership_authority,
        "closed_identity_fields": list(CLOSED_IDENTITY_FIELDS),
        "display_only": True,
    }
    return seed, eligible, meta


def _previous_lane(previous: Mapping[str, Any] | None, lane_id: str) -> dict[str, Any] | None:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return None
    row = (previous.get("lanes") or {}).get(lane_id)
    return dict(row) if isinstance(row, Mapping) else None


def _merge_lane(
    lane: Mapping[str, Any], seed: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]],
    source_meta: Mapping[str, Any], previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    lane_id = str(lane["lane_id"])
    previous_trades = [dict(x) for x in (previous or {}).get("closed_trades") or [] if isinstance(x, Mapping)]
    if previous_trades:
        known = {_trade_id(lane_id, x): _seal_trade(lane_id, x) for x in previous_trades}
        seed_state = "REUSED_PREVIOUS_APPEND_ONLY_STATE"
    else:
        known = {_trade_id(lane_id, x): _seal_trade(lane_id, x) for x in seed}
        seed_state = "INITIALIZED_FROM_EXACT_FROZEN_SEED"

    current_by_id = {_trade_id(lane_id, x): dict(x) for x in current}
    missing_known = sorted(set(known) - set(current_by_id))
    seed_ids = {_trade_id(lane_id, x) for x in seed}
    if not seed_ids.issubset(set(known)):
        raise RuntimeError(f"PREVIOUS_STATE_DROPPED_SEED:{lane_id}")

    new_ids = sorted(set(current_by_id) - set(known))
    for tid in new_ids:
        known[tid] = _seal_trade(lane_id, current_by_id[tid])
    combined = _ordered(known.values())
    last_close = max((int(x.get("exit_ts") or 0) for x in combined), default=0)
    rolling = _metrics(combined)
    state = "PASS_ROLLING_CLOSED_APPENDED" if new_ids else "PASS_ROLLING_CLOSED_NO_DELTA"
    if missing_known:
        # API visibility may eventually roll old trades out. Persisted append-only state remains authoritative;
        # this is diagnostic only and must never delete already sealed CLOSED rows.
        state = "PASS_ROLLING_CLOSED_APPEND_ONLY_WITH_REPLAY_WINDOW_ROLLOFF"
    return {
        "lane_id": lane_id,
        "strategy_id": lane.get("strategy_id"),
        "role": lane.get("role"),
        "source_kind": SOURCE_KIND,
        "source_meta": dict(source_meta),
        "source_provenance_status": lane.get("source_provenance_status"),
        "production_headline_eligible": bool(lane.get("production_headline_eligible")),
        "challenger_parent_eligible": bool(lane.get("challenger_parent_eligible")),
        "formal_promotion_eligible": bool(lane.get("formal_promotion_eligible", lane.get("challenger_parent_eligible"))),
        "seed_state": seed_state,
        "seed_completed_trades": int(lane.get("completed_trades") or 0),
        "frozen_headline_metrics": {k: lane.get(k) for k in (
            "completed_trades", "wins", "win_rate", "net_pnl_bps", "net_expectancy_bps",
            "max_drawdown_bps", "profit_factor", "payoff",
        )},
        "delta_t": len(new_ids),
        "delta_reason": "APPENDED_NEW_CLOSED" if new_ids else "NO_NEW_CLOSED_IDENTITY",
        "new_closed_trade_ids": new_ids,
        "replay_window_missing_known_count": len(missing_known),
        "last_verified_close_ts": last_close or None,
        "rolling_metrics": rolling,
        "rolling_completed_trades": rolling["completed_trades"],
        "closed_trades": combined,
        "value_semantics": VALUE_SEMANTICS,
        "closed_identity_fields": list(CLOSED_IDENTITY_FIELDS),
        "state": state,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }


def run(primary_seed_path: Path, broad_artifact_dir: Path, out: Path, previous_path: Path | None = None) -> dict[str, Any]:
    ssot = _read(SSOT)
    lanes = _lane_rows(ssot)
    primary_seed = _read(primary_seed_path)
    previous = _read(previous_path) if previous_path and previous_path.is_file() else (_read(LATEST) if LATEST.is_file() else None)

    sources: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]] = {}
    sources[EXPECTED_LANES[0]] = _primary_source(primary_seed, lanes[EXPECTED_LANES[0]])
    sources[EXPECTED_LANES[1]] = _broad_source(broad_artifact_dir, lanes[EXPECTED_LANES[1]])
    sources[EXPECTED_LANES[2]] = _break_source(lanes[EXPECTED_LANES[2]])
    sources[EXPECTED_LANES[3]] = _a4_display_source(lanes[EXPECTED_LANES[3]])
    sources[EXPECTED_LANES[4]] = _a4_display_source(lanes[EXPECTED_LANES[4]])

    lane_out: dict[str, Any] = {}
    for lane_id in EXPECTED_LANES:
        seed, current, meta = sources[lane_id]
        lane_out[lane_id] = _merge_lane(lanes[lane_id], seed, current, meta, _previous_lane(previous, lane_id))

    total_delta = sum(int(x["delta_t"]) for x in lane_out.values())
    display_only_delta = sum(
        int(x["delta_t"]) for x in lane_out.values() if not bool(x.get("challenger_parent_eligible"))
    )
    payload = {
        "schema_version": SCHEMA,
        "state": "PASS_HIGHWR_ROLLING_CLOSED_ACTIVE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "selection_unit": "lane_id",
        "source_kind": SOURCE_KIND,
        "economic_value_semantics": VALUE_SEMANTICS,
        "append_only": True,
        "stable_identity_dedup": True,
        "closed_trade_identity_authority": "LANE_PLUS_IMMUTABLE_CLOSED_EXECUTION_TUPLE",
        "closed_trade_identity_fields": ["lane_id", *CLOSED_IDENTITY_FIELDS],
        "headline_ssot_mutated": False,
        "rolling_receipt_grants_promotion": False,
        "total_delta_t": total_delta,
        "display_only_delta_t": display_only_delta,
        "lane_count": len(lane_out),
        "lanes": lane_out,
        **AUTH,
    }
    payload["receipt_sha256"] = _sha({k: v for k, v in payload.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def self_test() -> int:
    assert EXPECTED_LANES[0] != EXPECTED_LANES[1]
    a = {"symbol": "BTC-USDT", "signal_ts": 1, "entry_ts": 2, "exit_ts": 3, "side": "long", "intent_sha": "x", "feature_sha": "f1", "net_bps": 10.0}
    b = dict(a)
    b["intent_sha"] = "changed"
    b["feature_sha"] = "changed"
    b["net_bps"] = 999.0
    assert _trade_id("lane", a) == _trade_id("lane", b), "feature/intent/economic replay drift must not change CLOSED identity"
    assert _immutable_trade_key(a) == _immutable_trade_key(b), "immutable source membership must ignore enrichment hashes"
    assert _trade_id("lane-a", a) != _trade_id("lane-b", a), "same strategy trade may belong to distinct production lanes"
    assert _trade_id("lane", a) != _trade_id("lane", {**a, "exit_ts": 4}), "different CLOSED execution must remain distinct"
    m = _metrics([a, {**a, "signal_ts": 4, "entry_ts": 5, "exit_ts": 6, "intent_sha": "y", "net_bps": -4.0}])
    assert m["completed_trades"] == 2 and m["wins"] == 1 and abs(float(m["net_pnl_bps"]) - 6.0) < 1e-12
    lane = {"lane_id": "lane", "strategy_id": "s", "role": "MAIN", "completed_trades": 1, "wins": 1, "win_rate": 1.0, "net_pnl_bps": 10.0, "production_headline_eligible": True, "challenger_parent_eligible": True}
    merged = _merge_lane(lane, [a], [b, {**a, "signal_ts": 4, "entry_ts": 5, "exit_ts": 6, "intent_sha": "y", "net_bps": 5.0}], {}, None)
    assert merged["delta_t"] == 1 and merged["rolling_completed_trades"] == 2
    assert merged["selection_authority"] is False and merged["promotion_authority"] is False
    print("PASS_A1_PRODUCTION_HIGHWR_ROLLING_CLOSED_COLLECTOR_V1_SELF_TEST")
    print("PASS_IMMUTABLE_CLOSED_IDENTITY_IGNORES_INTENT_FEATURE_ECONOMIC_DRIFT")
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
        "total_delta_t": result["total_delta_t"],
        "lanes": {k: {"state": v["state"], "delta_t": v["delta_t"], "T": v["rolling_completed_trades"]} for k, v in result["lanes"].items()},
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
