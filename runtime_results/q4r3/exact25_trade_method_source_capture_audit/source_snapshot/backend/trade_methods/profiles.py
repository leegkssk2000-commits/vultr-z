from __future__ import annotations

from .types import MethodProfile, TradeMethod, ScalpSubtype

METHOD_PROFILES: dict[tuple[TradeMethod, ScalpSubtype], MethodProfile] = {
    (TradeMethod.SCALP_FIRST, ScalpSubtype.REVERT): MethodProfile(
        method=TradeMethod.SCALP_FIRST,
        subtype=ScalpSubtype.REVERT,
        label="Scalp-first · Revert",
        entry_style="pullback_confirm",
        hold_horizon="3-15m",
        rescue_observe="wick fail 시 observe → decay 상승 시 reduce25",
        next_strategy_hint="mean_revert_v6",
    ),
    (TradeMethod.SCALP_FIRST, ScalpSubtype.CONTINUATION): MethodProfile(
        method=TradeMethod.SCALP_FIRST,
        subtype=ScalpSubtype.CONTINUATION,
        label="Scalp-first · Continuation",
        entry_style="break_reclaim",
        hold_horizon="3-15m",
        rescue_observe="moment stall 시 partial30 → reclaim 실패 시 reduce25",
        next_strategy_hint="BTC Trend v1",
    ),
    (TradeMethod.SCALP_FIRST, ScalpSubtype.LIQUIDITY_RECLAIM): MethodProfile(
        method=TradeMethod.SCALP_FIRST,
        subtype=ScalpSubtype.LIQUIDITY_RECLAIM,
        label="Scalp-first · Liquidity Reclaim",
        entry_style="break_reclaim",
        hold_horizon="3-15m",
        rescue_observe="sweep 이후 reclaim 미완료면 observe 유지",
        next_strategy_hint="liquidity_reclaim_v2",
    ),
    (TradeMethod.INTRADAY, ScalpSubtype.BREAKOUT_PROBE): MethodProfile(
        method=TradeMethod.INTRADAY,
        subtype=ScalpSubtype.BREAKOUT_PROBE,
        label="Intraday · Breakout Probe",
        entry_style="observe_then_confirm",
        hold_horizon="10-45m",
        rescue_observe="확증 부족 시 route_change, decay 상승 시 reduce25",
        next_strategy_hint="breakout_probe",
    ),
    (TradeMethod.SCALP_FIRST, ScalpSubtype.RESCUE): MethodProfile(
        method=TradeMethod.SCALP_FIRST,
        subtype=ScalpSubtype.RESCUE,
        label="Scalp-first · Rescue",
        entry_style="range_revert",
        hold_horizon="3-15m",
        rescue_observe="구조 유지 시 observe, venue 악화 시 block",
        next_strategy_hint="short_guard_v2",
    ),
}

# >>> H74TM8_SINGLE_PATCH_WITH_BACKUP

from typing import Any, Dict

H74TM8_METHOD_PROFILES: Dict[str, Any] = {
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

def h74tm8_profile_snapshot() -> Dict[str, Any]:
    return dict(H74TM8_METHOD_PROFILES)

def h74tm8_base_tp_r() -> float:
    return float(H74TM8_METHOD_PROFILES.get("base_tp_r", 2.5))

def h74tm8_fallback_tp_r() -> float:
    return float(H74TM8_METHOD_PROFILES.get("fallback_tp_r", 2.25))

def h74tm8_long_beam_cap_r() -> float:
    return float(H74TM8_METHOD_PROFILES.get("long_beam_cap_r", 2.75))
# <<< H74TM8_SINGLE_PATCH_WITH_BACKUP
