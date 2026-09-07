# TPR1 frozen DEV economics

Equal nominal trade-bps; terminal includes hypothetical full-cost open marks. Neither account returns nor independent validation. FULL is primary; FIXED is a diagnostic. Parent ledgers reused, Native closed parents match stored ledgers; strict-end censored observations explicitly restored.

## DEV2025

| Metric | P | FIXED | FULL |
|---|---:|---:|---:|
| closed_T | 412.000000 | 412.000000 | 382.000000 |
| open_T | 0.000000 | 0.000000 | 0.000000 |
| entries_T | 412.000000 | 412.000000 | 382.000000 |
| win_rate | 0.235437 | 0.235437 | 0.222513 |
| PF | 0.744184 | 0.810130 | 0.806522 |
| mean_win_bps | 350.238053 | 381.274347 | 402.437658 |
| mean_loss_bps | -144.925240 | -144.925240 | -142.805476 |
| realized_payoff | 2.416681 | 2.630835 | 2.818083 |
| net_expectancy_bps_per_closed_trade | -28.345533 | -21.038444 | -21.481742 |
| closed_gross_bps | -3438.359577 | -295.839122 | -444.025439 |
| closed_net_bps | -11678.359577 | -8667.839122 | -8206.025439 |
| closed_cost2x_net_bps | -19918.359577 | -17039.839122 | -15968.025439 |
| closed_cost_bps | 8240.000000 | 8372.000000 | 7762.000000 |
| closed_fee_bps | 4120.000000 | 4120.000000 | 3820.000000 |
| closed_funding_bps | 1147.000000 | 1330.000000 | 1212.000000 |
| terminal_net_bps_hypothetical | -11678.359577 | -8667.839122 | -8206.025439 |
| terminal_cost2x_net_bps_hypothetical | -19918.359577 | -17039.839122 | -15968.025439 |
| open_net_mark_bps_hypothetical | 0.000000 | 0.000000 | 0.000000 |
| marked_DD_trade_sum_bps | 12263.051834 | 13602.860945 | 12459.859687 |
| grouped_max_loss_trade_sum_bps | 3242.315908 | 2954.484909 | 2954.484909 |
| exposure_symbol_days | 387.041667 | 448.083333 | 410.916667 |
| max_simultaneous_symbols | 2.000000 | 2.000000 | 2.000000 |
| entries_per_30_days | 32.960000 | 32.960000 | 30.560000 |
| max_completed_recovery_days | 12.000000 | 12.000000 | 12.000000 |
| open_underwater_days | 356.333333 | 356.333333 | 356.333333 |

