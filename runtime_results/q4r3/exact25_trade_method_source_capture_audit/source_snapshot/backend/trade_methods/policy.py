from __future__ import annotations

POLICY = {
    "fit_tier": {
        "S": {"pair_conf_min": 90, "venue_health_min": 90, "decay_pct_max": 6},
        "A": {"pair_conf_min": 80, "venue_health_min": 80, "decay_pct_max": 10},
        "B": {"pair_conf_min": 65, "venue_health_min": 70, "decay_pct_max": 18},
        "C": {"pair_conf_min": 0, "venue_health_min": 0, "decay_pct_max": 100},
    },
    "intuition": {
        "calm_max": 35,
        "uneasy_max": 69,
    },
    "consensus": {
        "high_min": 75,
        "medium_min": 55,
    },
    "action_gate": {
        "block_if_venue_health_lte": 45,
        "route_change_if_decay_gte": 18,
        "reduce25_if_uneasy_and_fit_lte": "B",
        "partial30_if_decay_gte": 12,
    },
}

# >>> H74TM8_SINGLE_PATCH_WITH_BACKUP

import copy
import re
from typing import Any, Dict, Iterable, Optional

H74TM8_TRADE_METHOD_POLICY = {
  "authority": {
    "execution_authority": "none",
    "live_execution_allowed": False,
    "order_authority": "blocked",
    "paper_execution_allowed": False,
    "registry_enabled": False
  },
  "base_tp_r": 2.5,
  "combo_filter": {
    "allow_full_count": 3,
    "allow_full_items": [
      {
        "action": "hold",
        "decision": "ALLOW_FULL_BASE25",
        "n": 36,
        "size_multiplier": 1.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "fvg_revert_legendary",
        "target_r": 2.5,
        "why": "strong combo; base25_total 42.700031 > policy_total 32.025023; pf=7.469702; wr=66.6667%"
      },
      {
        "action": "hold",
        "decision": "ALLOW_FULL_BASE25",
        "n": 36,
        "size_multiplier": 1.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "sr_levels_legendary",
        "target_r": 2.5,
        "why": "strong combo; base25_total 42.700031 > policy_total 32.025023; pf=7.469702; wr=66.6667%"
      },
      {
        "action": "hold",
        "decision": "ALLOW_FULL_BASE25",
        "n": 33,
        "size_multiplier": 1.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "liquidity_sweep_legendary",
        "target_r": 2.5,
        "why": "strong combo; base25_total 47.2 > policy_total 35.4; pf=11.727273; wr=75.7576%"
      }
    ],
    "allow_full_strategies": [
      "fvg_revert_legendary",
      "liquidity_sweep_legendary",
      "sr_levels_legendary"
    ],
    "allow_policy_count": 3,
    "allow_policy_items": [
      {
        "action": "hold",
        "decision": "ALLOW_POLICY",
        "n": 23,
        "size_multiplier": "policy",
        "skills": [
          "unclassified"
        ],
        "strategy": "unknown_strategy",
        "target_r": "policy",
        "why": "policy positive and improves total/DD; delta=-2.225009; pdd=3.025; bdd=6.05"
      },
      {
        "action": "hold",
        "decision": "ALLOW_POLICY",
        "n": 42,
        "size_multiplier": "policy",
        "skills": [
          "unclassified"
        ],
        "strategy": "trend_ma_macd",
        "target_r": "policy",
        "why": "policy positive and improves total/DD; delta=-2.7; pdd=1.375; bdd=2.75"
      },
      {
        "action": "hold",
        "decision": "ALLOW_POLICY",
        "n": 77,
        "size_multiplier": "policy",
        "skills": [
          "unclassified"
        ],
        "strategy": "vwap_revert",
        "target_r": "policy",
        "why": "policy positive and improves total/DD; delta=-7.625004; pdd=1.4; bdd=2.8"
      }
    ],
    "allow_policy_strategies": [
      "trend_ma_macd",
      "unknown_strategy",
      "vwap_revert"
    ],
    "block_count": 15,
    "block_items": [
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 66,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "anchor_vwap_trend_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.231495; wr=9.0909%; pf=0.058838"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 52,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "fvg_revert_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.250962; wr=1.9231%; pf=0.069519"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 52,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "sr_levels_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.250962; wr=1.9231%; pf=0.069519"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 70,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "rr275_vwap_reclaim_v2_shadow",
        "target_r": "none",
        "why": "negative combo; ev=-0.14422; wr=15.7143%; pf=0.360393"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 50,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "supertrend_pullback_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.142573; wr=18.0%; pf=0.35246"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 50,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "turtle_trend_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.142573; wr=18.0%; pf=0.35246"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 50,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "keltner_trend_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.142573; wr=18.0%; pf=0.35246"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 29,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "trend_ma_macd_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.175988; wr=20.6897%; pf=0.157649"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 29,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "ema_ribbon_scalp_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.175988; wr=20.6897%; pf=0.157649"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 76,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "liquidity_sweep_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.061184; wr=17.1053%; pf=0.731602"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 37,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "keltner_trend_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.088176; wr=16.2162%; pf=0.744868"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 37,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "supertrend_pullback_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.088176; wr=16.2162%; pf=0.744868"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 37,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "turtle_trend_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.088176; wr=16.2162%; pf=0.744868"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 27,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "vwap_revert_legendary",
        "target_r": "none",
        "why": "negative combo; ev=-0.035735; wr=22.2222%; pf=0.832926"
      },
      {
        "action": "block",
        "decision": "BLOCK_COMBO",
        "n": 135,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "unknown_strategy",
        "target_r": "none",
        "why": "negative combo; ev=-0.000401; wr=24.4444%; pf=0.998699"
      }
    ],
    "block_strategies": [
      "anchor_vwap_trend_legendary",
      "ema_ribbon_scalp_legendary",
      "fvg_revert_legendary",
      "keltner_trend_legendary",
      "liquidity_sweep_legendary",
      "rr275_vwap_reclaim_v2_shadow",
      "sr_levels_legendary",
      "supertrend_pullback_legendary",
      "trend_ma_macd_legendary",
      "turtle_trend_legendary",
      "unknown_strategy",
      "vwap_revert_legendary"
    ],
    "watch_count": 56,
    "watch_items": [
      {
        "action": "hold",
        "decision": "WATCH_NEEDS_MORE_OOS",
        "n": 52,
        "size_multiplier": 0.0,
        "skills": [
          "hedge_reversal"
        ],
        "strategy": "pivot_reversal_legendary",
        "target_r": "none",
        "why": "positive but not better enough; p_ev=0.0; b_ev=-0.497115; delta=25.85"
      },
      {
        "action": "reduce25",
        "decision": "REDUCE_OR_WATCH",
        "n": 50,
        "size_multiplier": 0.25,
        "skills": [
          "unclassified"
        ],
        "strategy": "trend_rider_legendary",
        "target_r": 2.25,
        "why": "weak negative but not hard block; ev=-0.03808"
      },
      {
        "action": "hold",
        "decision": "WATCH_NEEDS_MORE_OOS",
        "n": 20,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "trend_rider_legendary",
        "target_r": "none",
        "why": "positive but not better enough; p_ev=0.099375; b_ev=0.1325; delta=-0.6625"
      },
      {
        "action": "hold",
        "decision": "WATCH_NEEDS_MORE_OOS",
        "n": 29,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier",
          "risk_veto"
        ],
        "strategy": "unknown_strategy",
        "target_r": "none",
        "why": "positive but not better enough; p_ev=0.14317; b_ev=0.190893; delta=-1.383975"
      },
      {
        "action": "hold",
        "decision": "WATCH_NEEDS_MORE_OOS",
        "n": 36,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier",
          "hedge_reversal"
        ],
        "strategy": "pivot_reversal_legendary",
        "target_r": "none",
        "why": "positive but not better enough; p_ev=0.0; b_ev=1.186112; delta=-42.700031"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 3,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "obv_trend",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 5,
        "size_multiplier": 0.0,
        "skills": [
          "runner_hold"
        ],
        "strategy": "rr275_impulse_pullback_runner_shadow",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "hedge_reversal",
          "short_beam"
        ],
        "strategy": "unknown_strategy",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier",
          "hedge_reversal"
        ],
        "strategy": "pivot_reversal",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "hedge_reversal",
          "partial30",
          "runner_hold",
          "short_beam",
          "trailing"
        ],
        "strategy": "unknown_strategy",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "mfi_rsi_div_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "alpha_combo",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "anchor_vwap_trend",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "bb_revert",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "break_and_continue",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "donchian_breakout",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "ema_ribbon_scalp",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "fvg_revert",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "grid_rebalance",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "keltner_trend",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "liquidity_sweep",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "mfi_rsi_div",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "obv_trend",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "range_fade",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "rbreaker_like",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "rsi_swing_fail",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "scalp_snap",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "session_bias",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "squeeze_break",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "sr_levels",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "supertrend_pullback",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "trend_ma_macd",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "trend_rider",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "turtle_trend",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "vol_spike_fade",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "vwap_revert",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "long_beam",
          "runner_hold",
          "scale_in"
        ],
        "strategy": "unknown_strategy",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "long_beam",
          "partial30",
          "runner_hold",
          "scale_in",
          "trailing"
        ],
        "strategy": "unknown_strategy",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "long_beam",
          "partial30",
          "runner_hold",
          "trailing"
        ],
        "strategy": "unknown_strategy",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 1,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "ema_ribbon_scalp_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 10,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "trend_ma_macd_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 7,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "break_and_continue_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 7,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "orb_breakout_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 7,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "squeeze_break_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 10,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "bb_revert_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 10,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "range_fade_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 10,
        "size_multiplier": 0.0,
        "skills": [
          "exit_modifier"
        ],
        "strategy": "rsi_swing_fail_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 4,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "break_and_continue_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 4,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "orb_breakout_legendary",
        "target_r": "none",
        "why": "n<20"
      },
      {
        "action": "hold",
        "decision": "WATCH_SAMPLE_LOW",
        "n": 4,
        "size_multiplier": 0.0,
        "skills": [
          "unclassified"
        ],
        "strategy": "squeeze_break_legendary",
        "target_r": "none",
        "why": "n<20"
      }
    ],
    "watch_strategies": [
      "alpha_combo",
      "anchor_vwap_trend",
      "anchor_vwap_trend_legendary",
      "bb_revert",
      "bb_revert_legendary",
      "break_and_continue",
      "break_and_continue_legendary",
      "donchian_breakout",
      "ema_ribbon_scalp",
      "ema_ribbon_scalp_legendary",
      "fvg_revert",
      "grid_rebalance",
      "keltner_trend",
      "liquidity_sweep",
      "mfi_rsi_div",
      "mfi_rsi_div_legendary",
      "obv_trend",
      "orb_breakout_legendary",
      "pivot_reversal",
      "pivot_reversal_legendary",
      "range_fade",
      "range_fade_legendary",
      "rbreaker_like",
      "rr275_impulse_pullback_runner_shadow",
      "rsi_swing_fail",
      "rsi_swing_fail_legendary",
      "scalp_snap",
      "session_bias",
      "squeeze_break",
      "squeeze_break_legendary",
      "sr_levels",
      "supertrend_pullback",
      "trend_ma_macd",
      "trend_ma_macd_legendary",
      "trend_rider",
      "trend_rider_legendary",
      "turtle_trend",
      "unknown_strategy",
      "vol_spike_fade",
      "vwap_revert",
      "vwap_revert_legendary"
    ]
  },
  "cost_guard": {
    "base_only_above_r": 0.4,
    "block_at_or_above_r": 0.5,
    "half_size_above_r": 0.3,
    "normal_max_r": 0.3
  },
  "fallback_tp_r": 2.25,
  "long_beam_cap_r": 2.75,
  "main_tp_4_75r_allowed": False,
  "main_tp_6r_allowed": False,
  "owner": "H74TM8_SINGLE_PATCH_WITH_BACKUP",
  "performance": {
    "blocked_loss_removed_r_approx": -98.523756,
    "filtered_total_r": 144.150075,
    "watch_excluded_r_approx": 68.668833,
    "winrate_pct": 69.5238
  },
  "runner_allowed": False,
  "short_dca_hedge_multiplier": 0.0,
  "source_plan_owner": "W286W288H74TM7_TRADE_METHOD_PATCH_PLAN_FINAL_NO_WRITE",
  "source_plan_verdict": "PASS_H74TM7_FINAL_PLAN_READY_WAIT_24H_OR_USER_EXCEPTION_NO_WRITE"
}

