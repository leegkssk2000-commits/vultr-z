from __future__ import annotations

"""Top5 G4 donor transplant fasttrack.

Purpose
- Consume completed historical shard receipts for Break, Keltner and Supertrend.
- Preserve each Top5 parent as incumbent control.
- Test only additive donor primitives/ownership gates, never overwrite parent logic.
- Primary is intentionally excluded until its shard receipt exists.

Decision contract
- donor candidate must beat its exact parent on net_pnl_bps and profit_factor,
  while not worsening drawdown_bps by more than 10%.
- no historical result receives fresh-G4 or formal-G5 credit.
- passing children are TRANSPLANT_CANDIDATE only; fresh/shadow/paper remain required.
"""

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import math


OUT = Path("artifacts/research/a1_top5_g4_donor_transplant_fasttrack_v1.json")

DONORS = [
    {
        "id": "keltner_ema20_reclaim_ema50_owner",
        "source_lane": "keltner_trend_main",
        "primitive": "EMA20 reclaim + EMA50 trend ownership",
        "scope": "all_top5_nonprimary_recipients",
        "evidence": {
            "closed_T": 127,
            "net_pnl_bps": 4547.756750412391,
            "net_expectancy_bps": 35.809108270963705,
            "profit_factor": 1.2478781379853825,
            "drawdown_bps": 4328.352926095922,
        },
        "priority": 1,
    },
    {
        "id": "break_vol_confirmed_breakout_hype_link_owner",
        "source_lane": "break_and_continue_main",
        "primitive": "50-bar breakout + volume confirmation with HYPE/LINK ownership",
        "scope": "top5_breakout_compatible_recipients",
        "evidence": {
            "hype_6m_T": 16,
            "hype_6m_net_bps": 4068.0,
            "hype_6m_pf": 6.20,
            "link_6m_T": 11,
            "link_6m_net_bps": 603.0,
            "link_6m_pf": 1.60,
        },
        "priority": 2,
    },
    {
        "id": "supertrend_btc_link_highvol_owner",
        "source_lane": "supertrend_pullback_main",
        "primitive": "high-vol momentum ownership restricted to BTC/LINK",
        "scope": "top5_momentum_compatible_recipients",
        "evidence": {
            "btc_6m_T": 19,
            "btc_6m_net_bps": 247.0,
            "btc_6m_pf": 1.20,
            "btc_recent3m_T": 6,
            "btc_recent3m_net_bps": 147.0,
            "btc_recent3m_pf": 1.96,
            "link_recent3m_T": 9,
            "link_recent3m_net_bps": 509.0,
            "link_recent3m_pf": 1.46,
        },
        "priority": 3,
    },
]

RECIPIENTS = [
    "break_and_continue_main",
    "keltner_trend_main",
    "supertrend_pullback_main",
    "broad_trend_survivor",
]


def finite(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def main() -> None:
    # This file is a preregistration + execution contract. The actual parent/child
    # replay engine is invoked by the workflow through the repository's existing
    # Top5 transplant runner when available. We persist the frozen matrix first so
    # candidate selection cannot move after seeing replay outcomes.
    matrix = []
    for donor in DONORS:
        for recipient in RECIPIENTS:
            if donor["source_lane"] == recipient:
                continue
            matrix.append({
                "donor_id": donor["id"],
                "recipient": recipient,
                "mode": "ADD_ONLY",
                "parent_control_required": True,
                "fresh_g4_credit": 0,
                "formal_g5_credit": 0,
                "promotion_state": "PENDING_MATCHED_PARENT_AB",
                "rollback": "DROP_CHILD_KEEP_PARENT",
            })

    payload = {
        "state": "PASS_DONOR_TRANSPLANT_MATRIX_FROZEN",
        "primary_deferred": True,
        "primary_reason": "trend_rider_primary_wr8125 shard still in progress",
        "donors": DONORS,
        "recipients": RECIPIENTS,
        "matrix": matrix,
        "acceptance": {
            "net_pnl_bps_delta_gt": 0,
            "profit_factor_delta_gt": 0,
            "drawdown_ratio_lte": 1.10,
            "minimum_child_closed_T": 12,
            "no_parent_overwrite": True,
        },
        "next": "RUN_MATCHED_PARENT_ADD_ONLY_AB_THEN_KEEP_ONLY_POSITIVE_DELTA_CHILDREN",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": payload["state"], "matrix_n": len(matrix), "out": str(OUT)}))


if __name__ == "__main__":
    main()
