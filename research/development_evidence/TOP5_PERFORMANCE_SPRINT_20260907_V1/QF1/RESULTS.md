# QF1 frozen DEV economics

Equal nominal trade-bps; terminal includes hypothetical full-cost open marks. Neither account returns nor independent validation. FULL is primary; FIXED is a diagnostic. Parent ledgers reused, Q0 daily marks revalued exactly without replaying its signals.

## DEV2025

| Metric | Q0 | QF1_FIXED | QF1_FULL |
|---|---:|---:|---:|
| closed_T | 86.000000 | 56.000000 | 59.000000 |
| open_T | 0.000000 | 0.000000 | 0.000000 |
| entries_T | 86.000000 | 56.000000 | 59.000000 |
| win_rate | 0.337209 | 0.339286 | 0.355932 |
| PF | 1.240701 | 0.604000 | 0.792150 |
| mean_win_bps | 724.504574 | 407.612006 | 490.077786 |
| mean_loss_bps | -297.096310 | -346.546996 | -341.895524 |
| realized_payoff | 2.438619 | 1.176210 | 1.433414 |
| net_expectancy_bps_per_closed_trade | 47.397011 | -90.671620 | -45.769431 |
| closed_gross_bps | 6325.490202 | -3644.164463 | -1149.569770 |
| closed_net_bps | 4076.142956 | -5077.610728 | -2700.396411 |
| closed_cost2x_net_bps | 1826.795710 | -6511.056993 | -4251.223053 |
| closed_cost_bps | 2249.347246 | 1433.446265 | 1550.826642 |
| closed_fee_bps | 860.000000 | 560.000000 | 590.000000 |
| closed_funding_bps | 934.640000 | 602.450000 | 672.450000 |
| terminal_net_bps_hypothetical | 4076.142956 | -5077.610728 | -2700.396411 |
| terminal_cost2x_net_bps_hypothetical | 1826.795710 | -6511.056993 | -4251.223053 |
| open_net_mark_bps_hypothetical | 0.000000 | 0.000000 | 0.000000 |
| marked_DD_trade_sum_bps | 6801.478761 | 6697.790645 | 6508.918564 |
| grouped_max_loss_trade_sum_bps | 5224.687753 | 4143.866588 | 4143.866588 |
| exposure_symbol_days | 276.666667 | 178.000000 | 201.333333 |
| max_simultaneous_symbols | 6.000000 | 5.000000 | 5.000000 |
| entries_per_30_days | 7.724551 | 5.029940 | 5.299401 |
| max_completed_recovery_days | 85.000000 | 0.000000 | 0.000000 |
| open_underwater_days | 159.000000 | 321.000000 | 321.000000 |

