#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "backend/research/prep/g5_economic_evidence_ledger_v1.jsonl"
CONTRACT = ROOT / "backend/research/contracts/g5_exit_research_contract_v1.json"
SCHEMA = "zel.g5.exit_feature_ledger.v1"
ONE_HOUR_MS = 3_600_000
FOUR_HOURS_MS = 14_400_000
FIVE_MIN_MS = 300_000

REQUIRED = (
    "hold_min", "MFE_bps", "MAE_bps", "time_to_MFE_min", "time_to_MAE_min",
    "MFE_before_MAE", "path_efficiency", "realized_path_vol_bps",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RuntimeError(f"OBJECT_REQUIRED:{path}:{n}")
        out.append(row)
    return out


def directional_return(side: str, start_px: float, end_px: float) -> float:
    if side == "long":
        return (end_px / start_px - 1.0) * 10_000.0
    if side == "short":
        return (1.0 - end_px / start_px) * 10_000.0
    raise RuntimeError(f"SIDE_INVALID:{side}")


def horizon_close(path: Mapping[str, Any], target_end_ms: int) -> float | None:
    rows = [x for x in path.get("rows") or [] if isinstance(x, Mapping)]
    eligible = [x for x in rows if int(x["ts_ms"]) + FIVE_MIN_MS <= target_end_ms]
    if not eligible:
        return None
    return float(max(eligible, key=lambda x: int(x["ts_ms"]))["close"])


def enrich_post_exit(feature: dict[str, Any], trade: Mapping[str, Any], provider: ev.MarketProvider, current_ms: int) -> dict[str, Any]:
    out = dict(feature)
    exit_ts = int(trade["exit_ts"])
    side = str(trade["side"])
    exit_px = float(trade["exit"])
    mature_1h = current_ms >= exit_ts + ONE_HOUR_MS
    mature_4h = current_ms >= exit_ts + FOUR_HOURS_MS
    if not (mature_1h or mature_4h):
        out["post_exit_enrichment_pending"] = True
        return out
    end_ms = exit_ts + (FOUR_HOURS_MS if mature_4h else ONE_HOUR_MS)
    try:
        path = provider.path5m(str(trade["symbol"]), exit_ts, end_ms)
    except Exception as exc:
        out["post_exit_enrichment_pending"] = True
        out["post_exit_error"] = f"{type(exc).__name__}:{exc}"[:300]
        return out
    if mature_1h:
        px = horizon_close(path, exit_ts + ONE_HOUR_MS)
        if px is not None:
            out["post_exit_1h_directional_bps"] = directional_return(side, exit_px, px)
    if mature_4h:
        px = horizon_close(path, exit_ts + FOUR_HOURS_MS)
        if px is not None:
            out["post_exit_4h_directional_bps"] = directional_return(side, exit_px, px)
    out["post_exit_path_sha256"] = path.get("path_sha256")
    out["post_exit_enrichment_pending"] = not (
        out.get("post_exit_1h_directional_bps") is not None
        and out.get("post_exit_4h_directional_bps") is not None
    )
    out.pop("post_exit_error", None)
    out.pop("feature_sha256", None)
    out["feature_sha256"] = ev.stable(out)
    return out


def production_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if raw.get("economic_origin") != "FORWARD_REAL" or raw.get("production_grade") is not True:
            continue
        tid = str(raw.get("trade_id") or "")
        if not tid or tid in seen:
            raise RuntimeError(f"PRODUCTION_TRADE_ID_INVALID_OR_DUPLICATE:{tid}")
        seen.add(tid)
        out.append(dict(raw))
    return sorted(out, key=lambda x: (int((x.get("trade") or {}).get("entry_ts") or 0), str(x.get("trade_id") or "")))


def build(rows: Sequence[Mapping[str, Any]], *, provider: ev.MarketProvider | None, current_ms: int) -> dict[str, Any]:
    prod = production_rows(rows)
    features: list[dict[str, Any]] = []
    missing_feature_T = 0
    post_exit_complete_T = 0
    for row in prod:
        trade = row.get("trade") if isinstance(row.get("trade"), Mapping) else {}
        f = row.get("exit_research_features") if isinstance(row.get("exit_research_features"), Mapping) else None
        if f is None:
            missing_feature_T += 1
            features.append({
                "trade_id": row["trade_id"],
                "strategy_id": row.get("strategy_id"),
                "child_id": row.get("child_id"),
                "symbol": trade.get("symbol"),
                "side": trade.get("side"),
                "state": "MISSING_V4_EXIT_RESEARCH_FEATURES__DO_NOT_BACKFILL_AS_FRESH",
                "formal_credit": 0,
            })
            continue
        feature = dict(f)
        if provider is not None:
            feature = enrich_post_exit(feature, trade, provider, current_ms)
        complete = all(feature.get(k) is not None for k in REQUIRED)
        post_complete = feature.get("post_exit_1h_directional_bps") is not None and feature.get("post_exit_4h_directional_bps") is not None
        post_exit_complete_T += int(post_complete)
        item = {
            "trade_id": str(row["trade_id"]),
            "strategy_id": str(row.get("strategy_id") or ""),
            "child_id": str(row.get("child_id") or ""),
            "symbol": str(trade.get("symbol") or ""),
            "side": str(trade.get("side") or ""),
            "signal_ts": int(trade.get("signal_ts") or 0),
            "entry_ts": int(trade.get("entry_ts") or 0),
            "exit_ts": int(trade.get("exit_ts") or 0),
            "gross_bps": trade.get("gross_bps"),
            "net_bps": trade.get("net_bps"),
            "fee_bps": trade.get("fee_bps"),
            "slippage_bps": trade.get("slippage_bps"),
            "funding_bps": trade.get("funding_bps"),
            "feature_complete": complete,
            "post_exit_complete": post_complete,
            "features": feature,
            "source_evidence_row_sha256": row.get("evidence_row_sha256"),
            "formal_credit": 0,
        }
        item["row_sha256"] = ev.stable(item)
        features.append(item)
    complete_T = sum(bool(x.get("feature_complete")) for x in features)
    state = "WAIT_PRODUCTION_FORWARD_REAL_T" if not prod else (
        "WAIT_V4_FEATURE_COMPLETE_T" if complete_T < len(prod) else (
            "G5_EXIT_OBSERVER_DIAGNOSTIC_READY" if complete_T >= 6 else "ACCUMULATE_G5_EXIT_OBSERVER_T"
        )
    )
    out = {
        "schema_version": SCHEMA,
        "state": state,
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "production_forward_real_T": len(prod),
        "feature_complete_T": complete_T,
        "missing_v4_feature_T": missing_feature_T,
        "post_exit_complete_T": post_exit_complete_T,
        "minimum_T_for_family_ranking": 6,
        "minimum_T_for_stability_view": 12,
        "rows": features,
        "g4_reference_used_for_selection": False,
        "proxy_replay_used_for_selection": False,
        "formal_credit": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    out["receipt_sha256"] = ev.stable(out)
    return out


def self_test() -> int:
    fake = {
        "schema_version": ev.EVIDENCE_SCHEMA,
        "economic_origin": "FORWARD_REAL",
        "production_grade": True,
        "trade_id": "t1",
        "strategy_id": "s",
        "child_id": "c",
        "evidence_row_sha256": "e",
        "trade": {"symbol": "BTC-USDT", "side": "long", "signal_ts": 1, "entry_ts": 2, "exit_ts": 3, "gross_bps": 10, "net_bps": 5, "fee_bps": 2, "slippage_bps": 2, "funding_bps": 1, "exit": 100.0},
        "exit_research_features": {"hold_min": 10, "MFE_bps": 20, "MAE_bps": 5, "time_to_MFE_min": 8, "time_to_MAE_min": 2, "MFE_before_MAE": False, "path_efficiency": 0.5, "realized_path_vol_bps": 9, "post_exit_1h_directional_bps": 1, "post_exit_4h_directional_bps": -2},
    }
    out = build([fake], provider=None, current_ms=10)
    assert out["production_forward_real_T"] == 1
    assert out["feature_complete_T"] == 1
    assert out["formal_credit"] == 0 and out["selection_authority"] is False
    assert directional_return("long", 100, 101) > 0
    assert directional_return("short", 100, 99) > 0
    print("PASS_G5_EXIT_FEATURE_LEDGER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=CANONICAL)
    ap.add_argument("--output", type=Path, default=Path("out/g5_exit_feature_ledger_latest_v1.json"))
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    rows = read_jsonl(args.input)
    provider = None if args.no_network else ev.PublicBingXProvider()
    out = build(rows, provider=provider, current_ms=ev.now_ms())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("state", "production_forward_real_T", "feature_complete_T", "post_exit_complete_T")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
