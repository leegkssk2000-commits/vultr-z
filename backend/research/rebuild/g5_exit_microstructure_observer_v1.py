#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as base
from backend.research.rebuild import g5_forward_real_evidence_bridge_v3 as v3
from backend.research.rebuild.g5_forward_real_evidence_bridge_v4 import ExitResearchBingXProvider

ROOT = Path(__file__).resolve().parents[3]
BRIDGE_STATE = ROOT / "backend/research/rebuild/g5_forward_real_bridge_state_v1.jsonl"
SAMPLE_KIND = "OPEN_MICROSTRUCTURE_SAMPLE"
MIN_SAMPLE_GAP_MS = 30 * 60 * 1000


def last_samples(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        if row.get("kind") != SAMPLE_KIND:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        tid = str(payload.get("trade_id") or "")
        ts = int(payload.get("observed_at_ms") or row.get("event_ts_ms") or 0)
        if tid:
            out[tid] = max(out.get(tid, 0), ts)
    return out


def sample_open_positions(
    rows: list[dict[str, Any]], *, provider: Any, current_ms: int, min_gap_ms: int = MIN_SAMPLE_GAP_MS
) -> tuple[list[dict[str, Any]], int, list[str]]:
    base.validate_bridge_chain(rows)
    opens, _ = v3.retry_safe_open_index(rows)
    latest = last_samples(rows)
    appended = 0
    errors: list[str] = []
    for tid, opened in sorted(opens.items()):
        if current_ms - latest.get(tid, 0) < min_gap_ms:
            continue
        try:
            depth = provider.depth(str(opened["symbol"]), float(opened["notional"]))
            payload = {
                "trade_id": tid,
                "strategy_id": str(opened.get("strategy_id") or ""),
                "child_id": str(opened.get("child_id") or ""),
                "symbol": str(opened["symbol"]),
                "side": str(opened["side"]),
                "entry_ts": int(opened["entry_ts"]),
                "observed_at_ms": int(depth["observed_at_ms"]),
                "bid": float(depth["bid"]),
                "ask": float(depth["ask"]),
                "mid": float(depth["mid"]),
                "top5_bid_notional": depth.get("top5_bid_notional"),
                "top5_ask_notional": depth.get("top5_ask_notional"),
                "book_imbalance": depth.get("top5_book_imbalance"),
                "snapshot_sha256": depth.get("snapshot_sha256"),
                "observer_only": True,
                "formal_credit": 0,
            }
            base.bridge_event(rows, kind=SAMPLE_KIND, payload=payload, event_ts_ms=int(depth["observed_at_ms"]))
            appended += 1
        except Exception as exc:
            errors.append(f"{tid}:{type(exc).__name__}:{exc}"[:400])
    base.validate_bridge_chain(rows)
    return rows, appended, errors


class FakeProvider:
    def depth(self, symbol: str, reference_notional: float) -> dict[str, Any]:
        row = {
            "symbol": symbol, "observed_at_ms": 2_000_000, "bid": 99.0, "ask": 101.0, "mid": 100.0,
            "top5_bid_notional": 600.0, "top5_ask_notional": 400.0, "top5_book_imbalance": 0.2,
        }
        row["snapshot_sha256"] = base.stable(row)
        return row


def self_test() -> int:
    rows: list[dict[str, Any]] = []
    base.bridge_event(rows, kind="OPENED_PROVENANCE", payload={
        "trade_id": "t1", "strategy_id": "s", "child_id": "c", "symbol": "BTC-USDT", "side": "long",
        "entry_ts": 1_000_000, "notional": 10_000.0,
    }, event_ts_ms=1_000_000)
    rows, appended, errors = sample_open_positions(rows, provider=FakeProvider(), current_ms=2_000_000, min_gap_ms=1)
    assert appended == 1 and not errors
    assert rows[-1]["kind"] == SAMPLE_KIND
    rows2, appended2, _ = sample_open_positions(rows, provider=FakeProvider(), current_ms=2_000_001, min_gap_ms=10_000)
    assert appended2 == 0 and len(rows2) == len(rows)
    print("PASS_G5_EXIT_MICROSTRUCTURE_OBSERVER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=BRIDGE_STATE)
    ap.add_argument("--output", type=Path, default=Path("out/g5_forward_real_bridge_state_v1.jsonl"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    rows = base.read_jsonl(args.input)
    rows, appended, errors = sample_open_positions(rows, provider=ExitResearchBingXProvider(), current_ms=base.now_ms())
    base.write_jsonl(args.output, rows)
    print(json.dumps({"open_sample_appended_T": appended, "sample_errors": errors, "formal_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
