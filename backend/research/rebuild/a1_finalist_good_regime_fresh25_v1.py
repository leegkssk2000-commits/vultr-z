#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow
from backend.research.rebuild import a1_finalist_good_regime_h4_h5_hardening_v1 as hardening
from backend.tools import zel_economic_hardening_gate_v1 as hard

ROOT = Path(__file__).resolve().parents[3]
MIN_TRADES = 25
LIQUID6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TARGETS = {
    "supertrend_pullback_long_reclaim_good_v1": {
        "strategy_id": "supertrend_pullback",
        "policy": ROOT / "backend/research/rebuild/supertrend_pullback_long_reclaim_good_child_policy_v1.py",
        "prereg": ROOT / "backend/research/rebuild/a1_supertrend_long_reclaim_good_prereg_v1.json",
    },
    "trend_ma_macd_ema_fast_up_good_v1": {
        "strategy_id": "trend_ma_macd",
        "policy": ROOT / "backend/research/rebuild/trend_ma_macd_ema_fast_up_good_child_policy_v1.py",
        "prereg": ROOT / "backend/research/rebuild/a1_trendma_ema_fast_up_good_prereg_v1.json",
    },
}
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def _ordered_first25(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(x) for x in rows),
        key=lambda x: (
            int(x.get("exit_ts") or 0), int(x.get("signal_ts") or 0),
            str(x.get("symbol") or ""), int(x.get("entry_ts") or 0),
        ),
    )[:MIN_TRADES]


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    pnl = [float(x.get("net_bps") or 0.0) for x in trades]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    buckets: dict[int, float] = {}
    for trade in trades:
        t = int(trade.get("exit_ts") or 0)
        buckets[t] = buckets.get(t, 0.0) + float(trade.get("net_bps") or 0.0)
    equity = peak = max_dd = 0.0
    for _, value in sorted(buckets.items()):
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "completed_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / n) if n else None,
        "net_pnl_bps": sum(pnl),
        "net_expectancy_bps": (sum(pnl) / n) if n else None,
        "net_profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "realized_exit_bucket_max_drawdown_bps": max_dd,
        "drawdown_ordering_authority": "EXIT_TIMESTAMP_BUCKET_ASC",
    }


def _validate_prereg(identity: str, cfg: Mapping[str, Any]) -> dict[str, Any]:
    prereg = _read(Path(cfg["prereg"]))
    policy = Path(cfg["policy"])
    if prereg.get("state") != "PASS_PREREG_FROZEN":
        raise RuntimeError(f"PREREG_NOT_FROZEN:{identity}")
    if str(prereg.get("candidate_identity")) != identity:
        raise RuntimeError(f"PREREG_IDENTITY_MISMATCH:{identity}")
    if str(prereg.get("transport_strategy_id")) != str(cfg["strategy_id"]):
        raise RuntimeError(f"PREREG_TRANSPORT_MISMATCH:{identity}")
    if tuple(prereg.get("fixed_universe") or []) != LIQUID6:
        raise RuntimeError(f"PREREG_LIQUID6_MISMATCH:{identity}")
    if int(prereg.get("minimum_fresh_trades") or 0) != MIN_TRADES:
        raise RuntimeError(f"PREREG_MIN_SAMPLE_MISMATCH:{identity}")
    if int(prereg.get("exact_first_completed_trades") or 0) != MIN_TRADES:
        raise RuntimeError(f"PREREG_EXACT25_MISMATCH:{identity}")
    if prereg.get("preboundary_outcomes_counted") is not False:
        raise RuntimeError(f"PREREG_PREBOUNDARY_OUTCOME_FAIL:{identity}")
    if prereg.get("numeric_threshold_sweep") is not False:
        raise RuntimeError(f"PREREG_THRESHOLD_SWEEP_FAIL:{identity}")
    if prereg.get("outcome_used_at_runtime") is not False:
        raise RuntimeError(f"PREREG_RUNTIME_OUTCOME_FAIL:{identity}")
    actual_blob = _git_blob_sha(policy)
    if actual_blob != str(prereg.get("policy_blob_sha") or ""):
        raise RuntimeError(f"PREREG_POLICY_BLOB_MISMATCH:{identity}:{actual_blob}:{prereg.get('policy_blob_sha')}")
    return prereg


