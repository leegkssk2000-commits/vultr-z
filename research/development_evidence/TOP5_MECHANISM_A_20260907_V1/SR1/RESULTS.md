# SR1 frozen DEV economics

Equal nominal trade-bps; terminal includes hypothetical full-cost open marks. Neither account returns nor independent validation. FULL is primary; FIXED is a diagnostic. KR1/M/M2 ledgers reused. SR1/BR1 V2 baselines computed only for these authorized comparisons. Q0 is preserved without replay or replacement.

## DEV2025

| Metric | P | FIXED | FULL |
|---|---:|---:|---:|
| closed_T | 243.000000 | 242.000000 | 224.000000 |
| open_T | 3.000000 | 4.000000 | 4.000000 |
| entries_T | 246.000000 | 246.000000 | 228.000000 |
| win_rate | 0.436214 | 0.347107 | 0.348214 |
| PF | 0.906368 | 0.897373 | 0.886926 |
| mean_win_bps | 507.090641 | 672.855306 | 661.301692 |
| mean_loss_bps | -432.878727 | -398.630850 | -398.339890 |
| realized_payoff | 1.171438 | 1.687916 | 1.660144 |
| net_expectancy_bps_per_closed_trade | -22.850937 | -26.710036 | -29.357553 |
| closed_gross_bps | -367.410971 | -904.441382 | -1446.064481 |
| closed_net_bps | -5552.777662 | -6463.828632 | -6576.091963 |
| closed_cost2x_net_bps | -10738.144353 | -12023.215882 | -11706.119446 |
| closed_cost_bps | 5185.366691 | 5559.387250 | 5130.027483 |
| closed_fee_bps | 2430.000000 | 2420.000000 | 2240.000000 |
| closed_funding_bps | 1729.980000 | 2164.340000 | 1987.840000 |
| terminal_net_bps_hypothetical | -5897.474774 | -6312.024051 | -6424.287382 |
| terminal_cost2x_net_bps_hypothetical | -11142.841465 | -11957.015086 | -11639.918650 |
| open_net_mark_bps_hypothetical | -344.697113 | 151.804581 | 151.804581 |
| marked_DD_trade_sum_bps | 13409.625674 | 18123.569325 | 18096.174009 |
| grouped_max_loss_trade_sum_bps | 4456.324155 | 6864.043029 | 6981.588058 |
| exposure_symbol_days | 486.500000 | 610.333333 | 562.166667 |
| max_simultaneous_symbols | 7.000000 | 7.000000 | 7.000000 |
| entries_per_30_days | 19.680000 | 19.680000 | 18.240000 |
| max_completed_recovery_days | 83.000000 | 83.000000 | 82.000000 |
| open_underwater_days | 232.333333 | 232.333333 | 232.333333 |

