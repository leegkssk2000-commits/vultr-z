# Keltner cumulative entry repair: P / D / N

P is the unchanged original control. D is the unadopted PR1196 workcopy. N retains D exits and only admits original signal closes in the upper half of their own high-low range. All periods are reused development evidence; independent=false. Units: equal nominal trade-bps, never account returns.

| Period / metric | P | D | N | N-D | N-P |
|---|---:|---:|---:|---:|---:|
| DEV2025 / closed_T | 217.0000 | 217.0000 | 210.0000 | -7.0000 | -7.0000 |
| DEV2025 / open_T | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| DEV2025 / entries_T | 218.0000 | 218.0000 | 211.0000 | -7.0000 | -7.0000 |
| DEV2025 / win_rate | 0.4747 | 0.4700 | 0.4810 | 0.0109 | 0.0063 |
| DEV2025 / PF | 0.9866 | 1.0927 | 1.1093 | 0.0166 | 0.1227 |
| DEV2025 / mean_win_bps | 451.7071 | 451.9685 | 457.8974 | 5.9289 | 6.1904 |
| DEV2025 / mean_loss_bps | -413.6839 | -366.8720 | -382.4893 | -15.6173 | 31.1946 |
| DEV2025 / realized_payoff | 1.0919 | 1.2320 | 1.1972 | -0.0348 | 0.1052 |
| DEV2025 / net_expectancy_bps_per_closed_trade | -2.9223 | 18.0208 | 21.6967 | 3.6759 | 24.6190 |
| DEV2025 / closed_gross_bps | 3,986.6749 | 8,488.4313 | 8,988.6273 | 500.1960 | 5,001.9524 |
| DEV2025 / closed_net_bps | -634.1339 | 3,910.5089 | 4,556.3060 | 645.7971 | 5,190.4399 |
| DEV2025 / closed_cost2x_net_bps | -5,254.9427 | -667.4136 | 123.9847 | 791.3983 | 5,378.9274 |
| DEV2025 / closed_cost_bps | 4,620.8088 | 4,577.9225 | 4,432.3213 | -145.6011 | -188.4875 |
| DEV2025 / closed_fee_bps | 2,170.0000 | 2,170.0000 | 2,100.0000 | -70.0000 | -70.0000 |
| DEV2025 / closed_funding_bps | 1,535.5800 | 1,412.4400 | 1,363.8200 | -48.6200 | -171.7600 |
| DEV2025 / terminal_net_bps_hypothetical | -710.8650 | 3,833.7778 | 4,479.5749 | 645.7971 | 5,190.4399 |
| DEV2025 / terminal_cost2x_net_bps_hypothetical | -5,351.6738 | -764.1447 | 27.2536 | 791.3983 | 5,378.9274 |
| DEV2025 / open_net_mark_bps_hypothetical | -76.7311 | -76.7311 | -76.7311 | 0.0000 | 0.0000 |
| DEV2025 / marked_DD_trade_sum_bps | 16,609.7673 | 12,265.1987 | 12,733.2112 | 468.0125 | -3,876.5561 |
| DEV2025 / grouped_max_loss_trade_sum_bps | 7,709.3138 | 5,219.6360 | 5,548.5073 | 328.8713 | -2,160.8065 |
| DEV2025 / exposure_symbol_days | 434.1667 | 399.3333 | 385.8333 | -13.5000 | -48.3333 |
| DEV2025 / max_simultaneous_symbols | 7.0000 | 7.0000 | 7.0000 | 0.0000 | 0.0000 |
| DEV2025 / entries_per_30_days | 17.4400 | 17.4400 | 16.8800 | -0.5600 | -0.5600 |
| DEV2025 / max_completed_recovery_days | 64.0000 | 64.0000 | 64.0000 | 0.0000 | 0.0000 |
| DEV2025 / open_underwater_days | 101.3333 | 137.3333 | 101.3333 | -36.0000 | 0.0000 |
| DEV2025 / winner_amount_retention_vs_P_lower | 1.0000 | 0.9909 | 0.9690 | -0.0219 | -0.0310 |
| DEV2025 / large_winner_amount_retention_vs_P_lower | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| DEV2025 / winner_amount_retention_vs_D_lower | NA | 1.0000 | 0.9779 | -0.0221 | NA |
| DEV2025 / large_winner_amount_retention_vs_D_lower | NA | 1.0000 | 1.0000 | 0.0000 | NA |

