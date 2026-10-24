"""Default-OFF 4h research-only three-family signals, not a trading adapter to 15/30m runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import benchmark as engine


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def export(
    folder: Path, *, enabled: bool = False, scope: str = "USED_ARCHIVE_DEV"
) -> dict[str, Any]:
    """No order, source writer, owner mutation, or production/paper authority."""
    if not enabled:
        return {
            "state": "DEFAULT_OFF",
            "signal_T": 0,
            "order_authority": "BLOCKED",
            "formal_g5_credit": 0,
            "market_requests": 0,
        }
    if scope != "USED_ARCHIVE_DEV":
        raise ValueError("FORBIDDEN_FORMAL_OR_LIVE_INPUT_SCOPE")
    spec_raw = (folder / "FREEZE.json").read_bytes()
    spec = json.loads(spec_raw)
    if (
        tuple(s["id"] for s in spec["families"]) != engine.FAMILIES
        or spec["model_bar_minutes"] != 240
        or spec["cost_roundtrip_bps"] != [20, 40]
    ):
        raise ValueError("FROZEN_STRATEGY_SCOPE_CHANGED")
    if (
        sha((Path(spec["model_source_root"]).parent / "MANIFEST.json").read_bytes())
        != spec["manifest_sha256"]
    ):
        raise ValueError("SOURCE_MANIFEST_CHANGED")
    source = Path(spec["model_source_root"])
    out: dict[str, Any] = {
        "state": "OFFLINE_RESEARCH_SIGNAL_EXPORT_ONLY",
        "rule_sha256": sha(spec_raw),
        "native_scap7_15_30_execution_compatible": False,
        "order_authority": "BLOCKED",
        "formal_g5_credit": 0,
        "source_mode": "USED_ARCHIVE_DEV",
        "market_requests": 0,
        "units_verified": False,
        "actual_received_at_verified": False,
        "signals": {},
        "raw_pins_by_symbol": {},
    }
    for sym in spec["symbols"]:
        raw, pins = engine.load_exact_60m(source, sym)
        four = engine.enrich(engine.to_actual_4h(raw))
        rows = four.to_dict("records")
        out["raw_pins_by_symbol"][sym] = pins
        for family in engine.FAMILIES:
            for part, (a, b) in spec["intervals"].items():
                lo, hi = engine.ms(a), engine.ms(b)
                key = part + "_" + family
                dst = out["signals"].setdefault(key, [])
                for i in range(240, len(rows) - 1):
                    stamp = int(rows[i]["close_ts_ms"])
                    if not (lo <= stamp < hi) or not engine.signal_for(family, rows, i):
                        continue
                    stop_mult, max_hold = engine.safety(family)
                    if int(rows[i + 1]["open_ts_ms"]) >= hi:
                        continue
                    px = float(rows[i + 1]["open"])
                    initial_stop = px - stop_mult * float(rows[i]["atr14"])
                    if initial_stop <= 0 or initial_stop >= px:
                        continue
                    dst.append(
                        {
                            "identity": family,
                            "symbol": sym,
                            "side": "long",
                            "timeframe_min": 240,
                            "signal_open_ts_ms": int(rows[i]["open_ts_ms"]),
                            "signal_ts_ms": stamp,
                            "entry_next_bar_open_ts_ms": int(rows[i + 1]["open_ts_ms"]),
                            "model_only_initial_stop": initial_stop,
                            "model_only_initial_entry": px,
                            "max_hold_bars": max_hold,
                            "gross_actual_fill_not_verified": True,
                            "market_source_time_model_only": True,
                        }
                    )
    for key in out["signals"]:
        out["signals"][key].sort(
            key=lambda t: (t["signal_ts_ms"], t["symbol"], t["identity"])
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, required=True)
    ap.add_argument("--enable-used-dev-export", action="store_true")
    args = ap.parse_args()
    value = export(args.folder, enabled=args.enable_used_dev_export)
    if not args.enable_used_dev_export:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return
    original = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
    path = args.folder / "RESEARCH_ONLY_SIGNAL_EXPORT.json"
    with path.open("xb") as file:
        file.write(original)
    print(
        json.dumps(
            {
                "state": value["state"],
                "row_count": sum(map(len, value["signals"].values())),
                "signal_export_sha256": sha(original),
                "by_identity": {k: len(v) for k, v in value["signals"].items()},
                "native_engine_4h_supported": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
