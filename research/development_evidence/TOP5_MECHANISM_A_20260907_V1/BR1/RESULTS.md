# BR1 frozen DEV economics

Equal nominal trade-bps; terminal includes hypothetical full-cost open marks. Neither account returns nor independent validation. FULL is primary; FIXED is a diagnostic. KR1/M/M2 ledgers reused. SR1/BR1 V2 baselines computed only for these authorized comparisons. Q0 is preserved without replay or replacement.

## DEV2025

| Metric | P | FIXED | FULL |
|---|---:|---:|---:|
| closed_T | 155.000000 | 155.000000 | 138.000000 |
| open_T | 2.000000 | 2.000000 | 2.000000 |
| entries_T | 157.000000 | 157.000000 | 140.000000 |
| win_rate | 0.509677 | 0.419355 | 0.413043 |
| PF | 1.233340 | 1.180545 | 1.305780 |
| mean_win_bps | 349.950393 | 497.785724 | 531.401092 |
| mean_loss_bps | -294.942368 | -304.530389 | -286.379822 |
| realized_payoff | 1.186504 | 1.634601 | 1.855581 |
| net_expectancy_bps_per_closed_trade | 33.744910 | 31.924755 | 51.399252 |
| closed_gross_bps | 8359.592472 | 8144.871837 | 9940.512695 |
| closed_net_bps | 5230.461101 | 4948.337073 | 7093.096718 |
| closed_cost2x_net_bps | 2101.329730 | 1751.802310 | 4245.680741 |
| closed_cost_bps | 3129.131371 | 3196.534763 | 2847.415977 |
| closed_fee_bps | 1550.000000 | 1550.000000 | 1380.000000 |
| closed_funding_bps | 553.140000 | 809.870000 | 725.710000 |
| terminal_net_bps_hypothetical | 4792.194096 | 4510.070068 | 6654.829713 |
| terminal_cost2x_net_bps_hypothetical | 1623.062725 | 1273.535305 | 3767.413736 |
| open_net_mark_bps_hypothetical | -438.267005 | -438.267005 | -438.267005 |
| marked_DD_trade_sum_bps | 4289.896697 | 7525.077553 | 7593.304280 |
| grouped_max_loss_trade_sum_bps | 2735.501382 | 4528.515134 | 3296.705065 |
| exposure_symbol_days | 155.833333 | 230.000000 | 205.666667 |
| max_simultaneous_symbols | 7.000000 | 7.000000 | 7.000000 |
| entries_per_30_days | 12.560000 | 12.560000 | 11.200000 |
| max_completed_recovery_days | 98.000000 | 98.000000 | 83.000000 |
| open_underwater_days | 87.333333 | 137.333333 | 137.333333 |