D→N: `{"decision": "TRADEOFF", "comparison_type": "ENTRY_FILTER", "absolute_economic_checks": {"positive_closed_net": true, "positive_expectancy": true, "PF_above_one": true, "payoff_at_least_one": true, "positive_closed_cost2x_net": true}, "increment_checks": {"closed_net_increased": true, "terminal_net_increased": true}, "risk_and_evidence_checks": {"grouped_loss_run_not_worse": false, "marked_DD_not_worse": false, "large_winner_amount_preserved": true, "positive_daily_delta95_lower": false, "no_unresolved_positions": false}, "failed_checks": ["grouped_loss_run_not_worse", "marked_DD_not_worse", "positive_daily_delta95_lower", "no_unresolved_positions"], "partial_workbench_observations": {"closed_net_increased": true, "terminal_net_increased": true, "grouped_loss_run_not_worse": false, "marked_DD_not_worse": false, "large_winner_amount_preserved": true}, "partial_workbench_checks_met": false, "partial_workbench_is_economic_PASS": false, "loss_reduction": false, "closed_net_delta_bps": 645.7971282915464, "terminal_net_delta_bps": 645.7971282915469, "grouped_loss_run_delta_bps_descriptive": 328.8712548347494, "exposure_delta_symbol_days": -13.5, "source_overlap_is_economic_gate": false, "formal_pass": false, "operating_adoption": false, "independent": false, "prior_D_verdict_changed": false, "code_PASS_is_economic_PASS": false, "open_censoring_blocks_strong_verdict": true}`

Cumulative gain and remaining deficits:

```json
{
  "period": "DEV2025",
  "independent": false,
  "D_minus_P_closed_net_bps": 4544.642795586012,
  "N_minus_P_closed_net_bps": 5190.439923877559,
  "N_minus_D_closed_net_bps": 645.7971282915464,
  "D_observed_increment_retained_fraction": 1.1421007452816265,
  "increment_fraction_basis": "UNCLIPPED_FULL_REPLAY_CLOSED_NET_INCREMENT_OVER_P; OBSERVED_ONLY",
  "N_remaining_closed_net_deficit_bps": 0.0,
  "N_remaining_closed_cost2x_deficit_bps": 0.0,
  "N_remaining_hypothetical_terminal_net_deficit_bps": 0.0,
  "future_guarantee_or_execution_feature": false,
  "prior_D_status_changed": false,
  "formal_pass": false,
  "operating_adoption": false
}
```

Original P opportunity bridge (row detail is in the period ledger):

```json
{
  "basis": "ORIGINAL_P_ORIGINS; D_FIXED_EXIT_EFFECT; N_FULL_REPLAY_REMAINDER_AND_NEW_OPPORTUNITIES",
  "prior_fixed_D_minus_P_closed_net_bps": 4544.642795586012,
  "N_original_origins_minus_prior_fixed_closed_net_bps": 2609.0053394906404,
  "N_new_not_P_closed_totals_bps": {
    "gross_bps": -1760.4474573750406,
    "net_bps": -1963.2082111990942,
    "cost2x_net_bps": -2165.9689650231476,
    "cost_bps": 202.76075382405364,
    "fee_bps": 100.0,
    "spread_bps": 21.332862445431417,
    "impact_bps": 20.0,
    "slippage_bps": 0.0,
    "funding_bps": 51.0,
    "frozen_floor_reserve_bps": 10.427891378622228
  },
  "N_new_not_P_closed_T": 10,
  "N_new_not_P_open_T": 0,
  "N_minus_P_full_closed_net_bps": 5190.439923877559,
  "outcome_categories": {
    "D_helpful_closed": {
      "original_P_T": 21,
      "N_absent_T": 3,
      "N_closed_T": 18,
      "N_open_T": 0,
      "D_fixed_minus_P_closed_net_bps": 7769.994014271863,
      "N_minus_D_fixed_closed_net_bps": 1254.688630890055,
      "N_minus_P_closed_net_bps": 9024.682645161918
    },
    "D_harmful_closed": {
      "original_P_T": 17,
      "N_absent_T": 1,
      "N_closed_T": 16,
      "N_open_T": 0,
      "D_fixed_minus_P_closed_net_bps": -3225.3512186858516,
      "N_minus_D_fixed_closed_net_bps": 449.87979825435565,
      "N_minus_P_closed_net_bps": -2775.471420431496
    },
    "D_unchanged_closed": {
      "original_P_T": 179,
      "N_absent_T": 13,
      "N_closed_T": 166,
      "N_open_T": 0,
      "D_fixed_minus_P_closed_net_bps": 0.0,
      "N_minus_D_fixed_closed_net_bps": 904.43691034623,
      "N_minus_P_closed_net_bps": 904.43691034623
    },
    "censor_transition": {
      "original_P_T": 1,
      "N_absent_T": 0,
      "N_closed_T": 0,
      "N_open_T": 1,
      "D_fixed_minus_P_closed_net_bps": 0.0,
      "N_minus_D_fixed_closed_net_bps": 0.0,
      "N_minus_P_closed_net_bps": 0.0
    }
  },
  "fixed_harm_retrospective_labels_are_execution_features": false,
  "absent_N_entry_is_zero_profit_trade_or_win": false,
  "new_opportunity_net_is_fixed_bonus": false,
  "parity": "PASS"
}
```