def h74tm8_policy_snapshot() -> Dict[str, Any]:
    return copy.deepcopy(H74TM8_TRADE_METHOD_POLICY)

def h74tm8_normalize_strategy(strategy: Optional[str]) -> str:
    s = str(strategy or "unknown_strategy").strip()
    for suffix in ("_legendary", "_shadow", "_v2_shadow"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    return s

def h74tm8_cost_band(cost_r: Optional[float]) -> str:
    try:
        c = float(cost_r or 0.0)
    except Exception:
        c = 0.0
    cg = H74TM8_TRADE_METHOD_POLICY["cost_guard"]
    if c >= float(cg["block_at_or_above_r"]):
        return "BLOCK"
    if c > float(cg["base_only_above_r"]):
        return "BASE_ONLY"
    if c > float(cg["half_size_above_r"]):
        return "HALF"
    return "NORMAL"

def h74tm8_high_risk_skill(skills: Optional[Iterable[str]]) -> bool:
    risky = {"short_beam", "hedge_candidate", "reversal_candidate", "dca", "average_down", "water_add"}
    return any(str(s).strip() in risky for s in (skills or []))

def h74tm8_resolve_combo(strategy: Optional[str] = None, skills: Optional[Iterable[str]] = None, cost_r: Optional[float] = 0.0) -> Dict[str, Any]:
    policy = H74TM8_TRADE_METHOD_POLICY
    combo = policy["combo_filter"]
    raw = str(strategy or "unknown_strategy")
    norm = h74tm8_normalize_strategy(raw)
    names = {raw, norm}

    block_set = set(combo.get("block_strategies") or [])
    allow_full_set = set(combo.get("allow_full_strategies") or [])
    allow_policy_set = set(combo.get("allow_policy_strategies") or [])
    watch_set = set(combo.get("watch_strategies") or [])

    cost_band = h74tm8_cost_band(cost_r)

    if cost_band == "BLOCK":
        return {"decision": "BLOCK_COMBO", "action": "block", "size_multiplier": 0.0, "target_r": None, "reason": "cost_guard_block", "cost_band": cost_band, "source": "H74TM8"}

    if h74tm8_high_risk_skill(skills):
        return {"decision": "BLOCK_HIGH_RISK_SKILL", "action": "block", "size_multiplier": 0.0, "target_r": None, "reason": "short_dca_hedge_disabled", "cost_band": cost_band, "source": "H74TM8"}

    if names & block_set:
        return {"decision": "BLOCK_COMBO", "action": "block", "size_multiplier": 0.0, "target_r": None, "reason": "blocked_combo", "cost_band": cost_band, "source": "H74TM8"}

    size_multiplier = 1.0
    if cost_band == "HALF":
        size_multiplier = 0.5
    elif cost_band == "BASE_ONLY":
        size_multiplier = 1.0

    if names & allow_full_set:
        return {"decision": "ALLOW_FULL_BASE25", "action": "hold", "size_multiplier": size_multiplier, "target_r": policy["base_tp_r"], "reason": "allow_full", "cost_band": cost_band, "source": "H74TM8"}

    if names & allow_policy_set:
        return {"decision": "ALLOW_POLICY", "action": "hold", "size_multiplier": size_multiplier, "target_r": "policy", "reason": "allow_policy", "cost_band": cost_band, "source": "H74TM8"}

    if names & watch_set:
        return {"decision": "WATCH_COMBO", "action": "hold", "size_multiplier": 0.0, "target_r": None, "reason": "watch_combo", "cost_band": cost_band, "source": "H74TM8"}

    return {"decision": "WATCH_UNKNOWN_COMBO", "action": "hold", "size_multiplier": 0.0, "target_r": None, "reason": "unknown_combo_no_trade", "cost_band": cost_band, "source": "H74TM8"}
# <<< H74TM8_SINGLE_PATCH_WITH_BACKUP

# >>> H74TM9S_POLICY_PRECEDENCE_FIX

# H74TM9S: resolve overlapping allow/block/watch policy sets.
# Design:
# - exact raw strategy match is evaluated before normalized fallback.
# - unknown_strategy is always blocked.
# - allow_full exact tier wins over duplicate block/watch records.
# - allow_policy exact tier wins over watch, but not unknown.
# - exact block wins over normalized allow/watch.
# - watch is fallback observation only.
import copy as _h74tm9s_copy
from typing import Any as _H74TM9SAny, Dict as _H74TM9SDict, Iterable as _H74TM9SIterable, Optional as _H74TM9SOptional

def _h74tm9s_norm(strategy):
    s = str(strategy or "unknown_strategy").strip()
    for suffix in ("_legendary", "_shadow", "_v2_shadow"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    return s

def _h74tm9s_list(combo, key):
    v = combo.get(key) or []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return []

def _h74tm9s_effective_policy():
    p = _h74tm9s_copy.deepcopy(H74TM8_TRADE_METHOD_POLICY)
    combo = p.setdefault("combo_filter", {})

    raw_allow_full = _h74tm9s_list(combo, "allow_full_strategies")
    raw_allow_policy = _h74tm9s_list(combo, "allow_policy_strategies")
    raw_block = _h74tm9s_list(combo, "block_strategies")
    raw_watch = _h74tm9s_list(combo, "watch_strategies")

    unknowns = {"unknown_strategy", "__unknown_strategy__", ""}

    allow_full = sorted({s for s in raw_allow_full if s not in unknowns})
    allow_full_set = set(allow_full)

    allow_policy = sorted({s for s in raw_allow_policy if s not in unknowns and s not in allow_full_set})
    allow_policy_set = set(allow_policy)

    # Exact allow_full/allow_policy are removed from effective block.
    # unknown_strategy remains forced-block.
    block = sorted(({s for s in raw_block if s not in allow_full_set and s not in allow_policy_set} | {"unknown_strategy"}) - {""})
    block_set = set(block)

    # Watch excludes exact stronger tiers. Base/legendary can still diverge intentionally.
    watch = sorted({s for s in raw_watch if s not in allow_full_set and s not in allow_policy_set and s not in block_set and s not in unknowns})

    combo["allow_full_strategies"] = allow_full
    combo["allow_policy_strategies"] = allow_policy
    combo["block_strategies"] = block
    combo["watch_strategies"] = watch
    combo["effective_precedence"] = [
        "cost_block",
        "high_risk_skill_block",
        "raw_unknown_block",
        "raw_allow_full",
        "raw_allow_policy",
        "raw_block",
        "raw_watch",
        "normalized_allow_full",
        "normalized_allow_policy",
        "normalized_block",
        "normalized_watch",
        "unknown_watch_no_trade"
    ]
    combo["h74tm9s_effective_sets"] = {
        "allow_full_len": len(allow_full),
        "allow_policy_len": len(allow_policy),
        "block_len": len(block),
        "watch_len": len(watch),
        "unknown_strategy_forced_block": True
    }
    return p

def h74tm8_policy_snapshot() -> _H74TM9SDict[str, _H74TM9SAny]:
    return _h74tm9s_effective_policy()

def h74tm8_resolve_combo(strategy: _H74TM9SOptional[str] = None, skills: _H74TM9SOptional[_H74TM9SIterable[str]] = None, cost_r: _H74TM9SOptional[float] = 0.0) -> _H74TM9SDict[str, _H74TM9SAny]:
    policy = _h74tm9s_effective_policy()
    combo = policy["combo_filter"]

    raw = str(strategy or "unknown_strategy").strip()
    norm = _h74tm9s_norm(raw)

    allow_full_set = set(combo.get("allow_full_strategies") or [])
    allow_full_norm = {_h74tm9s_norm(x) for x in allow_full_set}

    allow_policy_set = set(combo.get("allow_policy_strategies") or [])
    allow_policy_norm = {_h74tm9s_norm(x) for x in allow_policy_set}

    block_set = set(combo.get("block_strategies") or [])
    block_norm = {_h74tm9s_norm(x) for x in block_set}

    watch_set = set(combo.get("watch_strategies") or [])
    watch_norm = {_h74tm9s_norm(x) for x in watch_set}

    cost_band = h74tm8_cost_band(cost_r)

    def out(decision, action, size_multiplier, target_r, reason):
        return {
            "decision": decision,
            "action": action,
            "size_multiplier": size_multiplier,
            "target_r": target_r,
            "reason": reason,
            "cost_band": cost_band,
            "source": "H74TM8",
        }

    if cost_band == "BLOCK":
        return out("BLOCK_COMBO", "block", 0.0, None, "cost_guard_block")

    if h74tm8_high_risk_skill(skills):
        return out("BLOCK_HIGH_RISK_SKILL", "block", 0.0, None, "short_dca_hedge_disabled")

    if raw in {"unknown_strategy", "__unknown_strategy__", ""} or norm == "unknown_strategy":
        return out("BLOCK_COMBO", "block", 0.0, None, "unknown_strategy_blocked")

    size_multiplier = 1.0
    if cost_band == "HALF":
        size_multiplier = 0.5
    elif cost_band == "BASE_ONLY":
        size_multiplier = 1.0

    # Raw exact precedence.
    if raw in allow_full_set:
        return out("ALLOW_FULL_BASE25", "hold", size_multiplier, policy["base_tp_r"], "allow_full_exact")
    if raw in allow_policy_set:
        return out("ALLOW_POLICY", "hold", size_multiplier, "policy", "allow_policy_exact")
    if raw in block_set:
        return out("BLOCK_COMBO", "block", 0.0, None, "blocked_combo_exact")
    if raw in watch_set:
        return out("WATCH_COMBO", "hold", 0.0, None, "watch_combo_exact")

    # Normalized fallback.
    if norm in allow_full_norm:
        return out("ALLOW_FULL_BASE25", "hold", size_multiplier, policy["base_tp_r"], "allow_full_norm")
    if norm in allow_policy_norm:
        return out("ALLOW_POLICY", "hold", size_multiplier, "policy", "allow_policy_norm")
    if norm in block_norm:
        return out("BLOCK_COMBO", "block", 0.0, None, "blocked_combo_norm")
    if norm in watch_norm:
        return out("WATCH_COMBO", "hold", 0.0, None, "watch_combo_norm")

    return out("WATCH_UNKNOWN_COMBO", "hold", 0.0, None, "unknown_combo_no_trade")
# <<< H74TM9S_POLICY_PRECEDENCE_FIX