Decisions: {"FIXED": "REJECT", "FULL": "TRADEOFF"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "P": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 1580.9202225320987,
        "net_bps": 1862.6356167511608,
        "cost2x_net_bps": 2144.3510109702243,
        "cost_bps": -281.71539421906266,
        "fee_bps": -170.0,
        "spread_bps": -23.55740902443314,
        "impact_bps": -34.70175431489772,
        "slippage_bps": 0.0,
        "funding_bps": 172.57,
        "frozen_floor_reserve_bps": -226.0262308797318
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 3,
          "delta_bps": {
            "gross_bps": 548.3242386292752,
            "net_bps": 488.3242386292752,
            "cost2x_net_bps": 428.3242386292752,
            "cost_bps": 60.0,
            "fee_bps": 30.0,
            "spread_bps": 5.3803769120268194,
            "impact_bps": 6.0,
            "slippage_bps": 0.0,
            "funding_bps": 12.0,
            "frozen_floor_reserve_bps": 6.619623087973181
          }
        },
        "C_ABSENT": {
          "T": 20,
          "delta_bps": {
            "gross_bps": 2003.5868803537683,
            "net_bps": 2405.2052898690454,
            "cost2x_net_bps": 2806.823699384323,
            "cost_bps": -401.6184095152772,
            "fee_bps": -200.0,
            "spread_bps": -28.93778593645996,
            "impact_bps": -40.70175431489772,
            "slippage_bps": 0.0,
            "funding_bps": -68.04,
            "frozen_floor_reserve_bps": -63.93886926391954
          }
        },
        "C_C": {
          "T": 135,
          "delta_bps": {
            "gross_bps": -970.9908964509449,
            "net_bps": -1030.8939117471598,
            "cost2x_net_bps": -1090.7969270433737,
            "cost_bps": 59.90301529621456,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 228.61,
            "frozen_floor_reserve_bps": -168.70698470378545
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
        "T": 71,
        "parent_positive_bps": 16921.370493069935,
        "child_signed_terminal_bps": 15188.084253296778,
        "capped_terminal_preserved_bps_hypothetical": 10380.391603487053,
        "capped_terminal_retention_hypothetical": 0.613448633356163,
        "realized_capped_retention_lower": 0.613448633356163,
        "realized_capped_retention_upper": 0.613448633356163,
        "profit_cut_bps": 6540.9788895828815,
        "additional_loss_after_winner_bps": 2848.7728977036013,
        "signed_winner_deterioration_bps": 9389.751787286483,
        "winner_to_loss_T": 16,
        "winner_removed_T": 11,
        "winner_to_loss_origins": [
          "19f257381a58217a5939d7cd4c1c2c64d7cc5d907b7cd4abd9305f6b8f5a6231",
          "1ff9ecf8923813e16032eb997cf21c0a433aa549336677e36f6014fa56a77eb8",
          "225f2c0c74dec674d14dd2542a98b87735badb7593e5ebf32d4b6af32309c910",
          "3c5a14e98e97cdcc4ab2ccf38c7721973355239db90f0b8cf0fb15c355155599",
          "3f51205dc1796ad1adfeadc494bbd4c5863874e0c53ce7fcb48aea973063220e",
          "486f3c379524c1142a45fd11d3bcdb20f1bc53d8cdb01e7fb4e537126a14e582",
          "62f365c2e2f8d3aaa16b0b80129fcf63647dfbf23f6f92a3b2e8a751fd7efae3",
          "65096e09475306adc4c891c76c29c02fa99fab9a2e47244d727d0b96f00ca052",
          "651217e8d7efd041657b1e7a9c5bc7e59fb672d38ba02d4bac6014c41cf0fd35",
          "65ea9e92c1f61c7e9ffb6969d5d84c537ab2fc15a03ebbe9c0d0a732c731b284",
          "822d8ddf2416c697673994ade0628e3cc865edc859393fa9331567774a642bed",
          "9c81225d6f110ff12a13a07bcae870e54d6a1849e93a0b305fff7577a8eec6f3",
          "a0c5f502cb345b714fc91e81e9486695f0c1f236cb6348d8948d65c27b24a0f1",
          "b9bdb4c2b4b149a2d8e6a8832b0991c8121ea44e8054055c1744eb5651743083",
          "bea8aae7dd2b88f3b8fb0ac87118bf5e97847dbbebd228e32a400dd469eb5a56",
          "d8a4f2a22a84a15e76cf58b338e484119ccadf383e7993fa025f42b80aa20ab4"
        ]
      },
      "large_winners": {
        "T": 8,
        "parent_positive_bps": 10724.71056986806,
        "child_signed_terminal_bps": 11004.770613434805,
        "capped_terminal_preserved_bps_hypothetical": 8878.295802308296,
        "capped_terminal_retention_hypothetical": 0.8278354687960143,
        "realized_capped_retention_lower": 0.8278354687960143,
        "realized_capped_retention_upper": 0.8278354687960143,
        "profit_cut_bps": 1846.4147675597653,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 1846.4147675597653,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "f8bbac66a79fa36955476264d2d7eb5f355b551a626f8dcc7d489aaa222417bc",
        "symbol": "1000PEPE-USDT",
        "signal_ts": 1752091200000,
        "entry_month": "2025-07",
        "transition": "C_C",
        "parent": {
          "gross_bps": 645.2473371474832,
          "net_bps": 623.628927632206,
          "cost2x_net_bps": 602.0105181169288,
          "cost_bps": 21.61840951527722,
          "fee_bps": 10.0,
          "spread_bps": 2.796655200379503,
          "impact_bps": 2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": 6.12,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 1974.28208760279,
          "net_bps": 1946.5436780875127,
          "cost2x_net_bps": 1918.8052685722355,
          "cost_bps": 27.738409515277223,
          "fee_bps": 10.0,
          "spread_bps": 2.796655200379503,
          "impact_bps": 2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": 12.24,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 1329.0347504553067,
          "net_bps": 1322.9147504553066,
          "cost2x_net_bps": 1316.7947504553067,
          "cost_bps": 6.120000000000001,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.12,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": false,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 86400000,
        "child_hold_ms": 172800000
      },
      "net_increment_without_largest_positive": 539.7208662958542,
      "largest_positive_share_of_net_increment": 0.7102380833685312,
      "increment_by_symbol": {
        "SOL-USDT": 291.72766327519406,
        "ETH-USDT": 962.2630448101675,
        "BTC-USDT": -223.8932414951455,
        "LINK-USDT": 1616.1904555470132,
        "HYPE-USDT": 2209.5010169980933,
        "BCH-USDT": -2741.038484700936,
        "1000PEPE-USDT": -252.11483768322614
      },
      "increment_by_entry_month": {
        "2025-04": -808.1320193812653,
        "2025-09": -992.6557311194877,
        "2025-07": 2499.847753792093,
        "2025-10": -672.0636264568125,
        "2025-06": 726.2452149737662,
        "2025-05": 602.0777531656253,
        "2025-03": 576.8706516259081,
        "2025-08": 855.2991422664425,
        "2025-12": -924.853522115109,
        "2025-11": 0.0,
        "2025-02": 0.0,
        "2025-01": 0.0
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
      "fixed_path_or_filter_effect": -214.72063547917787,
      "full_occupancy_remainder": 1795.6408580112766,
      "full_total_effect": 1580.9202225320987
    },
    "net_bps": {
      "fixed_path_or_filter_effect": -282.1240276874196,
      "full_occupancy_remainder": 2144.759644438581,
      "full_total_effect": 1862.6356167511613
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": -349.52741989565993,
      "full_occupancy_remainder": 2493.878430865884,
      "full_total_effect": 2144.3510109702243
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 67.40339220824171,
      "full_occupancy_remainder": -349.11878642730426,
      "full_total_effect": -281.71539421906255
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -170.0,
      "full_total_effect": -170.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -23.557409024433127,
      "full_total_effect": -23.557409024433127
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -34.7017543148977,
      "full_total_effect": -34.7017543148977
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 256.7299999999999,
      "full_occupancy_remainder": -84.15999999999997,
      "full_total_effect": 172.56999999999994
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -189.32660779175865,
      "full_occupancy_remainder": -36.69962308797315,
      "full_total_effect": -226.0262308797318
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
      "parent_marked_delta_sum_bps": 4792.194095970759,
      "child_marked_delta_sum_bps": 4510.070068283339,
      "child_minus_parent_marked_delta_sum_bps": -282.1240276874198,
      "child_minus_parent_mean_daily_bps": -0.7503298608707973,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -17.779890914236702,
        19.805469038345457
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -6685.238983753,
        7446.856358417892
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
      "parent_marked_delta_sum_bps": 4792.194095970759,
      "child_marked_delta_sum_bps": 6654.829712721921,
      "child_minus_parent_marked_delta_sum_bps": 1862.6356167511613,
      "child_minus_parent_mean_daily_bps": 4.953818129657344,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -12.492724867571402,
        27.462742173796066
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -4697.264550206847,
        10325.99105734732
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
          "1000PEPE-USDT": 868.7161469436712,
          "BCH-USDT": -268.5761485398582,
          "BTC-USDT": 631.0541422985866,
          "ETH-USDT": 2759.5034327414996,
          "HYPE-USDT": -185.5640801646053,
          "LINK-USDT": -698.5626412381157,
          "SOL-USDT": 2123.8902489969173
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 5945.662399681109,
          "BCH-USDT": 2791.1536417338034,
          "BTC-USDT": 1843.0292448453026,
          "ETH-USDT": 5214.205235064691,
          "HYPE-USDT": 5038.543467892354,
          "LINK-USDT": 2581.146688910741,
          "SOL-USDT": 4232.340384809996
        },
        "total_positive_trade_profit_bps": 27646.081062937996,
        "top_one_symbol_by_positive_trade_profit": "1000PEPE-USDT",
        "top_one_symbol_profit_share": 0.21506347992489222,
        "winner_T": 79,
        "top_decile_winner_T": 8,
        "top_decile_winners_share": 0.38792878258052566,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": -644.5578879101743,
          "2025-03": -2274.3253672401556,
          "2025-04": 2275.8637867055945,
          "2025-05": 7254.94986336325,
          "2025-06": -2274.40695812277,
          "2025-07": 1470.1622343259435,
          "2025-08": -7.6685427882268655,
          "2025-09": 2132.907139279734,
          "2025-10": -1619.6341005082256,
          "2025-11": -228.60518742291222,
          "2025-12": -854.2238786439627
        },
        "top_positive_month_share": 0.5523842301843117
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 1,
          "net_trade_sum_bps": -281.79679750602315
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 1,
          "net_trade_sum_bps": -362.76109040415116
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": 108.91873062494176
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 2,
          "net_trade_sum_bps": -968.6669303345063
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 6,
          "net_trade_sum_bps": -1414.5771675305907
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 3,
          "net_trade_sum_bps": -362.54416523867076
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 3,
          "net_trade_sum_bps": -165.30754012827327
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 10,
          "net_trade_sum_bps": 2803.7154920725384
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 1,
          "net_trade_sum_bps": 56.8204149862739
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 10,
          "net_trade_sum_bps": 6820.475039470532
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 5,
          "net_trade_sum_bps": -1577.7988160969912
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 4,
          "net_trade_sum_bps": 2413.0444507517045
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 2,
          "net_trade_sum_bps": -457.59122574826836
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 10,
          "net_trade_sum_bps": -1735.4467179373967
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 3,
          "net_trade_sum_bps": -454.9583469013118
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 1,
          "net_trade_sum_bps": 12.729638579813702
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": -924.8356138531144
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 10,
          "net_trade_sum_bps": 2291.52706502338
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 5,
          "net_trade_sum_bps": -370.0919707828865
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 5,
          "net_trade_sum_bps": 8.226992680220278
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 1,
          "net_trade_sum_bps": 368.60422939446914
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 7,
          "net_trade_sum_bps": 1657.1369421484285
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 9,
          "net_trade_sum_bps": -793.0951991145838
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 4,
          "net_trade_sum_bps": -905.3008538820939
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 1,
          "net_trade_sum_bps": 33.59056806002238
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 2,
          "net_trade_sum_bps": -525.072330872297
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 11,
          "net_trade_sum_bps": 2804.675985801264
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 5,
          "net_trade_sum_bps": -146.6965156492327
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 9,
          "net_trade_sum_bps": 170.92992425935657
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 5,
          "net_trade_sum_bps": -1927.3999703265874
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 5,
          "net_trade_sum_bps": 136.83594555900524
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 1,
          "net_trade_sum_bps": -228.60518742291222
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 3,
          "net_trade_sum_bps": -598.5093341710314
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 1,
          "net_trade_sum_bps": 232.88015237531658
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 1,
          "net_trade_sum_bps": -488.59469684824796
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1738425600000,
          "end_exit_ms": 1741032000000,
          "exit_groups": 3,
          "origin_keys": [
            "e1393b13ce9e62f6eb17d5c6206939eb2852acc688d6eb1e60d64655016ab17c",
            "a99278759b8e91aa7cdc7c3aefa7607831e082cc0daa3f2a56dd8ecd56682920",
            "438f3504500ed30e519cdf08501ea04d70d093f94287d91b697b6e437d20800d"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1741262400000,
          "end_exit_ms": 1741262400000,
          "exit_groups": 1,
          "origin_keys": [
            "503ff6a0363ff8e8203078e9fbb189950e1576469014e15bf8f9986e767d5265"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1742328000000,
          "end_exit_ms": 1742688000000,
          "exit_groups": 2,
          "origin_keys": [
            "2d8378ea4c8c85828631ce65eef9f301a2b6921a2eadd391324d5e64fa72f507",
            "0d5e3b780a55f9d0b89de38f6f5397fd5a9346de8509d98e1985489c20b3c79e"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1742875200000,
          "end_exit_ms": 1742875200000,
          "exit_groups": 1,
          "origin_keys": [
            "a4f1702ef521f42f52ce4cb17de0f23b603fb2804dfdc4dc96b8b3b4a0c38b60"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1742904000000,
          "end_exit_ms": 1742904000000,
          "exit_groups": 1,
          "origin_keys": [
            "49c17bcfd2e02b28bc452bc57a61822c7ab58faf688d0bb895708a2b71583793",
            "ec1914fd8dfd666abc394005c178938ae9100a41add23d56bc9d71732738cf3e"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1742918400000,
          "end_exit_ms": 1742918400000,
          "exit_groups": 1,
          "origin_keys": [
            "d87c44b0d3bd96b0d46da6aad6ac4b85cf487aed8a1d2d25071c29dae13a01cc"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1743004800000,
          "end_exit_ms": 1745020800000,
          "exit_groups": 5,
          "origin_keys": [
            "7f951ddccc04c7f115ced11144784c6deb4c060fc633ee873968203f21a9ea51",
            "b4313ed8c4be45927f975d025634067c32d0269604ef7cd4d63a2e13e4ba8aa1",
            "00adbc073c8872856db73cacefd0a384b2c8a11a80e36298d4cb2bf1c4a5e49a",
            "0730cc8fa39b674f51036349ac7df44da285d28b6d3721d665652b6d7b61c6b6",
            "34117dde1f1934ce9435ba09823ce9d9102b9593c48caf9d02c3e582e5725248",
            "321a80bc467bcc9866c67d64ff2519274d512301710eab411f04b57a03510f92"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1745121600000,
          "end_exit_ms": 1745121600000,
          "exit_groups": 1,
          "origin_keys": [
            "1ff9ecf8923813e16032eb997cf21c0a433aa549336677e36f6014fa56a77eb8"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1745136000000,
          "end_exit_ms": 1745136000000,
          "exit_groups": 1,
          "origin_keys": [
            "332d79fd52eb33ee7336b737f5ab4bcf53ef58663ff08a81df1a66d41a256d6a"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1745294400000,
          "end_exit_ms": 1745424000000,
          "exit_groups": 3,
          "origin_keys": [
            "7aa40f87b0cb278e8b45832279daca4bac8abca0d49d2fabc816b60d9e3c269d",
            "c1dc4e7d22dd89e05c1a4a35f29b5da0d3da0e704aee1d8b4a49e2c141c5d1eb",
            "d5a849a545cf0b2d554c2eafc5ad37fdfce9c3f2b576cc136a6c77dde73a3f6e",
            "19c2b21d26a6dc35a9050fcbc4af09cdc8aed83a7e3b1330d34e7db4d3b6f069",
            "317b76a5a17a6d8dbae91124d34254774434715ce6691639741a7b746c380f5a",
            "b48e572c7fabc339508f72f03101ea76c0ad794b6e7b4bc8336cb56aca379fbc",
            "d0dc725a4068a35969b894ce83ffc09acdcca6047035e0ea225af928d5685579",
            "f33042ca93ca19f2858627222d6a7f2654e967579d43bbc61df8819cce1ab080"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1745452800000,
          "end_exit_ms": 1745683200000,
          "exit_groups": 2,
          "origin_keys": [
            "1a3ee830b2578e8fb1e059f5f1572aa09c51567bee10629b494f650001c2e863",
            "e8a331ecc6c0baefedd65ef764f894b95b0092829b65ce652b72a1c6186e10bb"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1746187200000,
          "end_exit_ms": 1746993600000,
          "exit_groups": 8,
          "origin_keys": [
            "651217e8d7efd041657b1e7a9c5bc7e59fb672d38ba02d4bac6014c41cf0fd35",
            "4727e92ff6e16ac778bcdc0e96707fd4c9de3a10c9714bac8b5a3c8e6d4f9e6e",
            "9c8ef4d1492c6e8e4c525a19eb6c9669471924747bf32dfe8e1df3437444536b",
            "c27f7a34054d119316ebcd28150c8c34450fa6ac83ea2b3be483ab6fb68e0395",
            "6b8c9b6afc6e8194dfd2fba35a528ca944dfdfb0595ca5c9f27764eee555e405",
            "15ef26907cbfa59c389b9e0e6f675c6f02c8e05513c2552b94d03ef937162ad3",
            "213cde55e6492044bf899f97d1c6f6c81413f808f3312d413e48bcde50e23d40",
            "5d91b25b2bfc5529ad6e908957284f8fc832baf1d016d0f8a8a858a82b8f95db",
            "0d13f805bd8375a5c7e70cc76dccea234e652c6dc9558c33928dafa651242888",
            "5b290cde46c429707e3e44584d82d91f5e314862a83a73371bba47c1b7524593",
            "c4682ae9ff5c786a7d30e582c3c5cfbb59773c8533f628b5bb5fe0894e07f179"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1747008000000,
          "end_exit_ms": 1747252800000,
          "exit_groups": 2,
          "origin_keys": [
            "43b37377ff657b1007fe01f75d2a087bd1cc91b8ebb108caf6589e0697b4261f",
            "76501c19ae712b20bc40e7069b22467de9a873358202c6026021ef4788fb6d44",
            "2ba0e36b341287cb46536c05b450a4247a94603300bdc62a315cbc79ace79a74",
            "421ff70eee84ac0deb03a2424325f4186677f052096d3418e5780fb585772d94"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1747454400000,
          "end_exit_ms": 1747454400000,
          "exit_groups": 1,
          "origin_keys": [
            "f51dcf5ce8bdfccee6aa184557c5fe509fe0df4128c871758d0eee1cfdff0f62"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1747699200000,
          "end_exit_ms": 1747699200000,
          "exit_groups": 1,
          "origin_keys": [
            "b4621724549076ea216593e7f1e62dcc38c262ddacef72d159d705c4fec27760"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1747929600000,
          "end_exit_ms": 1748275200000,
          "exit_groups": 3,
          "origin_keys": [
            "d8a4f2a22a84a15e76cf58b338e484119ccadf383e7993fa025f42b80aa20ab4",
            "3f2af987b6f3f292ec47627b2f41c826755e06eab37bce2071f625299b4283f8",
            "8c0dc7f28401cfd52b8e11d68d5265c1e97d5cbab20a7cada9a5eee778e20494",
            "bea8aae7dd2b88f3b8fb0ac87118bf5e97847dbbebd228e32a400dd469eb5a56"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1748577600000,
          "end_exit_ms": 1748577600000,
          "exit_groups": 1,
          "origin_keys": [
            "607282c1e194dc55fc7302787c8b6227cbd33a9e4ac41047fc92e03ab66da039"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1749556800000,
          "end_exit_ms": 1749600000000,
          "exit_groups": 2,
          "origin_keys": [
            "9da72e0fc7048ceaeb290229b35d0bc6cb2f9f7fd00749cb63402b59366edfb1",
            "2c78d1df046911c0e8e26712639b79408993001d3a0fb4aa1cd4026724301ed6"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1749643200000,
          "end_exit_ms": 1749945600000,
          "exit_groups": 4,
          "origin_keys": [
            "38226dbedb6ead810df5ecd642f6f218ac3a25e03f3e2d27b058383d802b6df2",
            "42ea167aef4705fb7b96cddae7c0e4fe11b747d6ea32169ecc2f6ebc5281b554",
            "7f6cc3be57bf316ba6327dcf693f4750ea9b260407434a578f541a5115b35480",
            "8b0fc623cb6b3463c3caf7dedfff12fbd25a3e4aa151a8327486e0356d3e58d5",
            "071a8fc6d181c5dbd6c958b2aa0afba030127ceeaa941821ce8896f9ec17898d",
            "4bf55f018f60e2b7c47e10da45f371e5b4189252ab0305f129a63cdb762985f1",
            "510d51206bee21622774635edef6571cf20cc731b8da6fcce499a8fd686c0085",
            "2c7af43ed10a363244e4a6352d0ac64054ddbcf876b57a0c4b431d25fb095dab"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1750089600000,
          "end_exit_ms": 1750089600000,
          "exit_groups": 1,
          "origin_keys": [
            "9b89ad74d25350e095ccf046576217a519b3a33d9adddbd96d0e1f654420359d"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1750147200000,
          "end_exit_ms": 1750435200000,
          "exit_groups": 2,
          "origin_keys": [
            "848ed81c901695b377b62cfd5bf8a36b5f965bc754a4bfe785294bae2c786f92",
            "90800d50e8b03a2d3a996e8c3ef0cd2c8dc07f1fee582daff91829ec622c9a94"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1751227200000,
          "end_exit_ms": 1751227200000,
          "exit_groups": 1,
          "origin_keys": [
            "42d102a378a5b35795f0d782c240d56c0788d48fa19ef92e231fc2423a8bad28"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1751284800000,
          "end_exit_ms": 1751284800000,
          "exit_groups": 1,
          "origin_keys": [
            "a26f0b129f4b901a7799eca1d74ad15072c0271af2f54d04766f502d8c9a761f"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1751328000000,
          "end_exit_ms": 1751385600000,
          "exit_groups": 2,
          "origin_keys": [
            "8518ec4cb0c2038f027c118be592ad8e0db5f1cddb80077ab7f72fbdffb2d923",
            "65096e09475306adc4c891c76c29c02fa99fab9a2e47244d727d0b96f00ca052"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1751572800000,
          "end_exit_ms": 1751616000000,
          "exit_groups": 2,
          "origin_keys": [
            "028c41dfe81ef98c19d953c5390091c4630e41252054badb5b3dd75c0681f36f",
            "174c80c4b710eb45a2197c2145cc402914a5a1af622289aaa45bbd61676116cc",
            "c07fc33fad28c4b060028aea6bb81936c15e84bd9e0e50403e5ec0be3b24eb2b"
          ]
        },
        {
          "cohort_id": 25,
          "sign": 1,
          "start_exit_ms": 1752134400000,
          "end_exit_ms": 1752264000000,
          "exit_groups": 4,
          "origin_keys": [
            "61fd039868664da73b71783bef945000d6e11c1aead59752b066304518cbd09c",
            "1240944fafce74020b7af8554bab1061254c0f1955a5b52e81ba0c3958f8eeca",
            "5bd476198e0abce265e39a155e8507e87c9237130bb2e6ed8349cf689440ef6a",
            "6faf3f413a45770dbb67ec7b20593695292e0fbedec98d2e39fe2707330b398c",
            "f8bbac66a79fa36955476264d2d7eb5f355b551a626f8dcc7d489aaa222417bc",
            "0e8dbba3aedb4982ce7ac35dee78536f26203e89072466435e644e5560f2f301"
          ]
        },
        {
          "cohort_id": 26,
          "sign": -1,
          "start_exit_ms": 1752278400000,
          "end_exit_ms": 1752552000000,
          "exit_groups": 2,
          "origin_keys": [
            "029e403f490ee0af7a14688566714675a8d3f7797468bad06b0225189a6afc85",
            "5b26655f80a4f82740d21101e61c2a08cab0698e8b51096365b3a920201fe492",
            "810f5736e541496e8326a39bc27428cd93ac5d368793b05a972a9c5216c153f5",
            "87744ef9904c7e7b931b25035bd24fc26432513fb0624437075c5d423b604d77",
            "cad9d858623b7754075c1beb3a8da4002cf5baa2fe11ffac82c9e3e12d8bd839"
          ]
        },
        {
          "cohort_id": 27,
          "sign": 1,
          "start_exit_ms": 1752710400000,
          "end_exit_ms": 1752710400000,
          "exit_groups": 1,
          "origin_keys": [
            "e90b09ece23be1880bc54aa8479ed75a2965fdc1b613f486ed88c58c8edd1598"
          ]
        },
        {
          "cohort_id": 28,
          "sign": -1,
          "start_exit_ms": 1752782400000,
          "end_exit_ms": 1752883200000,
          "exit_groups": 2,
          "origin_keys": [
            "5f7cddbe4f325f74f40d38c9b18bf6e506ca556f5ad84fb92a3ffddb40d51258",
            "6e59c8f9d32080dd4f8ed5fe6a24b368c28a21e399d77e4f15573dd136801577",
            "d66c0ef8c6d34fd04c6395652175e98134d2b7a40c27097130827385be3c6e58"
          ]
        },
        {
          "cohort_id": 29,
          "sign": 1,
          "start_exit_ms": 1753099200000,
          "end_exit_ms": 1753099200000,
          "exit_groups": 1,
          "origin_keys": [
            "3f51205dc1796ad1adfeadc494bbd4c5863874e0c53ce7fcb48aea973063220e"
          ]
        },
        {
          "cohort_id": 30,
          "sign": -1,
          "start_exit_ms": 1753128000000,
          "end_exit_ms": 1753128000000,
          "exit_groups": 1,
          "origin_keys": [
            "9dd9647d8a39eb36b7e34f9623e1d6a75ac547c828429ddcff3d4a0d9c8cc087"
          ]
        },
        {
          "cohort_id": 31,
          "sign": 1,
          "start_exit_ms": 1753156800000,
          "end_exit_ms": 1753156800000,
          "exit_groups": 1,
          "origin_keys": [
            "f45c486676dbd3d3a4819429d0ca3489955a0d09cfabfd73ea7a8515bdc9dff2"
          ]
        },
        {
          "cohort_id": 32,
          "sign": -1,
          "start_exit_ms": 1753185600000,
          "end_exit_ms": 1753185600000,
          "exit_groups": 1,
          "origin_keys": [
            "cf5928f9c26eea33ffb926dd261dd99259b061b3c1cb4f05bcea29015decd463"
          ]
        },
        {
          "cohort_id": 33,
          "sign": 1,
          "start_exit_ms": 1753531200000,
          "end_exit_ms": 1754884800000,
          "exit_groups": 8,
          "origin_keys": [
            "56b1e08156f23c243e3da6fbcac38febfb3ee44013462dd4f5315ade287c70bc",
            "4a424868c72215feacca97f6641e69efa27004c76cdda2544c6783454ba12322",
            "cd935133a58267e73f63f8806fefbcfd88414a30b69f727af02f9cd7d9bef691",
            "bca7337d28d95b209eacb4bc4e2f2911072fd93a8a2be6bbbe96b66492fa518c",
            "5d40c5ecc7cdf6ad76892cf56b726e8fa41ff383441152bbded36ac29a2f098a",
            "be2b32ea0f4e9e73e8e7a9ef86b393f512fb2bd91b8f91772f1a835b23179d71",
            "399c7f19f57243e4c46be5078e252b3267ca75789a1db615e059bab51f90a254",
            "621063760c31a86f64d450cb014e2e7485bcee9eb6c216a20a0db82f20c6d7c3",
            "d8ade007e40ef4eb72cf3d738c2b658859df52d17cf371973b47238761c59fe4",
            "794efe3c48101b2c9cb5333cf67ad058ebaca8935cdaf97654a386c7385f440c"
          ]
        },
        {
          "cohort_id": 34,
          "sign": -1,
          "start_exit_ms": 1754971200000,
          "end_exit_ms": 1754971200000,
          "exit_groups": 1,
          "origin_keys": [
            "68d8e89074bdc8af006314372d6271b890946198171b9761807745bfdc264902"
          ]
        },
        {
          "cohort_id": 35,
          "sign": 1,
          "start_exit_ms": 1755100800000,
          "end_exit_ms": 1755115200000,
          "exit_groups": 2,
          "origin_keys": [
            "62f365c2e2f8d3aaa16b0b80129fcf63647dfbf23f6f92a3b2e8a751fd7efae3",
            "a68fad5ef0a5b7393e14a94eaa517358ffb93f052b389cd4a27feafa41fce916",
            "f95db26db32541a68ce5dbc5bd6b5cb91718b4b3c1977b6dbfb0876ce8db10b5",
            "17b2a26975fded5c11bea9b2546ec44237a5aef006b45931473ef683dcb4cd7b"
          ]
        },
        {
          "cohort_id": 36,
          "sign": -1,
          "start_exit_ms": 1755201600000,
          "end_exit_ms": 1755979200000,
          "exit_groups": 5,
          "origin_keys": [
            "27113e3ad60b303097eef3e5bca59ee65b1dcce476cab7d1e411327b54e891a2",
            "9cbe0691d615c49e92840f3b511521119e16875b10cb4cc41a4cd6be26b3838e",
            "e614a4a68563d5527463efcde239dc453067de386140698e5af0566a20f1325e",
            "2fee7650c49e82eafff54d449a4b0513ac9079fb2452cdef3e73ad12c2834b15",
            "23fd530a2f8c90f3c0030813a0a68759e8f020a50639f82a61c48b2bb0f38a7d",
            "8f96664f84014a0f7bf89401922d9d41823a30dbfa656060db3b0a9f1a34831a"
          ]
        },
        {
          "cohort_id": 37,
          "sign": 1,
          "start_exit_ms": 1756022400000,
          "end_exit_ms": 1756324800000,
          "exit_groups": 2,
          "origin_keys": [
            "65ea9e92c1f61c7e9ffb6969d5d84c537ab2fc15a03ebbe9c0d0a732c731b284",
            "19f257381a58217a5939d7cd4c1c2c64d7cc5d907b7cd4abd9305f6b8f5a6231"
          ]
        },
        {
          "cohort_id": 38,
          "sign": -1,
          "start_exit_ms": 1756972800000,
          "end_exit_ms": 1757174400000,
          "exit_groups": 2,
          "origin_keys": [
            "4dcc596d8520a56a1eef4e35021fafb47b899569326732b7b4f2119e7a191316",
            "2481b5bfde897d9b0d269e40ff2cccc8d0dd0ab8acde40cf5f5b4fcde2d43bf4"
          ]
        },
        {
          "cohort_id": 39,
          "sign": 1,
          "start_exit_ms": 1757390400000,
          "end_exit_ms": 1757793600000,
          "exit_groups": 9,
          "origin_keys": [
            "aec06aed672a058a6ff7919448d20405a1327ac26aaa3d3e368c41426a8dd905",
            "a9c711c89ed3595f329e30d71aec5023a9ae4e23166aa045c6a10d66ec907d1c",
            "fde25f4d60082572dd9a4400211e0fa37f24fa934a83153f988a2348b903bede",
            "889dafdb3c2e018947739b464c01e6dc3d252f018b0cb3be1460bd2aef1e78e0",
            "12e478a3456b2a2855a12d85476484c4c37c11a41b475948d963ba52469ac61f",
            "cf1824f8a26d6dce16d051736587b4ccd639585ffd0e866600ca6fa016f8ab5b",
            "a00341b57e33033b28f134bc0f3ca0221a0aae7e9d76fe45ff0cd379696e7f99",
            "0441679b4fdbf931bc87e2f82a0c3383d78dce909e90c8d25e460fce298092fe",
            "00c37fb9fec0e2400771ea684a7aaf5dbbd5c0666c2914aa7c4e39c6cda5f62f",
            "3c5a14e98e97cdcc4ab2ccf38c7721973355239db90f0b8cf0fb15c355155599",
            "e7cc27024a48e4ac6671293c2354a37eb246bf4acb513c163b7aea48c539e441"
          ]
        },
        {
          "cohort_id": 40,
          "sign": -1,
          "start_exit_ms": 1757908800000,
          "end_exit_ms": 1758139200000,
          "exit_groups": 2,
          "origin_keys": [
            "e424189e18759eccadd99370913f8e9b252cddfccaf42c1852d16744c37bd597",
            "1fdc5307d4a393d1fdbf41f8c55c914018ffcae4971b3bfe4e4f295a56ce5ee2"
          ]
        },
        {
          "cohort_id": 41,
          "sign": 1,
          "start_exit_ms": 1758240000000,
          "end_exit_ms": 1758240000000,
          "exit_groups": 1,
          "origin_keys": [
            "486f3c379524c1142a45fd11d3bcdb20f1bc53d8cdb01e7fb4e537126a14e582",
            "9c81225d6f110ff12a13a07bcae870e54d6a1849e93a0b305fff7577a8eec6f3"
          ]
        },
        {
          "cohort_id": 42,
          "sign": -1,
          "start_exit_ms": 1758254400000,
          "end_exit_ms": 1758254400000,
          "exit_groups": 1,
          "origin_keys": [
            "7fe948ab739701f8aa5a7ce848a164a2b13c2c485cb88b599a5cd43db7a51f4a"
          ]
        },
        {
          "cohort_id": 43,
          "sign": 1,
          "start_exit_ms": 1759406400000,
          "end_exit_ms": 1759507200000,
          "exit_groups": 3,
          "origin_keys": [
            "f7aeae27fdb82045e76f7bbfe040d6f88731fbd1b2a34f371ccbaaa5a2639e56",
            "067460dcf66a1873d0a59a68f2d78fef8cf3220ebff66b5627c5bc362ee24854",
            "8bb28404f952e40910dd8b31df3f43218b5bd1129ce35fb17e12939eb1f818bd",
            "d8c6245b330fb3d85efee5fba2528d2f86b2838e7bdf2a886ddbeaf14e77b8c7"
          ]
        },
        {
          "cohort_id": 44,
          "sign": -1,
          "start_exit_ms": 1759521600000,
          "end_exit_ms": 1759867200000,
          "exit_groups": 6,
          "origin_keys": [
            "142f3c05986dedbc643129262daca1c167ef3df51148b2a3a6f8490d1879f369",
            "78e988a010021cbb5c018d83195a643d469d02d5d2a9628eda0bf99223c21ea1",
            "d0c76540e54462481bd9d1f388240d47ec6ae641dbcf351cb2bcb22abcf10533",
            "9b4475a2c982a9a94d086845b5e325506c6c4eefb8f61e71eaf86541e2534191",
            "f873f68d0a80abea8338b94ef2152f8c550ed8445b00be347762659c758c34df",
            "7af08e6b7a4d1d43d659254188b5565884a4a312f584cf239069c1875f358114",
            "8082a86edee77e64280cca625b536a7485f9ab1a480adfe82dc68b93083b05ad",
            "906e76e912338f93b9da511b7644c861a4ece4574e5a3007c3cf5981b3f888bf",
            "c7ec5447b386898c4b04633f1a5f2aee9ec4d519e1df5333bedbd18f48e9297c",
            "2b88ec6a908124277534b0093bc34896e2c3ab30a730ffea82533de58facce29"
          ]
        },
        {
          "cohort_id": 45,
          "sign": 1,
          "start_exit_ms": 1761566400000,
          "end_exit_ms": 1761580800000,
          "exit_groups": 2,
          "origin_keys": [
            "070d1359333c645cb6deb528ee4a2f5a15bf7ca9dc7374005ab63f59679e0365",
            "55c3ae44b005f777ae6235a4d51479c9caa8b92b8d4dc1f2b59cc7cf7a43e256",
            "a0c5f502cb345b714fc91e81e9486695f0c1f236cb6348d8948d65c27b24a0f1"
          ]
        },
        {
          "cohort_id": 46,
          "sign": -1,
          "start_exit_ms": 1761609600000,
          "end_exit_ms": 1763899200000,
          "exit_groups": 2,
          "origin_keys": [
            "7c4452f1281bf5fd9996b5808886553a4ccb61768a7fe37cb5cd553172551696",
            "a17c1e54eafc10441c36c074c134b469d9507ff65c2a102fb48a2c79da7a2421",
            "394cba2137039eae01aa1fe7e77aa1ed3cec1995668905561b14417b5b2bfe3a"
          ]
        },
        {
          "cohort_id": 47,
          "sign": 1,
          "start_exit_ms": 1764835200000,
          "end_exit_ms": 1764835200000,
          "exit_groups": 1,
          "origin_keys": [
            "225f2c0c74dec674d14dd2542a98b87735badb7593e5ebf32d4b6af32309c910",
            "822d8ddf2416c697673994ade0628e3cc865edc859393fa9331567774a642bed"
          ]
        },
        {
          "cohort_id": 48,
          "sign": -1,
          "start_exit_ms": 1764950400000,
          "end_exit_ms": 1764950400000,
          "exit_groups": 1,
          "origin_keys": [
            "c134e390978dec23db3f41b5cb1738859821bea146f23f8dce16cb21a0af9b4f"
          ]
        },
        {
          "cohort_id": 49,
          "sign": 1,
          "start_exit_ms": 1765382400000,
          "end_exit_ms": 1765382400000,
          "exit_groups": 1,
          "origin_keys": [
            "b9bdb4c2b4b149a2d8e6a8832b0991c8121ea44e8054055c1744eb5651743083"
          ]
        },
        {
          "cohort_id": 50,
          "sign": -1,
          "start_exit_ms": 1766260800000,
          "end_exit_ms": 1766260800000,
          "exit_groups": 1,
          "origin_keys": [
            "8a83a5405cac111554da01fe93fe67c9e6a89e6f274eb063b5e58d3465ef8d28"
          ]
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 454.74398204614477,
          "BCH-USDT": -3009.6146332407943,
          "BTC-USDT": 757.0287676809164,
          "ETH-USDT": 3502.3585664505276,
          "HYPE-USDT": 705.6344235242639,
          "LINK-USDT": 930.7691377124551,
          "SOL-USDT": 1607.416829177162
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 5962.493553194487,
          "BCH-USDT": 1562.8446745964952,
          "BTC-USDT": 2144.2729214586807,
          "ETH-USDT": 6774.912488155272,
          "HYPE-USDT": 6114.2975417331045,
          "LINK-USDT": 5025.579036116026,
          "SOL-USDT": 4771.6718357807285
        },
        "total_positive_trade_profit_bps": 32356.072051034796,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.20938612318174138,
        "winner_T": 65,
        "top_decile_winner_T": 7,
        "top_decile_winners_share": 0.38477640360367804,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": -644.5578879101743,
          "2025-03": -2125.0080184625754,
          "2025-04": 1698.5705190285144,
          "2025-05": 7675.804808505799,
          "2025-06": -2806.51476815147,
          "2025-07": 3094.2616787312145,
          "2025-08": 504.8520329751011,
          "2025-09": 1731.2799086079988,
          "2025-10": -2172.668611791748,
          "2025-11": -228.60518742291222,
          "2025-12": -1779.0774007590715
        },
        "top_positive_month_share": 0.5219942479700643
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 1,
          "net_trade_sum_bps": -281.79679750602315
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 1,
          "net_trade_sum_bps": -362.76109040415116
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": -433.9615253986916
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 1,
          "net_trade_sum_bps": -743.8801974995291
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 7,
          "net_trade_sum_bps": -947.1662955643548
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 3,
          "net_trade_sum_bps": -362.54416523867076
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 2,
          "net_trade_sum_bps": -281.6845495942665
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 11,
          "net_trade_sum_bps": 2342.7992338614517
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 1,
          "net_trade_sum_bps": -44.60125679655256
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 10,
          "net_trade_sum_bps": 8881.095552539457
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 5,
          "net_trade_sum_bps": -1577.7988160969912
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 4,
          "net_trade_sum_bps": 973.0654236806745
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 2,
          "net_trade_sum_bps": -555.9560948207877
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 10,
          "net_trade_sum_bps": -2536.5771488254863
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 3,
          "net_trade_sum_bps": -627.3543201944053
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 7,
          "net_trade_sum_bps": -1135.6007150582636
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 10,
          "net_trade_sum_bps": 4419.4015547356685
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 5,
          "net_trade_sum_bps": 197.81438549259175
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 5,
          "net_trade_sum_bps": -267.71509288957435
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 1,
          "net_trade_sum_bps": 237.77824731921362
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 3,
          "net_trade_sum_bps": 2718.4641368344915
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 13,
          "net_trade_sum_bps": -643.4759440035976
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 3,
          "net_trade_sum_bps": -958.7682928987617
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 2,
          "net_trade_sum_bps": -611.3678669570311
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 2,
          "net_trade_sum_bps": -525.072330872297
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 11,
          "net_trade_sum_bps": 2947.1425386771543
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 5,
          "net_trade_sum_bps": -690.7902991968583
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 9,
          "net_trade_sum_bps": 96.97148590831821
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 5,
          "net_trade_sum_bps": -1927.3999703265874
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 5,
          "net_trade_sum_bps": -342.2401273734787
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 1,
          "net_trade_sum_bps": -228.60518742291222
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 3,
          "net_trade_sum_bps": -1101.5877331592417
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 1,
          "net_trade_sum_bps": -188.8949707515819
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 1,
          "net_trade_sum_bps": -488.59469684824796
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1738425600000,
          "end_exit_ms": 1741060800000,
          "exit_groups": 3,
          "origin_keys": [
            "e1393b13ce9e62f6eb17d5c6206939eb2852acc688d6eb1e60d64655016ab17c",
            "a99278759b8e91aa7cdc7c3aefa7607831e082cc0daa3f2a56dd8ecd56682920",
            "438f3504500ed30e519cdf08501ea04d70d093f94287d91b697b6e437d20800d"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1741348800000,
          "end_exit_ms": 1741348800000,
          "exit_groups": 1,
          "origin_keys": [
            "503ff6a0363ff8e8203078e9fbb189950e1576469014e15bf8f9986e767d5265"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1742328000000,
          "end_exit_ms": 1742328000000,
          "exit_groups": 1,
          "origin_keys": [
            "2d8378ea4c8c85828631ce65eef9f301a2b6921a2eadd391324d5e64fa72f507"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1742774400000,
          "end_exit_ms": 1742774400000,
          "exit_groups": 1,
          "origin_keys": [
            "0d5e3b780a55f9d0b89de38f6f5397fd5a9346de8509d98e1985489c20b3c79e"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1742904000000,
          "end_exit_ms": 1742904000000,
          "exit_groups": 1,
          "origin_keys": [
            "49c17bcfd2e02b28bc452bc57a61822c7ab58faf688d0bb895708a2b71583793",
            "ec1914fd8dfd666abc394005c178938ae9100a41add23d56bc9d71732738cf3e"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1742918400000,
          "end_exit_ms": 1742961600000,
          "exit_groups": 2,
          "origin_keys": [
            "d87c44b0d3bd96b0d46da6aad6ac4b85cf487aed8a1d2d25071c29dae13a01cc",
            "a4f1702ef521f42f52ce4cb17de0f23b603fb2804dfdc4dc96b8b3b4a0c38b60"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1743004800000,
          "end_exit_ms": 1745164800000,
          "exit_groups": 6,
          "origin_keys": [
            "7f951ddccc04c7f115ced11144784c6deb4c060fc633ee873968203f21a9ea51",
            "b4313ed8c4be45927f975d025634067c32d0269604ef7cd4d63a2e13e4ba8aa1",
            "00adbc073c8872856db73cacefd0a384b2c8a11a80e36298d4cb2bf1c4a5e49a",
            "0730cc8fa39b674f51036349ac7df44da285d28b6d3721d665652b6d7b61c6b6",
            "34117dde1f1934ce9435ba09823ce9d9102b9593c48caf9d02c3e582e5725248",
            "321a80bc467bcc9866c67d64ff2519274d512301710eab411f04b57a03510f92",
            "1ff9ecf8923813e16032eb997cf21c0a433aa549336677e36f6014fa56a77eb8"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1745222400000,
          "end_exit_ms": 1745380800000,
          "exit_groups": 3,
          "origin_keys": [
            "332d79fd52eb33ee7336b737f5ab4bcf53ef58663ff08a81df1a66d41a256d6a",
            "c1dc4e7d22dd89e05c1a4a35f29b5da0d3da0e704aee1d8b4a49e2c141c5d1eb",
            "7aa40f87b0cb278e8b45832279daca4bac8abca0d49d2fabc816b60d9e3c269d"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1745424000000,
          "end_exit_ms": 1745452800000,
          "exit_groups": 2,
          "origin_keys": [
            "b48e572c7fabc339508f72f03101ea76c0ad794b6e7b4bc8336cb56aca379fbc",
            "1a3ee830b2578e8fb1e059f5f1572aa09c51567bee10629b494f650001c2e863"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1745496000000,
          "end_exit_ms": 1745510400000,
          "exit_groups": 2,
          "origin_keys": [
            "d5a849a545cf0b2d554c2eafc5ad37fdfce9c3f2b576cc136a6c77dde73a3f6e",
            "19c2b21d26a6dc35a9050fcbc4af09cdc8aed83a7e3b1330d34e7db4d3b6f069",
            "317b76a5a17a6d8dbae91124d34254774434715ce6691639741a7b746c380f5a",
            "d0dc725a4068a35969b894ce83ffc09acdcca6047035e0ea225af928d5685579",
            "f33042ca93ca19f2858627222d6a7f2654e967579d43bbc61df8819cce1ab080"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1745683200000,
          "end_exit_ms": 1746273600000,
          "exit_groups": 2,
          "origin_keys": [
            "e8a331ecc6c0baefedd65ef764f894b95b0092829b65ce652b72a1c6186e10bb",
            "651217e8d7efd041657b1e7a9c5bc7e59fb672d38ba02d4bac6014c41cf0fd35"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1746849600000,
          "end_exit_ms": 1746993600000,
          "exit_groups": 7,
          "origin_keys": [
            "4727e92ff6e16ac778bcdc0e96707fd4c9de3a10c9714bac8b5a3c8e6d4f9e6e",
            "9c8ef4d1492c6e8e4c525a19eb6c9669471924747bf32dfe8e1df3437444536b",
            "c27f7a34054d119316ebcd28150c8c34450fa6ac83ea2b3be483ab6fb68e0395",
            "0d13f805bd8375a5c7e70cc76dccea234e652c6dc9558c33928dafa651242888",
            "6b8c9b6afc6e8194dfd2fba35a528ca944dfdfb0595ca5c9f27764eee555e405",
            "15ef26907cbfa59c389b9e0e6f675c6f02c8e05513c2552b94d03ef937162ad3",
            "213cde55e6492044bf899f97d1c6f6c81413f808f3312d413e48bcde50e23d40",
            "5d91b25b2bfc5529ad6e908957284f8fc832baf1d016d0f8a8a858a82b8f95db",
            "5b290cde46c429707e3e44584d82d91f5e314862a83a73371bba47c1b7524593",
            "c4682ae9ff5c786a7d30e582c3c5cfbb59773c8533f628b5bb5fe0894e07f179"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1747008000000,
          "end_exit_ms": 1747252800000,
          "exit_groups": 2,
          "origin_keys": [
            "43b37377ff657b1007fe01f75d2a087bd1cc91b8ebb108caf6589e0697b4261f",
            "76501c19ae712b20bc40e7069b22467de9a873358202c6026021ef4788fb6d44",
            "2ba0e36b341287cb46536c05b450a4247a94603300bdc62a315cbc79ace79a74",
            "421ff70eee84ac0deb03a2424325f4186677f052096d3418e5780fb585772d94"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1747454400000,
          "end_exit_ms": 1747454400000,
          "exit_groups": 1,
          "origin_keys": [
            "f51dcf5ce8bdfccee6aa184557c5fe509fe0df4128c871758d0eee1cfdff0f62"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1747699200000,
          "end_exit_ms": 1748016000000,
          "exit_groups": 2,
          "origin_keys": [
            "b4621724549076ea216593e7f1e62dcc38c262ddacef72d159d705c4fec27760",
            "d8a4f2a22a84a15e76cf58b338e484119ccadf383e7993fa025f42b80aa20ab4"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1748059200000,
          "end_exit_ms": 1748059200000,
          "exit_groups": 1,
          "origin_keys": [
            "3f2af987b6f3f292ec47627b2f41c826755e06eab37bce2071f625299b4283f8",
            "8c0dc7f28401cfd52b8e11d68d5265c1e97d5cbab20a7cada9a5eee778e20494"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1748361600000,
          "end_exit_ms": 1749643200000,
          "exit_groups": 3,
          "origin_keys": [
            "bea8aae7dd2b88f3b8fb0ac87118bf5e97847dbbebd228e32a400dd469eb5a56",
            "607282c1e194dc55fc7302787c8b6227cbd33a9e4ac41047fc92e03ab66da039",
            "38226dbedb6ead810df5ecd642f6f218ac3a25e03f3e2d27b058383d802b6df2",
            "9da72e0fc7048ceaeb290229b35d0bc6cb2f9f7fd00749cb63402b59366edfb1"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1749686400000,
          "end_exit_ms": 1749686400000,
          "exit_groups": 1,
          "origin_keys": [
            "2c78d1df046911c0e8e26712639b79408993001d3a0fb4aa1cd4026724301ed6"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1749700800000,
          "end_exit_ms": 1749945600000,
          "exit_groups": 4,
          "origin_keys": [
            "42ea167aef4705fb7b96cddae7c0e4fe11b747d6ea32169ecc2f6ebc5281b554",
            "8b0fc623cb6b3463c3caf7dedfff12fbd25a3e4aa151a8327486e0356d3e58d5",
            "7f6cc3be57bf316ba6327dcf693f4750ea9b260407434a578f541a5115b35480",
            "071a8fc6d181c5dbd6c958b2aa0afba030127ceeaa941821ce8896f9ec17898d",
            "4bf55f018f60e2b7c47e10da45f371e5b4189252ab0305f129a63cdb762985f1",
            "510d51206bee21622774635edef6571cf20cc731b8da6fcce499a8fd686c0085",
            "2c7af43ed10a363244e4a6352d0ac64054ddbcf876b57a0c4b431d25fb095dab"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1750089600000,
          "end_exit_ms": 1750089600000,
          "exit_groups": 1,
          "origin_keys": [
            "9b89ad74d25350e095ccf046576217a519b3a33d9adddbd96d0e1f654420359d"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1750147200000,
          "end_exit_ms": 1751284800000,
          "exit_groups": 3,
          "origin_keys": [
            "848ed81c901695b377b62cfd5bf8a36b5f965bc754a4bfe785294bae2c786f92",
            "90800d50e8b03a2d3a996e8c3ef0cd2c8dc07f1fee582daff91829ec622c9a94",
            "a26f0b129f4b901a7799eca1d74ad15072c0271af2f54d04766f502d8c9a761f"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1751313600000,
          "end_exit_ms": 1751313600000,
          "exit_groups": 1,
          "origin_keys": [
            "42d102a378a5b35795f0d782c240d56c0788d48fa19ef92e231fc2423a8bad28"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1751356800000,
          "end_exit_ms": 1751616000000,
          "exit_groups": 4,
          "origin_keys": [
            "8518ec4cb0c2038f027c118be592ad8e0db5f1cddb80077ab7f72fbdffb2d923",
            "65096e09475306adc4c891c76c29c02fa99fab9a2e47244d727d0b96f00ca052",
            "028c41dfe81ef98c19d953c5390091c4630e41252054badb5b3dd75c0681f36f",
            "174c80c4b710eb45a2197c2145cc402914a5a1af622289aaa45bbd61676116cc",
            "c07fc33fad28c4b060028aea6bb81936c15e84bd9e0e50403e5ec0be3b24eb2b"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1752177600000,
          "end_exit_ms": 1752264000000,
          "exit_groups": 4,
          "origin_keys": [
            "5bd476198e0abce265e39a155e8507e87c9237130bb2e6ed8349cf689440ef6a",
            "6faf3f413a45770dbb67ec7b20593695292e0fbedec98d2e39fe2707330b398c",
            "61fd039868664da73b71783bef945000d6e11c1aead59752b066304518cbd09c",
            "1240944fafce74020b7af8554bab1061254c0f1955a5b52e81ba0c3958f8eeca",
            "f8bbac66a79fa36955476264d2d7eb5f355b551a626f8dcc7d489aaa222417bc"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1752336000000,
          "end_exit_ms": 1752336000000,
          "exit_groups": 1,
          "origin_keys": [
            "5b26655f80a4f82740d21101e61c2a08cab0698e8b51096365b3a920201fe492"
          ]
        },
        {
          "cohort_id": 25,
          "sign": 1,
          "start_exit_ms": 1752350400000,
          "end_exit_ms": 1752350400000,
          "exit_groups": 1,
          "origin_keys": [
            "0e8dbba3aedb4982ce7ac35dee78536f26203e89072466435e644e5560f2f301"
          ]
        },
        {
          "cohort_id": 26,
          "sign": -1,
          "start_exit_ms": 1752364800000,
          "end_exit_ms": 1752782400000,
          "exit_groups": 3,
          "origin_keys": [
            "029e403f490ee0af7a14688566714675a8d3f7797468bad06b0225189a6afc85",
            "810f5736e541496e8326a39bc27428cd93ac5d368793b05a972a9c5216c153f5",
            "87744ef9904c7e7b931b25035bd24fc26432513fb0624437075c5d423b604d77",
            "cad9d858623b7754075c1beb3a8da4002cf5baa2fe11ffac82c9e3e12d8bd839",
            "5f7cddbe4f325f74f40d38c9b18bf6e506ca556f5ad84fb92a3ffddb40d51258"
          ]
        },
        {
          "cohort_id": 27,
          "sign": 1,
          "start_exit_ms": 1752796800000,
          "end_exit_ms": 1752868800000,
          "exit_groups": 2,
          "origin_keys": [
            "e90b09ece23be1880bc54aa8479ed75a2965fdc1b613f486ed88c58c8edd1598",
            "6e59c8f9d32080dd4f8ed5fe6a24b368c28a21e399d77e4f15573dd136801577"
          ]
        },
        {
          "cohort_id": 28,
          "sign": -1,
          "start_exit_ms": 1752883200000,
          "end_exit_ms": 1753185600000,
          "exit_groups": 4,
          "origin_keys": [
            "d66c0ef8c6d34fd04c6395652175e98134d2b7a40c27097130827385be3c6e58",
            "9dd9647d8a39eb36b7e34f9623e1d6a75ac547c828429ddcff3d4a0d9c8cc087",
            "3f51205dc1796ad1adfeadc494bbd4c5863874e0c53ce7fcb48aea973063220e",
            "cf5928f9c26eea33ffb926dd261dd99259b061b3c1cb4f05bcea29015decd463"
          ]
        },
        {
          "cohort_id": 29,
          "sign": 1,
          "start_exit_ms": 1753243200000,
          "end_exit_ms": 1754899200000,
          "exit_groups": 8,
          "origin_keys": [
            "f45c486676dbd3d3a4819429d0ca3489955a0d09cfabfd73ea7a8515bdc9dff2",
            "56b1e08156f23c243e3da6fbcac38febfb3ee44013462dd4f5315ade287c70bc",
            "4a424868c72215feacca97f6641e69efa27004c76cdda2544c6783454ba12322",
            "cd935133a58267e73f63f8806fefbcfd88414a30b69f727af02f9cd7d9bef691",
            "bca7337d28d95b209eacb4bc4e2f2911072fd93a8a2be6bbbe96b66492fa518c",
            "5d40c5ecc7cdf6ad76892cf56b726e8fa41ff383441152bbded36ac29a2f098a",
            "be2b32ea0f4e9e73e8e7a9ef86b393f512fb2bd91b8f91772f1a835b23179d71",
            "399c7f19f57243e4c46be5078e252b3267ca75789a1db615e059bab51f90a254",
            "621063760c31a86f64d450cb014e2e7485bcee9eb6c216a20a0db82f20c6d7c3",
            "d8ade007e40ef4eb72cf3d738c2b658859df52d17cf371973b47238761c59fe4"
          ]
        },
        {
          "cohort_id": 30,
          "sign": -1,
          "start_exit_ms": 1754971200000,
          "end_exit_ms": 1757174400000,
          "exit_groups": 11,
          "origin_keys": [
            "68d8e89074bdc8af006314372d6271b890946198171b9761807745bfdc264902",
            "794efe3c48101b2c9cb5333cf67ad058ebaca8935cdaf97654a386c7385f440c",
            "62f365c2e2f8d3aaa16b0b80129fcf63647dfbf23f6f92a3b2e8a751fd7efae3",
            "a68fad5ef0a5b7393e14a94eaa517358ffb93f052b389cd4a27feafa41fce916",
            "f95db26db32541a68ce5dbc5bd6b5cb91718b4b3c1977b6dbfb0876ce8db10b5",
            "17b2a26975fded5c11bea9b2546ec44237a5aef006b45931473ef683dcb4cd7b",
            "27113e3ad60b303097eef3e5bca59ee65b1dcce476cab7d1e411327b54e891a2",
            "9cbe0691d615c49e92840f3b511521119e16875b10cb4cc41a4cd6be26b3838e",
            "e614a4a68563d5527463efcde239dc453067de386140698e5af0566a20f1325e",
            "2fee7650c49e82eafff54d449a4b0513ac9079fb2452cdef3e73ad12c2834b15",
            "23fd530a2f8c90f3c0030813a0a68759e8f020a50639f82a61c48b2bb0f38a7d",
            "8f96664f84014a0f7bf89401922d9d41823a30dbfa656060db3b0a9f1a34831a",
            "65ea9e92c1f61c7e9ffb6969d5d84c537ab2fc15a03ebbe9c0d0a732c731b284",
            "19f257381a58217a5939d7cd4c1c2c64d7cc5d907b7cd4abd9305f6b8f5a6231",
            "4dcc596d8520a56a1eef4e35021fafb47b899569326732b7b4f2119e7a191316",
            "2481b5bfde897d9b0d269e40ff2cccc8d0dd0ab8acde40cf5f5b4fcde2d43bf4"
          ]
        },
        {
          "cohort_id": 31,
          "sign": 1,
          "start_exit_ms": 1757476800000,
          "end_exit_ms": 1757779200000,
          "exit_groups": 6,
          "origin_keys": [
            "aec06aed672a058a6ff7919448d20405a1327ac26aaa3d3e368c41426a8dd905",
            "889dafdb3c2e018947739b464c01e6dc3d252f018b0cb3be1460bd2aef1e78e0",
            "a9c711c89ed3595f329e30d71aec5023a9ae4e23166aa045c6a10d66ec907d1c",
            "fde25f4d60082572dd9a4400211e0fa37f24fa934a83153f988a2348b903bede",
            "12e478a3456b2a2855a12d85476484c4c37c11a41b475948d963ba52469ac61f",
            "cf1824f8a26d6dce16d051736587b4ccd639585ffd0e866600ca6fa016f8ab5b",
            "a00341b57e33033b28f134bc0f3ca0221a0aae7e9d76fe45ff0cd379696e7f99"
          ]
        },
        {
          "cohort_id": 32,
          "sign": -1,
          "start_exit_ms": 1757793600000,
          "end_exit_ms": 1757793600000,
          "exit_groups": 1,
          "origin_keys": [
            "e7cc27024a48e4ac6671293c2354a37eb246bf4acb513c163b7aea48c539e441"
          ]
        },
        {
          "cohort_id": 33,
          "sign": 1,
          "start_exit_ms": 1757808000000,
          "end_exit_ms": 1757822400000,
          "exit_groups": 2,
          "origin_keys": [
            "0441679b4fdbf931bc87e2f82a0c3383d78dce909e90c8d25e460fce298092fe",
            "00c37fb9fec0e2400771ea684a7aaf5dbbd5c0666c2914aa7c4e39c6cda5f62f"
          ]
        },
        {
          "cohort_id": 34,
          "sign": -1,
          "start_exit_ms": 1757865600000,
          "end_exit_ms": 1758268800000,
          "exit_groups": 5,
          "origin_keys": [
            "3c5a14e98e97cdcc4ab2ccf38c7721973355239db90f0b8cf0fb15c355155599",
            "e424189e18759eccadd99370913f8e9b252cddfccaf42c1852d16744c37bd597",
            "1fdc5307d4a393d1fdbf41f8c55c914018ffcae4971b3bfe4e4f295a56ce5ee2",
            "7fe948ab739701f8aa5a7ce848a164a2b13c2c485cb88b599a5cd43db7a51f4a",
            "9c81225d6f110ff12a13a07bcae870e54d6a1849e93a0b305fff7577a8eec6f3",
            "486f3c379524c1142a45fd11d3bcdb20f1bc53d8cdb01e7fb4e537126a14e582"
          ]
        },
        {
          "cohort_id": 35,
          "sign": 1,
          "start_exit_ms": 1759492800000,
          "end_exit_ms": 1759492800000,
          "exit_groups": 1,
          "origin_keys": [
            "f7aeae27fdb82045e76f7bbfe040d6f88731fbd1b2a34f371ccbaaa5a2639e56"
          ]
        },
        {
          "cohort_id": 36,
          "sign": -1,
          "start_exit_ms": 1759521600000,
          "end_exit_ms": 1759521600000,
          "exit_groups": 1,
          "origin_keys": [
            "142f3c05986dedbc643129262daca1c167ef3df51148b2a3a6f8490d1879f369",
            "78e988a010021cbb5c018d83195a643d469d02d5d2a9628eda0bf99223c21ea1",
            "d0c76540e54462481bd9d1f388240d47ec6ae641dbcf351cb2bcb22abcf10533"
          ]
        },
        {
          "cohort_id": 37,
          "sign": 1,
          "start_exit_ms": 1759550400000,
          "end_exit_ms": 1759550400000,
          "exit_groups": 1,
          "origin_keys": [
            "067460dcf66a1873d0a59a68f2d78fef8cf3220ebff66b5627c5bc362ee24854",
            "8bb28404f952e40910dd8b31df3f43218b5bd1129ce35fb17e12939eb1f818bd"
          ]
        },
        {
          "cohort_id": 38,
          "sign": -1,
          "start_exit_ms": 1759564800000,
          "end_exit_ms": 1759564800000,
          "exit_groups": 1,
          "origin_keys": [
            "9b4475a2c982a9a94d086845b5e325506c6c4eefb8f61e71eaf86541e2534191"
          ]
        },
        {
          "cohort_id": 39,
          "sign": 1,
          "start_exit_ms": 1759593600000,
          "end_exit_ms": 1759593600000,
          "exit_groups": 1,
          "origin_keys": [
            "d8c6245b330fb3d85efee5fba2528d2f86b2838e7bdf2a886ddbeaf14e77b8c7"
          ]
        },
        {
          "cohort_id": 40,
          "sign": -1,
          "start_exit_ms": 1759608000000,
          "end_exit_ms": 1761566400000,
          "exit_groups": 5,
          "origin_keys": [
            "f873f68d0a80abea8338b94ef2152f8c550ed8445b00be347762659c758c34df",
            "7af08e6b7a4d1d43d659254188b5565884a4a312f584cf239069c1875f358114",
            "8082a86edee77e64280cca625b536a7485f9ab1a480adfe82dc68b93083b05ad",
            "906e76e912338f93b9da511b7644c861a4ece4574e5a3007c3cf5981b3f888bf",
            "c7ec5447b386898c4b04633f1a5f2aee9ec4d519e1df5333bedbd18f48e9297c",
            "2b88ec6a908124277534b0093bc34896e2c3ab30a730ffea82533de58facce29",
            "070d1359333c645cb6deb528ee4a2f5a15bf7ca9dc7374005ab63f59679e0365"
          ]
        },
        {
          "cohort_id": 41,
          "sign": 1,
          "start_exit_ms": 1761652800000,
          "end_exit_ms": 1761652800000,
          "exit_groups": 1,
          "origin_keys": [
            "55c3ae44b005f777ae6235a4d51479c9caa8b92b8d4dc1f2b59cc7cf7a43e256"
          ]
        },
        {
          "cohort_id": 42,
          "sign": -1,
          "start_exit_ms": 1761667200000,
          "end_exit_ms": 1766260800000,
          "exit_groups": 8,
          "origin_keys": [
            "a0c5f502cb345b714fc91e81e9486695f0c1f236cb6348d8948d65c27b24a0f1",
            "a17c1e54eafc10441c36c074c134b469d9507ff65c2a102fb48a2c79da7a2421",
            "7c4452f1281bf5fd9996b5808886553a4ccb61768a7fe37cb5cd553172551696",
            "394cba2137039eae01aa1fe7e77aa1ed3cec1995668905561b14417b5b2bfe3a",
            "225f2c0c74dec674d14dd2542a98b87735badb7593e5ebf32d4b6af32309c910",
            "822d8ddf2416c697673994ade0628e3cc865edc859393fa9331567774a642bed",
            "c134e390978dec23db3f41b5cb1738859821bea146f23f8dce16cb21a0af9b4f",
            "b9bdb4c2b4b149a2d8e6a8832b0991c8121ea44e8054055c1744eb5651743083",
            "8a83a5405cac111554da01fe93fe67c9e6a89e6f274eb063b5e58d3465ef8d28"
          ]
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 616.6013092604451,
          "BCH-USDT": -3009.6146332407943,
          "BTC-USDT": 407.160900803441,
          "ETH-USDT": 3721.7664775516673,
          "HYPE-USDT": 2023.9369368334883,
          "LINK-USDT": 917.6278143088979,
          "SOL-USDT": 2415.617912272111
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 5962.493553194487,
          "BCH-USDT": 1562.8446745964952,
          "BTC-USDT": 1777.5536986928216,
          "ETH-USDT": 6418.412929216753,
          "HYPE-USDT": 6018.167799309975,
          "LINK-USDT": 4273.61652731122,
          "SOL-USDT": 4276.773077756106
        },
        "total_positive_trade_profit_bps": 30289.862260077858,
        "top_one_symbol_by_positive_trade_profit": "ETH-USDT",
        "top_one_symbol_profit_share": 0.21189970671065886,
        "winner_T": 57,
        "top_decile_winner_T": 6,
        "top_decile_winners_share": 0.37611359602332856,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": -644.5578879101743,
          "2025-03": -1697.4547156142476,
          "2025-04": 1467.731767324329,
          "2025-05": 7857.027616528876,
          "2025-06": -1116.9640597228447,
          "2025-07": 3538.8123046918777,
          "2025-08": 847.6305994782157,
          "2025-09": 1140.2514081602465,
          "2025-10": -2291.6977269650383,
          "2025-11": -228.60518742291222,
          "2025-12": -1779.0774007590715
        },
        "top_positive_month_share": 0.5290409799108041
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 1,
          "net_trade_sum_bps": -281.79679750602315
        },
        {
          "utc_monday_ms": 1739145600000,
          "T": 1,
          "net_trade_sum_bps": -362.76109040415116
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": -433.9615253986916
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 1,
          "net_trade_sum_bps": -743.8801974995291
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 6,
          "net_trade_sum_bps": -519.6129927160267
        },
        {
          "utc_monday_ms": 1743984000000,
          "T": 3,
          "net_trade_sum_bps": -362.54416523867076
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 2,
          "net_trade_sum_bps": -281.6845495942665
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 10,
          "net_trade_sum_bps": 2111.960482157266
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 1,
          "net_trade_sum_bps": -44.60125679655256
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 8,
          "net_trade_sum_bps": 8670.011122205597
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 5,
          "net_trade_sum_bps": -1185.4915777400554
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 4,
          "net_trade_sum_bps": 973.0654236806745
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 2,
          "net_trade_sum_bps": -555.9560948207877
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 7,
          "net_trade_sum_bps": -847.0264403968608
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 3,
          "net_trade_sum_bps": -627.3543201944053
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 6,
          "net_trade_sum_bps": -901.8850645469768
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 8,
          "net_trade_sum_bps": 4630.236530185045
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 5,
          "net_trade_sum_bps": 197.81438549259175
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 5,
          "net_trade_sum_bps": -267.71509288957435
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 1,
          "net_trade_sum_bps": 237.77824731921362
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 3,
          "net_trade_sum_bps": 2718.4641368344915
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 9,
          "net_trade_sum_bps": -300.697377500483
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 3,
          "net_trade_sum_bps": -958.7682928987617
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 2,
          "net_trade_sum_bps": -611.3678669570311
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 2,
          "net_trade_sum_bps": -525.072330872297
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 9,
          "net_trade_sum_bps": 2356.114038229402
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 5,
          "net_trade_sum_bps": -690.7902991968583
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 8,
          "net_trade_sum_bps": -22.057629264972086
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 5,
          "net_trade_sum_bps": -1927.3999703265874
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 5,
          "net_trade_sum_bps": -342.2401273734787
        },
        {
          "utc_monday_ms": 1763337600000,
          "T": 1,
          "net_trade_sum_bps": -228.60518742291222
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 3,
          "net_trade_sum_bps": -1101.5877331592417
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 1,
          "net_trade_sum_bps": -188.8949707515819
        },
        {
          "utc_monday_ms": 1765756800000,
          "T": 1,
          "net_trade_sum_bps": -488.59469684824796
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1738425600000,
          "end_exit_ms": 1741060800000,
          "exit_groups": 3,
          "origin_keys": [
            "e1393b13ce9e62f6eb17d5c6206939eb2852acc688d6eb1e60d64655016ab17c",
            "a99278759b8e91aa7cdc7c3aefa7607831e082cc0daa3f2a56dd8ecd56682920",
            "438f3504500ed30e519cdf08501ea04d70d093f94287d91b697b6e437d20800d"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1741348800000,
          "end_exit_ms": 1741348800000,
          "exit_groups": 1,
          "origin_keys": [
            "503ff6a0363ff8e8203078e9fbb189950e1576469014e15bf8f9986e767d5265"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1742328000000,
          "end_exit_ms": 1742328000000,
          "exit_groups": 1,
          "origin_keys": [
            "2d8378ea4c8c85828631ce65eef9f301a2b6921a2eadd391324d5e64fa72f507"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1742774400000,
          "end_exit_ms": 1742774400000,
          "exit_groups": 1,
          "origin_keys": [
            "0d5e3b780a55f9d0b89de38f6f5397fd5a9346de8509d98e1985489c20b3c79e"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1742904000000,
          "end_exit_ms": 1742904000000,
          "exit_groups": 1,
          "origin_keys": [
            "49c17bcfd2e02b28bc452bc57a61822c7ab58faf688d0bb895708a2b71583793",
            "ec1914fd8dfd666abc394005c178938ae9100a41add23d56bc9d71732738cf3e"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1742918400000,
          "end_exit_ms": 1742961600000,
          "exit_groups": 2,
          "origin_keys": [
            "d87c44b0d3bd96b0d46da6aad6ac4b85cf487aed8a1d2d25071c29dae13a01cc",
            "a4f1702ef521f42f52ce4cb17de0f23b603fb2804dfdc4dc96b8b3b4a0c38b60"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1743076800000,
          "end_exit_ms": 1745164800000,
          "exit_groups": 5,
          "origin_keys": [
            "b4313ed8c4be45927f975d025634067c32d0269604ef7cd4d63a2e13e4ba8aa1",
            "00adbc073c8872856db73cacefd0a384b2c8a11a80e36298d4cb2bf1c4a5e49a",
            "0730cc8fa39b674f51036349ac7df44da285d28b6d3721d665652b6d7b61c6b6",
            "34117dde1f1934ce9435ba09823ce9d9102b9593c48caf9d02c3e582e5725248",
            "321a80bc467bcc9866c67d64ff2519274d512301710eab411f04b57a03510f92",
            "1ff9ecf8923813e16032eb997cf21c0a433aa549336677e36f6014fa56a77eb8"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1745222400000,
          "end_exit_ms": 1745380800000,
          "exit_groups": 3,
          "origin_keys": [
            "332d79fd52eb33ee7336b737f5ab4bcf53ef58663ff08a81df1a66d41a256d6a",
            "c1dc4e7d22dd89e05c1a4a35f29b5da0d3da0e704aee1d8b4a49e2c141c5d1eb",
            "7aa40f87b0cb278e8b45832279daca4bac8abca0d49d2fabc816b60d9e3c269d"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1745424000000,
          "end_exit_ms": 1745452800000,
          "exit_groups": 2,
          "origin_keys": [
            "b48e572c7fabc339508f72f03101ea76c0ad794b6e7b4bc8336cb56aca379fbc",
            "1a3ee830b2578e8fb1e059f5f1572aa09c51567bee10629b494f650001c2e863"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1745496000000,
          "end_exit_ms": 1745510400000,
          "exit_groups": 2,
          "origin_keys": [
            "d5a849a545cf0b2d554c2eafc5ad37fdfce9c3f2b576cc136a6c77dde73a3f6e",
            "19c2b21d26a6dc35a9050fcbc4af09cdc8aed83a7e3b1330d34e7db4d3b6f069",
            "317b76a5a17a6d8dbae91124d34254774434715ce6691639741a7b746c380f5a",
            "d0dc725a4068a35969b894ce83ffc09acdcca6047035e0ea225af928d5685579"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1745683200000,
          "end_exit_ms": 1746273600000,
          "exit_groups": 2,
          "origin_keys": [
            "e8a331ecc6c0baefedd65ef764f894b95b0092829b65ce652b72a1c6186e10bb",
            "651217e8d7efd041657b1e7a9c5bc7e59fb672d38ba02d4bac6014c41cf0fd35"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1746849600000,
          "end_exit_ms": 1746993600000,
          "exit_groups": 6,
          "origin_keys": [
            "4727e92ff6e16ac778bcdc0e96707fd4c9de3a10c9714bac8b5a3c8e6d4f9e6e",
            "9c8ef4d1492c6e8e4c525a19eb6c9669471924747bf32dfe8e1df3437444536b",
            "c27f7a34054d119316ebcd28150c8c34450fa6ac83ea2b3be483ab6fb68e0395",
            "6b8c9b6afc6e8194dfd2fba35a528ca944dfdfb0595ca5c9f27764eee555e405",
            "15ef26907cbfa59c389b9e0e6f675c6f02c8e05513c2552b94d03ef937162ad3",
            "213cde55e6492044bf899f97d1c6f6c81413f808f3312d413e48bcde50e23d40",
            "5d91b25b2bfc5529ad6e908957284f8fc832baf1d016d0f8a8a858a82b8f95db",
            "c4682ae9ff5c786a7d30e582c3c5cfbb59773c8533f628b5bb5fe0894e07f179"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1747008000000,
          "end_exit_ms": 1747252800000,
          "exit_groups": 2,
          "origin_keys": [
            "43b37377ff657b1007fe01f75d2a087bd1cc91b8ebb108caf6589e0697b4261f",
            "5a79a5dd3e1a9eb432025d9a04f4dadcc13b17269e3b8cf1459b09085d2bbfee",
            "2ba0e36b341287cb46536c05b450a4247a94603300bdc62a315cbc79ace79a74",
            "421ff70eee84ac0deb03a2424325f4186677f052096d3418e5780fb585772d94"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1747454400000,
          "end_exit_ms": 1747454400000,
          "exit_groups": 1,
          "origin_keys": [
            "f51dcf5ce8bdfccee6aa184557c5fe509fe0df4128c871758d0eee1cfdff0f62"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1747699200000,
          "end_exit_ms": 1748016000000,
          "exit_groups": 2,
          "origin_keys": [
            "b4621724549076ea216593e7f1e62dcc38c262ddacef72d159d705c4fec27760",
            "d8a4f2a22a84a15e76cf58b338e484119ccadf383e7993fa025f42b80aa20ab4"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1748059200000,
          "end_exit_ms": 1748059200000,
          "exit_groups": 1,
          "origin_keys": [
            "3f2af987b6f3f292ec47627b2f41c826755e06eab37bce2071f625299b4283f8",
            "8c0dc7f28401cfd52b8e11d68d5265c1e97d5cbab20a7cada9a5eee778e20494"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1748361600000,
          "end_exit_ms": 1749643200000,
          "exit_groups": 3,
          "origin_keys": [
            "bea8aae7dd2b88f3b8fb0ac87118bf5e97847dbbebd228e32a400dd469eb5a56",
            "607282c1e194dc55fc7302787c8b6227cbd33a9e4ac41047fc92e03ab66da039",
            "38226dbedb6ead810df5ecd642f6f218ac3a25e03f3e2d27b058383d802b6df2",
            "9da72e0fc7048ceaeb290229b35d0bc6cb2f9f7fd00749cb63402b59366edfb1"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1749686400000,
          "end_exit_ms": 1749686400000,
          "exit_groups": 1,
          "origin_keys": [
            "2c78d1df046911c0e8e26712639b79408993001d3a0fb4aa1cd4026724301ed6"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1749700800000,
          "end_exit_ms": 1749945600000,
          "exit_groups": 3,
          "origin_keys": [
            "42ea167aef4705fb7b96cddae7c0e4fe11b747d6ea32169ecc2f6ebc5281b554",
            "8b0fc623cb6b3463c3caf7dedfff12fbd25a3e4aa151a8327486e0356d3e58d5",
            "7f6cc3be57bf316ba6327dcf693f4750ea9b260407434a578f541a5115b35480",
            "2c7af43ed10a363244e4a6352d0ac64054ddbcf876b57a0c4b431d25fb095dab"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1750089600000,
          "end_exit_ms": 1750089600000,
          "exit_groups": 1,
          "origin_keys": [
            "9b89ad74d25350e095ccf046576217a519b3a33d9adddbd96d0e1f654420359d"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1750147200000,
          "end_exit_ms": 1751284800000,
          "exit_groups": 3,
          "origin_keys": [
            "848ed81c901695b377b62cfd5bf8a36b5f965bc754a4bfe785294bae2c786f92",
            "90800d50e8b03a2d3a996e8c3ef0cd2c8dc07f1fee582daff91829ec622c9a94",
            "a26f0b129f4b901a7799eca1d74ad15072c0271af2f54d04766f502d8c9a761f"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1751313600000,
          "end_exit_ms": 1751313600000,
          "exit_groups": 1,
          "origin_keys": [
            "42d102a378a5b35795f0d782c240d56c0788d48fa19ef92e231fc2423a8bad28"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1751414400000,
          "end_exit_ms": 1751616000000,
          "exit_groups": 3,
          "origin_keys": [
            "65096e09475306adc4c891c76c29c02fa99fab9a2e47244d727d0b96f00ca052",
            "028c41dfe81ef98c19d953c5390091c4630e41252054badb5b3dd75c0681f36f",
            "174c80c4b710eb45a2197c2145cc402914a5a1af622289aaa45bbd61676116cc",
            "c07fc33fad28c4b060028aea6bb81936c15e84bd9e0e50403e5ec0be3b24eb2b"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1752177600000,
          "end_exit_ms": 1752264000000,
          "exit_groups": 4,
          "origin_keys": [
            "5bd476198e0abce265e39a155e8507e87c9237130bb2e6ed8349cf689440ef6a",
            "6faf3f413a45770dbb67ec7b20593695292e0fbedec98d2e39fe2707330b398c",
            "61fd039868664da73b71783bef945000d6e11c1aead59752b066304518cbd09c",
            "1240944fafce74020b7af8554bab1061254c0f1955a5b52e81ba0c3958f8eeca",
            "f8bbac66a79fa36955476264d2d7eb5f355b551a626f8dcc7d489aaa222417bc"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1752336000000,
          "end_exit_ms": 1752336000000,
          "exit_groups": 1,
          "origin_keys": [
            "5b26655f80a4f82740d21101e61c2a08cab0698e8b51096365b3a920201fe492"
          ]
        },
        {
          "cohort_id": 25,
          "sign": 1,
          "start_exit_ms": 1752350400000,
          "end_exit_ms": 1752364800000,
          "exit_groups": 2,
          "origin_keys": [
            "0e8dbba3aedb4982ce7ac35dee78536f26203e89072466435e644e5560f2f301",
            "87744ef9904c7e7b931b25035bd24fc26432513fb0624437075c5d423b604d77"
          ]
        },
        {
          "cohort_id": 26,
          "sign": -1,
          "start_exit_ms": 1752552000000,
          "end_exit_ms": 1752782400000,
          "exit_groups": 2,
          "origin_keys": [
            "cad9d858623b7754075c1beb3a8da4002cf5baa2fe11ffac82c9e3e12d8bd839",
            "5f7cddbe4f325f74f40d38c9b18bf6e506ca556f5ad84fb92a3ffddb40d51258"
          ]
        },
        {
          "cohort_id": 27,
          "sign": 1,
          "start_exit_ms": 1752796800000,
          "end_exit_ms": 1752868800000,
          "exit_groups": 2,
          "origin_keys": [
            "e90b09ece23be1880bc54aa8479ed75a2965fdc1b613f486ed88c58c8edd1598",
            "6e59c8f9d32080dd4f8ed5fe6a24b368c28a21e399d77e4f15573dd136801577"
          ]
        },
        {
          "cohort_id": 28,
          "sign": -1,
          "start_exit_ms": 1752883200000,
          "end_exit_ms": 1753185600000,
          "exit_groups": 4,
          "origin_keys": [
            "d66c0ef8c6d34fd04c6395652175e98134d2b7a40c27097130827385be3c6e58",
            "9dd9647d8a39eb36b7e34f9623e1d6a75ac547c828429ddcff3d4a0d9c8cc087",
            "3f51205dc1796ad1adfeadc494bbd4c5863874e0c53ce7fcb48aea973063220e",
            "cf5928f9c26eea33ffb926dd261dd99259b061b3c1cb4f05bcea29015decd463"
          ]
        },
        {
          "cohort_id": 29,
          "sign": 1,
          "start_exit_ms": 1753243200000,
          "end_exit_ms": 1754971200000,
          "exit_groups": 8,
          "origin_keys": [
            "f45c486676dbd3d3a4819429d0ca3489955a0d09cfabfd73ea7a8515bdc9dff2",
            "56b1e08156f23c243e3da6fbcac38febfb3ee44013462dd4f5315ade287c70bc",
            "4a424868c72215feacca97f6641e69efa27004c76cdda2544c6783454ba12322",
            "cd935133a58267e73f63f8806fefbcfd88414a30b69f727af02f9cd7d9bef691",
            "bca7337d28d95b209eacb4bc4e2f2911072fd93a8a2be6bbbe96b66492fa518c",
            "5d40c5ecc7cdf6ad76892cf56b726e8fa41ff383441152bbded36ac29a2f098a",
            "621063760c31a86f64d450cb014e2e7485bcee9eb6c216a20a0db82f20c6d7c3",
            "d8ade007e40ef4eb72cf3d738c2b658859df52d17cf371973b47238761c59fe4",
            "794efe3c48101b2c9cb5333cf67ad058ebaca8935cdaf97654a386c7385f440c"
          ]
        },
        {
          "cohort_id": 30,
          "sign": -1,
          "start_exit_ms": 1755187200000,
          "end_exit_ms": 1757174400000,
          "exit_groups": 9,
          "origin_keys": [
            "62f365c2e2f8d3aaa16b0b80129fcf63647dfbf23f6f92a3b2e8a751fd7efae3",
            "a68fad5ef0a5b7393e14a94eaa517358ffb93f052b389cd4a27feafa41fce916",
            "f95db26db32541a68ce5dbc5bd6b5cb91718b4b3c1977b6dbfb0876ce8db10b5",
            "17b2a26975fded5c11bea9b2546ec44237a5aef006b45931473ef683dcb4cd7b",
            "27113e3ad60b303097eef3e5bca59ee65b1dcce476cab7d1e411327b54e891a2",
            "e614a4a68563d5527463efcde239dc453067de386140698e5af0566a20f1325e",
            "2fee7650c49e82eafff54d449a4b0513ac9079fb2452cdef3e73ad12c2834b15",
            "23fd530a2f8c90f3c0030813a0a68759e8f020a50639f82a61c48b2bb0f38a7d",
            "8f96664f84014a0f7bf89401922d9d41823a30dbfa656060db3b0a9f1a34831a",
            "65ea9e92c1f61c7e9ffb6969d5d84c537ab2fc15a03ebbe9c0d0a732c731b284",
            "19f257381a58217a5939d7cd4c1c2c64d7cc5d907b7cd4abd9305f6b8f5a6231",
            "4dcc596d8520a56a1eef4e35021fafb47b899569326732b7b4f2119e7a191316",
            "2481b5bfde897d9b0d269e40ff2cccc8d0dd0ab8acde40cf5f5b4fcde2d43bf4"
          ]
        },
        {
          "cohort_id": 31,
          "sign": 1,
          "start_exit_ms": 1757476800000,
          "end_exit_ms": 1757692800000,
          "exit_groups": 3,
          "origin_keys": [
            "aec06aed672a058a6ff7919448d20405a1327ac26aaa3d3e368c41426a8dd905",
            "a9c711c89ed3595f329e30d71aec5023a9ae4e23166aa045c6a10d66ec907d1c",
            "fde25f4d60082572dd9a4400211e0fa37f24fa934a83153f988a2348b903bede",
            "a4b38a31b9584bdc8edb3b0eaee7c0070eb9a1a3cb55dcdaeac63f9e5e950baf",
            "cf1824f8a26d6dce16d051736587b4ccd639585ffd0e866600ca6fa016f8ab5b"
          ]
        },
        {
          "cohort_id": 32,
          "sign": -1,
          "start_exit_ms": 1757793600000,
          "end_exit_ms": 1757793600000,
          "exit_groups": 1,
          "origin_keys": [
            "e7cc27024a48e4ac6671293c2354a37eb246bf4acb513c163b7aea48c539e441"
          ]
        },
        {
          "cohort_id": 33,
          "sign": 1,
          "start_exit_ms": 1757808000000,
          "end_exit_ms": 1757822400000,
          "exit_groups": 2,
          "origin_keys": [
            "0441679b4fdbf931bc87e2f82a0c3383d78dce909e90c8d25e460fce298092fe",
            "00c37fb9fec0e2400771ea684a7aaf5dbbd5c0666c2914aa7c4e39c6cda5f62f"
          ]
        },
        {
          "cohort_id": 34,
          "sign": -1,
          "start_exit_ms": 1757865600000,
          "end_exit_ms": 1758268800000,
          "exit_groups": 5,
          "origin_keys": [
            "3c5a14e98e97cdcc4ab2ccf38c7721973355239db90f0b8cf0fb15c355155599",
            "e424189e18759eccadd99370913f8e9b252cddfccaf42c1852d16744c37bd597",
            "1fdc5307d4a393d1fdbf41f8c55c914018ffcae4971b3bfe4e4f295a56ce5ee2",
            "7fe948ab739701f8aa5a7ce848a164a2b13c2c485cb88b599a5cd43db7a51f4a",
            "9c81225d6f110ff12a13a07bcae870e54d6a1849e93a0b305fff7577a8eec6f3",
            "486f3c379524c1142a45fd11d3bcdb20f1bc53d8cdb01e7fb4e537126a14e582"
          ]
        },
        {
          "cohort_id": 35,
          "sign": 1,
          "start_exit_ms": 1759492800000,
          "end_exit_ms": 1759492800000,
          "exit_groups": 1,
          "origin_keys": [
            "f7aeae27fdb82045e76f7bbfe040d6f88731fbd1b2a34f371ccbaaa5a2639e56"
          ]
        },
        {
          "cohort_id": 36,
          "sign": -1,
          "start_exit_ms": 1759521600000,
          "end_exit_ms": 1759521600000,
          "exit_groups": 1,
          "origin_keys": [
            "142f3c05986dedbc643129262daca1c167ef3df51148b2a3a6f8490d1879f369",
            "78e988a010021cbb5c018d83195a643d469d02d5d2a9628eda0bf99223c21ea1",
            "d0c76540e54462481bd9d1f388240d47ec6ae641dbcf351cb2bcb22abcf10533"
          ]
        },
        {
          "cohort_id": 37,
          "sign": 1,
          "start_exit_ms": 1759550400000,
          "end_exit_ms": 1759550400000,
          "exit_groups": 1,
          "origin_keys": [
            "067460dcf66a1873d0a59a68f2d78fef8cf3220ebff66b5627c5bc362ee24854",
            "8bb28404f952e40910dd8b31df3f43218b5bd1129ce35fb17e12939eb1f818bd"
          ]
        },
        {
          "cohort_id": 38,
          "sign": -1,
          "start_exit_ms": 1759564800000,
          "end_exit_ms": 1761566400000,
          "exit_groups": 6,
          "origin_keys": [
            "9b4475a2c982a9a94d086845b5e325506c6c4eefb8f61e71eaf86541e2534191",
            "a9e32d6cf1e7eb66eaf0d6bf43e8ad51eed867e8df7477b6650325f7a8b8f475",
            "7af08e6b7a4d1d43d659254188b5565884a4a312f584cf239069c1875f358114",
            "8082a86edee77e64280cca625b536a7485f9ab1a480adfe82dc68b93083b05ad",
            "906e76e912338f93b9da511b7644c861a4ece4574e5a3007c3cf5981b3f888bf",
            "c7ec5447b386898c4b04633f1a5f2aee9ec4d519e1df5333bedbd18f48e9297c",
            "2b88ec6a908124277534b0093bc34896e2c3ab30a730ffea82533de58facce29",
            "070d1359333c645cb6deb528ee4a2f5a15bf7ca9dc7374005ab63f59679e0365"
          ]
        },
        {
          "cohort_id": 39,
          "sign": 1,
          "start_exit_ms": 1761652800000,
          "end_exit_ms": 1761652800000,
          "exit_groups": 1,
          "origin_keys": [
            "55c3ae44b005f777ae6235a4d51479c9caa8b92b8d4dc1f2b59cc7cf7a43e256"
          ]
        },
        {
          "cohort_id": 40,
          "sign": -1,
          "start_exit_ms": 1761667200000,
          "end_exit_ms": 1766260800000,
          "exit_groups": 8,
          "origin_keys": [
            "a0c5f502cb345b714fc91e81e9486695f0c1f236cb6348d8948d65c27b24a0f1",
            "a17c1e54eafc10441c36c074c134b469d9507ff65c2a102fb48a2c79da7a2421",
            "7c4452f1281bf5fd9996b5808886553a4ccb61768a7fe37cb5cd553172551696",
            "394cba2137039eae01aa1fe7e77aa1ed3cec1995668905561b14417b5b2bfe3a",
            "225f2c0c74dec674d14dd2542a98b87735badb7593e5ebf32d4b6af32309c910",
            "822d8ddf2416c697673994ade0628e3cc865edc859393fa9331567774a642bed",
            "c134e390978dec23db3f41b5cb1738859821bea146f23f8dce16cb21a0af9b4f",
            "b9bdb4c2b4b149a2d8e6a8832b0991c8121ea44e8054055c1744eb5651743083",
            "8a83a5405cac111554da01fe93fe67c9e6a89e6f274eb063b5e58d3465ef8d28"
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
| closed_T | 52.000000 | 52.000000 | 46.000000 |
| open_T | 0.000000 | 0.000000 | 0.000000 |
| entries_T | 52.000000 | 52.000000 | 46.000000 |
| win_rate | 0.692308 | 0.519231 | 0.500000 |
| PF | 3.806184 | 3.437957 | 2.978609 |
| mean_win_bps | 433.611480 | 727.955599 | 730.162178 |
| mean_loss_bps | -256.326514 | -228.680040 | -245.135263 |
| realized_payoff | 1.691637 | 3.183293 | 2.978609 |
| net_expectancy_bps_per_closed_trade | 221.322866 | 268.034619 | 242.513458 |
| closed_gross_bps | 12558.499508 | 15019.842530 | 12108.462991 |
| closed_net_bps | 11508.789051 | 13937.800189 | 11155.619059 |
| closed_cost2x_net_bps | 10459.078594 | 12855.757847 | 10202.775127 |
| closed_cost_bps | 1049.710457 | 1082.042342 | 952.843932 |
| closed_fee_bps | 520.000000 | 520.000000 | 460.000000 |
| closed_funding_bps | 188.250000 | 306.380000 | 267.680000 |
| terminal_net_bps_hypothetical | 11508.789051 | 13937.800189 | 11155.619059 |
| terminal_cost2x_net_bps_hypothetical | 10459.078594 | 12855.757847 | 10202.775127 |
| open_net_mark_bps_hypothetical | 0.000000 | 0.000000 | 0.000000 |
| marked_DD_trade_sum_bps | 1167.638146 | 1903.388508 | 2152.300872 |
| grouped_max_loss_trade_sum_bps | 1055.858832 | 886.384354 | 975.015867 |
| exposure_symbol_days | 52.000000 | 85.166667 | 75.166667 |
| max_simultaneous_symbols | 6.000000 | 6.000000 | 6.000000 |
| entries_per_30_days | 13.000000 | 13.000000 | 11.500000 |
| max_completed_recovery_days | 29.000000 | 47.000000 | 90.000000 |
| open_underwater_days | 14.000000 | 14.000000 | 14.000000 |

Decisions: {"FIXED": "TRADEOFF", "FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "P": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": -450.03651705811103,
        "net_bps": -353.1699921029677,
        "cost2x_net_bps": -256.30346714782496,
        "cost_bps": -96.86652495514312,
        "fee_bps": -60.0,
        "spread_bps": -10.177032112406323,
        "impact_bps": -12.70175431489772,
        "slippage_bps": 0.0,
        "funding_bps": 79.43,
        "frozen_floor_reserve_bps": -93.41773852783908
      },
      "transition_groups": {
        "ABSENT_C": {
          "T": 2,
          "delta_bps": {
            "gross_bps": -704.5261694157934,
            "net_bps": -745.9861694157934,
            "cost2x_net_bps": -787.4461694157934,
            "cost_bps": 41.46,
            "fee_bps": 20.0,
            "spread_bps": 2.0,
            "impact_bps": 4.0,
            "slippage_bps": 0.0,
            "funding_bps": 11.46,
            "frozen_floor_reserve_bps": 4.0
          }
        },
        "C_ABSENT": {
          "T": 8,
          "delta_bps": {
            "gross_bps": -3307.5934057997692,
            "net_bps": -3145.974996284492,
            "cost2x_net_bps": -2984.3565867692146,
            "cost_bps": -161.61840951527722,
            "fee_bps": -80.0,
            "spread_bps": -12.177032112406323,
            "impact_bps": -16.70175431489772,
            "slippage_bps": 0.0,
            "funding_bps": -29.580000000000002,
            "frozen_floor_reserve_bps": -23.15962308797318
          }
        },
        "C_C": {
          "T": 44,
          "delta_bps": {
            "gross_bps": 3562.0830581574514,
            "net_bps": 3538.7911735973175,
            "cost2x_net_bps": 3515.499289037183,
            "cost_bps": 23.2918845601341,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 97.55,
            "frozen_floor_reserve_bps": -74.2581154398659
          }
        }
      },
      "ordinary_winners": {
        "T": 32,
        "parent_positive_bps": 9517.75075865463,
        "child_signed_terminal_bps": 8815.79514194419,
        "capped_terminal_preserved_bps_hypothetical": 5471.209390665764,
        "capped_terminal_retention_hypothetical": 0.5748426838862861,
        "realized_capped_retention_lower": 0.5748426838862861,
        "realized_capped_retention_upper": 0.5748426838862861,
        "profit_cut_bps": 4046.5413679888666,
        "additional_loss_after_winner_bps": 1295.1209626102122,
        "signed_winner_deterioration_bps": 5341.662330599079,
        "winner_to_loss_T": 8,
        "winner_removed_T": 4,
        "winner_to_loss_origins": [
          "05f931d53335082784f715ab2aa3088c871c04a24ca1ed31708388aa34b61be7",
          "41b49e1212e6b7a059b6c722caf908846d3db6f7d912286f99f504f0ed638739",
          "5dc1f5cd16538e0bbd500c80985accfaef13c0d505283efc1c18902318637461",
          "5deda87e4f6bcedbe0ea537daa43aa3f1ddbb0c0baae482bb42dfe6e248bfe05",
          "c178719029ba5f1afb830a8a38f760e70dabd79096684c440b48e83bc88e4828",
          "c4f4ac82b590d77483debb043cd0953c41e1ec3a4f47961a4b130135ae9074cb",
          "d75c5263f533b3220c2a50304972f05e7f0b194c15756101b21940e356c645c2",
          "f8e77d579fd3b97ab5104462ef77d5229516558eef7aa0fb8c0ced932d5bedf5"
        ]
      },
      "large_winners": {
        "T": 4,
        "parent_positive_bps": 6092.262522154764,
        "child_signed_terminal_bps": 6682.813993770693,
        "capped_terminal_preserved_bps_hypothetical": 4224.9122809846995,
        "capped_terminal_retention_hypothetical": 0.6934882181489441,
        "realized_capped_retention_lower": 0.6934882181489441,
        "realized_capped_retention_upper": 0.6934882181489441,
        "profit_cut_bps": 1867.350241170065,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 1867.350241170065,
        "winner_to_loss_T": 0,
        "winner_removed_T": 1,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "17d4a27cebb8baa5995fdc65905a280f56bed1873794b81c83f634ef94f3fabd",
        "symbol": "1000PEPE-USDT",
        "signal_ts": 1787227200000,
        "entry_month": "2026-08",
        "transition": "C_C",
        "parent": {
          "gross_bps": 1197.1830985915499,
          "net_bps": 1175.5646890762728,
          "cost2x_net_bps": 1153.9462795609954,
          "cost_bps": 21.61840951527722,
          "fee_bps": 10.0,
          "spread_bps": 2.796655200379503,
          "impact_bps": 2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": 6.12,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 2703.3371399568564,
          "net_bps": 2675.5987304415794,
          "cost2x_net_bps": 2647.860320926302,
          "cost_bps": 27.738409515277223,
          "fee_bps": 10.0,
          "spread_bps": 2.796655200379503,
          "impact_bps": 2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": 12.24,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 1506.1540413653065,
          "net_bps": 1500.0340413653066,
          "cost2x_net_bps": 1493.9140413653065,
          "cost_bps": 6.120000000000001,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.12,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": true,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 86400000,
        "child_hold_ms": 172800000
      },
      "net_increment_without_largest_positive": -1853.2040334682742,
      "largest_positive_share_of_net_increment": -4.247342851620212,
      "increment_by_symbol": {
        "SOL-USDT": 267.5095695108896,
        "LINK-USDT": 1169.0799077820036,
        "HYPE-USDT": -2397.7766953872056,
        "1000PEPE-USDT": 627.7329983930866,
        "BTC-USDT": -243.56825045562584,
        "BCH-USDT": 40.31235684247798,
        "ETH-USDT": 183.54012121140636
      },
      "increment_by_entry_month": {
        "2026-08": 3006.4174409896896,
        "2026-07": -547.0201267156361,
        "2026-06": -1361.1754441911987,
        "2026-05": -1451.391862185823,
        "2026-09": 0.0
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
      "fixed_path_or_filter_effect": 2461.3430221785075,
      "full_occupancy_remainder": -2911.3795392366173,
      "full_total_effect": -450.0365170581099
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 2429.0111376183722,
      "full_occupancy_remainder": -2782.1811297213408,
      "full_total_effect": -353.16999210296854
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 2396.679253058239,
      "full_occupancy_remainder": -2652.982720206064,
      "full_total_effect": -256.30346714782536
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 32.331884560134085,
      "full_occupancy_remainder": -129.19840951527726,
      "full_total_effect": -96.86652495514318
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -60.0,
      "full_total_effect": -60.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -10.177032112406323,
      "full_total_effect": -10.177032112406323
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -12.701754314897713,
      "full_total_effect": -12.701754314897713
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 118.13,
      "full_occupancy_remainder": -38.69999999999999,
      "full_total_effect": 79.43
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -85.79811543986591,
      "full_occupancy_remainder": -7.619623087973181,
      "full_total_effect": -93.41773852783909
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
      "parent_marked_delta_sum_bps": 11508.789050994055,
      "child_marked_delta_sum_bps": 13937.800188612428,
      "child_minus_parent_marked_delta_sum_bps": 2429.0111376183727,
      "child_minus_parent_mean_daily_bps": 20.241759480153107,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -38.293071679267854,
        68.9013521857282
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -4595.168601512142,
        8268.162262287384
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
      "parent_marked_delta_sum_bps": 11508.789050994055,
      "child_marked_delta_sum_bps": 11155.619058891087,
      "child_minus_parent_marked_delta_sum_bps": -353.16999210296876,
      "child_minus_parent_mean_daily_bps": -2.94308326752474,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -52.54405030768706,
        52.235370685441794
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -6305.286036922447,
        6268.244482253015
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
          "1000PEPE-USDT": 1076.3324732714027,
          "BCH-USDT": 996.4072863011264,
          "BTC-USDT": 822.8937102863053,
          "ETH-USDT": 613.3809667940416,
          "HYPE-USDT": 5216.3632311089605,
          "LINK-USDT": 806.7366938975542,
          "SOL-USDT": 1976.6746893346635
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 2047.8657320484926,
          "BCH-USDT": 996.4072863011264,
          "BTC-USDT": 1453.1853260192752,
          "ETH-USDT": 1481.4703674827665,
          "HYPE-USDT": 5584.046523881212,
          "LINK-USDT": 1543.405725949263,
          "SOL-USDT": 2503.632319127258
        },
        "total_positive_trade_profit_bps": 15610.013280809395,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.357722086677922,
        "winner_T": 36,
        "top_decile_winner_T": 4,
        "top_decile_winners_share": 0.3902791376638005,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 2044.3357316311228,
          "2026-06": 681.4244994028297,
          "2026-07": 1012.3514998333418,
          "2026-08": 8031.475600016672,
          "2026-09": -260.7982798899111
        },
        "top_positive_month_share": 0.682392285661681
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1777852800000,
          "T": 3,
          "net_trade_sum_bps": -22.382810900823955
        },
        {
          "utc_monday_ms": 1778457600000,
          "T": 2,
          "net_trade_sum_bps": -128.78996444057213
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 2,
          "net_trade_sum_bps": 1914.6162246993304
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 2,
          "net_trade_sum_bps": 280.8922822731885
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 1,
          "net_trade_sum_bps": 194.5869167175274
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 6,
          "net_trade_sum_bps": 803.8555538524407
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 9,
          "net_trade_sum_bps": 603.5434471552204
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 1,
          "net_trade_sum_bps": 44.15315012245904
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 3,
          "net_trade_sum_bps": 647.4390414987186
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 1,
          "net_trade_sum_bps": -73.17171228632401
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 1,
          "net_trade_sum_bps": -526.6303978238707
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 1,
          "net_trade_sum_bps": 100.971477731453
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 4,
          "net_trade_sum_bps": -145.28089390038903
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 12,
          "net_trade_sum_bps": 8477.897724880324
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 3,
          "net_trade_sum_bps": -402.1127086947173
        },
        {
          "utc_monday_ms": 1788134400000,
          "T": 1,
          "net_trade_sum_bps": -260.7982798899111
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778356800000,
          "end_exit_ms": 1778529600000,
          "exit_groups": 2,
          "origin_keys": [
            "2ae7958a84c3a2d0d3f1093c2ccdeddab9b4e46115199ec415f26c24a38c6a89",
            "bca5b2331981ddc0fdb9910befae9512d163452657f679dc4958a53089cb2784",
            "c9968fa3b247f9ee9985464d7abb4fafc2ebbfe45418ccba34be26936da56896",
            "205443cbe74c73025a2bf09b5072dc4ce2db0ecff6ffd34350db4d81e532d130",
            "7a46cbe9a3bd2b9f4c19702ebab06d13de1bb8d3ebac4861be8fe23783a16db0"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1779235200000,
          "end_exit_ms": 1781611200000,
          "exit_groups": 7,
          "origin_keys": [
            "7769f57d3270e62f4b5145afb0357597520e98735e0bc7cf35f306e21461ebd2",
            "169ba63d527357de01d9804a46e877b74e0a65951ee580ae3767e112febc651c",
            "d75c5263f533b3220c2a50304972f05e7f0b194c15756101b21940e356c645c2",
            "d322448bb2893f21a0f225c653f0273a48700e5d008fe14d4892cd109f4644c0",
            "41b49e1212e6b7a059b6c722caf908846d3db6f7d912286f99f504f0ed638739",
            "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568",
            "c4f4ac82b590d77483debb043cd0953c41e1ec3a4f47961a4b130135ae9074cb",
            "110b56d34e1a887f9aec0189bb82c8f745ae944283164c9fea2ff2844deb4239",
            "e71c8fb2f3ed7a9aebad454e1581677b5f1fc0063e3b657ac6d8572c308bbb67"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1781625600000,
          "end_exit_ms": 1782849600000,
          "exit_groups": 2,
          "origin_keys": [
            "3e077cdfaad812153ad1e037e65630bc7852a2915039f0f4a99d4cf7f6d96ac1",
            "bd8c1aac8cf3599cfca13986a5df07d243e90516452773ce8ba1e98154aad25c",
            "39c81f7c7b50da5340eda9bca0d2cb41d02e13ef8df4ae1bc074ea76c5d0c798"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1782964800000,
          "end_exit_ms": 1783195200000,
          "exit_groups": 4,
          "origin_keys": [
            "2df39a2e32e657b807effa961bb6673abd3ff987afb839a78c879aef7e966cb0",
            "0b6d5d1ddc0e6a5746af47f3d609d6e3f6463c1d43e6c506018d2b119c23a76d",
            "8fbd4ef984cb305f0630f44263c88a8325e79c4034dae54d8525b123734e23f3",
            "f8e77d579fd3b97ab5104462ef77d5229516558eef7aa0fb8c0ced932d5bedf5",
            "d695f9dc670367aba895f5452702546db91008781da8663f8e66aebcb339af92"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1783209600000,
          "end_exit_ms": 1783281600000,
          "exit_groups": 3,
          "origin_keys": [
            "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6",
            "3f0e0a155999b96d09e2e4236f8c57bfca9c122fa37eb9d10ce92653d381fc3f",
            "cf0022bf6415f7345596df10984f25e6aedcd3d0d14d16764d72646c4012b1ce"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1783382400000,
          "end_exit_ms": 1784131200000,
          "exit_groups": 2,
          "origin_keys": [
            "c178719029ba5f1afb830a8a38f760e70dabd79096684c440b48e83bc88e4828",
            "7bee40ea3c951e545256bc407147d71269161c3c544e7a4837084338eed7acba",
            "b5d8f27bef7c7070c091b3b9dae694cf5c581a968a814e26f64b064e1fab7c55",
            "ec0231afb396a9c773bd3bf9c3fd4fe5d4b892993ec37d99b27ceea62f7a0326"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1784707200000,
          "end_exit_ms": 1785196800000,
          "exit_groups": 2,
          "origin_keys": [
            "fee9bb471e95a250bc2d3c05d538dee7d9442c169c7279064d85c2f7831f099f",
            "87849f027349edd67f6ba2066839a94d449a67fcf44cedbdf36887dcf1aa9588"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1786276800000,
          "end_exit_ms": 1786276800000,
          "exit_groups": 1,
          "origin_keys": [
            "570ddd119fa677f43b4720125bb87afbb927a3f97658cd9b24ef771cd86aaea9"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1786377600000,
          "end_exit_ms": 1786377600000,
          "exit_groups": 1,
          "origin_keys": [
            "da320a7bf2e46b61be23ab9b197823b900ea9cf270f5e4ac27440be4568423a5"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1786536000000,
          "end_exit_ms": 1786752000000,
          "exit_groups": 2,
          "origin_keys": [
            "5deda87e4f6bcedbe0ea537daa43aa3f1ddbb0c0baae482bb42dfe6e248bfe05",
            "295e5b9d59359065826aa92154ef7d126b59cfcca6a682267b28fa0c3576ce22"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1786852800000,
          "end_exit_ms": 1786852800000,
          "exit_groups": 1,
          "origin_keys": [
            "b4b989b2c085d9221103222f4a998f73624b1eb55c76f27c9dc250add69368e0"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1787025600000,
          "end_exit_ms": 1787428800000,
          "exit_groups": 8,
          "origin_keys": [
            "5dc1f5cd16538e0bbd500c80985accfaef13c0d505283efc1c18902318637461",
            "7afe61cfc9bcd8ddbd0a9da0815be332a0789fff401a75f1d7cb8bea22bdd36a",
            "155505d5bb664db30c824262880d9250e8706be1382693fc4487ae0bb16e88d2",
            "639caf1cf9d37acba24a59d22aad80d27687b2d69928f83168bca2fc09dc0087",
            "8aab430bc220281c99a09dd2f11b8cffbddc9fcf993fd756f0df796f0351602e",
            "ee0f796c751a94e9fb0c648a2231c338b35b878a20c359c50a4b06c978545d2d",
            "17d4a27cebb8baa5995fdc65905a280f56bed1873794b81c83f634ef94f3fabd",
            "29e5cd38e205482a6e9a4595c1fe9b6e8db24ced5729e04039fbe4e40722545f",
            "849fc59d52ce2d63d13d1e8218ee8b4a38252c51c15480792d467d56c96e6096",
            "184c70026b7ba49a4715a045056cf99efb3eddf5dc731c1fd63e584517888545",
            "2bc53f756b30563d7ff8a94ddc0aa280297801f290f2a65928546079520da2a7"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1787443200000,
          "end_exit_ms": 1787716800000,
          "exit_groups": 2,
          "origin_keys": [
            "9778f922c2e8ca341ab65ad5b3c55fed1951caaf1cd6790a8acf883ed1c18f3a",
            "70d474cbabbf9e20295b29e637ea598642d65c1ceef384867146df75a2a6c271"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1787918400000,
          "end_exit_ms": 1787918400000,
          "exit_groups": 1,
          "origin_keys": [
            "05f931d53335082784f715ab2aa3088c871c04a24ca1ed31708388aa34b61be7"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1787932800000,
          "end_exit_ms": 1788552000000,
          "exit_groups": 2,
          "origin_keys": [
            "b757745fd0bc8a8e67a9fe6a95906d23474e759ff263f7a2fd4b76f1faf6f060",
            "8a00596640825b294d4eee566fd59cccc1ea3750ac8bd2af567713d0b51c1811"
          ]
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 2417.574758911518,
          "BCH-USDT": 1036.7196431436043,
          "BTC-USDT": 1118.491553408154,
          "ETH-USDT": 684.5968977271343,
          "HYPE-USDT": 4822.362941608024,
          "LINK-USDT": 1765.7779674517196,
          "SOL-USDT": 2092.276426362273
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 3389.108017688608,
          "BCH-USDT": 1036.7196431436043,
          "BTC-USDT": 1870.1499002169198,
          "ETH-USDT": 1552.6862984158597,
          "HYPE-USDT": 6318.234313999732,
          "LINK-USDT": 2512.3053116614515,
          "SOL-USDT": 2975.5976950638787
        },
        "total_positive_trade_profit_bps": 19654.801180190054,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.3214600980226571,
        "winner_T": 27,
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.34000923909147746,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 2286.3714276621713,
          "2026-06": -679.750944788369,
          "2026-07": 353.0071828393922,
          "2026-08": 12238.970802789145,
          "2026-09": -260.7982798899111
        },
        "top_positive_month_share": 0.8226027271449998
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1777852800000,
          "T": 3,
          "net_trade_sum_bps": 301.71427773686526
        },
        {
          "utc_monday_ms": 1778457600000,
          "T": 2,
          "net_trade_sum_bps": -574.6121954179606
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 2,
          "net_trade_sum_bps": 2703.435897286088
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 2,
          "net_trade_sum_bps": -144.16655194282123
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 1,
          "net_trade_sum_bps": -339.52580480497005
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 6,
          "net_trade_sum_bps": -23.20716881626064
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 9,
          "net_trade_sum_bps": 479.01837411614355
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 1,
          "net_trade_sum_bps": -64.01588344594032
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 3,
          "net_trade_sum_bps": 248.87099183651736
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 1,
          "net_trade_sum_bps": -101.25387301059605
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 1,
          "net_trade_sum_bps": -526.6303978238707
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 5,
          "net_trade_sum_bps": 378.99815875350424
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 12,
          "net_trade_sum_bps": 12485.558717823471
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 3,
          "net_trade_sum_bps": -625.5860737878304
        },
        {
          "utc_monday_ms": 1788134400000,
          "T": 1,
          "net_trade_sum_bps": -260.7982798899111
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778356800000,
          "end_exit_ms": 1778356800000,
          "exit_groups": 1,
          "origin_keys": [
            "2ae7958a84c3a2d0d3f1093c2ccdeddab9b4e46115199ec415f26c24a38c6a89",
            "bca5b2331981ddc0fdb9910befae9512d163452657f679dc4958a53089cb2784"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1778443200000,
          "end_exit_ms": 1778443200000,
          "exit_groups": 1,
          "origin_keys": [
            "c9968fa3b247f9ee9985464d7abb4fafc2ebbfe45418ccba34be26936da56896"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1778529600000,
          "end_exit_ms": 1778601600000,
          "exit_groups": 2,
          "origin_keys": [
            "205443cbe74c73025a2bf09b5072dc4ce2db0ecff6ffd34350db4d81e532d130",
            "7a46cbe9a3bd2b9f4c19702ebab06d13de1bb8d3ebac4861be8fe23783a16db0"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1779321600000,
          "end_exit_ms": 1779465600000,
          "exit_groups": 2,
          "origin_keys": [
            "7769f57d3270e62f4b5145afb0357597520e98735e0bc7cf35f306e21461ebd2",
            "169ba63d527357de01d9804a46e877b74e0a65951ee580ae3767e112febc651c"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1779768000000,
          "end_exit_ms": 1779768000000,
          "exit_groups": 1,
          "origin_keys": [
            "d75c5263f533b3220c2a50304972f05e7f0b194c15756101b21940e356c645c2"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1780243200000,
          "end_exit_ms": 1780243200000,
          "exit_groups": 1,
          "origin_keys": [
            "d322448bb2893f21a0f225c653f0273a48700e5d008fe14d4892cd109f4644c0"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1780444800000,
          "end_exit_ms": 1780444800000,
          "exit_groups": 1,
          "origin_keys": [
            "41b49e1212e6b7a059b6c722caf908846d3db6f7d912286f99f504f0ed638739"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1781611200000,
          "end_exit_ms": 1781611200000,
          "exit_groups": 1,
          "origin_keys": [
            "110b56d34e1a887f9aec0189bb82c8f745ae944283164c9fea2ff2844deb4239"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1781625600000,
          "end_exit_ms": 1781625600000,
          "exit_groups": 1,
          "origin_keys": [
            "3e077cdfaad812153ad1e037e65630bc7852a2915039f0f4a99d4cf7f6d96ac1",
            "bd8c1aac8cf3599cfca13986a5df07d243e90516452773ce8ba1e98154aad25c"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1781654400000,
          "end_exit_ms": 1781697600000,
          "exit_groups": 2,
          "origin_keys": [
            "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568",
            "c4f4ac82b590d77483debb043cd0953c41e1ec3a4f47961a4b130135ae9074cb",
            "e71c8fb2f3ed7a9aebad454e1581677b5f1fc0063e3b657ac6d8572c308bbb67"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1782849600000,
          "end_exit_ms": 1782849600000,
          "exit_groups": 1,
          "origin_keys": [
            "39c81f7c7b50da5340eda9bca0d2cb41d02e13ef8df4ae1bc074ea76c5d0c798"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1783051200000,
          "end_exit_ms": 1783094400000,
          "exit_groups": 2,
          "origin_keys": [
            "2df39a2e32e657b807effa961bb6673abd3ff987afb839a78c879aef7e966cb0",
            "0b6d5d1ddc0e6a5746af47f3d609d6e3f6463c1d43e6c506018d2b119c23a76d"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1783209600000,
          "end_exit_ms": 1783209600000,
          "exit_groups": 1,
          "origin_keys": [
            "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1783252800000,
          "end_exit_ms": 1783252800000,
          "exit_groups": 1,
          "origin_keys": [
            "8fbd4ef984cb305f0630f44263c88a8325e79c4034dae54d8525b123734e23f3",
            "f8e77d579fd3b97ab5104462ef77d5229516558eef7aa0fb8c0ced932d5bedf5"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1783267200000,
          "end_exit_ms": 1783468800000,
          "exit_groups": 3,
          "origin_keys": [
            "3f0e0a155999b96d09e2e4236f8c57bfca9c122fa37eb9d10ce92653d381fc3f",
            "cf0022bf6415f7345596df10984f25e6aedcd3d0d14d16764d72646c4012b1ce",
            "d695f9dc670367aba895f5452702546db91008781da8663f8e66aebcb339af92",
            "c178719029ba5f1afb830a8a38f760e70dabd79096684c440b48e83bc88e4828"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1784131200000,
          "end_exit_ms": 1784217600000,
          "exit_groups": 2,
          "origin_keys": [
            "ec0231afb396a9c773bd3bf9c3fd4fe5d4b892993ec37d99b27ceea62f7a0326",
            "7bee40ea3c951e545256bc407147d71269161c3c544e7a4837084338eed7acba",
            "b5d8f27bef7c7070c091b3b9dae694cf5c581a968a814e26f64b064e1fab7c55"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1784779200000,
          "end_exit_ms": 1785196800000,
          "exit_groups": 2,
          "origin_keys": [
            "fee9bb471e95a250bc2d3c05d538dee7d9442c169c7279064d85c2f7831f099f",
            "87849f027349edd67f6ba2066839a94d449a67fcf44cedbdf36887dcf1aa9588"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1786363200000,
          "end_exit_ms": 1786363200000,
          "exit_groups": 1,
          "origin_keys": [
            "570ddd119fa677f43b4720125bb87afbb927a3f97658cd9b24ef771cd86aaea9"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1786377600000,
          "end_exit_ms": 1786622400000,
          "exit_groups": 2,
          "origin_keys": [
            "da320a7bf2e46b61be23ab9b197823b900ea9cf270f5e4ac27440be4568423a5",
            "5deda87e4f6bcedbe0ea537daa43aa3f1ddbb0c0baae482bb42dfe6e248bfe05"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1786838400000,
          "end_exit_ms": 1786838400000,
          "exit_groups": 1,
          "origin_keys": [
            "295e5b9d59359065826aa92154ef7d126b59cfcca6a682267b28fa0c3576ce22"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1786852800000,
          "end_exit_ms": 1787097600000,
          "exit_groups": 2,
          "origin_keys": [
            "b4b989b2c085d9221103222f4a998f73624b1eb55c76f27c9dc250add69368e0",
            "5dc1f5cd16538e0bbd500c80985accfaef13c0d505283efc1c18902318637461"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1787313600000,
          "end_exit_ms": 1787515200000,
          "exit_groups": 7,
          "origin_keys": [
            "7afe61cfc9bcd8ddbd0a9da0815be332a0789fff401a75f1d7cb8bea22bdd36a",
            "155505d5bb664db30c824262880d9250e8706be1382693fc4487ae0bb16e88d2",
            "639caf1cf9d37acba24a59d22aad80d27687b2d69928f83168bca2fc09dc0087",
            "8aab430bc220281c99a09dd2f11b8cffbddc9fcf993fd756f0df796f0351602e",
            "ee0f796c751a94e9fb0c648a2231c338b35b878a20c359c50a4b06c978545d2d",
            "17d4a27cebb8baa5995fdc65905a280f56bed1873794b81c83f634ef94f3fabd",
            "29e5cd38e205482a6e9a4595c1fe9b6e8db24ced5729e04039fbe4e40722545f",
            "9778f922c2e8ca341ab65ad5b3c55fed1951caaf1cd6790a8acf883ed1c18f3a",
            "849fc59d52ce2d63d13d1e8218ee8b4a38252c51c15480792d467d56c96e6096",
            "184c70026b7ba49a4715a045056cf99efb3eddf5dc731c1fd63e584517888545",
            "2bc53f756b30563d7ff8a94ddc0aa280297801f290f2a65928546079520da2a7"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1787716800000,
          "end_exit_ms": 1788552000000,
          "exit_groups": 4,
          "origin_keys": [
            "70d474cbabbf9e20295b29e637ea598642d65c1ceef384867146df75a2a6c271",
            "b757745fd0bc8a8e67a9fe6a95906d23474e759ff263f7a2fd4b76f1faf6f060",
            "05f931d53335082784f715ab2aa3088c871c04a24ca1ed31708388aa34b61be7",
            "8a00596640825b294d4eee566fd59cccc1ea3750ac8bd2af567713d0b51c1811"
          ]
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 1704.0654716644895,
          "BCH-USDT": 1036.7196431436043,
          "BTC-USDT": 579.3254598306796,
          "ETH-USDT": 796.9210880054477,
          "HYPE-USDT": 2818.5865357217544,
          "LINK-USDT": 1975.8166016795578,
          "SOL-USDT": 2244.1842588455534
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 2675.5987304415794,
          "BCH-USDT": 1036.7196431436043,
          "BTC-USDT": 1330.9838066394452,
          "ETH-USDT": 1552.6862984158597,
          "HYPE-USDT": 4709.838612959278,
          "LINK-USDT": 2512.3053116614515,
          "SOL-USDT": 2975.5976950638787
        },
        "total_positive_trade_profit_bps": 16793.730098325097,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.28045220361312156,
        "winner_T": 23,
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.39793505996843404,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 592.9438694453003,
          "2026-06": -679.750944788369,
          "2026-07": 465.3313731177056,
          "2026-08": 11037.89304100636,
          "2026-09": -260.7982798899111
        },
        "top_positive_month_share": 0.9125115311101866
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1777852800000,
          "T": 3,
          "net_trade_sum_bps": 301.71427773686526
        },
        {
          "utc_monday_ms": 1778457600000,
          "T": 2,
          "net_trade_sum_bps": -632.644021560137
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 2,
          "net_trade_sum_bps": 1068.0401652113933
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 2,
          "net_trade_sum_bps": -144.16655194282123
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 1,
          "net_trade_sum_bps": -339.52580480497005
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 6,
          "net_trade_sum_bps": -23.20716881626064
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 8,
          "net_trade_sum_bps": 591.342564394457
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 1,
          "net_trade_sum_bps": -64.01588344594032
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 3,
          "net_trade_sum_bps": 248.87099183651736
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 1,
          "net_trade_sum_bps": -101.25387301059605
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 1,
          "net_trade_sum_bps": -526.6303978238707
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 3,
          "net_trade_sum_bps": 798.9764516067988
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 9,
          "net_trade_sum_bps": 10864.502663187393
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 3,
          "net_trade_sum_bps": -625.5860737878304
        },
        {
          "utc_monday_ms": 1788134400000,
          "T": 1,
          "net_trade_sum_bps": -260.7982798899111
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": -1,
          "start_exit_ms": 1778356800000,
          "end_exit_ms": 1778356800000,
          "exit_groups": 1,
          "origin_keys": [
            "2ae7958a84c3a2d0d3f1093c2ccdeddab9b4e46115199ec415f26c24a38c6a89",
            "bca5b2331981ddc0fdb9910befae9512d163452657f679dc4958a53089cb2784"
          ]
        },
        {
          "cohort_id": 1,
          "sign": 1,
          "start_exit_ms": 1778443200000,
          "end_exit_ms": 1778443200000,
          "exit_groups": 1,
          "origin_keys": [
            "c9968fa3b247f9ee9985464d7abb4fafc2ebbfe45418ccba34be26936da56896"
          ]
        },
        {
          "cohort_id": 2,
          "sign": -1,
          "start_exit_ms": 1778529600000,
          "end_exit_ms": 1778616000000,
          "exit_groups": 2,
          "origin_keys": [
            "205443cbe74c73025a2bf09b5072dc4ce2db0ecff6ffd34350db4d81e532d130",
            "a2527e83bc08303a30a165fbe55e22f71dd247267354a0d74ba6343ac3e0ec3e"
          ]
        },
        {
          "cohort_id": 3,
          "sign": 1,
          "start_exit_ms": 1779321600000,
          "end_exit_ms": 1779321600000,
          "exit_groups": 1,
          "origin_keys": [
            "7769f57d3270e62f4b5145afb0357597520e98735e0bc7cf35f306e21461ebd2"
          ]
        },
        {
          "cohort_id": 4,
          "sign": -1,
          "start_exit_ms": 1779494400000,
          "end_exit_ms": 1779768000000,
          "exit_groups": 2,
          "origin_keys": [
            "6fcd9cabd94f7c0b3c97000580ba8c8b4288834a67e002bde524cdb187b95c13",
            "d75c5263f533b3220c2a50304972f05e7f0b194c15756101b21940e356c645c2"
          ]
        },
        {
          "cohort_id": 5,
          "sign": 1,
          "start_exit_ms": 1780243200000,
          "end_exit_ms": 1780243200000,
          "exit_groups": 1,
          "origin_keys": [
            "d322448bb2893f21a0f225c653f0273a48700e5d008fe14d4892cd109f4644c0"
          ]
        },
        {
          "cohort_id": 6,
          "sign": -1,
          "start_exit_ms": 1780444800000,
          "end_exit_ms": 1780444800000,
          "exit_groups": 1,
          "origin_keys": [
            "41b49e1212e6b7a059b6c722caf908846d3db6f7d912286f99f504f0ed638739"
          ]
        },
        {
          "cohort_id": 7,
          "sign": 1,
          "start_exit_ms": 1781611200000,
          "end_exit_ms": 1781611200000,
          "exit_groups": 1,
          "origin_keys": [
            "110b56d34e1a887f9aec0189bb82c8f745ae944283164c9fea2ff2844deb4239"
          ]
        },
        {
          "cohort_id": 8,
          "sign": -1,
          "start_exit_ms": 1781625600000,
          "end_exit_ms": 1781625600000,
          "exit_groups": 1,
          "origin_keys": [
            "3e077cdfaad812153ad1e037e65630bc7852a2915039f0f4a99d4cf7f6d96ac1",
            "bd8c1aac8cf3599cfca13986a5df07d243e90516452773ce8ba1e98154aad25c"
          ]
        },
        {
          "cohort_id": 9,
          "sign": 1,
          "start_exit_ms": 1781654400000,
          "end_exit_ms": 1781697600000,
          "exit_groups": 2,
          "origin_keys": [
            "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568",
            "c4f4ac82b590d77483debb043cd0953c41e1ec3a4f47961a4b130135ae9074cb",
            "e71c8fb2f3ed7a9aebad454e1581677b5f1fc0063e3b657ac6d8572c308bbb67"
          ]
        },
        {
          "cohort_id": 10,
          "sign": -1,
          "start_exit_ms": 1782849600000,
          "end_exit_ms": 1782849600000,
          "exit_groups": 1,
          "origin_keys": [
            "39c81f7c7b50da5340eda9bca0d2cb41d02e13ef8df4ae1bc074ea76c5d0c798"
          ]
        },
        {
          "cohort_id": 11,
          "sign": 1,
          "start_exit_ms": 1783051200000,
          "end_exit_ms": 1783094400000,
          "exit_groups": 2,
          "origin_keys": [
            "2df39a2e32e657b807effa961bb6673abd3ff987afb839a78c879aef7e966cb0",
            "0b6d5d1ddc0e6a5746af47f3d609d6e3f6463c1d43e6c506018d2b119c23a76d"
          ]
        },
        {
          "cohort_id": 12,
          "sign": -1,
          "start_exit_ms": 1783209600000,
          "end_exit_ms": 1783209600000,
          "exit_groups": 1,
          "origin_keys": [
            "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6"
          ]
        },
        {
          "cohort_id": 13,
          "sign": 1,
          "start_exit_ms": 1783252800000,
          "end_exit_ms": 1783252800000,
          "exit_groups": 1,
          "origin_keys": [
            "8fbd4ef984cb305f0630f44263c88a8325e79c4034dae54d8525b123734e23f3",
            "f8e77d579fd3b97ab5104462ef77d5229516558eef7aa0fb8c0ced932d5bedf5"
          ]
        },
        {
          "cohort_id": 14,
          "sign": -1,
          "start_exit_ms": 1783281600000,
          "end_exit_ms": 1783468800000,
          "exit_groups": 2,
          "origin_keys": [
            "cf0022bf6415f7345596df10984f25e6aedcd3d0d14d16764d72646c4012b1ce",
            "d695f9dc670367aba895f5452702546db91008781da8663f8e66aebcb339af92",
            "c178719029ba5f1afb830a8a38f760e70dabd79096684c440b48e83bc88e4828"
          ]
        },
        {
          "cohort_id": 15,
          "sign": 1,
          "start_exit_ms": 1784131200000,
          "end_exit_ms": 1784217600000,
          "exit_groups": 2,
          "origin_keys": [
            "ec0231afb396a9c773bd3bf9c3fd4fe5d4b892993ec37d99b27ceea62f7a0326",
            "7bee40ea3c951e545256bc407147d71269161c3c544e7a4837084338eed7acba",
            "b5d8f27bef7c7070c091b3b9dae694cf5c581a968a814e26f64b064e1fab7c55"
          ]
        },
        {
          "cohort_id": 16,
          "sign": -1,
          "start_exit_ms": 1784779200000,
          "end_exit_ms": 1785196800000,
          "exit_groups": 2,
          "origin_keys": [
            "fee9bb471e95a250bc2d3c05d538dee7d9442c169c7279064d85c2f7831f099f",
            "87849f027349edd67f6ba2066839a94d449a67fcf44cedbdf36887dcf1aa9588"
          ]
        },
        {
          "cohort_id": 17,
          "sign": 1,
          "start_exit_ms": 1786363200000,
          "end_exit_ms": 1786363200000,
          "exit_groups": 1,
          "origin_keys": [
            "570ddd119fa677f43b4720125bb87afbb927a3f97658cd9b24ef771cd86aaea9"
          ]
        },
        {
          "cohort_id": 18,
          "sign": -1,
          "start_exit_ms": 1786622400000,
          "end_exit_ms": 1786622400000,
          "exit_groups": 1,
          "origin_keys": [
            "5deda87e4f6bcedbe0ea537daa43aa3f1ddbb0c0baae482bb42dfe6e248bfe05"
          ]
        },
        {
          "cohort_id": 19,
          "sign": 1,
          "start_exit_ms": 1786838400000,
          "end_exit_ms": 1786838400000,
          "exit_groups": 1,
          "origin_keys": [
            "295e5b9d59359065826aa92154ef7d126b59cfcca6a682267b28fa0c3576ce22"
          ]
        },
        {
          "cohort_id": 20,
          "sign": -1,
          "start_exit_ms": 1787097600000,
          "end_exit_ms": 1787097600000,
          "exit_groups": 1,
          "origin_keys": [
            "5dc1f5cd16538e0bbd500c80985accfaef13c0d505283efc1c18902318637461"
          ]
        },
        {
          "cohort_id": 21,
          "sign": 1,
          "start_exit_ms": 1787313600000,
          "end_exit_ms": 1787400000000,
          "exit_groups": 3,
          "origin_keys": [
            "7afe61cfc9bcd8ddbd0a9da0815be332a0789fff401a75f1d7cb8bea22bdd36a",
            "155505d5bb664db30c824262880d9250e8706be1382693fc4487ae0bb16e88d2",
            "639caf1cf9d37acba24a59d22aad80d27687b2d69928f83168bca2fc09dc0087",
            "8aab430bc220281c99a09dd2f11b8cffbddc9fcf993fd756f0df796f0351602e",
            "ee0f796c751a94e9fb0c648a2231c338b35b878a20c359c50a4b06c978545d2d",
            "17d4a27cebb8baa5995fdc65905a280f56bed1873794b81c83f634ef94f3fabd"
          ]
        },
        {
          "cohort_id": 22,
          "sign": -1,
          "start_exit_ms": 1787443200000,
          "end_exit_ms": 1787443200000,
          "exit_groups": 1,
          "origin_keys": [
            "9778f922c2e8ca341ab65ad5b3c55fed1951caaf1cd6790a8acf883ed1c18f3a"
          ]
        },
        {
          "cohort_id": 23,
          "sign": 1,
          "start_exit_ms": 1787486400000,
          "end_exit_ms": 1787486400000,
          "exit_groups": 1,
          "origin_keys": [
            "849fc59d52ce2d63d13d1e8218ee8b4a38252c51c15480792d467d56c96e6096"
          ]
        },
        {
          "cohort_id": 24,
          "sign": -1,
          "start_exit_ms": 1787716800000,
          "end_exit_ms": 1788552000000,
          "exit_groups": 4,
          "origin_keys": [
            "70d474cbabbf9e20295b29e637ea598642d65c1ceef384867146df75a2a6c271",
            "b757745fd0bc8a8e67a9fe6a95906d23474e759ff263f7a2fd4b76f1faf6f060",
            "05f931d53335082784f715ab2aa3088c871c04a24ca1ed31708388aa34b61be7",
            "8a00596640825b294d4eee566fd59cccc1ea3750ac8bd2af567713d0b51c1811"
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