D_to_N_COMMON_D — complete net contribution and uncertainty:

```json
{
  "net_decomposition": {
    "common_loser_improvement_bps": 0.0,
    "common_loser_deterioration_bps": 0.0,
    "common_winner_profit_cut_bps": 0.0,
    "common_winner_flipped_loss_bps": 0.0,
    "common_winner_profit_added_bps": 0.0,
    "common_zero_parent_net_delta_bps": 0.0,
    "other_origin_group_signed_net_delta_bps": {
      "CO": 0,
      "OC": 0,
      "OO": 0.0,
      "removed_C": 2111.698822425021,
      "removed_O": 0,
      "new_C": 0,
      "new_O": 0
    },
    "common_closed_net_delta_bps": 0.0,
    "closed_net_delta_bps": 2111.6988224250204,
    "parity": "PASS",
    "cost_saving_already_in_net_do_not_add_again": true,
    "loser_improvement_can_include_new_positive_profit": true,
    "censor_changes_separate_from_avoided_losses": true
  },
  "uncertainty": {
    "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
    "calendar_days": 376,
    "block_days": 30,
    "resamples": 1000,
    "seed": 1178,
    "approximate_calendar_blocks": 12.533333333333333,
    "N_effective": null,
    "calendar_start": "2024-12-19",
    "calendar_last_day": "2025-12-29",
    "parent_marked_delta_sum_bps": 3833.7778076145214,
    "child_marked_delta_sum_bps": 5945.476630039542,
    "child_minus_parent_marked_delta_sum_bps": 2111.698822425021,
    "child_minus_parent_mean_daily_bps": 5.61622027240697,
    "child_minus_parent_95pct_interval_bps_per_day": [
      2.777125456191903,
      11.45548488281068
    ],
    "child_minus_parent_95pct_interval_calendar_sum_bps": [
      1044.1991715281556,
      4307.262315936816
    ],
    "status": "COMPUTED",
    "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
    "independent": false,
    "partial_native_edge_buckets_included": true,
    "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
  }
}
```

D_to_N — complete net contribution and uncertainty:

