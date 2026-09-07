# TBR1 frozen DEV economics

Equal nominal trade-bps; terminal includes hypothetical full-cost open marks. Neither account returns nor independent validation. FULL is primary; FIXED is a diagnostic. Parent ledgers reused, Native closed parents match stored ledgers; strict-end censored observations explicitly restored.

## DEV2025

| Metric | P | FIXED | FULL |
|---|---:|---:|---:|
| closed_T | 457.000000 | 457.000000 | 419.000000 |
| open_T | 2.000000 | 2.000000 | 2.000000 |
| entries_T | 459.000000 | 459.000000 | 421.000000 |
| win_rate | 0.223195 | 0.223195 | 0.221957 |
| PF | 0.719893 | 0.792303 | 0.777070 |
| mean_win_bps | 364.640148 | 402.128527 | 394.654150 |
| mean_loss_bps | -145.535370 | -145.829449 | -144.884516 |
| realized_payoff | 2.505509 | 2.757526 | 2.723922 |
| net_expectancy_bps_per_closed_trade | -31.666874 | -23.528106 | -25.130110 |
| closed_gross_bps | -5331.761301 | -1459.344496 | -2019.516143 |
| closed_net_bps | -14471.761301 | -10752.344496 | -10529.516143 |
| closed_cost2x_net_bps | -23611.761301 | -20045.344496 | -19039.516143 |
| closed_cost_bps | 9140.000000 | 9293.000000 | 8510.000000 |
| closed_fee_bps | 4570.000000 | 4570.000000 | 4190.000000 |
| closed_funding_bps | 1244.000000 | 1454.000000 | 1318.000000 |
| terminal_net_bps_hypothetical | -14081.642929 | -10362.226124 | -10139.397772 |
| terminal_cost2x_net_bps_hypothetical | -23261.642929 | -19695.226124 | -18689.397772 |
| open_net_mark_bps_hypothetical | 390.118372 | 390.118372 | 390.118372 |
| marked_DD_trade_sum_bps | 14603.902097 | 14352.853355 | 12942.693982 |
| grouped_max_loss_trade_sum_bps | 3657.901462 | 3366.045507 | 3366.045507 |
| exposure_symbol_days | 419.458333 | 488.916667 | 445.416667 |
| max_simultaneous_symbols | 2.000000 | 2.000000 | 2.000000 |
| entries_per_30_days | 36.720000 | 36.720000 | 33.680000 |
| max_completed_recovery_days | 15.000000 | 12.000000 | 12.000000 |
| open_underwater_days | 356.333333 | 356.333333 | 356.333333 |