Decisions: {"FIXED": "REJECT", "FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "P": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 2994.3341386755774,
        "net_bps": 3472.3341386755774,
        "cost2x_net_bps": 3950.3341386755774,
        "cost_bps": -478.0,
        "fee_bps": -300.0,
        "spread_bps": -30.0,
        "impact_bps": -60.0,
        "slippage_bps": 0.0,
        "funding_bps": 65.0,
        "frozen_floor_reserve_bps": -153.0
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 40,
          "delta_bps": {
            "gross_bps": -2589.969770192937,
            "net_bps": -3391.969770192937,
            "cost2x_net_bps": -4193.969770192937,
            "cost_bps": 802.0,
            "fee_bps": 400.0,
            "spread_bps": 40.0,
            "impact_bps": 80.0,
            "slippage_bps": 0.0,
            "funding_bps": 87.0,
            "frozen_floor_reserve_bps": 195.0
          }
        },
        "C_ABSENT": {
          "T": 70,
          "delta_bps": {
            "gross_bps": 2835.4452154672995,
            "net_bps": 4235.445215467299,
            "cost2x_net_bps": 5635.445215467299,
            "cost_bps": -1400.0,
            "fee_bps": -700.0,
            "spread_bps": -70.0,
            "impact_bps": -140.0,
            "slippage_bps": 0.0,
            "funding_bps": -183.0,
            "frozen_floor_reserve_bps": -307.0
          }
        },
        "C_C": {
          "T": 342,
          "delta_bps": {
            "gross_bps": 2748.858693401215,
            "net_bps": 2628.858693401215,
            "cost2x_net_bps": 2508.858693401215,
            "cost_bps": 120.0,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 161.0,
            "frozen_floor_reserve_bps": -41.0
          }
        }
      },
      "ordinary_winners": {
        "T": 87,
        "parent_positive_bps": 23168.93588334199,
        "child_signed_terminal_bps": 20336.606515974494,
        "capped_terminal_preserved_bps_hypothetical": 16190.95552694621,
        "capped_terminal_retention_hypothetical": 0.6988217157865757,
        "realized_capped_retention_lower": 0.6988217157865757,
        "realized_capped_retention_upper": 0.6988217157865757,
        "profit_cut_bps": 6977.98035639578,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 6977.98035639578,
        "winner_to_loss_T": 0,
        "winner_removed_T": 15,
        "winner_to_loss_origins": []
      },
      "large_winners": {
        "T": 10,
        "parent_positive_bps": 10804.155290328677,
        "child_signed_terminal_bps": 12731.00785538119,
        "capped_terminal_preserved_bps_hypothetical": 10097.26061401309,
        "capped_terminal_retention_hypothetical": 0.9345719626088341,
        "realized_capped_retention_lower": 0.9345719626088341,
        "realized_capped_retention_upper": 0.9345719626088341,
        "profit_cut_bps": 706.8946763155868,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 706.8946763155868,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "ee0ccaf4b4b699c6bb70368dced72933ceb6f130b4f538c8a23d644afb9b02b0",
        "symbol": "ETH-USDT",
        "signal_ts": 1746572400000,
        "entry_month": "2025-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 2188.452870210792,
          "net_bps": 2168.452870210792,
          "cost2x_net_bps": 2148.452870210792,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 7.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 4262.671792832207,
          "net_bps": 4236.671792832207,
          "cost2x_net_bps": 4210.671792832207,
          "cost_bps": 26.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 13.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 2074.218922621415,
          "net_bps": 2068.218922621415,
          "cost2x_net_bps": 2062.218922621415,
          "cost_bps": 6.0,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": true,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 176400000,
        "child_hold_ms": 349200000
      },
      "net_increment_without_largest_positive": 1404.1152160541624,
      "largest_positive_share_of_net_increment": 0.5956278514746505,
      "increment_by_symbol": {
        "BTC-USDT": 705.9211022446505,
        "ETH-USDT": 2766.4130364309276
      },
      "increment_by_entry_month": {
        "2025-05": 1779.2273834484404,
        "2025-03": 156.38118710792318,
        "2025-12": -158.82062449655098,
        "2025-04": -60.52731929943249,
        "2025-11": 455.42478771617294,
        "2025-09": 829.7953119736101,
        "2025-01": -408.5733705383154,
        "2025-10": -36.08999980404231,
        "2025-06": -561.92449984567,
        "2025-07": 1070.9364438502148,
        "2025-02": -292.5079073981359,
        "2025-08": 604.0359617037664,
        "2024-12": 94.97678425759705
      },
      "parity": "PASS",
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "cost_saving_already_in_net": true,
      "post_outcome_diagnostic_only": true,
      "independent": false
    }
  },
  "occupancy_bridge_summary": {
    "gross_bps": {
      "fixed_path_or_filter_effect": 3142.520455685769,
      "full_occupancy_remainder": -148.18631701019143,
      "full_total_effect": 2994.3341386755774
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 3010.520455685768,
      "full_occupancy_remainder": 461.8136829898085,
      "full_total_effect": 3472.3341386755765
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 2878.5204556857716,
      "full_occupancy_remainder": 1071.8136829898067,
      "full_total_effect": 3950.3341386755783
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 132.0,
      "full_occupancy_remainder": -610.0,
      "full_total_effect": -478.0
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -300.0,
      "full_total_effect": -300.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -30.0,
      "full_total_effect": -30.0
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -60.0,
      "full_total_effect": -60.0
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 183.0,
      "full_occupancy_remainder": -118.0,
      "full_total_effect": 65.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -51.0,
      "full_occupancy_remainder": -102.0,
      "full_total_effect": -153.0
    }
  },
  "uncertainty": {
    "FIXED": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 376,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 12.533333333333333,
      "N_effective": null,
      "calendar_start": "2024-12-19",
      "calendar_last_day": "2025-12-29",
      "parent_marked_delta_sum_bps": -11678.35957741325,
      "child_marked_delta_sum_bps": -8667.839121727482,
      "child_minus_parent_marked_delta_sum_bps": 3010.520455685768,
      "child_minus_parent_mean_daily_bps": 8.006703339589809,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -7.103580067523046,
        24.03045649655965
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -2670.9461053886653,
        9035.451642706428
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    },
    "FULL": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 376,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 12.533333333333333,
      "N_effective": null,
      "calendar_start": "2024-12-19",
      "calendar_last_day": "2025-12-29",
      "parent_marked_delta_sum_bps": -11678.35957741325,
      "child_marked_delta_sum_bps": -8206.025438737674,
      "child_minus_parent_marked_delta_sum_bps": 3472.3341386755765,
      "child_minus_parent_mean_daily_bps": 9.234931219881853,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -4.629192299529682,
        24.612382439482698
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1740.5763046231602,
        9254.255797245494
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    }
  },
  "concentration": {
    "P": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "BTC-USDT": -4545.522114755077,
          "ETH-USDT": -7132.837462658174
        },
        "by_symbol_positive_trade_profit_bps": {
          "BTC-USDT": 13346.470921754975,
          "ETH-USDT": 20626.6202519157
        },
        "total_positive_trade_profit_bps": 33973.09117367067,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.6071458186266384,
        "winner_T": 97,
        "top_decile_winner_T": 10,
        "top_decile_winners_share": 0.3180209665083982,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": -1036.9196879316364,
          "2025-01": -3202.7138945863894,
          "2025-02": -2370.1547882286163,
          "2025-03": -3362.147064914766,
          "2025-04": -821.9009576892964,
          "2025-05": 2396.895739920982,
          "2025-06": -1373.954054023598,
          "2025-07": -120.23700632397913,
          "2025-08": 1008.1245434816309,
          "2025-09": -1496.176285334711,
          "2025-10": 26.886080644312102,
          "2025-11": 133.50140722003346,
          "2025-12": -1459.5636096472163
        },
        "top_positive_month_share": 0.6722641262065941
      },
      "weekly": [
        {
          "utc_monday_ms": 1734912000000,
          "T": 8,
          "net_trade_sum_bps": -580.2432236229504
        },
        {
          "utc_monday_ms": 1735516800000,
          "T": 7,
          "net_trade_sum_bps": 476.77173228617335
        },
        {
          "utc_monday_ms": 1736121600000,
          "T": 7,
          "net_trade_sum_bps": -587.6114823675515
        },
        {
          "utc_monday_ms": 1736726400000,
          "T": 11,
          "net_trade_sum_bps": -901.0125402031459
        },
        {
          "utc_monday_ms": 1737331200000,
          "T": 12,
          "net_trade_sum_bps": -1975.2268321219035
        },
        {
          "utc_monday_ms": 1737936000000,
          "T": 6,
          "net_trade_sum_bps": -429.8317074096585
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 9,
          "net_trade_sum_bps": -1812.900580083931
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 10,
          "net_trade_sum_bps": -920.4508879026266
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 7,
          "net_trade_sum_bps": -365.3797337608508
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 5,
          "net_trade_sum_bps": 851.1629696955974
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 6,
          "net_trade_sum_bps": -1168.0354200484644
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 10,
          "net_trade_sum_bps": -376.1092830456232
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 11,
          "net_trade_sum_bps": -902.0931445189582
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 8,
          "net_trade_sum_bps": -810.7049787689018
        },
        {
          "utc_monday_ms": 1743379200000,
          "T": 11,
          "net_trade_sum_bps": -1345.2012769951
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 6,
          "net_trade_sum_bps": 31.909852340389378
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 8,
          "net_trade_sum_bps": -829.5271086156912
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 6,
          "net_trade_sum_bps": 1447.6022126491985
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 13,
          "net_trade_sum_bps": -923.7664508158621
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 5,
          "net_trade_sum_bps": 2521.580244404668
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 11,
          "net_trade_sum_bps": -1064.3047211394435
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 6,
          "net_trade_sum_bps": 357.0946384247322
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 7,
          "net_trade_sum_bps": 909.3370681901811
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 8,
          "net_trade_sum_bps": -546.2351436568034
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 10,
          "net_trade_sum_bps": 467.4253963876841
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 7,
          "net_trade_sum_bps": -382.6709813258757
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 7,
          "net_trade_sum_bps": -986.7226106295627
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": 518.7443998406314
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 3,
          "net_trade_sum_bps": 435.5982069023296
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 7,
          "net_trade_sum_bps": -213.74557250882128
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 9,
          "net_trade_sum_bps": 228.23924337093223
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 9,
          "net_trade_sum_bps": -891.0520400579867
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 7,
          "net_trade_sum_bps": 903.5273379942944
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": -472.8680359984305
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 4,
          "net_trade_sum_bps": 840.8934112304121
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 5,
          "net_trade_sum_bps": -387.20012841474966
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 15,
          "net_trade_sum_bps": -1852.543931851263
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 9,
          "net_trade_sum_bps": 201.47315171307432
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 9,
          "net_trade_sum_bps": -422.75564459717816
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 3,
          "net_trade_sum_bps": 83.79205452494857
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 4,
          "net_trade_sum_bps": 1379.2146971066722
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 8,
          "net_trade_sum_bps": -503.00584085565725
        },
        {
          "utc_monday_ms": 1760313600000,
          "T": 6,
          "net_trade_sum_bps": -714.387070202135
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 5,
          "net_trade_sum_bps": 57.48560437281911
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 7,
          "net_trade_sum_bps": 115.54456307071794
        },
        {
          "utc_monday_ms": 1762128000000,
          "T": 6,
          "net_trade_sum_bps": 2247.3423561444097
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 8,
          "net_trade_sum_bps": -1187.5424059737466
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 8,
          "net_trade_sum_bps": -1424.3897194578792
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 10,
          "net_trade_sum_bps": 683.9833885348519
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 8,
          "net_trade_sum_bps": 7.59543684248311
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 7,
          "net_trade_sum_bps": 122.9516937844482
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 11,
          "net_trade_sum_bps": -878.6820079723873
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 8,
          "net_trade_sum_bps": -711.4287323017604
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "BTC-USDT": -3878.642837012161,
          "ETH-USDT": -4789.196284715333
        },
        "by_symbol_positive_trade_profit_bps": {
          "BTC-USDT": 14013.350199497894,
          "ETH-USDT": 22970.261429858554
        },
        "total_positive_trade_profit_bps": 36983.611629356434,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.6210929765341111,
        "winner_T": 97,
        "top_decile_winner_T": 10,
        "top_decile_winners_share": 0.37845276278669315,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": -1036.9196879316364,
          "2025-01": -3323.155194653848,
          "2025-02": -2938.4172791371157,
          "2025-03": -3543.0073064348676,
          "2025-04": -921.4125171227788,
          "2025-05": 3820.674183969565,
          "2025-06": -1646.53207995453,
          "2025-07": 773.3019728952154,
          "2025-08": 2359.518880919663,
          "2025-09": -1327.1546623988884,
          "2025-10": 1539.9034660854445,
          "2025-11": -350.9292851525526,
          "2025-12": -2073.709612811152
        },
        "top_positive_month_share": 0.44984044752271224
      },
      "weekly": [
        {
          "utc_monday_ms": 1734912000000,
          "T": 8,
          "net_trade_sum_bps": -580.2432236229504
        },
        {
          "utc_monday_ms": 1735516800000,
          "T": 6,
          "net_trade_sum_bps": -85.97865951258446
        },
        {
          "utc_monday_ms": 1736121600000,
          "T": 8,
          "net_trade_sum_bps": 198.59473135323233
        },
        {
          "utc_monday_ms": 1736726400000,
          "T": 11,
          "net_trade_sum_bps": -1120.4143400887835
        },
        {
          "utc_monday_ms": 1737331200000,
          "T": 12,
          "net_trade_sum_bps": -2099.7221542257503
        },
        {
          "utc_monday_ms": 1737936000000,
          "T": 6,
          "net_trade_sum_bps": -504.8583328280582
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 9,
          "net_trade_sum_bps": -1812.900580083931
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 10,
          "net_trade_sum_bps": -1211.3387999241388
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 7,
          "net_trade_sum_bps": -567.7276872294384
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 4,
          "net_trade_sum_bps": 13.392634243107267
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 7,
          "net_trade_sum_bps": -565.8769787127518
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 10,
          "net_trade_sum_bps": -454.27425276620295
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 10,
          "net_trade_sum_bps": -997.7888060205489
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 9,
          "net_trade_sum_bps": -582.0926949500556
        },
        {
          "utc_monday_ms": 1743379200000,
          "T": 11,
          "net_trade_sum_bps": -1539.055500790842
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 6,
          "net_trade_sum_bps": -21.025180341197583
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 8,
          "net_trade_sum_bps": -829.5271086156912
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 6,
          "net_trade_sum_bps": 1623.916458078425
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 13,
          "net_trade_sum_bps": -952.8029992012421
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 5,
          "net_trade_sum_bps": 4697.61925305855
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 11,
          "net_trade_sum_bps": -1149.2576134630133
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 6,
          "net_trade_sum_bps": -102.80737022462743
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 7,
          "net_trade_sum_bps": 701.9314045578109
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 7,
          "net_trade_sum_bps": -698.460205970333
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 11,
          "net_trade_sum_bps": 417.4633884992667
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 7,
          "net_trade_sum_bps": -382.6709813258757
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 7,
          "net_trade_sum_bps": -986.7226106295627
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": 322.7525609063681
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 3,
          "net_trade_sum_bps": 1820.6965485965845
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 7,
          "net_trade_sum_bps": -253.471101364548
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 7,
          "net_trade_sum_bps": -485.967784502771
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 11,
          "net_trade_sum_bps": -507.9067066056763
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 7,
          "net_trade_sum_bps": 1171.5955439779
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": 444.0018493144142
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 4,
          "net_trade_sum_bps": 1012.1784013793313
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 5,
          "net_trade_sum_bps": -387.20012841474966
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 15,
          "net_trade_sum_bps": -1852.543931851263
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 9,
          "net_trade_sum_bps": 647.5639409973953
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 9,
          "net_trade_sum_bps": -422.75564459717816
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 3,
          "net_trade_sum_bps": 83.79205452494857
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 4,
          "net_trade_sum_bps": 1840.7067018597982
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 8,
          "net_trade_sum_bps": -626.4577554915995
        },
        {
          "utc_monday_ms": 1760313600000,
          "T": 6,
          "net_trade_sum_bps": -714.387070202135
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 3,
          "net_trade_sum_bps": -293.34487656292504
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 9,
          "net_trade_sum_bps": 1364.283172981913
        },
        {
          "utc_monday_ms": 1762128000000,
          "T": 4,
          "net_trade_sum_bps": 1618.6754597112454
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 10,
          "net_trade_sum_bps": -603.55892548764
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 8,
          "net_trade_sum_bps": -1424.3897194578792
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 10,
          "net_trade_sum_bps": 244.2361121093235
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 8,
          "net_trade_sum_bps": -291.67001131921927
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 7,
          "net_trade_sum_bps": -59.43213532535634
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 11,
          "net_trade_sum_bps": -1011.1787338648162
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 8,
          "net_trade_sum_bps": -711.4287323017604
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "BTC-USDT": -3839.601012510429,
          "ETH-USDT": -4366.424426227245
        },
        "by_symbol_positive_trade_profit_bps": {
          "BTC-USDT": 13041.054528847688,
          "ETH-USDT": 21166.14636897873
        },
        "total_positive_trade_profit_bps": 34207.20089782641,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.6187628865688237,
        "winner_T": 85,
        "top_decile_winner_T": 9,
        "top_decile_winners_share": 0.3720576292884125,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": -1036.9196879316364,
          "2025-01": -3441.283855448708,
          "2025-02": -2502.0774269283743,
          "2025-03": -3247.5235481278783,
          "2025-04": -1076.282500784471,
          "2025-05": 4176.1231233694225,
          "2025-06": -1915.8572256318705,
          "2025-07": 930.678109288838,
          "2025-08": 1612.1605051853971,
          "2025-09": -1558.076956340723,
          "2025-10": 882.4920638198917,
          "2025-11": 588.9261949362062,
          "2025-12": -1618.3842341437673
        },
        "top_positive_month_share": 0.5098814859753936
      },
      "weekly": [
        {
          "utc_monday_ms": 1734912000000,
          "T": 8,
          "net_trade_sum_bps": -580.2432236229504
        },
        {
          "utc_monday_ms": 1735516800000,
          "T": 5,
          "net_trade_sum_bps": -159.1524309900291
        },
        {
          "utc_monday_ms": 1736121600000,
          "T": 8,
          "net_trade_sum_bps": 36.806423738939074
        },
        {
          "utc_monday_ms": 1736726400000,
          "T": 10,
          "net_trade_sum_bps": -1003.5809217919059
        },
        {
          "utc_monday_ms": 1737331200000,
          "T": 12,
          "net_trade_sum_bps": -2099.7221542257503
        },
        {
          "utc_monday_ms": 1737936000000,
          "T": 5,
          "net_trade_sum_bps": -334.54802520961397
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 9,
          "net_trade_sum_bps": -1812.900580083931
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 10,
          "net_trade_sum_bps": -1160.2246602319335
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 6,
          "net_trade_sum_bps": -349.79249219501816
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 4,
          "net_trade_sum_bps": 10.3728441067789
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 7,
          "net_trade_sum_bps": -565.8769787127518
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 8,
          "net_trade_sum_bps": -270.87905465793403
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 10,
          "net_trade_sum_bps": -997.7888060205489
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 8,
          "net_trade_sum_bps": -470.004134751335
        },
        {
          "utc_monday_ms": 1743379200000,
          "T": 11,
          "net_trade_sum_bps": -1539.055500790842
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 4,
          "net_trade_sum_bps": 299.70472337015684
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 8,
          "net_trade_sum_bps": -829.5271086156912
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 7,
          "net_trade_sum_bps": 1248.752148303238
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 13,
          "net_trade_sum_bps": -1053.2385767991018
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 5,
          "net_trade_sum_bps": 4697.61925305855
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 8,
          "net_trade_sum_bps": -476.4224606355831
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 5,
          "net_trade_sum_bps": 5.236862492679634
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 6,
          "net_trade_sum_bps": 276.50095841293114
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 7,
          "net_trade_sum_bps": -698.460205970333
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 10,
          "net_trade_sum_bps": 148.1382428219262
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 7,
          "net_trade_sum_bps": -382.6709813258757
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 7,
          "net_trade_sum_bps": -986.7226106295627
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": -238.12333050067633
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 3,
          "net_trade_sum_bps": 1820.6965485965845
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 5,
          "net_trade_sum_bps": 26.220020062573354
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 6,
          "net_trade_sum_bps": -279.06806823980196
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 9,
          "net_trade_sum_bps": -276.24551649509976
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 7,
          "net_trade_sum_bps": 1171.5955439779
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": -303.35652641985143
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 4,
          "net_trade_sum_bps": 1012.1784013793313
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 5,
          "net_trade_sum_bps": -387.20012841474966
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 15,
          "net_trade_sum_bps": -1852.543931851263
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 10,
          "net_trade_sum_bps": 416.64164705556067
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 9,
          "net_trade_sum_bps": -422.75564459717816
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 3,
          "net_trade_sum_bps": 83.79205452494857
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 4,
          "net_trade_sum_bps": 1698.5364327420773
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 7,
          "net_trade_sum_bps": -528.5989957455649
        },
        {
          "utc_monday_ms": 1760313600000,
          "T": 6,
          "net_trade_sum_bps": -714.387070202135
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 3,
          "net_trade_sum_bps": -293.34487656292504
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 8,
          "net_trade_sum_bps": 751.1832800880461
        },
        {
          "utc_monday_ms": 1762128000000,
          "T": 4,
          "net_trade_sum_bps": 1618.6754597112454
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 10,
          "net_trade_sum_bps": -597.5585825553736
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 8,
          "net_trade_sum_bps": -1424.3897194578792
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 4,
          "net_trade_sum_bps": 1178.091249265816
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 8,
          "net_trade_sum_bps": -261.478733605574
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 4,
          "net_trade_sum_bps": 418.0420170519052
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 9,
          "net_trade_sum_bps": -872.0396108352037
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 9,
          "net_trade_sum_bps": -902.9079067548948
        }
      ]
    }
  },
  "partial_assets": {
    "preserve_development_evidence": true,
    "formal_or_operating_adoption": false
  }
}
```

No automatic adoption or further candidate is authorized. Old verdicts, Q0 observer, G5B and prior budgets are preserved.