```json
{
  "net_decomposition": {
    "common_loser_improvement_bps": 0.0,
    "common_loser_deterioration_bps": 0.0,
    "common_winner_profit_cut_bps": 0.0,
    "common_winner_flipped_loss_bps": 0.0,
    "common_winner_profit_added_bps": 0.0,
    "common_zero_parent_net_delta_bps": 0.0,
    "other_origin_group_signed_net_delta_bps": {
      "CO": 0,
      "OC": 0,
      "OO": 0.0,
      "removed_C": 2609.005339490641,
      "removed_O": 0,
      "new_C": -1963.2082111990942,
      "new_O": 0
    },
    "common_closed_net_delta_bps": 0.0,
    "closed_net_delta_bps": 645.7971282915464,
    "parity": "PASS",
    "cost_saving_already_in_net_do_not_add_again": true,
    "loser_improvement_can_include_new_positive_profit": true,
    "censor_changes_separate_from_avoided_losses": true
  },
  "uncertainty": {
    "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
    "calendar_days": 376,
    "block_days": 30,
    "resamples": 1000,
    "seed": 1178,
    "approximate_calendar_blocks": 12.533333333333333,
    "N_effective": null,
    "calendar_start": "2024-12-19",
    "calendar_last_day": "2025-12-29",
    "parent_marked_delta_sum_bps": 3833.7778076145214,
    "child_marked_delta_sum_bps": 4479.574935906068,
    "child_minus_parent_marked_delta_sum_bps": 645.7971282915469,
    "child_minus_parent_mean_daily_bps": 1.71754555396688,
    "child_minus_parent_95pct_interval_bps_per_day": [
      -2.0739670330101454,
      8.578194628674845
    ],
    "child_minus_parent_95pct_interval_calendar_sum_bps": [
      -779.8116044118146,
      3225.401180381742
    ],
    "status": "COMPUTED",
    "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
    "independent": false,
    "partial_native_edge_buckets_included": true,
    "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
  }
}
```

P_to_N — complete net contribution and uncertainty:

```json
{
  "net_decomposition": {
    "common_loser_improvement_bps": 7367.669455170686,
    "common_loser_deterioration_bps": 2601.520072508276,
    "common_winner_profit_cut_bps": 425.0409108619424,
    "common_winner_flipped_loss_bps": 194.0335079440669,
    "common_winner_profit_added_bps": 0.0,
    "common_zero_parent_net_delta_bps": 0.0,
    "other_origin_group_signed_net_delta_bps": {
      "CO": 0,
      "OC": 0,
      "OO": 0.0,
      "removed_C": 3006.5731712202505,
      "removed_O": 0,
      "new_C": -1963.2082111990942,
      "new_O": 0
    },
    "common_closed_net_delta_bps": 4147.074963856401,
    "closed_net_delta_bps": 5190.439923877559,
    "parity": "PASS",
    "cost_saving_already_in_net_do_not_add_again": true,
    "loser_improvement_can_include_new_positive_profit": true,
    "censor_changes_separate_from_avoided_losses": true
  },
  "uncertainty": {
    "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
    "calendar_days": 376,
    "block_days": 30,
    "resamples": 1000,
    "seed": 1178,
    "approximate_calendar_blocks": 12.533333333333333,
    "N_effective": null,
    "calendar_start": "2024-12-19",
    "calendar_last_day": "2025-12-29",
    "parent_marked_delta_sum_bps": -710.8649879714901,
    "child_marked_delta_sum_bps": 4479.574935906068,
    "child_minus_parent_marked_delta_sum_bps": 5190.439923877559,
    "child_minus_parent_mean_daily_bps": 13.804361499674359,
    "child_minus_parent_95pct_interval_bps_per_day": [
      0.4523913525145045,
      35.0085191388686
    ],
    "child_minus_parent_95pct_interval_calendar_sum_bps": [
      170.0991485454537,
      13163.203196214594
    ],
    "status": "COMPUTED",
    "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
    "independent": false,
    "partial_native_edge_buckets_included": true,
    "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
  }
}
```

