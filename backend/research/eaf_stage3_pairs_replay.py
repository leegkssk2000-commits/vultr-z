#!/usr/bin/env python3
"""EAF Stage3 two-leg replay adapter contract.

Research-only. This module intentionally does not generate pair signals yet. It proves
that pair data are aligned in an isolated two-leg lane before EAF_PSA_V1 is tested.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

BAR_MS = 15 * 60 * 1000
REQ = ("timestamp_ms", "open", "high", "low", "close", "volume")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if tuple(r.fieldnames or ()) != REQ:
            raise SystemExit(f"BAD_SCHEMA:{path}:{r.fieldnames}")
        last = None
        seen = set()
        for n, x in enumerate(r, 2):
            try:
                ts = int(x["timestamp_ms"])
                o, h, l, c, v = (float(x[k]) for k in REQ[1:])
            except Exception as exc:
                raise SystemExit(f"BAD_ROW:{path}:{n}:{exc}")
            if ts in seen:
                raise SystemExit(f"DUP_TS:{path}:{ts}")
            if last is not None and ts <= last:
                raise SystemExit(f"NON_MONOTONIC:{path}:{ts}")
            if not (h >= max(o, c, l) and l <= min(o, c, h)):
                raise SystemExit(f"BAD_OHLC:{path}:{n}")
            if v < 0:
                raise SystemExit(f"BAD_VOLUME:{path}:{n}")
            seen.add(ts); last = ts
            rows.append({"timestamp_ms": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    if not rows:
        raise SystemExit(f"EMPTY:{path}")
    return rows


def validate_two_leg(left: Path, right: Path) -> dict:
    a = _load(left); b = _load(right)
    bm = {x["timestamp_ms"]: x for x in b}
    common = [x["timestamp_ms"] for x in a if x["timestamp_ms"] in bm]
    if len(common) < 2:
        raise SystemExit("PAIR_ALIGNMENT_EMPTY")
    gaps = sum(1 for x, y in zip(common, common[1:]) if y - x != BAR_MS)
    return {
        "schema_version": "zel.eaf.stage3.pairs_adapter.v1",
        "state": "PASS_TWO_LEG_ADAPTER_CONTRACT" if gaps == 0 else "HOLD_PAIR_DATA_GAPS",
        "research_only": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "selection_authority": False,
        "promotion_authority": False,
        "signal_generation_enabled": False,
        "adapter_requirement": "multi_asset_two_leg_replay",
        "left": {"path": str(left), "rows": len(a), "sha256": _sha256(left)},
        "right": {"path": str(right), "rows": len(b), "sha256": _sha256(right)},
        "aligned_rows": len(common),
        "first_timestamp_ms": common[0],
        "last_timestamp_ms": common[-1],
        "gap_count": gaps,
        "next": "pair formation/trading windows and sourced all-in two-leg cost model required before EAF_PSA_V1 signal testing",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", required=True, type=Path)
    ap.add_argument("--right", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ns = ap.parse_args()
    out = validate_two_leg(ns.left, ns.right)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, sort_keys=True))
    if out["state"] != "PASS_TWO_LEG_ADAPTER_CONTRACT":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
