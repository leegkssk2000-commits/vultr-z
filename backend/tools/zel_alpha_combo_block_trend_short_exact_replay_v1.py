from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import zel_grid_block_trend_short_exact_replay_v1 as generic

VERSION = "ZEL_ALPHA_COMBO_BLOCK_TREND_SHORT_EXACT_REPLAY_V1"
SCHEMA = "zel.alpha_combo.block_trend_short.exact_replay.receipt.v1"


def normalize(receipt: dict[str, Any]) -> dict[str, Any]:
    baseline_censored = sum(
        int(row.get("censored_open_at_window_end") or 0)
        for row in (receipt.get("baseline_meta") or {}).get("lane_receipts", [])
    )
    candidate_censored = sum(
        int(row.get("censored_open_at_window_end") or 0)
        for row in (receipt.get("candidate_meta") or {}).get("lane_receipts", [])
    )
    candidate_pass = bool(receipt.get("candidate_pass")) and baseline_censored == 0 and candidate_censored == 0
    parity_pass = all((receipt.get("terminal_checks") or {}).values()) and all((receipt.get("baseline_parity") or {}).values())
    if candidate_pass:
        state = "PASS_ALPHA_COMBO_BLOCK_TREND_SHORT_EXACT_REPLAY_READY"
        next_step = "ROUTE_TO_ALPHA_COMBO_SEALED_HOLDBACK_WITHOUT_RUNTIME_PROMOTION"
    elif not parity_pass:
        state = "HOLD_ALPHA_COMBO_BLOCK_TREND_SHORT_BASELINE_PARITY_FAILED"
        next_step = "RESOLVE_SINGLE_ALPHA_BASELINE_PARITY_CAUSE"
    elif baseline_censored or candidate_censored:
        state = "HOLD_ALPHA_COMBO_BLOCK_TREND_SHORT_CENSORED_OPEN_REJECTED"
        next_step = "RESOLVE_CENSORED_OPEN_BEFORE_ECONOMIC_EVALUATION"
    else:
        state = "HOLD_ALPHA_COMBO_BLOCK_TREND_SHORT_EXACT_REPLAY_REJECTED"
        next_step = "RETAIN_INCUMBENT_AND_ROUTE_NEXT_ALPHA_SINGLE_AXIS"
    receipt.update(
        {
            "schema_version": SCHEMA,
            "version": VERSION,
            "state": state,
            "candidate_pass": candidate_pass,
            "selected_research_fork": receipt.get("candidate_id") if candidate_pass else None,
            "baseline_censored_open_count": baseline_censored,
            "candidate_censored_open_count": candidate_censored,
            "next": next_step,
            "action": "hold",
        }
    )
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = generic.stable_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--generic-tool",
        type=Path,
        default=Path(__file__).with_name("zel_grid_block_trend_short_exact_replay_v1.py"),
    )
    parser.add_argument(
        "--base-tool",
        type=Path,
        default=Path(__file__).with_name("zel_grid_entry_regime_fork_v1.py"),
    )
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"),
    )
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    receipt = generic.evaluate(
        policy,
        policy_path=args.policy,
        base_tool_path=args.base_tool,
        engine_path=args.engine,
        terminal_root=args.terminal_root,
        data_root=args.data_root,
    )
    receipt = normalize(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "candidate_pass": receipt["candidate_pass"],
                "baseline_trades": receipt["all_windows"]["baseline"]["trade_count"],
                "candidate_trades": receipt["all_windows"]["candidate"]["trade_count"],
                "baseline_censored": receipt["baseline_censored_open_count"],
                "candidate_censored": receipt["candidate_censored_open_count"],
                "windows": {key: value["delta"] for key, value in receipt["windows"].items()},
                "next": receipt["next"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