Decisions: {"FIXED": "REJECT", "FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "P": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": -556.5480314261271,
        "net_bps": -526.8126079753038,
        "cost2x_net_bps": -497.07718452448063,
        "cost_bps": -29.73542345082325,
        "fee_bps": -180.0,
        "spread_bps": -28.75450435763353,
        "impact_bps": -38.10526294469316,
        "slippage_bps": 0.0,
        "funding_bps": 269.86,
        "frozen_floor_reserve_bps": -52.73565614849657
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 10,
          "delta_bps": {
            "gross_bps": -3137.6062876272404,
            "net_bps": -3347.0477952753477,
            "cost2x_net_bps": -3556.489302923455,
            "cost_bps": 209.4415076481073,
            "fee_bps": 100.0,
            "spread_bps": 20.12529258054866,
            "impact_bps": 20.0,
            "slippage_bps": 0.0,
            "funding_bps": 66.92,
            "frozen_floor_reserve_bps": 2.3962150675586216
          }
        },
        "C_ABSENT": {
          "T": 28,
          "delta_bps": {
            "gross_bps": 1930.5720946600188,
            "net_bps": 2530.8295846780115,
            "cost2x_net_bps": 3131.087074696004,
            "cost_bps": -600.2574900179926,
            "fee_bps": -280.0,
            "spread_bps": -48.87979693818219,
            "impact_bps": -58.10526294469316,
            "slippage_bps": 0.0,
            "funding_bps": -201.48000000000002,
            "frozen_floor_reserve_bps": -11.792430135117243
          }
        },
        "C_C": {
          "T": 214,
          "delta_bps": {
            "gross_bps": 552.5807238662621,
            "net_bps": 197.10394987964142,
            "cost2x_net_bps": -158.37282410697938,
            "cost_bps": 355.4767739866207,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 398.42,
            "frozen_floor_reserve_bps": -42.94322601337932
          }
        },
        "C_O": {
          "T": 1,
          "delta_bps": {
            "gross_bps": 97.90543767483234,
            "net_bps": 92.30165274239096,
            "cost2x_net_bps": 86.69786780994957,
            "cost_bps": 5.603784932441378,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 6.0,
            "frozen_floor_reserve_bps": -0.39621506755862157
          }
        },
        "O_O": {
          "T": 3,
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
        "T": 95,
        "parent_positive_bps": 35063.98441027467,
        "child_signed_terminal_bps": 29213.939339262288,
        "capped_terminal_preserved_bps_hypothetical": 20664.236652439202,
        "capped_terminal_retention_hypothetical": 0.5893293931075338,
        "realized_capped_retention_lower": 0.5778018942298642,
        "realized_capped_retention_upper": 0.5893293931075338,
        "profit_cut_bps": 14399.747757835472,
        "additional_loss_after_winner_bps": 2346.933849642018,
        "signed_winner_deterioration_bps": 16746.68160747749,
        "winner_to_loss_T": 19,
        "winner_removed_T": 9,
        "winner_to_loss_origins": [
          "2411df91ef824606491da1378deb4854bb277662753f897769dd70b03c956f0b",
          "298c92b904c53ab9052c8fd807bcbb58ba4aa9fe4c7a733df2b4887cd99df27d",
          "36c90aa9676fc1aee9b7ce15aa8b40fbd96021c9ef4cecaf1154969e784e352b",
          "380b04754c9b18303423aae9c6fd2791e0ae42ce1f344eeb82c0bb47c74d59a3",
          "46dfa0fbb37dd28c73050787e55c5ed8cdc236c2c990e28c5ff7baadf0c43584",
          "48d763997a7d08341b875768bedfb5510a3e10967b963c2f699757b427254609",
          "551154175efb98da665fa3195b4949bb77249993a29bc8fc3005bb01f554fbf7",
          "5f1d966868dae1486ef8e990577d73ce8cf418df01653600b247d5cce6288e80",
          "66c69d6757c9a3e68f432bf73370c73d1b2c985878965e9071a827d5d3891374",
          "6819c2968fe4cd149e1f08ade6d94d39659e1efa165239842eb934f4a611a19b",
          "69e1d65ac318192e8d2f8b12d8e13c3e0664129bfb4b402963261838be36b162",
          "72ddb56d93eb92d9f5fb7770ff706a353ca8761886154fe2a0bb99d61a478566",
          "86d26a1d53c9e35900268b0b33376904bb329dba5314a4631f5d001bb5ad864d",
          "999da21c5d14a7a72e0a0daf703a6d9ba659e741ffa15d350734dec3c0346186",
          "9fed38bbaaff3f420cc0091e591df224ca52a792e6a000065f2a2ad082c33862",
          "a3b10b6d6ebde38b24761e4e03f3bf0c050b3f3bd71450d1642f48c832fe5d6a",
          "a597ad625acc8bf173e0636249e11feb850fb54bdb20b67030b2803c69e0791e",
          "f4f1cfea996b341497abdddbe8178f4623925cfa3cfe1507c41fc30d7c5862fc",
          "f9193759bc56d2fffdcaeaf63b1c67f78a936c9363ae739e58675073fd0c356e"
        ]
      },
      "large_winners": {
        "T": 11,
        "parent_positive_bps": 18687.623504329673,
        "child_signed_terminal_bps": 20257.34075897957,
        "capped_terminal_preserved_bps_hypothetical": 16020.818242267047,
        "capped_terminal_retention_hypothetical": 0.85729564481836,
        "realized_capped_retention_lower": 0.85729564481836,
        "realized_capped_retention_upper": 0.85729564481836,
        "profit_cut_bps": 2666.8052620626277,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 2666.8052620626277,
        "winner_to_loss_T": 0,
        "winner_removed_T": 1,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "40435df132fb643dfaae44cb14a00fc363ddb393cf23aafc39b63e67771c09aa",
        "symbol": "ETH-USDT",
        "signal_ts": 1752465600000,
        "entry_month": "2025-07",
        "transition": "C_C",
        "parent": {
          "gross_bps": 261.9021744499661,
          "net_bps": 241.90217444996608,
          "cost2x_net_bps": 221.90217444996608,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.0,
          "frozen_floor_reserve_bps": 1.0
        },
        "child": {
          "gross_bps": 1845.3351247929438,
          "net_bps": 1820.3351247929438,
          "cost2x_net_bps": 1795.3351247929438,
          "cost_bps": 25.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 12.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 1583.4329503429776,
          "net_bps": 1578.4329503429776,
          "cost2x_net_bps": 1573.4329503429776,
          "cost_bps": 5.0,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.0,
          "frozen_floor_reserve_bps": -1.0
        },
        "parent_large_winner": false,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 172800000,
        "child_hold_ms": 345600000
      },
      "net_increment_without_largest_positive": -2105.2455583182814,
      "largest_positive_share_of_net_increment": -2.9961943325718057,
      "increment_by_symbol": {
        "1000PEPE-USDT": 2377.6773266649802,
        "SOL-USDT": -363.32842382523734,
        "LINK-USDT": -1615.7928494625767,
        "BTC-USDT": -159.3220168638133,
        "ETH-USDT": 33.355133387767864,
        "HYPE-USDT": 1918.888435604303,
        "BCH-USDT": -2718.2902134807273
      },
      "increment_by_entry_month": {
        "2025-07": 1082.7349274973928,
        "2025-10": -910.0949414987891,
        "2025-05": 2470.166810005072,
        "2025-08": -3480.7515733886876,
        "2025-11": -609.3230815879302,
        "2025-09": -10.850632910322389,
        "2025-03": 1418.3982095444362,
        "2025-04": 486.02697929817526,
        "2025-06": -51.61555838070478,
        "2025-12": -703.0411618641898,
        "2025-01": -218.4625846897547,
        "2025-02": 0.0
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
      "fixed_path_or_filter_effect": -14.924932768356712,
      "full_occupancy_remainder": -541.62309865777,
      "full_total_effect": -556.5480314261267
    },
    "net_bps": {
      "fixed_path_or_filter_effect": -414.5492766198604,
      "full_occupancy_remainder": -112.26333135544337,
      "full_total_effect": -526.8126079753038
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": -814.1736204713652,
      "full_occupancy_remainder": 317.0964359468835,
      "full_total_effect": -497.0771845244817
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 399.624343851503,
      "full_occupancy_remainder": -429.3597673023269,
      "full_total_effect": -29.735423450823873
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -180.0,
      "full_total_effect": -180.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -28.75450435763355,
      "full_total_effect": -28.75450435763355
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -38.10526294469321,
      "full_total_effect": -38.10526294469321
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 446.3599999999999,
      "full_occupancy_remainder": -176.5,
      "full_total_effect": 269.8599999999999
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -46.73565614849656,
      "full_occupancy_remainder": -6.0,
      "full_total_effect": -52.73565614849656
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
      "parent_marked_delta_sum_bps": -5897.474774309463,
      "child_marked_delta_sum_bps": -6312.024050929325,
      "child_minus_parent_marked_delta_sum_bps": -414.5492766198624,
      "child_minus_parent_mean_daily_bps": -1.1025246718613362,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -32.14431275281532,
        34.08592372409798
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -12086.261595058559,
        12816.307320260841
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
      "parent_marked_delta_sum_bps": -5897.474774309463,
      "child_marked_delta_sum_bps": -6424.287382284769,
      "child_minus_parent_marked_delta_sum_bps": -526.8126079753055,
      "child_minus_parent_mean_daily_bps": -1.4010973616364508,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -31.929737014272476,
        25.542983984181266
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -12005.581117366452,
        9604.161978052156
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
          "1000PEPE-USDT": -5563.394417913226,
          "BCH-USDT": -785.390104203109,
          "BTC-USDT": -43.12792391180801,
          "ETH-USDT": 4786.467466722169,
          "HYPE-USDT": 1883.4007249650308,
          "LINK-USDT": -3837.1366081150263,
          "SOL-USDT": -1993.5967992991382
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 7757.553477770419,
          "BCH-USDT": 6915.852509454022,
          "BTC-USDT": 3377.851118229611,
          "ETH-USDT": 8191.753712992712,
          "HYPE-USDT": 13036.206830415202,
          "LINK-USDT": 7765.879759552012,
          "SOL-USDT": 6706.510506190376
        },
        "total_positive_trade_profit_bps": 53751.60791460435,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.24252682545098814,
        "winner_T": 106,
        "top_decile_winner_T": 11,
        "top_decile_winners_share": 0.34766631602944537,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": -1715.814064605713,
          "2025-03": -1513.1277383709369,
          "2025-04": 52.04993230967909,
          "2025-05": 2802.7523424418105,
          "2025-06": -3265.579892243409,
          "2025-07": 797.6941860428174,
          "2025-08": 2728.8381910751586,
          "2025-09": 2661.9038441396447,
          "2025-10": -5094.271733788864,
          "2025-11": -1245.0812061706738,
          "2025-12": -1762.1415225846195
        },
        "top_positive_month_share": 0.3099279471263197
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 2,
          "net_trade_sum_bps": -1534.1106915172509
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": 85.71032734221444
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 1,
          "net_trade_sum_bps": -955.7405803378083
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 4,
          "net_trade_sum_bps": -383.1821925014263
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 9,
          "net_trade_sum_bps": -259.91529287391677
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 9,
          "net_trade_sum_bps": -889.5738430439728
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 11,
          "net_trade_sum_bps": 2420.502684946904
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 13,
          "net_trade_sum_bps": -1943.8996786535688
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 9,
          "net_trade_sum_bps": 9755.099812886421
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 8,
          "net_trade_sum_bps": -3365.279402219232
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 13,
          "net_trade_sum_bps": -1416.3144376919217
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 6,
          "net_trade_sum_bps": -1705.7328614731402
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 1,
          "net_trade_sum_bps": 136.7776667700891
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 9,
          "net_trade_sum_bps": -1195.0691264903178
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 4,
          "net_trade_sum_bps": -2163.7398608430894
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 1,
          "net_trade_sum_bps": -43.548571680090944
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 10,
          "net_trade_sum_bps": -2770.7362716369485
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 15,
          "net_trade_sum_bps": 4463.5090912712185
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 10,
          "net_trade_sum_bps": 1284.2303887473593
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 13,
          "net_trade_sum_bps": -1448.8879514164626
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 4,
          "net_trade_sum_bps": -1663.6290021264476
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 4,
          "net_trade_sum_bps": 2255.5874604692867
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 12,
          "net_trade_sum_bps": 738.8344304268268
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 3,
          "net_trade_sum_bps": 807.4338673966377
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 5,
          "net_trade_sum_bps": -139.80963601349399
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 6,
          "net_trade_sum_bps": -214.28734950913363
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 10,
          "net_trade_sum_bps": 2345.2428603919525
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 7,
          "net_trade_sum_bps": 530.9483332568259
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 6,
          "net_trade_sum_bps": -1215.4122416131127
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 8,
          "net_trade_sum_bps": -3220.0165525583343
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 10,
          "net_trade_sum_bps": -1109.0482489805042
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 1,
          "net_trade_sum_bps": -74.87828035395492
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 3,
          "net_trade_sum_bps": -719.9976164536325
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 2,
          "net_trade_sum_bps": 301.9334527141594
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 8,
          "net_trade_sum_bps": -1476.358881229396
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 1,
          "net_trade_sum_bps": -666.702363012599
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 2,
          "net_trade_sum_bps": 78.98626894321637
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1738382400000,
          "end_exit_ms": 1740398400000,
          "exit_groups": 3,
          "origin_keys": [
            "3f06d2c26ac4254d84c976fdc109c9e2824a058a4eb1b6d080b8fd3de771bc74",
            "499a1d05fe5b1f2c1650761f86ebdb28bb1d70536a3ad6cc57f2cc31f6bdc656",
            "ea659b0ccf61c677a04573029ef42eae74657061e445433057785be7ca829d9e"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1741190400000,
          "end_exit_ms": 1741190400000,
          "exit_groups": 1,
          "origin_keys": [
            "cdffe4e2d1eb3eb2317d1c3c1f9647e8d2656395cb55f3a7df3de8e4dd035dea"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1741507200000,
          "end_exit_ms": 1741780800000,
          "exit_groups": 2,
          "origin_keys": [
            "89f6365a95ebd9eb1ce9f9657b6c5fd1b00252670beff002de99669be01b7566",
            "44ccfc78b8ec761cd50df0444997c02c0f5bcc5aeabc201e0fe8ca3674aaa37b"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1742385600000,
          "end_exit_ms": 1742385600000,
          "exit_groups": 1,
          "origin_keys": [
            "a43eb9bd1ec56bb7008b4c23124fbbb5bfca54c0660eb06d0ea400c224c946e9"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1742601600000,
          "end_exit_ms": 1742601600000,
          "exit_groups": 1,
          "origin_keys": [
            "0c4dc77ee1643edeac24b577a063714cac58e628ee51c7e1901ed40f3cab830d",
            "38d3beb857ea33f98d45d8194922a0db591136988f82df5354224f045fbab1d5",
            "faeca04e3298816e30ce894fef3bfa1f57f29115ae38c0f519b42d88f351e176"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1742875200000,
          "end_exit_ms": 1742961600000,
          "exit_groups": 3,
          "origin_keys": [
            "090ca68d59e37dda030bcd4d4a18599f5660609f21af4e700cc288305d1c0f41",
            "2411df91ef824606491da1378deb4854bb277662753f897769dd70b03c956f0b",
            "3705214900e321b6ba0e3dc458e05a08441916648a7717778cf07a4408b0fb04",
            "935f51d5dfca4ee83eea2d2fe12115624872cddf22dae3ba97b9ef0a9628e5f5",
            "fd3e68bcacc14ac6d735dc3eda32ae0660ec9c4239746c14ae792e2279c25007",
            "5c870227d8a62ab9504892010071669682709df69692f845f164fc63dc6f060d"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1743148800000,
          "end_exit_ms": 1744862400000,
          "exit_groups": 5,
          "origin_keys": [
            "33059fccf5e77f5fb35794d24f0b4f3ff33d2fde789a0830ed8a8f27f6765fdf",
            "796ea8e60570da5418088e91f9150a6270f14f8daeca0668dd44f97631e1caf0",
            "b3052e81cdd9b3e46e865eb8e9ec144f064a12ef0a89606e2f0b65a0f129d781",
            "6819c2968fe4cd149e1f08ade6d94d39659e1efa165239842eb934f4a611a19b",
            "a007aa659db48f86e9a74b2ea1b11e97460ac7ead22f80148bc210786623f19d",
            "20ee1bc5a3322017d98da923cc0187a901c4f5d7fa4d92067da71b850baeb0e5",
            "99329ce1c68774859d0c8a4fcaa7126a8e04e8a774535ebdbf22c71e96baaec1",
            "c88b3aa5c769869c2d4b56a4de6ced3d0378b79af5326e8d090780627cb728d6"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1745006400000,
          "end_exit_ms": 1745510400000,
          "exit_groups": 8,
          "origin_keys": [
            "f7191416ce6cf8c253f139505910c2bb8c0a0aa3496356ce9c5d2ceac1da16bc",
            "21ec29f15139d870b2290971c8f574cd0a00004d9e2b23e28c138d5bc4c8f634",
            "48d763997a7d08341b875768bedfb5510a3e10967b963c2f699757b427254609",
            "ea20ea6b1c734b045f607539ae0db1d7bba98ff9e553587ae5aa4f4c8515cc49",
            "25db8a487b5519a25c18678c1368ba8221c2735815a7d9f9c714a070c181b47e",
            "ce368643a1ee4e5c9dbf91e89831a3c2ab2189b3a5febbc5af221e3a5189a85b",
            "e0a77c870ec4a04bf08d0685426e835bfcd46cb87557f811e7ed607fe803b5a7",
            "d7025aa4a96ffcca427e405f253032d7db31a29115e6c1fe46c962c172d23437",
            "125bdbac1496792aa273008b9838a0a29906fbb6f6119f8ea2d6154bf9f7a99a",
            "5ec5cdb1913aaf85100c78e27878802d84097cbc2942fe5ea00391a3ecd2e05f",
            "a0f4ad8454ce33a2ed9a2cf6d59d3500766f8a4c6f6de104055c8142db7f3c15",
            "eb88c962b6c98641726ebe5eacad5fb13a180b336c8b900402de6ab72a89c83b"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1745697600000,
          "end_exit_ms": 1745812800000,
          "exit_groups": 4,
          "origin_keys": [
            "95a151e7dbdcb96c975501241c49d094cc47a8223933607974d927ec181826a3",
            "e5d33323834e2fac86875242aac13672f11763e859653492ba290224efc0a594",
            "87a25dd04bdfbf4a761a50e1cc4f1225809fe0e8d7e3221211aedbcfaf87a17d",
            "a0838588c4dfbd13a1f8fe0d619d25f059e53b309dff68f2ebb9b31204698029"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1745956800000,
          "end_exit_ms": 1745956800000,
          "exit_groups": 1,
          "origin_keys": [
            "aee7a148681fbd091590bdb281943a612aea009e99044a31ca255d165166ad1f"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1746000000000,
          "end_exit_ms": 1746000000000,
          "exit_groups": 1,
          "origin_keys": [
            "0e8b08199eef3e3e52b67c017532d78514495003b12742918da1977511e5da72",
            "1e6214adc8df4b1b9259bc6c92390c8a3d389cf314e4b280204eb84aeb0e3f0d",
            "a8c0d2be5fcef35d58065f903e086257a637b0aa61071aa1b32a8049eb6335fb",
            "c01515448143995a5b765c0ad78d4d11835338690c7d4b9c65f3e9f0ccdd340a",
            "c244760f3e78d562ee20dfe2bfeb733fc16af26f7a84d67e9e623132d4626635"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1746057600000,
          "end_exit_ms": 1746057600000,
          "exit_groups": 1,
          "origin_keys": [
            "380b04754c9b18303423aae9c6fd2791e0ae42ce1f344eeb82c0bb47c74d59a3"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1746187200000,
          "end_exit_ms": 1746187200000,
          "exit_groups": 1,
          "origin_keys": [
            "f27f1ea12e26b3fedd2fb5cd38c2a27047dba6dea49a838d92c063c8bfda5162"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1746230400000,
          "end_exit_ms": 1746230400000,
          "exit_groups": 1,
          "origin_keys": [
            "285f070cc24265fbe16c24c9c576b7b45e72358ad85828e7e69f409a3f9567ab"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1746273600000,
          "end_exit_ms": 1746331200000,
          "exit_groups": 2,
          "origin_keys": [
            "341fbebfe668e94b4449bf3cb5ca4f0e2f29d186b695aed1f091378b66211099",
            "4403f7818bced41979a2e76fe28022a9d81aa6b48f50641cf7cc3345c00a59be",
            "2d86cd66d569002ff559071a9c87f88524bb20b2538e7f459650dbee3281da5b"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1746604800000,
          "end_exit_ms": 1746950400000,
          "exit_groups": 9,
          "origin_keys": [
            "8421863143ed6ec945c5fcc03cb72c301c7f02b7399394024daba338877fc033",
            "1bb96056e6be22937b27faa373e169f92560e51c3e7c5d9d9c6b91b213ff0761",
            "80375c8342ee107f3229ae8265c49d4221e3dc1f28e4f4903dc1e093c3ade770",
            "1deacdf02cb0ec18460d87540f4ebc783c8cf5cd358c356bb2b7c259e2ac9725",
            "2c5f2a6e0c8040ce0ebd6fb22b8abb94e7f3f9c0dba621109f6187eb2cef6781",
            "045788ca13cf93e6b771285e100f2883ffdf058b21cd6efaf5fc9a04bb343dc0",
            "775c12ccb7a8d51637a17e6e544bc631a6e825b29a2edf210b021d9f8d8920ad",
            "e945308e66130445073cbf1ca3270feedb4b86e948723dd59e794c284660db5f",
            "d01914eefe83e81ad1859ffe18b947a3d9980a461f1b940a5fb52123a7494ca3"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1747094400000,
          "end_exit_ms": 1747785600000,
          "exit_groups": 8,
          "origin_keys": [
            "4e2c812e2248d73760a4f3a7924d35cdfd91bbd99ebb53c79a883f9bdcd80706",
            "8eaa3ed8ef66b96a3157c4c06a38df07945dad522b43a62301a9e818bea0b0e8",
            "18dcb03d55198ec875efc7623bbc6b2d473bb5d566ffb3d9e45e2e3dcfe08686",
            "1b1b55a0366fd5921b52f190788b8bca68d783c13e66335a63fb6b4b5110bae9",
            "88629602b9b9404d0aecf5a123ab7ea2615d917836a8ea81940f26046c0d7101",
            "9c4c1556a11de4a8b58ccc9d0cfcbe14526a34b6ffc1b282cb1bc9538b7d8511",
            "9d6efc1e44fa70078e8aa9ea4dbb240e783fb01f44cf8e45ff6d84b03fdc5f76",
            "1928bee9e627585150645e9a4073c6b325c00195ae06717f633b42125fe0743a",
            "2c3ae6fffd7209ac9b4372fd3dac3999dc23b1c050a8e73b59a73e2eb183beb6",
            "82118b3eaad4211bf1f99d50f37ee2f3f70566f7e3e80b92ba4fb796292c27da",
            "78ed91c962fcdffacd7531f1e597c8b12fdd265d68504ffedda614b350b93639",
            "a54d0ea01e824d885c967ffc682bd732e3cdf6de82fdd85297844c20a73d10e2",
            "403066dcbf04affef2e30405c09c15d1363053f9818a0c33cf1e32eb16e6d098",
            "fb41461d7243276d391cbd441e4a72dab4e75c8c282a5ddbf44b79b2ca392d23"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1748016000000,
          "end_exit_ms": 1748016000000,
          "exit_groups": 1,
          "origin_keys": [
            "046767c95037b0c4aa181d99d72f5e9d48e54e465e922efd7f5875cfa62050ec",
            "43dd923363960932784394019fc94c58f3d12c8da514263cc58c1e414f003d1e"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1748059200000,
          "end_exit_ms": 1748145600000,
          "exit_groups": 3,
          "origin_keys": [
            "1f3de44771f83db3077e5bf62f662bc9295f3416e1b6cd0ab9e5651f1215eb20",
            "29d35d14e2f9a76397611d8d5f77efed86ea1b4288c3673d3744a4c1b57f6bd2",
            "1adc71f522b4f815ed84dcd7378dbb0f30a510f420ecc2d924c6a1e45542e02b",
            "9197894107abc37a96c948c335cad7807bbde14c23ef4ae520787889f6e818c6",
            "c5528dd36a09284ce27229b9618324fd8ea023bdbfbfbcab0c75e0120d45fc04"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1748260800000,
          "end_exit_ms": 1748260800000,
          "exit_groups": 1,
          "origin_keys": [
            "5f1d966868dae1486ef8e990577d73ce8cf418df01653600b247d5cce6288e80"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1748361600000,
          "end_exit_ms": 1748361600000,
          "exit_groups": 1,
          "origin_keys": [
            "b13abb90bae0b6fc213c2976114b93cd32d026e09e553802717b3e38ad50002b"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1748505600000,
          "end_exit_ms": 1748505600000,
          "exit_groups": 1,
          "origin_keys": [
            "24fb834f157eff38c9157f7c14f06d7d47dd5b20d089f2c18af7cf0592d9e770",
            "72ddb56d93eb92d9f5fb7770ff706a353ca8761886154fe2a0bb99d61a478566"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1748649600000,
          "end_exit_ms": 1748649600000,
          "exit_groups": 1,
          "origin_keys": [
            "2a8f6ff3e67ea9e2d608ddd0b78133dc5a8256b8e774fdf3fa45078e30ebd590",
            "a9fae7f9c6cf0ee291c887ee0069923484772b48d31b0411e43fb8ef29e5b823"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1749067200000,
          "end_exit_ms": 1749643200000,
          "exit_groups": 2,
          "origin_keys": [
            "66c69d6757c9a3e68f432bf73370c73d1b2c985878965e9071a827d5d3891374",
            "298c92b904c53ab9052c8fd807bcbb58ba4aa9fe4c7a733df2b4887cd99df27d",
            "debfdc41dcd631bdb45d97b217275e99db314aa88ff4b2c93bcddfa795befda0"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1749729600000,
          "end_exit_ms": 1749830400000,
          "exit_groups": 3,
          "origin_keys": [
            "9c07f8a0239c528fe1435c96a3e411486164230c14e6cb29d6706c73eaf4895b",
            "b2bd7cef923eb95c993904c89416b65911f195109c7b4be739bd4b4280e2e00d",
            "f012d5a4e63d8d32a6d79066a02e6a2e4f89f736d25d22e099ab00511fddaf8e",
            "fb6eb627109c938f5424884a1ac1eab6b2bac0bb00ca8ca41c8c2b9bdbcb284d",
            "211014fd485d2bb93f6d02ca81fe9adde961fa6063bade04ed3900f42f478e6f",
            "77424ab32356c7b4be066c0df68f8eea9399817c5a873101f1f258428cd8385d"
          ]
        },
        {
          "cohort_id": 25,
          "sign": 1,
          "start_exit_ms": 1749974400000,
          "end_exit_ms": 1750176000000,
          "exit_groups": 2,
          "origin_keys": [
            "d96cfe80aedbf3b914ed0ee9b4d718b07c49a0f303e29aebb7ee29113bab48a4",
            "38f9a08fc2613579d7550f3602054e52703808b8e7a65ab2b4ad40955eab74d1"
          ]
        },
        {
          "cohort_id": 26,
          "sign": -1,
          "start_exit_ms": 1750233600000,
          "end_exit_ms": 1750233600000,
          "exit_groups": 1,
          "origin_keys": [
            "e6b471833bc1f03e703b77424cec247cfea6d4c37a207cc3f66b5108b071591f"
          ]
        },
        {
          "cohort_id": 27,
          "sign": 1,
          "start_exit_ms": 1750392000000,
          "end_exit_ms": 1750392000000,
          "exit_groups": 1,
          "origin_keys": [
            "999da21c5d14a7a72e0a0daf703a6d9ba659e741ffa15d350734dec3c0346186"
          ]
        },
        {
          "cohort_id": 28,
          "sign": -1,
          "start_exit_ms": 1750464000000,
          "end_exit_ms": 1750809600000,
          "exit_groups": 2,
          "origin_keys": [
            "44b3b744b06a48222f013ca383bd64ba79d59a8fe24cd3bbae77c83600091b3e",
            "afd11c6598758e778f56bacbf350cec3d92c93cee2789b8c1a2223f024465f29"
          ]
        },
        {
          "cohort_id": 29,
          "sign": 1,
          "start_exit_ms": 1751371200000,
          "end_exit_ms": 1751371200000,
          "exit_groups": 1,
          "origin_keys": [
            "9ddfa98891219f995aa8fbe370265a5defb759b1c5fe243dfabb69e8c6925018",
            "a01c6e3e26ad708c68aac4b74a4f9b089e5eb2d68d08e5a07916f49c0f0dc393"
          ]
        },
        {
          "cohort_id": 30,
          "sign": -1,
          "start_exit_ms": 1751414400000,
          "end_exit_ms": 1751472000000,
          "exit_groups": 2,
          "origin_keys": [
            "2124966535b29ec4bc7eda4a270b3ba9b3fce2e266e9b18cb7f7c0e7e3545251",
            "4a9f85a08e83bf75d783dba3ba621f9697fbeb4d1891853aa9cede5deec7b3cc",
            "bc45907d673b342b71c4f4c9da9ddbf0b4381095d6675cc3500223162ec5e24f",
            "4b6b20cda754238e38542beab975451845c696a0121db5c143e452871d396885"
          ]
        },
        {
          "cohort_id": 31,
          "sign": 1,
          "start_exit_ms": 1751616000000,
          "end_exit_ms": 1751616000000,
          "exit_groups": 1,
          "origin_keys": [
            "674b59f6e53d9364934f579fc7e03782f915af83cfd57acceef8c2c67b6a68b3"
          ]
        },
        {
          "cohort_id": 32,
          "sign": -1,
          "start_exit_ms": 1751644800000,
          "end_exit_ms": 1752163200000,
          "exit_groups": 4,
          "origin_keys": [
            "7eb2694e88ff843fad724b3975dd1f865c4ad6639134604e74977a22df69aae5",
            "f1188fb315936f4cac7982674e6579dea7940fc62e82f9c2798a637959210c5b",
            "a1affbf9531dd7eb95cbfdf521599945fce29d303aae044e7b20ce50b1621bc4",
            "03a8cf7ebd7c7fe24dabcbddc0f35f7908b87720d7515e0f917cde5501206bd9",
            "61bbb944677c3b495ecf6fba86e4070d22d77cb85041a9ead0b8d21ccb7e06e1",
            "956fb5d55ad1f8525407a55d326c053ed226a993614ae5ad5a048e63fdd163de",
            "f66015881e736f3438560c96faa25fe59ec5ca302ebf35562b27fc6a36bcc806",
            "e34fc457e6f4affa6e04c50a02bb8fa34b0e1c2cd2d1275c655f27d3f7cd36f9"
          ]
        },
        {
          "cohort_id": 33,
          "sign": 1,
          "start_exit_ms": 1752177600000,
          "end_exit_ms": 1752264000000,
          "exit_groups": 2,
          "origin_keys": [
            "0069d95e46cacc01205d6fb1e8795583ee08b5da74cc9b98d0515b63cdbe3da8",
            "baae8b2bb3a46b25f2e47fe9190276acbdb829f32f4f4626df1f6b2d6d697e4b",
            "f4ca9e203613851ffa90295134ba53872941603b7cabb08299780e7d729bd295",
            "196502b0ff8eebc249c1d2f90e034d643f8d49d1c26096bc58f5c934211ed574",
            "58213b5de1f2e9b1d6073bffac710d0cd4b17c4b4ac6285c753e76b014f407f6",
            "ca29aca9e31539d520fe60c926fd74103a505bc5118c4f36916726e990583499"
          ]
        },
        {
          "cohort_id": 34,
          "sign": -1,
          "start_exit_ms": 1752350400000,
          "end_exit_ms": 1752364800000,
          "exit_groups": 2,
          "origin_keys": [
            "2470eb9fc8f4ebb5107917cec49430e3b9881da51298726644b46480a39ae126",
            "cbb180c1ad6d8409b7cabca8652d3a82292c00317148d30fba4b5e20ee291a8f",
            "eb92992191e06173d323cf4bae6c29695b843f709d240fefbb5f934953663585",
            "fc803a2a8372e7035163a7e843dff7418b9e257cff312c331e02d98455b58cb0"
          ]
        },
        {
          "cohort_id": 35,
          "sign": 1,
          "start_exit_ms": 1752523200000,
          "end_exit_ms": 1752523200000,
          "exit_groups": 1,
          "origin_keys": [
            "2ea9ab95e694b9a72e505b6ca4233475f59760a302a0d8b418cda57d1ecd4056"
          ]
        },
        {
          "cohort_id": 36,
          "sign": -1,
          "start_exit_ms": 1752638400000,
          "end_exit_ms": 1752638400000,
          "exit_groups": 1,
          "origin_keys": [
            "1fdea7992968cb96805255ab0da46bd4037bc38042823e462e08957ad7830c2a",
            "40435df132fb643dfaae44cb14a00fc363ddb393cf23aafc39b63e67771c09aa",
            "67a6d1ec1b5e63ee4a0bdaaecaeea68f1cda8a8ed121c27cb1966975e9c25254",
            "959cda7c6f8ac04cb09008e2d59d6358caffabb19c081ac624603dac087a0951",
            "993b0a24bb6a44769d3507beb49d6af3901089d22623cf1e22209ed501f953a1"
          ]
        },
        {
          "cohort_id": 37,
          "sign": 1,
          "start_exit_ms": 1752825600000,
          "end_exit_ms": 1752854400000,
          "exit_groups": 2,
          "origin_keys": [
            "7cd2460eacda79c66ab2164119954954f233273268a16ea28e0a901cc21450a5",
            "77f9b449eeda9962632553b728d2a121023da52a3245d8e743df4989c980c070"
          ]
        },
        {
          "cohort_id": 38,
          "sign": -1,
          "start_exit_ms": 1752868800000,
          "end_exit_ms": 1752868800000,
          "exit_groups": 1,
          "origin_keys": [
            "67f4cd0fc1936a7dbb16cc49bed8e2b59ae2068b693f1908d793fa46766b9ac4",
            "f8bc01bb783b3fb83cef6d79640690cf4ecbfb21024219d6f476162cff793924"
          ]
        },
        {
          "cohort_id": 39,
          "sign": 1,
          "start_exit_ms": 1753128000000,
          "end_exit_ms": 1753128000000,
          "exit_groups": 1,
          "origin_keys": [
            "c2b0e8fda7b3a6e9f5f83d383ea671450616049414ea56aa758857e22b7b743f"
          ]
        },
        {
          "cohort_id": 40,
          "sign": -1,
          "start_exit_ms": 1753185600000,
          "end_exit_ms": 1753200000000,
          "exit_groups": 2,
          "origin_keys": [
            "74247b7404aaf99d7c7a1ac595a4d669072283581d2a58e0fc153b10f2738bef",
            "7eb9ecd015150253ce74d7931f6bad9c6ee03c58628fd420e0acd97d53af7670",
            "a601c4f6ad76a9ac57bbdfcee25d42261d7b7e6dc9c81bb546240caa7f9b3f99"
          ]
        },
        {
          "cohort_id": 41,
          "sign": 1,
          "start_exit_ms": 1753243200000,
          "end_exit_ms": 1753243200000,
          "exit_groups": 1,
          "origin_keys": [
            "375ef3c0a0acf7a90f2848b309ef4b879ba8d62b2ea676f47a8bde0b9428220f",
            "f4f1cfea996b341497abdddbe8178f4623925cfa3cfe1507c41fc30d7c5862fc"
          ]
        },
        {
          "cohort_id": 42,
          "sign": -1,
          "start_exit_ms": 1753401600000,
          "end_exit_ms": 1753401600000,
          "exit_groups": 1,
          "origin_keys": [
            "390b535ebacdef6f444c0051375eb4a7bb127ef59a19beda00fbe240759f18e1",
            "3eccc7caa793374e3a990df34735dcd393b6af2f92bef4340924216f30aeb3ab",
            "4c3d83a7bd8ea05433771fdbcefe60ed58b6b7d56bfe52761e63f006724df973",
            "5756bd3cfee17e430aeffe6a89d7156664677d7bb4417cf91be8f7e52a4c7bf2"
          ]
        },
        {
          "cohort_id": 43,
          "sign": 1,
          "start_exit_ms": 1753617600000,
          "end_exit_ms": 1753617600000,
          "exit_groups": 1,
          "origin_keys": [
            "0d713ab59f630f6fa5c06cd16c8e7744f3c81f0cb3ec875817a31296c077edc5",
            "20bb1470728ee9254f06093628659ea2b5af44a9f34b6af61a5172c7530841cb",
            "e437cc2930018e569ae9af01908521bae3dd8e02b2af85c705467580d8079fa0"
          ]
        },
        {
          "cohort_id": 44,
          "sign": -1,
          "start_exit_ms": 1753848000000,
          "end_exit_ms": 1754092800000,
          "exit_groups": 4,
          "origin_keys": [
            "cbf8b6632d4c9763e9e33ebcc7cc68babc1af7f31308e56d039a661a066a7deb",
            "e0ac6d207edd82993f1871ee47e8f8c282ac31abe6c8749d5df8a9d18ffb623f",
            "92c7426982d0e3a5106c22241ef2e76d91adf74b411570122c7df476b53265a3",
            "e25b42fc5f5759fa390f4680a89bb7266b6211db3746122aa6502f73512be9b2"
          ]
        },
        {
          "cohort_id": 45,
          "sign": 1,
          "start_exit_ms": 1754568000000,
          "end_exit_ms": 1754899200000,
          "exit_groups": 5,
          "origin_keys": [
            "efcb7bbcfa308dce9c4b5d722378dbb8cbaebc708a133395d3edda783280bf47",
            "974ae22c35e58ca3d74a6bf20ec4ba93e0954faffac671cc862a4fd29bafe035",
            "cb4a42dd44255cdd00147cc139ac069ecfba1d4533d608f54b6e83e4a206187c",
            "36c90aa9676fc1aee9b7ce15aa8b40fbd96021c9ef4cecaf1154969e784e352b",
            "c24510e0d1301807f86a66f72ffa7b1fe08c10df6bdec17c2f6bac8e0f3a52f5"
          ]
        },
        {
          "cohort_id": 46,
          "sign": -1,
          "start_exit_ms": 1754971200000,
          "end_exit_ms": 1754971200000,
          "exit_groups": 1,
          "origin_keys": [
            "1eede4413485a29011e94ac90bb816b5a7604b149269d30beba81f632c384e7b",
            "a1cebd837243dbc0e7d1a2ea31dda21ee34004661b215111c90709d2a4921db2",
            "a597ad625acc8bf173e0636249e11feb850fb54bdb20b67030b2803c69e0791e"
          ]
        },
        {
          "cohort_id": 47,
          "sign": 1,
          "start_exit_ms": 1755014400000,
          "end_exit_ms": 1755100800000,
          "exit_groups": 2,
          "origin_keys": [
            "eef85add1c8506c8431b606d61f369a44e896ecd61deaaf1e8b0ef84665fc867",
            "8e580e01821f21117f91d09febf0fb2d907d3456eb5fa5e76cb25823fd2c3ba0"
          ]
        },
        {
          "cohort_id": 48,
          "sign": -1,
          "start_exit_ms": 1755187200000,
          "end_exit_ms": 1755403200000,
          "exit_groups": 3,
          "origin_keys": [
            "16fffec8d82bdae63cc92c66487a76741ef6934576c903510c5b01dce3f464b1",
            "318f96df37fbd1cc371db55c24d8b303dd1478700fcf00acd07b6d8b39001643",
            "3e69d5d0c7cb16da22ee34f8e178b6c7b15711e77808001ff7394e810c0d8be1",
            "5dfc8aed55d4606b25ba47c379d6d5600488ec67f2cf2de491fcb993a06dcbb2",
            "dd7fcd1b2c77b82633b47e78c91d8a4017ab90984f62e3555fd68e1ee3a35bd5",
            "0ad0234311a4e8c25415fc1ad482405883729dd6d68cab3144cf826cf851333f"
          ]
        },
        {
          "cohort_id": 49,
          "sign": 1,
          "start_exit_ms": 1755547200000,
          "end_exit_ms": 1755547200000,
          "exit_groups": 1,
          "origin_keys": [
            "94e92b37c105f84cce916c08f2a74fdb93e69a31412d1730c38a4188023ee67d"
          ]
        },
        {
          "cohort_id": 50,
          "sign": -1,
          "start_exit_ms": 1756051200000,
          "end_exit_ms": 1756108800000,
          "exit_groups": 3,
          "origin_keys": [
            "29c33258341a60807ae85b4385595159380f696778b8a4d3e5c5ce65ca134ff4",
            "b2960577c4efbc08c2ae23b147253cb3a412cf45adffea6da406bf32928c3f86",
            "807e3e0eef96b49f108ee548aee365d65427171400e9aea4faf060c9787901b2"
          ]
        },
        {
          "cohort_id": 51,
          "sign": 1,
          "start_exit_ms": 1756238400000,
          "end_exit_ms": 1756238400000,
          "exit_groups": 1,
          "origin_keys": [
            "54d346e1674786f6884253e0782a678caae60c7a7be096481458d4b1dc19fc60"
          ]
        },
        {
          "cohort_id": 52,
          "sign": -1,
          "start_exit_ms": 1756396800000,
          "end_exit_ms": 1756396800000,
          "exit_groups": 1,
          "origin_keys": [
            "0474adeaa45f0a3c9b6c37fda12997d6e0e3b5ee5668b106988655979dfde008"
          ]
        },
        {
          "cohort_id": 53,
          "sign": 1,
          "start_exit_ms": 1756411200000,
          "end_exit_ms": 1756411200000,
          "exit_groups": 1,
          "origin_keys": [
            "838e3b9c70a6cde0911f04ba486c6d02572bfe2cf053f0a368ae84dd6552318a"
          ]
        },
        {
          "cohort_id": 54,
          "sign": -1,
          "start_exit_ms": 1756440000000,
          "end_exit_ms": 1756440000000,
          "exit_groups": 1,
          "origin_keys": [
            "cbef9679f2310df5be37c1310833587561f577568eaf2bc2fb4ea8a160d63b0a"
          ]
        },
        {
          "cohort_id": 55,
          "sign": 1,
          "start_exit_ms": 1756886400000,
          "end_exit_ms": 1756886400000,
          "exit_groups": 1,
          "origin_keys": [
            "980985667838896c62be7ec6ff8848aedde385cc901c6b4496d51f02451be388"
          ]
        },
        {
          "cohort_id": 56,
          "sign": -1,
          "start_exit_ms": 1757059200000,
          "end_exit_ms": 1757059200000,
          "exit_groups": 1,
          "origin_keys": [
            "aecee466bd1bd35fb0aa606060dc265b5ad39117634cf4f6f0642c55c39c43b6"
          ]
        },
        {
          "cohort_id": 57,
          "sign": 1,
          "start_exit_ms": 1757203200000,
          "end_exit_ms": 1757203200000,
          "exit_groups": 1,
          "origin_keys": [
            "9b631f7c648a600ea1a8ab1c011d53f4babab0dadfeb7fcdc0f1a4d51b44a1c2"
          ]
        },
        {
          "cohort_id": 58,
          "sign": -1,
          "start_exit_ms": 1757232000000,
          "end_exit_ms": 1757260800000,
          "exit_groups": 2,
          "origin_keys": [
            "12e461b2ad5a871e9aa1408be71d5f8fa60137a832cd6ed054910d34816e6900",
            "9b3b97aba3e8805652aa80b9ff4a28679377ce6d99e57f324f93973a6619b12c",
            "1c4d896c18cec0b41177004ea584872bd6aebc2ae41807778472cdff1737d545"
          ]
        },
        {
          "cohort_id": 59,
          "sign": 1,
          "start_exit_ms": 1757462400000,
          "end_exit_ms": 1757577600000,
          "exit_groups": 4,
          "origin_keys": [
            "ca29013e489859ae3bfc39ac02b1a7717709827d3750845019abcfad90bbc993",
            "8ccf205363405a39c01b3a909b78eb8facff0a584f2d365367d5356d61fa6dc9",
            "837c63517826928efa736bfc0c4bb7484f4e487b11c125951f981ae34615724d",
            "ccefdb9c39b9933be1e1f0bc7e0694732d646be741f5702e1476c04917a1b2d8"
          ]
        },
        {
          "cohort_id": 60,
          "sign": -1,
          "start_exit_ms": 1757750400000,
          "end_exit_ms": 1757750400000,
          "exit_groups": 1,
          "origin_keys": [
            "e5cd67168b064e5e8e10b404b141dd39b00f9623578a6786c8c95c4e595f5e6e"
          ]
        },
        {
          "cohort_id": 61,
          "sign": 1,
          "start_exit_ms": 1757793600000,
          "end_exit_ms": 1757822400000,
          "exit_groups": 2,
          "origin_keys": [
            "0778c9a9f2e7b6cdf5b9751677f85255be56ad215b031f2959e4f4281874419c",
            "77e713681d08d3c9c08c27ca53b34ca4e3dc0a731b1bc8eaa395ef95cabc77ee"
          ]
        },
        {
          "cohort_id": 62,
          "sign": -1,
          "start_exit_ms": 1757880000000,
          "end_exit_ms": 1758067200000,
          "exit_groups": 2,
          "origin_keys": [
            "1da3649cf17fa7b5ac3258e5a9e2beadd8818f4bdb100175522cc5144b388034",
            "2e839b4d5a5191520e9f91de94f90b382a9df0e040f816cca19db00ffbb71734",
            "f6a231258befaa6ff761959359f8990b3d07d6798a15f9e26fb16b3c457ac3d8",
            "c420a761f46e27f3cf8582dbfae714b92e6feda361c9d3ffec0fd93b558186fe"
          ]
        },
        {
          "cohort_id": 63,
          "sign": 1,
          "start_exit_ms": 1758182400000,
          "end_exit_ms": 1758268800000,
          "exit_groups": 3,
          "origin_keys": [
            "c1cc98b02a832eac9ca1be0b697e5a5a222c000b30a627f5a5fb1aa98a0a5c45",
            "4d43157978d87b00a52366fa3ba3e3abe8a5bd1bc31a8172d35710bc83e3f0f8",
            "20ea91371273223dc52ed00d385e68db8c0ae87a809d79757331e6d3090b007a",
            "77f599550ff733390fba5ee2b80724bc7eab334b4b6bdc31c7525780dcc099d1"
          ]
        },
        {
          "cohort_id": 64,
          "sign": -1,
          "start_exit_ms": 1758312000000,
          "end_exit_ms": 1758312000000,
          "exit_groups": 1,
          "origin_keys": [
            "8283fdde3c8107226b3a5848dab578373cdf19ef85537f31f87799a7fe24ae8a",
            "b5b71cb87e5492f1b71ce6c1eae60ef2f1eb4a0e7f18a6069e09173e99ae462d"
          ]
        },
        {
          "cohort_id": 65,
          "sign": 1,
          "start_exit_ms": 1759435200000,
          "end_exit_ms": 1759435200000,
          "exit_groups": 1,
          "origin_keys": [
            "9c92932ba963ea7d68119564fd74e79028a1d3cc69fe64844adc450fb5a1ebac"
          ]
        },
        {
          "cohort_id": 66,
          "sign": -1,
          "start_exit_ms": 1759608000000,
          "end_exit_ms": 1759608000000,
          "exit_groups": 1,
          "origin_keys": [
            "4492321f2cee38cb2494131551dace19e2720b72091546ba1472da70301a9de4",
            "57bdf3c019df9e59b76f8571bbed36dd460b113f31ca27d19036cb076f5f24fe",
            "8c0762ebc291bf119a319ba583d06472b8c5eaee6443434019ef28d54167072d",
            "96a9264307b892a32e55c4fbac4abaefa762676c2b7a74e9761cb6543e588b3f"
          ]
        },
        {
          "cohort_id": 67,
          "sign": 1,
          "start_exit_ms": 1759680000000,
          "end_exit_ms": 1759809600000,
          "exit_groups": 2,
          "origin_keys": [
            "e188b7fe29d31812a3228261b7985a492c201164e21f0128c9d920097175928a",
            "4a11ccf2fd7a26ae06ccda885fa02c1fdea8137a69866e07450e625ed0ca6ec2",
            "551154175efb98da665fa3195b4949bb77249993a29bc8fc3005bb01f554fbf7",
            "9fed38bbaaff3f420cc0091e591df224ca52a792e6a000065f2a2ad082c33862"
          ]
        },
        {
          "cohort_id": 68,
          "sign": -1,
          "start_exit_ms": 1759824000000,
          "end_exit_ms": 1760126400000,
          "exit_groups": 3,
          "origin_keys": [
            "047259e84f46fc2b383231d68d0ea27ea1936d13d0d30aed610683a8fae55958",
            "9d5a7a71b401d885f199d8f12825aae2cd2aabba00810f5529ecb4940ff1b4ea",
            "7283101e4fdcece1ffab8633279b7529d5061a4a0692a2832242d050efd60748",
            "098bafbe4f784e62a9587047efa0cb2e7eff95b7bdabb0646a3d517895fe90d1",
            "2a6ce18ac5e3271673d105c8c41041d03ef6d98df3569ed81c0aa708044ac981"
          ]
        },
        {
          "cohort_id": 69,
          "sign": 1,
          "start_exit_ms": 1761580800000,
          "end_exit_ms": 1761652800000,
          "exit_groups": 3,
          "origin_keys": [
            "7781fbc0c1822b713dbec25e6ae7934d19047408dc9c37dde793c90301168799",
            "512073d6d9c936fd66d4fcd6f3a89ae9dea297b30f75bb5e691d0b9a3b821609",
            "46dfa0fbb37dd28c73050787e55c5ed8cdc236c2c990e28c5ff7baadf0c43584",
            "86d26a1d53c9e35900268b0b33376904bb329dba5314a4631f5d001bb5ad864d"
          ]
        },
        {
          "cohort_id": 70,
          "sign": -1,
          "start_exit_ms": 1761696000000,
          "end_exit_ms": 1764360000000,
          "exit_groups": 7,
          "origin_keys": [
            "c232b9281ddee92893511f7ea9bc436d5fcb94f299db351f98035809305f3aa5",
            "d4c3fa0e1765b94e30384d07523c6afbf8d90e2929c199a21bc6653cf7c4dabb",
            "8c7d6608fc4551c9fd58fa182511ae956e14be8607559185ea261fdd01405342",
            "03513bbe310acacf07e8ddf4cdc297acae4f996d820c5cc95d947966df39887a",
            "4b4a123751e8ff4e45c0bb4a8076e19d08955731deb532411360cf2911438d65",
            "c598caa805b352c9132d483559991979d149d3be4b8070add0b23db9958dc084",
            "7f0f61a186927f45a5af2b84b2df34ee3c35778bab04a6d0a48ccebfeda92f3f",
            "2c2cd49704e4b55a885236ee5aad7777682324875b8c85faa2bf2470717998f1",
            "057dc5c71a9d6657005793a597771143480f391bb64ac8e6911b58b171bf6a0d"
          ]
        },
        {
          "cohort_id": 71,
          "sign": 1,
          "start_exit_ms": 1764532800000,
          "end_exit_ms": 1765310400000,
          "exit_groups": 5,
          "origin_keys": [
            "f9193759bc56d2fffdcaeaf63b1c67f78a936c9363ae739e58675073fd0c356e",
            "d206da52a9157e6d3145e8b42b534f45fdcea6e93a58f3f6a337c9f36cfaa390",
            "f250107b3756435d9d35e11671f93414fc7a1fcb61d559e9f8cfa7a844c2ffa5",
            "69e1d65ac318192e8d2f8b12d8e13c3e0664129bfb4b402963261838be36b162",
            "54761f9d39a4ab91f4e6b7419a2861725cd5491c1af0bc34cc67801693a4cc1d",
            "a3b10b6d6ebde38b24761e4e03f3bf0c050b3f3bd71450d1642f48c832fe5d6a"
          ]
        },
        {
          "cohort_id": 72,
          "sign": -1,
          "start_exit_ms": 1765468800000,
          "end_exit_ms": 1766577600000,
          "exit_groups": 5,
          "origin_keys": [
            "342addde20daf77d48a6f419f3e0ad39039f2d29c11f485862a77057e3facd1e",
            "517acc6538a9113077851244e126cc6f7becd8d71b0a28b055219133a0f6eeac",
            "d7ff6b20486a8dea69485aca40475038fa5f9d1854cb5dc5682a699c4c38bb3c",
            "e9b450fb969fa425881568ebf8a46906b9447135dc395388393cdfc3efc0c816",
            "c849b92b7ae7adbb73d72d938c122ccb1a24c14ceb6b3cf391d4751a8d5e69bb",
            "d50d4d75abf47a72631022cfab141b268f3bd8923cd95b61246bac32226cc9b8",
            "bcae1d3b355e9893b9699ab6272f3fa25019c195a6753c78674c75e621513b30"
          ]
        },
        {
          "cohort_id": 73,
          "sign": 1,
          "start_exit_ms": 1766836800000,
          "end_exit_ms": 1766836800000,
          "exit_groups": 1,
          "origin_keys": [
            "6106b6d13772a57ae8509c63a9b291018c3246ddb532ad7b6331777ef967adf4"
          ]
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -4953.738424621853,
          "BCH-USDT": -3862.1826579847557,
          "BTC-USDT": -310.69283236367806,
          "ETH-USDT": 7647.705117186415,
          "HYPE-USDT": 1956.6407345919306,
          "LINK-USDT": -3870.7105790595697,
          "SOL-USDT": -3070.8499898019186
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 9208.902793913641,
          "BCH-USDT": 5204.032565251612,
          "BTC-USDT": 3397.111195237211,
          "ETH-USDT": 11121.308787781496,
          "HYPE-USDT": 13844.426617098328,
          "LINK-USDT": 7971.696333947826,
          "SOL-USDT": 5772.3674361191825
        },
        "total_positive_trade_profit_bps": 56519.8457293493,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.24494806095886554,
        "winner_T": 84,
        "top_decile_winner_T": 9,
        "top_decile_winners_share": 0.3904599873664998,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": -1934.2766492954677,
          "2025-03": -1417.7148610272604,
          "2025-04": 903.5523582469548,
          "2025-05": 4477.863960942472,
          "2025-06": -3468.763049275596,
          "2025-07": 4587.307378160588,
          "2025-08": -276.105148246996,
          "2025-09": 2453.017507424985,
          "2025-10": -6319.771106889139,
          "2025-11": -1291.971444546457,
          "2025-12": -4176.9675775475125
        },
        "top_positive_month_share": 0.36929664710750826
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 2,
          "net_trade_sum_bps": -1752.5732762070056
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": 116.1561979029841
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 1,
          "net_trade_sum_bps": -955.7405803378083
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 4,
          "net_trade_sum_bps": -718.9102375084562
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 9,
          "net_trade_sum_bps": 140.77975891601997
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 8,
          "net_trade_sum_bps": -2272.591869785614
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 12,
          "net_trade_sum_bps": 4755.340641815351
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 13,
          "net_trade_sum_bps": -2452.7904709138456
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 5,
          "net_trade_sum_bps": 3834.5320545091326
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 12,
          "net_trade_sum_bps": 4933.111591283222
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 13,
          "net_trade_sum_bps": -559.9821672608176
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 6,
          "net_trade_sum_bps": -2856.2034604580017
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 1,
          "net_trade_sum_bps": -23.43412715426113
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 8,
          "net_trade_sum_bps": -2158.3865571373976
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 5,
          "net_trade_sum_bps": -1243.3937933038465
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 1,
          "net_trade_sum_bps": -43.548571680090944
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 10,
          "net_trade_sum_bps": -3310.8561818240078
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 15,
          "net_trade_sum_bps": 7341.9971641329485
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 10,
          "net_trade_sum_bps": 3987.9526017594067
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 10,
          "net_trade_sum_bps": -3069.2677351873217
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 7,
          "net_trade_sum_bps": -1295.7264019245365
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 1,
          "net_trade_sum_bps": 47.598017124830264
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 15,
          "net_trade_sum_bps": 1138.53116337158
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 3,
          "net_trade_sum_bps": 223.1005340633041
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 5,
          "net_trade_sum_bps": -752.1269316026118
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 6,
          "net_trade_sum_bps": -493.5628559402787
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 9,
          "net_trade_sum_bps": 2764.9713702318086
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 8,
          "net_trade_sum_bps": 181.60899313345516
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 5,
          "net_trade_sum_bps": -1144.6612544693758
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 9,
          "net_trade_sum_bps": -4287.70825263646
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 10,
          "net_trade_sum_bps": -1337.60690914639
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 1,
          "net_trade_sum_bps": -74.87828035395492
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 2,
          "net_trade_sum_bps": -766.8878548294156
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 3,
          "net_trade_sum_bps": -418.53733379322847
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 8,
          "net_trade_sum_bps": -2766.5141087488296
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 1,
          "net_trade_sum_bps": -666.702363012599
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 1,
          "net_trade_sum_bps": -325.21377199285496
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1738440000000,
          "end_exit_ms": 1740398400000,
          "exit_groups": 3,
          "origin_keys": [
            "3f06d2c26ac4254d84c976fdc109c9e2824a058a4eb1b6d080b8fd3de771bc74",
            "499a1d05fe5b1f2c1650761f86ebdb28bb1d70536a3ad6cc57f2cc31f6bdc656",
            "ea659b0ccf61c677a04573029ef42eae74657061e445433057785be7ca829d9e"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1741363200000,
          "end_exit_ms": 1741363200000,
          "exit_groups": 1,
          "origin_keys": [
            "cdffe4e2d1eb3eb2317d1c3c1f9647e8d2656395cb55f3a7df3de8e4dd035dea"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1741507200000,
          "end_exit_ms": 1741780800000,
          "exit_groups": 2,
          "origin_keys": [
            "89f6365a95ebd9eb1ce9f9657b6c5fd1b00252670beff002de99669be01b7566",
            "44ccfc78b8ec761cd50df0444997c02c0f5bcc5aeabc201e0fe8ca3674aaa37b"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1742558400000,
          "end_exit_ms": 1742558400000,
          "exit_groups": 1,
          "origin_keys": [
            "a43eb9bd1ec56bb7008b4c23124fbbb5bfca54c0660eb06d0ea400c224c946e9"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1742601600000,
          "end_exit_ms": 1742947200000,
          "exit_groups": 2,
          "origin_keys": [
            "0c4dc77ee1643edeac24b577a063714cac58e628ee51c7e1901ed40f3cab830d",
            "38d3beb857ea33f98d45d8194922a0db591136988f82df5354224f045fbab1d5",
            "faeca04e3298816e30ce894fef3bfa1f57f29115ae38c0f519b42d88f351e176",
            "fd3e68bcacc14ac6d735dc3eda32ae0660ec9c4239746c14ae792e2279c25007"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1743004800000,
          "end_exit_ms": 1743048000000,
          "exit_groups": 3,
          "origin_keys": [
            "2411df91ef824606491da1378deb4854bb277662753f897769dd70b03c956f0b",
            "3705214900e321b6ba0e3dc458e05a08441916648a7717778cf07a4408b0fb04",
            "935f51d5dfca4ee83eea2d2fe12115624872cddf22dae3ba97b9ef0a9628e5f5",
            "5c870227d8a62ab9504892010071669682709df69692f845f164fc63dc6f060d",
            "090ca68d59e37dda030bcd4d4a18599f5660609f21af4e700cc288305d1c0f41"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1743148800000,
          "end_exit_ms": 1745150400000,
          "exit_groups": 8,
          "origin_keys": [
            "33059fccf5e77f5fb35794d24f0b4f3ff33d2fde789a0830ed8a8f27f6765fdf",
            "796ea8e60570da5418088e91f9150a6270f14f8daeca0668dd44f97631e1caf0",
            "b3052e81cdd9b3e46e865eb8e9ec144f064a12ef0a89606e2f0b65a0f129d781",
            "a007aa659db48f86e9a74b2ea1b11e97460ac7ead22f80148bc210786623f19d",
            "6819c2968fe4cd149e1f08ade6d94d39659e1efa165239842eb934f4a611a19b",
            "20ee1bc5a3322017d98da923cc0187a901c4f5d7fa4d92067da71b850baeb0e5",
            "99329ce1c68774859d0c8a4fcaa7126a8e04e8a774535ebdbf22c71e96baaec1",
            "c88b3aa5c769869c2d4b56a4de6ced3d0378b79af5326e8d090780627cb728d6",
            "21ec29f15139d870b2290971c8f574cd0a00004d9e2b23e28c138d5bc4c8f634",
            "48d763997a7d08341b875768bedfb5510a3e10967b963c2f699757b427254609"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1745164800000,
          "end_exit_ms": 1745438400000,
          "exit_groups": 4,
          "origin_keys": [
            "f7191416ce6cf8c253f139505910c2bb8c0a0aa3496356ce9c5d2ceac1da16bc",
            "25db8a487b5519a25c18678c1368ba8221c2735815a7d9f9c714a070c181b47e",
            "ea20ea6b1c734b045f607539ae0db1d7bba98ff9e553587ae5aa4f4c8515cc49",
            "ce368643a1ee4e5c9dbf91e89831a3c2ab2189b3a5febbc5af221e3a5189a85b"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1745510400000,
          "end_exit_ms": 1745510400000,
          "exit_groups": 1,
          "origin_keys": [
            "eb88c962b6c98641726ebe5eacad5fb13a180b336c8b900402de6ab72a89c83b"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1745539200000,
          "end_exit_ms": 1745683200000,
          "exit_groups": 4,
          "origin_keys": [
            "e0a77c870ec4a04bf08d0685426e835bfcd46cb87557f811e7ed607fe803b5a7",
            "d7025aa4a96ffcca427e405f253032d7db31a29115e6c1fe46c962c172d23437",
            "125bdbac1496792aa273008b9838a0a29906fbb6f6119f8ea2d6154bf9f7a99a",
            "5ec5cdb1913aaf85100c78e27878802d84097cbc2942fe5ea00391a3ecd2e05f",
            "a0f4ad8454ce33a2ed9a2cf6d59d3500766f8a4c6f6de104055c8142db7f3c15"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1745697600000,
          "end_exit_ms": 1745812800000,
          "exit_groups": 4,
          "origin_keys": [
            "95a151e7dbdcb96c975501241c49d094cc47a8223933607974d927ec181826a3",
            "e5d33323834e2fac86875242aac13672f11763e859653492ba290224efc0a594",
            "87a25dd04bdfbf4a761a50e1cc4f1225809fe0e8d7e3221211aedbcfaf87a17d",
            "a0838588c4dfbd13a1f8fe0d619d25f059e53b309dff68f2ebb9b31204698029"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1745956800000,
          "end_exit_ms": 1745956800000,
          "exit_groups": 1,
          "origin_keys": [
            "aee7a148681fbd091590bdb281943a612aea009e99044a31ca255d165166ad1f"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1746000000000,
          "end_exit_ms": 1746331200000,
          "exit_groups": 6,
          "origin_keys": [
            "0e8b08199eef3e3e52b67c017532d78514495003b12742918da1977511e5da72",
            "a8c0d2be5fcef35d58065f903e086257a637b0aa61071aa1b32a8049eb6335fb",
            "c01515448143995a5b765c0ad78d4d11835338690c7d4b9c65f3e9f0ccdd340a",
            "1e6214adc8df4b1b9259bc6c92390c8a3d389cf314e4b280204eb84aeb0e3f0d",
            "c244760f3e78d562ee20dfe2bfeb733fc16af26f7a84d67e9e623132d4626635",
            "380b04754c9b18303423aae9c6fd2791e0ae42ce1f344eeb82c0bb47c74d59a3",
            "f27f1ea12e26b3fedd2fb5cd38c2a27047dba6dea49a838d92c063c8bfda5162",
            "341fbebfe668e94b4449bf3cb5ca4f0e2f29d186b695aed1f091378b66211099",
            "4403f7818bced41979a2e76fe28022a9d81aa6b48f50641cf7cc3345c00a59be",
            "2d86cd66d569002ff559071a9c87f88524bb20b2538e7f459650dbee3281da5b"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1746388800000,
          "end_exit_ms": 1747080000000,
          "exit_groups": 9,
          "origin_keys": [
            "285f070cc24265fbe16c24c9c576b7b45e72358ad85828e7e69f409a3f9567ab",
            "8421863143ed6ec945c5fcc03cb72c301c7f02b7399394024daba338877fc033",
            "1bb96056e6be22937b27faa373e169f92560e51c3e7c5d9d9c6b91b213ff0761",
            "80375c8342ee107f3229ae8265c49d4221e3dc1f28e4f4903dc1e093c3ade770",
            "1deacdf02cb0ec18460d87540f4ebc783c8cf5cd358c356bb2b7c259e2ac9725",
            "e945308e66130445073cbf1ca3270feedb4b86e948723dd59e794c284660db5f",
            "2c5f2a6e0c8040ce0ebd6fb22b8abb94e7f3f9c0dba621109f6187eb2cef6781",
            "045788ca13cf93e6b771285e100f2883ffdf058b21cd6efaf5fc9a04bb343dc0",
            "775c12ccb7a8d51637a17e6e544bc631a6e825b29a2edf210b021d9f8d8920ad",
            "d01914eefe83e81ad1859ffe18b947a3d9980a461f1b940a5fb52123a7494ca3"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1747094400000,
          "end_exit_ms": 1748059200000,
          "exit_groups": 10,
          "origin_keys": [
            "4e2c812e2248d73760a4f3a7924d35cdfd91bbd99ebb53c79a883f9bdcd80706",
            "8eaa3ed8ef66b96a3157c4c06a38df07945dad522b43a62301a9e818bea0b0e8",
            "18dcb03d55198ec875efc7623bbc6b2d473bb5d566ffb3d9e45e2e3dcfe08686",
            "1b1b55a0366fd5921b52f190788b8bca68d783c13e66335a63fb6b4b5110bae9",
            "88629602b9b9404d0aecf5a123ab7ea2615d917836a8ea81940f26046c0d7101",
            "9c4c1556a11de4a8b58ccc9d0cfcbe14526a34b6ffc1b282cb1bc9538b7d8511",
            "9d6efc1e44fa70078e8aa9ea4dbb240e783fb01f44cf8e45ff6d84b03fdc5f76",
            "1928bee9e627585150645e9a4073c6b325c00195ae06717f633b42125fe0743a",
            "2c3ae6fffd7209ac9b4372fd3dac3999dc23b1c050a8e73b59a73e2eb183beb6",
            "82118b3eaad4211bf1f99d50f37ee2f3f70566f7e3e80b92ba4fb796292c27da",
            "78ed91c962fcdffacd7531f1e597c8b12fdd265d68504ffedda614b350b93639",
            "a54d0ea01e824d885c967ffc682bd732e3cdf6de82fdd85297844c20a73d10e2",
            "403066dcbf04affef2e30405c09c15d1363053f9818a0c33cf1e32eb16e6d098",
            "fb41461d7243276d391cbd441e4a72dab4e75c8c282a5ddbf44b79b2ca392d23",
            "046767c95037b0c4aa181d99d72f5e9d48e54e465e922efd7f5875cfa62050ec",
            "29d35d14e2f9a76397611d8d5f77efed86ea1b4288c3673d3744a4c1b57f6bd2"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1748116800000,
          "end_exit_ms": 1748116800000,
          "exit_groups": 1,
          "origin_keys": [
            "1f3de44771f83db3077e5bf62f662bc9295f3416e1b6cd0ab9e5651f1215eb20"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1748131200000,
          "end_exit_ms": 1748145600000,
          "exit_groups": 2,
          "origin_keys": [
            "1adc71f522b4f815ed84dcd7378dbb0f30a510f420ecc2d924c6a1e45542e02b",
            "9197894107abc37a96c948c335cad7807bbde14c23ef4ae520787889f6e818c6",
            "c5528dd36a09284ce27229b9618324fd8ea023bdbfbfbcab0c75e0120d45fc04"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1748188800000,
          "end_exit_ms": 1748188800000,
          "exit_groups": 1,
          "origin_keys": [
            "43dd923363960932784394019fc94c58f3d12c8da514263cc58c1e414f003d1e"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1748318400000,
          "end_exit_ms": 1749758400000,
          "exit_groups": 8,
          "origin_keys": [
            "5f1d966868dae1486ef8e990577d73ce8cf418df01653600b247d5cce6288e80",
            "b13abb90bae0b6fc213c2976114b93cd32d026e09e553802717b3e38ad50002b",
            "24fb834f157eff38c9157f7c14f06d7d47dd5b20d089f2c18af7cf0592d9e770",
            "72ddb56d93eb92d9f5fb7770ff706a353ca8761886154fe2a0bb99d61a478566",
            "2a8f6ff3e67ea9e2d608ddd0b78133dc5a8256b8e774fdf3fa45078e30ebd590",
            "a9fae7f9c6cf0ee291c887ee0069923484772b48d31b0411e43fb8ef29e5b823",
            "66c69d6757c9a3e68f432bf73370c73d1b2c985878965e9071a827d5d3891374",
            "298c92b904c53ab9052c8fd807bcbb58ba4aa9fe4c7a733df2b4887cd99df27d",
            "9c07f8a0239c528fe1435c96a3e411486164230c14e6cb29d6706c73eaf4895b",
            "b2bd7cef923eb95c993904c89416b65911f195109c7b4be739bd4b4280e2e00d",
            "f012d5a4e63d8d32a6d79066a02e6a2e4f89f736d25d22e099ab00511fddaf8e",
            "fb6eb627109c938f5424884a1ac1eab6b2bac0bb00ca8ca41c8c2b9bdbcb284d",
            "211014fd485d2bb93f6d02ca81fe9adde961fa6063bade04ed3900f42f478e6f"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1749772800000,
          "end_exit_ms": 1749772800000,
          "exit_groups": 1,
          "origin_keys": [
            "debfdc41dcd631bdb45d97b217275e99db314aa88ff4b2c93bcddfa795befda0"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1749830400000,
          "end_exit_ms": 1749830400000,
          "exit_groups": 1,
          "origin_keys": [
            "77424ab32356c7b4be066c0df68f8eea9399817c5a873101f1f258428cd8385d"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1750147200000,
          "end_exit_ms": 1750147200000,
          "exit_groups": 1,
          "origin_keys": [
            "d96cfe80aedbf3b914ed0ee9b4d718b07c49a0f303e29aebb7ee29113bab48a4"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1750233600000,
          "end_exit_ms": 1751990400000,
          "exit_groups": 10,
          "origin_keys": [
            "e6b471833bc1f03e703b77424cec247cfea6d4c37a207cc3f66b5108b071591f",
            "38f9a08fc2613579d7550f3602054e52703808b8e7a65ab2b4ad40955eab74d1",
            "44b3b744b06a48222f013ca383bd64ba79d59a8fe24cd3bbae77c83600091b3e",
            "999da21c5d14a7a72e0a0daf703a6d9ba659e741ffa15d350734dec3c0346186",
            "afd11c6598758e778f56bacbf350cec3d92c93cee2789b8c1a2223f024465f29",
            "a01c6e3e26ad708c68aac4b74a4f9b089e5eb2d68d08e5a07916f49c0f0dc393",
            "2124966535b29ec4bc7eda4a270b3ba9b3fce2e266e9b18cb7f7c0e7e3545251",
            "4a9f85a08e83bf75d783dba3ba621f9697fbeb4d1891853aa9cede5deec7b3cc",
            "9ddfa98891219f995aa8fbe370265a5defb759b1c5fe243dfabb69e8c6925018",
            "bc45907d673b342b71c4f4c9da9ddbf0b4381095d6675cc3500223162ec5e24f",
            "4b6b20cda754238e38542beab975451845c696a0121db5c143e452871d396885",
            "674b59f6e53d9364934f579fc7e03782f915af83cfd57acceef8c2c67b6a68b3",
            "7eb2694e88ff843fad724b3975dd1f865c4ad6639134604e74977a22df69aae5",
            "f1188fb315936f4cac7982674e6579dea7940fc62e82f9c2798a637959210c5b",
            "a1affbf9531dd7eb95cbfdf521599945fce29d303aae044e7b20ce50b1621bc4",
            "61bbb944677c3b495ecf6fba86e4070d22d77cb85041a9ead0b8d21ccb7e06e1",
            "956fb5d55ad1f8525407a55d326c053ed226a993614ae5ad5a048e63fdd163de"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1752163200000,
          "end_exit_ms": 1752350400000,
          "exit_groups": 3,
          "origin_keys": [
            "03a8cf7ebd7c7fe24dabcbddc0f35f7908b87720d7515e0f917cde5501206bd9",
            "e34fc457e6f4affa6e04c50a02bb8fa34b0e1c2cd2d1275c655f27d3f7cd36f9",
            "f66015881e736f3438560c96faa25fe59ec5ca302ebf35562b27fc6a36bcc806",
            "ca29aca9e31539d520fe60c926fd74103a505bc5118c4f36916726e990583499",
            "f4ca9e203613851ffa90295134ba53872941603b7cabb08299780e7d729bd295",
            "0069d95e46cacc01205d6fb1e8795583ee08b5da74cc9b98d0515b63cdbe3da8",
            "2470eb9fc8f4ebb5107917cec49430e3b9881da51298726644b46480a39ae126",
            "baae8b2bb3a46b25f2e47fe9190276acbdb829f32f4f4626df1f6b2d6d697e4b"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1752364800000,
          "end_exit_ms": 1752364800000,
          "exit_groups": 1,
          "origin_keys": [
            "cbb180c1ad6d8409b7cabca8652d3a82292c00317148d30fba4b5e20ee291a8f",
            "eb92992191e06173d323cf4bae6c29695b843f709d240fefbb5f934953663585",
            "fc803a2a8372e7035163a7e843dff7418b9e257cff312c331e02d98455b58cb0"
          ]
        },
        {
          "cohort_id": 25,
          "sign": 1,
          "start_exit_ms": 1752436800000,
          "end_exit_ms": 1752523200000,
          "exit_groups": 2,
          "origin_keys": [
            "196502b0ff8eebc249c1d2f90e034d643f8d49d1c26096bc58f5c934211ed574",
            "58213b5de1f2e9b1d6073bffac710d0cd4b17c4b4ac6285c753e76b014f407f6",
            "2ea9ab95e694b9a72e505b6ca4233475f59760a302a0d8b418cda57d1ecd4056"
          ]
        },
        {
          "cohort_id": 26,
          "sign": -1,
          "start_exit_ms": 1752638400000,
          "end_exit_ms": 1752638400000,
          "exit_groups": 1,
          "origin_keys": [
            "1fdea7992968cb96805255ab0da46bd4037bc38042823e462e08957ad7830c2a",
            "67a6d1ec1b5e63ee4a0bdaaecaeea68f1cda8a8ed121c27cb1966975e9c25254",
            "959cda7c6f8ac04cb09008e2d59d6358caffabb19c081ac624603dac087a0951",
            "993b0a24bb6a44769d3507beb49d6af3901089d22623cf1e22209ed501f953a1"
          ]
        },
        {
          "cohort_id": 27,
          "sign": 1,
          "start_exit_ms": 1752811200000,
          "end_exit_ms": 1752811200000,
          "exit_groups": 1,
          "origin_keys": [
            "40435df132fb643dfaae44cb14a00fc363ddb393cf23aafc39b63e67771c09aa"
          ]
        },
        {
          "cohort_id": 28,
          "sign": -1,
          "start_exit_ms": 1752868800000,
          "end_exit_ms": 1752868800000,
          "exit_groups": 1,
          "origin_keys": [
            "67f4cd0fc1936a7dbb16cc49bed8e2b59ae2068b693f1908d793fa46766b9ac4"
          ]
        },
        {
          "cohort_id": 29,
          "sign": 1,
          "start_exit_ms": 1752998400000,
          "end_exit_ms": 1753128000000,
          "exit_groups": 4,
          "origin_keys": [
            "7cd2460eacda79c66ab2164119954954f233273268a16ea28e0a901cc21450a5",
            "77f9b449eeda9962632553b728d2a121023da52a3245d8e743df4989c980c070",
            "f8bc01bb783b3fb83cef6d79640690cf4ecbfb21024219d6f476162cff793924",
            "c2b0e8fda7b3a6e9f5f83d383ea671450616049414ea56aa758857e22b7b743f"
          ]
        },
        {
          "cohort_id": 30,
          "sign": -1,
          "start_exit_ms": 1753185600000,
          "end_exit_ms": 1753257600000,
          "exit_groups": 3,
          "origin_keys": [
            "74247b7404aaf99d7c7a1ac595a4d669072283581d2a58e0fc153b10f2738bef",
            "7eb9ecd015150253ce74d7931f6bad9c6ee03c58628fd420e0acd97d53af7670",
            "a601c4f6ad76a9ac57bbdfcee25d42261d7b7e6dc9c81bb546240caa7f9b3f99",
            "f4f1cfea996b341497abdddbe8178f4623925cfa3cfe1507c41fc30d7c5862fc"
          ]
        },
        {
          "cohort_id": 31,
          "sign": 1,
          "start_exit_ms": 1753286400000,
          "end_exit_ms": 1753286400000,
          "exit_groups": 1,
          "origin_keys": [
            "375ef3c0a0acf7a90f2848b309ef4b879ba8d62b2ea676f47a8bde0b9428220f"
          ]
        },
        {
          "cohort_id": 32,
          "sign": -1,
          "start_exit_ms": 1753401600000,
          "end_exit_ms": 1753401600000,
          "exit_groups": 1,
          "origin_keys": [
            "390b535ebacdef6f444c0051375eb4a7bb127ef59a19beda00fbe240759f18e1",
            "3eccc7caa793374e3a990df34735dcd393b6af2f92bef4340924216f30aeb3ab",
            "4c3d83a7bd8ea05433771fdbcefe60ed58b6b7d56bfe52761e63f006724df973",
            "5756bd3cfee17e430aeffe6a89d7156664677d7bb4417cf91be8f7e52a4c7bf2"
          ]
        },
        {
          "cohort_id": 33,
          "sign": 1,
          "start_exit_ms": 1753718400000,
          "end_exit_ms": 1753790400000,
          "exit_groups": 3,
          "origin_keys": [
            "0d713ab59f630f6fa5c06cd16c8e7744f3c81f0cb3ec875817a31296c077edc5",
            "20bb1470728ee9254f06093628659ea2b5af44a9f34b6af61a5172c7530841cb",
            "e437cc2930018e569ae9af01908521bae3dd8e02b2af85c705467580d8079fa0"
          ]
        },
        {
          "cohort_id": 34,
          "sign": -1,
          "start_exit_ms": 1753848000000,
          "end_exit_ms": 1754092800000,
          "exit_groups": 4,
          "origin_keys": [
            "cbf8b6632d4c9763e9e33ebcc7cc68babc1af7f31308e56d039a661a066a7deb",
            "e0ac6d207edd82993f1871ee47e8f8c282ac31abe6c8749d5df8a9d18ffb623f",
            "92c7426982d0e3a5106c22241ef2e76d91adf74b411570122c7df476b53265a3",
            "e25b42fc5f5759fa390f4680a89bb7266b6211db3746122aa6502f73512be9b2"
          ]
        },
        {
          "cohort_id": 35,
          "sign": 1,
          "start_exit_ms": 1754568000000,
          "end_exit_ms": 1754956800000,
          "exit_groups": 3,
          "origin_keys": [
            "efcb7bbcfa308dce9c4b5d722378dbb8cbaebc708a133395d3edda783280bf47",
            "36c90aa9676fc1aee9b7ce15aa8b40fbd96021c9ef4cecaf1154969e784e352b",
            "974ae22c35e58ca3d74a6bf20ec4ba93e0954faffac671cc862a4fd29bafe035",
            "c24510e0d1301807f86a66f72ffa7b1fe08c10df6bdec17c2f6bac8e0f3a52f5",
            "cb4a42dd44255cdd00147cc139ac069ecfba1d4533d608f54b6e83e4a206187c"
          ]
        },
        {
          "cohort_id": 36,
          "sign": -1,
          "start_exit_ms": 1754971200000,
          "end_exit_ms": 1755000000000,
          "exit_groups": 2,
          "origin_keys": [
            "1eede4413485a29011e94ac90bb816b5a7604b149269d30beba81f632c384e7b",
            "a1cebd837243dbc0e7d1a2ea31dda21ee34004661b215111c90709d2a4921db2",
            "a597ad625acc8bf173e0636249e11feb850fb54bdb20b67030b2803c69e0791e"
          ]
        },
        {
          "cohort_id": 37,
          "sign": 1,
          "start_exit_ms": 1755014400000,
          "end_exit_ms": 1755014400000,
          "exit_groups": 1,
          "origin_keys": [
            "eef85add1c8506c8431b606d61f369a44e896ecd61deaaf1e8b0ef84665fc867"
          ]
        },
        {
          "cohort_id": 38,
          "sign": -1,
          "start_exit_ms": 1755187200000,
          "end_exit_ms": 1755187200000,
          "exit_groups": 1,
          "origin_keys": [
            "16fffec8d82bdae63cc92c66487a76741ef6934576c903510c5b01dce3f464b1",
            "3e69d5d0c7cb16da22ee34f8e178b6c7b15711e77808001ff7394e810c0d8be1",
            "5dfc8aed55d4606b25ba47c379d6d5600488ec67f2cf2de491fcb993a06dcbb2"
          ]
        },
        {
          "cohort_id": 39,
          "sign": 1,
          "start_exit_ms": 1755201600000,
          "end_exit_ms": 1755201600000,
          "exit_groups": 1,
          "origin_keys": [
            "318f96df37fbd1cc371db55c24d8b303dd1478700fcf00acd07b6d8b39001643",
            "8e580e01821f21117f91d09febf0fb2d907d3456eb5fa5e76cb25823fd2c3ba0",
            "dd7fcd1b2c77b82633b47e78c91d8a4017ab90984f62e3555fd68e1ee3a35bd5"
          ]
        },
        {
          "cohort_id": 40,
          "sign": -1,
          "start_exit_ms": 1755403200000,
          "end_exit_ms": 1755403200000,
          "exit_groups": 1,
          "origin_keys": [
            "0ad0234311a4e8c25415fc1ad482405883729dd6d68cab3144cf826cf851333f"
          ]
        },
        {
          "cohort_id": 41,
          "sign": 1,
          "start_exit_ms": 1755576000000,
          "end_exit_ms": 1755576000000,
          "exit_groups": 1,
          "origin_keys": [
            "94e92b37c105f84cce916c08f2a74fdb93e69a31412d1730c38a4188023ee67d"
          ]
        },
        {
          "cohort_id": 42,
          "sign": -1,
          "start_exit_ms": 1756051200000,
          "end_exit_ms": 1756108800000,
          "exit_groups": 3,
          "origin_keys": [
            "29c33258341a60807ae85b4385595159380f696778b8a4d3e5c5ce65ca134ff4",
            "b2960577c4efbc08c2ae23b147253cb3a412cf45adffea6da406bf32928c3f86",
            "807e3e0eef96b49f108ee548aee365d65427171400e9aea4faf060c9787901b2"
          ]
        },
        {
          "cohort_id": 43,
          "sign": 1,
          "start_exit_ms": 1756339200000,
          "end_exit_ms": 1756339200000,
          "exit_groups": 1,
          "origin_keys": [
            "54d346e1674786f6884253e0782a678caae60c7a7be096481458d4b1dc19fc60"
          ]
        },
        {
          "cohort_id": 44,
          "sign": -1,
          "start_exit_ms": 1756396800000,
          "end_exit_ms": 1756440000000,
          "exit_groups": 2,
          "origin_keys": [
            "0474adeaa45f0a3c9b6c37fda12997d6e0e3b5ee5668b106988655979dfde008",
            "cbef9679f2310df5be37c1310833587561f577568eaf2bc2fb4ea8a160d63b0a"
          ]
        },
        {
          "cohort_id": 45,
          "sign": 1,
          "start_exit_ms": 1756483200000,
          "end_exit_ms": 1757001600000,
          "exit_groups": 2,
          "origin_keys": [
            "838e3b9c70a6cde0911f04ba486c6d02572bfe2cf053f0a368ae84dd6552318a",
            "980985667838896c62be7ec6ff8848aedde385cc901c6b4496d51f02451be388"
          ]
        },
        {
          "cohort_id": 46,
          "sign": -1,
          "start_exit_ms": 1757059200000,
          "end_exit_ms": 1757059200000,
          "exit_groups": 1,
          "origin_keys": [
            "aecee466bd1bd35fb0aa606060dc265b5ad39117634cf4f6f0642c55c39c43b6"
          ]
        },
        {
          "cohort_id": 47,
          "sign": 1,
          "start_exit_ms": 1757203200000,
          "end_exit_ms": 1757203200000,
          "exit_groups": 1,
          "origin_keys": [
            "9b631f7c648a600ea1a8ab1c011d53f4babab0dadfeb7fcdc0f1a4d51b44a1c2"
          ]
        },
        {
          "cohort_id": 48,
          "sign": -1,
          "start_exit_ms": 1757232000000,
          "end_exit_ms": 1757260800000,
          "exit_groups": 2,
          "origin_keys": [
            "12e461b2ad5a871e9aa1408be71d5f8fa60137a832cd6ed054910d34816e6900",
            "9b3b97aba3e8805652aa80b9ff4a28679377ce6d99e57f324f93973a6619b12c",
            "1c4d896c18cec0b41177004ea584872bd6aebc2ae41807778472cdff1737d545"
          ]
        },
        {
          "cohort_id": 49,
          "sign": 1,
          "start_exit_ms": 1757635200000,
          "end_exit_ms": 1757750400000,
          "exit_groups": 4,
          "origin_keys": [
            "ca29013e489859ae3bfc39ac02b1a7717709827d3750845019abcfad90bbc993",
            "8ccf205363405a39c01b3a909b78eb8facff0a584f2d365367d5356d61fa6dc9",
            "837c63517826928efa736bfc0c4bb7484f4e487b11c125951f981ae34615724d",
            "ccefdb9c39b9933be1e1f0bc7e0694732d646be741f5702e1476c04917a1b2d8"
          ]
        },
        {
          "cohort_id": 50,
          "sign": -1,
          "start_exit_ms": 1757822400000,
          "end_exit_ms": 1757822400000,
          "exit_groups": 1,
          "origin_keys": [
            "e5cd67168b064e5e8e10b404b141dd39b00f9623578a6786c8c95c4e595f5e6e"
          ]
        },
        {
          "cohort_id": 51,
          "sign": 1,
          "start_exit_ms": 1757851200000,
          "end_exit_ms": 1757851200000,
          "exit_groups": 1,
          "origin_keys": [
            "0778c9a9f2e7b6cdf5b9751677f85255be56ad215b031f2959e4f4281874419c"
          ]
        },
        {
          "cohort_id": 52,
          "sign": -1,
          "start_exit_ms": 1757880000000,
          "end_exit_ms": 1757880000000,
          "exit_groups": 1,
          "origin_keys": [
            "1da3649cf17fa7b5ac3258e5a9e2beadd8818f4bdb100175522cc5144b388034",
            "2e839b4d5a5191520e9f91de94f90b382a9df0e040f816cca19db00ffbb71734",
            "f6a231258befaa6ff761959359f8990b3d07d6798a15f9e26fb16b3c457ac3d8"
          ]
        },
        {
          "cohort_id": 53,
          "sign": 1,
          "start_exit_ms": 1757923200000,
          "end_exit_ms": 1757923200000,
          "exit_groups": 1,
          "origin_keys": [
            "77e713681d08d3c9c08c27ca53b34ca4e3dc0a731b1bc8eaa395ef95cabc77ee"
          ]
        },
        {
          "cohort_id": 54,
          "sign": -1,
          "start_exit_ms": 1758067200000,
          "end_exit_ms": 1758067200000,
          "exit_groups": 1,
          "origin_keys": [
            "c420a761f46e27f3cf8582dbfae714b92e6feda361c9d3ffec0fd93b558186fe"
          ]
        },
        {
          "cohort_id": 55,
          "sign": 1,
          "start_exit_ms": 1758268800000,
          "end_exit_ms": 1758283200000,
          "exit_groups": 2,
          "origin_keys": [
            "20ea91371273223dc52ed00d385e68db8c0ae87a809d79757331e6d3090b007a",
            "4d43157978d87b00a52366fa3ba3e3abe8a5bd1bc31a8172d35710bc83e3f0f8",
            "77f599550ff733390fba5ee2b80724bc7eab334b4b6bdc31c7525780dcc099d1",
            "c1cc98b02a832eac9ca1be0b697e5a5a222c000b30a627f5a5fb1aa98a0a5c45"
          ]
        },
        {
          "cohort_id": 56,
          "sign": -1,
          "start_exit_ms": 1758312000000,
          "end_exit_ms": 1761696000000,
          "exit_groups": 9,
          "origin_keys": [
            "8283fdde3c8107226b3a5848dab578373cdf19ef85537f31f87799a7fe24ae8a",
            "b5b71cb87e5492f1b71ce6c1eae60ef2f1eb4a0e7f18a6069e09173e99ae462d",
            "4492321f2cee38cb2494131551dace19e2720b72091546ba1472da70301a9de4",
            "57bdf3c019df9e59b76f8571bbed36dd460b113f31ca27d19036cb076f5f24fe",
            "8c0762ebc291bf119a319ba583d06472b8c5eaee6443434019ef28d54167072d",
            "96a9264307b892a32e55c4fbac4abaefa762676c2b7a74e9761cb6543e588b3f",
            "9c92932ba963ea7d68119564fd74e79028a1d3cc69fe64844adc450fb5a1ebac",
            "4a11ccf2fd7a26ae06ccda885fa02c1fdea8137a69866e07450e625ed0ca6ec2",
            "047259e84f46fc2b383231d68d0ea27ea1936d13d0d30aed610683a8fae55958",
            "9d5a7a71b401d885f199d8f12825aae2cd2aabba00810f5529ecb4940ff1b4ea",
            "551154175efb98da665fa3195b4949bb77249993a29bc8fc3005bb01f554fbf7",
            "9fed38bbaaff3f420cc0091e591df224ca52a792e6a000065f2a2ad082c33862",
            "e188b7fe29d31812a3228261b7985a492c201164e21f0128c9d920097175928a",
            "7283101e4fdcece1ffab8633279b7529d5061a4a0692a2832242d050efd60748",
            "098bafbe4f784e62a9587047efa0cb2e7eff95b7bdabb0646a3d517895fe90d1",
            "2a6ce18ac5e3271673d105c8c41041d03ef6d98df3569ed81c0aa708044ac981",
            "46dfa0fbb37dd28c73050787e55c5ed8cdc236c2c990e28c5ff7baadf0c43584",
            "86d26a1d53c9e35900268b0b33376904bb329dba5314a4631f5d001bb5ad864d",
            "c232b9281ddee92893511f7ea9bc436d5fcb94f299db351f98035809305f3aa5",
            "d4c3fa0e1765b94e30384d07523c6afbf8d90e2929c199a21bc6653cf7c4dabb"
          ]
        },
        {
          "cohort_id": 57,
          "sign": 1,
          "start_exit_ms": 1761753600000,
          "end_exit_ms": 1761768000000,
          "exit_groups": 2,
          "origin_keys": [
            "7781fbc0c1822b713dbec25e6ae7934d19047408dc9c37dde793c90301168799",
            "512073d6d9c936fd66d4fcd6f3a89ae9dea297b30f75bb5e691d0b9a3b821609"
          ]
        },
        {
          "cohort_id": 58,
          "sign": -1,
          "start_exit_ms": 1761897600000,
          "end_exit_ms": 1764561600000,
          "exit_groups": 7,
          "origin_keys": [
            "8c7d6608fc4551c9fd58fa182511ae956e14be8607559185ea261fdd01405342",
            "03513bbe310acacf07e8ddf4cdc297acae4f996d820c5cc95d947966df39887a",
            "4b4a123751e8ff4e45c0bb4a8076e19d08955731deb532411360cf2911438d65",
            "c598caa805b352c9132d483559991979d149d3be4b8070add0b23db9958dc084",
            "7f0f61a186927f45a5af2b84b2df34ee3c35778bab04a6d0a48ccebfeda92f3f",
            "2c2cd49704e4b55a885236ee5aad7777682324875b8c85faa2bf2470717998f1",
            "057dc5c71a9d6657005793a597771143480f391bb64ac8e6911b58b171bf6a0d",
            "f9193759bc56d2fffdcaeaf63b1c67f78a936c9363ae739e58675073fd0c356e"
          ]
        },
        {
          "cohort_id": 59,
          "sign": 1,
          "start_exit_ms": 1764691200000,
          "end_exit_ms": 1764964800000,
          "exit_groups": 2,
          "origin_keys": [
            "d206da52a9157e6d3145e8b42b534f45fdcea6e93a58f3f6a337c9f36cfaa390",
            "f250107b3756435d9d35e11671f93414fc7a1fcb61d559e9f8cfa7a844c2ffa5"
          ]
        },
        {
          "cohort_id": 60,
          "sign": -1,
          "start_exit_ms": 1765224000000,
          "end_exit_ms": 1765382400000,
          "exit_groups": 2,
          "origin_keys": [
            "69e1d65ac318192e8d2f8b12d8e13c3e0664129bfb4b402963261838be36b162",
            "a3b10b6d6ebde38b24761e4e03f3bf0c050b3f3bd71450d1642f48c832fe5d6a"
          ]
        },
        {
          "cohort_id": 61,
          "sign": 1,
          "start_exit_ms": 1765425600000,
          "end_exit_ms": 1765425600000,
          "exit_groups": 1,
          "origin_keys": [
            "54761f9d39a4ab91f4e6b7419a2861725cd5491c1af0bc34cc67801693a4cc1d"
          ]
        },
        {
          "cohort_id": 62,
          "sign": -1,
          "start_exit_ms": 1765468800000,
          "end_exit_ms": 1766577600000,
          "exit_groups": 5,
          "origin_keys": [
            "342addde20daf77d48a6f419f3e0ad39039f2d29c11f485862a77057e3facd1e",
            "517acc6538a9113077851244e126cc6f7becd8d71b0a28b055219133a0f6eeac",
            "d7ff6b20486a8dea69485aca40475038fa5f9d1854cb5dc5682a699c4c38bb3c",
            "e9b450fb969fa425881568ebf8a46906b9447135dc395388393cdfc3efc0c816",
            "c849b92b7ae7adbb73d72d938c122ccb1a24c14ceb6b3cf391d4751a8d5e69bb",
            "d50d4d75abf47a72631022cfab141b268f3bd8923cd95b61246bac32226cc9b8",
            "bcae1d3b355e9893b9699ab6272f3fa25019c195a6753c78674c75e621513b30"
          ]
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -3185.717091248245,
          "BCH-USDT": -4000.1820113623,
          "BTC-USDT": -202.44994077562097,
          "ETH-USDT": 4819.8226001099365,
          "HYPE-USDT": 3802.289160569334,
          "LINK-USDT": -5452.929457577604,
          "SOL-USDT": -2356.9252231243754
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 9208.902793913641,
          "BCH-USDT": 5204.032565251612,
          "BTC-USDT": 3397.111195237211,
          "ETH-USDT": 8236.590247757313,
          "HYPE-USDT": 13577.745944595914,
          "LINK-USDT": 6204.204049292521,
          "SOL-USDT": 5752.945149194121
        },
        "total_positive_trade_profit_bps": 51581.53194524233,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.26322882304096185,
        "winner_T": 78,
        "top_decile_winner_T": 8,
        "top_decile_winners_share": 0.3959721905528982,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": -1934.2766492954677,
          "2025-03": -94.72952882650091,
          "2025-04": 654.5316376036272,
          "2025-05": 5156.464426451109,
          "2025-06": -2880.7388047112845,
          "2025-07": 1443.9724676273806,
          "2025-08": -751.9133823135296,
          "2025-09": 2556.997057246561,
          "2025-10": -5421.20242539516,
          "2025-11": -1781.0795404561886,
          "2025-12": -3524.117221339419
        },
        "top_positive_month_share": 0.5255281808437446
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 2,
          "net_trade_sum_bps": -1752.5732762070056
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": 116.1561979029841
        },
        {
          "utc_monday_ms": 1741564800000,
          "T": 1,
          "net_trade_sum_bps": -955.7405803378083
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 4,
          "net_trade_sum_bps": -718.9102375084562
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 7,
          "net_trade_sum_bps": 1463.7650911167796
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 8,
          "net_trade_sum_bps": -2272.591869785614
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 10,
          "net_trade_sum_bps": 4506.319921172023
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 13,
          "net_trade_sum_bps": -2452.7904709138456
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 4,
          "net_trade_sum_bps": 3598.4234148961027
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 11,
          "net_trade_sum_bps": 5295.680660131757
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 13,
          "net_trade_sum_bps": -559.9821672608176
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 5,
          "net_trade_sum_bps": -2304.063424184869
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 1,
          "net_trade_sum_bps": -23.43412715426113
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 7,
          "net_trade_sum_bps": -1610.6470544600372
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 4,
          "net_trade_sum_bps": -1203.109051416895
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 1,
          "net_trade_sum_bps": -43.548571680090944
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 10,
          "net_trade_sum_bps": -3310.8561818240078
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 12,
          "net_trade_sum_bps": 5816.2843165477625
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 8,
          "net_trade_sum_bps": 2313.494515863678
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 10,
          "net_trade_sum_bps": -3069.2677351873217
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 6,
          "net_trade_sum_bps": -1238.8903789768292
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 1,
          "net_trade_sum_bps": 47.598017124830264
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 15,
          "net_trade_sum_bps": -396.4192535545619
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 3,
          "net_trade_sum_bps": 223.1005340633041
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 4,
          "net_trade_sum_bps": 307.0152512569965
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 6,
          "net_trade_sum_bps": -493.5628559402787
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 8,
          "net_trade_sum_bps": 2868.9509200533844
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 8,
          "net_trade_sum_bps": 181.60899313345516
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 5,
          "net_trade_sum_bps": -1144.6612544693758
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 9,
          "net_trade_sum_bps": -4405.253282036308
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 10,
          "net_trade_sum_bps": -810.6012941622948
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 1,
          "net_trade_sum_bps": -74.87828035395492
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 2,
          "net_trade_sum_bps": -766.8878548294156
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 3,
          "net_trade_sum_bps": -418.53733379322847
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 7,
          "net_trade_sum_bps": -2113.6637525407364
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 1,
          "net_trade_sum_bps": -666.702363012599
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 1,
          "net_trade_sum_bps": -325.21377199285496
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1738440000000,
          "end_exit_ms": 1740398400000,
          "exit_groups": 3,
          "origin_keys": [
            "3f06d2c26ac4254d84c976fdc109c9e2824a058a4eb1b6d080b8fd3de771bc74",
            "499a1d05fe5b1f2c1650761f86ebdb28bb1d70536a3ad6cc57f2cc31f6bdc656",
            "ea659b0ccf61c677a04573029ef42eae74657061e445433057785be7ca829d9e"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1741363200000,
          "end_exit_ms": 1741363200000,
          "exit_groups": 1,
          "origin_keys": [
            "cdffe4e2d1eb3eb2317d1c3c1f9647e8d2656395cb55f3a7df3de8e4dd035dea"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1741507200000,
          "end_exit_ms": 1741780800000,
          "exit_groups": 2,
          "origin_keys": [
            "89f6365a95ebd9eb1ce9f9657b6c5fd1b00252670beff002de99669be01b7566",
            "44ccfc78b8ec761cd50df0444997c02c0f5bcc5aeabc201e0fe8ca3674aaa37b"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1742558400000,
          "end_exit_ms": 1742558400000,
          "exit_groups": 1,
          "origin_keys": [
            "a43eb9bd1ec56bb7008b4c23124fbbb5bfca54c0660eb06d0ea400c224c946e9"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1742601600000,
          "end_exit_ms": 1742947200000,
          "exit_groups": 2,
          "origin_keys": [
            "0c4dc77ee1643edeac24b577a063714cac58e628ee51c7e1901ed40f3cab830d",
            "38d3beb857ea33f98d45d8194922a0db591136988f82df5354224f045fbab1d5",
            "faeca04e3298816e30ce894fef3bfa1f57f29115ae38c0f519b42d88f351e176",
            "fd3e68bcacc14ac6d735dc3eda32ae0660ec9c4239746c14ae792e2279c25007"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1743004800000,
          "end_exit_ms": 1743048000000,
          "exit_groups": 3,
          "origin_keys": [
            "2411df91ef824606491da1378deb4854bb277662753f897769dd70b03c956f0b",
            "3705214900e321b6ba0e3dc458e05a08441916648a7717778cf07a4408b0fb04",
            "935f51d5dfca4ee83eea2d2fe12115624872cddf22dae3ba97b9ef0a9628e5f5",
            "5c870227d8a62ab9504892010071669682709df69692f845f164fc63dc6f060d",
            "090ca68d59e37dda030bcd4d4a18599f5660609f21af4e700cc288305d1c0f41"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1743220800000,
          "end_exit_ms": 1745150400000,
          "exit_groups": 8,
          "origin_keys": [
            "f5a17b1752e69b8f7310f3744a590bbb4456f94e71530d213bd08d516fba367e",
            "a007aa659db48f86e9a74b2ea1b11e97460ac7ead22f80148bc210786623f19d",
            "6819c2968fe4cd149e1f08ade6d94d39659e1efa165239842eb934f4a611a19b",
            "20ee1bc5a3322017d98da923cc0187a901c4f5d7fa4d92067da71b850baeb0e5",
            "99329ce1c68774859d0c8a4fcaa7126a8e04e8a774535ebdbf22c71e96baaec1",
            "c88b3aa5c769869c2d4b56a4de6ced3d0378b79af5326e8d090780627cb728d6",
            "21ec29f15139d870b2290971c8f574cd0a00004d9e2b23e28c138d5bc4c8f634",
            "48d763997a7d08341b875768bedfb5510a3e10967b963c2f699757b427254609"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1745164800000,
          "end_exit_ms": 1745438400000,
          "exit_groups": 3,
          "origin_keys": [
            "f7191416ce6cf8c253f139505910c2bb8c0a0aa3496356ce9c5d2ceac1da16bc",
            "ea20ea6b1c734b045f607539ae0db1d7bba98ff9e553587ae5aa4f4c8515cc49",
            "ce368643a1ee4e5c9dbf91e89831a3c2ab2189b3a5febbc5af221e3a5189a85b"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1745510400000,
          "end_exit_ms": 1745510400000,
          "exit_groups": 1,
          "origin_keys": [
            "eb88c962b6c98641726ebe5eacad5fb13a180b336c8b900402de6ab72a89c83b"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1745539200000,
          "end_exit_ms": 1745683200000,
          "exit_groups": 4,
          "origin_keys": [
            "e0a77c870ec4a04bf08d0685426e835bfcd46cb87557f811e7ed607fe803b5a7",
            "d7025aa4a96ffcca427e405f253032d7db31a29115e6c1fe46c962c172d23437",
            "125bdbac1496792aa273008b9838a0a29906fbb6f6119f8ea2d6154bf9f7a99a",
            "44b5fbad3e4d3017209404349218f8d49a4d2ce000aebd8cb9e43cfded62b0a5",
            "5ec5cdb1913aaf85100c78e27878802d84097cbc2942fe5ea00391a3ecd2e05f"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1745697600000,
          "end_exit_ms": 1745812800000,
          "exit_groups": 3,
          "origin_keys": [
            "95a151e7dbdcb96c975501241c49d094cc47a8223933607974d927ec181826a3",
            "87a25dd04bdfbf4a761a50e1cc4f1225809fe0e8d7e3221211aedbcfaf87a17d",
            "a0838588c4dfbd13a1f8fe0d619d25f059e53b309dff68f2ebb9b31204698029"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1745956800000,
          "end_exit_ms": 1745956800000,
          "exit_groups": 1,
          "origin_keys": [
            "aee7a148681fbd091590bdb281943a612aea009e99044a31ca255d165166ad1f"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1746000000000,
          "end_exit_ms": 1746331200000,
          "exit_groups": 6,
          "origin_keys": [
            "0e8b08199eef3e3e52b67c017532d78514495003b12742918da1977511e5da72",
            "a8c0d2be5fcef35d58065f903e086257a637b0aa61071aa1b32a8049eb6335fb",
            "c01515448143995a5b765c0ad78d4d11835338690c7d4b9c65f3e9f0ccdd340a",
            "1e6214adc8df4b1b9259bc6c92390c8a3d389cf314e4b280204eb84aeb0e3f0d",
            "c244760f3e78d562ee20dfe2bfeb733fc16af26f7a84d67e9e623132d4626635",
            "380b04754c9b18303423aae9c6fd2791e0ae42ce1f344eeb82c0bb47c74d59a3",
            "f27f1ea12e26b3fedd2fb5cd38c2a27047dba6dea49a838d92c063c8bfda5162",
            "341fbebfe668e94b4449bf3cb5ca4f0e2f29d186b695aed1f091378b66211099",
            "4403f7818bced41979a2e76fe28022a9d81aa6b48f50641cf7cc3345c00a59be",
            "2d86cd66d569002ff559071a9c87f88524bb20b2538e7f459650dbee3281da5b"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1746388800000,
          "end_exit_ms": 1747080000000,
          "exit_groups": 9,
          "origin_keys": [
            "285f070cc24265fbe16c24c9c576b7b45e72358ad85828e7e69f409a3f9567ab",
            "8421863143ed6ec945c5fcc03cb72c301c7f02b7399394024daba338877fc033",
            "1bb96056e6be22937b27faa373e169f92560e51c3e7c5d9d9c6b91b213ff0761",
            "80375c8342ee107f3229ae8265c49d4221e3dc1f28e4f4903dc1e093c3ade770",
            "1deacdf02cb0ec18460d87540f4ebc783c8cf5cd358c356bb2b7c259e2ac9725",
            "2c5f2a6e0c8040ce0ebd6fb22b8abb94e7f3f9c0dba621109f6187eb2cef6781",
            "045788ca13cf93e6b771285e100f2883ffdf058b21cd6efaf5fc9a04bb343dc0",
            "775c12ccb7a8d51637a17e6e544bc631a6e825b29a2edf210b021d9f8d8920ad",
            "d01914eefe83e81ad1859ffe18b947a3d9980a461f1b940a5fb52123a7494ca3"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1747094400000,
          "end_exit_ms": 1748059200000,
          "exit_groups": 10,
          "origin_keys": [
            "c225e9cba9cdce9fdd4f81d89a7ae7410e198fe054892e784bde380712be35ae",
            "3f1fccc759bd500f5f2ccf2c950cdc57fb73e3772647d56227354bfb56cc5e5a",
            "1b1b55a0366fd5921b52f190788b8bca68d783c13e66335a63fb6b4b5110bae9",
            "88629602b9b9404d0aecf5a123ab7ea2615d917836a8ea81940f26046c0d7101",
            "9c4c1556a11de4a8b58ccc9d0cfcbe14526a34b6ffc1b282cb1bc9538b7d8511",
            "9d6efc1e44fa70078e8aa9ea4dbb240e783fb01f44cf8e45ff6d84b03fdc5f76",
            "1928bee9e627585150645e9a4073c6b325c00195ae06717f633b42125fe0743a",
            "2c3ae6fffd7209ac9b4372fd3dac3999dc23b1c050a8e73b59a73e2eb183beb6",
            "82118b3eaad4211bf1f99d50f37ee2f3f70566f7e3e80b92ba4fb796292c27da",
            "78ed91c962fcdffacd7531f1e597c8b12fdd265d68504ffedda614b350b93639",
            "a54d0ea01e824d885c967ffc682bd732e3cdf6de82fdd85297844c20a73d10e2",
            "403066dcbf04affef2e30405c09c15d1363053f9818a0c33cf1e32eb16e6d098",
            "fb41461d7243276d391cbd441e4a72dab4e75c8c282a5ddbf44b79b2ca392d23",
            "046767c95037b0c4aa181d99d72f5e9d48e54e465e922efd7f5875cfa62050ec",
            "29d35d14e2f9a76397611d8d5f77efed86ea1b4288c3673d3744a4c1b57f6bd2"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1748116800000,
          "end_exit_ms": 1748116800000,
          "exit_groups": 1,
          "origin_keys": [
            "1f3de44771f83db3077e5bf62f662bc9295f3416e1b6cd0ab9e5651f1215eb20"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1748131200000,
          "end_exit_ms": 1748145600000,
          "exit_groups": 2,
          "origin_keys": [
            "1adc71f522b4f815ed84dcd7378dbb0f30a510f420ecc2d924c6a1e45542e02b",
            "9197894107abc37a96c948c335cad7807bbde14c23ef4ae520787889f6e818c6",
            "c5528dd36a09284ce27229b9618324fd8ea023bdbfbfbcab0c75e0120d45fc04"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1748188800000,
          "end_exit_ms": 1748188800000,
          "exit_groups": 1,
          "origin_keys": [
            "43dd923363960932784394019fc94c58f3d12c8da514263cc58c1e414f003d1e"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1748318400000,
          "end_exit_ms": 1749758400000,
          "exit_groups": 7,
          "origin_keys": [
            "5f1d966868dae1486ef8e990577d73ce8cf418df01653600b247d5cce6288e80",
            "24fb834f157eff38c9157f7c14f06d7d47dd5b20d089f2c18af7cf0592d9e770",
            "72ddb56d93eb92d9f5fb7770ff706a353ca8761886154fe2a0bb99d61a478566",
            "2a8f6ff3e67ea9e2d608ddd0b78133dc5a8256b8e774fdf3fa45078e30ebd590",
            "a9fae7f9c6cf0ee291c887ee0069923484772b48d31b0411e43fb8ef29e5b823",
            "66c69d6757c9a3e68f432bf73370c73d1b2c985878965e9071a827d5d3891374",
            "298c92b904c53ab9052c8fd807bcbb58ba4aa9fe4c7a733df2b4887cd99df27d",
            "9c07f8a0239c528fe1435c96a3e411486164230c14e6cb29d6706c73eaf4895b",
            "b2bd7cef923eb95c993904c89416b65911f195109c7b4be739bd4b4280e2e00d",
            "f012d5a4e63d8d32a6d79066a02e6a2e4f89f736d25d22e099ab00511fddaf8e",
            "fb6eb627109c938f5424884a1ac1eab6b2bac0bb00ca8ca41c8c2b9bdbcb284d",
            "211014fd485d2bb93f6d02ca81fe9adde961fa6063bade04ed3900f42f478e6f"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1749772800000,
          "end_exit_ms": 1750147200000,
          "exit_groups": 2,
          "origin_keys": [
            "debfdc41dcd631bdb45d97b217275e99db314aa88ff4b2c93bcddfa795befda0",
            "d96cfe80aedbf3b914ed0ee9b4d718b07c49a0f303e29aebb7ee29113bab48a4"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1750233600000,
          "end_exit_ms": 1751990400000,
          "exit_groups": 9,
          "origin_keys": [
            "e6b471833bc1f03e703b77424cec247cfea6d4c37a207cc3f66b5108b071591f",
            "44b3b744b06a48222f013ca383bd64ba79d59a8fe24cd3bbae77c83600091b3e",
            "999da21c5d14a7a72e0a0daf703a6d9ba659e741ffa15d350734dec3c0346186",
            "afd11c6598758e778f56bacbf350cec3d92c93cee2789b8c1a2223f024465f29",
            "a01c6e3e26ad708c68aac4b74a4f9b089e5eb2d68d08e5a07916f49c0f0dc393",
            "2124966535b29ec4bc7eda4a270b3ba9b3fce2e266e9b18cb7f7c0e7e3545251",
            "4a9f85a08e83bf75d783dba3ba621f9697fbeb4d1891853aa9cede5deec7b3cc",
            "9ddfa98891219f995aa8fbe370265a5defb759b1c5fe243dfabb69e8c6925018",
            "bc45907d673b342b71c4f4c9da9ddbf0b4381095d6675cc3500223162ec5e24f",
            "4b6b20cda754238e38542beab975451845c696a0121db5c143e452871d396885",
            "674b59f6e53d9364934f579fc7e03782f915af83cfd57acceef8c2c67b6a68b3",
            "7eb2694e88ff843fad724b3975dd1f865c4ad6639134604e74977a22df69aae5",
            "f1188fb315936f4cac7982674e6579dea7940fc62e82f9c2798a637959210c5b",
            "a1affbf9531dd7eb95cbfdf521599945fce29d303aae044e7b20ce50b1621bc4",
            "61bbb944677c3b495ecf6fba86e4070d22d77cb85041a9ead0b8d21ccb7e06e1",
            "956fb5d55ad1f8525407a55d326c053ed226a993614ae5ad5a048e63fdd163de"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1752163200000,
          "end_exit_ms": 1752350400000,
          "exit_groups": 3,
          "origin_keys": [
            "03a8cf7ebd7c7fe24dabcbddc0f35f7908b87720d7515e0f917cde5501206bd9",
            "e34fc457e6f4affa6e04c50a02bb8fa34b0e1c2cd2d1275c655f27d3f7cd36f9",
            "f66015881e736f3438560c96faa25fe59ec5ca302ebf35562b27fc6a36bcc806",
            "ca29aca9e31539d520fe60c926fd74103a505bc5118c4f36916726e990583499",
            "0069d95e46cacc01205d6fb1e8795583ee08b5da74cc9b98d0515b63cdbe3da8",
            "ae88c1165e492084ffe082a97d0f79f62eeb08926fa665189ec0e6bb3fe8a5b6"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1752364800000,
          "end_exit_ms": 1752364800000,
          "exit_groups": 1,
          "origin_keys": [
            "777fcadc0af593c92212c0102e0165c28dfe802a9fef2b579de02c29ae0b5d2b",
            "fc803a2a8372e7035163a7e843dff7418b9e257cff312c331e02d98455b58cb0"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1752436800000,
          "end_exit_ms": 1752436800000,
          "exit_groups": 1,
          "origin_keys": [
            "196502b0ff8eebc249c1d2f90e034d643f8d49d1c26096bc58f5c934211ed574",
            "58213b5de1f2e9b1d6073bffac710d0cd4b17c4b4ac6285c753e76b014f407f6"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1752638400000,
          "end_exit_ms": 1752638400000,
          "exit_groups": 1,
          "origin_keys": [
            "1fdea7992968cb96805255ab0da46bd4037bc38042823e462e08957ad7830c2a",
            "67a6d1ec1b5e63ee4a0bdaaecaeea68f1cda8a8ed121c27cb1966975e9c25254",
            "959cda7c6f8ac04cb09008e2d59d6358caffabb19c081ac624603dac087a0951",
            "993b0a24bb6a44769d3507beb49d6af3901089d22623cf1e22209ed501f953a1"
          ]
        },
        {
          "cohort_id": 25,
          "sign": 1,
          "start_exit_ms": 1752811200000,
          "end_exit_ms": 1752811200000,
          "exit_groups": 1,
          "origin_keys": [
            "40435df132fb643dfaae44cb14a00fc363ddb393cf23aafc39b63e67771c09aa"
          ]
        },
        {
          "cohort_id": 26,
          "sign": -1,
          "start_exit_ms": 1752868800000,
          "end_exit_ms": 1752868800000,
          "exit_groups": 1,
          "origin_keys": [
            "67f4cd0fc1936a7dbb16cc49bed8e2b59ae2068b693f1908d793fa46766b9ac4"
          ]
        },
        {
          "cohort_id": 27,
          "sign": 1,
          "start_exit_ms": 1752998400000,
          "end_exit_ms": 1753128000000,
          "exit_groups": 3,
          "origin_keys": [
            "7cd2460eacda79c66ab2164119954954f233273268a16ea28e0a901cc21450a5",
            "f8bc01bb783b3fb83cef6d79640690cf4ecbfb21024219d6f476162cff793924",
            "c2b0e8fda7b3a6e9f5f83d383ea671450616049414ea56aa758857e22b7b743f"
          ]
        },
        {
          "cohort_id": 28,
          "sign": -1,
          "start_exit_ms": 1753185600000,
          "end_exit_ms": 1753257600000,
          "exit_groups": 3,
          "origin_keys": [
            "74247b7404aaf99d7c7a1ac595a4d669072283581d2a58e0fc153b10f2738bef",
            "7eb9ecd015150253ce74d7931f6bad9c6ee03c58628fd420e0acd97d53af7670",
            "a601c4f6ad76a9ac57bbdfcee25d42261d7b7e6dc9c81bb546240caa7f9b3f99",
            "f4f1cfea996b341497abdddbe8178f4623925cfa3cfe1507c41fc30d7c5862fc"
          ]
        },
        {
          "cohort_id": 29,
          "sign": 1,
          "start_exit_ms": 1753286400000,
          "end_exit_ms": 1753286400000,
          "exit_groups": 1,
          "origin_keys": [
            "375ef3c0a0acf7a90f2848b309ef4b879ba8d62b2ea676f47a8bde0b9428220f"
          ]
        },
        {
          "cohort_id": 30,
          "sign": -1,
          "start_exit_ms": 1753401600000,
          "end_exit_ms": 1753401600000,
          "exit_groups": 1,
          "origin_keys": [
            "390b535ebacdef6f444c0051375eb4a7bb127ef59a19beda00fbe240759f18e1",
            "3eccc7caa793374e3a990df34735dcd393b6af2f92bef4340924216f30aeb3ab",
            "4c3d83a7bd8ea05433771fdbcefe60ed58b6b7d56bfe52761e63f006724df973",
            "5756bd3cfee17e430aeffe6a89d7156664677d7bb4417cf91be8f7e52a4c7bf2"
          ]
        },
        {
          "cohort_id": 31,
          "sign": 1,
          "start_exit_ms": 1753718400000,
          "end_exit_ms": 1753790400000,
          "exit_groups": 3,
          "origin_keys": [
            "0d713ab59f630f6fa5c06cd16c8e7744f3c81f0cb3ec875817a31296c077edc5",
            "20bb1470728ee9254f06093628659ea2b5af44a9f34b6af61a5172c7530841cb",
            "e437cc2930018e569ae9af01908521bae3dd8e02b2af85c705467580d8079fa0"
          ]
        },
        {
          "cohort_id": 32,
          "sign": -1,
          "start_exit_ms": 1753848000000,
          "end_exit_ms": 1754092800000,
          "exit_groups": 3,
          "origin_keys": [
            "cbf8b6632d4c9763e9e33ebcc7cc68babc1af7f31308e56d039a661a066a7deb",
            "e0ac6d207edd82993f1871ee47e8f8c282ac31abe6c8749d5df8a9d18ffb623f",
            "e25b42fc5f5759fa390f4680a89bb7266b6211db3746122aa6502f73512be9b2"
          ]
        },
        {
          "cohort_id": 33,
          "sign": 1,
          "start_exit_ms": 1754568000000,
          "end_exit_ms": 1754956800000,
          "exit_groups": 3,
          "origin_keys": [
            "efcb7bbcfa308dce9c4b5d722378dbb8cbaebc708a133395d3edda783280bf47",
            "36c90aa9676fc1aee9b7ce15aa8b40fbd96021c9ef4cecaf1154969e784e352b",
            "974ae22c35e58ca3d74a6bf20ec4ba93e0954faffac671cc862a4fd29bafe035",
            "c24510e0d1301807f86a66f72ffa7b1fe08c10df6bdec17c2f6bac8e0f3a52f5",
            "cb4a42dd44255cdd00147cc139ac069ecfba1d4533d608f54b6e83e4a206187c"
          ]
        },
        {
          "cohort_id": 34,
          "sign": -1,
          "start_exit_ms": 1754971200000,
          "end_exit_ms": 1755187200000,
          "exit_groups": 3,
          "origin_keys": [
            "1eede4413485a29011e94ac90bb816b5a7604b149269d30beba81f632c384e7b",
            "a1cebd837243dbc0e7d1a2ea31dda21ee34004661b215111c90709d2a4921db2",
            "a597ad625acc8bf173e0636249e11feb850fb54bdb20b67030b2803c69e0791e",
            "16fffec8d82bdae63cc92c66487a76741ef6934576c903510c5b01dce3f464b1",
            "1f8e40a87e8de06986f539bf59b5a6110703adbdcb6bac7608931ee25d7066a6",
            "3e69d5d0c7cb16da22ee34f8e178b6c7b15711e77808001ff7394e810c0d8be1"
          ]
        },
        {
          "cohort_id": 35,
          "sign": 1,
          "start_exit_ms": 1755201600000,
          "end_exit_ms": 1755201600000,
          "exit_groups": 1,
          "origin_keys": [
            "318f96df37fbd1cc371db55c24d8b303dd1478700fcf00acd07b6d8b39001643",
            "8e580e01821f21117f91d09febf0fb2d907d3456eb5fa5e76cb25823fd2c3ba0",
            "dd7fcd1b2c77b82633b47e78c91d8a4017ab90984f62e3555fd68e1ee3a35bd5"
          ]
        },
        {
          "cohort_id": 36,
          "sign": -1,
          "start_exit_ms": 1755288000000,
          "end_exit_ms": 1755403200000,
          "exit_groups": 2,
          "origin_keys": [
            "68dca5fddb95097bab6a1e4460184cd0868b369f38ebab22df8cc01dcd926d4a",
            "0ad0234311a4e8c25415fc1ad482405883729dd6d68cab3144cf826cf851333f"
          ]
        },
        {
          "cohort_id": 37,
          "sign": 1,
          "start_exit_ms": 1755576000000,
          "end_exit_ms": 1755576000000,
          "exit_groups": 1,
          "origin_keys": [
            "94e92b37c105f84cce916c08f2a74fdb93e69a31412d1730c38a4188023ee67d"
          ]
        },
        {
          "cohort_id": 38,
          "sign": -1,
          "start_exit_ms": 1756051200000,
          "end_exit_ms": 1756108800000,
          "exit_groups": 3,
          "origin_keys": [
            "29c33258341a60807ae85b4385595159380f696778b8a4d3e5c5ce65ca134ff4",
            "b2960577c4efbc08c2ae23b147253cb3a412cf45adffea6da406bf32928c3f86",
            "807e3e0eef96b49f108ee548aee365d65427171400e9aea4faf060c9787901b2"
          ]
        },
        {
          "cohort_id": 39,
          "sign": 1,
          "start_exit_ms": 1756339200000,
          "end_exit_ms": 1756339200000,
          "exit_groups": 1,
          "origin_keys": [
            "54d346e1674786f6884253e0782a678caae60c7a7be096481458d4b1dc19fc60"
          ]
        },
        {
          "cohort_id": 40,
          "sign": -1,
          "start_exit_ms": 1756396800000,
          "end_exit_ms": 1756396800000,
          "exit_groups": 1,
          "origin_keys": [
            "0474adeaa45f0a3c9b6c37fda12997d6e0e3b5ee5668b106988655979dfde008"
          ]
        },
        {
          "cohort_id": 41,
          "sign": 1,
          "start_exit_ms": 1756483200000,
          "end_exit_ms": 1757001600000,
          "exit_groups": 2,
          "origin_keys": [
            "838e3b9c70a6cde0911f04ba486c6d02572bfe2cf053f0a368ae84dd6552318a",
            "980985667838896c62be7ec6ff8848aedde385cc901c6b4496d51f02451be388"
          ]
        },
        {
          "cohort_id": 42,
          "sign": -1,
          "start_exit_ms": 1757059200000,
          "end_exit_ms": 1757059200000,
          "exit_groups": 1,
          "origin_keys": [
            "aecee466bd1bd35fb0aa606060dc265b5ad39117634cf4f6f0642c55c39c43b6"
          ]
        },
        {
          "cohort_id": 43,
          "sign": 1,
          "start_exit_ms": 1757203200000,
          "end_exit_ms": 1757203200000,
          "exit_groups": 1,
          "origin_keys": [
            "9b631f7c648a600ea1a8ab1c011d53f4babab0dadfeb7fcdc0f1a4d51b44a1c2"
          ]
        },
        {
          "cohort_id": 44,
          "sign": -1,
          "start_exit_ms": 1757232000000,
          "end_exit_ms": 1757260800000,
          "exit_groups": 2,
          "origin_keys": [
            "12e461b2ad5a871e9aa1408be71d5f8fa60137a832cd6ed054910d34816e6900",
            "9b3b97aba3e8805652aa80b9ff4a28679377ce6d99e57f324f93973a6619b12c",
            "1c4d896c18cec0b41177004ea584872bd6aebc2ae41807778472cdff1737d545"
          ]
        },
        {
          "cohort_id": 45,
          "sign": 1,
          "start_exit_ms": 1757635200000,
          "end_exit_ms": 1757750400000,
          "exit_groups": 4,
          "origin_keys": [
            "ca29013e489859ae3bfc39ac02b1a7717709827d3750845019abcfad90bbc993",
            "8ccf205363405a39c01b3a909b78eb8facff0a584f2d365367d5356d61fa6dc9",
            "837c63517826928efa736bfc0c4bb7484f4e487b11c125951f981ae34615724d",
            "ccefdb9c39b9933be1e1f0bc7e0694732d646be741f5702e1476c04917a1b2d8"
          ]
        },
        {
          "cohort_id": 46,
          "sign": -1,
          "start_exit_ms": 1757822400000,
          "end_exit_ms": 1757822400000,
          "exit_groups": 1,
          "origin_keys": [
            "e5cd67168b064e5e8e10b404b141dd39b00f9623578a6786c8c95c4e595f5e6e"
          ]
        },
        {
          "cohort_id": 47,
          "sign": 1,
          "start_exit_ms": 1757851200000,
          "end_exit_ms": 1757851200000,
          "exit_groups": 1,
          "origin_keys": [
            "0778c9a9f2e7b6cdf5b9751677f85255be56ad215b031f2959e4f4281874419c"
          ]
        },
        {
          "cohort_id": 48,
          "sign": -1,
          "start_exit_ms": 1757880000000,
          "end_exit_ms": 1757880000000,
          "exit_groups": 1,
          "origin_keys": [
            "2e839b4d5a5191520e9f91de94f90b382a9df0e040f816cca19db00ffbb71734",
            "f6a231258befaa6ff761959359f8990b3d07d6798a15f9e26fb16b3c457ac3d8"
          ]
        },
        {
          "cohort_id": 49,
          "sign": 1,
          "start_exit_ms": 1757923200000,
          "end_exit_ms": 1757923200000,
          "exit_groups": 1,
          "origin_keys": [
            "77e713681d08d3c9c08c27ca53b34ca4e3dc0a731b1bc8eaa395ef95cabc77ee"
          ]
        },
        {
          "cohort_id": 50,
          "sign": -1,
          "start_exit_ms": 1758067200000,
          "end_exit_ms": 1758067200000,
          "exit_groups": 1,
          "origin_keys": [
            "c420a761f46e27f3cf8582dbfae714b92e6feda361c9d3ffec0fd93b558186fe"
          ]
        },
        {
          "cohort_id": 51,
          "sign": 1,
          "start_exit_ms": 1758268800000,
          "end_exit_ms": 1758283200000,
          "exit_groups": 2,
          "origin_keys": [
            "20ea91371273223dc52ed00d385e68db8c0ae87a809d79757331e6d3090b007a",
            "4d43157978d87b00a52366fa3ba3e3abe8a5bd1bc31a8172d35710bc83e3f0f8",
            "77f599550ff733390fba5ee2b80724bc7eab334b4b6bdc31c7525780dcc099d1",
            "c1cc98b02a832eac9ca1be0b697e5a5a222c000b30a627f5a5fb1aa98a0a5c45"
          ]
        },
        {
          "cohort_id": 52,
          "sign": -1,
          "start_exit_ms": 1758312000000,
          "end_exit_ms": 1761696000000,
          "exit_groups": 9,
          "origin_keys": [
            "8283fdde3c8107226b3a5848dab578373cdf19ef85537f31f87799a7fe24ae8a",
            "b5b71cb87e5492f1b71ce6c1eae60ef2f1eb4a0e7f18a6069e09173e99ae462d",
            "4492321f2cee38cb2494131551dace19e2720b72091546ba1472da70301a9de4",
            "57bdf3c019df9e59b76f8571bbed36dd460b113f31ca27d19036cb076f5f24fe",
            "8c0762ebc291bf119a319ba583d06472b8c5eaee6443434019ef28d54167072d",
            "96a9264307b892a32e55c4fbac4abaefa762676c2b7a74e9761cb6543e588b3f",
            "9c92932ba963ea7d68119564fd74e79028a1d3cc69fe64844adc450fb5a1ebac",
            "4a11ccf2fd7a26ae06ccda885fa02c1fdea8137a69866e07450e625ed0ca6ec2",
            "047259e84f46fc2b383231d68d0ea27ea1936d13d0d30aed610683a8fae55958",
            "9d5a7a71b401d885f199d8f12825aae2cd2aabba00810f5529ecb4940ff1b4ea",
            "1302a5f18a066e312a29221a30b42f0053dda58078ff136d7370c5e4f2287454",
            "551154175efb98da665fa3195b4949bb77249993a29bc8fc3005bb01f554fbf7",
            "9fed38bbaaff3f420cc0091e591df224ca52a792e6a000065f2a2ad082c33862",
            "7283101e4fdcece1ffab8633279b7529d5061a4a0692a2832242d050efd60748",
            "098bafbe4f784e62a9587047efa0cb2e7eff95b7bdabb0646a3d517895fe90d1",
            "2a6ce18ac5e3271673d105c8c41041d03ef6d98df3569ed81c0aa708044ac981",
            "46dfa0fbb37dd28c73050787e55c5ed8cdc236c2c990e28c5ff7baadf0c43584",
            "86d26a1d53c9e35900268b0b33376904bb329dba5314a4631f5d001bb5ad864d",
            "c232b9281ddee92893511f7ea9bc436d5fcb94f299db351f98035809305f3aa5",
            "d4c3fa0e1765b94e30384d07523c6afbf8d90e2929c199a21bc6653cf7c4dabb"
          ]
        },
        {
          "cohort_id": 53,
          "sign": 1,
          "start_exit_ms": 1761753600000,
          "end_exit_ms": 1761768000000,
          "exit_groups": 2,
          "origin_keys": [
            "7781fbc0c1822b713dbec25e6ae7934d19047408dc9c37dde793c90301168799",
            "512073d6d9c936fd66d4fcd6f3a89ae9dea297b30f75bb5e691d0b9a3b821609"
          ]
        },
        {
          "cohort_id": 54,
          "sign": -1,
          "start_exit_ms": 1761897600000,
          "end_exit_ms": 1764561600000,
          "exit_groups": 8,
          "origin_keys": [
            "8c7d6608fc4551c9fd58fa182511ae956e14be8607559185ea261fdd01405342",
            "03513bbe310acacf07e8ddf4cdc297acae4f996d820c5cc95d947966df39887a",
            "c598caa805b352c9132d483559991979d149d3be4b8070add0b23db9958dc084",
            "d7e12a8918433812eb1d76d25a1cc291e10f70b6dda9597272660472d17bf9a3",
            "7f0f61a186927f45a5af2b84b2df34ee3c35778bab04a6d0a48ccebfeda92f3f",
            "2c2cd49704e4b55a885236ee5aad7777682324875b8c85faa2bf2470717998f1",
            "057dc5c71a9d6657005793a597771143480f391bb64ac8e6911b58b171bf6a0d",
            "f9193759bc56d2fffdcaeaf63b1c67f78a936c9363ae739e58675073fd0c356e"
          ]
        },
        {
          "cohort_id": 55,
          "sign": 1,
          "start_exit_ms": 1764691200000,
          "end_exit_ms": 1764964800000,
          "exit_groups": 2,
          "origin_keys": [
            "d206da52a9157e6d3145e8b42b534f45fdcea6e93a58f3f6a337c9f36cfaa390",
            "f250107b3756435d9d35e11671f93414fc7a1fcb61d559e9f8cfa7a844c2ffa5"
          ]
        },
        {
          "cohort_id": 56,
          "sign": -1,
          "start_exit_ms": 1765224000000,
          "end_exit_ms": 1765382400000,
          "exit_groups": 2,
          "origin_keys": [
            "69e1d65ac318192e8d2f8b12d8e13c3e0664129bfb4b402963261838be36b162",
            "a3b10b6d6ebde38b24761e4e03f3bf0c050b3f3bd71450d1642f48c832fe5d6a"
          ]
        },
        {
          "cohort_id": 57,
          "sign": 1,
          "start_exit_ms": 1765425600000,
          "end_exit_ms": 1765425600000,
          "exit_groups": 1,
          "origin_keys": [
            "54761f9d39a4ab91f4e6b7419a2861725cd5491c1af0bc34cc67801693a4cc1d"
          ]
        },
        {
          "cohort_id": 58,
          "sign": -1,
          "start_exit_ms": 1765468800000,
          "end_exit_ms": 1766577600000,
          "exit_groups": 4,
          "origin_keys": [
            "342addde20daf77d48a6f419f3e0ad39039f2d29c11f485862a77057e3facd1e",
            "517acc6538a9113077851244e126cc6f7becd8d71b0a28b055219133a0f6eeac",
            "d7ff6b20486a8dea69485aca40475038fa5f9d1854cb5dc5682a699c4c38bb3c",
            "c849b92b7ae7adbb73d72d938c122ccb1a24c14ceb6b3cf391d4751a8d5e69bb",
            "d50d4d75abf47a72631022cfab141b268f3bd8923cd95b61246bac32226cc9b8",
            "bcae1d3b355e9893b9699ab6272f3fa25019c195a6753c78674c75e621513b30"
          ]
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
## SEEN2026

| Metric | P | FIXED | FULL |
|---|---:|---:|---:|
| closed_T | 84.000000 | 84.000000 | 74.000000 |
| open_T | 5.000000 | 5.000000 | 5.000000 |
| entries_T | 89.000000 | 89.000000 | 79.000000 |
| win_rate | 0.464286 | 0.404762 | 0.405405 |
| PF | 1.425121 | 1.661096 | 1.828314 |
| mean_win_bps | 588.008830 | 800.088823 | 852.472066 |
| mean_loss_bps | -357.589163 | -327.530908 | -317.905451 |
| realized_payoff | 1.644370 | 2.442789 | 2.681527 |
| net_expectancy_bps_per_closed_trade | 81.438477 | 128.886602 | 156.571921 |
| closed_gross_bps | 8637.543001 | 12801.334450 | 13340.537866 |
| closed_net_bps | 6840.832038 | 10826.474563 | 11586.322141 |
| closed_cost2x_net_bps | 5044.121076 | 8851.614676 | 9832.106416 |
| closed_cost_bps | 1796.710962 | 1974.859887 | 1754.215725 |
| closed_fee_bps | 840.000000 | 840.000000 | 740.000000 |
| closed_funding_bps | 606.900000 | 803.030000 | 718.370000 |
| terminal_net_bps_hypothetical | 5838.397371 | 9824.039895 | 10583.887473 |
| terminal_cost2x_net_bps_hypothetical | 3941.686408 | 7749.180008 | 8729.671748 |
| open_net_mark_bps_hypothetical | -1002.434668 | -1002.434668 | -1002.434668 |
| marked_DD_trade_sum_bps | 5347.546184 | 6723.070231 | 4890.463425 |
| grouped_max_loss_trade_sum_bps | 2678.010825 | 2627.810282 | 2412.741167 |
| exposure_symbol_days | 174.666667 | 231.333333 | 206.333333 |
| max_simultaneous_symbols | 7.000000 | 7.000000 | 7.000000 |
| entries_per_30_days | 22.250000 | 22.250000 | 19.750000 |
| max_completed_recovery_days | 79.000000 | 80.000000 | 79.000000 |
| open_underwater_days | 14.000000 | 14.000000 | 14.000000 |

Decisions: {"FIXED": "TRADEOFF", "FULL": "TRADEOFF"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "P": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 4702.994865358261,
        "net_bps": 4745.4901025405225,
        "cost2x_net_bps": 4787.9853397227835,
        "cost_bps": -42.495237182261306,
        "fee_bps": -100.0,
        "spread_bps": -12.9841618444682,
        "impact_bps": -20.0,
        "slippage_bps": 0.0,
        "funding_bps": 111.47,
        "frozen_floor_reserve_bps": -20.981075337793108
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 5,
          "delta_bps": {
            "gross_bps": -498.16289797229075,
            "net_bps": -616.0532748843176,
            "cost2x_net_bps": -733.9436517963444,
            "cost_bps": 117.89037691202682,
            "fee_bps": 50.0,
            "spread_bps": 7.9841618444682,
            "impact_bps": 10.0,
            "slippage_bps": 0.0,
            "funding_bps": 49.510000000000005,
            "frozen_floor_reserve_bps": 0.39621506755862157
          }
        },
        "C_ABSENT": {
          "T": 15,
          "delta_bps": {
            "gross_bps": 955.3109002095639,
            "net_bps": 1265.3716540336177,
            "cost2x_net_bps": 1575.4324078576713,
            "cost_bps": -310.0607538240536,
            "fee_bps": -150.0,
            "spread_bps": -20.9683236889364,
            "impact_bps": -30.0,
            "slippage_bps": 0.0,
            "funding_bps": -102.30000000000001,
            "frozen_floor_reserve_bps": -6.792430135117243
          }
        },
        "C_C": {
          "T": 69,
          "delta_bps": {
            "gross_bps": 4245.846863120988,
            "net_bps": 4096.171723391222,
            "cost2x_net_bps": 3946.4965836614565,
            "cost_bps": 149.67513972976553,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 164.26,
            "frozen_floor_reserve_bps": -14.584860270234486
          }
        },
        "O_O": {
          "T": 5,
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
        "T": 35,
        "parent_positive_bps": 13399.037810260763,
        "child_signed_terminal_bps": 14548.538918027572,
        "capped_terminal_preserved_bps_hypothetical": 8315.841316339478,
        "capped_terminal_retention_hypothetical": 0.6206297373063119,
        "realized_capped_retention_lower": 0.6206297373063119,
        "realized_capped_retention_upper": 0.6206297373063119,
        "profit_cut_bps": 5083.196493921285,
        "additional_loss_after_winner_bps": 281.954081106993,
        "signed_winner_deterioration_bps": 5365.150575028278,
        "winner_to_loss_T": 6,
        "winner_removed_T": 4,
        "winner_to_loss_origins": [
          "0dea81d8d3a9b335c32934ebe69a654e01e392dcf9ece2203c5184d5eaa158aa",
          "29f9ee8a37632b1d904842e0168f0381b5568d482898555e202c1b902aac39c4",
          "5a479c429a6576a94de9081765f8e06f777fd7f0a067d292fe6467a621d0ec0b",
          "6134cb9684d19748bccac5cfa9a75edc43133eace617fc910f3466e827946d57",
          "79c332d7d2a2eadf8cfd56427345481a09ffb3624cdf28d54f1e7188f4fffa46",
          "baff33edbdc7207e002ebdb1638982c4e35bb5580da1459324878f9faac02043"
        ]
      },
      "large_winners": {
        "T": 4,
        "parent_positive_bps": 9533.306558912971,
        "child_signed_terminal_bps": 10633.072124557099,
        "capped_terminal_preserved_bps_hypothetical": 9466.965832422968,
        "capped_terminal_retention_hypothetical": 0.9930411629920807,
        "realized_capped_retention_lower": 0.9930411629920807,
        "realized_capped_retention_upper": 0.9930411629920807,
        "profit_cut_bps": 66.34072649000336,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 66.34072649000336,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "37709b9f7edb53c1d5942eaf3c989a507b72c6d0a8aa08135a1320da3702a14d",
        "symbol": "HYPE-USDT",
        "signal_ts": 1779048000000,
        "entry_month": "2026-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 438.8426034996029,
          "net_bps": 417.3826034996029,
          "cost2x_net_bps": 395.9226034996029,
          "cost_bps": 21.46,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 8.46,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 2387.826347690134,
          "net_bps": 2357.9063476901338,
          "cost2x_net_bps": 2327.9863476901337,
          "cost_bps": 29.92,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 16.92,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 1948.983744190531,
          "net_bps": 1940.5237441905308,
          "cost2x_net_bps": 1932.0637441905308,
          "cost_bps": 8.46,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 8.46,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": false,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 172800000,
        "child_hold_ms": 345600000
      },
      "net_increment_without_largest_positive": 2804.9663583499914,
      "largest_positive_share_of_net_increment": 0.40891956410396085,
      "increment_by_symbol": {
        "BCH-USDT": 405.58846159259144,
        "SOL-USDT": 727.9341744954631,
        "1000PEPE-USDT": 36.082843867540134,
        "BTC-USDT": 541.2051419046436,
        "LINK-USDT": 229.03996995990684,
        "HYPE-USDT": 2573.5240563330235,
        "ETH-USDT": 232.1154543873536
      },
      "increment_by_entry_month": {
        "2026-08": 4255.33458889616,
        "2026-09": 0.0,
        "2026-07": -428.69282015819107,
        "2026-06": 723.3381083132426,
        "2026-05": 195.5102254893095
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
      "fixed_path_or_filter_effect": 4163.791449419338,
      "full_occupancy_remainder": 539.2034159389223,
      "full_total_effect": 4702.9948653582605
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 3985.6425247571306,
      "full_occupancy_remainder": 759.8475777833919,
      "full_total_effect": 4745.4901025405225
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 3807.4936000949247,
      "full_occupancy_remainder": 980.4917396278588,
      "full_total_effect": 4787.9853397227835
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 178.14892466220704,
      "full_occupancy_remainder": -220.6441618444685,
      "full_total_effect": -42.49523718226146
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -100.0,
      "full_total_effect": -100.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -12.98416184446819,
      "full_total_effect": -12.98416184446819
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -20.0,
      "full_total_effect": -20.0
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 196.1300000000001,
      "full_occupancy_remainder": -84.66000000000008,
      "full_total_effect": 111.47000000000003
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -17.981075337793108,
      "full_occupancy_remainder": -3.0,
      "full_total_effect": -20.981075337793108
    }
  },
  "uncertainty": {
    "FIXED": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 120,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 4.0,
      "N_effective": null,
      "calendar_start": "2026-05-08",
      "calendar_last_day": "2026-09-04",
      "parent_marked_delta_sum_bps": 5838.397370519645,
      "child_marked_delta_sum_bps": 9824.039895276775,
      "child_minus_parent_marked_delta_sum_bps": 3985.6425247571315,
      "child_minus_parent_mean_daily_bps": 33.21368770630943,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -31.302637617467912,
        81.41834107807813
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -3756.3165140961496,
        9770.200929369375
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    },
    "FULL": {
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "calendar_days": 120,
      "block_days": 30,
      "resamples": 1000,
      "seed": 1178,
      "approximate_calendar_blocks": 4.0,
      "N_effective": null,
      "calendar_start": "2026-05-08",
      "calendar_last_day": "2026-09-04",
      "parent_marked_delta_sum_bps": 5838.397370519645,
      "child_marked_delta_sum_bps": 10583.88747306017,
      "child_minus_parent_marked_delta_sum_bps": 4745.490102540523,
      "child_minus_parent_mean_daily_bps": 39.54575085450436,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -12.518151928081314,
        88.77719191468583
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1502.1782313697577,
        10653.2630297623
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
          "1000PEPE-USDT": 541.5105385625419,
          "BCH-USDT": 1370.0175307023815,
          "BTC-USDT": 862.3441574490668,
          "ETH-USDT": 1132.282825853708,
          "HYPE-USDT": 425.409362416362,
          "LINK-USDT": 1664.1480350766678,
          "SOL-USDT": 845.1195881406095
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 3303.8567760393275,
          "BCH-USDT": 3484.719955800813,
          "BTC-USDT": 1454.7151844966934,
          "ETH-USDT": 2470.645193390271,
          "HYPE-USDT": 5885.1590729322215,
          "LINK-USDT": 3255.5287314927978,
          "SOL-USDT": 3077.719455021611
        },
        "total_positive_trade_profit_bps": 22932.344369173734,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.25663137523973384,
        "winner_T": 39,
        "top_decile_winner_T": 4,
        "top_decile_winners_share": 0.4157144339646275,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 335.27307728468224,
          "2026-06": -4023.771989244373,
          "2026-07": 134.31914223260938,
          "2026-08": 10395.011807928418,
          "2026-09": 0
        },
        "top_positive_month_share": 0.9567777879128381
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1777852800000,
          "T": 2,
          "net_trade_sum_bps": 834.9197685161303
        },
        {
          "utc_monday_ms": 1778457600000,
          "T": 6,
          "net_trade_sum_bps": -2678.0108249465234
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 2,
          "net_trade_sum_bps": 1657.397630728483
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 2,
          "net_trade_sum_bps": 520.9665029865926
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 2,
          "net_trade_sum_bps": -1778.4509019853704
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 7,
          "net_trade_sum_bps": -1379.0228882627162
        },
        {
          "utc_monday_ms": 1782086400000,
          "T": 3,
          "net_trade_sum_bps": -866.298198996286
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 4,
          "net_trade_sum_bps": 1453.8491528511363
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 14,
          "net_trade_sum_bps": -683.2489492774687
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 4,
          "net_trade_sum_bps": -211.0028882008602
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 6,
          "net_trade_sum_bps": -158.46120574367777
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 2,
          "net_trade_sum_bps": -266.81696739652034
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 3,
          "net_trade_sum_bps": -517.473904562299
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 5,
          "net_trade_sum_bps": 572.69981989658
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 11,
          "net_trade_sum_bps": 12866.560782729342
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 11,
          "net_trade_sum_bps": -2526.7748901352047
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": 1,
          "start_exit_ms": 1778443200000,
          "end_exit_ms": 1778443200000,
          "exit_groups": 1,
          "origin_keys": [
            "3704af8874f5d479cae7c24c5e0570797dc3fc675fd5a9798c42bdadc6d58399",
            "e6f531e30771998b2b702b2366698ed231120fb87b2cf788600d29b08686fa98"
          ]
        },
        {
          "cohort_id": 1,
          "sign": -1,
          "start_exit_ms": 1778472000000,
          "end_exit_ms": 1778947200000,
          "exit_groups": 5,
          "origin_keys": [
            "af3e4bfe171ccff587124eb44124d9d6bf80e7c05351fbd2473fc910a5d14178",
            "20813582cd090f2e7c1d87d5a066c0f36f555e67f708eddcf03f1b54c02535e6",
            "e26e5ab7aa230b7fc5f798e3617b5dc155b2cf4d41f276352126a6c55a5f0bca",
            "ef6a9fd9f69ef1783edb036f8f946661089d30ef43afc0266fd767f1bf1850ea",
            "4ab3268feebf765b7a54119fa7c5016746133048811a0d1a78f5dc35994c293f",
            "e69a9771939170a09a3548b2322e29688c48b62ffb21ae51d77e748328548654"
          ]
        },
        {
          "cohort_id": 2,
          "sign": 1,
          "start_exit_ms": 1779220800000,
          "end_exit_ms": 1780243200000,
          "exit_groups": 4,
          "origin_keys": [
            "37709b9f7edb53c1d5942eaf3c989a507b72c6d0a8aa08135a1320da3702a14d",
            "873878171bdf5318599f664188d8b146730ac6ffdc7d36c13e5c1e807266b3cb",
            "2b1a4ccc3af49f20ede7666ec761c16a84ba1db24a27eeef8eb64cafa582240b",
            "6d3652d6e9043817725a1217d09e373409da0efce7c5e076738ebce8ab145a61"
          ]
        },
        {
          "cohort_id": 3,
          "sign": -1,
          "start_exit_ms": 1780444800000,
          "end_exit_ms": 1780646400000,
          "exit_groups": 2,
          "origin_keys": [
            "a67a3abde224ea3e365f40489d635c913c6065b1182f2209e65e6ad754ca6b54",
            "1aeb48d618308f3e3e92108d83347b7399f8d3abe5638179df0b9a44bb0aebf8"
          ]
        },
        {
          "cohort_id": 4,
          "sign": 1,
          "start_exit_ms": 1781654400000,
          "end_exit_ms": 1781697600000,
          "exit_groups": 2,
          "origin_keys": [
            "2179e1375958574fe042f2de6f137ca0520f8e433bb6e583532ca4e4a216dae3",
            "5cddb7370750225638aa8bb54fe7ead45c8a86840b8a8c05271c20ccfeaae303",
            "6134cb9684d19748bccac5cfa9a75edc43133eace617fc910f3466e827946d57"
          ]
        },
        {
          "cohort_id": 5,
          "sign": -1,
          "start_exit_ms": 1781712000000,
          "end_exit_ms": 1781884800000,
          "exit_groups": 2,
          "origin_keys": [
            "194caca2c855cf2b63d291ea855a2053da379563b06fb082a6137aae163b72e5",
            "45d2532a3430b47c597fbdb486be9e2de86ba0f26b17021c6b0b385a3cb0f38d",
            "7285c3ddbb558ba0890fa25be6439e651533c94df35e294c245e0e67712c02de",
            "8a69431a588a543d87f8f8047792c4cc980558ed2f1aefe5048af8d022ed91be"
          ]
        },
        {
          "cohort_id": 6,
          "sign": 1,
          "start_exit_ms": 1782115200000,
          "end_exit_ms": 1782115200000,
          "exit_groups": 1,
          "origin_keys": [
            "92b587094c241be908ce0209308b08b14a17d7d50be5034bfb5a2e008a25479a"
          ]
        },
        {
          "cohort_id": 7,
          "sign": -1,
          "start_exit_ms": 1782273600000,
          "end_exit_ms": 1782288000000,
          "exit_groups": 2,
          "origin_keys": [
            "26048c789a194d64061bab864b1105c91c2ceab6bf664f0071606f65ca1b69a6",
            "5ee84b421772b58c19b7785d02049cc7496003e942cbbbdf0a0d83b30d3c92a2"
          ]
        },
        {
          "cohort_id": 8,
          "sign": 1,
          "start_exit_ms": 1782936000000,
          "end_exit_ms": 1783094400000,
          "exit_groups": 3,
          "origin_keys": [
            "f576eadd0586926750d4b2ba9bab812d4543a0a8d7266fe5289b0bcd6a7af631",
            "125e8c500f160245f58567c6e0edd312ac12389775b4df8fd8447ed88410f13f",
            "96df5996f53c9d8ea7fdba22dcd3f9db6b86ded69de3a63ac067a8264e71fc7c"
          ]
        },
        {
          "cohort_id": 9,
          "sign": -1,
          "start_exit_ms": 1783166400000,
          "end_exit_ms": 1783296000000,
          "exit_groups": 2,
          "origin_keys": [
            "c7f4ea10a0248e02cf832cb22160cb2a181c1d7e926840e45061a775006b514d",
            "944a89cf5ed854bf74c916a7d91db8745d621e932dd73fffcf11c29b5a2c1df3"
          ]
        },
        {
          "cohort_id": 10,
          "sign": 1,
          "start_exit_ms": 1783353600000,
          "end_exit_ms": 1783353600000,
          "exit_groups": 1,
          "origin_keys": [
            "1d2f8f7ac4072f80c85d02f7449b15305f2dfbdffc3c04242b3884ac8a4f5c3d",
            "3f6e146ee6498eab92e7a0d6d06ab32d295150f930b2040f3a43ea6104fe34ca",
            "eaa82ab5342448af2ff822854c4477a696978b456a120ce280809ba68049c736"
          ]
        },
        {
          "cohort_id": 11,
          "sign": -1,
          "start_exit_ms": 1783468800000,
          "end_exit_ms": 1783540800000,
          "exit_groups": 3,
          "origin_keys": [
            "d552e4f2d70df39b5c2fd9c9defb47260c7f15a2be84c2caec94d9a8d191e532",
            "f141054db9dedfa62ca7fdd3e335485305c6baeacf42a8a5c5d34a06a65c8e84",
            "5c2bf1d18074cc3dc5a4a3f30da0e27270de1ac71cc9444ccab2927f1f640457",
            "a05d6fca791250f923ca7afcd56b1f374470050c19b2ebc7221d1045468525a1"
          ]
        },
        {
          "cohort_id": 12,
          "sign": 1,
          "start_exit_ms": 1783756800000,
          "end_exit_ms": 1783828800000,
          "exit_groups": 2,
          "origin_keys": [
            "2509d55bbea92d6c81839b97406dc4ead8036204374dd8ed2f75c1771eaae9ff",
            "db6ff814f1a0d91a4a34cd791cd3e58b21d5027b65df980a04440404c44f38c9",
            "41c878f7e646078d7b6c963c2592502a326e67e3f03d1524ae6a06e6c21953a0",
            "673de9d391a117ea56eacfc621dc137a6474a26cb63b9797a49ed85c94011df3",
            "b8c568424e8e61e1176d5a115249e60b4fe441db021025f6c036d3320b2ba02b",
            "f593f3edfb441e31698b8a96d52ab6fc475b6b97c9a90feac26584cd1ce5e81f"
          ]
        },
        {
          "cohort_id": 13,
          "sign": -1,
          "start_exit_ms": 1784217600000,
          "end_exit_ms": 1784217600000,
          "exit_groups": 1,
          "origin_keys": [
            "29f9ee8a37632b1d904842e0168f0381b5568d482898555e202c1b902aac39c4",
            "5a479c429a6576a94de9081765f8e06f777fd7f0a067d292fe6467a621d0ec0b",
            "df0b266cf5959bc5e7c13d349b8936c290530cd923802c6d322428009386e5d3",
            "ff4007a1005a0cf952569865a987bbc3f8a3af122df9ba3f7d2e5483d00c2ecd"
          ]
        },
        {
          "cohort_id": 14,
          "sign": 1,
          "start_exit_ms": 1784620800000,
          "end_exit_ms": 1784721600000,
          "exit_groups": 2,
          "origin_keys": [
            "133bda43d00e393b07af2b26e0437dc95a6c74e748feb4417e46ba76b61b3410",
            "2dfb5ce585636b0d1a805bd7e085f44230bda07a8ca3772cd681e9445b8dcca6",
            "baff33edbdc7207e002ebdb1638982c4e35bb5580da1459324878f9faac02043",
            "fb14aa9de9df3d910cd6c26e0e04eb88a1348b592b21e475f9c57c2e16cb73b1"
          ]
        },
        {
          "cohort_id": 15,
          "sign": -1,
          "start_exit_ms": 1784908800000,
          "end_exit_ms": 1785254400000,
          "exit_groups": 3,
          "origin_keys": [
            "692743b67342cdda1f9c615d423dba0e005a6a115c4b33146387026ceb09ff40",
            "5808db5067623613cc00396591daa9290d508d6468e2204604203e67c5e42c4b",
            "6bbaef456336a13b6ea8cf94bdbc750234d3a2a6c60ef1c2a9329e6aa40ad107",
            "7f14e27ee7b6bbdc40a2814def65b35ca57763e0a9cc72110698a02e28246716"
          ]
        },
        {
          "cohort_id": 16,
          "sign": 1,
          "start_exit_ms": 1786132800000,
          "end_exit_ms": 1786132800000,
          "exit_groups": 1,
          "origin_keys": [
            "0dea81d8d3a9b335c32934ebe69a654e01e392dcf9ece2203c5184d5eaa158aa"
          ]
        },
        {
          "cohort_id": 17,
          "sign": -1,
          "start_exit_ms": 1786276800000,
          "end_exit_ms": 1786276800000,
          "exit_groups": 1,
          "origin_keys": [
            "4dbae6b3266761da3fd9e689bc7ba77cf5831b0ebe3264928e74a772777dcaea",
            "714a5290daf3f290b6468334a2c1a0b6f686e49288235a232bbddfaa51fecf8e"
          ]
        },
        {
          "cohort_id": 18,
          "sign": 1,
          "start_exit_ms": 1786363200000,
          "end_exit_ms": 1786363200000,
          "exit_groups": 1,
          "origin_keys": [
            "79c332d7d2a2eadf8cfd56427345481a09ffb3624cdf28d54f1e7188f4fffa46"
          ]
        },
        {
          "cohort_id": 19,
          "sign": -1,
          "start_exit_ms": 1786464000000,
          "end_exit_ms": 1786478400000,
          "exit_groups": 2,
          "origin_keys": [
            "184ff514ca18c74952359c225d55a9fefa53449d4b9af844a4a0d67256bf7215",
            "20bce44d1b740e5f42b908329dce30e29c1855b15e989268a30810b6a2264890"
          ]
        },
        {
          "cohort_id": 20,
          "sign": 1,
          "start_exit_ms": 1786536000000,
          "end_exit_ms": 1786924800000,
          "exit_groups": 3,
          "origin_keys": [
            "f1013b06b2481cdf9c40af548714b09cb74cabf65a79ecedca9445e3269dd42a",
            "90a22f448a6144e6f23c7053b7dc9f68e83d612cd89f1028758f4966208158e9",
            "e48a6f7f81291c57574aaa67b384d6e455477b874cc5947ffd846748b465f43a"
          ]
        },
        {
          "cohort_id": 21,
          "sign": -1,
          "start_exit_ms": 1787112000000,
          "end_exit_ms": 1787112000000,
          "exit_groups": 1,
          "origin_keys": [
            "4b8cac18a488885b058fa5d2951112e88aa5fb478371a4792f6b0048030e8cce"
          ]
        },
        {
          "cohort_id": 22,
          "sign": 1,
          "start_exit_ms": 1787212800000,
          "end_exit_ms": 1787414400000,
          "exit_groups": 6,
          "origin_keys": [
            "4f729d69de9b8cbb7eb9e147fbac46ebccfe17a1fce84686555619f4963f7869",
            "abef2e2e44ebaf18fbe7cd5767a7a20d5ae4c65c504ee3d3a29ebf6b05005e9b",
            "c99e6b9a6a6e34dce2cac1e17592a05951d48bf5d0e59135e1aa3c2a34f6cf4e",
            "6d999b2e36a92331ba1e5603c7a458cd470a1e73501ed27f4b83b6f807b4c5c0",
            "54b18c3a11fdee2fc519a2bcdc09e1405d6b6d5c9649ec7cbf5a67271602bb56",
            "4090699a95f366b366062a12f2468fea8d6942c94ae79ca0bbda6e90d0aa4691",
            "7d0a46e61fc0677e82ba424de355c841f4047f2432e7fd79d5f03dbe3d8b3344"
          ]
        },
        {
          "cohort_id": 23,
          "sign": -1,
          "start_exit_ms": 1787472000000,
          "end_exit_ms": 1787544000000,
          "exit_groups": 3,
          "origin_keys": [
            "1383657232c15ad109875d61784984a9785c9a4c703557ca58395f12ff0b7040",
            "35b588907b2b1528d4eb89ab7def01e64f396dcadb64da781a5660129ef285dd",
            "56a95402b35719bce4892de33e5cebc58350172785e97cf7256a732b4ce9aa07",
            "6bdfa193b8b77a88b9a217f80335a559c231966a7d1b651163ed4700174ec8cc",
            "4a48214848c01cf2aa9487fa6f7fda0c833739643a59cd8f2c145c7b42e69a03"
          ]
        },
        {
          "cohort_id": 24,
          "sign": 1,
          "start_exit_ms": 1787788800000,
          "end_exit_ms": 1787788800000,
          "exit_groups": 1,
          "origin_keys": [
            "c197ed0697f8e463e8ab4709ff0facd8be88731132679bc929fe21b0d886fe83"
          ]
        },
        {
          "cohort_id": 25,
          "sign": -1,
          "start_exit_ms": 1787803200000,
          "end_exit_ms": 1788019200000,
          "exit_groups": 3,
          "origin_keys": [
            "efe05a9c02ffababff9218fd402b20bbf871094de63624b118f84e2abe6b46cb",
            "96f83fff2d373c4c150ee34f03386333ea563a61ae0bf28da65fbd699cfebb2d",
            "9ca276e7009d076a78c722e6478f25c6cd2a600ac27ff4de667ff597d570dae7",
            "a2e9e7ac1b41c7e88b0834fdf0dfc67a3ca0bdf0433bb48aa7de8d3bc3bffc58",
            "a8cc81ec4b4f93d3a4bd8af711f4b265e7d0fe67540f0486ca421716abac86ef",
            "42d2122b001aa615906ba62172ad2536a51346a86e6ab239faf085660aada6e9",
            "bb528b63dc4c0abd4b1005dfd7efbe1473746015ff2892357bc91727610e87a9"
          ]
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 577.5933824300822,
          "BCH-USDT": 1658.962009119945,
          "BTC-USDT": 1817.0654536604557,
          "ETH-USDT": 1132.2716481537786,
          "HYPE-USDT": 2595.812781486518,
          "LINK-USDT": 1448.8563123047684,
          "SOL-USDT": 1595.9129758029217
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 3339.939619906868,
          "BCH-USDT": 3832.5170480548586,
          "BTC-USDT": 2443.0610966793693,
          "ETH-USDT": 2560.5203698808778,
          "HYPE-USDT": 7882.978226741286,
          "LINK-USDT": 3127.1162464477184,
          "SOL-USDT": 4016.887371713496
        },
        "total_positive_trade_profit_bps": 27203.019979424473,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.28978320174391403,
        "winner_T": 34,
        "top_decile_winner_T": 4,
        "top_decile_winners_share": 0.394014588270247,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 478.58680114429217,
          "2026-06": -4121.38121301827,
          "2026-07": -176.4238814900307,
          "2026-08": 14645.692856322477,
          "2026-09": 0
        },
        "top_positive_month_share": 0.9683563903879536
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1778457600000,
          "T": 8,
          "net_trade_sum_bps": -2566.655700932032
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 2,
          "net_trade_sum_bps": 2959.7446097097404
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 1,
          "net_trade_sum_bps": 85.4978923665837
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 3,
          "net_trade_sum_bps": -843.1511251152849
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 7,
          "net_trade_sum_bps": -2109.7396989389845
        },
        {
          "utc_monday_ms": 1782086400000,
          "T": 3,
          "net_trade_sum_bps": -1168.490388964
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 3,
          "net_trade_sum_bps": 2919.6649601836757
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 12,
          "net_trade_sum_bps": -1710.0454178952364
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 7,
          "net_trade_sum_bps": -389.09749065552944
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 6,
          "net_trade_sum_bps": -730.1289657264202
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 2,
          "net_trade_sum_bps": -266.81696739652034
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 3,
          "net_trade_sum_bps": -586.0097427390236
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 4,
          "net_trade_sum_bps": -179.71574581597616
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 9,
          "net_trade_sum_bps": 11923.2231041574
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 14,
          "net_trade_sum_bps": 3488.1952407200774
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778472000000,
          "end_exit_ms": 1778472000000,
          "exit_groups": 1,
          "origin_keys": [
            "af3e4bfe171ccff587124eb44124d9d6bf80e7c05351fbd2473fc910a5d14178"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1778572800000,
          "end_exit_ms": 1778572800000,
          "exit_groups": 1,
          "origin_keys": [
            "e6f531e30771998b2b702b2366698ed231120fb87b2cf788600d29b08686fa98"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1778601600000,
          "end_exit_ms": 1778947200000,
          "exit_groups": 4,
          "origin_keys": [
            "20813582cd090f2e7c1d87d5a066c0f36f555e67f708eddcf03f1b54c02535e6",
            "3704af8874f5d479cae7c24c5e0570797dc3fc675fd5a9798c42bdadc6d58399",
            "e26e5ab7aa230b7fc5f798e3617b5dc155b2cf4d41f276352126a6c55a5f0bca",
            "ef6a9fd9f69ef1783edb036f8f946661089d30ef43afc0266fd767f1bf1850ea",
            "4ab3268feebf765b7a54119fa7c5016746133048811a0d1a78f5dc35994c293f",
            "e69a9771939170a09a3548b2322e29688c48b62ffb21ae51d77e748328548654"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1779393600000,
          "end_exit_ms": 1780416000000,
          "exit_groups": 4,
          "origin_keys": [
            "37709b9f7edb53c1d5942eaf3c989a507b72c6d0a8aa08135a1320da3702a14d",
            "873878171bdf5318599f664188d8b146730ac6ffdc7d36c13e5c1e807266b3cb",
            "2b1a4ccc3af49f20ede7666ec761c16a84ba1db24a27eeef8eb64cafa582240b",
            "6d3652d6e9043817725a1217d09e373409da0efce7c5e076738ebce8ab145a61"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1780444800000,
          "end_exit_ms": 1781654400000,
          "exit_groups": 3,
          "origin_keys": [
            "a67a3abde224ea3e365f40489d635c913c6065b1182f2209e65e6ad754ca6b54",
            "1aeb48d618308f3e3e92108d83347b7399f8d3abe5638179df0b9a44bb0aebf8",
            "2179e1375958574fe042f2de6f137ca0520f8e433bb6e583532ca4e4a216dae3"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1781697600000,
          "end_exit_ms": 1781697600000,
          "exit_groups": 1,
          "origin_keys": [
            "5cddb7370750225638aa8bb54fe7ead45c8a86840b8a8c05271c20ccfeaae303"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1781712000000,
          "end_exit_ms": 1781884800000,
          "exit_groups": 3,
          "origin_keys": [
            "194caca2c855cf2b63d291ea855a2053da379563b06fb082a6137aae163b72e5",
            "45d2532a3430b47c597fbdb486be9e2de86ba0f26b17021c6b0b385a3cb0f38d",
            "6134cb9684d19748bccac5cfa9a75edc43133eace617fc910f3466e827946d57",
            "7285c3ddbb558ba0890fa25be6439e651533c94df35e294c245e0e67712c02de",
            "8a69431a588a543d87f8f8047792c4cc980558ed2f1aefe5048af8d022ed91be"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1782172800000,
          "end_exit_ms": 1782172800000,
          "exit_groups": 1,
          "origin_keys": [
            "92b587094c241be908ce0209308b08b14a17d7d50be5034bfb5a2e008a25479a"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1782273600000,
          "end_exit_ms": 1782288000000,
          "exit_groups": 2,
          "origin_keys": [
            "26048c789a194d64061bab864b1105c91c2ceab6bf664f0071606f65ca1b69a6",
            "5ee84b421772b58c19b7785d02049cc7496003e942cbbbdf0a0d83b30d3c92a2"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1783108800000,
          "end_exit_ms": 1783267200000,
          "exit_groups": 3,
          "origin_keys": [
            "f576eadd0586926750d4b2ba9bab812d4543a0a8d7266fe5289b0bcd6a7af631",
            "125e8c500f160245f58567c6e0edd312ac12389775b4df8fd8447ed88410f13f",
            "96df5996f53c9d8ea7fdba22dcd3f9db6b86ded69de3a63ac067a8264e71fc7c"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1783296000000,
          "end_exit_ms": 1783540800000,
          "exit_groups": 7,
          "origin_keys": [
            "944a89cf5ed854bf74c916a7d91db8745d621e932dd73fffcf11c29b5a2c1df3",
            "c7f4ea10a0248e02cf832cb22160cb2a181c1d7e926840e45061a775006b514d",
            "1d2f8f7ac4072f80c85d02f7449b15305f2dfbdffc3c04242b3884ac8a4f5c3d",
            "3f6e146ee6498eab92e7a0d6d06ab32d295150f930b2040f3a43ea6104fe34ca",
            "d552e4f2d70df39b5c2fd9c9defb47260c7f15a2be84c2caec94d9a8d191e532",
            "eaa82ab5342448af2ff822854c4477a696978b456a120ce280809ba68049c736",
            "f141054db9dedfa62ca7fdd3e335485305c6baeacf42a8a5c5d34a06a65c8e84",
            "5c2bf1d18074cc3dc5a4a3f30da0e27270de1ac71cc9444ccab2927f1f640457",
            "a05d6fca791250f923ca7afcd56b1f374470050c19b2ebc7221d1045468525a1"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1783828800000,
          "end_exit_ms": 1783915200000,
          "exit_groups": 3,
          "origin_keys": [
            "673de9d391a117ea56eacfc621dc137a6474a26cb63b9797a49ed85c94011df3",
            "b8c568424e8e61e1176d5a115249e60b4fe441db021025f6c036d3320b2ba02b",
            "f593f3edfb441e31698b8a96d52ab6fc475b6b97c9a90feac26584cd1ce5e81f",
            "2509d55bbea92d6c81839b97406dc4ead8036204374dd8ed2f75c1771eaae9ff",
            "db6ff814f1a0d91a4a34cd791cd3e58b21d5027b65df980a04440404c44f38c9",
            "41c878f7e646078d7b6c963c2592502a326e67e3f03d1524ae6a06e6c21953a0"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1784217600000,
          "end_exit_ms": 1784260800000,
          "exit_groups": 3,
          "origin_keys": [
            "df0b266cf5959bc5e7c13d349b8936c290530cd923802c6d322428009386e5d3",
            "ff4007a1005a0cf952569865a987bbc3f8a3af122df9ba3f7d2e5483d00c2ecd",
            "5a479c429a6576a94de9081765f8e06f777fd7f0a067d292fe6467a621d0ec0b",
            "29f9ee8a37632b1d904842e0168f0381b5568d482898555e202c1b902aac39c4"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1784692800000,
          "end_exit_ms": 1784793600000,
          "exit_groups": 3,
          "origin_keys": [
            "133bda43d00e393b07af2b26e0437dc95a6c74e748feb4417e46ba76b61b3410",
            "fb14aa9de9df3d910cd6c26e0e04eb88a1348b592b21e475f9c57c2e16cb73b1",
            "2dfb5ce585636b0d1a805bd7e085f44230bda07a8ca3772cd681e9445b8dcca6"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1784822400000,
          "end_exit_ms": 1786478400000,
          "exit_groups": 9,
          "origin_keys": [
            "baff33edbdc7207e002ebdb1638982c4e35bb5580da1459324878f9faac02043",
            "692743b67342cdda1f9c615d423dba0e005a6a115c4b33146387026ceb09ff40",
            "5808db5067623613cc00396591daa9290d508d6468e2204604203e67c5e42c4b",
            "6bbaef456336a13b6ea8cf94bdbc750234d3a2a6c60ef1c2a9329e6aa40ad107",
            "7f14e27ee7b6bbdc40a2814def65b35ca57763e0a9cc72110698a02e28246716",
            "0dea81d8d3a9b335c32934ebe69a654e01e392dcf9ece2203c5184d5eaa158aa",
            "4dbae6b3266761da3fd9e689bc7ba77cf5831b0ebe3264928e74a772777dcaea",
            "714a5290daf3f290b6468334a2c1a0b6f686e49288235a232bbddfaa51fecf8e",
            "79c332d7d2a2eadf8cfd56427345481a09ffb3624cdf28d54f1e7188f4fffa46",
            "184ff514ca18c74952359c225d55a9fefa53449d4b9af844a4a0d67256bf7215",
            "20bce44d1b740e5f42b908329dce30e29c1855b15e989268a30810b6a2264890"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1786708800000,
          "end_exit_ms": 1787097600000,
          "exit_groups": 3,
          "origin_keys": [
            "f1013b06b2481cdf9c40af548714b09cb74cabf65a79ecedca9445e3269dd42a",
            "90a22f448a6144e6f23c7053b7dc9f68e83d612cd89f1028758f4966208158e9",
            "e48a6f7f81291c57574aaa67b384d6e455477b874cc5947ffd846748b465f43a"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1787112000000,
          "end_exit_ms": 1787112000000,
          "exit_groups": 1,
          "origin_keys": [
            "4b8cac18a488885b058fa5d2951112e88aa5fb478371a4792f6b0048030e8cce"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1787385600000,
          "end_exit_ms": 1787457600000,
          "exit_groups": 3,
          "origin_keys": [
            "4f729d69de9b8cbb7eb9e147fbac46ebccfe17a1fce84686555619f4963f7869",
            "abef2e2e44ebaf18fbe7cd5767a7a20d5ae4c65c504ee3d3a29ebf6b05005e9b",
            "c99e6b9a6a6e34dce2cac1e17592a05951d48bf5d0e59135e1aa3c2a34f6cf4e",
            "6d999b2e36a92331ba1e5603c7a458cd470a1e73501ed27f4b83b6f807b4c5c0"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1787472000000,
          "end_exit_ms": 1787472000000,
          "exit_groups": 1,
          "origin_keys": [
            "35b588907b2b1528d4eb89ab7def01e64f396dcadb64da781a5660129ef285dd"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1787500800000,
          "end_exit_ms": 1787500800000,
          "exit_groups": 1,
          "origin_keys": [
            "54b18c3a11fdee2fc519a2bcdc09e1405d6b6d5c9649ec7cbf5a67271602bb56"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1787529600000,
          "end_exit_ms": 1787529600000,
          "exit_groups": 1,
          "origin_keys": [
            "56a95402b35719bce4892de33e5cebc58350172785e97cf7256a732b4ce9aa07"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1787572800000,
          "end_exit_ms": 1787702400000,
          "exit_groups": 4,
          "origin_keys": [
            "4090699a95f366b366062a12f2468fea8d6942c94ae79ca0bbda6e90d0aa4691",
            "7d0a46e61fc0677e82ba424de355c841f4047f2432e7fd79d5f03dbe3d8b3344",
            "1383657232c15ad109875d61784984a9785c9a4c703557ca58395f12ff0b7040",
            "6bdfa193b8b77a88b9a217f80335a559c231966a7d1b651163ed4700174ec8cc"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1787716800000,
          "end_exit_ms": 1787716800000,
          "exit_groups": 1,
          "origin_keys": [
            "4a48214848c01cf2aa9487fa6f7fda0c833739643a59cd8f2c145c7b42e69a03"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1787788800000,
          "end_exit_ms": 1787788800000,
          "exit_groups": 1,
          "origin_keys": [
            "c197ed0697f8e463e8ab4709ff0facd8be88731132679bc929fe21b0d886fe83"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1787803200000,
          "end_exit_ms": 1788019200000,
          "exit_groups": 3,
          "origin_keys": [
            "efe05a9c02ffababff9218fd402b20bbf871094de63624b118f84e2abe6b46cb",
            "96f83fff2d373c4c150ee34f03386333ea563a61ae0bf28da65fbd699cfebb2d",
            "9ca276e7009d076a78c722e6478f25c6cd2a600ac27ff4de667ff597d570dae7",
            "a2e9e7ac1b41c7e88b0834fdf0dfc67a3ca0bdf0433bb48aa7de8d3bc3bffc58",
            "a8cc81ec4b4f93d3a4bd8af711f4b265e7d0fe67540f0486ca421716abac86ef",
            "42d2122b001aa615906ba62172ad2536a51346a86e6ab239faf085660aada6e9",
            "bb528b63dc4c0abd4b1005dfd7efbe1473746015ff2892357bc91727610e87a9"
          ]
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 577.5933824300822,
          "BCH-USDT": 1775.6059922949726,
          "BTC-USDT": 1403.5492993537105,
          "ETH-USDT": 1364.3982802410615,
          "HYPE-USDT": 2998.933418749386,
          "LINK-USDT": 1893.1880050365749,
          "SOL-USDT": 1573.0537626360724
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 3339.939619906868,
          "BCH-USDT": 3677.895338992723,
          "BTC-USDT": 2029.544942372624,
          "ETH-USDT": 2560.5203698808778,
          "HYPE-USDT": 7281.1399647216795,
          "LINK-USDT": 3127.1162464477184,
          "SOL-USDT": 3558.005504379543
        },
        "total_positive_trade_profit_bps": 25574.16198670203,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.2847068837879303,
        "winner_T": 30,
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.32568327273576925,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": -404.51647409609336,
          "2026-06": -3083.9837518788313,
          "2026-07": 424.47596989220517,
          "2026-08": 14650.34639682458,
          "2026-09": 0
        },
        "top_positive_month_share": 0.9718420582633603
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1778457600000,
          "T": 8,
          "net_trade_sum_bps": -2566.655700932032
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 1,
          "net_trade_sum_bps": 2357.9063476901338
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 2,
          "net_trade_sum_bps": -195.7671208541953
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 2,
          "net_trade_sum_bps": -503.6253203103149
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 6,
          "net_trade_sum_bps": -1411.8680426045166
        },
        {
          "utc_monday_ms": 1782086400000,
          "T": 3,
          "net_trade_sum_bps": -1168.490388964
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 3,
          "net_trade_sum_bps": 2919.6649601836757
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 10,
          "net_trade_sum_bps": -1324.2146822461623
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 7,
          "net_trade_sum_bps": -389.09749065552944
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 6,
          "net_trade_sum_bps": -515.0598499932584
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 2,
          "net_trade_sum_bps": -266.81696739652034
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 3,
          "net_trade_sum_bps": -586.0097427390236
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 4,
          "net_trade_sum_bps": -179.71574581597616
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 7,
          "net_trade_sum_bps": 12301.084384070768
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 9,
          "net_trade_sum_bps": 3171.6426852126915
        },
        {
          "utc_monday_ms": 1788134400000,
          "T": 1,
          "net_trade_sum_bps": -56.65518390387923
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778472000000,
          "end_exit_ms": 1778472000000,
          "exit_groups": 1,
          "origin_keys": [
            "af3e4bfe171ccff587124eb44124d9d6bf80e7c05351fbd2473fc910a5d14178"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1778572800000,
          "end_exit_ms": 1778572800000,
          "exit_groups": 1,
          "origin_keys": [
            "e6f531e30771998b2b702b2366698ed231120fb87b2cf788600d29b08686fa98"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1778601600000,
          "end_exit_ms": 1778947200000,
          "exit_groups": 4,
          "origin_keys": [
            "20813582cd090f2e7c1d87d5a066c0f36f555e67f708eddcf03f1b54c02535e6",
            "3704af8874f5d479cae7c24c5e0570797dc3fc675fd5a9798c42bdadc6d58399",
            "e26e5ab7aa230b7fc5f798e3617b5dc155b2cf4d41f276352126a6c55a5f0bca",
            "ef6a9fd9f69ef1783edb036f8f946661089d30ef43afc0266fd767f1bf1850ea",
            "4ab3268feebf765b7a54119fa7c5016746133048811a0d1a78f5dc35994c293f",
            "e69a9771939170a09a3548b2322e29688c48b62ffb21ae51d77e748328548654"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1779393600000,
          "end_exit_ms": 1779393600000,
          "exit_groups": 1,
          "origin_keys": [
            "37709b9f7edb53c1d5942eaf3c989a507b72c6d0a8aa08135a1320da3702a14d"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1779768000000,
          "end_exit_ms": 1779768000000,
          "exit_groups": 1,
          "origin_keys": [
            "fcc57c7506a17c9567f833fd096954ba76d7d88b90171f86a262cc9ea9c1d59a"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1780041600000,
          "end_exit_ms": 1780416000000,
          "exit_groups": 2,
          "origin_keys": [
            "2b1a4ccc3af49f20ede7666ec761c16a84ba1db24a27eeef8eb64cafa582240b",
            "6d3652d6e9043817725a1217d09e373409da0efce7c5e076738ebce8ab145a61"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1780646400000,
          "end_exit_ms": 1781654400000,
          "exit_groups": 2,
          "origin_keys": [
            "1aeb48d618308f3e3e92108d83347b7399f8d3abe5638179df0b9a44bb0aebf8",
            "2179e1375958574fe042f2de6f137ca0520f8e433bb6e583532ca4e4a216dae3"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1781697600000,
          "end_exit_ms": 1781697600000,
          "exit_groups": 1,
          "origin_keys": [
            "5cddb7370750225638aa8bb54fe7ead45c8a86840b8a8c05271c20ccfeaae303"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1781712000000,
          "end_exit_ms": 1781884800000,
          "exit_groups": 3,
          "origin_keys": [
            "194caca2c855cf2b63d291ea855a2053da379563b06fb082a6137aae163b72e5",
            "45d2532a3430b47c597fbdb486be9e2de86ba0f26b17021c6b0b385a3cb0f38d",
            "6134cb9684d19748bccac5cfa9a75edc43133eace617fc910f3466e827946d57",
            "8a69431a588a543d87f8f8047792c4cc980558ed2f1aefe5048af8d022ed91be"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1782172800000,
          "end_exit_ms": 1782172800000,
          "exit_groups": 1,
          "origin_keys": [
            "92b587094c241be908ce0209308b08b14a17d7d50be5034bfb5a2e008a25479a"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1782273600000,
          "end_exit_ms": 1782288000000,
          "exit_groups": 2,
          "origin_keys": [
            "26048c789a194d64061bab864b1105c91c2ceab6bf664f0071606f65ca1b69a6",
            "5ee84b421772b58c19b7785d02049cc7496003e942cbbbdf0a0d83b30d3c92a2"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1783108800000,
          "end_exit_ms": 1783267200000,
          "exit_groups": 3,
          "origin_keys": [
            "f576eadd0586926750d4b2ba9bab812d4543a0a8d7266fe5289b0bcd6a7af631",
            "125e8c500f160245f58567c6e0edd312ac12389775b4df8fd8447ed88410f13f",
            "96df5996f53c9d8ea7fdba22dcd3f9db6b86ded69de3a63ac067a8264e71fc7c"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1783296000000,
          "end_exit_ms": 1783526400000,
          "exit_groups": 6,
          "origin_keys": [
            "944a89cf5ed854bf74c916a7d91db8745d621e932dd73fffcf11c29b5a2c1df3",
            "1d2f8f7ac4072f80c85d02f7449b15305f2dfbdffc3c04242b3884ac8a4f5c3d",
            "3f6e146ee6498eab92e7a0d6d06ab32d295150f930b2040f3a43ea6104fe34ca",
            "7e1b71b1b58177d9f8ddae023cf4f05f3746211d2cfdc1433cf5068ce6c99249",
            "d552e4f2d70df39b5c2fd9c9defb47260c7f15a2be84c2caec94d9a8d191e532",
            "f141054db9dedfa62ca7fdd3e335485305c6baeacf42a8a5c5d34a06a65c8e84",
            "5c2bf1d18074cc3dc5a4a3f30da0e27270de1ac71cc9444ccab2927f1f640457"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1783828800000,
          "end_exit_ms": 1783915200000,
          "exit_groups": 3,
          "origin_keys": [
            "673de9d391a117ea56eacfc621dc137a6474a26cb63b9797a49ed85c94011df3",
            "b8c568424e8e61e1176d5a115249e60b4fe441db021025f6c036d3320b2ba02b",
            "f593f3edfb441e31698b8a96d52ab6fc475b6b97c9a90feac26584cd1ce5e81f",
            "2509d55bbea92d6c81839b97406dc4ead8036204374dd8ed2f75c1771eaae9ff",
            "db6ff814f1a0d91a4a34cd791cd3e58b21d5027b65df980a04440404c44f38c9",
            "41c878f7e646078d7b6c963c2592502a326e67e3f03d1524ae6a06e6c21953a0"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1784217600000,
          "end_exit_ms": 1784260800000,
          "exit_groups": 3,
          "origin_keys": [
            "df0b266cf5959bc5e7c13d349b8936c290530cd923802c6d322428009386e5d3",
            "ff4007a1005a0cf952569865a987bbc3f8a3af122df9ba3f7d2e5483d00c2ecd",
            "5a479c429a6576a94de9081765f8e06f777fd7f0a067d292fe6467a621d0ec0b",
            "29f9ee8a37632b1d904842e0168f0381b5568d482898555e202c1b902aac39c4"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1784692800000,
          "end_exit_ms": 1784793600000,
          "exit_groups": 3,
          "origin_keys": [
            "133bda43d00e393b07af2b26e0437dc95a6c74e748feb4417e46ba76b61b3410",
            "fb14aa9de9df3d910cd6c26e0e04eb88a1348b592b21e475f9c57c2e16cb73b1",
            "2dfb5ce585636b0d1a805bd7e085f44230bda07a8ca3772cd681e9445b8dcca6"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1784822400000,
          "end_exit_ms": 1786478400000,
          "exit_groups": 9,
          "origin_keys": [
            "baff33edbdc7207e002ebdb1638982c4e35bb5580da1459324878f9faac02043",
            "692743b67342cdda1f9c615d423dba0e005a6a115c4b33146387026ceb09ff40",
            "f549c68ede0e03f569bbb647e08b9b46c1ba80717a3ce2fd9be3e61358bbb3a8",
            "6bbaef456336a13b6ea8cf94bdbc750234d3a2a6c60ef1c2a9329e6aa40ad107",
            "7f14e27ee7b6bbdc40a2814def65b35ca57763e0a9cc72110698a02e28246716",
            "0dea81d8d3a9b335c32934ebe69a654e01e392dcf9ece2203c5184d5eaa158aa",
            "4dbae6b3266761da3fd9e689bc7ba77cf5831b0ebe3264928e74a772777dcaea",
            "714a5290daf3f290b6468334a2c1a0b6f686e49288235a232bbddfaa51fecf8e",
            "79c332d7d2a2eadf8cfd56427345481a09ffb3624cdf28d54f1e7188f4fffa46",
            "184ff514ca18c74952359c225d55a9fefa53449d4b9af844a4a0d67256bf7215",
            "20bce44d1b740e5f42b908329dce30e29c1855b15e989268a30810b6a2264890"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1786708800000,
          "end_exit_ms": 1787760000000,
          "exit_groups": 10,
          "origin_keys": [
            "f1013b06b2481cdf9c40af548714b09cb74cabf65a79ecedca9445e3269dd42a",
            "90a22f448a6144e6f23c7053b7dc9f68e83d612cd89f1028758f4966208158e9",
            "e48a6f7f81291c57574aaa67b384d6e455477b874cc5947ffd846748b465f43a",
            "4f729d69de9b8cbb7eb9e147fbac46ebccfe17a1fce84686555619f4963f7869",
            "abef2e2e44ebaf18fbe7cd5767a7a20d5ae4c65c504ee3d3a29ebf6b05005e9b",
            "c99e6b9a6a6e34dce2cac1e17592a05951d48bf5d0e59135e1aa3c2a34f6cf4e",
            "6d999b2e36a92331ba1e5603c7a458cd470a1e73501ed27f4b83b6f807b4c5c0",
            "54b18c3a11fdee2fc519a2bcdc09e1405d6b6d5c9649ec7cbf5a67271602bb56",
            "4090699a95f366b366062a12f2468fea8d6942c94ae79ca0bbda6e90d0aa4691",
            "7d0a46e61fc0677e82ba424de355c841f4047f2432e7fd79d5f03dbe3d8b3344",
            "ec147604ed47cf3619f52405bbff9c40a2827ee263a838d08b336679f93154ba"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1787803200000,
          "end_exit_ms": 1788134400000,
          "exit_groups": 4,
          "origin_keys": [
            "efe05a9c02ffababff9218fd402b20bbf871094de63624b118f84e2abe6b46cb",
            "96f83fff2d373c4c150ee34f03386333ea563a61ae0bf28da65fbd699cfebb2d",
            "9ca276e7009d076a78c722e6478f25c6cd2a600ac27ff4de667ff597d570dae7",
            "a2e9e7ac1b41c7e88b0834fdf0dfc67a3ca0bdf0433bb48aa7de8d3bc3bffc58",
            "a8cc81ec4b4f93d3a4bd8af711f4b265e7d0fe67540f0486ca421716abac86ef",
            "bb528b63dc4c0abd4b1005dfd7efbe1473746015ff2892357bc91727610e87a9",
            "7a416c466a13f7b820c7b2f19140cb429847de69f7250b9bcc49789d0cf2cefd"
          ]
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