| Period / metric | P | D | N | N-D | N-P |
|---|---:|---:|---:|---:|---:|
| SEEN2026 / closed_T | 78.0000 | 79.0000 | 75.0000 | -4.0000 | -3.0000 |
| SEEN2026 / open_T | 4.0000 | 4.0000 | 4.0000 | 0.0000 | 0.0000 |
| SEEN2026 / entries_T | 82.0000 | 83.0000 | 79.0000 | -4.0000 | -3.0000 |
| SEEN2026 / win_rate | 0.3590 | 0.3418 | 0.3600 | 0.0182 | 0.0010 |
| SEEN2026 / PF | 0.8869 | 0.9022 | 0.9713 | 0.0692 | 0.0844 |
| SEEN2026 / mean_win_bps | 470.1711 | 498.9341 | 498.9341 | 0.0000 | 28.7630 |
| SEEN2026 / mean_loss_bps | -296.8798 | -287.1584 | -288.9400 | -1.7816 | 7.9398 |
| SEEN2026 / realized_payoff | 1.5837 | 1.7375 | 1.7268 | -0.0107 | 0.1431 |
| SEEN2026 / net_expectancy_bps_per_closed_trade | -21.5282 | -18.4939 | -5.3053 | 13.1886 | 16.2229 |
| SEEN2026 / closed_gross_bps | 4.3891 | 230.6901 | 1,202.4119 | 971.7218 | 1,198.0228 |
| SEEN2026 / closed_net_bps | -1,679.1979 | -1,461.0166 | -397.8979 | 1,063.1187 | 1,281.3000 |
| SEEN2026 / closed_cost2x_net_bps | -3,362.7849 | -3,152.7232 | -1,998.2077 | 1,154.5155 | 1,364.5772 |
| SEEN2026 / closed_cost_bps | 1,683.5870 | 1,691.7067 | 1,600.3098 | -91.3968 | -83.2772 |
| SEEN2026 / closed_fee_bps | 780.0000 | 790.0000 | 750.0000 | -40.0000 | -30.0000 |
| SEEN2026 / closed_funding_bps | 573.5400 | 525.9100 | 497.5100 | -28.4000 | -76.0300 |
| SEEN2026 / terminal_net_bps_hypothetical | -2,296.1835 | -2,078.0022 | -1,014.8835 | 1,063.1187 | 1,281.3000 |
| SEEN2026 / terminal_cost2x_net_bps_hypothetical | -4,059.7705 | -3,849.7088 | -2,695.1933 | 1,154.5155 | 1,364.5772 |
| SEEN2026 / open_net_mark_bps_hypothetical | -616.9856 | -616.9856 | -616.9856 | 0.0000 | 0.0000 |
| SEEN2026 / marked_DD_trade_sum_bps | 5,023.0786 | 6,059.7626 | 5,643.8641 | -415.8985 | 620.7855 |
| SEEN2026 / grouped_max_loss_trade_sum_bps | 3,547.7544 | 3,758.3091 | 3,758.3091 | 0.0000 | 210.5547 |
| SEEN2026 / exposure_symbol_days | 160.3333 | 147.1667 | 141.1667 | -6.0000 | -19.1667 |
| SEEN2026 / max_simultaneous_symbols | 7.0000 | 7.0000 | 7.0000 | 0.0000 | 0.0000 |
| SEEN2026 / entries_per_30_days | 20.5000 | 20.7500 | 19.7500 | -1.0000 | -0.7500 |
| SEEN2026 / max_completed_recovery_days | 14.0000 | 13.0000 | 85.0000 | 72.0000 | 71.0000 |
| SEEN2026 / open_underwater_days | 93.0000 | 93.0000 | 8.0000 | -85.0000 | -85.0000 |
| SEEN2026 / winner_amount_retention_vs_P_lower | 1.0000 | 0.9241 | 0.9241 | 0.0000 | -0.0759 |
| SEEN2026 / large_winner_amount_retention_vs_P_lower | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| SEEN2026 / winner_amount_retention_vs_D_lower | NA | 1.0000 | 1.0000 | 0.0000 | NA |
| SEEN2026 / large_winner_amount_retention_vs_D_lower | NA | 1.0000 | 1.0000 | 0.0000 | NA |

D→N: `{"decision": "REJECT", "comparison_type": "ENTRY_FILTER", "absolute_economic_checks": {"positive_closed_net": false, "positive_expectancy": false, "PF_above_one": false, "payoff_at_least_one": true, "positive_closed_cost2x_net": false}, "increment_checks": {"closed_net_increased": true, "terminal_net_increased": true}, "risk_and_evidence_checks": {"grouped_loss_run_not_worse": true, "marked_DD_not_worse": true, "large_winner_amount_preserved": true, "positive_daily_delta95_lower": true, "no_unresolved_positions": false}, "failed_checks": ["positive_closed_net", "positive_expectancy", "PF_above_one", "positive_closed_cost2x_net", "no_unresolved_positions"], "partial_workbench_observations": {"closed_net_increased": true, "terminal_net_increased": true, "grouped_loss_run_not_worse": true, "marked_DD_not_worse": true, "large_winner_amount_preserved": true}, "partial_workbench_checks_met": true, "partial_workbench_is_economic_PASS": false, "loss_reduction": true, "closed_net_delta_bps": 1063.1186676698642, "terminal_net_delta_bps": 1063.1186676698644, "grouped_loss_run_delta_bps_descriptive": 0.0, "exposure_delta_symbol_days": -6.0, "source_overlap_is_economic_gate": false, "formal_pass": false, "operating_adoption": false, "independent": false, "prior_D_verdict_changed": false, "code_PASS_is_economic_PASS": false, "open_censoring_blocks_strong_verdict": true}`