def run_target(identity: str, now: datetime | None = None) -> dict[str, Any]:
    if identity not in TARGETS:
        raise RuntimeError(f"UNKNOWN_GOOD_CHILD:{identity}")
    cfg = TARGETS[identity]
    prereg = _validate_prereg(identity, cfg)
    boundary = str(prereg["fresh_boundary_utc"])
    boundary_dt = datetime.fromisoformat(boundary.replace("Z", "+00:00"))
    current = now or datetime.now(timezone.utc)

    common: dict[str, Any] = {
        "schema_version": "zel.a1.finalist.good_regime.fresh25.v1",
        "candidate_identity": identity,
        "transport_strategy_id": str(cfg["strategy_id"]),
        "strategy_id": str(cfg["strategy_id"]),
        "policy_path": str(Path(cfg["policy"]).relative_to(ROOT)),
        "policy_blob_sha_preregistered": str(prereg["policy_blob_sha"]),
        "policy_freeze_commit": str(prereg["policy_freeze_commit"]),
        "fresh_boundary_utc": boundary,
        "boundary_utc": boundary,
        "fresh_boundary_rule": str(prereg["fresh_boundary_rule"]),
        "fixed_universe": list(LIQUID6),
        "minimum_fresh_trades": MIN_TRADES,
        "exact_first_completed_trades": MIN_TRADES,
        "preboundary_outcomes_counted": False,
        "preboundary_data_feature_warmup_only": True,
        "post_25_outcomes_ignored": True,
        "parent_preserved": True,
        "parent_h4_h5_reuse_for_promotion": False,
        "identity_specific_hardening_required_after_25": True,
        "numeric_threshold_sweep": False,
        "outcome_used_at_runtime": False,
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        "runtime_good_boost_enabled": False,
        **AUTH,
    }

    if current < boundary_dt:
        common.update({
            "state": "WAIT_FRESH_BOUNDARY",
            "completed_trades": 0,
            "sample_gap_to_25": MIN_TRADES,
            "metrics": _metrics([]),
            "trades": [],
            "source_quality_state": "NOT_RUN_BEFORE_FRESH_BOUNDARY",
            "integrity_defects": [],
            "leakage_lookahead": 0,
            "shadow_replay": None,
            "h4_state": "NOT_RUN_MIN_SAMPLE",
            "h5_state": "NOT_RUN_MIN_SAMPLE",
            "hardening_receipt": None,
            "next": "WAIT_FOR_PREREGISTERED_FRESH_BOUNDARY_THEN_COLLECT_EXACT25",
        })
        common["receipt_sha256"] = hard.stable_sha(common)
        return common

    with tempfile.TemporaryDirectory(prefix=f"{identity}_fresh25_") as td:
        td_path = Path(td)
        raw_path = td_path / "raw.json"
        raw, shadow = run_terminal_shadow(
            strategy_id=str(cfg["strategy_id"]),
            policy_path=Path(cfg["policy"]),
            fresh_boundary_utc=boundary,
            out=raw_path,
            symbols=LIQUID6,
        )
        if str(raw.get("policy_path") or "") != str(Path(cfg["policy"]).relative_to(ROOT)):
            raise RuntimeError(f"GOOD_CHILD_POLICY_PATH_MISMATCH:{identity}:{raw.get('policy_path')}")
        if str(raw.get("boundary_utc") or "") != boundary:
            raise RuntimeError(f"GOOD_CHILD_BOUNDARY_MISMATCH:{identity}")
        defects = list(raw.get("integrity_defects") or [])
        lookahead = int(raw.get("leakage_lookahead") or 0)
        source_quality = raw.get("source_quality_gate") if isinstance(raw.get("source_quality_gate"), Mapping) else {}
        source_state = str(source_quality.get("state") or "")
        if defects or lookahead != 0:
            raise RuntimeError(f"GOOD_CHILD_INTEGRITY_FAIL:{identity}:{defects}:{lookahead}")
        source_symbols = tuple(sorted(str(x) for x in ((raw.get("source") or {}).get("symbols") or [])))
        if source_symbols and source_symbols != tuple(sorted(LIQUID6)):
            raise RuntimeError(f"GOOD_CHILD_SOURCE_UNIVERSE_MISMATCH:{identity}:{source_symbols}")

        raw_trades = [dict(x) for x in (raw.get("trades") or [])]
        trades = _ordered_first25(raw_trades)
        metrics = _metrics(trades)
        completed = len(trades)
        common.update({
            "completed_trades": completed,
            "raw_completed_trades_since_boundary": len(raw_trades),
            "sample_gap_to_25": max(0, MIN_TRADES - completed),
            "metrics": metrics,
            "win_rate": metrics["win_rate"],
            "net_pnl_bps": metrics["net_pnl_bps"],
            "net_expectancy_bps": metrics["net_expectancy_bps"],
            "profit_factor": metrics["net_profit_factor"],
            "max_drawdown_bps": metrics["realized_exit_bucket_max_drawdown_bps"],
            "drawdown_ordering_authority": "EXIT_TIMESTAMP_BUCKET_ASC",
            "source_quality_state": source_state,
            "source_quality_gate": dict(source_quality),
            "integrity_defects": defects,
            "leakage_lookahead": lookahead,
            "trades": trades,
            "source": raw.get("source"),
            "config_sha": raw.get("config_sha"),
            "cost_authority_sha256": raw.get("cost_authority_sha256"),
            "policy_sha": raw.get("policy_sha"),
            "shadow_replay": shadow,
            "h4_state": "NOT_RUN_MIN_SAMPLE",
            "h5_state": "NOT_RUN_MIN_SAMPLE",
            "hardening_receipt": None,
        })

        if source_state == "FAIL":
            state = "HOLD_FRESH_SOURCE_QUALITY"
            nxt = "REPAIR_SOURCE_ONLY_NO_STRATEGY_CHANGE"
        elif completed < MIN_TRADES:
            state = "WAIT_FRESH_25"
            nxt = "CONTINUE_HOURLY_EXACT_FIRST25_COLLECTION"
        elif metrics["net_pnl_bps"] <= 0 or metrics["net_expectancy_bps"] is None or metrics["net_expectancy_bps"] <= 0 or (metrics["net_profit_factor"] is not None and metrics["net_profit_factor"] < 1.0):
            state = "HOLD_FRESH_25_ECONOMICS_NONPOSITIVE"
            nxt = "PRESERVE_PARENT_AND_CHILD_EVIDENCE_DO_NOT_HARDEN_OR_PROMOTE"
        else:
            common["state"] = "READY_IDENTITY_HARDENING"
            common["next"] = "RUN_IDENTITY_SPECIFIC_H4_H5"
            common["receipt_sha256"] = hard.stable_sha({k: v for k, v in common.items() if k != "receipt_sha256"})
            candidate_path = td_path / "candidate.json"
            candidate_path.write_text(json.dumps(common, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            hard_path = td_path / "hardening.json"
            hardened = hardening.run(candidate_path, hard_path)
            common["hardening_receipt"] = hardened
            common["h4_state"] = str((hardened.get("h4_receipt") or {}).get("state") or "")
            common["h5_state"] = str((hardened.get("h5_receipt") or {}).get("state") or "")
            if hardened.get("state") == "PASS_GOOD_REGIME_IDENTITY_HARDENING":
                state = "PASS_GOOD_REGIME_FRESH_SURVIVOR_GATE"
                nxt = "ROUTE_NEXT_GATE_WITHOUT_PROMOTION_AUTHORITY"
            else:
                state = "HOLD_GOOD_REGIME_FRESH_HARDENING"
                nxt = "PRESERVE_PARENT_AND_CHILD_EVIDENCE_NO_PROMOTION"

        common["state"] = state
        common["next"] = nxt
        common["receipt_sha256"] = hard.stable_sha({k: v for k, v in common.items() if k != "receipt_sha256"})
        return common


def run(out: Path, now: datetime | None = None) -> dict[str, Any]:
    results = {identity: run_target(identity, now=now) for identity in TARGETS}
    payload = {
        "schema_version": "zel.a1.finalist.good_regime.fresh25.bundle.v1",
        "state": "PASS_GOOD_REGIME_FRESH25_BUNDLE_ACTIVE",
        "fixed_universe": list(LIQUID6),
        "fresh_boundary_utc": "2026-08-23T18:00:00Z",
        "exact_first_completed_trades": MIN_TRADES,
        "targets": results,
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        "runtime_good_boost_enabled": False,
        **AUTH,
    }
    payload["receipt_sha256"] = hard.stable_sha(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def self_test() -> int:
    for identity, cfg in TARGETS.items():
        prereg = _validate_prereg(identity, cfg)
        assert prereg["fresh_boundary_utc"] == "2026-08-23T18:00:00Z"
    fake = [
        {"exit_ts": 3, "signal_ts": 1, "symbol": "BTC-USDT", "entry_ts": 2, "net_bps": -10},
        {"exit_ts": 2, "signal_ts": 1, "symbol": "ETH-USDT", "entry_ts": 2, "net_bps": 30},
    ]
    ordered = _ordered_first25(fake)
    assert ordered[0]["exit_ts"] == 2
    m = _metrics(ordered)
    assert m["completed_trades"] == 2 and m["net_pnl_bps"] == 20.0 and m["win_rate"] == 0.5
    future = datetime(2026, 8, 23, 17, 0, tzinfo=timezone.utc)
    r = run_target("trend_ma_macd_ema_fast_up_good_v1", now=future)
    assert r["state"] == "WAIT_FRESH_BOUNDARY" and r["completed_trades"] == 0
    assert r["preboundary_outcomes_counted"] is False
    print("PASS_A1_FINALIST_GOOD_REGIME_FRESH25_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_good_regime_fresh25_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "targets": {
            k: {
                "state": v["state"], "completed_trades": v["completed_trades"],
                "sample_gap_to_25": v["sample_gap_to_25"], "win_rate": v.get("win_rate"),
                "net_pnl_bps": v.get("net_pnl_bps"), "h4_state": v["h4_state"], "h5_state": v["h5_state"],
                "next": v["next"],
            }
            for k, v in result["targets"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
