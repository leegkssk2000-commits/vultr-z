from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_active5_lifecycle_overlay_v2 as life
from backend.research.rebuild.policy_kernel_v1 import ema, atr

MODES = (
    "v5_current",
    "strong025_all",
    "strong050_all",
    "strict_core_plus_strong050_other",
)


def btc_feature(bars: list[dict[str, Any]]) -> dict[int, tuple[int, float]]:
    closes = [float(x["close"]) for x in bars]
    e = ema(closes, 50)
    out = {}
    for i, b in enumerate(bars):
        if i < 50:
            continue
        a = atr(bars[: i + 1], 14)
        c = closes[i]
        st = (
            1
            if c > e[i] and e[i] > e[i - 1]
            else (-1 if c < e[i] and e[i] < e[i - 1] else 0)
        )
        out[int(b["ts_ms"])] = (st, abs(c - e[i]) / max(a, 1e-12))
    return out


def allow(
    t: dict[str, Any], feat: dict[int, tuple[int, float]], mode: str, sid: str
) -> bool:
    keys = [k for k in feat if k <= int(t["signal_ts"])]
    if not keys:
        return False
    st, dist = feat[max(keys)]
    side = 1 if t["side"] == "long" else -1
    core = sid in {"break_and_continue", "trend_ma_macd", "trend_rider"}
    if mode == "v5_current":
        return (st == side) if core else True
    if mode == "strict_core_plus_strong050_other":
        return (st == side) if core else not (st == -side and dist >= 0.50)
    thr = 0.25 if mode == "strong025_all" else 0.50
    return not (st == -side and dist >= thr)


def main() -> int:
    bars = life.bars6()
    feat = btc_feature(bars["BTC-USDT"])
    res = {
        "schema": "zel.a1.active5.market_state_scan.v1",
        "research_only": True,
        "modes": {},
    }
    for mode in MODES:
        rows = []
        vals = []
        for sid, path in life.SOURCES.items():
            d = json.loads(path.read_text())
            tr = sorted(
                d.get("trades") or [],
                key=lambda x: (int(x["exit_ts"]), str(x["symbol"])),
            )
            base = life.BASE_RULE[sid]
            extra = life.CANDIDATES["late_scratch"]
            for t in tr:
                if not allow(t, feat, mode, sid):
                    continue
                rows.append(t)
                vals.append(life.simulate(t, bars[str(t["symbol"])], base, extra))
        order = sorted(
            range(len(rows)),
            key=lambda i: (int(rows[i]["exit_ts"]), str(rows[i]["symbol"])),
        )
        sr = [rows[i] for i in order]
        sv = [vals[i] for i in order]
        res["modes"][mode] = life.split(sr, sv)
        print(
            "STATE_SCAN",
            mode,
            json.dumps(res["modes"][mode], sort_keys=True),
            flush=True,
        )
    out = Path("/home/z/z/runtime/active5_market_state_scan_v1/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