Cumulative gain and remaining deficits:

```json
{
  "period": "SEEN2026",
  "independent": false,
  "D_minus_P_closed_net_bps": 218.18134693662705,
  "N_minus_P_closed_net_bps": 1281.3000146064912,
  "N_minus_D_closed_net_bps": 1063.1186676698642,
  "D_observed_increment_retained_fraction": 5.872637751102791,
  "increment_fraction_basis": "UNCLIPPED_FULL_REPLAY_CLOSED_NET_INCREMENT_OVER_P; OBSERVED_ONLY",
  "N_remaining_closed_net_deficit_bps": 397.8978939435051,
  "N_remaining_closed_cost2x_deficit_bps": 1998.207725613295,
  "N_remaining_hypothetical_terminal_net_deficit_bps": 1014.8834909301728,
  "future_guarantee_or_execution_feature": false,
  "prior_D_status_changed": false,
  "formal_pass": false,
  "operating_adoption": false
}
```

Original P opportunity bridge (row detail is in the period ledger):

```json
{
  "basis": "ORIGINAL_P_ORIGINS; D_FIXED_EXIT_EFFECT; N_FULL_REPLAY_REMAINDER_AND_NEW_OPPORTUNITIES",
  "prior_fixed_D_minus_P_closed_net_bps": -1086.8426475939361,
  "N_original_origins_minus_prior_fixed_closed_net_bps": 1063.1186676698642,
  "N_new_not_P_closed_totals_bps": {
    "gross_bps": 1325.0239945305632,
    "net_bps": 1305.0239945305632,
    "cost2x_net_bps": 1285.0239945305632,
    "cost_bps": 20.0,
    "fee_bps": 10.0,
    "spread_bps": 1.0,
    "impact_bps": 2.0,
    "slippage_bps": 0.0,
    "funding_bps": 6.0,
    "frozen_floor_reserve_bps": 1.0
  },
  "N_new_not_P_closed_T": 1,
  "N_new_not_P_open_T": 0,
  "N_minus_P_full_closed_net_bps": 1281.3000146064912,
  "outcome_categories": {
    "D_helpful_closed": {
      "original_P_T": 7,
      "N_absent_T": 0,
      "N_closed_T": 7,
      "N_open_T": 0,
      "D_fixed_minus_P_closed_net_bps": 856.3860092887226,
      "N_minus_D_fixed_closed_net_bps": 0.0,
      "N_minus_P_closed_net_bps": 856.3860092887226
    },
    "D_harmful_closed": {
      "original_P_T": 10,
      "N_absent_T": 3,
      "N_closed_T": 7,
      "N_open_T": 0,
      "D_fixed_minus_P_closed_net_bps": -1943.228656882659,
      "N_minus_D_fixed_closed_net_bps": 808.6668567077984,
      "N_minus_P_closed_net_bps": -1134.5618001748605
    },
    "D_unchanged_closed": {
      "original_P_T": 61,
      "N_absent_T": 1,
      "N_closed_T": 60,
      "N_open_T": 0,
      "D_fixed_minus_P_closed_net_bps": 0.0,
      "N_minus_D_fixed_closed_net_bps": 254.45181096206588,
      "N_minus_P_closed_net_bps": 254.45181096206588
    },
    "censor_transition": {
      "original_P_T": 4,
      "N_absent_T": 0,
      "N_closed_T": 0,
      "N_open_T": 4,
      "D_fixed_minus_P_closed_net_bps": 0.0,
      "N_minus_D_fixed_closed_net_bps": 0.0,
      "N_minus_P_closed_net_bps": 0.0
    }
  },
  "fixed_harm_retrospective_labels_are_execution_features": false,
  "absent_N_entry_is_zero_profit_trade_or_win": false,
  "new_opportunity_net_is_fixed_bonus": false,
  "parity": "PASS"
}
```