Decisions: {"QF1_FIXED": "REJECT", "QF1_FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "Q0": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": -7475.0599715164135,
        "net_bps": -6776.539367553418,
        "cost2x_net_bps": -6078.018763590422,
        "cost_bps": -698.5206039629958,
        "fee_bps": -270.0,
        "spread_bps": -39.5712227788071,
        "impact_bps": -57.5087715744886,
        "slippage_bps": 0.0,
        "funding_bps": -262.19,
        "frozen_floor_reserve_bps": -69.25060960970013
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 3,
          "delta_bps": {
            "gross_bps": 2494.5946935196507,
            "net_bps": 2377.214316607624,
            "cost2x_net_bps": 2259.833939695597,
            "cost_bps": 117.38037691202682,
            "fee_bps": 30.0,
            "spread_bps": 5.3803769120268194,
            "impact_bps": 6.0,
            "slippage_bps": 0.0,
            "funding_bps": 70.0,
            "frozen_floor_reserve_bps": 6.0
          }
        },
        "C_ABSENT": {
          "T": 30,
          "delta_bps": {
            "gross_bps": -9969.654665036065,
            "net_bps": -9153.753684161042,
            "cost2x_net_bps": -8337.852703286018,
            "cost_bps": -815.9009808750227,
            "fee_bps": -300.0,
            "spread_bps": -44.951599690833916,
            "impact_bps": -63.5087715744886,
            "slippage_bps": 0.0,
            "funding_bps": -332.19,
            "frozen_floor_reserve_bps": -75.25060960970013
          }
        },
        "C_C": {
          "T": 56,
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
        "T": 26,
        "parent_positive_bps": 10856.439568055808,
        "child_signed_terminal_bps": 7744.628123440552,
        "capped_terminal_preserved_bps_hypothetical": 7744.628123440552,
        "capped_terminal_retention_hypothetical": 0.7133672208915058,
        "realized_capped_retention_lower": 0.7133672208915058,
        "realized_capped_retention_upper": 0.7133672208915058,
        "profit_cut_bps": 3111.811444615256,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 3111.811444615256,
        "winner_to_loss_T": 0,
        "winner_removed_T": 7,
        "winner_to_loss_origins": []
      },
      "large_winners": {
        "T": 3,
        "parent_positive_bps": 10154.19307527661,
        "child_signed_terminal_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 0.0,
        "capped_terminal_retention_hypothetical": 0.0,
        "realized_capped_retention_lower": 0.0,
        "realized_capped_retention_upper": 0.0,
        "profit_cut_bps": 10154.19307527661,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 10154.19307527661,
        "winner_to_loss_T": 0,
        "winner_removed_T": 3,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "1f495de3fcde0eb3042053ad0c6b943d1169f657e9cbe2b89027b895fcdc930f",
        "symbol": "LINK-USDT",
        "signal_ts": 1752105600000,
        "entry_month": "2025-07",
        "transition": "ABSENT_C",
        "parent": {
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
        },
        "child": {
          "gross_bps": 2569.8637831765204,
          "net_bps": 2509.4834062644936,
          "cost2x_net_bps": 2449.103029352467,
          "cost_bps": 60.38037691202682,
          "fee_bps": 10.0,
          "spread_bps": 3.3803769120268194,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 45.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 2569.8637831765204,
          "net_bps": 2509.4834062644936,
          "cost2x_net_bps": 2449.103029352467,
          "cost_bps": 60.38037691202682,
          "fee_bps": 10.0,
          "spread_bps": 3.3803769120268194,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 45.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": false,
        "parent_winner": false,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 0,
        "child_hold_ms": 1296000000
      },
      "net_increment_without_largest_positive": -9286.022773817911,
      "largest_positive_share_of_net_increment": -0.3703193134655263,
      "increment_by_symbol": {
        "1000PEPE-USDT": -1406.1854952691683,
        "ETH-USDT": -3497.4726835787556,
        "LINK-USDT": -588.9863771671326,
        "BCH-USDT": -69.94860192272449,
        "BTC-USDT": -854.6987652416864,
        "HYPE-USDT": -642.7642292041246,
        "SOL-USDT": 283.5167848301742
      },
      "increment_by_entry_month": {
        "2025-04": -1388.2893575737849,
        "2025-05": 293.5983437652654,
        "2025-11": 162.07464765786938,
        "2025-09": 297.00311998229773,
        "2025-07": -8592.76340732183,
        "2025-03": 684.6861299248741,
        "2025-12": 222.7339024641744,
        "2025-02": 340.38763824898234,
        "2025-10": 785.9885591254512,
        "2025-06": 277.3612413149229,
        "2025-08": 140.67981485835932
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
      "fixed_path_or_filter_effect": -9969.654665036065,
      "full_occupancy_remainder": 2494.5946935196507,
      "full_total_effect": -7475.0599715164135
    },
    "net_bps": {
      "fixed_path_or_filter_effect": -9153.753684161042,
      "full_occupancy_remainder": 2377.2143166076244,
      "full_total_effect": -6776.539367553418
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": -8337.852703286018,
      "full_occupancy_remainder": 2259.833939695597,
      "full_total_effect": -6078.018763590421
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": -815.9009808750229,
      "full_occupancy_remainder": 117.38037691202703,
      "full_total_effect": -698.5206039629959
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": -300.0,
      "full_occupancy_remainder": 30.0,
      "full_total_effect": -270.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": -44.9515996908339,
      "full_occupancy_remainder": 5.380376912026819,
      "full_total_effect": -39.57122277880708
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": -63.508771574488605,
      "full_occupancy_remainder": 6.0,
      "full_total_effect": -57.508771574488605
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": -332.18999999999994,
      "full_occupancy_remainder": 70.0,
      "full_total_effect": -262.18999999999994
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -75.25060960970012,
      "full_occupancy_remainder": 6.0,
      "full_total_effect": -69.25060960970012
    }
  },
  "uncertainty": {
    "QF1_FIXED": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 334,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 11.133333333333333,
      "N_effective": null,
      "calendar_start": "2025-01-29",
      "calendar_last_day": "2025-12-28",
      "parent_marked_delta_sum_bps": 4076.14295613087,
      "child_marked_delta_sum_bps": -5077.610728030172,
      "child_minus_parent_marked_delta_sum_bps": -9153.753684161042,
      "child_minus_parent_mean_daily_bps": -27.406448156170782,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -110.84773692836951,
        14.650850155705234
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -37023.14413407542,
        4893.383952005548
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    },
    "QF1_FULL": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 334,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 11.133333333333333,
      "N_effective": null,
      "calendar_start": "2025-01-29",
      "calendar_last_day": "2025-12-28",
      "parent_marked_delta_sum_bps": 4076.14295613087,
      "child_marked_delta_sum_bps": -2700.3964114225473,
      "child_minus_parent_marked_delta_sum_bps": -6776.539367553418,
      "child_minus_parent_mean_daily_bps": -20.289040022615023,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -84.13040289034652,
        13.542899307974315
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -28099.554565375736,
        4523.328368863421
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    }
  },
  "concentration": {
    "Q0": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -59.97106972696808,
          "BCH-USDT": -2904.7462669194206,
          "BTC-USDT": -482.7905631116455,
          "ETH-USDT": 2593.389424183817,
          "HYPE-USDT": 41.67673948633829,
          "LINK-USDT": 4687.290856101852,
          "SOL-USDT": 201.29383611689605
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 2513.443441247362,
          "BCH-USDT": 415.23694160262346,
          "BTC-USDT": 3052.274705397677,
          "ETH-USDT": 6243.935023316846,
          "HYPE-USDT": 1489.0033119875416,
          "LINK-USDT": 5361.3911725214375,
          "SOL-USDT": 1935.348047258928
        },
        "total_positive_trade_profit_bps": 21010.632643332418,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.2971797722282445,
        "winner_T": 29,
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.4832883068135016,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2025-01": 0,
          "2025-02": -1624.8775210607291,
          "2025-03": -3035.4949917963568,
          "2025-04": 1176.3116197960471,
          "2025-05": 480.19725814220817,
          "2025-06": -2194.5531767657353,
          "2025-07": 10400.32268426996,
          "2025-08": -278.7862304112139,
          "2025-09": 88.78433890032234,
          "2025-10": 373.8640646047653,
          "2025-11": -107.75987903700994,
          "2025-12": -1201.8652105113883
        },
        "top_positive_month_share": 0.8307312055095731
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 1,
          "net_trade_sum_bps": -223.38420030218018
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 2,
          "net_trade_sum_bps": -370.4034196995975
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 3,
          "net_trade_sum_bps": -795.0273230893645
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -236.06257796958684
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": -1329.171062266159
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 1,
          "net_trade_sum_bps": -110.2604442427457
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 4,
          "net_trade_sum_bps": -1596.0634852874518
        },
        {
          "utc_monday_ms": 1743379200000,
          "T": 1,
          "net_trade_sum_bps": -311.75265875622694
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 1,
          "net_trade_sum_bps": -252.5625809972043
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 3,
          "net_trade_sum_bps": 1623.9616262627399
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 2,
          "net_trade_sum_bps": 1214.3416588009156
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 3,
          "net_trade_sum_bps": -448.41639925851445
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 6,
          "net_trade_sum_bps": 1210.6843044158595
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 3,
          "net_trade_sum_bps": -939.5170371361103
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 5,
          "net_trade_sum_bps": -440.23003539320365
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 3,
          "net_trade_sum_bps": -986.5287618436221
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 3,
          "net_trade_sum_bps": -1208.0244149221132
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 2,
          "net_trade_sum_bps": -1498.245747903602
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 1,
          "net_trade_sum_bps": 767.0887426831832
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 3,
          "net_trade_sum_bps": 2213.100682081996
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 5,
          "net_trade_sum_bps": 9078.649203065133
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 2,
          "net_trade_sum_bps": -160.2701956567511
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 2,
          "net_trade_sum_bps": -278.7862304112139
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 1,
          "net_trade_sum_bps": -30.74321263229758
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 8,
          "net_trade_sum_bps": 119.52755153261992
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 3,
          "net_trade_sum_bps": 1421.134803603169
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 1,
          "net_trade_sum_bps": -261.2821798729525
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 2,
          "net_trade_sum_bps": -785.9885591254512
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 4,
          "net_trade_sum_bps": -107.75987903700994
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 2,
          "net_trade_sum_bps": 300.7602484395731
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 3,
          "net_trade_sum_bps": -719.1511779508195
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 3,
          "net_trade_sum_bps": -783.4742810001421
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1738411200000,
          "end_exit_ms": 1745150400000,
          "exit_groups": 16,
          "origin_keys": [
            "249dc7688099c74d95a17bb74e690881af688aa4dd30c8d49d616eaa0617986e",
            "dbdb4282848cfa4810fe0ac66502c76d0fedb7bb69a127921a0d5e978ab610c8",
            "822276feefbc820824c4015e40b85ab60ac8c36445fa20b3a041ad127a0ad870",
            "e8fd6c3f14123e754210d67b1284e5efb9e25dac66cbe3417e3e75ef969d8655",
            "c7597e3863bdab26e6d69b1294dd475c5f251543be0cbc9ab5299e34b7531782",
            "a1b6c4a282a46cc9edae1b743ddf737516ad72d8801de75c0046c5bc06663f64",
            "a3de1b516e7a12fe793d77f5e49e6bdf5d030de37353fee3ebec6a4153e39f22",
            "f93b1f48ef6cae401141504125815521481d1bb17a4e014ba2cde6c1f2dae5b4",
            "ea874f892905672f612a727e909246741fed2d4f7409e55d48fc5b9b78060e8c",
            "40c1d47f7a644dac48977432d5027fe3bc497b0fcac4b65cf33d8cf651574a71",
            "ff6d66f3e19b24dc63af15001aa1309a07758135f2625e73c2945d9896eec854",
            "603644ad06f44008be3e19b3dbd099ab97a4883900613ffe55476fada6973501",
            "82455889cedc097547034d57457625bd8792b52d847f4c98a5a3d00967bc789b",
            "1bc83e5bf9ac17526236b54008535d95a1740869baad7cf947a52d68a62b738b",
            "78c6931fa7569cf2201a020a9716d531c3c21abf15836182e561de46958d2d10",
            "eb18e24c0ff9629a6d1ffe8d0b803b5e7c7a1b09eb568b2e5190379068258e5d"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1745539200000,
          "end_exit_ms": 1746057600000,
          "exit_groups": 4,
          "origin_keys": [
            "841a3a4fcc7136e6b96f161addd11857072f3a033c48a524ebdfd5d328fbeab3",
            "e77ffd8707ff3070d07455fdb4986cb74ec121b623d5ba0c85fe25c1ee097564",
            "44e908428ac11d7933f5f300b7003ef5c4ab18cce09033f0dd99c2ff54e05683",
            "03e3d1a8ef359c4e66f181ef970ca48efd0e1de67bbfcd19db7ea2b82f3792ac",
            "74c6bb14650f6896c472c4f51f3667404782e03888e0adc6f0b6d86472d2f0e8"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1746403200000,
          "end_exit_ms": 1746417600000,
          "exit_groups": 2,
          "origin_keys": [
            "c8699e4a2b890d1c27535e035527d38deeeaa01170d16dfcf7b1bee4cbdbd184",
            "4ab15f7fe9c0148ee048da1f52078dd6283e27885190ed8ee6d96e7a702e6712"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1746489600000,
          "end_exit_ms": 1747094400000,
          "exit_groups": 2,
          "origin_keys": [
            "9bf6d3c96c4258448c222acccd4ae6757cc978d81119a6255dc1a2321414003b",
            "196087d2e72a9e200b7d7638147216a764b193282ba360b24cfa3e9c0f85e54d",
            "2305ac645c1a80a5f2dd3ce1be4b8d30f0afa45ba52ce4f2a8d7ae6217d5f84c",
            "80b89944ea80be64786bc90af7a2accefce3ed8f792ce57571adfa26e39bef7a",
            "bd1cb00492f907807190c0d939e3152ef7babfe7a02f3bd8080f12540b7d35cf"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1747281600000,
          "end_exit_ms": 1748318400000,
          "exit_groups": 4,
          "origin_keys": [
            "a342bac885bc7b03cf8c6b2f80d97f754e1e8cbed89579d111e07f325b9e3821",
            "fc082145c8553e4baa5bf1d25ee1dd722b5504064800c819248b78efdd6239ab",
            "072110df953c36fcd811f7df4f83c49653b3befc1af9b58dfcadbb6eeaaf255c",
            "4317063a9fc0782aaecb6cdff6d805f5e160586da35aa407926e9ae12e310bef",
            "e8fc762cc281a613aef920e10368096be8db8bb4b4139bbde598d0113d8f7358",
            "14afe126709036c3ce1764769cb60f4e62fe4d03650c897a376cddff06517ed1"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1748390400000,
          "end_exit_ms": 1748390400000,
          "exit_groups": 1,
          "origin_keys": [
            "5044849de818b606086eb3b6f033981544ecbc9ed69f221aa0baeffd90e814ea"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1748448000000,
          "end_exit_ms": 1751414400000,
          "exit_groups": 8,
          "origin_keys": [
            "d5c63c989dce0ae74917b646c077c427447375af6343c8b480df74de14c16f6b",
            "768c09bc9a116d2943088bf9aaecffcb8aa36d4d9d15bdcd576ed55148752715",
            "c1044610e7c31aedbd81d9246de4363f6f0329662e14fda608cb1afdf0ad3ed2",
            "61e5640a1a32fd7bfa95db3bbc4a2c85c407216cd10383c2997f9498b6ab8eaf",
            "bdc81c82ba863da9be097212469b16fc6b26bfbfad675a92131181a7ecccd9a7",
            "68ebff7ae25c87278983395f74c7f4812856a994943af5580f5faeb42a82a305",
            "83c72826eaccff4b55491772da3131b3d13d42103997c568e1f8619fdd33a599",
            "8ceeb28bb7393e0d0a062a7dc02045ad7d5aef8b022d3d94d804ba14f68bf33d",
            "e873632fd27f97f07532eea12457ebbe53c8524a8949cb9e9b1e09e55c951d23",
            "aba23a6d6b67d2d78fe19321a24679f104202f45f3903303096efd510f76247a",
            "5713e1e141667cc851a73d09e6d0f442e7c0e4b36620569b4797c4e4a584b61d"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1752364800000,
          "end_exit_ms": 1752451200000,
          "exit_groups": 2,
          "origin_keys": [
            "fb5a0b45e69581dcebc3e7e5c0b5f850f380114259392f8846ddd6fcf3e1c95d",
            "638490ca5c785454a604d903468d34b7b81f99861f8844b32c52ee9458c3400d",
            "7c640e876cb0c2cfd14e1d56a32cdb05922eeea2890628a2fa463e80bb4d87d2"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1752552000000,
          "end_exit_ms": 1752552000000,
          "exit_groups": 1,
          "origin_keys": [
            "1a2c6d7b6f435f7530279efafb1d8027c7583d86b7bdd0b823f6ef6cea5e33d5"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1753228800000,
          "end_exit_ms": 1753401600000,
          "exit_groups": 2,
          "origin_keys": [
            "fd7dece91b8a5dd33ac1b80a75072e36620821fbc910b1f2cb50de2c00300c5e",
            "2f8f3a1a542a1f122d4876051385e48e1c37f6fbbfd8c69ff1fdbb4e145c1886",
            "967c5b329021c5ab12ba9963400216d3626a59ae0899656d9d600f93b0a6d18e",
            "bb9fe36c88f702195a951844f4fbe85353f8f1297f32fbb662caf25be13f7a34",
            "f04afaec4bb234c83ebf2aaab0aeeaf7ca7d37b4070c42318f6ce22ddb1cdff9"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1753833600000,
          "end_exit_ms": 1757289600000,
          "exit_groups": 4,
          "origin_keys": [
            "8a7fd157e3e5ceb2ab51a6ef19610734afc1969d187bc76fda54703343f08b05",
            "b1efea66f3488ec4ada6d661c35d23c2a6766ee03b036b55beb0c1d5cb113b50",
            "74ad333a86f8b3e44be755421917092eb68792a9cf409310d1eb3123ad632c78",
            "f9625fbaa0504977ee31ecdb2e1868cb2c07faf42defb9b38e7592de12846618",
            "3c734f9f5acc2054c8388cf8a585f317c02b02632b9591733ff0967b39659fb3"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1757894400000,
          "end_exit_ms": 1757980800000,
          "exit_groups": 2,
          "origin_keys": [
            "2ff198dd0c25c5e5590d6cda81b1d4f8c8692ebada3e5c852f4c95e98b8966a4",
            "fd5c2ee30f0aae162ac8b636378fc24e6f3908296144a8f7b2e522f222459a6f",
            "675967258c024bb0423e6982392420b1e7f68d412cf9ada098280b566a4ef9a0",
            "924fb3945e23e11bef35323a4cf613c0b7a62c69420ff71e9ab20327a8028ea6"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1758297600000,
          "end_exit_ms": 1759708800000,
          "exit_groups": 3,
          "origin_keys": [
            "49e065489f512c843f78baa41957638ac432be827e5d7af1aa3123e0d74f0e6d",
            "8e89523ac96eb6c6ea57310140629fa1341aaaa33e364c04fb65c692ec4a3e0b",
            "0b72feee35c41b3baecc5209df37e2d1cff696a1f24e447d7b9ab01e0aa7f590",
            "c6d83a4d5959bfa1d487b16795a858fe26d92ff251b6562729ed4dea997722d2",
            "e39980fc09efe451975d0437dad587030ebdefac8e4153947950d5990c3e877d"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1759968000000,
          "end_exit_ms": 1759968000000,
          "exit_groups": 1,
          "origin_keys": [
            "275b8d10f5619adbb4bd21911f994a80f7a32a9aeaa833f736017c795cc74b36",
            "e650a86ec5749fccdb20aff8f1ddd1c167f47e2c90692765e4ffffcafc26704a"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1761033600000,
          "end_exit_ms": 1764360000000,
          "exit_groups": 3,
          "origin_keys": [
            "2509e1b6768f8f48184edc1da7e9cdf1a275ec9e83ad0d4d989a1827666dfef3",
            "2aca058f2b8c5e31f0516bc035f9f4e4ec2d81bd3b916bd0f210b70b5bb6739b",
            "810dad84e729664e69c01220bc6e12b1b5a773db8e72c2b014e704e3c1024f37",
            "68fd380862c80663c0fffd0ad0528b9a24af906067165b640a9f2f70d908203f"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1764374400000,
          "end_exit_ms": 1764374400000,
          "exit_groups": 1,
          "origin_keys": [
            "0767fe760b55a3073627d638ab2311f38316935b1c9fb8beaaad669ab7912650",
            "1da29520db300744f57b688c2fb2fa870c698da2af636a2939f07a29ee88dcd1"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1764460800000,
          "end_exit_ms": 1764460800000,
          "exit_groups": 1,
          "origin_keys": [
            "f2e8316b8095252fbb16ec578a5f3816d213f0451003cf417c41fb1a06fb07d4"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1764547200000,
          "end_exit_ms": 1764547200000,
          "exit_groups": 1,
          "origin_keys": [
            "6985570ab664ee0f6e19fbf5838d37b038abd7d1296c6078d33f8f22e1f27858",
            "d5d70e85570e80f2d66e772b6ebb78c8d6a408756ff2fe1507a02b0e5cf5add8"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1765425600000,
          "end_exit_ms": 1766620800000,
          "exit_groups": 6,
          "origin_keys": [
            "98ee625bc086f1b8128597a6778a9aa87e6a7ec1a0d2bdab99db02ecc6e39d9c",
            "779a6d94f45aa1f779cb3a7cc5cc5ec1c17391d9e57e042ee5b4e03836dca8d1",
            "f9db1a2281e29093ed209cebb783caf9a39df0a65711f09f43115fed4d07c437",
            "da3b7e455e76d0345b913f91b12cc05c3aaf9aba5efef3fe77c9b94c1476fcf8",
            "1bd5174052aab87a2170b9f824574ed45f09490312bc51a6e3ab5b809664f172",
            "fe8bbd6c9ec4bd2e558173e1bbbfa6c9166730e91e03e91f7a1ba021794076f9"
          ]
        }
      ]
    },
    "QF1_FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -1466.156564996136,
          "BCH-USDT": -2974.6948688421453,
          "BTC-USDT": -1375.0113097688636,
          "ETH-USDT": -734.2921883225378,
          "HYPE-USDT": -601.0874897177864,
          "LINK-USDT": 1588.8210726702266,
          "SOL-USDT": 484.8106209470701
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 148.99265968491892,
          "BCH-USDT": 177.76625243528417,
          "BTC-USDT": 1776.201710792954,
          "ETH-USDT": 1721.6422350085454,
          "HYPE-USDT": 657.8242938275308,
          "LINK-USDT": 2093.941667115574,
          "SOL-USDT": 1168.2593045757449
        },
        "total_positive_trade_profit_bps": 7744.628123440552,
        "top_one_symbol_by_positive_trade_profit": "LINK-USDT",
        "top_one_symbol_profit_share": 0.27037342965220906,
        "winner_T": 19,
        "top_decile_winner_T": 2,
        "top_decile_winners_share": 0.29260226996366745,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2025-01": 0,
          "2025-02": -1284.4898828117466,
          "2025-03": -2350.808861871483,
          "2025-04": 848.1767063209072,
          "2025-05": -323.8808236067034,
          "2025-06": -1917.1919354508125,
          "2025-07": -701.9241293163628,
          "2025-08": -138.1064155528546,
          "2025-09": 385.7874588826201,
          "2025-10": 1159.8526237302165,
          "2025-11": 54.314768620859425,
          "2025-12": -809.3402369748125
        },
        "top_positive_month_share": 0.473770545602857
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1739145600000,
          "T": 1,
          "net_trade_sum_bps": -276.72827202995796
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 2,
          "net_trade_sum_bps": -771.699032812202
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -236.06257796958684
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": -1329.171062266159
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 3,
          "net_trade_sum_bps": -1021.6377996053235
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 1,
          "net_trade_sum_bps": -252.5625809972043
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 2,
          "net_trade_sum_bps": 984.074054031373
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 1,
          "net_trade_sum_bps": 116.66523328673853
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 2,
          "net_trade_sum_bps": -600.6521599971726
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 4,
          "net_trade_sum_bps": 1665.9352560360903
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 2,
          "net_trade_sum_bps": -1117.9136062266557
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 4,
          "net_trade_sum_bps": -271.2503134189653
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 2,
          "net_trade_sum_bps": -709.1675205286992
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 3,
          "net_trade_sum_bps": -1208.0244149221132
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 2,
          "net_trade_sum_bps": -1498.245747903602
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 2,
          "net_trade_sum_bps": -151.350099480447
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 1,
          "net_trade_sum_bps": 1107.9419137244374
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 2,
          "net_trade_sum_bps": -160.2701956567511
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 1,
          "net_trade_sum_bps": -138.1064155528546
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 1,
          "net_trade_sum_bps": -30.74321263229758
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 6,
          "net_trade_sum_bps": 416.5306715149177
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 3,
          "net_trade_sum_bps": 1421.134803603169
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 1,
          "net_trade_sum_bps": -261.2821798729525
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 2,
          "net_trade_sum_bps": 54.314768620859425
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 2,
          "net_trade_sum_bps": 300.7602484395731
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 2,
          "net_trade_sum_bps": -551.6290907062047
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 1,
          "net_trade_sum_bps": -558.4713947081809
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1739376000000,
          "end_exit_ms": 1745539200000,
          "exit_groups": 11,
          "origin_keys": [
            "822276feefbc820824c4015e40b85ab60ac8c36445fa20b3a041ad127a0ad870",
            "c7597e3863bdab26e6d69b1294dd475c5f251543be0cbc9ab5299e34b7531782",
            "a1b6c4a282a46cc9edae1b743ddf737516ad72d8801de75c0046c5bc06663f64",
            "a3de1b516e7a12fe793d77f5e49e6bdf5d030de37353fee3ebec6a4153e39f22",
            "f93b1f48ef6cae401141504125815521481d1bb17a4e014ba2cde6c1f2dae5b4",
            "ea874f892905672f612a727e909246741fed2d4f7409e55d48fc5b9b78060e8c",
            "ff6d66f3e19b24dc63af15001aa1309a07758135f2625e73c2945d9896eec854",
            "603644ad06f44008be3e19b3dbd099ab97a4883900613ffe55476fada6973501",
            "1bc83e5bf9ac17526236b54008535d95a1740869baad7cf947a52d68a62b738b",
            "eb18e24c0ff9629a6d1ffe8d0b803b5e7c7a1b09eb568b2e5190379068258e5d",
            "e77ffd8707ff3070d07455fdb4986cb74ec121b623d5ba0c85fe25c1ee097564"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1745712000000,
          "end_exit_ms": 1745884800000,
          "exit_groups": 2,
          "origin_keys": [
            "44e908428ac11d7933f5f300b7003ef5c4ab18cce09033f0dd99c2ff54e05683",
            "03e3d1a8ef359c4e66f181ef970ca48efd0e1de67bbfcd19db7ea2b82f3792ac"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1746403200000,
          "end_exit_ms": 1746417600000,
          "exit_groups": 2,
          "origin_keys": [
            "c8699e4a2b890d1c27535e035527d38deeeaa01170d16dfcf7b1bee4cbdbd184",
            "4ab15f7fe9c0148ee048da1f52078dd6283e27885190ed8ee6d96e7a702e6712"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1747094400000,
          "end_exit_ms": 1747094400000,
          "exit_groups": 1,
          "origin_keys": [
            "196087d2e72a9e200b7d7638147216a764b193282ba360b24cfa3e9c0f85e54d",
            "2305ac645c1a80a5f2dd3ce1be4b8d30f0afa45ba52ce4f2a8d7ae6217d5f84c",
            "80b89944ea80be64786bc90af7a2accefce3ed8f792ce57571adfa26e39bef7a",
            "bd1cb00492f907807190c0d939e3152ef7babfe7a02f3bd8080f12540b7d35cf"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1748016000000,
          "end_exit_ms": 1748318400000,
          "exit_groups": 3,
          "origin_keys": [
            "072110df953c36fcd811f7df4f83c49653b3befc1af9b58dfcadbb6eeaaf255c",
            "e8fc762cc281a613aef920e10368096be8db8bb4b4139bbde598d0113d8f7358",
            "14afe126709036c3ce1764769cb60f4e62fe4d03650c897a376cddff06517ed1"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1748390400000,
          "end_exit_ms": 1748390400000,
          "exit_groups": 1,
          "origin_keys": [
            "5044849de818b606086eb3b6f033981544ecbc9ed69f221aa0baeffd90e814ea"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1748448000000,
          "end_exit_ms": 1751414400000,
          "exit_groups": 6,
          "origin_keys": [
            "d5c63c989dce0ae74917b646c077c427447375af6343c8b480df74de14c16f6b",
            "c1044610e7c31aedbd81d9246de4363f6f0329662e14fda608cb1afdf0ad3ed2",
            "61e5640a1a32fd7bfa95db3bbc4a2c85c407216cd10383c2997f9498b6ab8eaf",
            "bdc81c82ba863da9be097212469b16fc6b26bfbfad675a92131181a7ecccd9a7",
            "83c72826eaccff4b55491772da3131b3d13d42103997c568e1f8619fdd33a599",
            "8ceeb28bb7393e0d0a062a7dc02045ad7d5aef8b022d3d94d804ba14f68bf33d",
            "e873632fd27f97f07532eea12457ebbe53c8524a8949cb9e9b1e09e55c951d23",
            "aba23a6d6b67d2d78fe19321a24679f104202f45f3903303096efd510f76247a",
            "5713e1e141667cc851a73d09e6d0f442e7c0e4b36620569b4797c4e4a584b61d"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1752451200000,
          "end_exit_ms": 1752451200000,
          "exit_groups": 1,
          "origin_keys": [
            "638490ca5c785454a604d903468d34b7b81f99861f8844b32c52ee9458c3400d"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1752552000000,
          "end_exit_ms": 1752552000000,
          "exit_groups": 1,
          "origin_keys": [
            "1a2c6d7b6f435f7530279efafb1d8027c7583d86b7bdd0b823f6ef6cea5e33d5"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1753401600000,
          "end_exit_ms": 1753401600000,
          "exit_groups": 1,
          "origin_keys": [
            "2f8f3a1a542a1f122d4876051385e48e1c37f6fbbfd8c69ff1fdbb4e145c1886"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1753833600000,
          "end_exit_ms": 1757289600000,
          "exit_groups": 3,
          "origin_keys": [
            "8a7fd157e3e5ceb2ab51a6ef19610734afc1969d187bc76fda54703343f08b05",
            "b1efea66f3488ec4ada6d661c35d23c2a6766ee03b036b55beb0c1d5cb113b50",
            "74ad333a86f8b3e44be755421917092eb68792a9cf409310d1eb3123ad632c78",
            "3c734f9f5acc2054c8388cf8a585f317c02b02632b9591733ff0967b39659fb3"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1757894400000,
          "end_exit_ms": 1757980800000,
          "exit_groups": 2,
          "origin_keys": [
            "2ff198dd0c25c5e5590d6cda81b1d4f8c8692ebada3e5c852f4c95e98b8966a4",
            "fd5c2ee30f0aae162ac8b636378fc24e6f3908296144a8f7b2e522f222459a6f",
            "675967258c024bb0423e6982392420b1e7f68d412cf9ada098280b566a4ef9a0",
            "924fb3945e23e11bef35323a4cf613c0b7a62c69420ff71e9ab20327a8028ea6"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1758297600000,
          "end_exit_ms": 1759708800000,
          "exit_groups": 3,
          "origin_keys": [
            "49e065489f512c843f78baa41957638ac432be827e5d7af1aa3123e0d74f0e6d",
            "0b72feee35c41b3baecc5209df37e2d1cff696a1f24e447d7b9ab01e0aa7f590",
            "e39980fc09efe451975d0437dad587030ebdefac8e4153947950d5990c3e877d"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1759968000000,
          "end_exit_ms": 1759968000000,
          "exit_groups": 1,
          "origin_keys": [
            "275b8d10f5619adbb4bd21911f994a80f7a32a9aeaa833f736017c795cc74b36",
            "e650a86ec5749fccdb20aff8f1ddd1c167f47e2c90692765e4ffffcafc26704a"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1761033600000,
          "end_exit_ms": 1761033600000,
          "exit_groups": 1,
          "origin_keys": [
            "2509e1b6768f8f48184edc1da7e9cdf1a275ec9e83ad0d4d989a1827666dfef3"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1764374400000,
          "end_exit_ms": 1764374400000,
          "exit_groups": 1,
          "origin_keys": [
            "0767fe760b55a3073627d638ab2311f38316935b1c9fb8beaaad669ab7912650"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1764460800000,
          "end_exit_ms": 1764460800000,
          "exit_groups": 1,
          "origin_keys": [
            "f2e8316b8095252fbb16ec578a5f3816d213f0451003cf417c41fb1a06fb07d4"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1764547200000,
          "end_exit_ms": 1764547200000,
          "exit_groups": 1,
          "origin_keys": [
            "6985570ab664ee0f6e19fbf5838d37b038abd7d1296c6078d33f8f22e1f27858",
            "d5d70e85570e80f2d66e772b6ebb78c8d6a408756ff2fe1507a02b0e5cf5add8"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1765425600000,
          "end_exit_ms": 1766361600000,
          "exit_groups": 3,
          "origin_keys": [
            "98ee625bc086f1b8128597a6778a9aa87e6a7ec1a0d2bdab99db02ecc6e39d9c",
            "779a6d94f45aa1f779cb3a7cc5cc5ec1c17391d9e57e042ee5b4e03836dca8d1",
            "da3b7e455e76d0345b913f91b12cc05c3aaf9aba5efef3fe77c9b94c1476fcf8"
          ]
        }
      ]
    },
    "QF1_FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -1466.156564996136,
          "BCH-USDT": -2974.6948688421453,
          "BTC-USDT": -1337.4893283533315,
          "ETH-USDT": -904.0832593949393,
          "HYPE-USDT": -601.0874897177864,
          "LINK-USDT": 4098.304478934721,
          "SOL-USDT": 484.8106209470701
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 148.99265968491892,
          "BCH-USDT": 177.76625243528417,
          "BTC-USDT": 1813.7236922084855,
          "ETH-USDT": 1721.6422350085454,
          "HYPE-USDT": 657.8242938275308,
          "LINK-USDT": 4603.425073380068,
          "SOL-USDT": 1168.2593045757449
        },
        "total_positive_trade_profit_bps": 10291.633511120577,
        "top_one_symbol_by_positive_trade_profit": "LINK-USDT",
        "top_one_symbol_profit_share": 0.4472978044161657,
        "winner_T": 21,
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.46402538236980817,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2025-01": 0,
          "2025-02": -1284.4898828117466,
          "2025-03": -2350.808861871483,
          "2025-04": 848.1767063209072,
          "2025-05": -286.3588421911717,
          "2025-06": -1917.1919354508125,
          "2025-07": 1807.559276948131,
          "2025-08": -138.1064155528546,
          "2025-09": 385.7874588826201,
          "2025-10": 1159.8526237302165,
          "2025-11": 54.314768620859425,
          "2025-12": -979.131308047214
        },
        "top_positive_month_share": 0.42473933075529424
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1739145600000,
          "T": 1,
          "net_trade_sum_bps": -276.72827202995796
        },
        {
          "utc_monday_ms": 1739750400000,
          "T": 2,
          "net_trade_sum_bps": -771.699032812202
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -236.06257796958684
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": -1329.171062266159
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 3,
          "net_trade_sum_bps": -1021.6377996053235
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 1,
          "net_trade_sum_bps": -252.5625809972043
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 2,
          "net_trade_sum_bps": 984.074054031373
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 2,
          "net_trade_sum_bps": 154.18721470227032
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 2,
          "net_trade_sum_bps": -600.6521599971726
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 4,
          "net_trade_sum_bps": 1665.9352560360903
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 2,
          "net_trade_sum_bps": -1117.9136062266557
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 4,
          "net_trade_sum_bps": -271.2503134189653
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 2,
          "net_trade_sum_bps": -709.1675205286992
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 3,
          "net_trade_sum_bps": -1208.0244149221132
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 2,
          "net_trade_sum_bps": -1498.245747903602
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 2,
          "net_trade_sum_bps": -151.350099480447
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 2,
          "net_trade_sum_bps": 3617.425319988931
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 2,
          "net_trade_sum_bps": -160.2701956567511
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 1,
          "net_trade_sum_bps": -138.1064155528546
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 1,
          "net_trade_sum_bps": -30.74321263229758
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 6,
          "net_trade_sum_bps": 416.5306715149177
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 3,
          "net_trade_sum_bps": 1421.134803603169
        },
        {
          "utc_monday_ms": 1760918400000,
          "T": 1,
          "net_trade_sum_bps": -261.2821798729525
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 2,
          "net_trade_sum_bps": 54.314768620859425
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 2,
          "net_trade_sum_bps": 300.7602484395731
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 2,
          "net_trade_sum_bps": -551.6290907062047
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 2,
          "net_trade_sum_bps": -728.2624657805825
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1739376000000,
          "end_exit_ms": 1745539200000,
          "exit_groups": 11,
          "origin_keys": [
            "822276feefbc820824c4015e40b85ab60ac8c36445fa20b3a041ad127a0ad870",
            "c7597e3863bdab26e6d69b1294dd475c5f251543be0cbc9ab5299e34b7531782",
            "a1b6c4a282a46cc9edae1b743ddf737516ad72d8801de75c0046c5bc06663f64",
            "a3de1b516e7a12fe793d77f5e49e6bdf5d030de37353fee3ebec6a4153e39f22",
            "f93b1f48ef6cae401141504125815521481d1bb17a4e014ba2cde6c1f2dae5b4",
            "ea874f892905672f612a727e909246741fed2d4f7409e55d48fc5b9b78060e8c",
            "ff6d66f3e19b24dc63af15001aa1309a07758135f2625e73c2945d9896eec854",
            "603644ad06f44008be3e19b3dbd099ab97a4883900613ffe55476fada6973501",
            "1bc83e5bf9ac17526236b54008535d95a1740869baad7cf947a52d68a62b738b",
            "eb18e24c0ff9629a6d1ffe8d0b803b5e7c7a1b09eb568b2e5190379068258e5d",
            "e77ffd8707ff3070d07455fdb4986cb74ec121b623d5ba0c85fe25c1ee097564"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1745712000000,
          "end_exit_ms": 1746057600000,
          "exit_groups": 3,
          "origin_keys": [
            "44e908428ac11d7933f5f300b7003ef5c4ab18cce09033f0dd99c2ff54e05683",
            "03e3d1a8ef359c4e66f181ef970ca48efd0e1de67bbfcd19db7ea2b82f3792ac",
            "5ea7389d90f314e4c74c67bdaeb86904385e53552246bdf9efea6a761b9a08a2"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1746403200000,
          "end_exit_ms": 1746417600000,
          "exit_groups": 2,
          "origin_keys": [
            "c8699e4a2b890d1c27535e035527d38deeeaa01170d16dfcf7b1bee4cbdbd184",
            "4ab15f7fe9c0148ee048da1f52078dd6283e27885190ed8ee6d96e7a702e6712"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1747094400000,
          "end_exit_ms": 1747094400000,
          "exit_groups": 1,
          "origin_keys": [
            "196087d2e72a9e200b7d7638147216a764b193282ba360b24cfa3e9c0f85e54d",
            "2305ac645c1a80a5f2dd3ce1be4b8d30f0afa45ba52ce4f2a8d7ae6217d5f84c",
            "80b89944ea80be64786bc90af7a2accefce3ed8f792ce57571adfa26e39bef7a",
            "bd1cb00492f907807190c0d939e3152ef7babfe7a02f3bd8080f12540b7d35cf"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1748016000000,
          "end_exit_ms": 1748318400000,
          "exit_groups": 3,
          "origin_keys": [
            "072110df953c36fcd811f7df4f83c49653b3befc1af9b58dfcadbb6eeaaf255c",
            "e8fc762cc281a613aef920e10368096be8db8bb4b4139bbde598d0113d8f7358",
            "14afe126709036c3ce1764769cb60f4e62fe4d03650c897a376cddff06517ed1"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1748390400000,
          "end_exit_ms": 1748390400000,
          "exit_groups": 1,
          "origin_keys": [
            "5044849de818b606086eb3b6f033981544ecbc9ed69f221aa0baeffd90e814ea"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1748448000000,
          "end_exit_ms": 1751414400000,
          "exit_groups": 6,
          "origin_keys": [
            "d5c63c989dce0ae74917b646c077c427447375af6343c8b480df74de14c16f6b",
            "c1044610e7c31aedbd81d9246de4363f6f0329662e14fda608cb1afdf0ad3ed2",
            "61e5640a1a32fd7bfa95db3bbc4a2c85c407216cd10383c2997f9498b6ab8eaf",
            "bdc81c82ba863da9be097212469b16fc6b26bfbfad675a92131181a7ecccd9a7",
            "83c72826eaccff4b55491772da3131b3d13d42103997c568e1f8619fdd33a599",
            "8ceeb28bb7393e0d0a062a7dc02045ad7d5aef8b022d3d94d804ba14f68bf33d",
            "e873632fd27f97f07532eea12457ebbe53c8524a8949cb9e9b1e09e55c951d23",
            "aba23a6d6b67d2d78fe19321a24679f104202f45f3903303096efd510f76247a",
            "5713e1e141667cc851a73d09e6d0f442e7c0e4b36620569b4797c4e4a584b61d"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1752451200000,
          "end_exit_ms": 1752451200000,
          "exit_groups": 1,
          "origin_keys": [
            "638490ca5c785454a604d903468d34b7b81f99861f8844b32c52ee9458c3400d"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1752552000000,
          "end_exit_ms": 1752552000000,
          "exit_groups": 1,
          "origin_keys": [
            "1a2c6d7b6f435f7530279efafb1d8027c7583d86b7bdd0b823f6ef6cea5e33d5"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1753401600000,
          "end_exit_ms": 1753401600000,
          "exit_groups": 1,
          "origin_keys": [
            "1f495de3fcde0eb3042053ad0c6b943d1169f657e9cbe2b89027b895fcdc930f",
            "2f8f3a1a542a1f122d4876051385e48e1c37f6fbbfd8c69ff1fdbb4e145c1886"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1753833600000,
          "end_exit_ms": 1757289600000,
          "exit_groups": 3,
          "origin_keys": [
            "8a7fd157e3e5ceb2ab51a6ef19610734afc1969d187bc76fda54703343f08b05",
            "b1efea66f3488ec4ada6d661c35d23c2a6766ee03b036b55beb0c1d5cb113b50",
            "74ad333a86f8b3e44be755421917092eb68792a9cf409310d1eb3123ad632c78",
            "3c734f9f5acc2054c8388cf8a585f317c02b02632b9591733ff0967b39659fb3"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1757894400000,
          "end_exit_ms": 1757980800000,
          "exit_groups": 2,
          "origin_keys": [
            "2ff198dd0c25c5e5590d6cda81b1d4f8c8692ebada3e5c852f4c95e98b8966a4",
            "fd5c2ee30f0aae162ac8b636378fc24e6f3908296144a8f7b2e522f222459a6f",
            "675967258c024bb0423e6982392420b1e7f68d412cf9ada098280b566a4ef9a0",
            "924fb3945e23e11bef35323a4cf613c0b7a62c69420ff71e9ab20327a8028ea6"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1758297600000,
          "end_exit_ms": 1759708800000,
          "exit_groups": 3,
          "origin_keys": [
            "49e065489f512c843f78baa41957638ac432be827e5d7af1aa3123e0d74f0e6d",
            "0b72feee35c41b3baecc5209df37e2d1cff696a1f24e447d7b9ab01e0aa7f590",
            "e39980fc09efe451975d0437dad587030ebdefac8e4153947950d5990c3e877d"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1759968000000,
          "end_exit_ms": 1759968000000,
          "exit_groups": 1,
          "origin_keys": [
            "275b8d10f5619adbb4bd21911f994a80f7a32a9aeaa833f736017c795cc74b36",
            "e650a86ec5749fccdb20aff8f1ddd1c167f47e2c90692765e4ffffcafc26704a"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1761033600000,
          "end_exit_ms": 1761033600000,
          "exit_groups": 1,
          "origin_keys": [
            "2509e1b6768f8f48184edc1da7e9cdf1a275ec9e83ad0d4d989a1827666dfef3"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1764374400000,
          "end_exit_ms": 1764374400000,
          "exit_groups": 1,
          "origin_keys": [
            "0767fe760b55a3073627d638ab2311f38316935b1c9fb8beaaad669ab7912650"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1764460800000,
          "end_exit_ms": 1764460800000,
          "exit_groups": 1,
          "origin_keys": [
            "f2e8316b8095252fbb16ec578a5f3816d213f0451003cf417c41fb1a06fb07d4"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1764547200000,
          "end_exit_ms": 1764547200000,
          "exit_groups": 1,
          "origin_keys": [
            "6985570ab664ee0f6e19fbf5838d37b038abd7d1296c6078d33f8f22e1f27858",
            "d5d70e85570e80f2d66e772b6ebb78c8d6a408756ff2fe1507a02b0e5cf5add8"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1765425600000,
          "end_exit_ms": 1766476800000,
          "exit_groups": 4,
          "origin_keys": [
            "98ee625bc086f1b8128597a6778a9aa87e6a7ec1a0d2bdab99db02ecc6e39d9c",
            "779a6d94f45aa1f779cb3a7cc5cc5ec1c17391d9e57e042ee5b4e03836dca8d1",
            "da3b7e455e76d0345b913f91b12cc05c3aaf9aba5efef3fe77c9b94c1476fcf8",
            "d1f2b21dd607592ed9ed02d9b6616e0d34553c6fd9aa36649b880db9a393f725"
          ]
        }
      ]
    }
  },
  "partial_assets": {
    "full_terminal_increment_positive": false,
    "full_terminal_base_positive": false,
    "full_terminal_cost2_positive": false,
    "preserve_branch_as_development_evidence": true,
    "formal_or_operating_adoption": false
  }
}
```
## SEEN2026

| Metric | Q0 | QF1_FIXED | QF1_FULL |
|---|---:|---:|---:|
| closed_T | 34.000000 | 18.000000 | 22.000000 |
| open_T | 0.000000 | 0.000000 | 0.000000 |
| entries_T | 34.000000 | 18.000000 | 22.000000 |
| win_rate | 0.323529 | 0.333333 | 0.272727 |
| PF | 2.235969 | 2.776628 | 2.225429 |
| mean_win_bps | 1203.012749 | 1507.943080 | 1507.943080 |
| mean_loss_bps | -257.317433 | -271.542156 | -254.098732 |
| realized_payoff | 4.675209 | 5.553256 | 5.934477 |
| net_expectancy_bps_per_closed_trade | 215.142332 | 321.619589 | 226.458126 |
| closed_gross_bps | 8181.299662 | 6243.827754 | 5528.753908 |
| closed_net_bps | 7314.839288 | 5789.152608 | 4982.078763 |
| closed_cost2x_net_bps | 6448.378914 | 5334.477462 | 4435.403617 |
| closed_cost_bps | 866.460374 | 454.675146 | 546.675146 |
| closed_fee_bps | 340.000000 | 180.000000 | 220.000000 |
| closed_funding_bps | 348.540000 | 186.020000 | 223.020000 |
| terminal_net_bps_hypothetical | 7314.839288 | 5789.152608 | 4982.078763 |
| terminal_cost2x_net_bps_hypothetical | 6448.378914 | 5334.477462 | 4435.403617 |
| open_net_mark_bps_hypothetical | 0.000000 | 0.000000 | 0.000000 |
| marked_DD_trade_sum_bps | 5619.081051 | 3211.846842 | 4018.920688 |
| grouped_max_loss_trade_sum_bps | 2779.711014 | 2134.756307 | 3978.920688 |
| exposure_symbol_days | 97.000000 | 51.500000 | 64.000000 |
| max_simultaneous_symbols | 5.000000 | 4.000000 | 4.000000 |
| entries_per_30_days | 8.500000 | 4.500000 | 5.500000 |
| max_completed_recovery_days | 102.000000 | 103.000000 | 104.000000 |
| open_underwater_days | 8.000000 | 8.000000 | 8.000000 |

Decisions: {"QF1_FIXED": "REJECT", "QF1_FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "Q0": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": -2652.545754089794,
        "net_bps": -2332.7605255439626,
        "cost2x_net_bps": -2012.9752969981314,
        "cost_bps": -319.78522854583167,
        "fee_bps": -120.0,
        "spread_bps": -25.134881269660347,
        "impact_bps": -26.10526294469316,
        "slippage_bps": 0.0,
        "funding_bps": -125.52000000000001,
        "frozen_floor_reserve_bps": -23.025084331478162
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 4,
          "delta_bps": {
            "gross_bps": -715.0738455002303,
            "net_bps": -807.0738455002303,
            "cost2x_net_bps": -899.0738455002304,
            "cost_bps": 92.0,
            "fee_bps": 40.0,
            "spread_bps": 4.0,
            "impact_bps": 8.0,
            "slippage_bps": 0.0,
            "funding_bps": 37.0,
            "frozen_floor_reserve_bps": 3.0
          }
        },
        "C_ABSENT": {
          "T": 16,
          "delta_bps": {
            "gross_bps": -1937.471908589564,
            "net_bps": -1525.6866800437324,
            "cost2x_net_bps": -1113.901451497901,
            "cost_bps": -411.78522854583167,
            "fee_bps": -160.0,
            "spread_bps": -29.134881269660347,
            "impact_bps": -34.10526294469316,
            "slippage_bps": 0.0,
            "funding_bps": -162.52,
            "frozen_floor_reserve_bps": -26.025084331478162
          }
        },
        "C_C": {
          "T": 18,
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
        "T": 9,
        "parent_positive_bps": 6845.445900970279,
        "child_signed_terminal_bps": 6230.051143895064,
        "capped_terminal_preserved_bps_hypothetical": 6230.051143895064,
        "capped_terminal_retention_hypothetical": 0.9101015819892773,
        "realized_capped_retention_lower": 0.9101015819892773,
        "realized_capped_retention_upper": 0.9101015819892773,
        "profit_cut_bps": 615.3947570752146,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 615.3947570752146,
        "winner_to_loss_T": 0,
        "winner_removed_T": 4,
        "winner_to_loss_origins": []
      },
      "large_winners": {
        "T": 2,
        "parent_positive_bps": 6387.694338045512,
        "child_signed_terminal_bps": 2817.6073362336087,
        "capped_terminal_preserved_bps_hypothetical": 2817.6073362336087,
        "capped_terminal_retention_hypothetical": 0.44109927418595485,
        "realized_capped_retention_lower": 0.44109927418595485,
        "realized_capped_retention_upper": 0.44109927418595485,
        "profit_cut_bps": 3570.087001811904,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 3570.087001811904,
        "winner_to_loss_T": 0,
        "winner_removed_T": 1,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "1978e6145de1a23ed120177583f891cfeff854068ec1aa90d9e1473df533c8c4",
        "symbol": "1000PEPE-USDT",
        "signal_ts": 1780963200000,
        "entry_month": "2026-06",
        "transition": "C_ABSENT",
        "parent": {
          "gross_bps": -472.2220246140718,
          "net_bps": -499.96043412934904,
          "cost2x_net_bps": -527.6988436446262,
          "cost_bps": 27.738409515277223,
          "fee_bps": 10.0,
          "spread_bps": 2.796655200379503,
          "impact_bps": 2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": 12.24,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
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
        },
        "delta": {
          "gross_bps": 472.2220246140718,
          "net_bps": 499.96043412934904,
          "cost2x_net_bps": 527.6988436446262,
          "cost_bps": -27.738409515277223,
          "fee_bps": -10.0,
          "spread_bps": -2.796655200379503,
          "impact_bps": -2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": -12.24,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": false,
        "parent_winner": false,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 172800000,
        "child_hold_ms": 0
      },
      "net_increment_without_largest_positive": -2832.7209596733114,
      "largest_positive_share_of_net_increment": -0.2143213710343312,
      "increment_by_symbol": {
        "1000PEPE-USDT": 587.6928810824382,
        "ETH-USDT": -128.53317247286805,
        "LINK-USDT": 571.3910438197278,
        "BTC-USDT": -427.38444175761697,
        "HYPE-USDT": -3140.3517538182996,
        "SOL-USDT": 90.69382119433865,
        "BCH-USDT": 113.73109640831711
      },
      "increment_by_entry_month": {
        "2026-08": -3646.3699415355513,
        "2026-06": 863.1139191083172,
        "2026-07": -105.6578659071088,
        "2026-05": 556.1533627903801
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
      "fixed_path_or_filter_effect": -1937.471908589565,
      "full_occupancy_remainder": -715.0738455002302,
      "full_total_effect": -2652.545754089795
    },
    "net_bps": {
      "fixed_path_or_filter_effect": -1525.6866800437328,
      "full_occupancy_remainder": -807.0738455002302,
      "full_total_effect": -2332.760525543963
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": -1113.9014514979017,
      "full_occupancy_remainder": -899.0738455002302,
      "full_total_effect": -2012.9752969981319
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": -411.7852285458316,
      "full_occupancy_remainder": 92.0,
      "full_total_effect": -319.7852285458316
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": -160.0,
      "full_occupancy_remainder": 40.0,
      "full_total_effect": -120.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": -29.13488126966034,
      "full_occupancy_remainder": 4.0,
      "full_total_effect": -25.13488126966034
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": -34.10526294469316,
      "full_occupancy_remainder": 8.0,
      "full_total_effect": -26.10526294469316
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": -162.52,
      "full_occupancy_remainder": 37.0,
      "full_total_effect": -125.52000000000001
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -26.025084331478162,
      "full_occupancy_remainder": 3.0,
      "full_total_effect": -23.025084331478162
    }
  },
  "uncertainty": {
    "QF1_FIXED": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 120,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 4.0,
      "N_effective": null,
      "calendar_start": "2026-05-08",
      "calendar_last_day": "2026-09-04",
      "parent_marked_delta_sum_bps": 7314.839288116795,
      "child_marked_delta_sum_bps": 5789.152608073062,
      "child_minus_parent_marked_delta_sum_bps": -1525.6866800437333,
      "child_minus_parent_mean_daily_bps": -12.714055667031111,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -58.23750033069787,
        32.94588992511141
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -6988.500039683744,
        3953.506791013369
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    },
    "QF1_FULL": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 120,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 4.0,
      "N_effective": null,
      "calendar_start": "2026-05-08",
      "calendar_last_day": "2026-09-04",
      "parent_marked_delta_sum_bps": 7314.839288116795,
      "child_marked_delta_sum_bps": 4982.078762572832,
      "child_minus_parent_marked_delta_sum_bps": -2332.7605255439635,
      "child_minus_parent_mean_daily_bps": -19.439671046199695,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -69.19575438472151,
        27.209159124121584
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -8303.49052616658,
        3265.09909489459
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    }
  },
  "concentration": {
    "Q0": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 1419.4829660843816,
          "BCH-USDT": -113.73109640831711,
          "BTC-USDT": 1338.1192454329666,
          "ETH-USDT": 2724.4391401202474,
          "HYPE-USDT": 2710.5121134532965,
          "LINK-USDT": -1185.620292710212,
          "SOL-USDT": 421.63721214443154
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 2935.0290011036914,
          "BCH-USDT": 0.0,
          "BTC-USDT": 2134.5997192929135,
          "ETH-USDT": 3090.561936128391,
          "HYPE-USDT": 3570.087001811904,
          "LINK-USDT": 776.6677234061467,
          "SOL-USDT": 726.194857272745
        },
        "total_positive_trade_profit_bps": 13233.140239015791,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.26978381074554586,
        "winner_T": 11,
        "top_decile_winner_T": 2,
        "top_decile_winners_share": 0.48270434852737526,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": -935.2868690962222,
          "2026-06": -2276.5646001881582,
          "2026-07": -1252.0455144292018,
          "2026-08": 11778.736271830376,
          "2026-09": 0
        },
        "top_positive_month_share": 1.0
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1778457600000,
          "T": 3,
          "net_trade_sum_bps": -785.402882743068
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 1,
          "net_trade_sum_bps": -149.88398635315423
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 2,
          "net_trade_sum_bps": -384.6484438927344
        },
        {
          "utc_monday_ms": 1780876800000,
          "T": 3,
          "net_trade_sum_bps": -1459.7757005993599
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 4,
          "net_trade_sum_bps": -341.44663450172516
        },
        {
          "utc_monday_ms": 1782086400000,
          "T": 1,
          "net_trade_sum_bps": -90.69382119433865
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 1,
          "net_trade_sum_bps": -429.7352479936045
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 2,
          "net_trade_sum_bps": -176.12037739556388
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 2,
          "net_trade_sum_bps": 465.5717756489606
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 3,
          "net_trade_sum_bps": -568.1909279156741
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 2,
          "net_trade_sum_bps": -543.57073677332
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 1,
          "net_trade_sum_bps": -148.74953813142525
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 3,
          "net_trade_sum_bps": -603.6006423291792
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 6,
          "net_trade_sum_bps": 12531.086452290981
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778587200000,
          "end_exit_ms": 1781136000000,
          "exit_groups": 7,
          "origin_keys": [
            "c4cf3282179efb7fb426139875146fcadc35eaa73910c5a527140174c53c3f65",
            "d6754eb08aa2efdcbdca0a71a1f64cdbd3ffdd0d573da28b90fd4a028b93783f",
            "51694dbf44269443137e55f6d0930bed96a9a973d316548eefc83aa046896729",
            "fbb58ca3453bbf81df4b4e82debd3cc07875c5666c6841a5cca57fea900705b4",
            "2f92e5c776980667af76c0657717ea176a11148c42eb75199cd794eadd593250",
            "578c32fa7bb629c2cc136354741556c944f16d029a5a671b423715f1fbf3e379",
            "564e1bd0da2b14b7ad470365d10d552756f22ba83acf9b39794a60743395cda2",
            "1978e6145de1a23ed120177583f891cfeff854068ec1aa90d9e1473df533c8c4",
            "9190a651256b0b77e800f2c67116fb3b1701de716ddcf13e266d3344e2f014d5"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1781740800000,
          "end_exit_ms": 1781740800000,
          "exit_groups": 1,
          "origin_keys": [
            "31715d9f91e846da37de1e8f01413cee2d4253495818dbfcfac99cec390c27e6",
            "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1781798400000,
          "end_exit_ms": 1783396800000,
          "exit_groups": 6,
          "origin_keys": [
            "64b673229efe7ebff6a88851395741b66b20cea69751309f0393f4715ae73b19",
            "18a8d76917adc06bc592b54eb4b9211697ff94fae98c588e3e850d704cd4e1d0",
            "efa60e623906f0d7806aa1865503f7fbd5e88e5086c317dbbe48e10143780573",
            "7cf9020701be02c957a508ce6c551b757539204eb16ac730c4d9973e7b4a30f3",
            "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6",
            "e2445ff43ebdd66214ef673c57f11985307e96452e8bbb5646c0b0910c9760fd"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1783900800000,
          "end_exit_ms": 1784851200000,
          "exit_groups": 3,
          "origin_keys": [
            "e31955635438f244d0376a365c0362f67dd0cb5850f49389ef0d3be90cffe84e",
            "cf3d93688918f848d38e6c44f971f7808ca47e5ae32c4a5ef6eb84e353814272",
            "ab2a2b1541e2af29c7ebd20a9a64c6e7348ca43ef05eb7855304fe34d2515a65"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1784908800000,
          "end_exit_ms": 1786492800000,
          "exit_groups": 6,
          "origin_keys": [
            "b005e4d1d431dfabd2c4d12d0205b33f3fa3cfd3a01ef62299888eaf438b4245",
            "fe5abbc5dd9ef292ad6a800292338342013096ae76e0cdda1294205ca0a16330",
            "84b9483292abbf26e56f2460135f9f76d6a9e95821073d80c342cb2d3fc55d3a",
            "d6af7453485b4ffec7745f4b952aa50d376b3e08e1c9dd450f69d87342bef175",
            "e2ee772a775c57ef6f6b059f00d842055e54bba3605202bd51555f9d3260740a",
            "7cde4b543006fb8c9d2138a83226b490da703904eab4e4496115462252268705",
            "de18c3d895e5ac61eb712cc3dd5168f660d9d03f94c65336e237d33f0c5408ef",
            "369bc66780e9c80e600445beeb75b248437a03e18ad94379ada3964623cc56d7"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1787529600000,
          "end_exit_ms": 1788048000000,
          "exit_groups": 3,
          "origin_keys": [
            "0885a5740d9d7680986d09077031be501313f4588115afee33c0cd8b28e816d3",
            "254874089657dee5a2f36bb9bd1cf8c9a786cfe709b1f6df29229eccbe214a45",
            "4999f99153ed39cf58046aea603e500de7337a8f914896b6d167d57ff2ddd00b",
            "811b7a73c0c6e4ff61e0143d6fac907c10babe6954b7451207ae435548e7c8e3",
            "40ebc4356d6f9e0d5c7e7c83ec57b8f7870c55be0ac3b98c4827c6dcc05f5cae",
            "9d1db065e5e0eb36d9c8ce8c640427a2b089c80b83c9473c725c5c99c2a10e4f"
          ]
        }
      ]
    },
    "QF1_FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 2007.1758471668197,
          "BTC-USDT": 1605.6432315608174,
          "ETH-USDT": 2708.0713852621416,
          "HYPE-USDT": -429.8396403650029,
          "LINK-USDT": -614.2292488904841,
          "SOL-USDT": 512.3310333387702
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 2742.411825349513,
          "BTC-USDT": 1984.7767378666595,
          "ETH-USDT": 2817.6073362336087,
          "HYPE-USDT": 0.0,
          "LINK-USDT": 776.6677234061467,
          "SOL-USDT": 726.194857272745
        },
        "total_positive_trade_profit_bps": 9047.658480128674,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.31141840095113066,
        "winner_T": 6,
        "top_decile_winner_T": 1,
        "top_decile_winners_share": 0.31141840095113066,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": -379.13350630584205,
          "2026-06": -1204.0984055334968,
          "2026-07": -1118.5604699356659,
          "2026-08": 8490.944989848067,
          "2026-09": 0
        },
        "top_positive_month_share": 1.0
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1778457600000,
          "T": 1,
          "net_trade_sum_bps": -229.24951995268782
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 1,
          "net_trade_sum_bps": -149.88398635315423
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 1,
          "net_trade_sum_bps": -176.4388846670961
        },
        {
          "utc_monday_ms": 1780876800000,
          "T": 1,
          "net_trade_sum_bps": -568.1771737088236
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 3,
          "net_trade_sum_bps": -459.48234715757724
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 1,
          "net_trade_sum_bps": -88.742632884587
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 2,
          "net_trade_sum_bps": -599.978196686076
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 1,
          "net_trade_sum_bps": -429.8396403650029
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 1,
          "net_trade_sum_bps": -148.74953813142525
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 1,
          "net_trade_sum_bps": -321.30492249958496
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 5,
          "net_trade_sum_bps": 8960.999450479077
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778630400000,
          "end_exit_ms": 1781136000000,
          "exit_groups": 4,
          "origin_keys": [
            "51694dbf44269443137e55f6d0930bed96a9a973d316548eefc83aa046896729",
            "fbb58ca3453bbf81df4b4e82debd3cc07875c5666c6841a5cca57fea900705b4",
            "578c32fa7bb629c2cc136354741556c944f16d029a5a671b423715f1fbf3e379",
            "9190a651256b0b77e800f2c67116fb3b1701de716ddcf13e266d3344e2f014d5"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1781740800000,
          "end_exit_ms": 1781740800000,
          "exit_groups": 1,
          "origin_keys": [
            "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1781798400000,
          "end_exit_ms": 1786464000000,
          "exit_groups": 7,
          "origin_keys": [
            "64b673229efe7ebff6a88851395741b66b20cea69751309f0393f4715ae73b19",
            "18a8d76917adc06bc592b54eb4b9211697ff94fae98c588e3e850d704cd4e1d0",
            "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6",
            "b005e4d1d431dfabd2c4d12d0205b33f3fa3cfd3a01ef62299888eaf438b4245",
            "fe5abbc5dd9ef292ad6a800292338342013096ae76e0cdda1294205ca0a16330",
            "84b9483292abbf26e56f2460135f9f76d6a9e95821073d80c342cb2d3fc55d3a",
            "e2ee772a775c57ef6f6b059f00d842055e54bba3605202bd51555f9d3260740a",
            "7cde4b543006fb8c9d2138a83226b490da703904eab4e4496115462252268705"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1787529600000,
          "end_exit_ms": 1788048000000,
          "exit_groups": 2,
          "origin_keys": [
            "0885a5740d9d7680986d09077031be501313f4588115afee33c0cd8b28e816d3",
            "254874089657dee5a2f36bb9bd1cf8c9a786cfe709b1f6df29229eccbe214a45",
            "4999f99153ed39cf58046aea603e500de7337a8f914896b6d167d57ff2ddd00b",
            "811b7a73c0c6e4ff61e0143d6fac907c10babe6954b7451207ae435548e7c8e3",
            "9d1db065e5e0eb36d9c8ce8c640427a2b089c80b83c9473c725c5c99c2a10e4f"
          ]
        }
      ]
    },
    "QF1_FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 2007.1758471668197,
          "BTC-USDT": 910.7348036753494,
          "ETH-USDT": 2595.9059676473794,
          "HYPE-USDT": -429.8396403650029,
          "LINK-USDT": -614.2292488904841,
          "SOL-USDT": 512.3310333387702
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 2742.411825349513,
          "BTC-USDT": 1984.7767378666595,
          "ETH-USDT": 2817.6073362336087,
          "HYPE-USDT": 0.0,
          "LINK-USDT": 776.6677234061467,
          "SOL-USDT": 726.194857272745
        },
        "total_positive_trade_profit_bps": 9047.658480128674,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.31141840095113066,
        "winner_T": 6,
        "top_decile_winner_T": 1,
        "top_decile_winners_share": 0.31141840095113066,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": -379.13350630584205,
          "2026-06": -1413.4506810798412,
          "2026-07": -1357.7033803363106,
          "2026-08": 8132.366330294825,
          "2026-09": 0
        },
        "top_positive_month_share": 1.0
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1778457600000,
          "T": 1,
          "net_trade_sum_bps": -229.24951995268782
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 1,
          "net_trade_sum_bps": -149.88398635315423
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 1,
          "net_trade_sum_bps": -176.4388846670961
        },
        {
          "utc_monday_ms": 1780876800000,
          "T": 1,
          "net_trade_sum_bps": -568.1771737088236
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 4,
          "net_trade_sum_bps": -668.8346227039214
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 1,
          "net_trade_sum_bps": -88.742632884587
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 3,
          "net_trade_sum_bps": -839.1211070867208
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 1,
          "net_trade_sum_bps": -429.8396403650029
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 1,
          "net_trade_sum_bps": -148.74953813142525
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 3,
          "net_trade_sum_bps": -679.8835820528263
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 5,
          "net_trade_sum_bps": 8960.999450479077
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778630400000,
          "end_exit_ms": 1786478400000,
          "exit_groups": 15,
          "origin_keys": [
            "51694dbf44269443137e55f6d0930bed96a9a973d316548eefc83aa046896729",
            "fbb58ca3453bbf81df4b4e82debd3cc07875c5666c6841a5cca57fea900705b4",
            "578c32fa7bb629c2cc136354741556c944f16d029a5a671b423715f1fbf3e379",
            "9190a651256b0b77e800f2c67116fb3b1701de716ddcf13e266d3344e2f014d5",
            "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568",
            "c4f4ac82b590d77483debb043cd0953c41e1ec3a4f47961a4b130135ae9074cb",
            "64b673229efe7ebff6a88851395741b66b20cea69751309f0393f4715ae73b19",
            "18a8d76917adc06bc592b54eb4b9211697ff94fae98c588e3e850d704cd4e1d0",
            "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6",
            "bb2096de88f7ae613a038f39a58221438e44cac57cf6286915522e1b0faeab62",
            "b005e4d1d431dfabd2c4d12d0205b33f3fa3cfd3a01ef62299888eaf438b4245",
            "fe5abbc5dd9ef292ad6a800292338342013096ae76e0cdda1294205ca0a16330",
            "84b9483292abbf26e56f2460135f9f76d6a9e95821073d80c342cb2d3fc55d3a",
            "e2ee772a775c57ef6f6b059f00d842055e54bba3605202bd51555f9d3260740a",
            "774407ad10ddb1586a82d56100cdad53b85533e69b7e0c423d2ecd81814b19cb",
            "7cde4b543006fb8c9d2138a83226b490da703904eab4e4496115462252268705",
            "73aa8af72a1c27f9dafc67c2e23b9fc8a883f4769a5559b9631b7939660332b1"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1787529600000,
          "end_exit_ms": 1788048000000,
          "exit_groups": 2,
          "origin_keys": [
            "0885a5740d9d7680986d09077031be501313f4588115afee33c0cd8b28e816d3",
            "254874089657dee5a2f36bb9bd1cf8c9a786cfe709b1f6df29229eccbe214a45",
            "4999f99153ed39cf58046aea603e500de7337a8f914896b6d167d57ff2ddd00b",
            "811b7a73c0c6e4ff61e0143d6fac907c10babe6954b7451207ae435548e7c8e3",
            "9d1db065e5e0eb36d9c8ce8c640427a2b089c80b83c9473c725c5c99c2a10e4f"
          ]
        }
      ]
    }
  },
  "partial_assets": {
    "full_terminal_increment_positive": false,
    "full_terminal_base_positive": true,
    "full_terminal_cost2_positive": true,
    "preserve_branch_as_development_evidence": true,
    "formal_or_operating_adoption": false
  }
}
```

No automatic adoption or further candidate is authorized. Old verdicts, Q0 observer, G5B and prior budgets are preserved.