Decisions: {"FIXED": "REJECT", "FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "P": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 3312.24515721249,
        "net_bps": 3942.2451572124905,
        "cost2x_net_bps": 4572.24515721249,
        "cost_bps": -630.0,
        "fee_bps": -380.0,
        "spread_bps": -38.0,
        "impact_bps": -76.0,
        "slippage_bps": 0.0,
        "funding_bps": 74.0,
        "frozen_floor_reserve_bps": -210.0
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 55,
          "delta_bps": {
            "gross_bps": -2660.66622658407,
            "net_bps": -3764.66622658407,
            "cost2x_net_bps": -4868.66622658407,
            "cost_bps": 1104.0,
            "fee_bps": 550.0,
            "spread_bps": 55.0,
            "impact_bps": 110.0,
            "slippage_bps": 0.0,
            "funding_bps": 151.0,
            "frozen_floor_reserve_bps": 238.0
          }
        },
        "C_ABSENT": {
          "T": 93,
          "delta_bps": {
            "gross_bps": 2701.7123839880046,
            "net_bps": 4561.712383988005,
            "cost2x_net_bps": 6421.712383988005,
            "cost_bps": -1860.0,
            "fee_bps": -930.0,
            "spread_bps": -93.0,
            "impact_bps": -186.0,
            "slippage_bps": 0.0,
            "funding_bps": -247.0,
            "frozen_floor_reserve_bps": -404.0
          }
        },
        "C_C": {
          "T": 364,
          "delta_bps": {
            "gross_bps": 3271.1989998085555,
            "net_bps": 3145.1989998085555,
            "cost2x_net_bps": 3019.1989998085555,
            "cost_bps": 126.0,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 170.0,
            "frozen_floor_reserve_bps": -44.0
          }
        },
        "O_O": {
          "T": 2,
          "delta_bps": {
            "gross_bps": 0.0,
            "net_bps": 0.0,
            "cost2x_net_bps": 0.0,
            "cost_bps": 0.0,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 0.0,
            "frozen_floor_reserve_bps": 0.0
          }
        }
      },
      "ordinary_winners": {
        "T": 91,
        "parent_positive_bps": 25102.79440140828,
        "child_signed_terminal_bps": 21396.703786445152,
        "capped_terminal_preserved_bps_hypothetical": 17079.2315562689,
        "capped_terminal_retention_hypothetical": 0.6803717260780635,
        "realized_capped_retention_lower": 0.6803717260780635,
        "realized_capped_retention_upper": 0.6803717260780635,
        "profit_cut_bps": 8023.562845139379,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 8023.562845139379,
        "winner_to_loss_T": 0,
        "winner_removed_T": 17,
        "winner_to_loss_origins": []
      },
      "large_winners": {
        "T": 11,
        "parent_positive_bps": 12090.50067865908,
        "child_signed_terminal_bps": 13528.149331260447,
        "capped_terminal_preserved_bps_hypothetical": 10370.05598738757,
        "capped_terminal_retention_hypothetical": 0.8577027753442614,
        "realized_capped_retention_lower": 0.8577027753442614,
        "realized_capped_retention_upper": 0.8577027753442614,
        "profit_cut_bps": 1720.4446912715098,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 1720.4446912715098,
        "winner_to_loss_T": 0,
        "winner_removed_T": 1,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "f5990697fab23c4df5aed33cca05e710612c67720ec4a1475b47d6f8c945a7a3",
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
      "net_increment_without_largest_positive": 1874.0262345910755,
      "largest_positive_share_of_net_increment": 0.5246297072209039,
      "increment_by_symbol": {
        "BTC-USDT": -229.60036322436173,
        "ETH-USDT": 4171.845520436854
      },
      "increment_by_entry_month": {
        "2025-11": 41.54011616948548,
        "2024-12": 204.7859011992289,
        "2025-09": 334.157489811901,
        "2025-06": -538.6449441793478,
        "2025-03": 392.4945017204917,
        "2025-04": 11.175197103264026,
        "2025-12": -105.13707175059716,
        "2025-02": -383.22085449109727,
        "2025-05": 1758.5524618046165,
        "2025-07": 955.9039890935501,
        "2025-10": 547.9772212811588,
        "2025-01": -359.4217584587874,
        "2025-08": 1082.082907908624
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
      "fixed_path_or_filter_effect": 3872.416804800745,
      "full_occupancy_remainder": -560.1716475882547,
      "full_total_effect": 3312.24515721249
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 3719.416804800745,
      "full_occupancy_remainder": 222.82835241174507,
      "full_total_effect": 3942.24515721249
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 3566.416804800745,
      "full_occupancy_remainder": 1005.8283524117433,
      "full_total_effect": 4572.245157212488
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 153.0,
      "full_occupancy_remainder": -783.0,
      "full_total_effect": -630.0
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -380.0,
      "full_total_effect": -380.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -38.0,
      "full_total_effect": -38.0
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -76.0,
      "full_total_effect": -76.0
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 210.0,
      "full_occupancy_remainder": -136.0,
      "full_total_effect": 74.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -57.0,
      "full_occupancy_remainder": -153.0,
      "full_total_effect": -210.0
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
      "parent_marked_delta_sum_bps": -14081.64292891933,
      "child_marked_delta_sum_bps": -10362.226124118584,
      "child_minus_parent_marked_delta_sum_bps": 3719.416804800745,
      "child_minus_parent_mean_daily_bps": 9.892065970214748,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -6.402132764125569,
        27.48314569258552
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -2407.2019193112137,
        10333.662780412156
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
      "parent_marked_delta_sum_bps": -14081.64292891933,
      "child_marked_delta_sum_bps": -10139.39777170684,
      "child_minus_parent_marked_delta_sum_bps": 3942.24515721249,
      "child_minus_parent_mean_daily_bps": 10.484694567054495,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -4.372398653173437,
        26.073472673745464
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1644.021893593212,
        9803.625725328295
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
          "BTC-USDT": -7034.264520455353,
          "ETH-USDT": -7437.496780185972
        },
        "by_symbol_positive_trade_profit_bps": {
          "BTC-USDT": 13527.6941529474,
          "ETH-USDT": 23665.600927119955
        },
        "total_positive_trade_profit_bps": 37193.29508006736,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.6362867521195462,
        "winner_T": 102,
        "top_decile_winner_T": 11,
        "top_decile_winners_share": 0.32507205001953765,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": -1235.3571002948893,
          "2025-01": -4345.112480371193,
          "2025-02": -2542.4266026596706,
          "2025-03": -3785.945795172099,
          "2025-04": -96.75496234092235,
          "2025-05": 2363.070045595976,
          "2025-06": -1050.9232969916814,
          "2025-07": 1601.7702222716518,
          "2025-08": 253.6679562989372,
          "2025-09": -1526.0166610651647,
          "2025-10": 575.3271482666797,
          "2025-11": -2357.620861305039,
          "2025-12": -2325.43891287391
        },
        "top_positive_month_share": 0.49293934021696156
      },
      "weekly": [
        {
          "utc_monday_ms": 1734912000000,
          "T": 9,
          "net_trade_sum_bps": -638.5310774327432
        },
        {
          "utc_monday_ms": 1735516800000,
          "T": 9,
          "net_trade_sum_bps": 147.25185193486936
        },
        {
          "utc_monday_ms": 1736121600000,
          "T": 7,
          "net_trade_sum_bps": -594.8223527344597
        },
        {
          "utc_monday_ms": 1736726400000,
          "T": 12,
          "net_trade_sum_bps": -1062.9448543240935
        },
        {
          "utc_monday_ms": 1737331200000,
          "T": 14,
          "net_trade_sum_bps": -2640.282319180381
        },
        {
          "utc_monday_ms": 1737936000000,
          "T": 7,
          "net_trade_sum_bps": -548.6612998502845
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 10,
          "net_trade_sum_bps": -1918.6720844941328
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 10,
          "net_trade_sum_bps": -926.8374877814688
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 8,
          "net_trade_sum_bps": -453.29347984386516
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 5,
          "net_trade_sum_bps": 878.9630056366019
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 9,
          "net_trade_sum_bps": -1072.3056294363928
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 9,
          "net_trade_sum_bps": -815.8390054928907
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 13,
          "net_trade_sum_bps": -1123.2634414341767
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 7,
          "net_trade_sum_bps": -669.3334802758211
        },
        {
          "utc_monday_ms": 1743379200000,
          "T": 12,
          "net_trade_sum_bps": -1526.4989123256746
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 9,
          "net_trade_sum_bps": 1009.1685408734553
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 9,
          "net_trade_sum_bps": -900.3421664698084
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 6,
          "net_trade_sum_bps": 1447.6022126491985
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 15,
          "net_trade_sum_bps": -1141.989365380486
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 4,
          "net_trade_sum_bps": 2591.7301724994036
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 11,
          "net_trade_sum_bps": -1168.8960510423578
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 6,
          "net_trade_sum_bps": 491.6231765731362
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 6,
          "net_trade_sum_bps": 993.647152089574
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 8,
          "net_trade_sum_bps": -229.5968400814324
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 11,
          "net_trade_sum_bps": 280.6947578190705
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 9,
          "net_trade_sum_bps": -1123.9994166747813
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 10,
          "net_trade_sum_bps": -52.94772047048292
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": 519.4210370556162
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 4,
          "net_trade_sum_bps": 1400.8847294501807
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 11,
          "net_trade_sum_bps": 542.9751335389587
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
          "net_trade_sum_bps": 849.9910314164116
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": -472.8680359984305
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 6,
          "net_trade_sum_bps": 502.7266879719499
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 6,
          "net_trade_sum_bps": -749.9536857610984
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 15,
          "net_trade_sum_bps": -1463.663151523042
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 8,
          "net_trade_sum_bps": 249.20026826879408
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 11,
          "net_trade_sum_bps": -826.9498332417718
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 3,
          "net_trade_sum_bps": 21.537970555147737
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 5,
          "net_trade_sum_bps": 2002.8277842101688
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 9,
          "net_trade_sum_bps": -621.8265122036684
        },
        {
          "utc_monday_ms": 1760313600000,
          "T": 6,
          "net_trade_sum_bps": -722.8967739804738
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 6,
          "net_trade_sum_bps": -46.046884781688036
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 7,
          "net_trade_sum_bps": 458.5075898789738
        },
        {
          "utc_monday_ms": 1762128000000,
          "T": 7,
          "net_trade_sum_bps": -524.5332171213922
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 9,
          "net_trade_sum_bps": -815.9521951918553
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 8,
          "net_trade_sum_bps": -1455.0262451132226
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 12,
          "net_trade_sum_bps": 436.5108261405053
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 9,
          "net_trade_sum_bps": -199.2124310348651
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 7,
          "net_trade_sum_bps": 83.64422587999684
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 13,
          "net_trade_sum_bps": -1170.4317770191524
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 11,
          "net_trade_sum_bps": -1039.4389306998894
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "BTC-USDT": -6749.883931261698,
          "ETH-USDT": -4002.4605645788806
        },
        "by_symbol_positive_trade_profit_bps": {
          "BTC-USDT": 13916.472602155058,
          "ETH-USDT": 27100.63714272706
        },
        "total_positive_trade_profit_bps": 41017.10974488211,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.6607154261060174,
        "winner_T": 102,
        "top_decile_winner_T": 11,
        "top_decile_winners_share": 0.3929979786274425,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": -1271.645621956345,
          "2025-01": -4286.499416621053,
          "2025-02": -3110.68909356817,
          "2025-03": -4017.350581661828,
          "2025-04": -196.26652177440465,
          "2025-05": 3817.521049962031,
          "2025-06": -1430.4727938211538,
          "2025-07": 3193.285415487847,
          "2025-08": 1853.2047321101934,
          "2025-09": -1451.9360582167756,
          "2025-10": 2134.562346813568,
          "2025-11": -2940.043770469978,
          "2025-12": -3046.0141821245115
        },
        "top_positive_month_share": 0.34709237834890855
      },
      "weekly": [
        {
          "utc_monday_ms": 1734912000000,
          "T": 9,
          "net_trade_sum_bps": -674.819599094199
        },
        {
          "utc_monday_ms": 1735516800000,
          "T": 8,
          "net_trade_sum_bps": -386.8121941135198
        },
        {
          "utc_monday_ms": 1736121600000,
          "T": 8,
          "net_trade_sum_bps": 217.2469308189967
        },
        {
          "utc_monday_ms": 1736726400000,
          "T": 12,
          "net_trade_sum_bps": -1282.346654209731
        },
        {
          "utc_monday_ms": 1737331200000,
          "T": 14,
          "net_trade_sum_bps": -2640.272693049671
        },
        {
          "utc_monday_ms": 1737936000000,
          "T": 7,
          "net_trade_sum_bps": -623.6879252686842
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 10,
          "net_trade_sum_bps": -1918.6720844941328
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 10,
          "net_trade_sum_bps": -1217.725399802981
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 8,
          "net_trade_sum_bps": -655.6414333124527
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 4,
          "net_trade_sum_bps": 41.19267018411179
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 10,
          "net_trade_sum_bps": -470.1471881006803
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 9,
          "net_trade_sum_bps": -894.0039752134704
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 12,
          "net_trade_sum_bps": -1269.503647905394
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 8,
          "net_trade_sum_bps": -440.7211964569749
        },
        {
          "utc_monday_ms": 1743379200000,
          "T": 12,
          "net_trade_sum_bps": -1720.3531361214166
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 9,
          "net_trade_sum_bps": 956.2335081918684
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 9,
          "net_trade_sum_bps": -900.3421664698084
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 6,
          "net_trade_sum_bps": 1623.916458078425
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 15,
          "net_trade_sum_bps": -1171.025913765866
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 4,
          "net_trade_sum_bps": 4855.968186778033
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 11,
          "net_trade_sum_bps": -1253.8489433659279
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 6,
          "net_trade_sum_bps": 31.721167923776598
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 6,
          "net_trade_sum_bps": 728.7150431499293
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 7,
          "net_trade_sum_bps": -381.9000545650523
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 12,
          "net_trade_sum_bps": 230.73274993065314
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 9,
          "net_trade_sum_bps": -1123.9994166747813
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 10,
          "net_trade_sum_bps": -159.841039198933
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": 323.4291981213529
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 4,
          "net_trade_sum_bps": 3115.793318155335
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 11,
          "net_trade_sum_bps": 871.4155716693333
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
          "net_trade_sum_bps": 1366.2016757732413
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": 444.0018493144142
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 6,
          "net_trade_sum_bps": 674.0116781208691
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 6,
          "net_trade_sum_bps": -749.9536857610984
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 15,
          "net_trade_sum_bps": -1568.235465595336
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 8,
          "net_trade_sum_bps": 704.9223515379754
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 11,
          "net_trade_sum_bps": -826.9498332417718
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 3,
          "net_trade_sum_bps": 21.537970555147737
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 5,
          "net_trade_sum_bps": 2510.675433494365
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 9,
          "net_trade_sum_bps": -745.2784268396107
        },
        {
          "utc_monday_ms": 1760313600000,
          "T": 6,
          "net_trade_sum_bps": -722.8967739804738
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 4,
          "net_trade_sum_bps": -338.2675966114308
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 9,
          "net_trade_sum_bps": 1648.4985992588533
        },
        {
          "utc_monday_ms": 1762128000000,
          "T": 6,
          "net_trade_sum_bps": -965.2024271367893
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 10,
          "net_trade_sum_bps": -605.3668270534521
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 8,
          "net_trade_sum_bps": -1455.0262451132226
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 11,
          "net_trade_sum_bps": 84.17175885256046
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 10,
          "net_trade_sum_bps": -604.9071452832331
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 7,
          "net_trade_sum_bps": -98.7396032298077
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 13,
          "net_trade_sum_bps": -1302.9285029115813
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 11,
          "net_trade_sum_bps": -1039.4389306998894
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "BTC-USDT": -7263.864883679715,
          "ETH-USDT": -3265.651259749125
        },
        "by_symbol_positive_trade_profit_bps": {
          "BTC-USDT": 12204.485681135,
          "ETH-USDT": 24498.35023450792
        },
        "total_positive_trade_profit_bps": 36702.835915642914,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.6674784011462889,
        "winner_T": 93,
        "top_decile_winner_T": 10,
        "top_decile_winners_share": 0.3919316163836622,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": -1125.5479833532575,
          "2025-01": -4534.530829153983,
          "2025-02": -2765.06218845239,
          "2025-03": -3435.208963772643,
          "2025-04": -279.4339890334002,
          "2025-05": 4121.622507400592,
          "2025-06": -1540.0253407156183,
          "2025-07": 2508.131310909791,
          "2025-08": 1335.7508642075607,
          "2025-09": -1385.2996631327271,
          "2025-10": 1316.7448614273019,
          "2025-11": -2230.150148122165,
          "2025-12": -2516.506581637896
        },
        "top_positive_month_share": 0.4440327194272751
      },
      "weekly": [
        {
          "utc_monday_ms": 1734912000000,
          "T": 8,
          "net_trade_sum_bps": -528.7219604911113
        },
        {
          "utc_monday_ms": 1735516800000,
          "T": 7,
          "net_trade_sum_bps": -459.98596559096444
        },
        {
          "utc_monday_ms": 1736121600000,
          "T": 9,
          "net_trade_sum_bps": -80.43230428954423
        },
        {
          "utc_monday_ms": 1736726400000,
          "T": 11,
          "net_trade_sum_bps": -1161.4882803447395
        },
        {
          "utc_monday_ms": 1737331200000,
          "T": 14,
          "net_trade_sum_bps": -2638.3094728616074
        },
        {
          "utc_monday_ms": 1737936000000,
          "T": 6,
          "net_trade_sum_bps": -453.37761765024
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 10,
          "net_trade_sum_bps": -1918.6720844941328
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 10,
          "net_trade_sum_bps": -1166.6112601107757
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 7,
          "net_trade_sum_bps": -531.4389755073222
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 4,
          "net_trade_sum_bps": 41.19267018411179
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 10,
          "net_trade_sum_bps": -467.3396630257531
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 7,
          "net_trade_sum_bps": -708.5944054090975
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 12,
          "net_trade_sum_bps": -1269.503647905394
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 6,
          "net_trade_sum_bps": -46.79667344709031
        },
        {
          "utc_monday_ms": 1743379200000,
          "T": 11,
          "net_trade_sum_bps": -1539.055500790842
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 7,
          "net_trade_sum_bps": 1285.6295779345753
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 9,
          "net_trade_sum_bps": -900.3421664698084
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 8,
          "net_trade_sum_bps": 1232.1931349511524
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 16,
          "net_trade_sum_bps": -1373.1637629708707
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 4,
          "net_trade_sum_bps": 4855.968186778033
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 8,
          "net_trade_sum_bps": -577.7284897675645
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 5,
          "net_trade_sum_bps": 85.13261790885444
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 5,
          "net_trade_sum_bps": 303.28459700504965
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 8,
          "net_trade_sum_bps": -509.3841493502063
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 11,
          "net_trade_sum_bps": -46.115431560907
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 9,
          "net_trade_sum_bps": -1123.9994166747813
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 8,
          "net_trade_sum_bps": 143.1349690880407
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": 79.91042167308261
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 3,
          "net_trade_sum_bps": 1820.6965485965845
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 8,
          "net_trade_sum_bps": 1388.212220461015
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 6,
          "net_trade_sum_bps": -389.1604608807887
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 9,
          "net_trade_sum_bps": -276.24551649509976
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 6,
          "net_trade_sum_bps": 1443.1884745276368
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": -150.43881734261402
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 6,
          "net_trade_sum_bps": 674.0116781208691
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 6,
          "net_trade_sum_bps": -749.9536857610984
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 15,
          "net_trade_sum_bps": -1568.235465595336
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 6,
          "net_trade_sum_bps": 771.5587466220239
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 11,
          "net_trade_sum_bps": -826.9498332417718
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 3,
          "net_trade_sum_bps": 21.537970555147737
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 3,
          "net_trade_sum_bps": 1792.4131165131175
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 8,
          "net_trade_sum_bps": -282.7964949781717
        },
        {
          "utc_monday_ms": 1760313600000,
          "T": 6,
          "net_trade_sum_bps": -722.8967739804738
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 4,
          "net_trade_sum_bps": -338.2675966114308
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 7,
          "net_trade_sum_bps": 1086.4614989923953
        },
        {
          "utc_monday_ms": 1762128000000,
          "T": 6,
          "net_trade_sum_bps": -965.2024271367893
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 10,
          "net_trade_sum_bps": -598.9570246899831
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 8,
          "net_trade_sum_bps": -1455.0262451132226
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 7,
          "net_trade_sum_bps": 787.6555788369043
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 10,
          "net_trade_sum_bps": -554.2171984963107
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 5,
          "net_trade_sum_bps": 241.28021739128732
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 11,
          "net_trade_sum_bps": -1163.789379881969
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 11,
          "net_trade_sum_bps": -1039.7802206509036
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