D_to_N_COMMON_D — complete net contribution and uncertainty:

```json
{
  "net_decomposition": {
    "common_loser_improvement_bps": 0.0,
    "common_loser_deterioration_bps": 0.0,
    "common_winner_profit_cut_bps": 0.0,
    "common_winner_flipped_loss_bps": 0.0,
    "common_winner_profit_added_bps": 0.0,
    "common_zero_parent_net_delta_bps": 0.0,
    "other_origin_group_signed_net_delta_bps": {
      "CO": 0,
      "OC": 0,
      "OO": 0.0,
      "removed_C": 1063.1186676698642,
      "removed_O": 0,
      "new_C": 0,
      "new_O": 0
    },
    "common_closed_net_delta_bps": 0.0,
    "closed_net_delta_bps": 1063.1186676698642,
    "parity": "PASS",
    "cost_saving_already_in_net_do_not_add_again": true,
    "loser_improvement_can_include_new_positive_profit": true,
    "censor_changes_separate_from_avoided_losses": true
  },
  "uncertainty": {
    "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
    "calendar_days": 120,
    "block_days": 30,
    "resamples": 1000,
    "seed": 1178,
    "approximate_calendar_blocks": 4.0,
    "N_effective": null,
    "calendar_start": "2026-05-08",
    "calendar_last_day": "2026-09-04",
    "parent_marked_delta_sum_bps": -2078.002158600037,
    "child_marked_delta_sum_bps": -1014.8834909301727,
    "child_minus_parent_marked_delta_sum_bps": 1063.1186676698644,
    "child_minus_parent_mean_daily_bps": 8.859322230582203,
    "child_minus_parent_95pct_interval_bps_per_day": [
      2.1204317580172147,
      20.337168090444756
    ],
    "child_minus_parent_95pct_interval_calendar_sum_bps": [
      254.45181096206576,
      2440.4601708533705
    ],
    "status": "COMPUTED",
    "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
    "independent": false,
    "partial_native_edge_buckets_included": true,
    "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
  }
}
```

D_to_N — complete net contribution and uncertainty:

```json
{
  "net_decomposition": {
    "common_loser_improvement_bps": 0.0,
    "common_loser_deterioration_bps": 0.0,
    "common_winner_profit_cut_bps": 0.0,
    "common_winner_flipped_loss_bps": 0.0,
    "common_winner_profit_added_bps": 0.0,
    "common_zero_parent_net_delta_bps": 0.0,
    "other_origin_group_signed_net_delta_bps": {
      "CO": 0,
      "OC": 0,
      "OO": 0.0,
      "removed_C": 1063.1186676698642,
      "removed_O": 0,
      "new_C": 0,
      "new_O": 0
    },
    "common_closed_net_delta_bps": 0.0,
    "closed_net_delta_bps": 1063.1186676698642,
    "parity": "PASS",
    "cost_saving_already_in_net_do_not_add_again": true,
    "loser_improvement_can_include_new_positive_profit": true,
    "censor_changes_separate_from_avoided_losses": true
  },
  "uncertainty": {
    "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
    "calendar_days": 120,
    "block_days": 30,
    "resamples": 1000,
    "seed": 1178,
    "approximate_calendar_blocks": 4.0,
    "N_effective": null,
    "calendar_start": "2026-05-08",
    "calendar_last_day": "2026-09-04",
    "parent_marked_delta_sum_bps": -2078.002158600037,
    "child_marked_delta_sum_bps": -1014.8834909301727,
    "child_minus_parent_marked_delta_sum_bps": 1063.1186676698644,
    "child_minus_parent_mean_daily_bps": 8.859322230582203,
    "child_minus_parent_95pct_interval_bps_per_day": [
      2.1204317580172147,
      20.337168090444756
    ],
    "child_minus_parent_95pct_interval_calendar_sum_bps": [
      254.45181096206576,
      2440.4601708533705
    ],
    "status": "COMPUTED",
    "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
    "independent": false,
    "partial_native_edge_buckets_included": true,
    "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
  }
}
```

P_to_N — complete net contribution and uncertainty:

