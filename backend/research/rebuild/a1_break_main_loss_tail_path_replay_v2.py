#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from backend.research.rebuild import a1_break_main_loss_tail_path_replay_v1 as v1

# Loss-tail pass only: keep the exact parent holding horizon so no candidate can
# gain by waiting for future/unclosed 72h/96h bars. Winner-extension is a later,
# separately validated axis.
v1.TIMEOUT_BARS = (48,)
v1.SCHEMA = "zel.a1.break_main.loss_tail_path_replay.v2"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", default="backend/research/rebuild/a1_break_main_loss_tail_path_replay_v2.json")
    args = p.parse_args()
    if args.self_test:
        raise SystemExit(v1.self_test())
    out = Path(args.out)
    if not out.is_absolute():
        out = v1.ROOT / out
    result = v1.run(out)
    best = result.get("best_candidate")
    if best:
        m = best["metrics"]
        print(
            "PASS_BREAK_MAIN_LOSS_TAIL_CANDIDATE",
            best["candidate_id"],
            f"T={m['completed_trades']}",
            f"WR={m['win_rate']:.6f}",
            f"PNL_BPS={m['net_pnl_bps']:.6f}",
            f"PF={m['profit_factor']:.6f}",
            f"PAYOFF={m['realized_payoff']:.6f}",
            f"DD_BPS={m['max_drawdown_bps']:.6f}",
        )
    else:
        print("KEEP_BREAK_MAIN_NO_VALID_LOSS_TAIL_CANDIDATE")


if __name__ == "__main__":
    main()