```json
{
  "net_decomposition": {
    "common_loser_improvement_bps": 856.3860092887226,
    "common_loser_deterioration_bps": 341.2510406729584,
    "common_winner_profit_cut_bps": 998.5928089438187,
    "common_winner_flipped_loss_bps": 419.2511576220581,
    "common_winner_profit_added_bps": 0.0,
    "common_zero_parent_net_delta_bps": 0.0,
    "other_origin_group_signed_net_delta_bps": {
      "CO": 0,
      "OC": 0,
      "OO": 0.0,
      "removed_C": 878.9850180260406,
      "removed_O": 0,
      "new_C": 1305.0239945305632,
      "new_O": 0
    },
    "common_closed_net_delta_bps": -902.7089979501127,
    "closed_net_delta_bps": 1281.3000146064912,
    "parity": "PASS",
    "cost_saving_already_in_net_do_not_add_again": true,
    "loser_improvement_can_include_new_positive_profit": true,
    "censor_changes_separate_from_avoided_losses": true
  },
  "uncertainty": {
    "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
    "calendar_days": 120,
    "block_days": 30,
    "resamples": 1000,
    "seed": 1178,
    "approximate_calendar_blocks": 4.0,
    "N_effective": null,
    "calendar_start": "2026-05-08",
    "calendar_last_day": "2026-09-04",
    "parent_marked_delta_sum_bps": -2296.1835055366646,
    "child_marked_delta_sum_bps": -1014.8834909301727,
    "child_minus_parent_marked_delta_sum_bps": 1281.300014606492,
    "child_minus_parent_mean_daily_bps": 10.677500121720765,
    "child_minus_parent_95pct_interval_bps_per_day": [
      -21.594109283694564,
      39.12569762357106
    ],
    "child_minus_parent_95pct_interval_calendar_sum_bps": [
      -2591.2931140433475,
      4695.083714828526
    ],
    "status": "COMPUTED",
    "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
    "independent": false,
    "partial_native_edge_buckets_included": true,
    "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
  }
}
```

## Interpretation and complete accounting

Common-original-opportunity view applies the new eligibility to D admitted origins. Full N independently replays the complete original signal pool and occupancy. Vetoes remain explicit events; removed entries are not zero-PnL wins. Retained common origins keep D exit geometry; changed aggregate performance includes lost winners, avoided losers, newly admitted and displaced entries.

The2026 new SOL profit from PR1196 is not added as a constant; its origin must survive actual N replay. Original P winners/losers and prior D fixed effects are diagnostic labels only. Per-period gzip ledgers contain every event/fill/trigger/openmark, UTC path, same-calendar loss/DD windows, common/removed/new origin bridges and block uncertainty.

N-D and N-P retention use each reference’s completed winners and capped original profit; topdecile winner definition is unchanged. Existing 90% large-profit preservation is a research comparison prior, not a new formal gate. No P/D verdict is rewritten. Partial improvements and absolute cost-stressed profitability are separate.

2025 native interval2024-12-19T08Z–2025-12-29T08Z;2026 interval2026-05-08T00Z–2026-09-05T00Z. The exact original EMA warmup/seed and cost authority are preserved. No input afterSep5T00Z is decoded. Original seen-prefix split labels remain in source_access, not independent validation.

Parent P/D unfinished tails remain separate hypothetical full-roundtrip-cost marks; no end-price fabricated fill. D has no separate SL in the original Keltner model. Research cost/funding assumptions remain distinct from production signed funding/fills and account sizing.

28 old candidates preserved;1new candidate ordinal29,2period applications,4common/full views,0remaining. Same-result reproduction consumes no new trial. Old seen1/1 and independent0/1 NOT_RUN preserved. No numeric sweep, alternative filter scan, additional candidate, B2, externalpaidAI or operating deployment.

| Top5 | This work |
|---|---|
| Primary | Preserved |
| Broad | Preserved |
| Break / Q0 | Research/future observer preserved |
| Keltner | P fixed; D retained; one N entry repair measured |
| Supertrend | Preserved |

PR1195 observer code/spec/period/schedule/data never used for development. G5B/operating code unchanged; execution=NONE/order=BLOCKED/live=BLOCKED, formal credit0. A separate future child freeze/boundary/authorization would be required for unused validation.
