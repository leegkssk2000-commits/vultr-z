# KR2 frozen DEV economics

Equal nominal trade-bps; terminal includes hypothetical full-cost open marks. Neither account returns nor independent validation. FULL is primary; FIXED is a diagnostic. KR1/M/M2 ledgers reused. SR1/BR1 V2 baselines computed only for these authorized comparisons. Q0 is preserved without replay or replacement.

## DEV2025

| Metric | M | M2 | KR1_FULL | FIXED | FULL |
|---|---:|---:|---:|---:|---:|
| closed_T | 202.000000 | 202.000000 | 202.000000 | 202.000000 | 202.000000 |
| open_T | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| entries_T | 203.000000 | 203.000000 | 203.000000 | 203.000000 | 203.000000 |
| win_rate | 0.485149 | 0.430693 | 0.400990 | 0.400990 | 0.400990 |
| PF | 1.154179 | 1.164512 | 1.246539 | 1.205955 | 1.205955 |
| mean_win_bps | 460.021948 | 502.320121 | 589.522690 | 569.983121 | 569.983121 |
| mean_loss_bps | -375.576377 | -326.330693 | -316.587896 | -316.395788 | -316.395788 |
| realized_payoff | 1.224843 | 1.539298 | 1.862114 | 1.801488 | 1.801488 |
| net_expectancy_bps_per_closed_trade | 29.812909 | 30.563469 | 46.753478 | 39.033378 | 39.033378 |
| closed_gross_bps | 10294.529028 | 10401.724983 | 13960.380766 | 12311.866942 | 12311.866942 |
| closed_net_bps | 6022.207694 | 6173.820762 | 9444.202480 | 7884.742442 | 7884.742442 |
| closed_cost2x_net_bps | 1749.886360 | 1945.916541 | 4928.024195 | 3457.617941 | 3457.617941 |
| closed_cost_bps | 4272.321334 | 4227.904221 | 4516.178285 | 4427.124500 | 4427.124500 |
| closed_fee_bps | 2020.000000 | 2020.000000 | 2020.000000 | 2020.000000 | 2020.000000 |
| closed_funding_bps | 1324.820000 | 1121.430000 | 1442.270000 | 1343.820000 | 1343.820000 |
| terminal_net_bps_hypothetical | 5945.476630 | 6097.089698 | 9367.471416 | 7808.011378 | 7808.011378 |
| terminal_cost2x_net_bps_hypothetical | 1653.155296 | 1849.185477 | 4831.293131 | 3360.886877 | 3360.886877 |
| open_net_mark_bps_hypothetical | -76.731064 | -76.731064 | -76.731064 | -76.731064 | -76.731064 |
| marked_DD_trade_sum_bps | 11605.833081 | 9599.807816 | 12640.258962 | 11427.293041 | 11427.293041 |
| grouped_max_loss_trade_sum_bps | 4782.532910 | 3981.700930 | 3835.253714 | 3835.253714 | 3835.253714 |
| exposure_symbol_days | 372.666667 | 315.833333 | 406.000000 | 380.666667 | 380.666667 |
| max_simultaneous_symbols | 7.000000 | 6.000000 | 6.000000 | 6.000000 | 6.000000 |
| entries_per_30_days | 16.240000 | 16.240000 | 16.240000 | 16.240000 | 16.240000 |
| max_completed_recovery_days | 64.000000 | 64.000000 | 63.000000 | 58.000000 | 58.000000 |
| open_underwater_days | 101.333333 | 101.333333 | 137.333333 | 101.333333 | 101.333333 |

Decisions: {"FIXED": "REJECT", "FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "M": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 2017.337913899416,
        "net_bps": 1862.5347475458507,
        "cost2x_net_bps": 1707.731581192285,
        "cost_bps": 154.80316635356527,
        "fee_bps": 0.0,
        "spread_bps": 0.0,
        "impact_bps": 0.0,
        "slippage_bps": 0.0,
        "funding_bps": 19.0,
        "frozen_floor_reserve_bps": 135.80316635356525
      },
      "transition_groups": {
        "C_C": {
          "T": 202,
          "delta_bps": {
            "gross_bps": 2017.337913899416,
            "net_bps": 1862.5347475458507,
            "cost2x_net_bps": 1707.731581192285,
            "cost_bps": 154.80316635356527,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 19.0,
            "frozen_floor_reserve_bps": 135.80316635356525
          }
        },
        "O_O": {
          "T": 1,
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
        "T": 88,
        "parent_positive_bps": 29266.752302772857,
        "child_signed_terminal_bps": 24627.643478758786,
        "capped_terminal_preserved_bps_hypothetical": 21885.53272187811,
        "capped_terminal_retention_hypothetical": 0.7477950575269188,
        "realized_capped_retention_lower": 0.7477950575269188,
        "realized_capped_retention_upper": 0.7477950575269188,
        "profit_cut_bps": 7381.2195808947445,
        "additional_loss_after_winner_bps": 3218.8068344879944,
        "signed_winner_deterioration_bps": 10600.02641538274,
        "winner_to_loss_T": 18,
        "winner_removed_T": 0,
        "winner_to_loss_origins": [
          "0699ffb8a34eae2af55c58494a1e85dffbf7b36aa8e425931ea7d037495506fa",
          "136c2d685362c73f9c8faac1906b1f0f6b39c96937143c502f1dafa8a17f4635",
          "1c033c7e7de80f564916f3b313f06fa64d43e200b4bd4f00c6f63fc63f41cd41",
          "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530",
          "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77",
          "426aaff0097e98b6f0e7cc599671e126621e79f81c2d9456d7d68d4dc6ce0e50",
          "437f79a339b9767f600ec378cd215060196d2354fc2a82b194def883ac5e5e94",
          "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1",
          "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569",
          "6183540eaf7ee3778e78b8f4d8f8cbc7736977c475a71761e053c24a7e44e283",
          "6d3370d48c8dd5361e302db82f2faab51beb8134d32e053764712ba77b9847f2",
          "8f8515e6532e5db846128d34e0acd9af583552e0154ecac8c07839a96cfa430b",
          "96a7eaa94ec10a0dc4fed1a17b04fca7a0d6ce97a652a93ce32f852597731eca",
          "b79a83562bbb1fcf661f5da109bec9523bc2fbe18a6cc2ee2b9045b078870920",
          "cfede36f952bb1cbafdc54a70967713c8d8900f29aebfedaa2683dac8a33a86e",
          "d88d6da82807ed73485910acdb84b99de13e8b250836cce7b9e4604a05804a5e",
          "dba9bbf39a23532d0a92a6380648a5a82bb86abaaa2a1533200bea613985c5f9",
          "f04b345b13db9aef69e08301403563cd13bee3941d6c62e05f591694a5764ad7"
        ]
      },
      "large_winners": {
        "T": 10,
        "parent_positive_bps": 15815.398579277295,
        "child_signed_terminal_bps": 18142.339245472274,
        "capped_terminal_preserved_bps_hypothetical": 13739.61312010474,
        "capped_terminal_retention_hypothetical": 0.8687490897704956,
        "realized_capped_retention_lower": 0.8687490897704956,
        "realized_capped_retention_upper": 0.8687490897704956,
        "profit_cut_bps": 2075.7854591725554,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 2075.7854591725554,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
        "symbol": "ETH-USDT",
        "signal_ts": 1746576000000,
        "entry_month": "2025-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 2149.0592944570762,
          "net_bps": 2129.0592944570762,
          "cost2x_net_bps": 2109.0592944570762,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.0,
          "frozen_floor_reserve_bps": 1.0
        },
        "child": {
          "gross_bps": 4216.574257098651,
          "net_bps": 4191.574257098651,
          "cost2x_net_bps": 4166.574257098651,
          "cost_bps": 25.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 12.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 2067.514962641575,
          "net_bps": 2062.514962641575,
          "cost2x_net_bps": 2057.514962641575,
          "cost_bps": 5.0,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.0,
          "frozen_floor_reserve_bps": -1.0
        },
        "parent_large_winner": true,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 172800000,
        "child_hold_ms": 345600000
      },
      "net_increment_without_largest_positive": -199.98021509572436,
      "largest_positive_share_of_net_increment": 1.1073699244318669,
      "increment_by_symbol": {
        "BCH-USDT": -2260.4675974188967,
        "BTC-USDT": 478.84487358723175,
        "1000PEPE-USDT": 1460.411369975222,
        "LINK-USDT": -369.4728063920105,
        "SOL-USDT": 1059.4922679691342,
        "HYPE-USDT": -550.3587540987062,
        "ETH-USDT": 2044.085393923877
      },
      "increment_by_entry_month": {
        "2025-06": -384.467141838421,
        "2025-05": 1006.1508199036857,
        "2025-12": -913.0442516924364,
        "2025-09": 719.1882589150405,
        "2025-07": 2030.3631001159029,
        "2025-11": 1040.5833104569974,
        "2025-08": -2031.9402618876193,
        "2025-04": -1018.1226641168579,
        "2025-03": 759.8308957762879,
        "2025-10": 782.8437512479559,
        "2025-02": 119.12093337511374,
        "2025-01": -247.97200270979852
      },
      "parity": "PASS",
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "cost_saving_already_in_net": true,
      "post_outcome_diagnostic_only": true,
      "independent": false
    },
    "M2": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 1910.1419588648869,
        "net_bps": 1710.9216794053557,
        "cost2x_net_bps": 1511.7013999458245,
        "cost_bps": 199.22027945953104,
        "fee_bps": 0.0,
        "spread_bps": 0.0,
        "impact_bps": 0.0,
        "slippage_bps": 0.0,
        "funding_bps": 222.39000000000001,
        "frozen_floor_reserve_bps": -23.169720540468973
      },
      "transition_groups": {
        "C_C": {
          "T": 202,
          "delta_bps": {
            "gross_bps": 1910.1419588648869,
            "net_bps": 1710.9216794053557,
            "cost2x_net_bps": 1511.7013999458245,
            "cost_bps": 199.22027945953104,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 222.39000000000001,
            "frozen_floor_reserve_bps": -23.169720540468973
          }
        },
        "O_O": {
          "T": 1,
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
        "T": 78,
        "parent_positive_bps": 28980.277563894128,
        "child_signed_terminal_bps": 29956.25736723592,
        "capped_terminal_preserved_bps_hypothetical": 22979.358357849884,
        "capped_terminal_retention_hypothetical": 0.7929309271516207,
        "realized_capped_retention_lower": 0.7929309271516207,
        "realized_capped_retention_upper": 0.7929309271516207,
        "profit_cut_bps": 6000.919206044242,
        "additional_loss_after_winner_bps": 408.81084394615226,
        "signed_winner_deterioration_bps": 6409.730049990394,
        "winner_to_loss_T": 7,
        "winner_removed_T": 0,
        "winner_to_loss_origins": [
          "0699ffb8a34eae2af55c58494a1e85dffbf7b36aa8e425931ea7d037495506fa",
          "1c033c7e7de80f564916f3b313f06fa64d43e200b4bd4f00c6f63fc63f41cd41",
          "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530",
          "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77",
          "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1",
          "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569",
          "6d3370d48c8dd5361e302db82f2faab51beb8134d32e053764712ba77b9847f2"
        ]
      },
      "large_winners": {
        "T": 9,
        "parent_positive_bps": 14721.57294330552,
        "child_signed_terminal_bps": 15623.721347536983,
        "capped_terminal_preserved_bps_hypothetical": 12645.787484132965,
        "capped_terminal_retention_hypothetical": 0.8589970333220067,
        "realized_capped_retention_lower": 0.8589970333220067,
        "realized_capped_retention_upper": 0.8589970333220067,
        "profit_cut_bps": 2075.7854591725554,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 2075.7854591725554,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
        "symbol": "ETH-USDT",
        "signal_ts": 1746576000000,
        "entry_month": "2025-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 2149.0592944570762,
          "net_bps": 2129.0592944570762,
          "cost2x_net_bps": 2109.0592944570762,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.0,
          "frozen_floor_reserve_bps": 1.0
        },
        "child": {
          "gross_bps": 4216.574257098651,
          "net_bps": 4191.574257098651,
          "cost2x_net_bps": 4166.574257098651,
          "cost_bps": 25.0,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 12.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 2067.514962641575,
          "net_bps": 2062.514962641575,
          "cost2x_net_bps": 2057.514962641575,
          "cost_bps": 5.0,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 6.0,
          "frozen_floor_reserve_bps": -1.0
        },
        "parent_large_winner": true,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 172800000,
        "child_hold_ms": 345600000
      },
      "net_increment_without_largest_positive": -351.59328323621935,
      "largest_positive_share_of_net_increment": 1.2054993442823276,
      "increment_by_symbol": {
        "BCH-USDT": -2042.705831959457,
        "BTC-USDT": 482.7562402327333,
        "1000PEPE-USDT": 315.34334682889124,
        "LINK-USDT": -39.83383705486233,
        "SOL-USDT": 524.3191973616866,
        "HYPE-USDT": -112.11302661865852,
        "ETH-USDT": 2583.1555906150224
      },
      "increment_by_entry_month": {
        "2025-06": -182.91108149279364,
        "2025-05": 1885.778714869108,
        "2025-12": -949.6183137588591,
        "2025-09": 821.3116963335538,
        "2025-07": 2212.171912560406,
        "2025-11": 0.5620398298877838,
        "2025-08": -2159.146662798121,
        "2025-04": -48.61397220169419,
        "2025-03": 569.1313680858312,
        "2025-10": -189.77201931216436,
        "2025-02": 0.0,
        "2025-01": -247.97200270979852
      },
      "parity": "PASS",
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "cost_saving_already_in_net": true,
      "post_outcome_diagnostic_only": true,
      "independent": false
    },
    "KR1_FULL": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": -1648.5138235689042,
        "net_bps": -1559.4600386364634,
        "cost2x_net_bps": -1470.4062537040215,
        "cost_bps": -89.05378493244137,
        "fee_bps": 0.0,
        "spread_bps": 0.0,
        "impact_bps": 0.0,
        "slippage_bps": 0.0,
        "funding_bps": -98.45,
        "frozen_floor_reserve_bps": 9.396215067558622
      },
      "transition_groups": {
        "C_C": {
          "T": 202,
          "delta_bps": {
            "gross_bps": -1648.5138235689042,
            "net_bps": -1559.4600386364634,
            "cost2x_net_bps": -1470.4062537040215,
            "cost_bps": -89.05378493244137,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": -98.45,
            "frozen_floor_reserve_bps": 9.396215067558622
          }
        },
        "O_O": {
          "T": 1,
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
        "T": 72,
        "parent_positive_bps": 26318.170914415055,
        "child_signed_terminal_bps": 27691.137507482614,
        "capped_terminal_preserved_bps_hypothetical": 24446.972746289626,
        "capped_terminal_retention_hypothetical": 0.9289009037060196,
        "realized_capped_retention_lower": 0.9289009037060196,
        "realized_capped_retention_upper": 0.9289009037060196,
        "profit_cut_bps": 1871.1981681254297,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 1871.1981681254297,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "large_winners": {
        "T": 9,
        "parent_positive_bps": 21433.16693932385,
        "child_signed_terminal_bps": 18477.49526213568,
        "capped_terminal_preserved_bps_hypothetical": 18477.49526213568,
        "capped_terminal_retention_hypothetical": 0.8620982290878655,
        "realized_capped_retention_lower": 0.8620982290878655,
        "realized_capped_retention_upper": 0.8620982290878655,
        "profit_cut_bps": 2955.6716771881756,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 2955.6716771881756,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "a10581de8ca6e0a3a8d39c7919e138b74e98b8a995d5c1d71b10bc23272e623e",
        "symbol": "1000PEPE-USDT",
        "signal_ts": 1747771200000,
        "entry_month": "2025-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 525.175630630288,
          "net_bps": 489.2772211150108,
          "cost2x_net_bps": 453.3788115997335,
          "cost_bps": 35.89840951527722,
          "fee_bps": 10.0,
          "spread_bps": 2.796655200379503,
          "impact_bps": 2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": 20.4,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 884.6749403122823,
          "net_bps": 856.936530797005,
          "cost2x_net_bps": 829.1981212817278,
          "cost_bps": 27.738409515277223,
          "fee_bps": 10.0,
          "spread_bps": 2.796655200379503,
          "impact_bps": 2.7017543148977197,
          "slippage_bps": 0.0,
          "funding_bps": 12.24,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 359.4993096819943,
          "net_bps": 367.6593096819943,
          "cost2x_net_bps": 375.8193096819943,
          "cost_bps": -8.16,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": -8.159999999999998,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": false,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 273600000,
        "child_hold_ms": 172800000
      },
      "net_increment_without_largest_positive": -1927.1193483184577,
      "largest_positive_share_of_net_increment": -0.23576064828404486,
      "increment_by_symbol": {
        "BCH-USDT": -229.77831573702883,
        "BTC-USDT": -406.94487865704224,
        "1000PEPE-USDT": -2136.212715883568,
        "LINK-USDT": 806.940294827428,
        "SOL-USDT": 508.3507657175056,
        "HYPE-USDT": 80.60914661538527,
        "ETH-USDT": -182.42433551914354
      },
      "increment_by_entry_month": {
        "2025-06": 272.98584418034426,
        "2025-05": 73.35855545117914,
        "2025-12": 0.0,
        "2025-09": 285.23417749748484,
        "2025-07": 435.54037024285014,
        "2025-11": 0.0,
        "2025-08": 959.6644545766569,
        "2025-04": -2281.4194176477376,
        "2025-03": -1840.720551439497,
        "2025-10": 290.88836693057425,
        "2025-02": 0.0,
        "2025-01": 245.00816157168163
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
      "fixed_path_or_filter_effect": -1648.5138235689046,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -1648.5138235689046
    },
    "net_bps": {
      "fixed_path_or_filter_effect": -1559.4600386364637,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -1559.4600386364637
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": -1470.4062537040218,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -1470.4062537040218
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": -89.05378493244098,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -89.05378493244098
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": -98.45000000000005,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -98.45000000000005
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": 9.396215067558614,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 9.396215067558614
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
      "parent_marked_delta_sum_bps": 9367.471416221857,
      "child_marked_delta_sum_bps": 7808.011377585393,
      "child_minus_parent_marked_delta_sum_bps": -1559.4600386364637,
      "child_minus_parent_mean_daily_bps": -4.147500102756553,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -23.169266572647903,
        10.088696005611423
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -8711.644231315611,
        3793.349698109895
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
      "parent_marked_delta_sum_bps": 9367.471416221857,
      "child_marked_delta_sum_bps": 7808.011377585393,
      "child_minus_parent_marked_delta_sum_bps": -1559.4600386364637,
      "child_minus_parent_mean_daily_bps": -4.147500102756553,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -23.169266572647903,
        10.088696005611423
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -8711.644231315611,
        3793.349698109895
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    }
  },
  "concentration": {
    "M": {
      "profit": {
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 1310.5748886442557,
          "2025-02": -880.1443487650902,
          "2025-03": 2279.731670117847,
          "2025-04": 3259.7195088666813,
          "2025-05": 2634.252189535562,
          "2025-06": -473.75798763902463,
          "2025-07": 5531.759452247585,
          "2025-08": 1665.7245211081088,
          "2025-09": -53.82128269654385,
          "2025-10": -3218.441565505039,
          "2025-11": -1117.0189712241074,
          "2025-12": -4916.370380559923
        },
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -1385.5874417137502,
          "BCH-USDT": 1637.537058278182,
          "BTC-USDT": -434.65050642938064,
          "ETH-USDT": 1683.499733247723,
          "HYPE-USDT": 3692.0113164548075,
          "LINK-USDT": 2763.54546376381,
          "SOL-USDT": -1934.1479294710798
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 6374.351528715127,
          "BCH-USDT": 7346.6042443148835,
          "BTC-USDT": 2919.0702993718974,
          "ETH-USDT": 6157.98834541387,
          "HYPE-USDT": 9929.71492737391,
          "LINK-USDT": 7161.146636510585,
          "SOL-USDT": 5193.274900349878
        },
        "top_decile_winner_T": 10,
        "top_decile_winners_share": 0.3508128665079805,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.22025823375981632,
        "top_positive_month_share": 0.3316052210675309,
        "total_positive_trade_profit_bps": 45082.15088205015,
        "winner_T": 98
      },
      "market_event_weekly_clusters": [
        {
          "T": 1,
          "net_trade_sum_bps": 1310.5748886442557,
          "utc_monday_ms": 1737936000000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -698.4409756766281,
          "utc_monday_ms": 1738540800000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206,
          "utc_monday_ms": 1740355200000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 1994.1735285369746,
          "utc_monday_ms": 1740960000000
        },
        {
          "T": 3,
          "net_trade_sum_bps": 1494.4465256871222,
          "utc_monday_ms": 1742169600000
        },
        {
          "T": 5,
          "net_trade_sum_bps": -1208.8883841062498,
          "utc_monday_ms": 1742774400000
        },
        {
          "T": 7,
          "net_trade_sum_bps": 1118.2104212643624,
          "utc_monday_ms": 1744588800000
        },
        {
          "T": 6,
          "net_trade_sum_bps": 2394.125620872916,
          "utc_monday_ms": 1745193600000
        },
        {
          "T": 14,
          "net_trade_sum_bps": 194.17876107711368,
          "utc_monday_ms": 1745798400000
        },
        {
          "T": 6,
          "net_trade_sum_bps": 3179.223730553162,
          "utc_monday_ms": 1746403200000
        },
        {
          "T": 13,
          "net_trade_sum_bps": -2152.047899130069,
          "utc_monday_ms": 1747008000000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 2926.2527063330244,
          "utc_monday_ms": 1747612800000
        },
        {
          "T": 10,
          "net_trade_sum_bps": -1765.9716425682666,
          "utc_monday_ms": 1748217600000
        },
        {
          "T": 1,
          "net_trade_sum_bps": 33.105192549422824,
          "utc_monday_ms": 1748822400000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -160.18844467064713,
          "utc_monday_ms": 1749427200000
        },
        {
          "T": 3,
          "net_trade_sum_bps": -244.04853546585196,
          "utc_monday_ms": 1750032000000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -102.62620005194837,
          "utc_monday_ms": 1750636800000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -84.23699873728054,
          "utc_monday_ms": 1751241600000
        },
        {
          "T": 10,
          "net_trade_sum_bps": 2154.523469393026,
          "utc_monday_ms": 1751846400000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 4184.854660838501,
          "utc_monday_ms": 1752451200000
        },
        {
          "T": 10,
          "net_trade_sum_bps": -638.7805168340109,
          "utc_monday_ms": 1753056000000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -398.1397970185695,
          "utc_monday_ms": 1753660800000
        },
        {
          "T": 1,
          "net_trade_sum_bps": 292.8668492760833,
          "utc_monday_ms": 1754265600000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 1295.5159192617164,
          "utc_monday_ms": 1754870400000
        },
        {
          "T": 5,
          "net_trade_sum_bps": 434.98402752213735,
          "utc_monday_ms": 1755475200000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -44.10364034590947,
          "utc_monday_ms": 1756080000000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -612.1792165144293,
          "utc_monday_ms": 1756684800000
        },
        {
          "T": 5,
          "net_trade_sum_bps": 1651.873802833461,
          "utc_monday_ms": 1757289600000
        },
        {
          "T": 11,
          "net_trade_sum_bps": -234.50553038186456,
          "utc_monday_ms": 1757894400000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -859.0103386337111,
          "utc_monday_ms": 1758499200000
        },
        {
          "T": 11,
          "net_trade_sum_bps": -1671.6433500232104,
          "utc_monday_ms": 1759708800000
        },
        {
          "T": 3,
          "net_trade_sum_bps": -1610.933950956831,
          "utc_monday_ms": 1761523200000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -779.6085764601213,
          "utc_monday_ms": 1762128000000
        },
        {
          "T": 1,
          "net_trade_sum_bps": 14.949245057036563,
          "utc_monday_ms": 1762732800000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -288.2239043460199,
          "utc_monday_ms": 1763942400000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -2333.9983664455185,
          "utc_monday_ms": 1764547200000
        },
        {
          "T": 9,
          "net_trade_sum_bps": -2108.6902649673557,
          "utc_monday_ms": 1765152000000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -473.68174914704906,
          "utc_monday_ms": 1766361600000
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "end_exit_ms": 1738310400000,
          "exit_groups": 1,
          "origin_keys": [
            "979b207a0cba154c4e56588b522459fa2902ad9ee30a61a24690b47f38d357e6"
          ],
          "sign": 1,
          "start_exit_ms": 1738310400000
        },
        {
          "cohort_id": 1,
          "end_exit_ms": 1740398400000,
          "exit_groups": 2,
          "origin_keys": [
            "75bc1657579c38bd14d06fb08329382d285734e221669423c07436b9168745f3",
            "e20ec6b5b1d64710658dccc8218f65bec8ec99a40af5f15cf38a37a4902efd57"
          ],
          "sign": -1,
          "start_exit_ms": 1738944000000
        },
        {
          "cohort_id": 2,
          "end_exit_ms": 1741291200000,
          "exit_groups": 1,
          "origin_keys": [
            "5d6e5b2ff3cf13258185ce91cb7c4e919d939674c0a8eb3b43bee07fbb02deb6"
          ],
          "sign": 1,
          "start_exit_ms": 1741291200000
        },
        {
          "cohort_id": 3,
          "end_exit_ms": 1741392000000,
          "exit_groups": 1,
          "origin_keys": [
            "3ba2fc0bf476825ddf705c60441b6695aa84f0134bde8a0de6895f244bbe5a6e"
          ],
          "sign": -1,
          "start_exit_ms": 1741392000000
        },
        {
          "cohort_id": 4,
          "end_exit_ms": 1742875200000,
          "exit_groups": 5,
          "origin_keys": [
            "4d5ff1901411d6d49cbce69c93cbc35f4d7bb8f5a9c9a77c44ee660c68c28e32",
            "1653ba4f1d26dff2261e9c362f004f8c74c8b766ce03e28276216c4ccab687dc",
            "c1127e43093e62cbe8bc16e1487a4dbf17ce66211259d19a6e5ed93a56095320",
            "e8a6e1ffe7c7d82419d74876b6a6c46f0e78bad36cdd9a091afc4a89323dbc35",
            "5a528e3ccae612a1a58eb63f60fb13cc6f88990b4cdc88471dcb9c3b4631c521"
          ],
          "sign": 1,
          "start_exit_ms": 1742371200000
        },
        {
          "cohort_id": 5,
          "end_exit_ms": 1744876800000,
          "exit_groups": 4,
          "origin_keys": [
            "196c03d2731521f1e86e4d797f11094e616708a19020dce4919dacc640f21060",
            "1708bab61045d1eeaa2c350e2e7851851f62a23daf078ff8998df30b18ed7d14",
            "711b1318d15c09603ef57558aa7a1f321f727f1dff1c4d08c6e41a755e5d3c3a",
            "c854aa8fd523fc736ca1f0b9acc5783788dc70558b58da7d91737d68ee88eec4"
          ],
          "sign": -1,
          "start_exit_ms": 1743076800000
        },
        {
          "cohort_id": 6,
          "end_exit_ms": 1745683200000,
          "exit_groups": 7,
          "origin_keys": [
            "11ff48ed506f83b9a9fa9267381bd2d96e7de9404c20349e175ed0db38927ae8",
            "9c1cc06b28d04eb6b93b11b379fff3ea7948f56ac55794d9003e490d48691ebb",
            "ab487bcd177eb3107deb68c125a05af61af7384a70cf079a682c2c129adc581f",
            "2061fca492db51368428be5f97a2337099a971b1842d4f29c72fb5ae77d1aa25",
            "6a17e80b6f6a73786f18faa40f8e3a691fe1f65bc2214d9ddccb1cacba42f3a1",
            "e1f389c1a4c16aa5bae8730c6d710e4e99e1f40b7a1278be9fffc2fc593c5a55",
            "54e6c4939b93069ee71a073f9a5a7b9ee5f32e6eb14fbf1ef64e5b05c56eab0f",
            "15f69d81e2bb95a5a72b262f18e8222757758b3138990c1d01b999cdc4da3c09",
            "3ad0f0c17337ad73dfebd624f47c0cf42535a2ecf32a0c9e0c23efbda8935e30",
            "0f9e0ad9a9c424f355d0fdc40b7b9f452b36a382a8c11e5d93e8fc8cb8812f7b",
            "ea78a8e6612680ae67dc8d6a43ac87831fd7402265ddde47cb87cae704a34f2a"
          ],
          "sign": 1,
          "start_exit_ms": 1744992000000
        },
        {
          "cohort_id": 7,
          "end_exit_ms": 1745956800000,
          "exit_groups": 2,
          "origin_keys": [
            "4504481ef8c1c67ae04a5af5a8063e7ca5996ffb14cc64793242056b597b31cb",
            "618293610019999e13d4089b009d7d4f7243872a4800ba1651afc4ef5d78ae32",
            "ef80ea0ab964ded3cdbd87ba38a28fa6eb5edb7d734c2b5aa4c4f62794837d20"
          ],
          "sign": -1,
          "start_exit_ms": 1745697600000
        },
        {
          "cohort_id": 8,
          "end_exit_ms": 1745985600000,
          "exit_groups": 1,
          "origin_keys": [
            "45f7cd3f209d7eabbd187e7f0fec94a334dc2c79f7cf987251ea383993cfbb9b"
          ],
          "sign": 1,
          "start_exit_ms": 1745985600000
        },
        {
          "cohort_id": 9,
          "end_exit_ms": 1746000000000,
          "exit_groups": 1,
          "origin_keys": [
            "136c2d685362c73f9c8faac1906b1f0f6b39c96937143c502f1dafa8a17f4635",
            "ad4f0095fed68a4b976ecb545563933251f5d099bc47915b8c67de1819455bb4",
            "b2e6e3962feac71b22eb2074e39a006cb98587f0725bf3109be8838ef695308a"
          ],
          "sign": -1,
          "start_exit_ms": 1746000000000
        },
        {
          "cohort_id": 10,
          "end_exit_ms": 1746057600000,
          "exit_groups": 1,
          "origin_keys": [
            "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77"
          ],
          "sign": 1,
          "start_exit_ms": 1746057600000
        },
        {
          "cohort_id": 11,
          "end_exit_ms": 1746187200000,
          "exit_groups": 1,
          "origin_keys": [
            "2a6edbf2a77ba9baccbbcad7d1ac4fa45547e5b199bfb7188e01fef99ea9f0f1",
            "8f8515e6532e5db846128d34e0acd9af583552e0154ecac8c07839a96cfa430b"
          ],
          "sign": -1,
          "start_exit_ms": 1746187200000
        },
        {
          "cohort_id": 12,
          "end_exit_ms": 1746244800000,
          "exit_groups": 3,
          "origin_keys": [
            "443656f5dc9edca0ebcdea7effb81353900acbd8e3568596f3b41b175c57c721",
            "66117e742708f66294f9f95ffa8f4508569ca50a81ef0ff2ed50ae5b21508b7a",
            "9f57fefae4501e2060405f7b470a13e8d60a6ebc9b825b311517e592dab05c18"
          ],
          "sign": 1,
          "start_exit_ms": 1746216000000
        },
        {
          "cohort_id": 13,
          "end_exit_ms": 1746460800000,
          "exit_groups": 3,
          "origin_keys": [
            "3d58ce6d768f2b3a9f9ec4e78dbcbd10c17801962fd80435b1900d7a3a2458bb",
            "c798df5ca9bb60fe80cee47c9a36ff1dae5485b87024b19d401247092885b5d6",
            "54b78a22139f7b6fc6d5a8c320c51466f5d1d0b370101c3b40221d9a51a8ecd5",
            "a414ff0468e67cedd06ac949d41cc4e377a5c3179a42c660ff0b8de3fdfc92f1"
          ],
          "sign": -1,
          "start_exit_ms": 1746259200000
        },
        {
          "cohort_id": 14,
          "end_exit_ms": 1746835200000,
          "exit_groups": 4,
          "origin_keys": [
            "437f79a339b9767f600ec378cd215060196d2354fc2a82b194def883ac5e5e94",
            "c22715040c25b6fa120e78b741bbd6aa34568c23f641a18898967fa9605765ed",
            "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
            "98d9d88ea5b38501a3f288f0b18d965f0ca2f3d4b971d011f6c4b3f696539466"
          ],
          "sign": 1,
          "start_exit_ms": 1746590400000
        },
        {
          "cohort_id": 15,
          "end_exit_ms": 1747137600000,
          "exit_groups": 1,
          "origin_keys": [
            "614f68e55b8871666bebe8710b0bf29a55c5a71bc88360169166f0b5cb0630ff",
            "7eafb7cae685ca0d1c66f35b17c30da5f58b571af67a9d38d545974f2953a2bb"
          ],
          "sign": -1,
          "start_exit_ms": 1747137600000
        },
        {
          "cohort_id": 16,
          "end_exit_ms": 1747267200000,
          "exit_groups": 1,
          "origin_keys": [
            "0699ffb8a34eae2af55c58494a1e85dffbf7b36aa8e425931ea7d037495506fa"
          ],
          "sign": 1,
          "start_exit_ms": 1747267200000
        },
        {
          "cohort_id": 17,
          "end_exit_ms": 1747483200000,
          "exit_groups": 4,
          "origin_keys": [
            "32d7355d1e8b6905432e9c1c04556f6b55d24b66827a68e18ece58943811bcc1",
            "dcae4bdf5d8ecbbd233ca0df467fee60f9a5d995fa76a2732c9190f4cd1860e6",
            "df5f82141ecb5edf4d9fa776242df2050725bc80a7fa0fbf15264585eb13aa2d",
            "994c40c0e2256268dde011f6f7d9fc1f972f2003cc15f350f2c2a2a82c7a439f",
            "1d528bb8ffde0df9b2af2eb4afa0b2ba2baa64b6feed2cd6c2728f06dfc039e7",
            "042d9748b7ad652fe6a1459db425be08a6a4ee9271a2ed26f7c2d7a8d49bfe0b",
            "a8e615a6faad7f5be3eaaaa1834f896ed1365beb77d5a8fcbdc70f12f3462b16"
          ],
          "sign": -1,
          "start_exit_ms": 1747296000000
        },
        {
          "cohort_id": 18,
          "end_exit_ms": 1747497600000,
          "exit_groups": 1,
          "origin_keys": [
            "3d76dfec91f65235b6b9528f7172d0f4b81cf455cd99f0d21020be81763780c2",
            "88d458309b458d10306f7ea1e344f5b0f924c5741006087fbcf9ff96d73e9279",
            "ebe480142f6fde44c8bd630e98949d1b5928821c747eb9e776bd2b56e13f9800"
          ],
          "sign": 1,
          "start_exit_ms": 1747497600000
        },
        {
          "cohort_id": 19,
          "end_exit_ms": 1747656000000,
          "exit_groups": 2,
          "origin_keys": [
            "3b45e5a08e5b46c824e67cffc67750543f72613e1da6b5d08cb2d52d95a3f4dd",
            "e6329bba085fc7a05bdfd0f60732a72382fc45a58d44d58671fc7a2c5a41d78d"
          ],
          "sign": -1,
          "start_exit_ms": 1747627200000
        },
        {
          "cohort_id": 20,
          "end_exit_ms": 1747728000000,
          "exit_groups": 2,
          "origin_keys": [
            "1c033c7e7de80f564916f3b313f06fa64d43e200b4bd4f00c6f63fc63f41cd41",
            "2f8ad94eff3a7f569bc6c03875ae0c0ede863e07d0230d8b551f42d8a74a8df9",
            "58caa5c0de31b1d116e216d8f4e878d6050afe63914f6b025e6c09f3f9e2bd3e"
          ],
          "sign": 1,
          "start_exit_ms": 1747713600000
        },
        {
          "cohort_id": 21,
          "end_exit_ms": 1747756800000,
          "exit_groups": 1,
          "origin_keys": [
            "6edb54a38352879b003aa03b19b60af41cfea5ed2fe58d45d32c36ff9b8036fb"
          ],
          "sign": -1,
          "start_exit_ms": 1747756800000
        },
        {
          "cohort_id": 22,
          "end_exit_ms": 1748390400000,
          "exit_groups": 4,
          "origin_keys": [
            "a10581de8ca6e0a3a8d39c7919e138b74e98b8a995d5c1d71b10bc23272e623e",
            "f2155391aa7764c59c85a1774bf8ec2783fdf8da4a5fdf1f7a3e77e7e43eb21f",
            "f4d6def625f4d88d6adbcbcc6c20c2ef2ece38e91cd8c40a8e26b2655f74aadf",
            "6d3370d48c8dd5361e302db82f2faab51beb8134d32e053764712ba77b9847f2",
            "b79a83562bbb1fcf661f5da109bec9523bc2fbe18a6cc2ee2b9045b078870920",
            "2309869ab033df7389c783f5f2491430e47c77c04811e44332342a27cf828f14",
            "8d1e9fb1a87540daedeec63a1bd37862547398d79b72b7411f8d46b027e1cea3"
          ],
          "sign": 1,
          "start_exit_ms": 1747944000000
        },
        {
          "cohort_id": 23,
          "end_exit_ms": 1748592000000,
          "exit_groups": 5,
          "origin_keys": [
            "23c94f724bf48a6e16603c297353285d71192d1cadfa92536f6299787da312dd",
            "025bb75df735c790d62747f3e13e8ca2ecf6e25cff47e05c2325121f4400cb62",
            "33f57ce14343f17bddeb7418ac566edd267076603ae156bdc4baf6823225f58e",
            "0a331de10b2976732100714d118f7ab16568669025031ce21fd3ed2ff51ce773",
            "aa3e034323ec63827bf0018347ef7d0a316702d5a0617020d04e8c858a1e2a8a",
            "fb48642108224d3fd03fb697ee7a20785f5171d1bd7cee02e2a5f31071d76a3d"
          ],
          "sign": -1,
          "start_exit_ms": 1748404800000
        },
        {
          "cohort_id": 24,
          "end_exit_ms": 1749398400000,
          "exit_groups": 1,
          "origin_keys": [
            "dba9bbf39a23532d0a92a6380648a5a82bb86abaaa2a1533200bea613985c5f9"
          ],
          "sign": 1,
          "start_exit_ms": 1749398400000
        },
        {
          "cohort_id": 25,
          "end_exit_ms": 1750003200000,
          "exit_groups": 2,
          "origin_keys": [
            "024114bc463b975bb2471e67185237d7bee62108dc9b572958bf60110d707c7f",
            "edee33a09ec6eb780a2ad5c573cf33227791b558457c97d5e2045ab17f3d554c"
          ],
          "sign": -1,
          "start_exit_ms": 1749916800000
        },
        {
          "cohort_id": 26,
          "end_exit_ms": 1750118400000,
          "exit_groups": 1,
          "origin_keys": [
            "87c161e5a0178ff7eca2cffd9a8d37631304339b34d0b8783cf85c19f8d4fff5"
          ],
          "sign": 1,
          "start_exit_ms": 1750118400000
        },
        {
          "cohort_id": 27,
          "end_exit_ms": 1750305600000,
          "exit_groups": 1,
          "origin_keys": [
            "346f7341f2bf3ca2b223cbb6c08980902fe7f1f65b9318434a2f735617f90af0"
          ],
          "sign": -1,
          "start_exit_ms": 1750305600000
        },
        {
          "cohort_id": 28,
          "end_exit_ms": 1750507200000,
          "exit_groups": 1,
          "origin_keys": [
            "fe8e0737e3379d2cef8489483a55b8b1e702cce913035dd0ea89742db9df1314"
          ],
          "sign": 1,
          "start_exit_ms": 1750507200000
        },
        {
          "cohort_id": 29,
          "end_exit_ms": 1750752000000,
          "exit_groups": 1,
          "origin_keys": [
            "39539c214fa857f57942fdecb68ca04e4d9b1018d4cbf98a027b0bce364fd025"
          ],
          "sign": -1,
          "start_exit_ms": 1750752000000
        },
        {
          "cohort_id": 30,
          "end_exit_ms": 1751356800000,
          "exit_groups": 2,
          "origin_keys": [
            "f8b2e6dbf975e01a4c24cd97e823cf2d2682b8c4ca2e60fd6ad9d67412e1f08f",
            "19b7e6cbf30ad251a04905bcbe18c261b3c3bc82fa95963ecd9c4c95ddfac24b"
          ],
          "sign": 1,
          "start_exit_ms": 1751169600000
        },
        {
          "cohort_id": 31,
          "end_exit_ms": 1751472000000,
          "exit_groups": 1,
          "origin_keys": [
            "ea90f21d84b730c28a1773be9ee1628a4daf2163a42ab9d96c480e4de0f0193e"
          ],
          "sign": -1,
          "start_exit_ms": 1751472000000
        },
        {
          "cohort_id": 32,
          "end_exit_ms": 1751616000000,
          "exit_groups": 1,
          "origin_keys": [
            "5dc1f4defbfbc3fa4dc1acb116712938b0a3552d6a89b263aaad65507c8dbd26",
            "96ed746cc89114bc96aac5280111eea20edd9a85e84ab8419892e4e8f9fb98cd"
          ],
          "sign": 1,
          "start_exit_ms": 1751616000000
        },
        {
          "cohort_id": 33,
          "end_exit_ms": 1751644800000,
          "exit_groups": 1,
          "origin_keys": [
            "64fee382be25139512d408919e8250d563f51d560dd3b813196fdd208868c8d1",
            "ccd2a420e644f4be3c60d0b80e6328f0b025f3b9e7258bcba646be88e60ca47f"
          ],
          "sign": -1,
          "start_exit_ms": 1751644800000
        },
        {
          "cohort_id": 34,
          "end_exit_ms": 1751875200000,
          "exit_groups": 2,
          "origin_keys": [
            "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569",
            "96a7eaa94ec10a0dc4fed1a17b04fca7a0d6ce97a652a93ce32f852597731eca"
          ],
          "sign": 1,
          "start_exit_ms": 1751860800000
        },
        {
          "cohort_id": 35,
          "end_exit_ms": 1751990400000,
          "exit_groups": 1,
          "origin_keys": [
            "1db87f8de43b59b15f878d313cfc72243fc58147aba4e2a1d092d175f11a6420",
            "5670edf0d14be75b650617df11623e0c264c928e01761685247611300e2c2b4e",
            "a87ac993ed55790f6527004a16cd082a003328436ad856153d97b67f81c32b3c",
            "d4587f56aa58595f4a5c34cb1c8d91539ec6b99ae14be7a6f3791416a8d508a8"
          ],
          "sign": -1,
          "start_exit_ms": 1751990400000
        },
        {
          "cohort_id": 36,
          "end_exit_ms": 1752177600000,
          "exit_groups": 2,
          "origin_keys": [
            "7580befe0c0c1ebfe54b91a1135cd1c53d3864646f191c09a6825a74bb37bb9a",
            "0849bb8f17c8313ebc2ae91114edfd46c6f62986e96607f92da1776c575d6ea3",
            "588117c7ecbadbf1bd2d05794cc3719559963cbeae1c93b38b0a6ed478c372c8"
          ],
          "sign": 1,
          "start_exit_ms": 1752134400000
        },
        {
          "cohort_id": 37,
          "end_exit_ms": 1752350400000,
          "exit_groups": 1,
          "origin_keys": [
            "6c79f7624a88231c465b70a25a0548f526f4c38ee7bf9fd10beeaf91f078f348"
          ],
          "sign": -1,
          "start_exit_ms": 1752350400000
        },
        {
          "cohort_id": 38,
          "end_exit_ms": 1752523200000,
          "exit_groups": 1,
          "origin_keys": [
            "4135d00ba44ebc5cf362711a4abee2e6d01c478113057178d7b0ea1f56c7e916",
            "c4b037954cd3a617621503a5d77862a4938eef8c6a6327ed5330b232b49ed2c6"
          ],
          "sign": 1,
          "start_exit_ms": 1752523200000
        },
        {
          "cohort_id": 39,
          "end_exit_ms": 1752710400000,
          "exit_groups": 2,
          "origin_keys": [
            "6bcecc02427a0ab87800a8061d36d4d0c8fb501f79b12637a45b21655b0f9221",
            "1f62363ddf4605200913f11e62d56c828b95351635929f111bd69433e45bade4"
          ],
          "sign": -1,
          "start_exit_ms": 1752566400000
        },
        {
          "cohort_id": 40,
          "end_exit_ms": 1753200000000,
          "exit_groups": 7,
          "origin_keys": [
            "ad79f7e334f3d55db655513fa0d0b4c8b86d80c941edf24bfcbb43fac93ed175",
            "47dd745683e2b505200b6d7e1fc1ede9415e6a8d5b5aafb1c19767cb1332b910",
            "52b2c7f77188ca8227f75c8db34792dd70799a9ad5ff7cd3319389ceec23568a",
            "0d2b35ab633f4d557b8498f19d4a4520d5b9a0efb7ba02443b9ae02d1091d3e6",
            "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530",
            "a9a3e8365fcc187a032b988186095539cef032de8177ce8cd707794f13c41178",
            "130a5d5d13a47060b238ee0b3ea34039c17b4d62c365ed662db54151cb725994",
            "d88d6da82807ed73485910acdb84b99de13e8b250836cce7b9e4604a05804a5e"
          ],
          "sign": 1,
          "start_exit_ms": 1752739200000
        },
        {
          "cohort_id": 41,
          "end_exit_ms": 1753545600000,
          "exit_groups": 4,
          "origin_keys": [
            "8a5d77ec50be4dde6278d0637ccd74d2208b8fdb80e2fe1aafd67d12055bbe9b",
            "e8c732e46d0580a95e52293b59277c9ba520fdc091bf689bd5ae2e21d33050dd",
            "3cd227554c6bd53fad0d12e860efe081bd24b05cccf9e1d794a182c8c4dcad6e",
            "7af2a28e7e974d6aea365bca7852e315a945200b974024e626335ee7577f02d7",
            "81f03a46613732f84a14cc6faf711252ca5de24205bf3fca9360c100254dde55",
            "63792578bc411889e22ef91262a5824732a8d1ae57a0ded1ca745836604b9ca0"
          ],
          "sign": -1,
          "start_exit_ms": 1753358400000
        },
        {
          "cohort_id": 42,
          "end_exit_ms": 1753660800000,
          "exit_groups": 2,
          "origin_keys": [
            "557b95fc65cbf0a8035281ddc5e29e72cd7bc95790782d8b7411eecf313ca04e",
            "10a7b67bfcf5fdef4e36f5eea44c22d0c15966fe732ee607db46507ea2c37308",
            "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1"
          ],
          "sign": 1,
          "start_exit_ms": 1753603200000
        },
        {
          "cohort_id": 43,
          "end_exit_ms": 1754064000000,
          "exit_groups": 4,
          "origin_keys": [
            "da7ef6e9025099319f5576f5f52136b82c6f1ec5029bcf9e25045c2badadd7fd",
            "72b8b528d33ac98c9e17345c6de9613fe8d6014697570c41ea668548c0f2e6ae",
            "71902b786b8aa54c87f1430de51e32e03473b5c94413248f360662735a04ef94",
            "eacc20084995a3ab4a7da3fa3ca8dbab480710b7067c84bc8292646e35c78df3"
          ],
          "sign": -1,
          "start_exit_ms": 1753848000000
        },
        {
          "cohort_id": 44,
          "end_exit_ms": 1755144000000,
          "exit_groups": 4,
          "origin_keys": [
            "b39417684ba0dd296a071fcc13fe5216b1b6844235c84549dc686fccb4673de2",
            "426aaff0097e98b6f0e7cc599671e126621e79f81c2d9456d7d68d4dc6ce0e50",
            "a6dd07b321410fe650cca40b7fba4a0319308127876915148c36d7d211015c8d",
            "fa2227abd88b8c794620d6219457b183c6b3c8053e46cdabdf4ff044408ae2e8"
          ],
          "sign": 1,
          "start_exit_ms": 1754640000000
        },
        {
          "cohort_id": 45,
          "end_exit_ms": 1755187200000,
          "exit_groups": 1,
          "origin_keys": [
            "86080a597e0bc1116384e954acd6b0c32041e73eec3b5942be80a252744afa0d",
            "97ac73b0f3529903ed9ea201036b3a9a435d9f8242a6960923498385c043fde6",
            "d8c4f5ef31ad715ad9c25e6dbcb30b68461f2f90690cb945d7860890f229bfc0"
          ],
          "sign": -1,
          "start_exit_ms": 1755187200000
        },
        {
          "cohort_id": 46,
          "end_exit_ms": 1755374400000,
          "exit_groups": 1,
          "origin_keys": [
            "26f83f96f1a03e42ad86c962382630587b92091985220c144f5c7f898fa19067"
          ],
          "sign": 1,
          "start_exit_ms": 1755374400000
        },
        {
          "cohort_id": 47,
          "end_exit_ms": 1755403200000,
          "exit_groups": 1,
          "origin_keys": [
            "23afcd4e4c4688f46d0a8905fb2ed0da9124e917c61c1c8310d2bbd3f05a9253",
            "d982dd8e49b3f106e644332a4059d1194d1d35aee6d350030b4372357aea69b9"
          ],
          "sign": -1,
          "start_exit_ms": 1755403200000
        },
        {
          "cohort_id": 48,
          "end_exit_ms": 1755547200000,
          "exit_groups": 1,
          "origin_keys": [
            "d42bc424b418ebd385e34b86cfaafa6df637e49e5d03982b8bf2a22f33c6c63a"
          ],
          "sign": 1,
          "start_exit_ms": 1755547200000
        },
        {
          "cohort_id": 49,
          "end_exit_ms": 1755604800000,
          "exit_groups": 2,
          "origin_keys": [
            "0d6aa06212cbc737dcc220fe2a05a8b0915ef9cbbaeeff4122e1226468ce37f9",
            "8192c69c9ec4091daed78995d26184cd0f43e977592742eb3f1fb55906840011"
          ],
          "sign": -1,
          "start_exit_ms": 1755576000000
        },
        {
          "cohort_id": 50,
          "end_exit_ms": 1756022400000,
          "exit_groups": 2,
          "origin_keys": [
            "23bdd736b6f855d35443df00de3082fc216d437a3f7b5535adb2b3a3965c802a",
            "2a31409627d7f1beff834be00cd1d4b4f8f24cebba69f13c1e941d9ef6a9c809"
          ],
          "sign": 1,
          "start_exit_ms": 1755777600000
        },
        {
          "cohort_id": 51,
          "end_exit_ms": 1756209600000,
          "exit_groups": 1,
          "origin_keys": [
            "d1b4cfd5ebf80e5ed19f62d16eda0239aaa594558936a7e9760b06bd1999ac97"
          ],
          "sign": -1,
          "start_exit_ms": 1756209600000
        },
        {
          "cohort_id": 52,
          "end_exit_ms": 1756411200000,
          "exit_groups": 2,
          "origin_keys": [
            "2adc0b6550a8692d06f7907f2283b556c58dbb2f52425e8fefaf9d9a861db92e",
            "c46a24ae2079a3556a5634f46ea9cc39fa760e6f78bcdc8b8e93307851dbe34f",
            "ea31de60b9c578b294c333209ac5925bedfc3aab8bedc15564ff24f696aba6af"
          ],
          "sign": 1,
          "start_exit_ms": 1756368000000
        },
        {
          "cohort_id": 53,
          "end_exit_ms": 1757376000000,
          "exit_groups": 3,
          "origin_keys": [
            "428905cd69a7a3e76e9dfd3255579237ec52be6122201a44ace33881e1ee47c8",
            "57df2b8e7677d5ef175fe1e3bed5da1b538e591195809d42e04946f07d5a9955",
            "62a1ecd9a5055c7fafa15edff164e12cc643c6d1dacc2dba19cc9ff6f76a0192",
            "6b549f02e4f064bbf7f4c40e4f51f94b9580167a0e1972608ddacf43c0ed34ac",
            "c6127a03ef0009f3f300690bc57de1882c9f9c2a234e6211a1955769f77408b0"
          ],
          "sign": -1,
          "start_exit_ms": 1756785600000
        },
        {
          "cohort_id": 54,
          "end_exit_ms": 1757635200000,
          "exit_groups": 3,
          "origin_keys": [
            "1c68a9cc14bdd4d08a9787b78b28f26e9ac4ebe70a07e7108f38487895199cf3",
            "eb9da654bf3fdb218cb78c6eab455ba63d5919565b52ce5ed54cba88c489db93",
            "f160d012b4eb926c79383261efa36103180162299f3ef7802efe75e8f5161450"
          ],
          "sign": 1,
          "start_exit_ms": 1757390400000
        },
        {
          "cohort_id": 55,
          "end_exit_ms": 1758052800000,
          "exit_groups": 2,
          "origin_keys": [
            "9e87739b9533756c1f3a5cba53e0ec0310b87524ee622d82057c4b3d0ae11e3a",
            "5b91366303f982be376a09ad7ec60f28c97722348abadb55e4614180885d8494",
            "6183540eaf7ee3778e78b8f4d8f8cbc7736977c475a71761e053c24a7e44e283",
            "c6309e88f62a6732468866d3fbf8b8b99fd3bcfa67c46b5ad8d5f497d650274f"
          ],
          "sign": -1,
          "start_exit_ms": 1757750400000
        },
        {
          "cohort_id": 56,
          "end_exit_ms": 1758240000000,
          "exit_groups": 3,
          "origin_keys": [
            "446c24a7ab0118e270580f92355def0e54c1f805a46924eba8477af8c43d6db3",
            "084205c0d23f84547fa462ce8f9949eb7525299fea73afbdbb958d422d815579",
            "5b8217ea755075291a5abafee4e933350a5545b7276cab5507cff0aa515ad7b3",
            "64961492ab5f443e90a8c9d564c918cfdce4ee3c606ef665241c4f0c2a96f75e"
          ],
          "sign": 1,
          "start_exit_ms": 1758139200000
        },
        {
          "cohort_id": 57,
          "end_exit_ms": 1758268800000,
          "exit_groups": 1,
          "origin_keys": [
            "319461a1067ffe81b0a9b34ec4e5678ae9de6a09dc2f66ef17cc4c4a09a2c730"
          ],
          "sign": -1,
          "start_exit_ms": 1758268800000
        },
        {
          "cohort_id": 58,
          "end_exit_ms": 1758312000000,
          "exit_groups": 1,
          "origin_keys": [
            "2567100622d709b4dadce9bc9984c5f759dd2871070bde93c87592cddcef3b69"
          ],
          "sign": 1,
          "start_exit_ms": 1758312000000
        },
        {
          "cohort_id": 59,
          "end_exit_ms": 1758542400000,
          "exit_groups": 3,
          "origin_keys": [
            "2cb7e5e850046b8607fd9b0cb9c7f0f2aeb120b13a6a1d50f764438965a23882",
            "554c51a2434a2ee43b490764a07e182d925621dbdb5a87d364e2d6b925a69c4e",
            "7167ad5b637d274e19469116dd430cf47e3fa43d9259e8d766a1b58d5247e381"
          ],
          "sign": -1,
          "start_exit_ms": 1758326400000
        },
        {
          "cohort_id": 60,
          "end_exit_ms": 1759780800000,
          "exit_groups": 1,
          "origin_keys": [
            "673673e4647d7f781ef34e86f6ab6f68b4e56d561629511e3dff804e2fc671b9"
          ],
          "sign": 1,
          "start_exit_ms": 1759780800000
        },
        {
          "cohort_id": 61,
          "end_exit_ms": 1759795200000,
          "exit_groups": 1,
          "origin_keys": [
            "35ed91621849376419f6a0416043957568e31d43b58965d228e0a880574e2118",
            "b281893de94140686bcbd995ee033670ee9076750fd90c016395f78e85a96224"
          ],
          "sign": -1,
          "start_exit_ms": 1759795200000
        },
        {
          "cohort_id": 62,
          "end_exit_ms": 1759809600000,
          "exit_groups": 1,
          "origin_keys": [
            "cfede36f952bb1cbafdc54a70967713c8d8900f29aebfedaa2683dac8a33a86e",
            "dc95dba52f37e16c5de4ccd174eaa3cc6e3ce42cdd52d1f6e2841c740a29209e"
          ],
          "sign": 1,
          "start_exit_ms": 1759809600000
        },
        {
          "cohort_id": 63,
          "end_exit_ms": 1762185600000,
          "exit_groups": 10,
          "origin_keys": [
            "6b15d4c81966c958f5e997c9caf2044debb3fddad3fd1969d5b022cf9f8e5b66",
            "d346d8f7ef310a5146f7cbd5edb0b096875d404f38193565e98f1903694dfaa6",
            "681c4acc892374e7bcd61098f01cc55c78648364b0a80492cfad92ce115adb96",
            "838b7a14075d36308a1a5ab625659a67f9be7cf6c23d20b03f869a40305a56a3",
            "6d7eb08e9607b2be435cacced40b81d9855211d28884d5b533cb61f20bd74fd6",
            "5e58f9cb119a8b70f2c4bb512362e1b7e01abc3d777b030a55dc34eff226844a",
            "f888e7d1e2866d29d3cd9fead0ba59a9c640b2a0a344b1a07c88e34cab792734",
            "71904ade42290aeffcefe5a884c06e6e43bb3f316316ca6025b4318cbe94c6d8",
            "8eaf489299cdec5d86e09ce744d53479600da0ce04381f2d640e33c1fc094db5",
            "9a17a25717bcb7603fddca5b6b6f1092fe9f037d524c36d2a920f5c502b3190a"
          ],
          "sign": -1,
          "start_exit_ms": 1759910400000
        },
        {
          "cohort_id": 64,
          "end_exit_ms": 1764316800000,
          "exit_groups": 2,
          "origin_keys": [
            "f04b345b13db9aef69e08301403563cd13bee3941d6c62e05f591694a5764ad7",
            "c2f731fadf077fedfbfdf44b7e5a0fb93953f2b0866afa1175c6f9775d38b1a2"
          ],
          "sign": 1,
          "start_exit_ms": 1763092800000
        },
        {
          "cohort_id": 65,
          "end_exit_ms": 1764504000000,
          "exit_groups": 1,
          "origin_keys": [
            "1b899f0e0e9a043529d9ff3ea24e4737f7ecd88b972cdccc07476aef05e5e951",
            "f3a7f3359ee694f3f2ec72d0883e89ff8244c00ad0ba3ab05e8a8fdcfcff5a7c"
          ],
          "sign": -1,
          "start_exit_ms": 1764504000000
        },
        {
          "cohort_id": 66,
          "end_exit_ms": 1764518400000,
          "exit_groups": 1,
          "origin_keys": [
            "0bdca7d41379168b140b2e66004f877e7ed16f1ec94ad27a829709e01d88dcfd"
          ],
          "sign": 1,
          "start_exit_ms": 1764518400000
        },
        {
          "cohort_id": 67,
          "end_exit_ms": 1765008000000,
          "exit_groups": 4,
          "origin_keys": [
            "096bc697ee57acd04f69b2bdafa69304be268939fa6fc7ce3e7d4a153993239d",
            "50ef6567fbd7df3446b1349d46cc3248422d6ac0b97efc4a25c0e41078dd9fa2",
            "8f2deb5337fb114b9d57c7ffc9866b6a3147b0b3736a493d25f9408a2952de70",
            "96d5be021062d7510e93873bbad3117337da5ca3fc3a5d22dfde06c7a45223c4"
          ],
          "sign": -1,
          "start_exit_ms": 1764547200000
        },
        {
          "cohort_id": 68,
          "end_exit_ms": 1765310400000,
          "exit_groups": 2,
          "origin_keys": [
            "0bb441638757d83417e5d34843eb3662cf34bc63b082e0543c9d4e6ea4c281a2",
            "8db5e99d7b412ef451f5f40543f15fa63a61ce198466589c3f312ac65c581f6f"
          ],
          "sign": 1,
          "start_exit_ms": 1765166400000
        },
        {
          "cohort_id": 69,
          "end_exit_ms": 1766534400000,
          "exit_groups": 7,
          "origin_keys": [
            "98415b5f82bd3af2ba758b66c93c9918aecfd9d3b1cca6f1c99f5fd6b1981665",
            "a97a1ea6fdb491a48099adef01ad75dd6269a7cf73b55ef7ec9f7155b6a56862",
            "06f11cb99f29537c27c1e17dd06ab6fa36592086e512f419221fab219e69025c",
            "98e92a785ee2e630812749980e5a0265365fb37533cd38ac8932dc77759b3137",
            "71ad5943e5ee593a23085130ebed82c16fe5e4084605413d3843385d3ceec257",
            "87a932ea0171d6110434a232dfd49105d4d3f1260f570d604c5ae0bbec3f9d70",
            "a56600ae8b8d496db0b3245e50dbbde722769f7fb538e778fc707eb4974a8006",
            "b8f4efc9ce43a92fe22dcb9ccfd9832f3d5b18e624a147236e626f2f61a9b930",
            "7592b8b06b52feeb652ccc01853e62faecdb8115c0564457f76aeb2254d34000"
          ],
          "sign": -1,
          "start_exit_ms": 1765425600000
        }
      ]
    },
    "M2": {
      "profit": {
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 1310.5748886442557,
          "2025-02": -761.0234153899764,
          "2025-03": 2470.4311978083038,
          "2025-04": 1838.8630243981263,
          "2025-05": 2205.9720871235313,
          "2025-06": -408.12256883323903,
          "2025-07": 4967.804509734142,
          "2025-08": 1967.25932584399,
          "2025-09": -215.31847302291004,
          "2025-10": -2245.8257949449185,
          "2025-11": -730.8118792014883,
          "2025-12": -4225.982139889011
        },
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -240.5194185674194,
          "BCH-USDT": 1419.7752928187406,
          "BTC-USDT": -438.5618730748823,
          "ETH-USDT": 1144.4295365565777,
          "HYPE-USDT": 3253.76558897476,
          "LINK-USDT": 2433.9064944266624,
          "SOL-USDT": -1398.9748588636328
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 6104.199865866797,
          "BCH-USDT": 7016.847084735873,
          "BTC-USDT": 2918.7945252576683,
          "ETH-USDT": 6080.729233915804,
          "HYPE-USDT": 9694.17793018207,
          "LINK-USDT": 6732.3144379023615,
          "SOL-USDT": 5154.787429339074
        },
        "top_decile_winner_T": 9,
        "top_decile_winners_share": 0.336863834653414,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.22182534189450412,
        "top_positive_month_share": 0.3365514850506828,
        "total_positive_trade_profit_bps": 43701.85050719965,
        "winner_T": 87
      },
      "market_event_weekly_clusters": [
        {
          "T": 1,
          "net_trade_sum_bps": 1310.5748886442557,
          "utc_monday_ms": 1737936000000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -579.3200423015144,
          "utc_monday_ms": 1738540800000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206,
          "utc_monday_ms": 1740355200000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 2017.2084680132564,
          "utc_monday_ms": 1740960000000
        },
        {
          "T": 3,
          "net_trade_sum_bps": 1494.4465256871222,
          "utc_monday_ms": 1742169600000
        },
        {
          "T": 5,
          "net_trade_sum_bps": -1041.223795892075,
          "utc_monday_ms": 1742774400000
        },
        {
          "T": 7,
          "net_trade_sum_bps": 1055.8074823177603,
          "utc_monday_ms": 1744588800000
        },
        {
          "T": 6,
          "net_trade_sum_bps": 2276.116862616642,
          "utc_monday_ms": 1745193600000
        },
        {
          "T": 14,
          "net_trade_sum_bps": -594.9182336351739,
          "utc_monday_ms": 1745798400000
        },
        {
          "T": 6,
          "net_trade_sum_bps": 2655.476734325638,
          "utc_monday_ms": 1746403200000
        },
        {
          "T": 15,
          "net_trade_sum_bps": -3152.577598185379,
          "utc_monday_ms": 1747008000000
        },
        {
          "T": 8,
          "net_trade_sum_bps": 3566.018441915256,
          "utc_monday_ms": 1747612800000
        },
        {
          "T": 9,
          "net_trade_sum_bps": -1761.088577833086,
          "utc_monday_ms": 1748217600000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -366.531824934293,
          "utc_monday_ms": 1748822400000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -160.18844467064713,
          "utc_monday_ms": 1749427200000
        },
        {
          "T": 3,
          "net_trade_sum_bps": 221.2239008236495,
          "utc_monday_ms": 1750032000000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -102.62620005194837,
          "utc_monday_ms": 1750636800000
        },
        {
          "T": 7,
          "net_trade_sum_bps": -543.8002154283296,
          "utc_monday_ms": 1751241600000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 1851.2712093926514,
          "utc_monday_ms": 1751846400000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 4259.490229351622,
          "utc_monday_ms": 1752451200000
        },
        {
          "T": 10,
          "net_trade_sum_bps": -476.96893056238866,
          "utc_monday_ms": 1753056000000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -320.77176670780455,
          "utc_monday_ms": 1753660800000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 3.3162155986788093,
          "utc_monday_ms": 1754265600000
        },
        {
          "T": 8,
          "net_trade_sum_bps": 751.7097577352685,
          "utc_monday_ms": 1754870400000
        },
        {
          "T": 5,
          "net_trade_sum_bps": 901.1157319480349,
          "utc_monday_ms": 1755475200000
        },
        {
          "T": 4,
          "net_trade_sum_bps": 509.7016042503997,
          "utc_monday_ms": 1756080000000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -578.3437006055626,
          "utc_monday_ms": 1756684800000
        },
        {
          "T": 5,
          "net_trade_sum_bps": 1651.873802833461,
          "utc_monday_ms": 1757289600000
        },
        {
          "T": 11,
          "net_trade_sum_bps": -429.8382366170974,
          "utc_monday_ms": 1757894400000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -859.0103386337111,
          "utc_monday_ms": 1758499200000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -359.57654723127064,
          "utc_monday_ms": 1759104000000
        },
        {
          "T": 10,
          "net_trade_sum_bps": -1363.0649597883255,
          "utc_monday_ms": 1759708800000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -919.0427590078841,
          "utc_monday_ms": 1761523200000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -139.76988474602933,
          "utc_monday_ms": 1762732800000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -195.18352337289707,
          "utc_monday_ms": 1763942400000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -1373.2093762526397,
          "utc_monday_ms": 1764547200000
        },
        {
          "T": 9,
          "net_trade_sum_bps": -2379.091014489322,
          "utc_monday_ms": 1765152000000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -473.68174914704906,
          "utc_monday_ms": 1766361600000
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "end_exit_ms": 1738310400000,
          "exit_groups": 1,
          "origin_keys": [
            "979b207a0cba154c4e56588b522459fa2902ad9ee30a61a24690b47f38d357e6"
          ],
          "sign": 1,
          "start_exit_ms": 1738310400000
        },
        {
          "cohort_id": 1,
          "end_exit_ms": 1740398400000,
          "exit_groups": 2,
          "origin_keys": [
            "75bc1657579c38bd14d06fb08329382d285734e221669423c07436b9168745f3",
            "e20ec6b5b1d64710658dccc8218f65bec8ec99a40af5f15cf38a37a4902efd57"
          ],
          "sign": -1,
          "start_exit_ms": 1738857600000
        },
        {
          "cohort_id": 2,
          "end_exit_ms": 1741291200000,
          "exit_groups": 1,
          "origin_keys": [
            "5d6e5b2ff3cf13258185ce91cb7c4e919d939674c0a8eb3b43bee07fbb02deb6"
          ],
          "sign": 1,
          "start_exit_ms": 1741291200000
        },
        {
          "cohort_id": 3,
          "end_exit_ms": 1741320000000,
          "exit_groups": 1,
          "origin_keys": [
            "3ba2fc0bf476825ddf705c60441b6695aa84f0134bde8a0de6895f244bbe5a6e"
          ],
          "sign": -1,
          "start_exit_ms": 1741320000000
        },
        {
          "cohort_id": 4,
          "end_exit_ms": 1742875200000,
          "exit_groups": 5,
          "origin_keys": [
            "4d5ff1901411d6d49cbce69c93cbc35f4d7bb8f5a9c9a77c44ee660c68c28e32",
            "1653ba4f1d26dff2261e9c362f004f8c74c8b766ce03e28276216c4ccab687dc",
            "c1127e43093e62cbe8bc16e1487a4dbf17ce66211259d19a6e5ed93a56095320",
            "e8a6e1ffe7c7d82419d74876b6a6c46f0e78bad36cdd9a091afc4a89323dbc35",
            "5a528e3ccae612a1a58eb63f60fb13cc6f88990b4cdc88471dcb9c3b4631c521"
          ],
          "sign": 1,
          "start_exit_ms": 1742371200000
        },
        {
          "cohort_id": 5,
          "end_exit_ms": 1744876800000,
          "exit_groups": 4,
          "origin_keys": [
            "196c03d2731521f1e86e4d797f11094e616708a19020dce4919dacc640f21060",
            "1708bab61045d1eeaa2c350e2e7851851f62a23daf078ff8998df30b18ed7d14",
            "711b1318d15c09603ef57558aa7a1f321f727f1dff1c4d08c6e41a755e5d3c3a",
            "c854aa8fd523fc736ca1f0b9acc5783788dc70558b58da7d91737d68ee88eec4"
          ],
          "sign": -1,
          "start_exit_ms": 1743004800000
        },
        {
          "cohort_id": 6,
          "end_exit_ms": 1745006400000,
          "exit_groups": 2,
          "origin_keys": [
            "11ff48ed506f83b9a9fa9267381bd2d96e7de9404c20349e175ed0db38927ae8",
            "9c1cc06b28d04eb6b93b11b379fff3ea7948f56ac55794d9003e490d48691ebb",
            "ab487bcd177eb3107deb68c125a05af61af7384a70cf079a682c2c129adc581f",
            "2061fca492db51368428be5f97a2337099a971b1842d4f29c72fb5ae77d1aa25"
          ],
          "sign": 1,
          "start_exit_ms": 1744992000000
        },
        {
          "cohort_id": 7,
          "end_exit_ms": 1745150400000,
          "exit_groups": 1,
          "origin_keys": [
            "6a17e80b6f6a73786f18faa40f8e3a691fe1f65bc2214d9ddccb1cacba42f3a1"
          ],
          "sign": -1,
          "start_exit_ms": 1745150400000
        },
        {
          "cohort_id": 8,
          "end_exit_ms": 1745366400000,
          "exit_groups": 4,
          "origin_keys": [
            "e1f389c1a4c16aa5bae8730c6d710e4e99e1f40b7a1278be9fffc2fc593c5a55",
            "54e6c4939b93069ee71a073f9a5a7b9ee5f32e6eb14fbf1ef64e5b05c56eab0f",
            "15f69d81e2bb95a5a72b262f18e8222757758b3138990c1d01b999cdc4da3c09",
            "3ad0f0c17337ad73dfebd624f47c0cf42535a2ecf32a0c9e0c23efbda8935e30",
            "0f9e0ad9a9c424f355d0fdc40b7b9f452b36a382a8c11e5d93e8fc8cb8812f7b"
          ],
          "sign": 1,
          "start_exit_ms": 1745179200000
        },
        {
          "cohort_id": 9,
          "end_exit_ms": 1745668800000,
          "exit_groups": 1,
          "origin_keys": [
            "4504481ef8c1c67ae04a5af5a8063e7ca5996ffb14cc64793242056b597b31cb"
          ],
          "sign": -1,
          "start_exit_ms": 1745668800000
        },
        {
          "cohort_id": 10,
          "end_exit_ms": 1745683200000,
          "exit_groups": 1,
          "origin_keys": [
            "ea78a8e6612680ae67dc8d6a43ac87831fd7402265ddde47cb87cae704a34f2a"
          ],
          "sign": 1,
          "start_exit_ms": 1745683200000
        },
        {
          "cohort_id": 11,
          "end_exit_ms": 1745956800000,
          "exit_groups": 2,
          "origin_keys": [
            "136c2d685362c73f9c8faac1906b1f0f6b39c96937143c502f1dafa8a17f4635",
            "618293610019999e13d4089b009d7d4f7243872a4800ba1651afc4ef5d78ae32",
            "ef80ea0ab964ded3cdbd87ba38a28fa6eb5edb7d734c2b5aa4c4f62794837d20"
          ],
          "sign": -1,
          "start_exit_ms": 1745856000000
        },
        {
          "cohort_id": 12,
          "end_exit_ms": 1745985600000,
          "exit_groups": 1,
          "origin_keys": [
            "45f7cd3f209d7eabbd187e7f0fec94a334dc2c79f7cf987251ea383993cfbb9b"
          ],
          "sign": 1,
          "start_exit_ms": 1745985600000
        },
        {
          "cohort_id": 13,
          "end_exit_ms": 1746028800000,
          "exit_groups": 2,
          "origin_keys": [
            "ad4f0095fed68a4b976ecb545563933251f5d099bc47915b8c67de1819455bb4",
            "b2e6e3962feac71b22eb2074e39a006cb98587f0725bf3109be8838ef695308a",
            "2a6edbf2a77ba9baccbbcad7d1ac4fa45547e5b199bfb7188e01fef99ea9f0f1",
            "8f8515e6532e5db846128d34e0acd9af583552e0154ecac8c07839a96cfa430b"
          ],
          "sign": -1,
          "start_exit_ms": 1746000000000
        },
        {
          "cohort_id": 14,
          "end_exit_ms": 1746244800000,
          "exit_groups": 4,
          "origin_keys": [
            "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77",
            "443656f5dc9edca0ebcdea7effb81353900acbd8e3568596f3b41b175c57c721",
            "66117e742708f66294f9f95ffa8f4508569ca50a81ef0ff2ed50ae5b21508b7a",
            "9f57fefae4501e2060405f7b470a13e8d60a6ebc9b825b311517e592dab05c18"
          ],
          "sign": 1,
          "start_exit_ms": 1746057600000
        },
        {
          "cohort_id": 15,
          "end_exit_ms": 1746532800000,
          "exit_groups": 4,
          "origin_keys": [
            "3d58ce6d768f2b3a9f9ec4e78dbcbd10c17801962fd80435b1900d7a3a2458bb",
            "c798df5ca9bb60fe80cee47c9a36ff1dae5485b87024b19d401247092885b5d6",
            "54b78a22139f7b6fc6d5a8c320c51466f5d1d0b370101c3b40221d9a51a8ecd5",
            "a414ff0468e67cedd06ac949d41cc4e377a5c3179a42c660ff0b8de3fdfc92f1",
            "437f79a339b9767f600ec378cd215060196d2354fc2a82b194def883ac5e5e94"
          ],
          "sign": -1,
          "start_exit_ms": 1746259200000
        },
        {
          "cohort_id": 16,
          "end_exit_ms": 1746835200000,
          "exit_groups": 3,
          "origin_keys": [
            "c22715040c25b6fa120e78b741bbd6aa34568c23f641a18898967fa9605765ed",
            "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
            "98d9d88ea5b38501a3f288f0b18d965f0ca2f3d4b971d011f6c4b3f696539466"
          ],
          "sign": 1,
          "start_exit_ms": 1746734400000
        },
        {
          "cohort_id": 17,
          "end_exit_ms": 1747137600000,
          "exit_groups": 1,
          "origin_keys": [
            "614f68e55b8871666bebe8710b0bf29a55c5a71bc88360169166f0b5cb0630ff",
            "7eafb7cae685ca0d1c66f35b17c30da5f58b571af67a9d38d545974f2953a2bb"
          ],
          "sign": -1,
          "start_exit_ms": 1747137600000
        },
        {
          "cohort_id": 18,
          "end_exit_ms": 1747267200000,
          "exit_groups": 1,
          "origin_keys": [
            "0699ffb8a34eae2af55c58494a1e85dffbf7b36aa8e425931ea7d037495506fa"
          ],
          "sign": 1,
          "start_exit_ms": 1747267200000
        },
        {
          "cohort_id": 19,
          "end_exit_ms": 1747483200000,
          "exit_groups": 3,
          "origin_keys": [
            "32d7355d1e8b6905432e9c1c04556f6b55d24b66827a68e18ece58943811bcc1",
            "994c40c0e2256268dde011f6f7d9fc1f972f2003cc15f350f2c2a2a82c7a439f",
            "dcae4bdf5d8ecbbd233ca0df467fee60f9a5d995fa76a2732c9190f4cd1860e6",
            "df5f82141ecb5edf4d9fa776242df2050725bc80a7fa0fbf15264585eb13aa2d",
            "1d528bb8ffde0df9b2af2eb4afa0b2ba2baa64b6feed2cd6c2728f06dfc039e7",
            "042d9748b7ad652fe6a1459db425be08a6a4ee9271a2ed26f7c2d7a8d49bfe0b",
            "a8e615a6faad7f5be3eaaaa1834f896ed1365beb77d5a8fcbdc70f12f3462b16"
          ],
          "sign": -1,
          "start_exit_ms": 1747296000000
        },
        {
          "cohort_id": 20,
          "end_exit_ms": 1747497600000,
          "exit_groups": 1,
          "origin_keys": [
            "3d76dfec91f65235b6b9528f7172d0f4b81cf455cd99f0d21020be81763780c2",
            "88d458309b458d10306f7ea1e344f5b0f924c5741006087fbcf9ff96d73e9279",
            "ebe480142f6fde44c8bd630e98949d1b5928821c747eb9e776bd2b56e13f9800"
          ],
          "sign": 1,
          "start_exit_ms": 1747497600000
        },
        {
          "cohort_id": 21,
          "end_exit_ms": 1747627200000,
          "exit_groups": 2,
          "origin_keys": [
            "6edb54a38352879b003aa03b19b60af41cfea5ed2fe58d45d32c36ff9b8036fb",
            "e6329bba085fc7a05bdfd0f60732a72382fc45a58d44d58671fc7a2c5a41d78d",
            "3b45e5a08e5b46c824e67cffc67750543f72613e1da6b5d08cb2d52d95a3f4dd"
          ],
          "sign": -1,
          "start_exit_ms": 1747598400000
        },
        {
          "cohort_id": 22,
          "end_exit_ms": 1747958400000,
          "exit_groups": 4,
          "origin_keys": [
            "1c033c7e7de80f564916f3b313f06fa64d43e200b4bd4f00c6f63fc63f41cd41",
            "2f8ad94eff3a7f569bc6c03875ae0c0ede863e07d0230d8b551f42d8a74a8df9",
            "58caa5c0de31b1d116e216d8f4e878d6050afe63914f6b025e6c09f3f9e2bd3e",
            "a10581de8ca6e0a3a8d39c7919e138b74e98b8a995d5c1d71b10bc23272e623e",
            "f2155391aa7764c59c85a1774bf8ec2783fdf8da4a5fdf1f7a3e77e7e43eb21f",
            "f4d6def625f4d88d6adbcbcc6c20c2ef2ece38e91cd8c40a8e26b2655f74aadf"
          ],
          "sign": 1,
          "start_exit_ms": 1747713600000
        },
        {
          "cohort_id": 23,
          "end_exit_ms": 1748160000000,
          "exit_groups": 1,
          "origin_keys": [
            "b79a83562bbb1fcf661f5da109bec9523bc2fbe18a6cc2ee2b9045b078870920"
          ],
          "sign": -1,
          "start_exit_ms": 1748160000000
        },
        {
          "cohort_id": 24,
          "end_exit_ms": 1748390400000,
          "exit_groups": 2,
          "origin_keys": [
            "6d3370d48c8dd5361e302db82f2faab51beb8134d32e053764712ba77b9847f2",
            "2309869ab033df7389c783f5f2491430e47c77c04811e44332342a27cf828f14",
            "8d1e9fb1a87540daedeec63a1bd37862547398d79b72b7411f8d46b027e1cea3"
          ],
          "sign": 1,
          "start_exit_ms": 1748260800000
        },
        {
          "cohort_id": 25,
          "end_exit_ms": 1750003200000,
          "exit_groups": 7,
          "origin_keys": [
            "23c94f724bf48a6e16603c297353285d71192d1cadfa92536f6299787da312dd",
            "025bb75df735c790d62747f3e13e8ca2ecf6e25cff47e05c2325121f4400cb62",
            "33f57ce14343f17bddeb7418ac566edd267076603ae156bdc4baf6823225f58e",
            "0a331de10b2976732100714d118f7ab16568669025031ce21fd3ed2ff51ce773",
            "aa3e034323ec63827bf0018347ef7d0a316702d5a0617020d04e8c858a1e2a8a",
            "fb48642108224d3fd03fb697ee7a20785f5171d1bd7cee02e2a5f31071d76a3d",
            "dba9bbf39a23532d0a92a6380648a5a82bb86abaaa2a1533200bea613985c5f9",
            "024114bc463b975bb2471e67185237d7bee62108dc9b572958bf60110d707c7f",
            "edee33a09ec6eb780a2ad5c573cf33227791b558457c97d5e2045ab17f3d554c"
          ],
          "sign": -1,
          "start_exit_ms": 1748404800000
        },
        {
          "cohort_id": 26,
          "end_exit_ms": 1750118400000,
          "exit_groups": 1,
          "origin_keys": [
            "87c161e5a0178ff7eca2cffd9a8d37631304339b34d0b8783cf85c19f8d4fff5"
          ],
          "sign": 1,
          "start_exit_ms": 1750118400000
        },
        {
          "cohort_id": 27,
          "end_exit_ms": 1750161600000,
          "exit_groups": 1,
          "origin_keys": [
            "346f7341f2bf3ca2b223cbb6c08980902fe7f1f65b9318434a2f735617f90af0"
          ],
          "sign": -1,
          "start_exit_ms": 1750161600000
        },
        {
          "cohort_id": 28,
          "end_exit_ms": 1750507200000,
          "exit_groups": 1,
          "origin_keys": [
            "fe8e0737e3379d2cef8489483a55b8b1e702cce913035dd0ea89742db9df1314"
          ],
          "sign": 1,
          "start_exit_ms": 1750507200000
        },
        {
          "cohort_id": 29,
          "end_exit_ms": 1750752000000,
          "exit_groups": 1,
          "origin_keys": [
            "39539c214fa857f57942fdecb68ca04e4d9b1018d4cbf98a027b0bce364fd025"
          ],
          "sign": -1,
          "start_exit_ms": 1750752000000
        },
        {
          "cohort_id": 30,
          "end_exit_ms": 1751356800000,
          "exit_groups": 2,
          "origin_keys": [
            "f8b2e6dbf975e01a4c24cd97e823cf2d2682b8c4ca2e60fd6ad9d67412e1f08f",
            "19b7e6cbf30ad251a04905bcbe18c261b3c3bc82fa95963ecd9c4c95ddfac24b"
          ],
          "sign": 1,
          "start_exit_ms": 1751169600000
        },
        {
          "cohort_id": 31,
          "end_exit_ms": 1751385600000,
          "exit_groups": 1,
          "origin_keys": [
            "ea90f21d84b730c28a1773be9ee1628a4daf2163a42ab9d96c480e4de0f0193e"
          ],
          "sign": -1,
          "start_exit_ms": 1751385600000
        },
        {
          "cohort_id": 32,
          "end_exit_ms": 1751616000000,
          "exit_groups": 1,
          "origin_keys": [
            "5dc1f4defbfbc3fa4dc1acb116712938b0a3552d6a89b263aaad65507c8dbd26",
            "96ed746cc89114bc96aac5280111eea20edd9a85e84ab8419892e4e8f9fb98cd"
          ],
          "sign": 1,
          "start_exit_ms": 1751616000000
        },
        {
          "cohort_id": 33,
          "end_exit_ms": 1751731200000,
          "exit_groups": 2,
          "origin_keys": [
            "64fee382be25139512d408919e8250d563f51d560dd3b813196fdd208868c8d1",
            "ccd2a420e644f4be3c60d0b80e6328f0b025f3b9e7258bcba646be88e60ca47f",
            "96a7eaa94ec10a0dc4fed1a17b04fca7a0d6ce97a652a93ce32f852597731eca"
          ],
          "sign": -1,
          "start_exit_ms": 1751644800000
        },
        {
          "cohort_id": 34,
          "end_exit_ms": 1751860800000,
          "exit_groups": 1,
          "origin_keys": [
            "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569"
          ],
          "sign": 1,
          "start_exit_ms": 1751860800000
        },
        {
          "cohort_id": 35,
          "end_exit_ms": 1751990400000,
          "exit_groups": 2,
          "origin_keys": [
            "a87ac993ed55790f6527004a16cd082a003328436ad856153d97b67f81c32b3c",
            "1db87f8de43b59b15f878d313cfc72243fc58147aba4e2a1d092d175f11a6420",
            "5670edf0d14be75b650617df11623e0c264c928e01761685247611300e2c2b4e",
            "d4587f56aa58595f4a5c34cb1c8d91539ec6b99ae14be7a6f3791416a8d508a8"
          ],
          "sign": -1,
          "start_exit_ms": 1751947200000
        },
        {
          "cohort_id": 36,
          "end_exit_ms": 1752177600000,
          "exit_groups": 2,
          "origin_keys": [
            "7580befe0c0c1ebfe54b91a1135cd1c53d3864646f191c09a6825a74bb37bb9a",
            "0849bb8f17c8313ebc2ae91114edfd46c6f62986e96607f92da1776c575d6ea3",
            "588117c7ecbadbf1bd2d05794cc3719559963cbeae1c93b38b0a6ed478c372c8"
          ],
          "sign": 1,
          "start_exit_ms": 1752134400000
        },
        {
          "cohort_id": 37,
          "end_exit_ms": 1752350400000,
          "exit_groups": 1,
          "origin_keys": [
            "6c79f7624a88231c465b70a25a0548f526f4c38ee7bf9fd10beeaf91f078f348"
          ],
          "sign": -1,
          "start_exit_ms": 1752350400000
        },
        {
          "cohort_id": 38,
          "end_exit_ms": 1752523200000,
          "exit_groups": 1,
          "origin_keys": [
            "4135d00ba44ebc5cf362711a4abee2e6d01c478113057178d7b0ea1f56c7e916",
            "c4b037954cd3a617621503a5d77862a4938eef8c6a6327ed5330b232b49ed2c6"
          ],
          "sign": 1,
          "start_exit_ms": 1752523200000
        },
        {
          "cohort_id": 39,
          "end_exit_ms": 1752710400000,
          "exit_groups": 2,
          "origin_keys": [
            "6bcecc02427a0ab87800a8061d36d4d0c8fb501f79b12637a45b21655b0f9221",
            "1f62363ddf4605200913f11e62d56c828b95351635929f111bd69433e45bade4"
          ],
          "sign": -1,
          "start_exit_ms": 1752552000000
        },
        {
          "cohort_id": 40,
          "end_exit_ms": 1752825600000,
          "exit_groups": 4,
          "origin_keys": [
            "ad79f7e334f3d55db655513fa0d0b4c8b86d80c941edf24bfcbb43fac93ed175",
            "47dd745683e2b505200b6d7e1fc1ede9415e6a8d5b5aafb1c19767cb1332b910",
            "52b2c7f77188ca8227f75c8db34792dd70799a9ad5ff7cd3319389ceec23568a",
            "0d2b35ab633f4d557b8498f19d4a4520d5b9a0efb7ba02443b9ae02d1091d3e6",
            "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530"
          ],
          "sign": 1,
          "start_exit_ms": 1752739200000
        },
        {
          "cohort_id": 41,
          "end_exit_ms": 1753056000000,
          "exit_groups": 1,
          "origin_keys": [
            "d88d6da82807ed73485910acdb84b99de13e8b250836cce7b9e4604a05804a5e"
          ],
          "sign": -1,
          "start_exit_ms": 1753056000000
        },
        {
          "cohort_id": 42,
          "end_exit_ms": 1753128000000,
          "exit_groups": 2,
          "origin_keys": [
            "a9a3e8365fcc187a032b988186095539cef032de8177ce8cd707794f13c41178",
            "130a5d5d13a47060b238ee0b3ea34039c17b4d62c365ed662db54151cb725994"
          ],
          "sign": 1,
          "start_exit_ms": 1753070400000
        },
        {
          "cohort_id": 43,
          "end_exit_ms": 1753545600000,
          "exit_groups": 6,
          "origin_keys": [
            "e8c732e46d0580a95e52293b59277c9ba520fdc091bf689bd5ae2e21d33050dd",
            "3cd227554c6bd53fad0d12e860efe081bd24b05cccf9e1d794a182c8c4dcad6e",
            "8a5d77ec50be4dde6278d0637ccd74d2208b8fdb80e2fe1aafd67d12055bbe9b",
            "7af2a28e7e974d6aea365bca7852e315a945200b974024e626335ee7577f02d7",
            "81f03a46613732f84a14cc6faf711252ca5de24205bf3fca9360c100254dde55",
            "63792578bc411889e22ef91262a5824732a8d1ae57a0ded1ca745836604b9ca0"
          ],
          "sign": -1,
          "start_exit_ms": 1753286400000
        },
        {
          "cohort_id": 44,
          "end_exit_ms": 1753660800000,
          "exit_groups": 2,
          "origin_keys": [
            "557b95fc65cbf0a8035281ddc5e29e72cd7bc95790782d8b7411eecf313ca04e",
            "10a7b67bfcf5fdef4e36f5eea44c22d0c15966fe732ee607db46507ea2c37308",
            "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1"
          ],
          "sign": 1,
          "start_exit_ms": 1753603200000
        },
        {
          "cohort_id": 45,
          "end_exit_ms": 1754035200000,
          "exit_groups": 3,
          "origin_keys": [
            "72b8b528d33ac98c9e17345c6de9613fe8d6014697570c41ea668548c0f2e6ae",
            "da7ef6e9025099319f5576f5f52136b82c6f1ec5029bcf9e25045c2badadd7fd",
            "71902b786b8aa54c87f1430de51e32e03473b5c94413248f360662735a04ef94",
            "eacc20084995a3ab4a7da3fa3ca8dbab480710b7067c84bc8292646e35c78df3"
          ],
          "sign": -1,
          "start_exit_ms": 1753804800000
        },
        {
          "cohort_id": 46,
          "end_exit_ms": 1754640000000,
          "exit_groups": 1,
          "origin_keys": [
            "b39417684ba0dd296a071fcc13fe5216b1b6844235c84549dc686fccb4673de2"
          ],
          "sign": 1,
          "start_exit_ms": 1754640000000
        },
        {
          "cohort_id": 47,
          "end_exit_ms": 1754812800000,
          "exit_groups": 1,
          "origin_keys": [
            "426aaff0097e98b6f0e7cc599671e126621e79f81c2d9456d7d68d4dc6ce0e50"
          ],
          "sign": -1,
          "start_exit_ms": 1754812800000
        },
        {
          "cohort_id": 48,
          "end_exit_ms": 1755144000000,
          "exit_groups": 2,
          "origin_keys": [
            "a6dd07b321410fe650cca40b7fba4a0319308127876915148c36d7d211015c8d",
            "fa2227abd88b8c794620d6219457b183c6b3c8053e46cdabdf4ff044408ae2e8"
          ],
          "sign": 1,
          "start_exit_ms": 1755100800000
        },
        {
          "cohort_id": 49,
          "end_exit_ms": 1755273600000,
          "exit_groups": 2,
          "origin_keys": [
            "86080a597e0bc1116384e954acd6b0c32041e73eec3b5942be80a252744afa0d",
            "97ac73b0f3529903ed9ea201036b3a9a435d9f8242a6960923498385c043fde6",
            "d8c4f5ef31ad715ad9c25e6dbcb30b68461f2f90690cb945d7860890f229bfc0",
            "23afcd4e4c4688f46d0a8905fb2ed0da9124e917c61c1c8310d2bbd3f05a9253"
          ],
          "sign": -1,
          "start_exit_ms": 1755187200000
        },
        {
          "cohort_id": 50,
          "end_exit_ms": 1755374400000,
          "exit_groups": 1,
          "origin_keys": [
            "26f83f96f1a03e42ad86c962382630587b92091985220c144f5c7f898fa19067"
          ],
          "sign": 1,
          "start_exit_ms": 1755374400000
        },
        {
          "cohort_id": 51,
          "end_exit_ms": 1755489600000,
          "exit_groups": 2,
          "origin_keys": [
            "d982dd8e49b3f106e644332a4059d1194d1d35aee6d350030b4372357aea69b9",
            "0d6aa06212cbc737dcc220fe2a05a8b0915ef9cbbaeeff4122e1226468ce37f9",
            "8192c69c9ec4091daed78995d26184cd0f43e977592742eb3f1fb55906840011"
          ],
          "sign": -1,
          "start_exit_ms": 1755403200000
        },
        {
          "cohort_id": 52,
          "end_exit_ms": 1756022400000,
          "exit_groups": 3,
          "origin_keys": [
            "d42bc424b418ebd385e34b86cfaafa6df637e49e5d03982b8bf2a22f33c6c63a",
            "23bdd736b6f855d35443df00de3082fc216d437a3f7b5535adb2b3a3965c802a",
            "2a31409627d7f1beff834be00cd1d4b4f8f24cebba69f13c1e941d9ef6a9c809"
          ],
          "sign": 1,
          "start_exit_ms": 1755547200000
        },
        {
          "cohort_id": 53,
          "end_exit_ms": 1756108800000,
          "exit_groups": 1,
          "origin_keys": [
            "d1b4cfd5ebf80e5ed19f62d16eda0239aaa594558936a7e9760b06bd1999ac97"
          ],
          "sign": -1,
          "start_exit_ms": 1756108800000
        },
        {
          "cohort_id": 54,
          "end_exit_ms": 1756411200000,
          "exit_groups": 2,
          "origin_keys": [
            "2adc0b6550a8692d06f7907f2283b556c58dbb2f52425e8fefaf9d9a861db92e",
            "c46a24ae2079a3556a5634f46ea9cc39fa760e6f78bcdc8b8e93307851dbe34f",
            "ea31de60b9c578b294c333209ac5925bedfc3aab8bedc15564ff24f696aba6af"
          ],
          "sign": 1,
          "start_exit_ms": 1756368000000
        },
        {
          "cohort_id": 55,
          "end_exit_ms": 1757188800000,
          "exit_groups": 3,
          "origin_keys": [
            "428905cd69a7a3e76e9dfd3255579237ec52be6122201a44ace33881e1ee47c8",
            "6b549f02e4f064bbf7f4c40e4f51f94b9580167a0e1972608ddacf43c0ed34ac",
            "57df2b8e7677d5ef175fe1e3bed5da1b538e591195809d42e04946f07d5a9955"
          ],
          "sign": -1,
          "start_exit_ms": 1756684800000
        },
        {
          "cohort_id": 56,
          "end_exit_ms": 1757203200000,
          "exit_groups": 1,
          "origin_keys": [
            "62a1ecd9a5055c7fafa15edff164e12cc643c6d1dacc2dba19cc9ff6f76a0192"
          ],
          "sign": 1,
          "start_exit_ms": 1757203200000
        },
        {
          "cohort_id": 57,
          "end_exit_ms": 1757376000000,
          "exit_groups": 1,
          "origin_keys": [
            "c6127a03ef0009f3f300690bc57de1882c9f9c2a234e6211a1955769f77408b0"
          ],
          "sign": -1,
          "start_exit_ms": 1757376000000
        },
        {
          "cohort_id": 58,
          "end_exit_ms": 1757635200000,
          "exit_groups": 3,
          "origin_keys": [
            "1c68a9cc14bdd4d08a9787b78b28f26e9ac4ebe70a07e7108f38487895199cf3",
            "eb9da654bf3fdb218cb78c6eab455ba63d5919565b52ce5ed54cba88c489db93",
            "f160d012b4eb926c79383261efa36103180162299f3ef7802efe75e8f5161450"
          ],
          "sign": 1,
          "start_exit_ms": 1757390400000
        },
        {
          "cohort_id": 59,
          "end_exit_ms": 1758052800000,
          "exit_groups": 3,
          "origin_keys": [
            "9e87739b9533756c1f3a5cba53e0ec0310b87524ee622d82057c4b3d0ae11e3a",
            "6183540eaf7ee3778e78b8f4d8f8cbc7736977c475a71761e053c24a7e44e283",
            "5b91366303f982be376a09ad7ec60f28c97722348abadb55e4614180885d8494",
            "c6309e88f62a6732468866d3fbf8b8b99fd3bcfa67c46b5ad8d5f497d650274f"
          ],
          "sign": -1,
          "start_exit_ms": 1757750400000
        },
        {
          "cohort_id": 60,
          "end_exit_ms": 1758240000000,
          "exit_groups": 3,
          "origin_keys": [
            "446c24a7ab0118e270580f92355def0e54c1f805a46924eba8477af8c43d6db3",
            "084205c0d23f84547fa462ce8f9949eb7525299fea73afbdbb958d422d815579",
            "5b8217ea755075291a5abafee4e933350a5545b7276cab5507cff0aa515ad7b3",
            "64961492ab5f443e90a8c9d564c918cfdce4ee3c606ef665241c4f0c2a96f75e"
          ],
          "sign": 1,
          "start_exit_ms": 1758139200000
        },
        {
          "cohort_id": 61,
          "end_exit_ms": 1759723200000,
          "exit_groups": 6,
          "origin_keys": [
            "319461a1067ffe81b0a9b34ec4e5678ae9de6a09dc2f66ef17cc4c4a09a2c730",
            "2567100622d709b4dadce9bc9984c5f759dd2871070bde93c87592cddcef3b69",
            "2cb7e5e850046b8607fd9b0cb9c7f0f2aeb120b13a6a1d50f764438965a23882",
            "554c51a2434a2ee43b490764a07e182d925621dbdb5a87d364e2d6b925a69c4e",
            "7167ad5b637d274e19469116dd430cf47e3fa43d9259e8d766a1b58d5247e381",
            "b281893de94140686bcbd995ee033670ee9076750fd90c016395f78e85a96224",
            "cfede36f952bb1cbafdc54a70967713c8d8900f29aebfedaa2683dac8a33a86e"
          ],
          "sign": -1,
          "start_exit_ms": 1758268800000
        },
        {
          "cohort_id": 62,
          "end_exit_ms": 1759809600000,
          "exit_groups": 3,
          "origin_keys": [
            "673673e4647d7f781ef34e86f6ab6f68b4e56d561629511e3dff804e2fc671b9",
            "35ed91621849376419f6a0416043957568e31d43b58965d228e0a880574e2118",
            "dc95dba52f37e16c5de4ccd174eaa3cc6e3ce42cdd52d1f6e2841c740a29209e"
          ],
          "sign": 1,
          "start_exit_ms": 1759780800000
        },
        {
          "cohort_id": 63,
          "end_exit_ms": 1762977600000,
          "exit_groups": 10,
          "origin_keys": [
            "6b15d4c81966c958f5e997c9caf2044debb3fddad3fd1969d5b022cf9f8e5b66",
            "6d7eb08e9607b2be435cacced40b81d9855211d28884d5b533cb61f20bd74fd6",
            "681c4acc892374e7bcd61098f01cc55c78648364b0a80492cfad92ce115adb96",
            "d346d8f7ef310a5146f7cbd5edb0b096875d404f38193565e98f1903694dfaa6",
            "838b7a14075d36308a1a5ab625659a67f9be7cf6c23d20b03f869a40305a56a3",
            "5e58f9cb119a8b70f2c4bb512362e1b7e01abc3d777b030a55dc34eff226844a",
            "f888e7d1e2866d29d3cd9fead0ba59a9c640b2a0a344b1a07c88e34cab792734",
            "71904ade42290aeffcefe5a884c06e6e43bb3f316316ca6025b4318cbe94c6d8",
            "8eaf489299cdec5d86e09ce744d53479600da0ce04381f2d640e33c1fc094db5",
            "9a17a25717bcb7603fddca5b6b6f1092fe9f037d524c36d2a920f5c502b3190a",
            "f04b345b13db9aef69e08301403563cd13bee3941d6c62e05f591694a5764ad7"
          ],
          "sign": -1,
          "start_exit_ms": 1759852800000
        },
        {
          "cohort_id": 64,
          "end_exit_ms": 1764316800000,
          "exit_groups": 1,
          "origin_keys": [
            "c2f731fadf077fedfbfdf44b7e5a0fb93953f2b0866afa1175c6f9775d38b1a2"
          ],
          "sign": 1,
          "start_exit_ms": 1764316800000
        },
        {
          "cohort_id": 65,
          "end_exit_ms": 1764446400000,
          "exit_groups": 2,
          "origin_keys": [
            "1b899f0e0e9a043529d9ff3ea24e4737f7ecd88b972cdccc07476aef05e5e951",
            "f3a7f3359ee694f3f2ec72d0883e89ff8244c00ad0ba3ab05e8a8fdcfcff5a7c"
          ],
          "sign": -1,
          "start_exit_ms": 1764360000000
        },
        {
          "cohort_id": 66,
          "end_exit_ms": 1764518400000,
          "exit_groups": 1,
          "origin_keys": [
            "0bdca7d41379168b140b2e66004f877e7ed16f1ec94ad27a829709e01d88dcfd"
          ],
          "sign": 1,
          "start_exit_ms": 1764518400000
        },
        {
          "cohort_id": 67,
          "end_exit_ms": 1764936000000,
          "exit_groups": 3,
          "origin_keys": [
            "096bc697ee57acd04f69b2bdafa69304be268939fa6fc7ce3e7d4a153993239d",
            "50ef6567fbd7df3446b1349d46cc3248422d6ac0b97efc4a25c0e41078dd9fa2",
            "8f2deb5337fb114b9d57c7ffc9866b6a3147b0b3736a493d25f9408a2952de70",
            "96d5be021062d7510e93873bbad3117337da5ca3fc3a5d22dfde06c7a45223c4"
          ],
          "sign": -1,
          "start_exit_ms": 1764547200000
        },
        {
          "cohort_id": 68,
          "end_exit_ms": 1765310400000,
          "exit_groups": 2,
          "origin_keys": [
            "0bb441638757d83417e5d34843eb3662cf34bc63b082e0543c9d4e6ea4c281a2",
            "8db5e99d7b412ef451f5f40543f15fa63a61ce198466589c3f312ac65c581f6f"
          ],
          "sign": 1,
          "start_exit_ms": 1765166400000
        },
        {
          "cohort_id": 69,
          "end_exit_ms": 1766534400000,
          "exit_groups": 5,
          "origin_keys": [
            "06f11cb99f29537c27c1e17dd06ab6fa36592086e512f419221fab219e69025c",
            "98415b5f82bd3af2ba758b66c93c9918aecfd9d3b1cca6f1c99f5fd6b1981665",
            "98e92a785ee2e630812749980e5a0265365fb37533cd38ac8932dc77759b3137",
            "a97a1ea6fdb491a48099adef01ad75dd6269a7cf73b55ef7ec9f7155b6a56862",
            "71ad5943e5ee593a23085130ebed82c16fe5e4084605413d3843385d3ceec257",
            "87a932ea0171d6110434a232dfd49105d4d3f1260f570d604c5ae0bbec3f9d70",
            "a56600ae8b8d496db0b3245e50dbbde722769f7fb538e778fc707eb4974a8006",
            "b8f4efc9ce43a92fe22dcb9ccfd9832f3d5b18e624a147236e626f2f61a9b930",
            "7592b8b06b52feeb652ccc01853e62faecdb8115c0564457f76aeb2254d34000"
          ],
          "sign": -1,
          "start_exit_ms": 1765339200000
        }
      ]
    },
    "KR1_FULL": {
      "profit": {
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": 56.5713089727991,
          "2025-03": 4880.283117333632,
          "2025-04": 4564.550865732531,
          "2025-05": 3525.509850653099,
          "2025-06": -800.1534246882177,
          "2025-07": 6680.569982233538,
          "2025-08": -1151.5517915307873,
          "2025-09": 320.75904581315876,
          "2025-10": -2726.486181187657,
          "2025-11": -730.2498393716005,
          "2025-12": -5175.6004536478695
        },
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 2211.0366441450406,
          "BCH-USDT": -393.1522234036873,
          "BTC-USDT": 451.1392458148923,
          "ETH-USDT": 3910.0094626907453,
          "HYPE-USDT": 3061.0434157407167,
          "LINK-USDT": 1587.1323625443717,
          "SOL-USDT": -1383.0064272194513
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 8555.755928579256,
          "BCH-USDT": 5641.82955538924,
          "BTC-USDT": 3907.4867566955436,
          "ETH-USDT": 8840.117321438644,
          "HYPE-USDT": 9720.923113858606,
          "LINK-USDT": 5913.498450079142,
          "SOL-USDT": 5171.726727698478
        },
        "top_decile_winner_T": 9,
        "top_decile_winners_share": 0.44884955904215873,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.203573837944259,
        "top_positive_month_share": 0.3335574464382576,
        "total_positive_trade_profit_bps": 47751.33785373891,
        "winner_T": 81
      },
      "market_event_weekly_clusters": [
        {
          "T": 1,
          "net_trade_sum_bps": 817.5947243627755,
          "utc_monday_ms": 1737936000000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -579.3200423015144,
          "utc_monday_ms": 1738540800000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206,
          "utc_monday_ms": 1740355200000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 2055.081564169959,
          "utc_monday_ms": 1740960000000
        },
        {
          "T": 1,
          "net_trade_sum_bps": 685.041899176842,
          "utc_monday_ms": 1742169600000
        },
        {
          "T": 7,
          "net_trade_sum_bps": 2140.159653986831,
          "utc_monday_ms": 1742774400000
        },
        {
          "T": 6,
          "net_trade_sum_bps": 1237.8178580301912,
          "utc_monday_ms": 1744588800000
        },
        {
          "T": 7,
          "net_trade_sum_bps": 4819.174363356517,
          "utc_monday_ms": 1745193600000
        },
        {
          "T": 14,
          "net_trade_sum_bps": -1128.5171548609667,
          "utc_monday_ms": 1745798400000
        },
        {
          "T": 6,
          "net_trade_sum_bps": 4808.170503176422,
          "utc_monday_ms": 1746403200000
        },
        {
          "T": 15,
          "net_trade_sum_bps": -3531.986040104079,
          "utc_monday_ms": 1747008000000
        },
        {
          "T": 8,
          "net_trade_sum_bps": 3802.2170424834176,
          "utc_monday_ms": 1747612800000
        },
        {
          "T": 9,
          "net_trade_sum_bps": -1916.8158556958726,
          "utc_monday_ms": 1748217600000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -366.531824934293,
          "utc_monday_ms": 1748822400000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -344.6236840662,
          "utc_monday_ms": 1749427200000
        },
        {
          "T": 3,
          "net_trade_sum_bps": 76.30836362043397,
          "utc_monday_ms": 1750032000000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -194.0335079440669,
          "utc_monday_ms": 1750636800000
        },
        {
          "T": 8,
          "net_trade_sum_bps": -823.2476084392875,
          "utc_monday_ms": 1751241600000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 4754.208666423764,
          "utc_monday_ms": 1751846400000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 4385.434311968081,
          "utc_monday_ms": 1752451200000
        },
        {
          "T": 8,
          "net_trade_sum_bps": -2055.77426014282,
          "utc_monday_ms": 1753056000000
        },
        {
          "T": 8,
          "net_trade_sum_bps": 250.09211737131767,
          "utc_monday_ms": 1753660800000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -212.65995025226442,
          "utc_monday_ms": 1754265600000
        },
        {
          "T": 8,
          "net_trade_sum_bps": -213.34519196819411,
          "utc_monday_ms": 1754870400000
        },
        {
          "T": 5,
          "net_trade_sum_bps": -158.9339400318845,
          "utc_monday_ms": 1755475200000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -368.0287255900525,
          "utc_monday_ms": 1756080000000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -578.3437006055626,
          "utc_monday_ms": 1756684800000
        },
        {
          "T": 5,
          "net_trade_sum_bps": 3039.435402516072,
          "utc_monday_ms": 1757289600000
        },
        {
          "T": 11,
          "net_trade_sum_bps": -1281.3223174636394,
          "utc_monday_ms": 1757894400000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -859.0103386337111,
          "utc_monday_ms": 1758499200000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -359.57654723127064,
          "utc_monday_ms": 1759104000000
        },
        {
          "T": 10,
          "net_trade_sum_bps": -1843.725346031064,
          "utc_monday_ms": 1759708800000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -919.0427590078841,
          "utc_monday_ms": 1761523200000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -139.76988474602933,
          "utc_monday_ms": 1762732800000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -194.62148354300928,
          "utc_monday_ms": 1763942400000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -1373.2093762526397,
          "utc_monday_ms": 1764547200000
        },
        {
          "T": 9,
          "net_trade_sum_bps": -3328.709328248181,
          "utc_monday_ms": 1765152000000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -473.68174914704906,
          "utc_monday_ms": 1766361600000
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "end_exit_ms": 1738440000000,
          "exit_groups": 1,
          "origin_keys": [
            "979b207a0cba154c4e56588b522459fa2902ad9ee30a61a24690b47f38d357e6"
          ],
          "sign": 1,
          "start_exit_ms": 1738440000000
        },
        {
          "cohort_id": 1,
          "end_exit_ms": 1741320000000,
          "exit_groups": 3,
          "origin_keys": [
            "75bc1657579c38bd14d06fb08329382d285734e221669423c07436b9168745f3",
            "e20ec6b5b1d64710658dccc8218f65bec8ec99a40af5f15cf38a37a4902efd57",
            "3ba2fc0bf476825ddf705c60441b6695aa84f0134bde8a0de6895f244bbe5a6e"
          ],
          "sign": -1,
          "start_exit_ms": 1738857600000
        },
        {
          "cohort_id": 2,
          "end_exit_ms": 1742990400000,
          "exit_groups": 5,
          "origin_keys": [
            "5d6e5b2ff3cf13258185ce91cb7c4e919d939674c0a8eb3b43bee07fbb02deb6",
            "4d5ff1901411d6d49cbce69c93cbc35f4d7bb8f5a9c9a77c44ee660c68c28e32",
            "1653ba4f1d26dff2261e9c362f004f8c74c8b766ce03e28276216c4ccab687dc",
            "c1127e43093e62cbe8bc16e1487a4dbf17ce66211259d19a6e5ed93a56095320",
            "e8a6e1ffe7c7d82419d74876b6a6c46f0e78bad36cdd9a091afc4a89323dbc35"
          ],
          "sign": 1,
          "start_exit_ms": 1741464000000
        },
        {
          "cohort_id": 3,
          "end_exit_ms": 1743004800000,
          "exit_groups": 1,
          "origin_keys": [
            "196c03d2731521f1e86e4d797f11094e616708a19020dce4919dacc640f21060"
          ],
          "sign": -1,
          "start_exit_ms": 1743004800000
        },
        {
          "cohort_id": 4,
          "end_exit_ms": 1743048000000,
          "exit_groups": 1,
          "origin_keys": [
            "5a528e3ccae612a1a58eb63f60fb13cc6f88990b4cdc88471dcb9c3b4631c521"
          ],
          "sign": 1,
          "start_exit_ms": 1743048000000
        },
        {
          "cohort_id": 5,
          "end_exit_ms": 1744992000000,
          "exit_groups": 4,
          "origin_keys": [
            "1708bab61045d1eeaa2c350e2e7851851f62a23daf078ff8998df30b18ed7d14",
            "711b1318d15c09603ef57558aa7a1f321f727f1dff1c4d08c6e41a755e5d3c3a",
            "c854aa8fd523fc736ca1f0b9acc5783788dc70558b58da7d91737d68ee88eec4",
            "11ff48ed506f83b9a9fa9267381bd2d96e7de9404c20349e175ed0db38927ae8"
          ],
          "sign": -1,
          "start_exit_ms": 1743148800000
        },
        {
          "cohort_id": 6,
          "end_exit_ms": 1745006400000,
          "exit_groups": 1,
          "origin_keys": [
            "2061fca492db51368428be5f97a2337099a971b1842d4f29c72fb5ae77d1aa25"
          ],
          "sign": 1,
          "start_exit_ms": 1745006400000
        },
        {
          "cohort_id": 7,
          "end_exit_ms": 1745150400000,
          "exit_groups": 1,
          "origin_keys": [
            "6a17e80b6f6a73786f18faa40f8e3a691fe1f65bc2214d9ddccb1cacba42f3a1"
          ],
          "sign": -1,
          "start_exit_ms": 1745150400000
        },
        {
          "cohort_id": 8,
          "end_exit_ms": 1745539200000,
          "exit_groups": 6,
          "origin_keys": [
            "9c1cc06b28d04eb6b93b11b379fff3ea7948f56ac55794d9003e490d48691ebb",
            "ab487bcd177eb3107deb68c125a05af61af7384a70cf079a682c2c129adc581f",
            "e1f389c1a4c16aa5bae8730c6d710e4e99e1f40b7a1278be9fffc2fc593c5a55",
            "54e6c4939b93069ee71a073f9a5a7b9ee5f32e6eb14fbf1ef64e5b05c56eab0f",
            "3ad0f0c17337ad73dfebd624f47c0cf42535a2ecf32a0c9e0c23efbda8935e30",
            "15f69d81e2bb95a5a72b262f18e8222757758b3138990c1d01b999cdc4da3c09",
            "0f9e0ad9a9c424f355d0fdc40b7b9f452b36a382a8c11e5d93e8fc8cb8812f7b"
          ],
          "sign": 1,
          "start_exit_ms": 1745164800000
        },
        {
          "cohort_id": 9,
          "end_exit_ms": 1745668800000,
          "exit_groups": 1,
          "origin_keys": [
            "4504481ef8c1c67ae04a5af5a8063e7ca5996ffb14cc64793242056b597b31cb"
          ],
          "sign": -1,
          "start_exit_ms": 1745668800000
        },
        {
          "cohort_id": 10,
          "end_exit_ms": 1745683200000,
          "exit_groups": 1,
          "origin_keys": [
            "ea78a8e6612680ae67dc8d6a43ac87831fd7402265ddde47cb87cae704a34f2a"
          ],
          "sign": 1,
          "start_exit_ms": 1745683200000
        },
        {
          "cohort_id": 11,
          "end_exit_ms": 1745956800000,
          "exit_groups": 2,
          "origin_keys": [
            "136c2d685362c73f9c8faac1906b1f0f6b39c96937143c502f1dafa8a17f4635",
            "618293610019999e13d4089b009d7d4f7243872a4800ba1651afc4ef5d78ae32",
            "ef80ea0ab964ded3cdbd87ba38a28fa6eb5edb7d734c2b5aa4c4f62794837d20"
          ],
          "sign": -1,
          "start_exit_ms": 1745856000000
        },
        {
          "cohort_id": 12,
          "end_exit_ms": 1745985600000,
          "exit_groups": 1,
          "origin_keys": [
            "45f7cd3f209d7eabbd187e7f0fec94a334dc2c79f7cf987251ea383993cfbb9b"
          ],
          "sign": 1,
          "start_exit_ms": 1745985600000
        },
        {
          "cohort_id": 13,
          "end_exit_ms": 1746129600000,
          "exit_groups": 3,
          "origin_keys": [
            "ad4f0095fed68a4b976ecb545563933251f5d099bc47915b8c67de1819455bb4",
            "b2e6e3962feac71b22eb2074e39a006cb98587f0725bf3109be8838ef695308a",
            "2a6edbf2a77ba9baccbbcad7d1ac4fa45547e5b199bfb7188e01fef99ea9f0f1",
            "8f8515e6532e5db846128d34e0acd9af583552e0154ecac8c07839a96cfa430b",
            "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77"
          ],
          "sign": -1,
          "start_exit_ms": 1746000000000
        },
        {
          "cohort_id": 14,
          "end_exit_ms": 1746230400000,
          "exit_groups": 1,
          "origin_keys": [
            "66117e742708f66294f9f95ffa8f4508569ca50a81ef0ff2ed50ae5b21508b7a"
          ],
          "sign": 1,
          "start_exit_ms": 1746230400000
        },
        {
          "cohort_id": 15,
          "end_exit_ms": 1746259200000,
          "exit_groups": 1,
          "origin_keys": [
            "3d58ce6d768f2b3a9f9ec4e78dbcbd10c17801962fd80435b1900d7a3a2458bb"
          ],
          "sign": -1,
          "start_exit_ms": 1746259200000
        },
        {
          "cohort_id": 16,
          "end_exit_ms": 1746273600000,
          "exit_groups": 1,
          "origin_keys": [
            "9f57fefae4501e2060405f7b470a13e8d60a6ebc9b825b311517e592dab05c18"
          ],
          "sign": 1,
          "start_exit_ms": 1746273600000
        },
        {
          "cohort_id": 17,
          "end_exit_ms": 1746331200000,
          "exit_groups": 1,
          "origin_keys": [
            "c798df5ca9bb60fe80cee47c9a36ff1dae5485b87024b19d401247092885b5d6"
          ],
          "sign": -1,
          "start_exit_ms": 1746331200000
        },
        {
          "cohort_id": 18,
          "end_exit_ms": 1746388800000,
          "exit_groups": 1,
          "origin_keys": [
            "443656f5dc9edca0ebcdea7effb81353900acbd8e3568596f3b41b175c57c721"
          ],
          "sign": 1,
          "start_exit_ms": 1746388800000
        },
        {
          "cohort_id": 19,
          "end_exit_ms": 1746532800000,
          "exit_groups": 2,
          "origin_keys": [
            "54b78a22139f7b6fc6d5a8c320c51466f5d1d0b370101c3b40221d9a51a8ecd5",
            "a414ff0468e67cedd06ac949d41cc4e377a5c3179a42c660ff0b8de3fdfc92f1",
            "437f79a339b9767f600ec378cd215060196d2354fc2a82b194def883ac5e5e94"
          ],
          "sign": -1,
          "start_exit_ms": 1746460800000
        },
        {
          "cohort_id": 20,
          "end_exit_ms": 1746950400000,
          "exit_groups": 3,
          "origin_keys": [
            "c22715040c25b6fa120e78b741bbd6aa34568c23f641a18898967fa9605765ed",
            "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
            "98d9d88ea5b38501a3f288f0b18d965f0ca2f3d4b971d011f6c4b3f696539466"
          ],
          "sign": 1,
          "start_exit_ms": 1746907200000
        },
        {
          "cohort_id": 21,
          "end_exit_ms": 1747497600000,
          "exit_groups": 6,
          "origin_keys": [
            "614f68e55b8871666bebe8710b0bf29a55c5a71bc88360169166f0b5cb0630ff",
            "7eafb7cae685ca0d1c66f35b17c30da5f58b571af67a9d38d545974f2953a2bb",
            "0699ffb8a34eae2af55c58494a1e85dffbf7b36aa8e425931ea7d037495506fa",
            "32d7355d1e8b6905432e9c1c04556f6b55d24b66827a68e18ece58943811bcc1",
            "994c40c0e2256268dde011f6f7d9fc1f972f2003cc15f350f2c2a2a82c7a439f",
            "dcae4bdf5d8ecbbd233ca0df467fee60f9a5d995fa76a2732c9190f4cd1860e6",
            "df5f82141ecb5edf4d9fa776242df2050725bc80a7fa0fbf15264585eb13aa2d",
            "1d528bb8ffde0df9b2af2eb4afa0b2ba2baa64b6feed2cd6c2728f06dfc039e7",
            "042d9748b7ad652fe6a1459db425be08a6a4ee9271a2ed26f7c2d7a8d49bfe0b",
            "a8e615a6faad7f5be3eaaaa1834f896ed1365beb77d5a8fcbdc70f12f3462b16",
            "88d458309b458d10306f7ea1e344f5b0f924c5741006087fbcf9ff96d73e9279",
            "ebe480142f6fde44c8bd630e98949d1b5928821c747eb9e776bd2b56e13f9800"
          ],
          "sign": -1,
          "start_exit_ms": 1747137600000
        },
        {
          "cohort_id": 22,
          "end_exit_ms": 1747512000000,
          "exit_groups": 1,
          "origin_keys": [
            "3d76dfec91f65235b6b9528f7172d0f4b81cf455cd99f0d21020be81763780c2"
          ],
          "sign": 1,
          "start_exit_ms": 1747512000000
        },
        {
          "cohort_id": 23,
          "end_exit_ms": 1747627200000,
          "exit_groups": 2,
          "origin_keys": [
            "6edb54a38352879b003aa03b19b60af41cfea5ed2fe58d45d32c36ff9b8036fb",
            "e6329bba085fc7a05bdfd0f60732a72382fc45a58d44d58671fc7a2c5a41d78d",
            "3b45e5a08e5b46c824e67cffc67750543f72613e1da6b5d08cb2d52d95a3f4dd"
          ],
          "sign": -1,
          "start_exit_ms": 1747598400000
        },
        {
          "cohort_id": 24,
          "end_exit_ms": 1747728000000,
          "exit_groups": 1,
          "origin_keys": [
            "58caa5c0de31b1d116e216d8f4e878d6050afe63914f6b025e6c09f3f9e2bd3e"
          ],
          "sign": 1,
          "start_exit_ms": 1747728000000
        },
        {
          "cohort_id": 25,
          "end_exit_ms": 1747742400000,
          "exit_groups": 1,
          "origin_keys": [
            "1c033c7e7de80f564916f3b313f06fa64d43e200b4bd4f00c6f63fc63f41cd41"
          ],
          "sign": -1,
          "start_exit_ms": 1747742400000
        },
        {
          "cohort_id": 26,
          "end_exit_ms": 1748131200000,
          "exit_groups": 4,
          "origin_keys": [
            "2f8ad94eff3a7f569bc6c03875ae0c0ede863e07d0230d8b551f42d8a74a8df9",
            "f2155391aa7764c59c85a1774bf8ec2783fdf8da4a5fdf1f7a3e77e7e43eb21f",
            "a10581de8ca6e0a3a8d39c7919e138b74e98b8a995d5c1d71b10bc23272e623e",
            "f4d6def625f4d88d6adbcbcc6c20c2ef2ece38e91cd8c40a8e26b2655f74aadf"
          ],
          "sign": 1,
          "start_exit_ms": 1747900800000
        },
        {
          "cohort_id": 27,
          "end_exit_ms": 1748448000000,
          "exit_groups": 5,
          "origin_keys": [
            "b79a83562bbb1fcf661f5da109bec9523bc2fbe18a6cc2ee2b9045b078870920",
            "6d3370d48c8dd5361e302db82f2faab51beb8134d32e053764712ba77b9847f2",
            "8d1e9fb1a87540daedeec63a1bd37862547398d79b72b7411f8d46b027e1cea3",
            "23c94f724bf48a6e16603c297353285d71192d1cadfa92536f6299787da312dd",
            "025bb75df735c790d62747f3e13e8ca2ecf6e25cff47e05c2325121f4400cb62",
            "33f57ce14343f17bddeb7418ac566edd267076603ae156bdc4baf6823225f58e"
          ],
          "sign": -1,
          "start_exit_ms": 1748160000000
        },
        {
          "cohort_id": 28,
          "end_exit_ms": 1748534400000,
          "exit_groups": 1,
          "origin_keys": [
            "0a331de10b2976732100714d118f7ab16568669025031ce21fd3ed2ff51ce773",
            "2309869ab033df7389c783f5f2491430e47c77c04811e44332342a27cf828f14"
          ],
          "sign": 1,
          "start_exit_ms": 1748534400000
        },
        {
          "cohort_id": 29,
          "end_exit_ms": 1750161600000,
          "exit_groups": 5,
          "origin_keys": [
            "aa3e034323ec63827bf0018347ef7d0a316702d5a0617020d04e8c858a1e2a8a",
            "fb48642108224d3fd03fb697ee7a20785f5171d1bd7cee02e2a5f31071d76a3d",
            "dba9bbf39a23532d0a92a6380648a5a82bb86abaaa2a1533200bea613985c5f9",
            "024114bc463b975bb2471e67185237d7bee62108dc9b572958bf60110d707c7f",
            "edee33a09ec6eb780a2ad5c573cf33227791b558457c97d5e2045ab17f3d554c",
            "346f7341f2bf3ca2b223cbb6c08980902fe7f1f65b9318434a2f735617f90af0"
          ],
          "sign": -1,
          "start_exit_ms": 1748577600000
        },
        {
          "cohort_id": 30,
          "end_exit_ms": 1750507200000,
          "exit_groups": 2,
          "origin_keys": [
            "87c161e5a0178ff7eca2cffd9a8d37631304339b34d0b8783cf85c19f8d4fff5",
            "fe8e0737e3379d2cef8489483a55b8b1e702cce913035dd0ea89742db9df1314"
          ],
          "sign": 1,
          "start_exit_ms": 1750276800000
        },
        {
          "cohort_id": 31,
          "end_exit_ms": 1750752000000,
          "exit_groups": 1,
          "origin_keys": [
            "39539c214fa857f57942fdecb68ca04e4d9b1018d4cbf98a027b0bce364fd025"
          ],
          "sign": -1,
          "start_exit_ms": 1750752000000
        },
        {
          "cohort_id": 32,
          "end_exit_ms": 1751371200000,
          "exit_groups": 2,
          "origin_keys": [
            "f8b2e6dbf975e01a4c24cd97e823cf2d2682b8c4ca2e60fd6ad9d67412e1f08f",
            "19b7e6cbf30ad251a04905bcbe18c261b3c3bc82fa95963ecd9c4c95ddfac24b"
          ],
          "sign": 1,
          "start_exit_ms": 1751284800000
        },
        {
          "cohort_id": 33,
          "end_exit_ms": 1751990400000,
          "exit_groups": 6,
          "origin_keys": [
            "ea90f21d84b730c28a1773be9ee1628a4daf2163a42ab9d96c480e4de0f0193e",
            "5dc1f4defbfbc3fa4dc1acb116712938b0a3552d6a89b263aaad65507c8dbd26",
            "64fee382be25139512d408919e8250d563f51d560dd3b813196fdd208868c8d1",
            "96ed746cc89114bc96aac5280111eea20edd9a85e84ab8419892e4e8f9fb98cd",
            "ccd2a420e644f4be3c60d0b80e6328f0b025f3b9e7258bcba646be88e60ca47f",
            "96a7eaa94ec10a0dc4fed1a17b04fca7a0d6ce97a652a93ce32f852597731eca",
            "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569",
            "a87ac993ed55790f6527004a16cd082a003328436ad856153d97b67f81c32b3c",
            "1db87f8de43b59b15f878d313cfc72243fc58147aba4e2a1d092d175f11a6420"
          ],
          "sign": -1,
          "start_exit_ms": 1751385600000
        },
        {
          "cohort_id": 34,
          "end_exit_ms": 1752537600000,
          "exit_groups": 5,
          "origin_keys": [
            "5670edf0d14be75b650617df11623e0c264c928e01761685247611300e2c2b4e",
            "d4587f56aa58595f4a5c34cb1c8d91539ec6b99ae14be7a6f3791416a8d508a8",
            "7580befe0c0c1ebfe54b91a1135cd1c53d3864646f191c09a6825a74bb37bb9a",
            "0849bb8f17c8313ebc2ae91114edfd46c6f62986e96607f92da1776c575d6ea3",
            "588117c7ecbadbf1bd2d05794cc3719559963cbeae1c93b38b0a6ed478c372c8",
            "6c79f7624a88231c465b70a25a0548f526f4c38ee7bf9fd10beeaf91f078f348",
            "4135d00ba44ebc5cf362711a4abee2e6d01c478113057178d7b0ea1f56c7e916"
          ],
          "sign": 1,
          "start_exit_ms": 1752163200000
        },
        {
          "cohort_id": 35,
          "end_exit_ms": 1752854400000,
          "exit_groups": 3,
          "origin_keys": [
            "6bcecc02427a0ab87800a8061d36d4d0c8fb501f79b12637a45b21655b0f9221",
            "c4b037954cd3a617621503a5d77862a4938eef8c6a6327ed5330b232b49ed2c6",
            "1f62363ddf4605200913f11e62d56c828b95351635929f111bd69433e45bade4",
            "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530"
          ],
          "sign": -1,
          "start_exit_ms": 1752552000000
        },
        {
          "cohort_id": 36,
          "end_exit_ms": 1752969600000,
          "exit_groups": 4,
          "origin_keys": [
            "47dd745683e2b505200b6d7e1fc1ede9415e6a8d5b5aafb1c19767cb1332b910",
            "ad79f7e334f3d55db655513fa0d0b4c8b86d80c941edf24bfcbb43fac93ed175",
            "52b2c7f77188ca8227f75c8db34792dd70799a9ad5ff7cd3319389ceec23568a",
            "0d2b35ab633f4d557b8498f19d4a4520d5b9a0efb7ba02443b9ae02d1091d3e6"
          ],
          "sign": 1,
          "start_exit_ms": 1752868800000
        },
        {
          "cohort_id": 37,
          "end_exit_ms": 1753056000000,
          "exit_groups": 1,
          "origin_keys": [
            "d88d6da82807ed73485910acdb84b99de13e8b250836cce7b9e4604a05804a5e"
          ],
          "sign": -1,
          "start_exit_ms": 1753056000000
        },
        {
          "cohort_id": 38,
          "end_exit_ms": 1753171200000,
          "exit_groups": 2,
          "origin_keys": [
            "130a5d5d13a47060b238ee0b3ea34039c17b4d62c365ed662db54151cb725994",
            "a9a3e8365fcc187a032b988186095539cef032de8177ce8cd707794f13c41178"
          ],
          "sign": 1,
          "start_exit_ms": 1753128000000
        },
        {
          "cohort_id": 39,
          "end_exit_ms": 1753416000000,
          "exit_groups": 5,
          "origin_keys": [
            "e8c732e46d0580a95e52293b59277c9ba520fdc091bf689bd5ae2e21d33050dd",
            "3cd227554c6bd53fad0d12e860efe081bd24b05cccf9e1d794a182c8c4dcad6e",
            "8a5d77ec50be4dde6278d0637ccd74d2208b8fdb80e2fe1aafd67d12055bbe9b",
            "7af2a28e7e974d6aea365bca7852e315a945200b974024e626335ee7577f02d7",
            "81f03a46613732f84a14cc6faf711252ca5de24205bf3fca9360c100254dde55"
          ],
          "sign": -1,
          "start_exit_ms": 1753286400000
        },
        {
          "cohort_id": 40,
          "end_exit_ms": 1753776000000,
          "exit_groups": 2,
          "origin_keys": [
            "10a7b67bfcf5fdef4e36f5eea44c22d0c15966fe732ee607db46507ea2c37308",
            "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1",
            "63792578bc411889e22ef91262a5824732a8d1ae57a0ded1ca745836604b9ca0",
            "557b95fc65cbf0a8035281ddc5e29e72cd7bc95790782d8b7411eecf313ca04e"
          ],
          "sign": 1,
          "start_exit_ms": 1753718400000
        },
        {
          "cohort_id": 41,
          "end_exit_ms": 1754035200000,
          "exit_groups": 3,
          "origin_keys": [
            "72b8b528d33ac98c9e17345c6de9613fe8d6014697570c41ea668548c0f2e6ae",
            "da7ef6e9025099319f5576f5f52136b82c6f1ec5029bcf9e25045c2badadd7fd",
            "71902b786b8aa54c87f1430de51e32e03473b5c94413248f360662735a04ef94",
            "eacc20084995a3ab4a7da3fa3ca8dbab480710b7067c84bc8292646e35c78df3"
          ],
          "sign": -1,
          "start_exit_ms": 1753804800000
        },
        {
          "cohort_id": 42,
          "end_exit_ms": 1754755200000,
          "exit_groups": 1,
          "origin_keys": [
            "b39417684ba0dd296a071fcc13fe5216b1b6844235c84549dc686fccb4673de2"
          ],
          "sign": 1,
          "start_exit_ms": 1754755200000
        },
        {
          "cohort_id": 43,
          "end_exit_ms": 1755187200000,
          "exit_groups": 2,
          "origin_keys": [
            "426aaff0097e98b6f0e7cc599671e126621e79f81c2d9456d7d68d4dc6ce0e50",
            "86080a597e0bc1116384e954acd6b0c32041e73eec3b5942be80a252744afa0d",
            "97ac73b0f3529903ed9ea201036b3a9a435d9f8242a6960923498385c043fde6",
            "d8c4f5ef31ad715ad9c25e6dbcb30b68461f2f90690cb945d7860890f229bfc0",
            "fa2227abd88b8c794620d6219457b183c6b3c8053e46cdabdf4ff044408ae2e8"
          ],
          "sign": -1,
          "start_exit_ms": 1754812800000
        },
        {
          "cohort_id": 44,
          "end_exit_ms": 1755201600000,
          "exit_groups": 1,
          "origin_keys": [
            "a6dd07b321410fe650cca40b7fba4a0319308127876915148c36d7d211015c8d"
          ],
          "sign": 1,
          "start_exit_ms": 1755201600000
        },
        {
          "cohort_id": 45,
          "end_exit_ms": 1755273600000,
          "exit_groups": 1,
          "origin_keys": [
            "23afcd4e4c4688f46d0a8905fb2ed0da9124e917c61c1c8310d2bbd3f05a9253"
          ],
          "sign": -1,
          "start_exit_ms": 1755273600000
        },
        {
          "cohort_id": 46,
          "end_exit_ms": 1755374400000,
          "exit_groups": 1,
          "origin_keys": [
            "26f83f96f1a03e42ad86c962382630587b92091985220c144f5c7f898fa19067"
          ],
          "sign": 1,
          "start_exit_ms": 1755374400000
        },
        {
          "cohort_id": 47,
          "end_exit_ms": 1755489600000,
          "exit_groups": 2,
          "origin_keys": [
            "d982dd8e49b3f106e644332a4059d1194d1d35aee6d350030b4372357aea69b9",
            "0d6aa06212cbc737dcc220fe2a05a8b0915ef9cbbaeeff4122e1226468ce37f9",
            "8192c69c9ec4091daed78995d26184cd0f43e977592742eb3f1fb55906840011"
          ],
          "sign": -1,
          "start_exit_ms": 1755403200000
        },
        {
          "cohort_id": 48,
          "end_exit_ms": 1756022400000,
          "exit_groups": 3,
          "origin_keys": [
            "d42bc424b418ebd385e34b86cfaafa6df637e49e5d03982b8bf2a22f33c6c63a",
            "23bdd736b6f855d35443df00de3082fc216d437a3f7b5535adb2b3a3965c802a",
            "2a31409627d7f1beff834be00cd1d4b4f8f24cebba69f13c1e941d9ef6a9c809"
          ],
          "sign": 1,
          "start_exit_ms": 1755576000000
        },
        {
          "cohort_id": 49,
          "end_exit_ms": 1756411200000,
          "exit_groups": 2,
          "origin_keys": [
            "d1b4cfd5ebf80e5ed19f62d16eda0239aaa594558936a7e9760b06bd1999ac97",
            "2adc0b6550a8692d06f7907f2283b556c58dbb2f52425e8fefaf9d9a861db92e",
            "ea31de60b9c578b294c333209ac5925bedfc3aab8bedc15564ff24f696aba6af"
          ],
          "sign": -1,
          "start_exit_ms": 1756108800000
        },
        {
          "cohort_id": 50,
          "end_exit_ms": 1756483200000,
          "exit_groups": 1,
          "origin_keys": [
            "c46a24ae2079a3556a5634f46ea9cc39fa760e6f78bcdc8b8e93307851dbe34f"
          ],
          "sign": 1,
          "start_exit_ms": 1756483200000
        },
        {
          "cohort_id": 51,
          "end_exit_ms": 1757188800000,
          "exit_groups": 3,
          "origin_keys": [
            "428905cd69a7a3e76e9dfd3255579237ec52be6122201a44ace33881e1ee47c8",
            "6b549f02e4f064bbf7f4c40e4f51f94b9580167a0e1972608ddacf43c0ed34ac",
            "57df2b8e7677d5ef175fe1e3bed5da1b538e591195809d42e04946f07d5a9955"
          ],
          "sign": -1,
          "start_exit_ms": 1756684800000
        },
        {
          "cohort_id": 52,
          "end_exit_ms": 1757203200000,
          "exit_groups": 1,
          "origin_keys": [
            "62a1ecd9a5055c7fafa15edff164e12cc643c6d1dacc2dba19cc9ff6f76a0192"
          ],
          "sign": 1,
          "start_exit_ms": 1757203200000
        },
        {
          "cohort_id": 53,
          "end_exit_ms": 1757376000000,
          "exit_groups": 1,
          "origin_keys": [
            "c6127a03ef0009f3f300690bc57de1882c9f9c2a234e6211a1955769f77408b0"
          ],
          "sign": -1,
          "start_exit_ms": 1757376000000
        },
        {
          "cohort_id": 54,
          "end_exit_ms": 1757808000000,
          "exit_groups": 3,
          "origin_keys": [
            "1c68a9cc14bdd4d08a9787b78b28f26e9ac4ebe70a07e7108f38487895199cf3",
            "eb9da654bf3fdb218cb78c6eab455ba63d5919565b52ce5ed54cba88c489db93",
            "f160d012b4eb926c79383261efa36103180162299f3ef7802efe75e8f5161450"
          ],
          "sign": 1,
          "start_exit_ms": 1757563200000
        },
        {
          "cohort_id": 55,
          "end_exit_ms": 1758052800000,
          "exit_groups": 3,
          "origin_keys": [
            "9e87739b9533756c1f3a5cba53e0ec0310b87524ee622d82057c4b3d0ae11e3a",
            "6183540eaf7ee3778e78b8f4d8f8cbc7736977c475a71761e053c24a7e44e283",
            "5b91366303f982be376a09ad7ec60f28c97722348abadb55e4614180885d8494",
            "c6309e88f62a6732468866d3fbf8b8b99fd3bcfa67c46b5ad8d5f497d650274f"
          ],
          "sign": -1,
          "start_exit_ms": 1757822400000
        },
        {
          "cohort_id": 56,
          "end_exit_ms": 1758283200000,
          "exit_groups": 4,
          "origin_keys": [
            "446c24a7ab0118e270580f92355def0e54c1f805a46924eba8477af8c43d6db3",
            "64961492ab5f443e90a8c9d564c918cfdce4ee3c606ef665241c4f0c2a96f75e",
            "319461a1067ffe81b0a9b34ec4e5678ae9de6a09dc2f66ef17cc4c4a09a2c730",
            "5b8217ea755075291a5abafee4e933350a5545b7276cab5507cff0aa515ad7b3",
            "084205c0d23f84547fa462ce8f9949eb7525299fea73afbdbb958d422d815579"
          ],
          "sign": 1,
          "start_exit_ms": 1758139200000
        },
        {
          "cohort_id": 57,
          "end_exit_ms": 1759723200000,
          "exit_groups": 5,
          "origin_keys": [
            "2567100622d709b4dadce9bc9984c5f759dd2871070bde93c87592cddcef3b69",
            "2cb7e5e850046b8607fd9b0cb9c7f0f2aeb120b13a6a1d50f764438965a23882",
            "554c51a2434a2ee43b490764a07e182d925621dbdb5a87d364e2d6b925a69c4e",
            "7167ad5b637d274e19469116dd430cf47e3fa43d9259e8d766a1b58d5247e381",
            "b281893de94140686bcbd995ee033670ee9076750fd90c016395f78e85a96224",
            "cfede36f952bb1cbafdc54a70967713c8d8900f29aebfedaa2683dac8a33a86e"
          ],
          "sign": -1,
          "start_exit_ms": 1758312000000
        },
        {
          "cohort_id": 58,
          "end_exit_ms": 1759838400000,
          "exit_groups": 3,
          "origin_keys": [
            "35ed91621849376419f6a0416043957568e31d43b58965d228e0a880574e2118",
            "dc95dba52f37e16c5de4ccd174eaa3cc6e3ce42cdd52d1f6e2841c740a29209e",
            "673673e4647d7f781ef34e86f6ab6f68b4e56d561629511e3dff804e2fc671b9"
          ],
          "sign": 1,
          "start_exit_ms": 1759809600000
        },
        {
          "cohort_id": 59,
          "end_exit_ms": 1762977600000,
          "exit_groups": 10,
          "origin_keys": [
            "6b15d4c81966c958f5e997c9caf2044debb3fddad3fd1969d5b022cf9f8e5b66",
            "6d7eb08e9607b2be435cacced40b81d9855211d28884d5b533cb61f20bd74fd6",
            "681c4acc892374e7bcd61098f01cc55c78648364b0a80492cfad92ce115adb96",
            "d346d8f7ef310a5146f7cbd5edb0b096875d404f38193565e98f1903694dfaa6",
            "838b7a14075d36308a1a5ab625659a67f9be7cf6c23d20b03f869a40305a56a3",
            "5e58f9cb119a8b70f2c4bb512362e1b7e01abc3d777b030a55dc34eff226844a",
            "f888e7d1e2866d29d3cd9fead0ba59a9c640b2a0a344b1a07c88e34cab792734",
            "71904ade42290aeffcefe5a884c06e6e43bb3f316316ca6025b4318cbe94c6d8",
            "8eaf489299cdec5d86e09ce744d53479600da0ce04381f2d640e33c1fc094db5",
            "9a17a25717bcb7603fddca5b6b6f1092fe9f037d524c36d2a920f5c502b3190a",
            "f04b345b13db9aef69e08301403563cd13bee3941d6c62e05f591694a5764ad7"
          ],
          "sign": -1,
          "start_exit_ms": 1759852800000
        },
        {
          "cohort_id": 60,
          "end_exit_ms": 1764316800000,
          "exit_groups": 1,
          "origin_keys": [
            "c2f731fadf077fedfbfdf44b7e5a0fb93953f2b0866afa1175c6f9775d38b1a2"
          ],
          "sign": 1,
          "start_exit_ms": 1764316800000
        },
        {
          "cohort_id": 61,
          "end_exit_ms": 1764446400000,
          "exit_groups": 2,
          "origin_keys": [
            "1b899f0e0e9a043529d9ff3ea24e4737f7ecd88b972cdccc07476aef05e5e951",
            "f3a7f3359ee694f3f2ec72d0883e89ff8244c00ad0ba3ab05e8a8fdcfcff5a7c"
          ],
          "sign": -1,
          "start_exit_ms": 1764360000000
        },
        {
          "cohort_id": 62,
          "end_exit_ms": 1764518400000,
          "exit_groups": 1,
          "origin_keys": [
            "0bdca7d41379168b140b2e66004f877e7ed16f1ec94ad27a829709e01d88dcfd"
          ],
          "sign": 1,
          "start_exit_ms": 1764518400000
        },
        {
          "cohort_id": 63,
          "end_exit_ms": 1764936000000,
          "exit_groups": 3,
          "origin_keys": [
            "096bc697ee57acd04f69b2bdafa69304be268939fa6fc7ce3e7d4a153993239d",
            "50ef6567fbd7df3446b1349d46cc3248422d6ac0b97efc4a25c0e41078dd9fa2",
            "8f2deb5337fb114b9d57c7ffc9866b6a3147b0b3736a493d25f9408a2952de70",
            "96d5be021062d7510e93873bbad3117337da5ca3fc3a5d22dfde06c7a45223c4"
          ],
          "sign": -1,
          "start_exit_ms": 1764547200000
        },
        {
          "cohort_id": 64,
          "end_exit_ms": 1765224000000,
          "exit_groups": 1,
          "origin_keys": [
            "0bb441638757d83417e5d34843eb3662cf34bc63b082e0543c9d4e6ea4c281a2"
          ],
          "sign": 1,
          "start_exit_ms": 1765224000000
        },
        {
          "cohort_id": 65,
          "end_exit_ms": 1766534400000,
          "exit_groups": 5,
          "origin_keys": [
            "06f11cb99f29537c27c1e17dd06ab6fa36592086e512f419221fab219e69025c",
            "8db5e99d7b412ef451f5f40543f15fa63a61ce198466589c3f312ac65c581f6f",
            "98415b5f82bd3af2ba758b66c93c9918aecfd9d3b1cca6f1c99f5fd6b1981665",
            "98e92a785ee2e630812749980e5a0265365fb37533cd38ac8932dc77759b3137",
            "a97a1ea6fdb491a48099adef01ad75dd6269a7cf73b55ef7ec9f7155b6a56862",
            "71ad5943e5ee593a23085130ebed82c16fe5e4084605413d3843385d3ceec257",
            "87a932ea0171d6110434a232dfd49105d4d3f1260f570d604c5ae0bbec3f9d70",
            "a56600ae8b8d496db0b3245e50dbbde722769f7fb538e778fc707eb4974a8006",
            "b8f4efc9ce43a92fe22dcb9ccfd9832f3d5b18e624a147236e626f2f61a9b930",
            "7592b8b06b52feeb652ccc01853e62faecdb8115c0564457f76aeb2254d34000"
          ],
          "sign": -1,
          "start_exit_ms": 1765339200000
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 74.8239282614719,
          "BCH-USDT": -622.9305391407165,
          "BTC-USDT": 44.19436715785122,
          "ETH-USDT": 3727.5851271716006,
          "HYPE-USDT": 3141.6525623561015,
          "LINK-USDT": 2394.0726573718,
          "SOL-USDT": -874.6556615019458
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 6419.543212695689,
          "BCH-USDT": 5412.051239652212,
          "BTC-USDT": 3477.296832554346,
          "ETH-USDT": 8657.6929859195,
          "HYPE-USDT": 9801.53226047399,
          "LINK-USDT": 6720.438744906569,
          "SOL-USDT": 5680.077493415983
        },
        "total_positive_trade_profit_bps": 46168.63276961829,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.21229851681733106,
        "winner_T": 81,
        "top_decile_winner_T": 9,
        "top_decile_winners_share": 0.42260670789051974,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": 301.5794705444807,
          "2025-03": 3039.562565894135,
          "2025-04": 2283.1314480847927,
          "2025-05": 3598.868406104278,
          "2025-06": -591.0336503260327,
          "2025-07": 7179.976422294548,
          "2025-08": -191.8873369541304,
          "2025-09": 605.9932233106437,
          "2025-10": -2435.597814257083,
          "2025-11": -730.2498393716005,
          "2025-12": -5175.6004536478695
        },
        "top_positive_month_share": 0.4221253066040359
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 1,
          "net_trade_sum_bps": 1062.6028859344572
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 1,
          "net_trade_sum_bps": -579.3200423015144
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": 1680.3877112297146
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 2,
          "net_trade_sum_bps": 779.8888881178773
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 6,
          "net_trade_sum_bps": 579.285966546543
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 6,
          "net_trade_sum_bps": 468.5167582084153
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 7,
          "net_trade_sum_bps": 3307.0560455305554
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 14,
          "net_trade_sum_bps": -1087.1701088472046
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 6,
          "net_trade_sum_bps": 4808.170503176422
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 15,
          "net_trade_sum_bps": -3325.9101505891254
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 8,
          "net_trade_sum_bps": 3594.5159864285515
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 9,
          "net_trade_sum_bps": -1883.1791797185433
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 1,
          "net_trade_sum_bps": -366.531824934293
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 2,
          "net_trade_sum_bps": -344.6236840662
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 3,
          "net_trade_sum_bps": 221.2239008236495
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 2,
          "net_trade_sum_bps": -101.1020421491892
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 7,
          "net_trade_sum_bps": -543.8002154283296
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 9,
          "net_trade_sum_bps": 4754.208666423764
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 9,
          "net_trade_sum_bps": 4576.666130382224
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 8,
          "net_trade_sum_bps": -2055.77426014282
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 8,
          "net_trade_sum_bps": 250.09211737131767
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 2,
          "net_trade_sum_bps": -212.65995025226442
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": 408.10482506887473
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 5,
          "net_trade_sum_bps": -97.77309917158306
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 4,
          "net_trade_sum_bps": -90.97512891076587
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 4,
          "net_trade_sum_bps": -578.3437006055626
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 5,
          "net_trade_sum_bps": 3039.435402516072
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 11,
          "net_trade_sum_bps": -996.0881399661545
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 1,
          "net_trade_sum_bps": -859.0103386337111
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 1,
          "net_trade_sum_bps": -359.57654723127064
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 10,
          "net_trade_sum_bps": -1552.8369791004898
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 4,
          "net_trade_sum_bps": -919.0427590078841
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 1,
          "net_trade_sum_bps": -139.76988474602933
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 4,
          "net_trade_sum_bps": -194.62148354300928
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 4,
          "net_trade_sum_bps": -1373.2093762526397
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 9,
          "net_trade_sum_bps": -3328.709328248181
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 2,
          "net_trade_sum_bps": -473.68174914704906
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": 1,
          "start_exit_ms": 1738382400000,
          "end_exit_ms": 1738382400000,
          "exit_groups": 1,
          "origin_keys": [
            "979b207a0cba154c4e56588b522459fa2902ad9ee30a61a24690b47f38d357e6"
          ]
        },
        {
          "cohort_id": 1,
          "sign": -1,
          "start_exit_ms": 1738857600000,
          "end_exit_ms": 1741320000000,
          "exit_groups": 3,
          "origin_keys": [
            "75bc1657579c38bd14d06fb08329382d285734e221669423c07436b9168745f3",
            "e20ec6b5b1d64710658dccc8218f65bec8ec99a40af5f15cf38a37a4902efd57",
            "3ba2fc0bf476825ddf705c60441b6695aa84f0134bde8a0de6895f244bbe5a6e"
          ]
        },
        {
          "cohort_id": 2,
          "sign": 1,
          "start_exit_ms": 1741406400000,
          "end_exit_ms": 1742990400000,
          "exit_groups": 5,
          "origin_keys": [
            "5d6e5b2ff3cf13258185ce91cb7c4e919d939674c0a8eb3b43bee07fbb02deb6",
            "4d5ff1901411d6d49cbce69c93cbc35f4d7bb8f5a9c9a77c44ee660c68c28e32",
            "c1127e43093e62cbe8bc16e1487a4dbf17ce66211259d19a6e5ed93a56095320",
            "1653ba4f1d26dff2261e9c362f004f8c74c8b766ce03e28276216c4ccab687dc",
            "5a528e3ccae612a1a58eb63f60fb13cc6f88990b4cdc88471dcb9c3b4631c521",
            "e8a6e1ffe7c7d82419d74876b6a6c46f0e78bad36cdd9a091afc4a89323dbc35"
          ]
        },
        {
          "cohort_id": 3,
          "sign": -1,
          "start_exit_ms": 1743004800000,
          "end_exit_ms": 1744876800000,
          "exit_groups": 4,
          "origin_keys": [
            "196c03d2731521f1e86e4d797f11094e616708a19020dce4919dacc640f21060",
            "1708bab61045d1eeaa2c350e2e7851851f62a23daf078ff8998df30b18ed7d14",
            "711b1318d15c09603ef57558aa7a1f321f727f1dff1c4d08c6e41a755e5d3c3a",
            "c854aa8fd523fc736ca1f0b9acc5783788dc70558b58da7d91737d68ee88eec4"
          ]
        },
        {
          "cohort_id": 4,
          "sign": 1,
          "start_exit_ms": 1744992000000,
          "end_exit_ms": 1745006400000,
          "exit_groups": 2,
          "origin_keys": [
            "11ff48ed506f83b9a9fa9267381bd2d96e7de9404c20349e175ed0db38927ae8",
            "9c1cc06b28d04eb6b93b11b379fff3ea7948f56ac55794d9003e490d48691ebb",
            "ab487bcd177eb3107deb68c125a05af61af7384a70cf079a682c2c129adc581f",
            "2061fca492db51368428be5f97a2337099a971b1842d4f29c72fb5ae77d1aa25"
          ]
        },
        {
          "cohort_id": 5,
          "sign": -1,
          "start_exit_ms": 1745150400000,
          "end_exit_ms": 1745150400000,
          "exit_groups": 1,
          "origin_keys": [
            "6a17e80b6f6a73786f18faa40f8e3a691fe1f65bc2214d9ddccb1cacba42f3a1"
          ]
        },
        {
          "cohort_id": 6,
          "sign": 1,
          "start_exit_ms": 1745280000000,
          "end_exit_ms": 1745539200000,
          "exit_groups": 5,
          "origin_keys": [
            "54e6c4939b93069ee71a073f9a5a7b9ee5f32e6eb14fbf1ef64e5b05c56eab0f",
            "e1f389c1a4c16aa5bae8730c6d710e4e99e1f40b7a1278be9fffc2fc593c5a55",
            "3ad0f0c17337ad73dfebd624f47c0cf42535a2ecf32a0c9e0c23efbda8935e30",
            "15f69d81e2bb95a5a72b262f18e8222757758b3138990c1d01b999cdc4da3c09",
            "0f9e0ad9a9c424f355d0fdc40b7b9f452b36a382a8c11e5d93e8fc8cb8812f7b"
          ]
        },
        {
          "cohort_id": 7,
          "sign": -1,
          "start_exit_ms": 1745668800000,
          "end_exit_ms": 1745668800000,
          "exit_groups": 1,
          "origin_keys": [
            "4504481ef8c1c67ae04a5af5a8063e7ca5996ffb14cc64793242056b597b31cb"
          ]
        },
        {
          "cohort_id": 8,
          "sign": 1,
          "start_exit_ms": 1745683200000,
          "end_exit_ms": 1745683200000,
          "exit_groups": 1,
          "origin_keys": [
            "ea78a8e6612680ae67dc8d6a43ac87831fd7402265ddde47cb87cae704a34f2a"
          ]
        },
        {
          "cohort_id": 9,
          "sign": -1,
          "start_exit_ms": 1745856000000,
          "end_exit_ms": 1745956800000,
          "exit_groups": 2,
          "origin_keys": [
            "136c2d685362c73f9c8faac1906b1f0f6b39c96937143c502f1dafa8a17f4635",
            "618293610019999e13d4089b009d7d4f7243872a4800ba1651afc4ef5d78ae32",
            "ef80ea0ab964ded3cdbd87ba38a28fa6eb5edb7d734c2b5aa4c4f62794837d20"
          ]
        },
        {
          "cohort_id": 10,
          "sign": 1,
          "start_exit_ms": 1745985600000,
          "end_exit_ms": 1745985600000,
          "exit_groups": 1,
          "origin_keys": [
            "45f7cd3f209d7eabbd187e7f0fec94a334dc2c79f7cf987251ea383993cfbb9b"
          ]
        },
        {
          "cohort_id": 11,
          "sign": -1,
          "start_exit_ms": 1746000000000,
          "end_exit_ms": 1746129600000,
          "exit_groups": 3,
          "origin_keys": [
            "ad4f0095fed68a4b976ecb545563933251f5d099bc47915b8c67de1819455bb4",
            "b2e6e3962feac71b22eb2074e39a006cb98587f0725bf3109be8838ef695308a",
            "2a6edbf2a77ba9baccbbcad7d1ac4fa45547e5b199bfb7188e01fef99ea9f0f1",
            "8f8515e6532e5db846128d34e0acd9af583552e0154ecac8c07839a96cfa430b",
            "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77"
          ]
        },
        {
          "cohort_id": 12,
          "sign": 1,
          "start_exit_ms": 1746230400000,
          "end_exit_ms": 1746244800000,
          "exit_groups": 2,
          "origin_keys": [
            "66117e742708f66294f9f95ffa8f4508569ca50a81ef0ff2ed50ae5b21508b7a",
            "9f57fefae4501e2060405f7b470a13e8d60a6ebc9b825b311517e592dab05c18"
          ]
        },
        {
          "cohort_id": 13,
          "sign": -1,
          "start_exit_ms": 1746259200000,
          "end_exit_ms": 1746331200000,
          "exit_groups": 2,
          "origin_keys": [
            "3d58ce6d768f2b3a9f9ec4e78dbcbd10c17801962fd80435b1900d7a3a2458bb",
            "c798df5ca9bb60fe80cee47c9a36ff1dae5485b87024b19d401247092885b5d6"
          ]
        },
        {
          "cohort_id": 14,
          "sign": 1,
          "start_exit_ms": 1746388800000,
          "end_exit_ms": 1746388800000,
          "exit_groups": 1,
          "origin_keys": [
            "443656f5dc9edca0ebcdea7effb81353900acbd8e3568596f3b41b175c57c721"
          ]
        },
        {
          "cohort_id": 15,
          "sign": -1,
          "start_exit_ms": 1746460800000,
          "end_exit_ms": 1746532800000,
          "exit_groups": 2,
          "origin_keys": [
            "54b78a22139f7b6fc6d5a8c320c51466f5d1d0b370101c3b40221d9a51a8ecd5",
            "a414ff0468e67cedd06ac949d41cc4e377a5c3179a42c660ff0b8de3fdfc92f1",
            "437f79a339b9767f600ec378cd215060196d2354fc2a82b194def883ac5e5e94"
          ]
        },
        {
          "cohort_id": 16,
          "sign": 1,
          "start_exit_ms": 1746907200000,
          "end_exit_ms": 1746950400000,
          "exit_groups": 3,
          "origin_keys": [
            "c22715040c25b6fa120e78b741bbd6aa34568c23f641a18898967fa9605765ed",
            "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
            "98d9d88ea5b38501a3f288f0b18d965f0ca2f3d4b971d011f6c4b3f696539466"
          ]
        },
        {
          "cohort_id": 17,
          "sign": -1,
          "start_exit_ms": 1747137600000,
          "end_exit_ms": 1747483200000,
          "exit_groups": 5,
          "origin_keys": [
            "614f68e55b8871666bebe8710b0bf29a55c5a71bc88360169166f0b5cb0630ff",
            "7eafb7cae685ca0d1c66f35b17c30da5f58b571af67a9d38d545974f2953a2bb",
            "0699ffb8a34eae2af55c58494a1e85dffbf7b36aa8e425931ea7d037495506fa",
            "32d7355d1e8b6905432e9c1c04556f6b55d24b66827a68e18ece58943811bcc1",
            "994c40c0e2256268dde011f6f7d9fc1f972f2003cc15f350f2c2a2a82c7a439f",
            "dcae4bdf5d8ecbbd233ca0df467fee60f9a5d995fa76a2732c9190f4cd1860e6",
            "df5f82141ecb5edf4d9fa776242df2050725bc80a7fa0fbf15264585eb13aa2d",
            "1d528bb8ffde0df9b2af2eb4afa0b2ba2baa64b6feed2cd6c2728f06dfc039e7",
            "042d9748b7ad652fe6a1459db425be08a6a4ee9271a2ed26f7c2d7a8d49bfe0b",
            "a8e615a6faad7f5be3eaaaa1834f896ed1365beb77d5a8fcbdc70f12f3462b16"
          ]
        },
        {
          "cohort_id": 18,
          "sign": 1,
          "start_exit_ms": 1747497600000,
          "end_exit_ms": 1747497600000,
          "exit_groups": 1,
          "origin_keys": [
            "3d76dfec91f65235b6b9528f7172d0f4b81cf455cd99f0d21020be81763780c2",
            "88d458309b458d10306f7ea1e344f5b0f924c5741006087fbcf9ff96d73e9279",
            "ebe480142f6fde44c8bd630e98949d1b5928821c747eb9e776bd2b56e13f9800"
          ]
        },
        {
          "cohort_id": 19,
          "sign": -1,
          "start_exit_ms": 1747598400000,
          "end_exit_ms": 1747627200000,
          "exit_groups": 2,
          "origin_keys": [
            "6edb54a38352879b003aa03b19b60af41cfea5ed2fe58d45d32c36ff9b8036fb",
            "e6329bba085fc7a05bdfd0f60732a72382fc45a58d44d58671fc7a2c5a41d78d",
            "3b45e5a08e5b46c824e67cffc67750543f72613e1da6b5d08cb2d52d95a3f4dd"
          ]
        },
        {
          "cohort_id": 20,
          "sign": 1,
          "start_exit_ms": 1747728000000,
          "end_exit_ms": 1747728000000,
          "exit_groups": 1,
          "origin_keys": [
            "2f8ad94eff3a7f569bc6c03875ae0c0ede863e07d0230d8b551f42d8a74a8df9",
            "58caa5c0de31b1d116e216d8f4e878d6050afe63914f6b025e6c09f3f9e2bd3e"
          ]
        },
        {
          "cohort_id": 21,
          "sign": -1,
          "start_exit_ms": 1747742400000,
          "end_exit_ms": 1747742400000,
          "exit_groups": 1,
          "origin_keys": [
            "1c033c7e7de80f564916f3b313f06fa64d43e200b4bd4f00c6f63fc63f41cd41"
          ]
        },
        {
          "cohort_id": 22,
          "sign": 1,
          "start_exit_ms": 1747944000000,
          "end_exit_ms": 1748131200000,
          "exit_groups": 3,
          "origin_keys": [
            "a10581de8ca6e0a3a8d39c7919e138b74e98b8a995d5c1d71b10bc23272e623e",
            "f2155391aa7764c59c85a1774bf8ec2783fdf8da4a5fdf1f7a3e77e7e43eb21f",
            "f4d6def625f4d88d6adbcbcc6c20c2ef2ece38e91cd8c40a8e26b2655f74aadf"
          ]
        },
        {
          "cohort_id": 23,
          "sign": -1,
          "start_exit_ms": 1748160000000,
          "end_exit_ms": 1748390400000,
          "exit_groups": 3,
          "origin_keys": [
            "b79a83562bbb1fcf661f5da109bec9523bc2fbe18a6cc2ee2b9045b078870920",
            "6d3370d48c8dd5361e302db82f2faab51beb8134d32e053764712ba77b9847f2",
            "8d1e9fb1a87540daedeec63a1bd37862547398d79b72b7411f8d46b027e1cea3"
          ]
        },
        {
          "cohort_id": 24,
          "sign": 1,
          "start_exit_ms": 1748404800000,
          "end_exit_ms": 1748404800000,
          "exit_groups": 1,
          "origin_keys": [
            "2309869ab033df7389c783f5f2491430e47c77c04811e44332342a27cf828f14",
            "23c94f724bf48a6e16603c297353285d71192d1cadfa92536f6299787da312dd"
          ]
        },
        {
          "cohort_id": 25,
          "sign": -1,
          "start_exit_ms": 1748448000000,
          "end_exit_ms": 1750003200000,
          "exit_groups": 6,
          "origin_keys": [
            "025bb75df735c790d62747f3e13e8ca2ecf6e25cff47e05c2325121f4400cb62",
            "33f57ce14343f17bddeb7418ac566edd267076603ae156bdc4baf6823225f58e",
            "0a331de10b2976732100714d118f7ab16568669025031ce21fd3ed2ff51ce773",
            "aa3e034323ec63827bf0018347ef7d0a316702d5a0617020d04e8c858a1e2a8a",
            "fb48642108224d3fd03fb697ee7a20785f5171d1bd7cee02e2a5f31071d76a3d",
            "dba9bbf39a23532d0a92a6380648a5a82bb86abaaa2a1533200bea613985c5f9",
            "024114bc463b975bb2471e67185237d7bee62108dc9b572958bf60110d707c7f",
            "edee33a09ec6eb780a2ad5c573cf33227791b558457c97d5e2045ab17f3d554c"
          ]
        },
        {
          "cohort_id": 26,
          "sign": 1,
          "start_exit_ms": 1750118400000,
          "end_exit_ms": 1750118400000,
          "exit_groups": 1,
          "origin_keys": [
            "87c161e5a0178ff7eca2cffd9a8d37631304339b34d0b8783cf85c19f8d4fff5"
          ]
        },
        {
          "cohort_id": 27,
          "sign": -1,
          "start_exit_ms": 1750161600000,
          "end_exit_ms": 1750161600000,
          "exit_groups": 1,
          "origin_keys": [
            "346f7341f2bf3ca2b223cbb6c08980902fe7f1f65b9318434a2f735617f90af0"
          ]
        },
        {
          "cohort_id": 28,
          "sign": 1,
          "start_exit_ms": 1750507200000,
          "end_exit_ms": 1750507200000,
          "exit_groups": 1,
          "origin_keys": [
            "fe8e0737e3379d2cef8489483a55b8b1e702cce913035dd0ea89742db9df1314"
          ]
        },
        {
          "cohort_id": 29,
          "sign": -1,
          "start_exit_ms": 1750752000000,
          "end_exit_ms": 1750752000000,
          "exit_groups": 1,
          "origin_keys": [
            "39539c214fa857f57942fdecb68ca04e4d9b1018d4cbf98a027b0bce364fd025"
          ]
        },
        {
          "cohort_id": 30,
          "sign": 1,
          "start_exit_ms": 1751169600000,
          "end_exit_ms": 1751356800000,
          "exit_groups": 2,
          "origin_keys": [
            "f8b2e6dbf975e01a4c24cd97e823cf2d2682b8c4ca2e60fd6ad9d67412e1f08f",
            "19b7e6cbf30ad251a04905bcbe18c261b3c3bc82fa95963ecd9c4c95ddfac24b"
          ]
        },
        {
          "cohort_id": 31,
          "sign": -1,
          "start_exit_ms": 1751385600000,
          "end_exit_ms": 1751385600000,
          "exit_groups": 1,
          "origin_keys": [
            "ea90f21d84b730c28a1773be9ee1628a4daf2163a42ab9d96c480e4de0f0193e"
          ]
        },
        {
          "cohort_id": 32,
          "sign": 1,
          "start_exit_ms": 1751616000000,
          "end_exit_ms": 1751616000000,
          "exit_groups": 1,
          "origin_keys": [
            "5dc1f4defbfbc3fa4dc1acb116712938b0a3552d6a89b263aaad65507c8dbd26",
            "96ed746cc89114bc96aac5280111eea20edd9a85e84ab8419892e4e8f9fb98cd"
          ]
        },
        {
          "cohort_id": 33,
          "sign": -1,
          "start_exit_ms": 1751644800000,
          "end_exit_ms": 1751990400000,
          "exit_groups": 5,
          "origin_keys": [
            "64fee382be25139512d408919e8250d563f51d560dd3b813196fdd208868c8d1",
            "ccd2a420e644f4be3c60d0b80e6328f0b025f3b9e7258bcba646be88e60ca47f",
            "96a7eaa94ec10a0dc4fed1a17b04fca7a0d6ce97a652a93ce32f852597731eca",
            "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569",
            "a87ac993ed55790f6527004a16cd082a003328436ad856153d97b67f81c32b3c",
            "1db87f8de43b59b15f878d313cfc72243fc58147aba4e2a1d092d175f11a6420"
          ]
        },
        {
          "cohort_id": 34,
          "sign": 1,
          "start_exit_ms": 1752163200000,
          "end_exit_ms": 1752537600000,
          "exit_groups": 6,
          "origin_keys": [
            "5670edf0d14be75b650617df11623e0c264c928e01761685247611300e2c2b4e",
            "d4587f56aa58595f4a5c34cb1c8d91539ec6b99ae14be7a6f3791416a8d508a8",
            "7580befe0c0c1ebfe54b91a1135cd1c53d3864646f191c09a6825a74bb37bb9a",
            "0849bb8f17c8313ebc2ae91114edfd46c6f62986e96607f92da1776c575d6ea3",
            "588117c7ecbadbf1bd2d05794cc3719559963cbeae1c93b38b0a6ed478c372c8",
            "6c79f7624a88231c465b70a25a0548f526f4c38ee7bf9fd10beeaf91f078f348",
            "c4b037954cd3a617621503a5d77862a4938eef8c6a6327ed5330b232b49ed2c6",
            "4135d00ba44ebc5cf362711a4abee2e6d01c478113057178d7b0ea1f56c7e916"
          ]
        },
        {
          "cohort_id": 35,
          "sign": -1,
          "start_exit_ms": 1752552000000,
          "end_exit_ms": 1752710400000,
          "exit_groups": 2,
          "origin_keys": [
            "6bcecc02427a0ab87800a8061d36d4d0c8fb501f79b12637a45b21655b0f9221",
            "1f62363ddf4605200913f11e62d56c828b95351635929f111bd69433e45bade4"
          ]
        },
        {
          "cohort_id": 36,
          "sign": 1,
          "start_exit_ms": 1752782400000,
          "end_exit_ms": 1752782400000,
          "exit_groups": 1,
          "origin_keys": [
            "47dd745683e2b505200b6d7e1fc1ede9415e6a8d5b5aafb1c19767cb1332b910"
          ]
        },
        {
          "cohort_id": 37,
          "sign": -1,
          "start_exit_ms": 1752854400000,
          "end_exit_ms": 1752854400000,
          "exit_groups": 1,
          "origin_keys": [
            "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530"
          ]
        },
        {
          "cohort_id": 38,
          "sign": 1,
          "start_exit_ms": 1752912000000,
          "end_exit_ms": 1752969600000,
          "exit_groups": 3,
          "origin_keys": [
            "ad79f7e334f3d55db655513fa0d0b4c8b86d80c941edf24bfcbb43fac93ed175",
            "52b2c7f77188ca8227f75c8db34792dd70799a9ad5ff7cd3319389ceec23568a",
            "0d2b35ab633f4d557b8498f19d4a4520d5b9a0efb7ba02443b9ae02d1091d3e6"
          ]
        },
        {
          "cohort_id": 39,
          "sign": -1,
          "start_exit_ms": 1753056000000,
          "end_exit_ms": 1753056000000,
          "exit_groups": 1,
          "origin_keys": [
            "d88d6da82807ed73485910acdb84b99de13e8b250836cce7b9e4604a05804a5e"
          ]
        },
        {
          "cohort_id": 40,
          "sign": 1,
          "start_exit_ms": 1753128000000,
          "end_exit_ms": 1753171200000,
          "exit_groups": 2,
          "origin_keys": [
            "130a5d5d13a47060b238ee0b3ea34039c17b4d62c365ed662db54151cb725994",
            "a9a3e8365fcc187a032b988186095539cef032de8177ce8cd707794f13c41178"
          ]
        },
        {
          "cohort_id": 41,
          "sign": -1,
          "start_exit_ms": 1753286400000,
          "end_exit_ms": 1753416000000,
          "exit_groups": 5,
          "origin_keys": [
            "e8c732e46d0580a95e52293b59277c9ba520fdc091bf689bd5ae2e21d33050dd",
            "3cd227554c6bd53fad0d12e860efe081bd24b05cccf9e1d794a182c8c4dcad6e",
            "8a5d77ec50be4dde6278d0637ccd74d2208b8fdb80e2fe1aafd67d12055bbe9b",
            "7af2a28e7e974d6aea365bca7852e315a945200b974024e626335ee7577f02d7",
            "81f03a46613732f84a14cc6faf711252ca5de24205bf3fca9360c100254dde55"
          ]
        },
        {
          "cohort_id": 42,
          "sign": 1,
          "start_exit_ms": 1753718400000,
          "end_exit_ms": 1753776000000,
          "exit_groups": 2,
          "origin_keys": [
            "10a7b67bfcf5fdef4e36f5eea44c22d0c15966fe732ee607db46507ea2c37308",
            "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1",
            "63792578bc411889e22ef91262a5824732a8d1ae57a0ded1ca745836604b9ca0",
            "557b95fc65cbf0a8035281ddc5e29e72cd7bc95790782d8b7411eecf313ca04e"
          ]
        },
        {
          "cohort_id": 43,
          "sign": -1,
          "start_exit_ms": 1753804800000,
          "end_exit_ms": 1754035200000,
          "exit_groups": 3,
          "origin_keys": [
            "72b8b528d33ac98c9e17345c6de9613fe8d6014697570c41ea668548c0f2e6ae",
            "da7ef6e9025099319f5576f5f52136b82c6f1ec5029bcf9e25045c2badadd7fd",
            "71902b786b8aa54c87f1430de51e32e03473b5c94413248f360662735a04ef94",
            "eacc20084995a3ab4a7da3fa3ca8dbab480710b7067c84bc8292646e35c78df3"
          ]
        },
        {
          "cohort_id": 44,
          "sign": 1,
          "start_exit_ms": 1754755200000,
          "end_exit_ms": 1754755200000,
          "exit_groups": 1,
          "origin_keys": [
            "b39417684ba0dd296a071fcc13fe5216b1b6844235c84549dc686fccb4673de2"
          ]
        },
        {
          "cohort_id": 45,
          "sign": -1,
          "start_exit_ms": 1754812800000,
          "end_exit_ms": 1754812800000,
          "exit_groups": 1,
          "origin_keys": [
            "426aaff0097e98b6f0e7cc599671e126621e79f81c2d9456d7d68d4dc6ce0e50"
          ]
        },
        {
          "cohort_id": 46,
          "sign": 1,
          "start_exit_ms": 1755100800000,
          "end_exit_ms": 1755158400000,
          "exit_groups": 2,
          "origin_keys": [
            "a6dd07b321410fe650cca40b7fba4a0319308127876915148c36d7d211015c8d",
            "fa2227abd88b8c794620d6219457b183c6b3c8053e46cdabdf4ff044408ae2e8"
          ]
        },
        {
          "cohort_id": 47,
          "sign": -1,
          "start_exit_ms": 1755187200000,
          "end_exit_ms": 1755273600000,
          "exit_groups": 2,
          "origin_keys": [
            "86080a597e0bc1116384e954acd6b0c32041e73eec3b5942be80a252744afa0d",
            "97ac73b0f3529903ed9ea201036b3a9a435d9f8242a6960923498385c043fde6",
            "d8c4f5ef31ad715ad9c25e6dbcb30b68461f2f90690cb945d7860890f229bfc0",
            "23afcd4e4c4688f46d0a8905fb2ed0da9124e917c61c1c8310d2bbd3f05a9253"
          ]
        },
        {
          "cohort_id": 48,
          "sign": 1,
          "start_exit_ms": 1755374400000,
          "end_exit_ms": 1755374400000,
          "exit_groups": 1,
          "origin_keys": [
            "26f83f96f1a03e42ad86c962382630587b92091985220c144f5c7f898fa19067"
          ]
        },
        {
          "cohort_id": 49,
          "sign": -1,
          "start_exit_ms": 1755403200000,
          "end_exit_ms": 1755489600000,
          "exit_groups": 2,
          "origin_keys": [
            "d982dd8e49b3f106e644332a4059d1194d1d35aee6d350030b4372357aea69b9",
            "0d6aa06212cbc737dcc220fe2a05a8b0915ef9cbbaeeff4122e1226468ce37f9",
            "8192c69c9ec4091daed78995d26184cd0f43e977592742eb3f1fb55906840011"
          ]
        },
        {
          "cohort_id": 50,
          "sign": 1,
          "start_exit_ms": 1755576000000,
          "end_exit_ms": 1756022400000,
          "exit_groups": 3,
          "origin_keys": [
            "d42bc424b418ebd385e34b86cfaafa6df637e49e5d03982b8bf2a22f33c6c63a",
            "23bdd736b6f855d35443df00de3082fc216d437a3f7b5535adb2b3a3965c802a",
            "2a31409627d7f1beff834be00cd1d4b4f8f24cebba69f13c1e941d9ef6a9c809"
          ]
        },
        {
          "cohort_id": 51,
          "sign": -1,
          "start_exit_ms": 1756108800000,
          "end_exit_ms": 1756108800000,
          "exit_groups": 1,
          "origin_keys": [
            "d1b4cfd5ebf80e5ed19f62d16eda0239aaa594558936a7e9760b06bd1999ac97"
          ]
        },
        {
          "cohort_id": 52,
          "sign": 1,
          "start_exit_ms": 1756411200000,
          "end_exit_ms": 1756411200000,
          "exit_groups": 1,
          "origin_keys": [
            "2adc0b6550a8692d06f7907f2283b556c58dbb2f52425e8fefaf9d9a861db92e",
            "c46a24ae2079a3556a5634f46ea9cc39fa760e6f78bcdc8b8e93307851dbe34f",
            "ea31de60b9c578b294c333209ac5925bedfc3aab8bedc15564ff24f696aba6af"
          ]
        },
        {
          "cohort_id": 53,
          "sign": -1,
          "start_exit_ms": 1756684800000,
          "end_exit_ms": 1757188800000,
          "exit_groups": 3,
          "origin_keys": [
            "428905cd69a7a3e76e9dfd3255579237ec52be6122201a44ace33881e1ee47c8",
            "6b549f02e4f064bbf7f4c40e4f51f94b9580167a0e1972608ddacf43c0ed34ac",
            "57df2b8e7677d5ef175fe1e3bed5da1b538e591195809d42e04946f07d5a9955"
          ]
        },
        {
          "cohort_id": 54,
          "sign": 1,
          "start_exit_ms": 1757203200000,
          "end_exit_ms": 1757203200000,
          "exit_groups": 1,
          "origin_keys": [
            "62a1ecd9a5055c7fafa15edff164e12cc643c6d1dacc2dba19cc9ff6f76a0192"
          ]
        },
        {
          "cohort_id": 55,
          "sign": -1,
          "start_exit_ms": 1757376000000,
          "end_exit_ms": 1757376000000,
          "exit_groups": 1,
          "origin_keys": [
            "c6127a03ef0009f3f300690bc57de1882c9f9c2a234e6211a1955769f77408b0"
          ]
        },
        {
          "cohort_id": 56,
          "sign": 1,
          "start_exit_ms": 1757563200000,
          "end_exit_ms": 1757808000000,
          "exit_groups": 3,
          "origin_keys": [
            "1c68a9cc14bdd4d08a9787b78b28f26e9ac4ebe70a07e7108f38487895199cf3",
            "eb9da654bf3fdb218cb78c6eab455ba63d5919565b52ce5ed54cba88c489db93",
            "f160d012b4eb926c79383261efa36103180162299f3ef7802efe75e8f5161450"
          ]
        },
        {
          "cohort_id": 57,
          "sign": -1,
          "start_exit_ms": 1757822400000,
          "end_exit_ms": 1758052800000,
          "exit_groups": 3,
          "origin_keys": [
            "9e87739b9533756c1f3a5cba53e0ec0310b87524ee622d82057c4b3d0ae11e3a",
            "6183540eaf7ee3778e78b8f4d8f8cbc7736977c475a71761e053c24a7e44e283",
            "5b91366303f982be376a09ad7ec60f28c97722348abadb55e4614180885d8494",
            "c6309e88f62a6732468866d3fbf8b8b99fd3bcfa67c46b5ad8d5f497d650274f"
          ]
        },
        {
          "cohort_id": 58,
          "sign": 1,
          "start_exit_ms": 1758139200000,
          "end_exit_ms": 1758268800000,
          "exit_groups": 3,
          "origin_keys": [
            "446c24a7ab0118e270580f92355def0e54c1f805a46924eba8477af8c43d6db3",
            "5b8217ea755075291a5abafee4e933350a5545b7276cab5507cff0aa515ad7b3",
            "64961492ab5f443e90a8c9d564c918cfdce4ee3c606ef665241c4f0c2a96f75e",
            "084205c0d23f84547fa462ce8f9949eb7525299fea73afbdbb958d422d815579",
            "319461a1067ffe81b0a9b34ec4e5678ae9de6a09dc2f66ef17cc4c4a09a2c730"
          ]
        },
        {
          "cohort_id": 59,
          "sign": -1,
          "start_exit_ms": 1758312000000,
          "end_exit_ms": 1759723200000,
          "exit_groups": 5,
          "origin_keys": [
            "2567100622d709b4dadce9bc9984c5f759dd2871070bde93c87592cddcef3b69",
            "2cb7e5e850046b8607fd9b0cb9c7f0f2aeb120b13a6a1d50f764438965a23882",
            "554c51a2434a2ee43b490764a07e182d925621dbdb5a87d364e2d6b925a69c4e",
            "7167ad5b637d274e19469116dd430cf47e3fa43d9259e8d766a1b58d5247e381",
            "b281893de94140686bcbd995ee033670ee9076750fd90c016395f78e85a96224",
            "cfede36f952bb1cbafdc54a70967713c8d8900f29aebfedaa2683dac8a33a86e"
          ]
        },
        {
          "cohort_id": 60,
          "sign": 1,
          "start_exit_ms": 1759795200000,
          "end_exit_ms": 1759809600000,
          "exit_groups": 2,
          "origin_keys": [
            "673673e4647d7f781ef34e86f6ab6f68b4e56d561629511e3dff804e2fc671b9",
            "35ed91621849376419f6a0416043957568e31d43b58965d228e0a880574e2118",
            "dc95dba52f37e16c5de4ccd174eaa3cc6e3ce42cdd52d1f6e2841c740a29209e"
          ]
        },
        {
          "cohort_id": 61,
          "sign": -1,
          "start_exit_ms": 1759852800000,
          "end_exit_ms": 1762977600000,
          "exit_groups": 10,
          "origin_keys": [
            "6b15d4c81966c958f5e997c9caf2044debb3fddad3fd1969d5b022cf9f8e5b66",
            "6d7eb08e9607b2be435cacced40b81d9855211d28884d5b533cb61f20bd74fd6",
            "681c4acc892374e7bcd61098f01cc55c78648364b0a80492cfad92ce115adb96",
            "d346d8f7ef310a5146f7cbd5edb0b096875d404f38193565e98f1903694dfaa6",
            "838b7a14075d36308a1a5ab625659a67f9be7cf6c23d20b03f869a40305a56a3",
            "5e58f9cb119a8b70f2c4bb512362e1b7e01abc3d777b030a55dc34eff226844a",
            "f888e7d1e2866d29d3cd9fead0ba59a9c640b2a0a344b1a07c88e34cab792734",
            "71904ade42290aeffcefe5a884c06e6e43bb3f316316ca6025b4318cbe94c6d8",
            "8eaf489299cdec5d86e09ce744d53479600da0ce04381f2d640e33c1fc094db5",
            "9a17a25717bcb7603fddca5b6b6f1092fe9f037d524c36d2a920f5c502b3190a",
            "f04b345b13db9aef69e08301403563cd13bee3941d6c62e05f591694a5764ad7"
          ]
        },
        {
          "cohort_id": 62,
          "sign": 1,
          "start_exit_ms": 1764316800000,
          "end_exit_ms": 1764316800000,
          "exit_groups": 1,
          "origin_keys": [
            "c2f731fadf077fedfbfdf44b7e5a0fb93953f2b0866afa1175c6f9775d38b1a2"
          ]
        },
        {
          "cohort_id": 63,
          "sign": -1,
          "start_exit_ms": 1764360000000,
          "end_exit_ms": 1764446400000,
          "exit_groups": 2,
          "origin_keys": [
            "1b899f0e0e9a043529d9ff3ea24e4737f7ecd88b972cdccc07476aef05e5e951",
            "f3a7f3359ee694f3f2ec72d0883e89ff8244c00ad0ba3ab05e8a8fdcfcff5a7c"
          ]
        },
        {
          "cohort_id": 64,
          "sign": 1,
          "start_exit_ms": 1764518400000,
          "end_exit_ms": 1764518400000,
          "exit_groups": 1,
          "origin_keys": [
            "0bdca7d41379168b140b2e66004f877e7ed16f1ec94ad27a829709e01d88dcfd"
          ]
        },
        {
          "cohort_id": 65,
          "sign": -1,
          "start_exit_ms": 1764547200000,
          "end_exit_ms": 1764936000000,
          "exit_groups": 3,
          "origin_keys": [
            "096bc697ee57acd04f69b2bdafa69304be268939fa6fc7ce3e7d4a153993239d",
            "50ef6567fbd7df3446b1349d46cc3248422d6ac0b97efc4a25c0e41078dd9fa2",
            "8f2deb5337fb114b9d57c7ffc9866b6a3147b0b3736a493d25f9408a2952de70",
            "96d5be021062d7510e93873bbad3117337da5ca3fc3a5d22dfde06c7a45223c4"
          ]
        },
        {
          "cohort_id": 66,
          "sign": 1,
          "start_exit_ms": 1765224000000,
          "end_exit_ms": 1765224000000,
          "exit_groups": 1,
          "origin_keys": [
            "0bb441638757d83417e5d34843eb3662cf34bc63b082e0543c9d4e6ea4c281a2"
          ]
        },
        {
          "cohort_id": 67,
          "sign": -1,
          "start_exit_ms": 1765339200000,
          "end_exit_ms": 1766534400000,
          "exit_groups": 5,
          "origin_keys": [
            "06f11cb99f29537c27c1e17dd06ab6fa36592086e512f419221fab219e69025c",
            "8db5e99d7b412ef451f5f40543f15fa63a61ce198466589c3f312ac65c581f6f",
            "98415b5f82bd3af2ba758b66c93c9918aecfd9d3b1cca6f1c99f5fd6b1981665",
            "98e92a785ee2e630812749980e5a0265365fb37533cd38ac8932dc77759b3137",
            "a97a1ea6fdb491a48099adef01ad75dd6269a7cf73b55ef7ec9f7155b6a56862",
            "71ad5943e5ee593a23085130ebed82c16fe5e4084605413d3843385d3ceec257",
            "87a932ea0171d6110434a232dfd49105d4d3f1260f570d604c5ae0bbec3f9d70",
            "a56600ae8b8d496db0b3245e50dbbde722769f7fb538e778fc707eb4974a8006",
            "b8f4efc9ce43a92fe22dcb9ccfd9832f3d5b18e624a147236e626f2f61a9b930",
            "7592b8b06b52feeb652ccc01853e62faecdb8115c0564457f76aeb2254d34000"
          ]
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": 74.8239282614719,
          "BCH-USDT": -622.9305391407165,
          "BTC-USDT": 44.19436715785122,
          "ETH-USDT": 3727.5851271716006,
          "HYPE-USDT": 3141.6525623561015,
          "LINK-USDT": 2394.0726573718,
          "SOL-USDT": -874.6556615019458
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 6419.543212695689,
          "BCH-USDT": 5412.051239652212,
          "BTC-USDT": 3477.296832554346,
          "ETH-USDT": 8657.6929859195,
          "HYPE-USDT": 9801.53226047399,
          "LINK-USDT": 6720.438744906569,
          "SOL-USDT": 5680.077493415983
        },
        "total_positive_trade_profit_bps": 46168.63276961829,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.21229851681733106,
        "winner_T": 81,
        "top_decile_winner_T": 9,
        "top_decile_winners_share": 0.42260670789051974,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2024-12": 0,
          "2025-01": 0,
          "2025-02": 301.5794705444807,
          "2025-03": 3039.562565894135,
          "2025-04": 2283.1314480847927,
          "2025-05": 3598.868406104278,
          "2025-06": -591.0336503260327,
          "2025-07": 7179.976422294548,
          "2025-08": -191.8873369541304,
          "2025-09": 605.9932233106437,
          "2025-10": -2435.597814257083,
          "2025-11": -730.2498393716005,
          "2025-12": -5175.6004536478695
        },
        "top_positive_month_share": 0.4221253066040359
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1737936000000,
          "T": 1,
          "net_trade_sum_bps": 1062.6028859344572
        },
        {
          "utc_monday_ms": 1738540800000,
          "T": 1,
          "net_trade_sum_bps": -579.3200423015144
        },
        {
          "utc_monday_ms": 1740355200000,
          "T": 1,
          "net_trade_sum_bps": -181.70337308846206
        },
        {
          "utc_monday_ms": 1740960000000,
          "T": 2,
          "net_trade_sum_bps": 1680.3877112297146
        },
        {
          "utc_monday_ms": 1742169600000,
          "T": 2,
          "net_trade_sum_bps": 779.8888881178773
        },
        {
          "utc_monday_ms": 1742774400000,
          "T": 6,
          "net_trade_sum_bps": 579.285966546543
        },
        {
          "utc_monday_ms": 1744588800000,
          "T": 6,
          "net_trade_sum_bps": 468.5167582084153
        },
        {
          "utc_monday_ms": 1745193600000,
          "T": 7,
          "net_trade_sum_bps": 3307.0560455305554
        },
        {
          "utc_monday_ms": 1745798400000,
          "T": 14,
          "net_trade_sum_bps": -1087.1701088472046
        },
        {
          "utc_monday_ms": 1746403200000,
          "T": 6,
          "net_trade_sum_bps": 4808.170503176422
        },
        {
          "utc_monday_ms": 1747008000000,
          "T": 15,
          "net_trade_sum_bps": -3325.9101505891254
        },
        {
          "utc_monday_ms": 1747612800000,
          "T": 8,
          "net_trade_sum_bps": 3594.5159864285515
        },
        {
          "utc_monday_ms": 1748217600000,
          "T": 9,
          "net_trade_sum_bps": -1883.1791797185433
        },
        {
          "utc_monday_ms": 1748822400000,
          "T": 1,
          "net_trade_sum_bps": -366.531824934293
        },
        {
          "utc_monday_ms": 1749427200000,
          "T": 2,
          "net_trade_sum_bps": -344.6236840662
        },
        {
          "utc_monday_ms": 1750032000000,
          "T": 3,
          "net_trade_sum_bps": 221.2239008236495
        },
        {
          "utc_monday_ms": 1750636800000,
          "T": 2,
          "net_trade_sum_bps": -101.1020421491892
        },
        {
          "utc_monday_ms": 1751241600000,
          "T": 7,
          "net_trade_sum_bps": -543.8002154283296
        },
        {
          "utc_monday_ms": 1751846400000,
          "T": 9,
          "net_trade_sum_bps": 4754.208666423764
        },
        {
          "utc_monday_ms": 1752451200000,
          "T": 9,
          "net_trade_sum_bps": 4576.666130382224
        },
        {
          "utc_monday_ms": 1753056000000,
          "T": 8,
          "net_trade_sum_bps": -2055.77426014282
        },
        {
          "utc_monday_ms": 1753660800000,
          "T": 8,
          "net_trade_sum_bps": 250.09211737131767
        },
        {
          "utc_monday_ms": 1754265600000,
          "T": 2,
          "net_trade_sum_bps": -212.65995025226442
        },
        {
          "utc_monday_ms": 1754870400000,
          "T": 8,
          "net_trade_sum_bps": 408.10482506887473
        },
        {
          "utc_monday_ms": 1755475200000,
          "T": 5,
          "net_trade_sum_bps": -97.77309917158306
        },
        {
          "utc_monday_ms": 1756080000000,
          "T": 4,
          "net_trade_sum_bps": -90.97512891076587
        },
        {
          "utc_monday_ms": 1756684800000,
          "T": 4,
          "net_trade_sum_bps": -578.3437006055626
        },
        {
          "utc_monday_ms": 1757289600000,
          "T": 5,
          "net_trade_sum_bps": 3039.435402516072
        },
        {
          "utc_monday_ms": 1757894400000,
          "T": 11,
          "net_trade_sum_bps": -996.0881399661545
        },
        {
          "utc_monday_ms": 1758499200000,
          "T": 1,
          "net_trade_sum_bps": -859.0103386337111
        },
        {
          "utc_monday_ms": 1759104000000,
          "T": 1,
          "net_trade_sum_bps": -359.57654723127064
        },
        {
          "utc_monday_ms": 1759708800000,
          "T": 10,
          "net_trade_sum_bps": -1552.8369791004898
        },
        {
          "utc_monday_ms": 1761523200000,
          "T": 4,
          "net_trade_sum_bps": -919.0427590078841
        },
        {
          "utc_monday_ms": 1762732800000,
          "T": 1,
          "net_trade_sum_bps": -139.76988474602933
        },
        {
          "utc_monday_ms": 1763942400000,
          "T": 4,
          "net_trade_sum_bps": -194.62148354300928
        },
        {
          "utc_monday_ms": 1764547200000,
          "T": 4,
          "net_trade_sum_bps": -1373.2093762526397
        },
        {
          "utc_monday_ms": 1765152000000,
          "T": 9,
          "net_trade_sum_bps": -3328.709328248181
        },
        {
          "utc_monday_ms": 1766361600000,
          "T": 2,
          "net_trade_sum_bps": -473.68174914704906
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": 1,
          "start_exit_ms": 1738382400000,
          "end_exit_ms": 1738382400000,
          "exit_groups": 1,
          "origin_keys": [
            "979b207a0cba154c4e56588b522459fa2902ad9ee30a61a24690b47f38d357e6"
          ]
        },
        {
          "cohort_id": 1,
          "sign": -1,
          "start_exit_ms": 1738857600000,
          "end_exit_ms": 1741320000000,
          "exit_groups": 3,
          "origin_keys": [
            "75bc1657579c38bd14d06fb08329382d285734e221669423c07436b9168745f3",
            "e20ec6b5b1d64710658dccc8218f65bec8ec99a40af5f15cf38a37a4902efd57",
            "3ba2fc0bf476825ddf705c60441b6695aa84f0134bde8a0de6895f244bbe5a6e"
          ]
        },
        {
          "cohort_id": 2,
          "sign": 1,
          "start_exit_ms": 1741406400000,
          "end_exit_ms": 1742990400000,
          "exit_groups": 5,
          "origin_keys": [
            "5d6e5b2ff3cf13258185ce91cb7c4e919d939674c0a8eb3b43bee07fbb02deb6",
            "4d5ff1901411d6d49cbce69c93cbc35f4d7bb8f5a9c9a77c44ee660c68c28e32",
            "c1127e43093e62cbe8bc16e1487a4dbf17ce66211259d19a6e5ed93a56095320",
            "1653ba4f1d26dff2261e9c362f004f8c74c8b766ce03e28276216c4ccab687dc",
            "5a528e3ccae612a1a58eb63f60fb13cc6f88990b4cdc88471dcb9c3b4631c521",
            "e8a6e1ffe7c7d82419d74876b6a6c46f0e78bad36cdd9a091afc4a89323dbc35"
          ]
        },
        {
          "cohort_id": 3,
          "sign": -1,
          "start_exit_ms": 1743004800000,
          "end_exit_ms": 1744876800000,
          "exit_groups": 4,
          "origin_keys": [
            "196c03d2731521f1e86e4d797f11094e616708a19020dce4919dacc640f21060",
            "1708bab61045d1eeaa2c350e2e7851851f62a23daf078ff8998df30b18ed7d14",
            "711b1318d15c09603ef57558aa7a1f321f727f1dff1c4d08c6e41a755e5d3c3a",
            "c854aa8fd523fc736ca1f0b9acc5783788dc70558b58da7d91737d68ee88eec4"
          ]
        },
        {
          "cohort_id": 4,
          "sign": 1,
          "start_exit_ms": 1744992000000,
          "end_exit_ms": 1745006400000,
          "exit_groups": 2,
          "origin_keys": [
            "11ff48ed506f83b9a9fa9267381bd2d96e7de9404c20349e175ed0db38927ae8",
            "9c1cc06b28d04eb6b93b11b379fff3ea7948f56ac55794d9003e490d48691ebb",
            "ab487bcd177eb3107deb68c125a05af61af7384a70cf079a682c2c129adc581f",
            "2061fca492db51368428be5f97a2337099a971b1842d4f29c72fb5ae77d1aa25"
          ]
        },
        {
          "cohort_id": 5,
          "sign": -1,
          "start_exit_ms": 1745150400000,
          "end_exit_ms": 1745150400000,
          "exit_groups": 1,
          "origin_keys": [
            "6a17e80b6f6a73786f18faa40f8e3a691fe1f65bc2214d9ddccb1cacba42f3a1"
          ]
        },
        {
          "cohort_id": 6,
          "sign": 1,
          "start_exit_ms": 1745280000000,
          "end_exit_ms": 1745539200000,
          "exit_groups": 5,
          "origin_keys": [
            "54e6c4939b93069ee71a073f9a5a7b9ee5f32e6eb14fbf1ef64e5b05c56eab0f",
            "e1f389c1a4c16aa5bae8730c6d710e4e99e1f40b7a1278be9fffc2fc593c5a55",
            "3ad0f0c17337ad73dfebd624f47c0cf42535a2ecf32a0c9e0c23efbda8935e30",
            "15f69d81e2bb95a5a72b262f18e8222757758b3138990c1d01b999cdc4da3c09",
            "0f9e0ad9a9c424f355d0fdc40b7b9f452b36a382a8c11e5d93e8fc8cb8812f7b"
          ]
        },
        {
          "cohort_id": 7,
          "sign": -1,
          "start_exit_ms": 1745668800000,
          "end_exit_ms": 1745668800000,
          "exit_groups": 1,
          "origin_keys": [
            "4504481ef8c1c67ae04a5af5a8063e7ca5996ffb14cc64793242056b597b31cb"
          ]
        },
        {
          "cohort_id": 8,
          "sign": 1,
          "start_exit_ms": 1745683200000,
          "end_exit_ms": 1745683200000,
          "exit_groups": 1,
          "origin_keys": [
            "ea78a8e6612680ae67dc8d6a43ac87831fd7402265ddde47cb87cae704a34f2a"
          ]
        },
        {
          "cohort_id": 9,
          "sign": -1,
          "start_exit_ms": 1745856000000,
          "end_exit_ms": 1745956800000,
          "exit_groups": 2,
          "origin_keys": [
            "136c2d685362c73f9c8faac1906b1f0f6b39c96937143c502f1dafa8a17f4635",
            "618293610019999e13d4089b009d7d4f7243872a4800ba1651afc4ef5d78ae32",
            "ef80ea0ab964ded3cdbd87ba38a28fa6eb5edb7d734c2b5aa4c4f62794837d20"
          ]
        },
        {
          "cohort_id": 10,
          "sign": 1,
          "start_exit_ms": 1745985600000,
          "end_exit_ms": 1745985600000,
          "exit_groups": 1,
          "origin_keys": [
            "45f7cd3f209d7eabbd187e7f0fec94a334dc2c79f7cf987251ea383993cfbb9b"
          ]
        },
        {
          "cohort_id": 11,
          "sign": -1,
          "start_exit_ms": 1746000000000,
          "end_exit_ms": 1746129600000,
          "exit_groups": 3,
          "origin_keys": [
            "ad4f0095fed68a4b976ecb545563933251f5d099bc47915b8c67de1819455bb4",
            "b2e6e3962feac71b22eb2074e39a006cb98587f0725bf3109be8838ef695308a",
            "2a6edbf2a77ba9baccbbcad7d1ac4fa45547e5b199bfb7188e01fef99ea9f0f1",
            "8f8515e6532e5db846128d34e0acd9af583552e0154ecac8c07839a96cfa430b",
            "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77"
          ]
        },
        {
          "cohort_id": 12,
          "sign": 1,
          "start_exit_ms": 1746230400000,
          "end_exit_ms": 1746244800000,
          "exit_groups": 2,
          "origin_keys": [
            "66117e742708f66294f9f95ffa8f4508569ca50a81ef0ff2ed50ae5b21508b7a",
            "9f57fefae4501e2060405f7b470a13e8d60a6ebc9b825b311517e592dab05c18"
          ]
        },
        {
          "cohort_id": 13,
          "sign": -1,
          "start_exit_ms": 1746259200000,
          "end_exit_ms": 1746331200000,
          "exit_groups": 2,
          "origin_keys": [
            "3d58ce6d768f2b3a9f9ec4e78dbcbd10c17801962fd80435b1900d7a3a2458bb",
            "c798df5ca9bb60fe80cee47c9a36ff1dae5485b87024b19d401247092885b5d6"
          ]
        },
        {
          "cohort_id": 14,
          "sign": 1,
          "start_exit_ms": 1746388800000,
          "end_exit_ms": 1746388800000,
          "exit_groups": 1,
          "origin_keys": [
            "443656f5dc9edca0ebcdea7effb81353900acbd8e3568596f3b41b175c57c721"
          ]
        },
        {
          "cohort_id": 15,
          "sign": -1,
          "start_exit_ms": 1746460800000,
          "end_exit_ms": 1746532800000,
          "exit_groups": 2,
          "origin_keys": [
            "54b78a22139f7b6fc6d5a8c320c51466f5d1d0b370101c3b40221d9a51a8ecd5",
            "a414ff0468e67cedd06ac949d41cc4e377a5c3179a42c660ff0b8de3fdfc92f1",
            "437f79a339b9767f600ec378cd215060196d2354fc2a82b194def883ac5e5e94"
          ]
        },
        {
          "cohort_id": 16,
          "sign": 1,
          "start_exit_ms": 1746907200000,
          "end_exit_ms": 1746950400000,
          "exit_groups": 3,
          "origin_keys": [
            "c22715040c25b6fa120e78b741bbd6aa34568c23f641a18898967fa9605765ed",
            "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
            "98d9d88ea5b38501a3f288f0b18d965f0ca2f3d4b971d011f6c4b3f696539466"
          ]
        },
        {
          "cohort_id": 17,
          "sign": -1,
          "start_exit_ms": 1747137600000,
          "end_exit_ms": 1747483200000,
          "exit_groups": 5,
          "origin_keys": [
            "614f68e55b8871666bebe8710b0bf29a55c5a71bc88360169166f0b5cb0630ff",
            "7eafb7cae685ca0d1c66f35b17c30da5f58b571af67a9d38d545974f2953a2bb",
            "0699ffb8a34eae2af55c58494a1e85dffbf7b36aa8e425931ea7d037495506fa",
            "32d7355d1e8b6905432e9c1c04556f6b55d24b66827a68e18ece58943811bcc1",
            "994c40c0e2256268dde011f6f7d9fc1f972f2003cc15f350f2c2a2a82c7a439f",
            "dcae4bdf5d8ecbbd233ca0df467fee60f9a5d995fa76a2732c9190f4cd1860e6",
            "df5f82141ecb5edf4d9fa776242df2050725bc80a7fa0fbf15264585eb13aa2d",
            "1d528bb8ffde0df9b2af2eb4afa0b2ba2baa64b6feed2cd6c2728f06dfc039e7",
            "042d9748b7ad652fe6a1459db425be08a6a4ee9271a2ed26f7c2d7a8d49bfe0b",
            "a8e615a6faad7f5be3eaaaa1834f896ed1365beb77d5a8fcbdc70f12f3462b16"
          ]
        },
        {
          "cohort_id": 18,
          "sign": 1,
          "start_exit_ms": 1747497600000,
          "end_exit_ms": 1747497600000,
          "exit_groups": 1,
          "origin_keys": [
            "3d76dfec91f65235b6b9528f7172d0f4b81cf455cd99f0d21020be81763780c2",
            "88d458309b458d10306f7ea1e344f5b0f924c5741006087fbcf9ff96d73e9279",
            "ebe480142f6fde44c8bd630e98949d1b5928821c747eb9e776bd2b56e13f9800"
          ]
        },
        {
          "cohort_id": 19,
          "sign": -1,
          "start_exit_ms": 1747598400000,
          "end_exit_ms": 1747627200000,
          "exit_groups": 2,
          "origin_keys": [
            "6edb54a38352879b003aa03b19b60af41cfea5ed2fe58d45d32c36ff9b8036fb",
            "e6329bba085fc7a05bdfd0f60732a72382fc45a58d44d58671fc7a2c5a41d78d",
            "3b45e5a08e5b46c824e67cffc67750543f72613e1da6b5d08cb2d52d95a3f4dd"
          ]
        },
        {
          "cohort_id": 20,
          "sign": 1,
          "start_exit_ms": 1747728000000,
          "end_exit_ms": 1747728000000,
          "exit_groups": 1,
          "origin_keys": [
            "2f8ad94eff3a7f569bc6c03875ae0c0ede863e07d0230d8b551f42d8a74a8df9",
            "58caa5c0de31b1d116e216d8f4e878d6050afe63914f6b025e6c09f3f9e2bd3e"
          ]
        },
        {
          "cohort_id": 21,
          "sign": -1,
          "start_exit_ms": 1747742400000,
          "end_exit_ms": 1747742400000,
          "exit_groups": 1,
          "origin_keys": [
            "1c033c7e7de80f564916f3b313f06fa64d43e200b4bd4f00c6f63fc63f41cd41"
          ]
        },
        {
          "cohort_id": 22,
          "sign": 1,
          "start_exit_ms": 1747944000000,
          "end_exit_ms": 1748131200000,
          "exit_groups": 3,
          "origin_keys": [
            "a10581de8ca6e0a3a8d39c7919e138b74e98b8a995d5c1d71b10bc23272e623e",
            "f2155391aa7764c59c85a1774bf8ec2783fdf8da4a5fdf1f7a3e77e7e43eb21f",
            "f4d6def625f4d88d6adbcbcc6c20c2ef2ece38e91cd8c40a8e26b2655f74aadf"
          ]
        },
        {
          "cohort_id": 23,
          "sign": -1,
          "start_exit_ms": 1748160000000,
          "end_exit_ms": 1748390400000,
          "exit_groups": 3,
          "origin_keys": [
            "b79a83562bbb1fcf661f5da109bec9523bc2fbe18a6cc2ee2b9045b078870920",
            "6d3370d48c8dd5361e302db82f2faab51beb8134d32e053764712ba77b9847f2",
            "8d1e9fb1a87540daedeec63a1bd37862547398d79b72b7411f8d46b027e1cea3"
          ]
        },
        {
          "cohort_id": 24,
          "sign": 1,
          "start_exit_ms": 1748404800000,
          "end_exit_ms": 1748404800000,
          "exit_groups": 1,
          "origin_keys": [
            "2309869ab033df7389c783f5f2491430e47c77c04811e44332342a27cf828f14",
            "23c94f724bf48a6e16603c297353285d71192d1cadfa92536f6299787da312dd"
          ]
        },
        {
          "cohort_id": 25,
          "sign": -1,
          "start_exit_ms": 1748448000000,
          "end_exit_ms": 1750003200000,
          "exit_groups": 6,
          "origin_keys": [
            "025bb75df735c790d62747f3e13e8ca2ecf6e25cff47e05c2325121f4400cb62",
            "33f57ce14343f17bddeb7418ac566edd267076603ae156bdc4baf6823225f58e",
            "0a331de10b2976732100714d118f7ab16568669025031ce21fd3ed2ff51ce773",
            "aa3e034323ec63827bf0018347ef7d0a316702d5a0617020d04e8c858a1e2a8a",
            "fb48642108224d3fd03fb697ee7a20785f5171d1bd7cee02e2a5f31071d76a3d",
            "dba9bbf39a23532d0a92a6380648a5a82bb86abaaa2a1533200bea613985c5f9",
            "024114bc463b975bb2471e67185237d7bee62108dc9b572958bf60110d707c7f",
            "edee33a09ec6eb780a2ad5c573cf33227791b558457c97d5e2045ab17f3d554c"
          ]
        },
        {
          "cohort_id": 26,
          "sign": 1,
          "start_exit_ms": 1750118400000,
          "end_exit_ms": 1750118400000,
          "exit_groups": 1,
          "origin_keys": [
            "87c161e5a0178ff7eca2cffd9a8d37631304339b34d0b8783cf85c19f8d4fff5"
          ]
        },
        {
          "cohort_id": 27,
          "sign": -1,
          "start_exit_ms": 1750161600000,
          "end_exit_ms": 1750161600000,
          "exit_groups": 1,
          "origin_keys": [
            "346f7341f2bf3ca2b223cbb6c08980902fe7f1f65b9318434a2f735617f90af0"
          ]
        },
        {
          "cohort_id": 28,
          "sign": 1,
          "start_exit_ms": 1750507200000,
          "end_exit_ms": 1750507200000,
          "exit_groups": 1,
          "origin_keys": [
            "fe8e0737e3379d2cef8489483a55b8b1e702cce913035dd0ea89742db9df1314"
          ]
        },
        {
          "cohort_id": 29,
          "sign": -1,
          "start_exit_ms": 1750752000000,
          "end_exit_ms": 1750752000000,
          "exit_groups": 1,
          "origin_keys": [
            "39539c214fa857f57942fdecb68ca04e4d9b1018d4cbf98a027b0bce364fd025"
          ]
        },
        {
          "cohort_id": 30,
          "sign": 1,
          "start_exit_ms": 1751169600000,
          "end_exit_ms": 1751356800000,
          "exit_groups": 2,
          "origin_keys": [
            "f8b2e6dbf975e01a4c24cd97e823cf2d2682b8c4ca2e60fd6ad9d67412e1f08f",
            "19b7e6cbf30ad251a04905bcbe18c261b3c3bc82fa95963ecd9c4c95ddfac24b"
          ]
        },
        {
          "cohort_id": 31,
          "sign": -1,
          "start_exit_ms": 1751385600000,
          "end_exit_ms": 1751385600000,
          "exit_groups": 1,
          "origin_keys": [
            "ea90f21d84b730c28a1773be9ee1628a4daf2163a42ab9d96c480e4de0f0193e"
          ]
        },
        {
          "cohort_id": 32,
          "sign": 1,
          "start_exit_ms": 1751616000000,
          "end_exit_ms": 1751616000000,
          "exit_groups": 1,
          "origin_keys": [
            "5dc1f4defbfbc3fa4dc1acb116712938b0a3552d6a89b263aaad65507c8dbd26",
            "96ed746cc89114bc96aac5280111eea20edd9a85e84ab8419892e4e8f9fb98cd"
          ]
        },
        {
          "cohort_id": 33,
          "sign": -1,
          "start_exit_ms": 1751644800000,
          "end_exit_ms": 1751990400000,
          "exit_groups": 5,
          "origin_keys": [
            "64fee382be25139512d408919e8250d563f51d560dd3b813196fdd208868c8d1",
            "ccd2a420e644f4be3c60d0b80e6328f0b025f3b9e7258bcba646be88e60ca47f",
            "96a7eaa94ec10a0dc4fed1a17b04fca7a0d6ce97a652a93ce32f852597731eca",
            "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569",
            "a87ac993ed55790f6527004a16cd082a003328436ad856153d97b67f81c32b3c",
            "1db87f8de43b59b15f878d313cfc72243fc58147aba4e2a1d092d175f11a6420"
          ]
        },
        {
          "cohort_id": 34,
          "sign": 1,
          "start_exit_ms": 1752163200000,
          "end_exit_ms": 1752537600000,
          "exit_groups": 6,
          "origin_keys": [
            "5670edf0d14be75b650617df11623e0c264c928e01761685247611300e2c2b4e",
            "d4587f56aa58595f4a5c34cb1c8d91539ec6b99ae14be7a6f3791416a8d508a8",
            "7580befe0c0c1ebfe54b91a1135cd1c53d3864646f191c09a6825a74bb37bb9a",
            "0849bb8f17c8313ebc2ae91114edfd46c6f62986e96607f92da1776c575d6ea3",
            "588117c7ecbadbf1bd2d05794cc3719559963cbeae1c93b38b0a6ed478c372c8",
            "6c79f7624a88231c465b70a25a0548f526f4c38ee7bf9fd10beeaf91f078f348",
            "c4b037954cd3a617621503a5d77862a4938eef8c6a6327ed5330b232b49ed2c6",
            "4135d00ba44ebc5cf362711a4abee2e6d01c478113057178d7b0ea1f56c7e916"
          ]
        },
        {
          "cohort_id": 35,
          "sign": -1,
          "start_exit_ms": 1752552000000,
          "end_exit_ms": 1752710400000,
          "exit_groups": 2,
          "origin_keys": [
            "6bcecc02427a0ab87800a8061d36d4d0c8fb501f79b12637a45b21655b0f9221",
            "1f62363ddf4605200913f11e62d56c828b95351635929f111bd69433e45bade4"
          ]
        },
        {
          "cohort_id": 36,
          "sign": 1,
          "start_exit_ms": 1752782400000,
          "end_exit_ms": 1752782400000,
          "exit_groups": 1,
          "origin_keys": [
            "47dd745683e2b505200b6d7e1fc1ede9415e6a8d5b5aafb1c19767cb1332b910"
          ]
        },
        {
          "cohort_id": 37,
          "sign": -1,
          "start_exit_ms": 1752854400000,
          "end_exit_ms": 1752854400000,
          "exit_groups": 1,
          "origin_keys": [
            "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530"
          ]
        },
        {
          "cohort_id": 38,
          "sign": 1,
          "start_exit_ms": 1752912000000,
          "end_exit_ms": 1752969600000,
          "exit_groups": 3,
          "origin_keys": [
            "ad79f7e334f3d55db655513fa0d0b4c8b86d80c941edf24bfcbb43fac93ed175",
            "52b2c7f77188ca8227f75c8db34792dd70799a9ad5ff7cd3319389ceec23568a",
            "0d2b35ab633f4d557b8498f19d4a4520d5b9a0efb7ba02443b9ae02d1091d3e6"
          ]
        },
        {
          "cohort_id": 39,
          "sign": -1,
          "start_exit_ms": 1753056000000,
          "end_exit_ms": 1753056000000,
          "exit_groups": 1,
          "origin_keys": [
            "d88d6da82807ed73485910acdb84b99de13e8b250836cce7b9e4604a05804a5e"
          ]
        },
        {
          "cohort_id": 40,
          "sign": 1,
          "start_exit_ms": 1753128000000,
          "end_exit_ms": 1753171200000,
          "exit_groups": 2,
          "origin_keys": [
            "130a5d5d13a47060b238ee0b3ea34039c17b4d62c365ed662db54151cb725994",
            "a9a3e8365fcc187a032b988186095539cef032de8177ce8cd707794f13c41178"
          ]
        },
        {
          "cohort_id": 41,
          "sign": -1,
          "start_exit_ms": 1753286400000,
          "end_exit_ms": 1753416000000,
          "exit_groups": 5,
          "origin_keys": [
            "e8c732e46d0580a95e52293b59277c9ba520fdc091bf689bd5ae2e21d33050dd",
            "3cd227554c6bd53fad0d12e860efe081bd24b05cccf9e1d794a182c8c4dcad6e",
            "8a5d77ec50be4dde6278d0637ccd74d2208b8fdb80e2fe1aafd67d12055bbe9b",
            "7af2a28e7e974d6aea365bca7852e315a945200b974024e626335ee7577f02d7",
            "81f03a46613732f84a14cc6faf711252ca5de24205bf3fca9360c100254dde55"
          ]
        },
        {
          "cohort_id": 42,
          "sign": 1,
          "start_exit_ms": 1753718400000,
          "end_exit_ms": 1753776000000,
          "exit_groups": 2,
          "origin_keys": [
            "10a7b67bfcf5fdef4e36f5eea44c22d0c15966fe732ee607db46507ea2c37308",
            "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1",
            "63792578bc411889e22ef91262a5824732a8d1ae57a0ded1ca745836604b9ca0",
            "557b95fc65cbf0a8035281ddc5e29e72cd7bc95790782d8b7411eecf313ca04e"
          ]
        },
        {
          "cohort_id": 43,
          "sign": -1,
          "start_exit_ms": 1753804800000,
          "end_exit_ms": 1754035200000,
          "exit_groups": 3,
          "origin_keys": [
            "72b8b528d33ac98c9e17345c6de9613fe8d6014697570c41ea668548c0f2e6ae",
            "da7ef6e9025099319f5576f5f52136b82c6f1ec5029bcf9e25045c2badadd7fd",
            "71902b786b8aa54c87f1430de51e32e03473b5c94413248f360662735a04ef94",
            "eacc20084995a3ab4a7da3fa3ca8dbab480710b7067c84bc8292646e35c78df3"
          ]
        },
        {
          "cohort_id": 44,
          "sign": 1,
          "start_exit_ms": 1754755200000,
          "end_exit_ms": 1754755200000,
          "exit_groups": 1,
          "origin_keys": [
            "b39417684ba0dd296a071fcc13fe5216b1b6844235c84549dc686fccb4673de2"
          ]
        },
        {
          "cohort_id": 45,
          "sign": -1,
          "start_exit_ms": 1754812800000,
          "end_exit_ms": 1754812800000,
          "exit_groups": 1,
          "origin_keys": [
            "426aaff0097e98b6f0e7cc599671e126621e79f81c2d9456d7d68d4dc6ce0e50"
          ]
        },
        {
          "cohort_id": 46,
          "sign": 1,
          "start_exit_ms": 1755100800000,
          "end_exit_ms": 1755158400000,
          "exit_groups": 2,
          "origin_keys": [
            "a6dd07b321410fe650cca40b7fba4a0319308127876915148c36d7d211015c8d",
            "fa2227abd88b8c794620d6219457b183c6b3c8053e46cdabdf4ff044408ae2e8"
          ]
        },
        {
          "cohort_id": 47,
          "sign": -1,
          "start_exit_ms": 1755187200000,
          "end_exit_ms": 1755273600000,
          "exit_groups": 2,
          "origin_keys": [
            "86080a597e0bc1116384e954acd6b0c32041e73eec3b5942be80a252744afa0d",
            "97ac73b0f3529903ed9ea201036b3a9a435d9f8242a6960923498385c043fde6",
            "d8c4f5ef31ad715ad9c25e6dbcb30b68461f2f90690cb945d7860890f229bfc0",
            "23afcd4e4c4688f46d0a8905fb2ed0da9124e917c61c1c8310d2bbd3f05a9253"
          ]
        },
        {
          "cohort_id": 48,
          "sign": 1,
          "start_exit_ms": 1755374400000,
          "end_exit_ms": 1755374400000,
          "exit_groups": 1,
          "origin_keys": [
            "26f83f96f1a03e42ad86c962382630587b92091985220c144f5c7f898fa19067"
          ]
        },
        {
          "cohort_id": 49,
          "sign": -1,
          "start_exit_ms": 1755403200000,
          "end_exit_ms": 1755489600000,
          "exit_groups": 2,
          "origin_keys": [
            "d982dd8e49b3f106e644332a4059d1194d1d35aee6d350030b4372357aea69b9",
            "0d6aa06212cbc737dcc220fe2a05a8b0915ef9cbbaeeff4122e1226468ce37f9",
            "8192c69c9ec4091daed78995d26184cd0f43e977592742eb3f1fb55906840011"
          ]
        },
        {
          "cohort_id": 50,
          "sign": 1,
          "start_exit_ms": 1755576000000,
          "end_exit_ms": 1756022400000,
          "exit_groups": 3,
          "origin_keys": [
            "d42bc424b418ebd385e34b86cfaafa6df637e49e5d03982b8bf2a22f33c6c63a",
            "23bdd736b6f855d35443df00de3082fc216d437a3f7b5535adb2b3a3965c802a",
            "2a31409627d7f1beff834be00cd1d4b4f8f24cebba69f13c1e941d9ef6a9c809"
          ]
        },
        {
          "cohort_id": 51,
          "sign": -1,
          "start_exit_ms": 1756108800000,
          "end_exit_ms": 1756108800000,
          "exit_groups": 1,
          "origin_keys": [
            "d1b4cfd5ebf80e5ed19f62d16eda0239aaa594558936a7e9760b06bd1999ac97"
          ]
        },
        {
          "cohort_id": 52,
          "sign": 1,
          "start_exit_ms": 1756411200000,
          "end_exit_ms": 1756411200000,
          "exit_groups": 1,
          "origin_keys": [
            "2adc0b6550a8692d06f7907f2283b556c58dbb2f52425e8fefaf9d9a861db92e",
            "c46a24ae2079a3556a5634f46ea9cc39fa760e6f78bcdc8b8e93307851dbe34f",
            "ea31de60b9c578b294c333209ac5925bedfc3aab8bedc15564ff24f696aba6af"
          ]
        },
        {
          "cohort_id": 53,
          "sign": -1,
          "start_exit_ms": 1756684800000,
          "end_exit_ms": 1757188800000,
          "exit_groups": 3,
          "origin_keys": [
            "428905cd69a7a3e76e9dfd3255579237ec52be6122201a44ace33881e1ee47c8",
            "6b549f02e4f064bbf7f4c40e4f51f94b9580167a0e1972608ddacf43c0ed34ac",
            "57df2b8e7677d5ef175fe1e3bed5da1b538e591195809d42e04946f07d5a9955"
          ]
        },
        {
          "cohort_id": 54,
          "sign": 1,
          "start_exit_ms": 1757203200000,
          "end_exit_ms": 1757203200000,
          "exit_groups": 1,
          "origin_keys": [
            "62a1ecd9a5055c7fafa15edff164e12cc643c6d1dacc2dba19cc9ff6f76a0192"
          ]
        },
        {
          "cohort_id": 55,
          "sign": -1,
          "start_exit_ms": 1757376000000,
          "end_exit_ms": 1757376000000,
          "exit_groups": 1,
          "origin_keys": [
            "c6127a03ef0009f3f300690bc57de1882c9f9c2a234e6211a1955769f77408b0"
          ]
        },
        {
          "cohort_id": 56,
          "sign": 1,
          "start_exit_ms": 1757563200000,
          "end_exit_ms": 1757808000000,
          "exit_groups": 3,
          "origin_keys": [
            "1c68a9cc14bdd4d08a9787b78b28f26e9ac4ebe70a07e7108f38487895199cf3",
            "eb9da654bf3fdb218cb78c6eab455ba63d5919565b52ce5ed54cba88c489db93",
            "f160d012b4eb926c79383261efa36103180162299f3ef7802efe75e8f5161450"
          ]
        },
        {
          "cohort_id": 57,
          "sign": -1,
          "start_exit_ms": 1757822400000,
          "end_exit_ms": 1758052800000,
          "exit_groups": 3,
          "origin_keys": [
            "9e87739b9533756c1f3a5cba53e0ec0310b87524ee622d82057c4b3d0ae11e3a",
            "6183540eaf7ee3778e78b8f4d8f8cbc7736977c475a71761e053c24a7e44e283",
            "5b91366303f982be376a09ad7ec60f28c97722348abadb55e4614180885d8494",
            "c6309e88f62a6732468866d3fbf8b8b99fd3bcfa67c46b5ad8d5f497d650274f"
          ]
        },
        {
          "cohort_id": 58,
          "sign": 1,
          "start_exit_ms": 1758139200000,
          "end_exit_ms": 1758268800000,
          "exit_groups": 3,
          "origin_keys": [
            "446c24a7ab0118e270580f92355def0e54c1f805a46924eba8477af8c43d6db3",
            "5b8217ea755075291a5abafee4e933350a5545b7276cab5507cff0aa515ad7b3",
            "64961492ab5f443e90a8c9d564c918cfdce4ee3c606ef665241c4f0c2a96f75e",
            "084205c0d23f84547fa462ce8f9949eb7525299fea73afbdbb958d422d815579",
            "319461a1067ffe81b0a9b34ec4e5678ae9de6a09dc2f66ef17cc4c4a09a2c730"
          ]
        },
        {
          "cohort_id": 59,
          "sign": -1,
          "start_exit_ms": 1758312000000,
          "end_exit_ms": 1759723200000,
          "exit_groups": 5,
          "origin_keys": [
            "2567100622d709b4dadce9bc9984c5f759dd2871070bde93c87592cddcef3b69",
            "2cb7e5e850046b8607fd9b0cb9c7f0f2aeb120b13a6a1d50f764438965a23882",
            "554c51a2434a2ee43b490764a07e182d925621dbdb5a87d364e2d6b925a69c4e",
            "7167ad5b637d274e19469116dd430cf47e3fa43d9259e8d766a1b58d5247e381",
            "b281893de94140686bcbd995ee033670ee9076750fd90c016395f78e85a96224",
            "cfede36f952bb1cbafdc54a70967713c8d8900f29aebfedaa2683dac8a33a86e"
          ]
        },
        {
          "cohort_id": 60,
          "sign": 1,
          "start_exit_ms": 1759795200000,
          "end_exit_ms": 1759809600000,
          "exit_groups": 2,
          "origin_keys": [
            "673673e4647d7f781ef34e86f6ab6f68b4e56d561629511e3dff804e2fc671b9",
            "35ed91621849376419f6a0416043957568e31d43b58965d228e0a880574e2118",
            "dc95dba52f37e16c5de4ccd174eaa3cc6e3ce42cdd52d1f6e2841c740a29209e"
          ]
        },
        {
          "cohort_id": 61,
          "sign": -1,
          "start_exit_ms": 1759852800000,
          "end_exit_ms": 1762977600000,
          "exit_groups": 10,
          "origin_keys": [
            "6b15d4c81966c958f5e997c9caf2044debb3fddad3fd1969d5b022cf9f8e5b66",
            "6d7eb08e9607b2be435cacced40b81d9855211d28884d5b533cb61f20bd74fd6",
            "681c4acc892374e7bcd61098f01cc55c78648364b0a80492cfad92ce115adb96",
            "d346d8f7ef310a5146f7cbd5edb0b096875d404f38193565e98f1903694dfaa6",
            "838b7a14075d36308a1a5ab625659a67f9be7cf6c23d20b03f869a40305a56a3",
            "5e58f9cb119a8b70f2c4bb512362e1b7e01abc3d777b030a55dc34eff226844a",
            "f888e7d1e2866d29d3cd9fead0ba59a9c640b2a0a344b1a07c88e34cab792734",
            "71904ade42290aeffcefe5a884c06e6e43bb3f316316ca6025b4318cbe94c6d8",
            "8eaf489299cdec5d86e09ce744d53479600da0ce04381f2d640e33c1fc094db5",
            "9a17a25717bcb7603fddca5b6b6f1092fe9f037d524c36d2a920f5c502b3190a",
            "f04b345b13db9aef69e08301403563cd13bee3941d6c62e05f591694a5764ad7"
          ]
        },
        {
          "cohort_id": 62,
          "sign": 1,
          "start_exit_ms": 1764316800000,
          "end_exit_ms": 1764316800000,
          "exit_groups": 1,
          "origin_keys": [
            "c2f731fadf077fedfbfdf44b7e5a0fb93953f2b0866afa1175c6f9775d38b1a2"
          ]
        },
        {
          "cohort_id": 63,
          "sign": -1,
          "start_exit_ms": 1764360000000,
          "end_exit_ms": 1764446400000,
          "exit_groups": 2,
          "origin_keys": [
            "1b899f0e0e9a043529d9ff3ea24e4737f7ecd88b972cdccc07476aef05e5e951",
            "f3a7f3359ee694f3f2ec72d0883e89ff8244c00ad0ba3ab05e8a8fdcfcff5a7c"
          ]
        },
        {
          "cohort_id": 64,
          "sign": 1,
          "start_exit_ms": 1764518400000,
          "end_exit_ms": 1764518400000,
          "exit_groups": 1,
          "origin_keys": [
            "0bdca7d41379168b140b2e66004f877e7ed16f1ec94ad27a829709e01d88dcfd"
          ]
        },
        {
          "cohort_id": 65,
          "sign": -1,
          "start_exit_ms": 1764547200000,
          "end_exit_ms": 1764936000000,
          "exit_groups": 3,
          "origin_keys": [
            "096bc697ee57acd04f69b2bdafa69304be268939fa6fc7ce3e7d4a153993239d",
            "50ef6567fbd7df3446b1349d46cc3248422d6ac0b97efc4a25c0e41078dd9fa2",
            "8f2deb5337fb114b9d57c7ffc9866b6a3147b0b3736a493d25f9408a2952de70",
            "96d5be021062d7510e93873bbad3117337da5ca3fc3a5d22dfde06c7a45223c4"
          ]
        },
        {
          "cohort_id": 66,
          "sign": 1,
          "start_exit_ms": 1765224000000,
          "end_exit_ms": 1765224000000,
          "exit_groups": 1,
          "origin_keys": [
            "0bb441638757d83417e5d34843eb3662cf34bc63b082e0543c9d4e6ea4c281a2"
          ]
        },
        {
          "cohort_id": 67,
          "sign": -1,
          "start_exit_ms": 1765339200000,
          "end_exit_ms": 1766534400000,
          "exit_groups": 5,
          "origin_keys": [
            "06f11cb99f29537c27c1e17dd06ab6fa36592086e512f419221fab219e69025c",
            "8db5e99d7b412ef451f5f40543f15fa63a61ce198466589c3f312ac65c581f6f",
            "98415b5f82bd3af2ba758b66c93c9918aecfd9d3b1cca6f1c99f5fd6b1981665",
            "98e92a785ee2e630812749980e5a0265365fb37533cd38ac8932dc77759b3137",
            "a97a1ea6fdb491a48099adef01ad75dd6269a7cf73b55ef7ec9f7155b6a56862",
            "71ad5943e5ee593a23085130ebed82c16fe5e4084605413d3843385d3ceec257",
            "87a932ea0171d6110434a232dfd49105d4d3f1260f570d604c5ae0bbec3f9d70",
            "a56600ae8b8d496db0b3245e50dbbde722769f7fb538e778fc707eb4974a8006",
            "b8f4efc9ce43a92fe22dcb9ccfd9832f3d5b18e624a147236e626f2f61a9b930",
            "7592b8b06b52feeb652ccc01853e62faecdb8115c0564457f76aeb2254d34000"
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

| Metric | M | M2 | KR1_FULL | FIXED | FULL |
|---|---:|---:|---:|---:|---:|
| closed_T | 75.000000 | 75.000000 | 74.000000 | 74.000000 | 74.000000 |
| open_T | 4.000000 | 4.000000 | 5.000000 | 5.000000 | 5.000000 |
| entries_T | 79.000000 | 79.000000 | 79.000000 | 79.000000 | 79.000000 |
| win_rate | 0.360000 | 0.346667 | 0.324324 | 0.324324 | 0.324324 |
| PF | 0.971311 | 1.038533 | 1.386200 | 1.344986 | 1.344986 |
| mean_win_bps | 498.934140 | 500.295916 | 726.622550 | 705.019003 | 705.019003 |
| mean_loss_bps | -288.939993 | -255.613491 | -251.607894 | -251.607894 | -251.607894 |
| realized_payoff | 1.726774 | 1.957236 | 2.887916 | 2.802054 | 2.802054 |
| net_expectancy_bps_per_closed_trade | -5.305305 | 6.435103 | 65.656034 | 58.649478 | 58.649478 |
| closed_gross_bps | 1202.411938 | 2062.403401 | 6507.134767 | 5959.189634 | 5959.189634 |
| closed_net_bps | -397.897894 | 482.632733 | 4858.546528 | 4340.061396 | 4340.061396 |
| closed_cost2x_net_bps | -1998.207726 | -1097.137935 | 3209.958290 | 2720.933158 | 2720.933158 |
| closed_cost_bps | 1600.309832 | 1579.770668 | 1648.588238 | 1619.128238 | 1619.128238 |
| closed_fee_bps | 750.000000 | 750.000000 | 740.000000 | 740.000000 | 740.000000 |
| closed_funding_bps | 497.510000 | 424.910000 | 519.520000 | 486.060000 | 486.060000 |
| terminal_net_bps_hypothetical | -1014.883491 | -134.352864 | 4414.411183 | 3895.926051 | 3895.926051 |
| terminal_cost2x_net_bps_hypothetical | -2695.193323 | -1794.123532 | 2660.132945 | 2171.107812 | 2171.107812 |
| open_net_mark_bps_hypothetical | -616.985597 | -616.985597 | -444.135345 | -444.135345 | -444.135345 |
| marked_DD_trade_sum_bps | 5643.864102 | 4260.361260 | 4409.680129 | 4576.353499 | 4576.353499 |
| grouped_max_loss_trade_sum_bps | 3758.309108 | 2665.353543 | 2665.353543 | 2665.353543 | 2665.353543 |
| exposure_symbol_days | 141.166667 | 119.833333 | 151.166667 | 140.666667 | 140.666667 |
| max_simultaneous_symbols | 7.000000 | 7.000000 | 7.000000 | 7.000000 | 7.000000 |
| entries_per_30_days | 19.750000 | 19.750000 | 19.750000 | 19.750000 | 19.750000 |
| max_completed_recovery_days | 85.000000 | 78.000000 | 78.000000 | 79.000000 | 79.000000 |
| open_underwater_days | 8.000000 | 8.000000 | 8.000000 | 8.000000 | 8.000000 |

Decisions: {"FIXED": "REJECT", "FULL": "REJECT"}

Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:

```json
{
  "effects": {
    "M": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 4955.3179480068175,
        "net_bps": 4910.809541481266,
        "cost2x_net_bps": 4866.301134955714,
        "cost_bps": 44.5084065255519,
        "fee_bps": 0.0,
        "spread_bps": 0.0,
        "impact_bps": 0.0,
        "slippage_bps": 0.0,
        "funding_bps": 1.2400000000000029,
        "frozen_floor_reserve_bps": 43.268406525551896
      },
      "transition_groups": {
        "C_C": {
          "T": 74,
          "delta_bps": {
            "gross_bps": 5325.934474096189,
            "net_bps": 5285.656067570637,
            "cost2x_net_bps": 5245.377661045085,
            "cost_bps": 40.2784065255519,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": -2.9899999999999975,
            "frozen_floor_reserve_bps": 43.268406525551896
          }
        },
        "C_O": {
          "T": 1,
          "delta_bps": {
            "gross_bps": -370.61652608937123,
            "net_bps": -374.8465260893712,
            "cost2x_net_bps": -379.07652608937127,
            "cost_bps": 4.23,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 4.23,
            "frozen_floor_reserve_bps": 0.0
          }
        },
        "O_O": {
          "T": 4,
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
        "T": 24,
        "parent_positive_bps": 8301.577494410176,
        "child_signed_terminal_bps": 7546.357847074025,
        "capped_terminal_preserved_bps_hypothetical": 6241.200015193773,
        "capped_terminal_retention_hypothetical": 0.7518089205812091,
        "realized_capped_retention_lower": 0.7309875463367218,
        "realized_capped_retention_upper": 0.7969625707569464,
        "profit_cut_bps": 2060.377479216402,
        "additional_loss_after_winner_bps": 113.88534219641485,
        "signed_winner_deterioration_bps": 2174.2628214128167,
        "winner_to_loss_T": 2,
        "winner_removed_T": 0,
        "winner_to_loss_origins": [
          "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782",
          "93dfc61c03a8525e14fface007825cb7ff83bfbf1335caa50d94ab17aee30bdc"
        ]
      },
      "large_winners": {
        "T": 3,
        "parent_positive_bps": 5169.644276112545,
        "child_signed_terminal_bps": 9433.063140226812,
        "capped_terminal_preserved_bps_hypothetical": 5169.644276112545,
        "capped_terminal_retention_hypothetical": 1.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "profit_cut_bps": 0.0,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
        "symbol": "HYPE-USDT",
        "signal_ts": 1778990400000,
        "entry_month": "2026-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 1258.5483186341562,
          "net_bps": 1237.0883186341562,
          "cost2x_net_bps": 1215.6283186341561,
          "cost_bps": 21.46,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 8.46,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 3382.5402065745425,
          "net_bps": 3352.6202065745424,
          "cost2x_net_bps": 3322.7002065745423,
          "cost_bps": 29.92,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 16.92,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 2123.9918879403863,
          "net_bps": 2115.5318879403862,
          "cost2x_net_bps": 2107.071887940386,
          "cost_bps": 8.46,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 8.46,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": true,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 172800000,
        "child_hold_ms": 345600000
      },
      "net_increment_without_largest_positive": 2795.27765354088,
      "largest_positive_share_of_net_increment": 0.4307908645347851,
      "increment_by_symbol": {
        "1000PEPE-USDT": -287.5887223216232,
        "BCH-USDT": 29.992878958958215,
        "HYPE-USDT": 4834.824478348426,
        "BTC-USDT": 38.96617641090805,
        "SOL-USDT": 637.7864072989207,
        "LINK-USDT": -483.23010304294615,
        "ETH-USDT": 140.05842582862226
      },
      "increment_by_entry_month": {
        "2026-07": -38.22507895399275,
        "2026-08": 1320.6185483388263,
        "2026-05": 2788.304663660553,
        "2026-06": 1214.9579345252505,
        "2026-09": -374.8465260893712
      },
      "parity": "PASS",
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "cost_saving_already_in_net": true,
      "post_outcome_diagnostic_only": true,
      "independent": false
    },
    "M2": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": 4095.3264844152404,
        "net_bps": 4030.2789145503575,
        "cost2x_net_bps": 3965.2313446854746,
        "cost_bps": 65.04756986488276,
        "fee_bps": 0.0,
        "spread_bps": 0.0,
        "impact_bps": 0.0,
        "slippage_bps": 0.0,
        "funding_bps": 73.84,
        "frozen_floor_reserve_bps": -8.792430135117243
      },
      "transition_groups": {
        "C_C": {
          "T": 74,
          "delta_bps": {
            "gross_bps": 4465.943010504611,
            "net_bps": 4405.125440639729,
            "cost2x_net_bps": 4344.307870774846,
            "cost_bps": 60.817569864882756,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 69.61,
            "frozen_floor_reserve_bps": -8.792430135117243
          }
        },
        "C_O": {
          "T": 1,
          "delta_bps": {
            "gross_bps": -370.61652608937123,
            "net_bps": -374.8465260893712,
            "cost2x_net_bps": -379.07652608937127,
            "cost_bps": 4.23,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": 4.23,
            "frozen_floor_reserve_bps": 0.0
          }
        },
        "O_O": {
          "T": 4,
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
        "T": 23,
        "parent_positive_bps": 7838.049528379601,
        "child_signed_terminal_bps": 7658.424804861506,
        "capped_terminal_preserved_bps_hypothetical": 6241.200015193773,
        "capped_terminal_retention_hypothetical": 0.7962695301421561,
        "realized_capped_retention_lower": 0.7742168177671092,
        "realized_capped_retention_upper": 0.8440934849069411,
        "profit_cut_bps": 1596.849513185828,
        "additional_loss_after_winner_bps": 1.8183844089337633,
        "signed_winner_deterioration_bps": 1598.6678975947618,
        "winner_to_loss_T": 1,
        "winner_removed_T": 0,
        "winner_to_loss_origins": [
          "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782"
        ]
      },
      "large_winners": {
        "T": 3,
        "parent_positive_bps": 5169.644276112545,
        "child_signed_terminal_bps": 9433.063140226812,
        "capped_terminal_preserved_bps_hypothetical": 5169.644276112545,
        "capped_terminal_retention_hypothetical": 1.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "profit_cut_bps": 0.0,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
        "symbol": "HYPE-USDT",
        "signal_ts": 1778990400000,
        "entry_month": "2026-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 1258.5483186341562,
          "net_bps": 1237.0883186341562,
          "cost2x_net_bps": 1215.6283186341561,
          "cost_bps": 21.46,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 8.46,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 3382.5402065745425,
          "net_bps": 3352.6202065745424,
          "cost2x_net_bps": 3322.7002065745423,
          "cost_bps": 29.92,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 16.92,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 2123.9918879403863,
          "net_bps": 2115.5318879403862,
          "cost2x_net_bps": 2107.071887940386,
          "cost_bps": 8.46,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 8.46,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": true,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 172800000,
        "child_hold_ms": 345600000
      },
      "net_increment_without_largest_positive": 1914.7470266099713,
      "largest_positive_share_of_net_increment": 0.5249095491388361,
      "increment_by_symbol": {
        "1000PEPE-USDT": 0.0,
        "BCH-USDT": -22.478094545060287,
        "HYPE-USDT": 3704.951513188515,
        "BTC-USDT": -143.9394679511089,
        "SOL-USDT": 782.0937590981407,
        "LINK-USDT": -198.06226470203563,
        "ETH-USDT": -92.28653053809344
      },
      "increment_by_entry_month": {
        "2026-07": -142.76795610121872,
        "2026-08": 1833.8885745387995,
        "2026-05": 3016.197012169862,
        "2026-06": -302.1921899677139,
        "2026-09": -374.8465260893712
      },
      "parity": "PASS",
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "cost_saving_already_in_net": true,
      "post_outcome_diagnostic_only": true,
      "independent": false
    },
    "KR1_FULL": {
      "all_origin_terminal_delta_bps": {
        "gross_bps": -547.9451327221674,
        "net_bps": -518.4851327221674,
        "cost2x_net_bps": -489.02513272216737,
        "cost_bps": -29.46,
        "fee_bps": 0.0,
        "spread_bps": 0.0,
        "impact_bps": 0.0,
        "slippage_bps": 0.0,
        "funding_bps": -33.46,
        "frozen_floor_reserve_bps": 4.0
      },
      "transition_groups": {
        "C_C": {
          "T": 74,
          "delta_bps": {
            "gross_bps": -547.9451327221674,
            "net_bps": -518.4851327221674,
            "cost2x_net_bps": -489.02513272216737,
            "cost_bps": -29.46,
            "fee_bps": 0.0,
            "spread_bps": 0.0,
            "impact_bps": 0.0,
            "slippage_bps": 0.0,
            "funding_bps": -33.46,
            "frozen_floor_reserve_bps": 4.0
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
        "T": 21,
        "parent_positive_bps": 8005.87807016188,
        "child_signed_terminal_bps": 7487.392937439712,
        "capped_terminal_preserved_bps_hypothetical": 6706.058421426779,
        "capped_terminal_retention_hypothetical": 0.8376418379915673,
        "realized_capped_retention_lower": 0.8376418379915673,
        "realized_capped_retention_upper": 0.8376418379915673,
        "profit_cut_bps": 1299.8196487351006,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 1299.8196487351006,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "large_winners": {
        "T": 3,
        "parent_positive_bps": 9433.063140226812,
        "child_signed_terminal_bps": 9433.063140226812,
        "capped_terminal_preserved_bps_hypothetical": 9433.063140226812,
        "capped_terminal_retention_hypothetical": 1.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "profit_cut_bps": 0.0,
        "additional_loss_after_winner_bps": 0.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_to_loss_T": 0,
        "winner_removed_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "origin_key": "2787c0350c5cf492e78a44da8ffdfe8b932312bd3576f427d9981014ff178768",
        "symbol": "HYPE-USDT",
        "signal_ts": 1779508800000,
        "entry_month": "2026-05",
        "transition": "C_C",
        "parent": {
          "gross_bps": 608.6334793100367,
          "net_bps": 582.9434793100367,
          "cost2x_net_bps": 557.2534793100367,
          "cost_bps": 25.69,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 12.690000000000001,
          "frozen_floor_reserve_bps": 0.0
        },
        "child": {
          "gross_bps": 929.8418089194738,
          "net_bps": 904.1518089194738,
          "cost2x_net_bps": 878.4618089194738,
          "cost_bps": 25.69,
          "fee_bps": 10.0,
          "spread_bps": 1.0,
          "impact_bps": 2.0,
          "slippage_bps": 0.0,
          "funding_bps": 12.690000000000001,
          "frozen_floor_reserve_bps": 0.0
        },
        "delta": {
          "gross_bps": 321.2083296094371,
          "net_bps": 321.2083296094371,
          "cost2x_net_bps": 321.2083296094371,
          "cost_bps": 0.0,
          "fee_bps": 0.0,
          "spread_bps": 0.0,
          "impact_bps": 0.0,
          "slippage_bps": 0.0,
          "funding_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0
        },
        "parent_large_winner": false,
        "parent_winner": true,
        "winner_to_loss": false,
        "winner_removed": false,
        "parent_hold_ms": 259200000,
        "child_hold_ms": 244800000
      },
      "net_increment_without_largest_positive": -839.6934623316045,
      "largest_positive_share_of_net_increment": -0.6195130956272917,
      "increment_by_symbol": {
        "1000PEPE-USDT": 0.0,
        "BCH-USDT": 55.19951349581165,
        "HYPE-USDT": 87.67431307524441,
        "BTC-USDT": 8.780154063337307,
        "SOL-USDT": -877.6306051087956,
        "LINK-USDT": 17.477721812083075,
        "ETH-USDT": 190.0137699401518
      },
      "increment_by_entry_month": {
        "2026-07": 329.75792683826387,
        "2026-08": -533.6629002050431,
        "2026-05": 321.2083296094371,
        "2026-06": -635.7884889648252,
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
      "fixed_path_or_filter_effect": -547.9451327221677,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -547.9451327221677
    },
    "net_bps": {
      "fixed_path_or_filter_effect": -518.4851327221677,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -518.4851327221677
    },
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": -489.0251327221672,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -489.0251327221672
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": -29.45999999999981,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -29.45999999999981
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": -33.460000000000036,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -33.460000000000036
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": 4.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 4.0
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
      "parent_marked_delta_sum_bps": 4414.411183273261,
      "child_marked_delta_sum_bps": 3895.926050551093,
      "child_minus_parent_marked_delta_sum_bps": -518.485132722168,
      "child_minus_parent_mean_daily_bps": -4.3207094393514005,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -16.20497558488921,
        7.002937883795623
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1944.597070186705,
        840.3525460554747
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
      "parent_marked_delta_sum_bps": 4414.411183273261,
      "child_marked_delta_sum_bps": 3895.926050551093,
      "child_minus_parent_marked_delta_sum_bps": -518.485132722168,
      "child_minus_parent_mean_daily_bps": -4.3207094393514005,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -16.20497558488921,
        7.002937883795623
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1944.597070186705,
        840.3525460554747
      ],
      "status": "COMPUTED",
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "independent": false,
      "partial_native_edge_buckets_included": true,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION"
    }
  },
  "concentration": {
    "M": {
      "profit": {
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 1336.7260291425532,
          "2026-06": -3400.22445518209,
          "2026-07": -862.1549921933814,
          "2026-08": 2724.054484327025,
          "2026-09": -196.298960037612
        },
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -2021.4638261171444,
          "BCH-USDT": -835.8577497629149,
          "BTC-USDT": -1013.9681694947367,
          "ETH-USDT": 63.737662545863145,
          "HYPE-USDT": 3297.500595881906,
          "LINK-USDT": -155.4263350039867,
          "SOL-USDT": 267.5799280075077
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 696.5971218110033,
          "BCH-USDT": 341.05028238142324,
          "BTC-USDT": 354.1964863071191,
          "ETH-USDT": 916.8824110542339,
          "HYPE-USDT": 6638.004439303006,
          "LINK-USDT": 1775.0642366652914,
          "SOL-USDT": 2749.426793000645
        },
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.38375467082166137,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.49275444739749336,
        "top_positive_month_share": 0.6708204187080186,
        "total_positive_trade_profit_bps": 13471.221770522721,
        "winner_T": 27
      },
      "market_event_weekly_clusters": [
        {
          "T": 1,
          "net_trade_sum_bps": 50.85453311490776,
          "utc_monday_ms": 1777852800000
        },
        {
          "T": 7,
          "net_trade_sum_bps": -1345.741011339072,
          "utc_monday_ms": 1778457600000
        },
        {
          "T": 1,
          "net_trade_sum_bps": 1237.0883186341562,
          "utc_monday_ms": 1779062400000
        },
        {
          "T": 3,
          "net_trade_sum_bps": 1394.5241887325615,
          "utc_monday_ms": 1779667200000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -1272.3098583569406,
          "utc_monday_ms": 1780272000000
        },
        {
          "T": 5,
          "net_trade_sum_bps": -2485.99924975154,
          "utc_monday_ms": 1781481600000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -92.12814307468227,
          "utc_monday_ms": 1782086400000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 176.61539541311112,
          "utc_monday_ms": 1782691200000
        },
        {
          "T": 10,
          "net_trade_sum_bps": -316.4480481826008,
          "utc_monday_ms": 1783296000000
        },
        {
          "T": 7,
          "net_trade_sum_bps": 413.38410348738756,
          "utc_monday_ms": 1783900800000
        },
        {
          "T": 7,
          "net_trade_sum_bps": -228.4218375755886,
          "utc_monday_ms": 1784505600000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -457.0718093346181,
          "utc_monday_ms": 1785110400000
        },
        {
          "T": 3,
          "net_trade_sum_bps": -26.62957415073241,
          "utc_monday_ms": 1785715200000
        },
        {
          "T": 6,
          "net_trade_sum_bps": 149.6644935593478,
          "utc_monday_ms": 1786320000000
        },
        {
          "T": 4,
          "net_trade_sum_bps": 3879.977773741749,
          "utc_monday_ms": 1786924800000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -1163.1995400986632,
          "utc_monday_ms": 1787529600000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -312.0576287622881,
          "utc_monday_ms": 1788134400000
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "end_exit_ms": 1778472000000,
          "exit_groups": 2,
          "origin_keys": [
            "dafa358fd6d72b028ca32eccaf37b64cf0f8d606e43cd843215c695ddf4ce30d",
            "54b968ba74f3b0748fe9b476247a26378ecd85a99f05bbd4e4de5e244c091cc0"
          ],
          "sign": 1,
          "start_exit_ms": 1778400000000
        },
        {
          "cohort_id": 1,
          "end_exit_ms": 1778817600000,
          "exit_groups": 5,
          "origin_keys": [
            "54aa08a8e20cfff2787cc4b6b325e4cdd3a7fa69c21b505ee70fbee8aac49ce8",
            "a68d8edf1a29c59f68fd3f5bcba84c940c821c4a58d01ee3402032015f4c9ff4",
            "a4feadb736502e81f108b5f7e93522f1fc442c5d91d6b5c216872fc68c116acd",
            "f3d1045f6c8a7a24de19e7d6d1827fe28c79578abfe3271af872406f2a9aeca8",
            "b139c8184981e16baba8d89e998d6b021c6a20bc6cffebb1d14d6adcf8aa97c6",
            "2232a44395250d67899755c9220e8f6f064dbf18967d68c222be3919851f2f13"
          ],
          "sign": -1,
          "start_exit_ms": 1778558400000
        },
        {
          "cohort_id": 2,
          "end_exit_ms": 1779681600000,
          "exit_groups": 2,
          "origin_keys": [
            "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
            "2787c0350c5cf492e78a44da8ffdfe8b932312bd3576f427d9981014ff178768"
          ],
          "sign": 1,
          "start_exit_ms": 1779163200000
        },
        {
          "cohort_id": 3,
          "end_exit_ms": 1779969600000,
          "exit_groups": 1,
          "origin_keys": [
            "50b807bef744a52955bcca34b4f5801627a78a04bccb1bfb201cfda6d3d4a777"
          ],
          "sign": -1,
          "start_exit_ms": 1779969600000
        },
        {
          "cohort_id": 4,
          "end_exit_ms": 1780171200000,
          "exit_groups": 1,
          "origin_keys": [
            "0abc7cc780daa8ce66694c8bccae6e042dd3e38f893b9b18a6d1783a9f52d213"
          ],
          "sign": 1,
          "start_exit_ms": 1780171200000
        },
        {
          "cohort_id": 5,
          "end_exit_ms": 1782057600000,
          "exit_groups": 6,
          "origin_keys": [
            "ae6b7b9caaa58babcc9fcc1bc4b2cee66f1adc18cebb57d3811d2fb5463027a7",
            "619e768742c15c76ee70c1212b0b15ffd2c77e18c8237d51ec2c3e1870e27c86",
            "8b66516f43666f0af8ca73955c4ba0ce47c6289413ceb6b2d1b74b4e52acf280",
            "756357e369270b8141b1294beab84ed68db5b2afd5e8a94eaae99d36dd4f532d",
            "9b48ab43e36323daf1b28a7593a1eec3df8e2207f1c82e74b99c679ba2c22323",
            "9a0d851b807312b4cd8e8a2717944d7d4712726ab3cfa08b9a0e1bbaef13af66"
          ],
          "sign": -1,
          "start_exit_ms": 1780632000000
        },
        {
          "cohort_id": 6,
          "end_exit_ms": 1782115200000,
          "exit_groups": 1,
          "origin_keys": [
            "8b2cf1ec4a983969bec012213fff13788b44c092e5ba7a2f90b1c5d9c4678d34"
          ],
          "sign": 1,
          "start_exit_ms": 1782115200000
        },
        {
          "cohort_id": 7,
          "end_exit_ms": 1782216000000,
          "exit_groups": 1,
          "origin_keys": [
            "2ce471f09edb704478b719eb9fdd6f4d5de1714d1e7dba1b6a56fcb54337c83c"
          ],
          "sign": -1,
          "start_exit_ms": 1782216000000
        },
        {
          "cohort_id": 8,
          "end_exit_ms": 1782792000000,
          "exit_groups": 1,
          "origin_keys": [
            "962f9283dc72ebb8cde3d9e0c593e37fb697e91eee5c09c8621ad854178a7630"
          ],
          "sign": 1,
          "start_exit_ms": 1782792000000
        },
        {
          "cohort_id": 9,
          "end_exit_ms": 1783598400000,
          "exit_groups": 3,
          "origin_keys": [
            "f826a228ca45502fa67f3e7a6e6d7ee11336a63e7b5aeddb3e8f297993765312",
            "15ae8dc0ab4390da0278ef1b62bd74ff1ca4e9740f168e753171672c3ea593f1",
            "63d5711bd8e789167e03fc120f8a17294ea157d5724e2fd8f7dad342b093ed3f",
            "aacf3707686f90a2ab2f52fed2b918e3b6c0e38da45c7bf425917f0ca48495e9"
          ],
          "sign": -1,
          "start_exit_ms": 1782936000000
        },
        {
          "cohort_id": 10,
          "end_exit_ms": 1783670400000,
          "exit_groups": 1,
          "origin_keys": [
            "2b38504c380f0ce399ecfad56506edeff49119e8d6bec3b139be77a3c3d92006"
          ],
          "sign": 1,
          "start_exit_ms": 1783670400000
        },
        {
          "cohort_id": 11,
          "end_exit_ms": 1783728000000,
          "exit_groups": 1,
          "origin_keys": [
            "71f9c504b36da1bd0767f40a73abe13d2b1773433011d03dfc27642a372df1ad",
            "c845106fe6307ad59e5d7f481d3995fc9a25ffce7720a19b27bb765ec98f78fd"
          ],
          "sign": -1,
          "start_exit_ms": 1783728000000
        },
        {
          "cohort_id": 12,
          "end_exit_ms": 1783828800000,
          "exit_groups": 3,
          "origin_keys": [
            "06e7d93e8dbc7b0caa092915e4dc54aa6c402b8d13c9255035b9d33e494a6dd9",
            "65605dadb017905b3f7e20717019fade3b6a980661bbf009fbc142950270aa9b",
            "6799663cf96705b99cb17e39b93b93883ed7c06349b33a6f79d53d14f3229c74",
            "968e327f0605a840e11db55796bb26798903f1538cbd7a61717a126227e87f62"
          ],
          "sign": 1,
          "start_exit_ms": 1783756800000
        },
        {
          "cohort_id": 13,
          "end_exit_ms": 1784030400000,
          "exit_groups": 2,
          "origin_keys": [
            "de2fd35bd7d208c609912e7554cbea80e5c8b22c329d552a49e4329a2ddd1ed0",
            "de917e9e79772496d3e24a0cc8351bb306f4a644776903b39ca577854125b8a8"
          ],
          "sign": -1,
          "start_exit_ms": 1784001600000
        },
        {
          "cohort_id": 14,
          "end_exit_ms": 1784203200000,
          "exit_groups": 1,
          "origin_keys": [
            "42266ad29ddca70b313d0b39e336944ce72dba1f27d9e357b7c80030ecf4b97e",
            "6681a5caea361e92b02a4d9193b908f79dfe91f2776bfa31f1b3b7da1abe0a67"
          ],
          "sign": 1,
          "start_exit_ms": 1784203200000
        },
        {
          "cohort_id": 15,
          "end_exit_ms": 1784217600000,
          "exit_groups": 1,
          "origin_keys": [
            "013696a18ca39b51a8245b74518f9d2a58dee13996ab9016496c7ad21d58ead5",
            "26c7a35a019f91a6ae5894960175e7db3f8cefbb6758dfbdda245c87379af569"
          ],
          "sign": -1,
          "start_exit_ms": 1784217600000
        },
        {
          "cohort_id": 16,
          "end_exit_ms": 1784721600000,
          "exit_groups": 4,
          "origin_keys": [
            "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782",
            "93dfc61c03a8525e14fface007825cb7ff83bfbf1335caa50d94ab17aee30bdc",
            "cc82551910becb2ad68371a1b3a10e04d67a710d5de33ae05db11dc9f013f668",
            "b4b54f33da070c5a2b107b71d85233ecb1d9c72ab1fd090b44d7d5b9132e4f58",
            "13c4486cfd2eed83fdb4b21fc1f8f8d68db13cf14b7c9a6b1cb12f7895e15e0f"
          ],
          "sign": 1,
          "start_exit_ms": 1784491200000
        },
        {
          "cohort_id": 17,
          "end_exit_ms": 1786449600000,
          "exit_groups": 11,
          "origin_keys": [
            "1af94576f2cea51c8aeb8c36c975918cee22ea5bc4ea92e554246be1e6d7a127",
            "7a906d846ccb4308f54f14e0761cf09f7f670c78fdff33aa78dc11ccb770bb0b",
            "43b476ac4ac38af2e843d981583c1cc540442dfef5eb82ab503a6d9368b890b2",
            "3ad115aa9c72b11be73f3f89e82a83a8ab2b991a9c701340de98e7e796740e27",
            "97b143bc5b5ed7b17bf78597ae4e633cefc3a42a07c5ed9a169fa4af476a35b4",
            "c13b68c9e68bf23173d9fd098c2b34843f61d584a6c06eb9d39c23a7a4a8c32b",
            "6320bc05ba8fe5e201115c6a1426cd5e8237575566b79307f4a42ea4874f6f5e",
            "acfca04dd278b6bf61e3ba9a18c2bfe11b7d216dba6de190059b5be8a753a992",
            "38ba18c10c721df47c7ef7da72cfc453857ef94be5709487ca191dea13b337ce",
            "a2b05143ce6d7640252b05e5b7cec8092489491c9a5d60ed773715357d5d1270",
            "cc4bcf0271d48c707a7f20905e89386e7809e7a8e6656c49172474682459e6cc",
            "04f043c401d6de0a723172f94ce77f53f216b41a2c7764a07fbfafe7d25c1b90"
          ],
          "sign": -1,
          "start_exit_ms": 1784880000000
        },
        {
          "cohort_id": 18,
          "end_exit_ms": 1786536000000,
          "exit_groups": 1,
          "origin_keys": [
            "356b3f003fd56d9d6ad5a5e5c3d7973dd84b86d0aa002131811fa409e9817aa8"
          ],
          "sign": 1,
          "start_exit_ms": 1786536000000
        },
        {
          "cohort_id": 19,
          "end_exit_ms": 1786924800000,
          "exit_groups": 4,
          "origin_keys": [
            "9f8e2e26ed410b93656c69f6043e97778577d2fa5c0169e089ca36c0a137de7e",
            "2f440a0c3fa704ef7d28c95044dd753eb0b733c4bbb9917fd2662aafec8fdf45",
            "9ecd714cc633db0047602f722ab967fbfc72c42feb26833f383a3bedb343f2bb",
            "e61dc3626e169b8820e5825f4c028311607ad156e07490946412f789df74e5ba",
            "ebf7543c7ec608f421e7fba452d6da10de0a36a2e77d1ff5b8842c606aab58ea"
          ],
          "sign": -1,
          "start_exit_ms": 1786550400000
        },
        {
          "cohort_id": 20,
          "end_exit_ms": 1787947200000,
          "exit_groups": 4,
          "origin_keys": [
            "c9052be83a5788a6ba745823a4bf0147dde04deeb2d8b391feb7a0eabaad5ac1",
            "fbeada1abd3295ce40c13a3b978128232e4a1a4c741e75bb0a5cbbeb90832a02",
            "66b48055595e32540059dd7581a1c98154cbd3e8cb9bc0f7c7eded4d36b06634",
            "789d5e159a5a23a24ab065114446b96d4eeb6796049b97b9fc327573dca75002",
            "ff0ff86e7ecfe93c02186f61edd57f38d259e17c8d249038e9c77397a47d88db"
          ],
          "sign": 1,
          "start_exit_ms": 1787212800000
        },
        {
          "cohort_id": 21,
          "end_exit_ms": 1788408000000,
          "exit_groups": 5,
          "origin_keys": [
            "1bd838219fe26f37a91250f207fd090e9991c6f479038fe1e8fa708d2ede810e",
            "644115547aee472e42b7bf88ea31bffe83df59e6869a826ab5be5022cd22435a",
            "96c8b29888f69f723c7f604035d0ed3098bd52d26b8eb73cb5fd9e0da79309c1",
            "056de4242b3e2706b5e09330a43084fd84bf1eaf43609e14fad35fd8e80c5e25",
            "3a0dd213596625a304559ef7f5ee287e3ca9da6350729310a19ae8cc9609691c",
            "778b8b9aec9a5244631fd0384759de29d52303397bfe54705eb09db48a8aa788",
            "7ad3e943d2db184816904b595059ba414f078a7261744f373b0646995e89df1d",
            "ec364875f0ba137c532fe352a6bd74a254e375843d76806feb62beedd4109d19"
          ],
          "sign": -1,
          "start_exit_ms": 1787961600000
        },
        {
          "cohort_id": 22,
          "end_exit_ms": 1788480000000,
          "exit_groups": 1,
          "origin_keys": [
            "e8c589146cdb1cbe7e03cb2cc50877f46166fadee59afb758fa1d3ab2c47861c"
          ],
          "sign": 1,
          "start_exit_ms": 1788480000000
        }
      ]
    },
    "M2": {
      "profit": {
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 1108.8336806332445,
          "2026-06": -1883.0743306891256,
          "2026-07": -757.6121150461556,
          "2026-08": 1923.5306609787363,
          "2026-09": 90.95483711070369
        },
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -2309.0525484387676,
          "BCH-USDT": -783.3867762588964,
          "BTC-USDT": -831.0625251327197,
          "ETH-USDT": 296.0826189125789,
          "HYPE-USDT": 4427.373561041817,
          "LINK-USDT": -440.59417334489746,
          "SOL-USDT": 123.27257620828772
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 233.06915578042924,
          "BCH-USDT": 341.05028238142324,
          "BTC-USDT": 354.1964863071191,
          "ETH-USDT": 916.8824110542339,
          "HYPE-USDT": 6638.004439303006,
          "LINK-USDT": 1775.0642366652914,
          "SOL-USDT": 2749.426793000645
        },
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.397429733034401,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.5103137065703839,
        "top_positive_month_share": 0.6158610602728682,
        "total_positive_trade_profit_bps": 13007.693804492146,
        "winner_T": 26
      },
      "market_event_weekly_clusters": [
        {
          "T": 1,
          "net_trade_sum_bps": 50.85453311490776,
          "utc_monday_ms": 1777852800000
        },
        {
          "T": 7,
          "net_trade_sum_bps": -1573.633359848381,
          "utc_monday_ms": 1778457600000
        },
        {
          "T": 1,
          "net_trade_sum_bps": 1237.0883186341562,
          "utc_monday_ms": 1779062400000
        },
        {
          "T": 3,
          "net_trade_sum_bps": 1394.5241887325615,
          "utc_monday_ms": 1779667200000
        },
        {
          "T": 1,
          "net_trade_sum_bps": -411.9263456090649,
          "utc_monday_ms": 1780272000000
        },
        {
          "T": 5,
          "net_trade_sum_bps": -2096.5953147548585,
          "utc_monday_ms": 1781481600000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 175.2345336737249,
          "utc_monday_ms": 1782086400000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 176.61539541311112,
          "utc_monday_ms": 1782691200000
        },
        {
          "T": 10,
          "net_trade_sum_bps": -76.73884295615477,
          "utc_monday_ms": 1783296000000
        },
        {
          "T": 8,
          "net_trade_sum_bps": 301.3171456999065,
          "utc_monday_ms": 1783900800000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -361.64230856712595,
          "utc_monday_ms": 1784505600000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -346.9507086348198,
          "utc_monday_ms": 1785110400000
        },
        {
          "T": 3,
          "net_trade_sum_bps": -46.757355466507406,
          "utc_monday_ms": 1785715200000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -18.518798177642978,
          "utc_monday_ms": 1786320000000
        },
        {
          "T": 4,
          "net_trade_sum_bps": 3879.977773741749,
          "utc_monday_ms": 1786924800000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -1110.7285665946447,
          "utc_monday_ms": 1787529600000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -689.4875554135141,
          "utc_monday_ms": 1788134400000
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "end_exit_ms": 1778400000000,
          "exit_groups": 1,
          "origin_keys": [
            "dafa358fd6d72b028ca32eccaf37b64cf0f8d606e43cd843215c695ddf4ce30d"
          ],
          "sign": 1,
          "start_exit_ms": 1778400000000
        },
        {
          "cohort_id": 1,
          "end_exit_ms": 1778688000000,
          "exit_groups": 4,
          "origin_keys": [
            "54b968ba74f3b0748fe9b476247a26378ecd85a99f05bbd4e4de5e244c091cc0",
            "a68d8edf1a29c59f68fd3f5bcba84c940c821c4a58d01ee3402032015f4c9ff4",
            "54aa08a8e20cfff2787cc4b6b325e4cdd3a7fa69c21b505ee70fbee8aac49ce8",
            "a4feadb736502e81f108b5f7e93522f1fc442c5d91d6b5c216872fc68c116acd",
            "f3d1045f6c8a7a24de19e7d6d1827fe28c79578abfe3271af872406f2a9aeca8",
            "2232a44395250d67899755c9220e8f6f064dbf18967d68c222be3919851f2f13",
            "b139c8184981e16baba8d89e998d6b021c6a20bc6cffebb1d14d6adcf8aa97c6"
          ],
          "sign": -1,
          "start_exit_ms": 1778472000000
        },
        {
          "cohort_id": 2,
          "end_exit_ms": 1779681600000,
          "exit_groups": 2,
          "origin_keys": [
            "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
            "2787c0350c5cf492e78a44da8ffdfe8b932312bd3576f427d9981014ff178768"
          ],
          "sign": 1,
          "start_exit_ms": 1779163200000
        },
        {
          "cohort_id": 3,
          "end_exit_ms": 1779969600000,
          "exit_groups": 1,
          "origin_keys": [
            "50b807bef744a52955bcca34b4f5801627a78a04bccb1bfb201cfda6d3d4a777"
          ],
          "sign": -1,
          "start_exit_ms": 1779969600000
        },
        {
          "cohort_id": 4,
          "end_exit_ms": 1780171200000,
          "exit_groups": 1,
          "origin_keys": [
            "0abc7cc780daa8ce66694c8bccae6e042dd3e38f893b9b18a6d1783a9f52d213"
          ],
          "sign": 1,
          "start_exit_ms": 1780171200000
        },
        {
          "cohort_id": 5,
          "end_exit_ms": 1782086400000,
          "exit_groups": 6,
          "origin_keys": [
            "ae6b7b9caaa58babcc9fcc1bc4b2cee66f1adc18cebb57d3811d2fb5463027a7",
            "619e768742c15c76ee70c1212b0b15ffd2c77e18c8237d51ec2c3e1870e27c86",
            "8b66516f43666f0af8ca73955c4ba0ce47c6289413ceb6b2d1b74b4e52acf280",
            "756357e369270b8141b1294beab84ed68db5b2afd5e8a94eaae99d36dd4f532d",
            "9b48ab43e36323daf1b28a7593a1eec3df8e2207f1c82e74b99c679ba2c22323",
            "9a0d851b807312b4cd8e8a2717944d7d4712726ab3cfa08b9a0e1bbaef13af66",
            "2ce471f09edb704478b719eb9fdd6f4d5de1714d1e7dba1b6a56fcb54337c83c"
          ],
          "sign": -1,
          "start_exit_ms": 1780560000000
        },
        {
          "cohort_id": 6,
          "end_exit_ms": 1782792000000,
          "exit_groups": 2,
          "origin_keys": [
            "8b2cf1ec4a983969bec012213fff13788b44c092e5ba7a2f90b1c5d9c4678d34",
            "962f9283dc72ebb8cde3d9e0c593e37fb697e91eee5c09c8621ad854178a7630"
          ],
          "sign": 1,
          "start_exit_ms": 1782115200000
        },
        {
          "cohort_id": 7,
          "end_exit_ms": 1783598400000,
          "exit_groups": 4,
          "origin_keys": [
            "f826a228ca45502fa67f3e7a6e6d7ee11336a63e7b5aeddb3e8f297993765312",
            "63d5711bd8e789167e03fc120f8a17294ea157d5724e2fd8f7dad342b093ed3f",
            "15ae8dc0ab4390da0278ef1b62bd74ff1ca4e9740f168e753171672c3ea593f1",
            "aacf3707686f90a2ab2f52fed2b918e3b6c0e38da45c7bf425917f0ca48495e9"
          ],
          "sign": -1,
          "start_exit_ms": 1782936000000
        },
        {
          "cohort_id": 8,
          "end_exit_ms": 1783670400000,
          "exit_groups": 1,
          "origin_keys": [
            "2b38504c380f0ce399ecfad56506edeff49119e8d6bec3b139be77a3c3d92006"
          ],
          "sign": 1,
          "start_exit_ms": 1783670400000
        },
        {
          "cohort_id": 9,
          "end_exit_ms": 1783728000000,
          "exit_groups": 1,
          "origin_keys": [
            "71f9c504b36da1bd0767f40a73abe13d2b1773433011d03dfc27642a372df1ad",
            "c845106fe6307ad59e5d7f481d3995fc9a25ffce7720a19b27bb765ec98f78fd"
          ],
          "sign": -1,
          "start_exit_ms": 1783728000000
        },
        {
          "cohort_id": 10,
          "end_exit_ms": 1783828800000,
          "exit_groups": 3,
          "origin_keys": [
            "06e7d93e8dbc7b0caa092915e4dc54aa6c402b8d13c9255035b9d33e494a6dd9",
            "65605dadb017905b3f7e20717019fade3b6a980661bbf009fbc142950270aa9b",
            "6799663cf96705b99cb17e39b93b93883ed7c06349b33a6f79d53d14f3229c74",
            "968e327f0605a840e11db55796bb26798903f1538cbd7a61717a126227e87f62"
          ],
          "sign": 1,
          "start_exit_ms": 1783756800000
        },
        {
          "cohort_id": 11,
          "end_exit_ms": 1784030400000,
          "exit_groups": 2,
          "origin_keys": [
            "de2fd35bd7d208c609912e7554cbea80e5c8b22c329d552a49e4329a2ddd1ed0",
            "de917e9e79772496d3e24a0cc8351bb306f4a644776903b39ca577854125b8a8"
          ],
          "sign": -1,
          "start_exit_ms": 1784001600000
        },
        {
          "cohort_id": 12,
          "end_exit_ms": 1784203200000,
          "exit_groups": 1,
          "origin_keys": [
            "42266ad29ddca70b313d0b39e336944ce72dba1f27d9e357b7c80030ecf4b97e",
            "6681a5caea361e92b02a4d9193b908f79dfe91f2776bfa31f1b3b7da1abe0a67"
          ],
          "sign": 1,
          "start_exit_ms": 1784203200000
        },
        {
          "cohort_id": 13,
          "end_exit_ms": 1784361600000,
          "exit_groups": 2,
          "origin_keys": [
            "013696a18ca39b51a8245b74518f9d2a58dee13996ab9016496c7ad21d58ead5",
            "26c7a35a019f91a6ae5894960175e7db3f8cefbb6758dfbdda245c87379af569",
            "93dfc61c03a8525e14fface007825cb7ff83bfbf1335caa50d94ab17aee30bdc"
          ],
          "sign": -1,
          "start_exit_ms": 1784217600000
        },
        {
          "cohort_id": 14,
          "end_exit_ms": 1784721600000,
          "exit_groups": 4,
          "origin_keys": [
            "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782",
            "cc82551910becb2ad68371a1b3a10e04d67a710d5de33ae05db11dc9f013f668",
            "b4b54f33da070c5a2b107b71d85233ecb1d9c72ab1fd090b44d7d5b9132e4f58",
            "13c4486cfd2eed83fdb4b21fc1f8f8d68db13cf14b7c9a6b1cb12f7895e15e0f"
          ],
          "sign": 1,
          "start_exit_ms": 1784491200000
        },
        {
          "cohort_id": 15,
          "end_exit_ms": 1786132800000,
          "exit_groups": 7,
          "origin_keys": [
            "1af94576f2cea51c8aeb8c36c975918cee22ea5bc4ea92e554246be1e6d7a127",
            "7a906d846ccb4308f54f14e0761cf09f7f670c78fdff33aa78dc11ccb770bb0b",
            "43b476ac4ac38af2e843d981583c1cc540442dfef5eb82ab503a6d9368b890b2",
            "3ad115aa9c72b11be73f3f89e82a83a8ab2b991a9c701340de98e7e796740e27",
            "c13b68c9e68bf23173d9fd098c2b34843f61d584a6c06eb9d39c23a7a4a8c32b",
            "97b143bc5b5ed7b17bf78597ae4e633cefc3a42a07c5ed9a169fa4af476a35b4",
            "6320bc05ba8fe5e201115c6a1426cd5e8237575566b79307f4a42ea4874f6f5e",
            "acfca04dd278b6bf61e3ba9a18c2bfe11b7d216dba6de190059b5be8a753a992",
            "a2b05143ce6d7640252b05e5b7cec8092489491c9a5d60ed773715357d5d1270"
          ],
          "sign": -1,
          "start_exit_ms": 1784822400000
        },
        {
          "cohort_id": 16,
          "end_exit_ms": 1786204800000,
          "exit_groups": 1,
          "origin_keys": [
            "38ba18c10c721df47c7ef7da72cfc453857ef94be5709487ca191dea13b337ce"
          ],
          "sign": 1,
          "start_exit_ms": 1786204800000
        },
        {
          "cohort_id": 17,
          "end_exit_ms": 1786464000000,
          "exit_groups": 3,
          "origin_keys": [
            "cc4bcf0271d48c707a7f20905e89386e7809e7a8e6656c49172474682459e6cc",
            "04f043c401d6de0a723172f94ce77f53f216b41a2c7764a07fbfafe7d25c1b90",
            "2f440a0c3fa704ef7d28c95044dd753eb0b733c4bbb9917fd2662aafec8fdf45"
          ],
          "sign": -1,
          "start_exit_ms": 1786435200000
        },
        {
          "cohort_id": 18,
          "end_exit_ms": 1786536000000,
          "exit_groups": 1,
          "origin_keys": [
            "356b3f003fd56d9d6ad5a5e5c3d7973dd84b86d0aa002131811fa409e9817aa8"
          ],
          "sign": 1,
          "start_exit_ms": 1786536000000
        },
        {
          "cohort_id": 19,
          "end_exit_ms": 1786924800000,
          "exit_groups": 3,
          "origin_keys": [
            "9f8e2e26ed410b93656c69f6043e97778577d2fa5c0169e089ca36c0a137de7e",
            "9ecd714cc633db0047602f722ab967fbfc72c42feb26833f383a3bedb343f2bb",
            "e61dc3626e169b8820e5825f4c028311607ad156e07490946412f789df74e5ba",
            "ebf7543c7ec608f421e7fba452d6da10de0a36a2e77d1ff5b8842c606aab58ea"
          ],
          "sign": -1,
          "start_exit_ms": 1786550400000
        },
        {
          "cohort_id": 20,
          "end_exit_ms": 1787889600000,
          "exit_groups": 3,
          "origin_keys": [
            "c9052be83a5788a6ba745823a4bf0147dde04deeb2d8b391feb7a0eabaad5ac1",
            "fbeada1abd3295ce40c13a3b978128232e4a1a4c741e75bb0a5cbbeb90832a02",
            "66b48055595e32540059dd7581a1c98154cbd3e8cb9bc0f7c7eded4d36b06634"
          ],
          "sign": 1,
          "start_exit_ms": 1787212800000
        },
        {
          "cohort_id": 21,
          "end_exit_ms": 1787932800000,
          "exit_groups": 1,
          "origin_keys": [
            "1bd838219fe26f37a91250f207fd090e9991c6f479038fe1e8fa708d2ede810e"
          ],
          "sign": -1,
          "start_exit_ms": 1787932800000
        },
        {
          "cohort_id": 22,
          "end_exit_ms": 1787947200000,
          "exit_groups": 1,
          "origin_keys": [
            "789d5e159a5a23a24ab065114446b96d4eeb6796049b97b9fc327573dca75002",
            "ff0ff86e7ecfe93c02186f61edd57f38d259e17c8d249038e9c77397a47d88db"
          ],
          "sign": 1,
          "start_exit_ms": 1787947200000
        },
        {
          "cohort_id": 23,
          "end_exit_ms": 1788408000000,
          "exit_groups": 6,
          "origin_keys": [
            "644115547aee472e42b7bf88ea31bffe83df59e6869a826ab5be5022cd22435a",
            "96c8b29888f69f723c7f604035d0ed3098bd52d26b8eb73cb5fd9e0da79309c1",
            "3a0dd213596625a304559ef7f5ee287e3ca9da6350729310a19ae8cc9609691c",
            "7ad3e943d2db184816904b595059ba414f078a7261744f373b0646995e89df1d",
            "056de4242b3e2706b5e09330a43084fd84bf1eaf43609e14fad35fd8e80c5e25",
            "778b8b9aec9a5244631fd0384759de29d52303397bfe54705eb09db48a8aa788",
            "ec364875f0ba137c532fe352a6bd74a254e375843d76806feb62beedd4109d19"
          ],
          "sign": -1,
          "start_exit_ms": 1787961600000
        },
        {
          "cohort_id": 24,
          "end_exit_ms": 1788480000000,
          "exit_groups": 1,
          "origin_keys": [
            "e8c589146cdb1cbe7e03cb2cc50877f46166fadee59afb758fa1d3ab2c47861c"
          ],
          "sign": 1,
          "start_exit_ms": 1788480000000
        }
      ]
    },
    "KR1_FULL": {
      "profit": {
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 1725.5517744951076,
          "2026-06": -557.2087279593504,
          "2026-07": -144.13671301974028,
          "2026-08": 4291.082135722579,
          "2026-09": -456.74194080939526
        },
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -2309.0525484387676,
          "BCH-USDT": -861.0643842997683,
          "BTC-USDT": -983.7821471471657,
          "ETH-USDT": 13.782318434333718,
          "HYPE-USDT": 7871.800509324362,
          "LINK-USDT": -656.1341598590161,
          "SOL-USDT": 1782.996940415224
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 233.06915578042924,
          "BCH-USDT": 263.3726743405513,
          "BTC-USDT": 203.2952487016066,
          "ETH-USDT": 688.0973366218016,
          "HYPE-USDT": 10082.431387585548,
          "LINK-USDT": 1559.524250151173,
          "SOL-USDT": 4409.151157207581
        },
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.540919487394531,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.5781561659018187,
        "top_positive_month_share": 0.7132031298157085,
        "total_positive_trade_profit_bps": 17438.94121038869,
        "winner_T": 24
      },
      "market_event_weekly_clusters": [
        {
          "T": 1,
          "net_trade_sum_bps": 50.85453311490776,
          "utc_monday_ms": 1777852800000
        },
        {
          "T": 7,
          "net_trade_sum_bps": -1573.633359848381,
          "utc_monday_ms": 1778457600000
        },
        {
          "T": 1,
          "net_trade_sum_bps": 3352.6202065745424,
          "utc_monday_ms": 1779062400000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -104.28960534596172,
          "utc_monday_ms": 1779667200000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 1666.344243089497,
          "utc_monday_ms": 1780272000000
        },
        {
          "T": 5,
          "net_trade_sum_bps": -2096.5953147548585,
          "utc_monday_ms": 1781481600000
        },
        {
          "T": 2,
          "net_trade_sum_bps": -126.95765629398899,
          "utc_monday_ms": 1782086400000
        },
        {
          "T": 2,
          "net_trade_sum_bps": 812.4038843779363,
          "utc_monday_ms": 1782691200000
        },
        {
          "T": 8,
          "net_trade_sum_bps": -595.5107849177698,
          "utc_monday_ms": 1783296000000
        },
        {
          "T": 9,
          "net_trade_sum_bps": 52.535524032712175,
          "utc_monday_ms": 1783900800000
        },
        {
          "T": 7,
          "net_trade_sum_bps": -13.099401831986452,
          "utc_monday_ms": 1784505600000
        },
        {
          "T": 4,
          "net_trade_sum_bps": -400.46593468063253,
          "utc_monday_ms": 1785110400000
        },
        {
          "T": 3,
          "net_trade_sum_bps": -167.1160171356284,
          "utc_monday_ms": 1785715200000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -78.70302454730081,
          "utc_monday_ms": 1786320000000
        },
        {
          "T": 4,
          "net_trade_sum_bps": 6261.398766449821,
          "utc_monday_ms": 1786924800000
        },
        {
          "T": 6,
          "net_trade_sum_bps": -944.055196520095,
          "utc_monday_ms": 1787529600000
        },
        {
          "T": 5,
          "net_trade_sum_bps": -1237.184333333613,
          "utc_monday_ms": 1788134400000
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "end_exit_ms": 1778400000000,
          "exit_groups": 1,
          "origin_keys": [
            "dafa358fd6d72b028ca32eccaf37b64cf0f8d606e43cd843215c695ddf4ce30d"
          ],
          "sign": 1,
          "start_exit_ms": 1778400000000
        },
        {
          "cohort_id": 1,
          "end_exit_ms": 1778688000000,
          "exit_groups": 4,
          "origin_keys": [
            "54b968ba74f3b0748fe9b476247a26378ecd85a99f05bbd4e4de5e244c091cc0",
            "a68d8edf1a29c59f68fd3f5bcba84c940c821c4a58d01ee3402032015f4c9ff4",
            "54aa08a8e20cfff2787cc4b6b325e4cdd3a7fa69c21b505ee70fbee8aac49ce8",
            "a4feadb736502e81f108b5f7e93522f1fc442c5d91d6b5c216872fc68c116acd",
            "f3d1045f6c8a7a24de19e7d6d1827fe28c79578abfe3271af872406f2a9aeca8",
            "2232a44395250d67899755c9220e8f6f064dbf18967d68c222be3919851f2f13",
            "b139c8184981e16baba8d89e998d6b021c6a20bc6cffebb1d14d6adcf8aa97c6"
          ],
          "sign": -1,
          "start_exit_ms": 1778472000000
        },
        {
          "cohort_id": 2,
          "end_exit_ms": 1779768000000,
          "exit_groups": 2,
          "origin_keys": [
            "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
            "2787c0350c5cf492e78a44da8ffdfe8b932312bd3576f427d9981014ff178768"
          ],
          "sign": 1,
          "start_exit_ms": 1779336000000
        },
        {
          "cohort_id": 3,
          "end_exit_ms": 1779969600000,
          "exit_groups": 1,
          "origin_keys": [
            "50b807bef744a52955bcca34b4f5801627a78a04bccb1bfb201cfda6d3d4a777"
          ],
          "sign": -1,
          "start_exit_ms": 1779969600000
        },
        {
          "cohort_id": 4,
          "end_exit_ms": 1780344000000,
          "exit_groups": 1,
          "origin_keys": [
            "0abc7cc780daa8ce66694c8bccae6e042dd3e38f893b9b18a6d1783a9f52d213"
          ],
          "sign": 1,
          "start_exit_ms": 1780344000000
        },
        {
          "cohort_id": 5,
          "end_exit_ms": 1782086400000,
          "exit_groups": 6,
          "origin_keys": [
            "ae6b7b9caaa58babcc9fcc1bc4b2cee66f1adc18cebb57d3811d2fb5463027a7",
            "619e768742c15c76ee70c1212b0b15ffd2c77e18c8237d51ec2c3e1870e27c86",
            "8b66516f43666f0af8ca73955c4ba0ce47c6289413ceb6b2d1b74b4e52acf280",
            "756357e369270b8141b1294beab84ed68db5b2afd5e8a94eaae99d36dd4f532d",
            "9b48ab43e36323daf1b28a7593a1eec3df8e2207f1c82e74b99c679ba2c22323",
            "9a0d851b807312b4cd8e8a2717944d7d4712726ab3cfa08b9a0e1bbaef13af66",
            "2ce471f09edb704478b719eb9fdd6f4d5de1714d1e7dba1b6a56fcb54337c83c"
          ],
          "sign": -1,
          "start_exit_ms": 1780560000000
        },
        {
          "cohort_id": 6,
          "end_exit_ms": 1782172800000,
          "exit_groups": 1,
          "origin_keys": [
            "8b2cf1ec4a983969bec012213fff13788b44c092e5ba7a2f90b1c5d9c4678d34"
          ],
          "sign": 1,
          "start_exit_ms": 1782172800000
        },
        {
          "cohort_id": 7,
          "end_exit_ms": 1782936000000,
          "exit_groups": 1,
          "origin_keys": [
            "f826a228ca45502fa67f3e7a6e6d7ee11336a63e7b5aeddb3e8f297993765312"
          ],
          "sign": -1,
          "start_exit_ms": 1782936000000
        },
        {
          "cohort_id": 8,
          "end_exit_ms": 1782964800000,
          "exit_groups": 1,
          "origin_keys": [
            "962f9283dc72ebb8cde3d9e0c593e37fb697e91eee5c09c8621ad854178a7630"
          ],
          "sign": 1,
          "start_exit_ms": 1782964800000
        },
        {
          "cohort_id": 9,
          "end_exit_ms": 1783728000000,
          "exit_groups": 4,
          "origin_keys": [
            "63d5711bd8e789167e03fc120f8a17294ea157d5724e2fd8f7dad342b093ed3f",
            "15ae8dc0ab4390da0278ef1b62bd74ff1ca4e9740f168e753171672c3ea593f1",
            "aacf3707686f90a2ab2f52fed2b918e3b6c0e38da45c7bf425917f0ca48495e9",
            "71f9c504b36da1bd0767f40a73abe13d2b1773433011d03dfc27642a372df1ad",
            "c845106fe6307ad59e5d7f481d3995fc9a25ffce7720a19b27bb765ec98f78fd"
          ],
          "sign": -1,
          "start_exit_ms": 1783483200000
        },
        {
          "cohort_id": 10,
          "end_exit_ms": 1783915200000,
          "exit_groups": 5,
          "origin_keys": [
            "65605dadb017905b3f7e20717019fade3b6a980661bbf009fbc142950270aa9b",
            "6799663cf96705b99cb17e39b93b93883ed7c06349b33a6f79d53d14f3229c74",
            "2b38504c380f0ce399ecfad56506edeff49119e8d6bec3b139be77a3c3d92006",
            "06e7d93e8dbc7b0caa092915e4dc54aa6c402b8d13c9255035b9d33e494a6dd9",
            "968e327f0605a840e11db55796bb26798903f1538cbd7a61717a126227e87f62"
          ],
          "sign": 1,
          "start_exit_ms": 1783814400000
        },
        {
          "cohort_id": 11,
          "end_exit_ms": 1784217600000,
          "exit_groups": 3,
          "origin_keys": [
            "de2fd35bd7d208c609912e7554cbea80e5c8b22c329d552a49e4329a2ddd1ed0",
            "de917e9e79772496d3e24a0cc8351bb306f4a644776903b39ca577854125b8a8",
            "013696a18ca39b51a8245b74518f9d2a58dee13996ab9016496c7ad21d58ead5",
            "26c7a35a019f91a6ae5894960175e7db3f8cefbb6758dfbdda245c87379af569"
          ],
          "sign": -1,
          "start_exit_ms": 1784001600000
        },
        {
          "cohort_id": 12,
          "end_exit_ms": 1784260800000,
          "exit_groups": 2,
          "origin_keys": [
            "42266ad29ddca70b313d0b39e336944ce72dba1f27d9e357b7c80030ecf4b97e",
            "6681a5caea361e92b02a4d9193b908f79dfe91f2776bfa31f1b3b7da1abe0a67"
          ],
          "sign": 1,
          "start_exit_ms": 1784246400000
        },
        {
          "cohort_id": 13,
          "end_exit_ms": 1784534400000,
          "exit_groups": 2,
          "origin_keys": [
            "93dfc61c03a8525e14fface007825cb7ff83bfbf1335caa50d94ab17aee30bdc",
            "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782"
          ],
          "sign": -1,
          "start_exit_ms": 1784361600000
        },
        {
          "cohort_id": 14,
          "end_exit_ms": 1784779200000,
          "exit_groups": 3,
          "origin_keys": [
            "cc82551910becb2ad68371a1b3a10e04d67a710d5de33ae05db11dc9f013f668",
            "b4b54f33da070c5a2b107b71d85233ecb1d9c72ab1fd090b44d7d5b9132e4f58",
            "13c4486cfd2eed83fdb4b21fc1f8f8d68db13cf14b7c9a6b1cb12f7895e15e0f"
          ],
          "sign": 1,
          "start_exit_ms": 1784692800000
        },
        {
          "cohort_id": 15,
          "end_exit_ms": 1786132800000,
          "exit_groups": 7,
          "origin_keys": [
            "1af94576f2cea51c8aeb8c36c975918cee22ea5bc4ea92e554246be1e6d7a127",
            "7a906d846ccb4308f54f14e0761cf09f7f670c78fdff33aa78dc11ccb770bb0b",
            "43b476ac4ac38af2e843d981583c1cc540442dfef5eb82ab503a6d9368b890b2",
            "3ad115aa9c72b11be73f3f89e82a83a8ab2b991a9c701340de98e7e796740e27",
            "c13b68c9e68bf23173d9fd098c2b34843f61d584a6c06eb9d39c23a7a4a8c32b",
            "97b143bc5b5ed7b17bf78597ae4e633cefc3a42a07c5ed9a169fa4af476a35b4",
            "6320bc05ba8fe5e201115c6a1426cd5e8237575566b79307f4a42ea4874f6f5e",
            "acfca04dd278b6bf61e3ba9a18c2bfe11b7d216dba6de190059b5be8a753a992",
            "a2b05143ce6d7640252b05e5b7cec8092489491c9a5d60ed773715357d5d1270"
          ],
          "sign": -1,
          "start_exit_ms": 1784822400000
        },
        {
          "cohort_id": 16,
          "end_exit_ms": 1786248000000,
          "exit_groups": 1,
          "origin_keys": [
            "38ba18c10c721df47c7ef7da72cfc453857ef94be5709487ca191dea13b337ce"
          ],
          "sign": 1,
          "start_exit_ms": 1786248000000
        },
        {
          "cohort_id": 17,
          "end_exit_ms": 1786550400000,
          "exit_groups": 4,
          "origin_keys": [
            "cc4bcf0271d48c707a7f20905e89386e7809e7a8e6656c49172474682459e6cc",
            "04f043c401d6de0a723172f94ce77f53f216b41a2c7764a07fbfafe7d25c1b90",
            "2f440a0c3fa704ef7d28c95044dd753eb0b733c4bbb9917fd2662aafec8fdf45",
            "9f8e2e26ed410b93656c69f6043e97778577d2fa5c0169e089ca36c0a137de7e"
          ],
          "sign": -1,
          "start_exit_ms": 1786435200000
        },
        {
          "cohort_id": 18,
          "end_exit_ms": 1786708800000,
          "exit_groups": 1,
          "origin_keys": [
            "356b3f003fd56d9d6ad5a5e5c3d7973dd84b86d0aa002131811fa409e9817aa8"
          ],
          "sign": 1,
          "start_exit_ms": 1786708800000
        },
        {
          "cohort_id": 19,
          "end_exit_ms": 1786924800000,
          "exit_groups": 2,
          "origin_keys": [
            "9ecd714cc633db0047602f722ab967fbfc72c42feb26833f383a3bedb343f2bb",
            "ebf7543c7ec608f421e7fba452d6da10de0a36a2e77d1ff5b8842c606aab58ea"
          ],
          "sign": -1,
          "start_exit_ms": 1786737600000
        },
        {
          "cohort_id": 20,
          "end_exit_ms": 1787486400000,
          "exit_groups": 3,
          "origin_keys": [
            "e61dc3626e169b8820e5825f4c028311607ad156e07490946412f789df74e5ba",
            "c9052be83a5788a6ba745823a4bf0147dde04deeb2d8b391feb7a0eabaad5ac1",
            "fbeada1abd3295ce40c13a3b978128232e4a1a4c741e75bb0a5cbbeb90832a02"
          ],
          "sign": 1,
          "start_exit_ms": 1787097600000
        },
        {
          "cohort_id": 21,
          "end_exit_ms": 1788004800000,
          "exit_groups": 4,
          "origin_keys": [
            "1bd838219fe26f37a91250f207fd090e9991c6f479038fe1e8fa708d2ede810e",
            "66b48055595e32540059dd7581a1c98154cbd3e8cb9bc0f7c7eded4d36b06634",
            "789d5e159a5a23a24ab065114446b96d4eeb6796049b97b9fc327573dca75002",
            "644115547aee472e42b7bf88ea31bffe83df59e6869a826ab5be5022cd22435a",
            "96c8b29888f69f723c7f604035d0ed3098bd52d26b8eb73cb5fd9e0da79309c1"
          ],
          "sign": -1,
          "start_exit_ms": 1787932800000
        },
        {
          "cohort_id": 22,
          "end_exit_ms": 1788120000000,
          "exit_groups": 1,
          "origin_keys": [
            "ff0ff86e7ecfe93c02186f61edd57f38d259e17c8d249038e9c77397a47d88db"
          ],
          "sign": 1,
          "start_exit_ms": 1788120000000
        },
        {
          "cohort_id": 23,
          "end_exit_ms": 1788408000000,
          "exit_groups": 4,
          "origin_keys": [
            "3a0dd213596625a304559ef7f5ee287e3ca9da6350729310a19ae8cc9609691c",
            "7ad3e943d2db184816904b595059ba414f078a7261744f373b0646995e89df1d",
            "056de4242b3e2706b5e09330a43084fd84bf1eaf43609e14fad35fd8e80c5e25",
            "778b8b9aec9a5244631fd0384759de29d52303397bfe54705eb09db48a8aa788",
            "ec364875f0ba137c532fe352a6bd74a254e375843d76806feb62beedd4109d19"
          ],
          "sign": -1,
          "start_exit_ms": 1788134400000
        }
      ]
    },
    "FIXED": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -2309.0525484387676,
          "BCH-USDT": -805.8648708039566,
          "BTC-USDT": -975.0019930838284,
          "ETH-USDT": 203.79608837448546,
          "HYPE-USDT": 7959.474822399606,
          "LINK-USDT": -638.6564380469331,
          "SOL-USDT": 905.3663353064285
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 233.06915578042924,
          "BCH-USDT": 318.57218783636296,
          "BTC-USDT": 212.07540276494393,
          "ETH-USDT": 878.1111065619533,
          "HYPE-USDT": 10170.105700660792,
          "LINK-USDT": 1577.0019719632558,
          "SOL-USDT": 3531.520552098785
        },
        "total_positive_trade_profit_bps": 16920.456077666524,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.6010538754971513,
        "winner_T": 24,
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.5574946146207964,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 2046.7601041045448,
          "2026-06": -106.99593195827781,
          "2026-07": -900.3800711473742,
          "2026-08": 3757.4192355175355,
          "2026-09": -456.74194080939526
        },
        "top_positive_month_share": 0.6473644275371732
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1777852800000,
          "T": 1,
          "net_trade_sum_bps": 50.85453311490776
        },
        {
          "utc_monday_ms": 1778457600000,
          "T": 7,
          "net_trade_sum_bps": -1573.633359848381
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 1,
          "net_trade_sum_bps": 3352.6202065745424
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 2,
          "net_trade_sum_bps": 216.91872426347538
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 2,
          "net_trade_sum_bps": 1666.344243089497
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 5,
          "net_trade_sum_bps": -2096.5953147548585
        },
        {
          "utc_monday_ms": 1782086400000,
          "T": 2,
          "net_trade_sum_bps": -126.95765629398899
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 2,
          "net_trade_sum_bps": 176.61539541311112
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 9,
          "net_trade_sum_bps": -487.7435615672177
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 8,
          "net_trade_sum_bps": 274.5262275204239
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 7,
          "net_trade_sum_bps": -13.099401831986452
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 4,
          "net_trade_sum_bps": -400.46593468063253
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 3,
          "net_trade_sum_bps": -111.91650363981675
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 6,
          "net_trade_sum_bps": -267.3580516394132
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 4,
          "net_trade_sum_bps": 6027.864749915629
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 6,
          "net_trade_sum_bps": -1110.7285665946447
        },
        {
          "utc_monday_ms": 1788134400000,
          "T": 5,
          "net_trade_sum_bps": -1237.184333333613
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": 1,
          "start_exit_ms": 1778400000000,
          "end_exit_ms": 1778400000000,
          "exit_groups": 1,
          "origin_keys": [
            "dafa358fd6d72b028ca32eccaf37b64cf0f8d606e43cd843215c695ddf4ce30d"
          ]
        },
        {
          "cohort_id": 1,
          "sign": -1,
          "start_exit_ms": 1778472000000,
          "end_exit_ms": 1778688000000,
          "exit_groups": 4,
          "origin_keys": [
            "54b968ba74f3b0748fe9b476247a26378ecd85a99f05bbd4e4de5e244c091cc0",
            "a68d8edf1a29c59f68fd3f5bcba84c940c821c4a58d01ee3402032015f4c9ff4",
            "54aa08a8e20cfff2787cc4b6b325e4cdd3a7fa69c21b505ee70fbee8aac49ce8",
            "a4feadb736502e81f108b5f7e93522f1fc442c5d91d6b5c216872fc68c116acd",
            "f3d1045f6c8a7a24de19e7d6d1827fe28c79578abfe3271af872406f2a9aeca8",
            "2232a44395250d67899755c9220e8f6f064dbf18967d68c222be3919851f2f13",
            "b139c8184981e16baba8d89e998d6b021c6a20bc6cffebb1d14d6adcf8aa97c6"
          ]
        },
        {
          "cohort_id": 2,
          "sign": 1,
          "start_exit_ms": 1779336000000,
          "end_exit_ms": 1779753600000,
          "exit_groups": 2,
          "origin_keys": [
            "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
            "2787c0350c5cf492e78a44da8ffdfe8b932312bd3576f427d9981014ff178768"
          ]
        },
        {
          "cohort_id": 3,
          "sign": -1,
          "start_exit_ms": 1779969600000,
          "end_exit_ms": 1779969600000,
          "exit_groups": 1,
          "origin_keys": [
            "50b807bef744a52955bcca34b4f5801627a78a04bccb1bfb201cfda6d3d4a777"
          ]
        },
        {
          "cohort_id": 4,
          "sign": 1,
          "start_exit_ms": 1780344000000,
          "end_exit_ms": 1780344000000,
          "exit_groups": 1,
          "origin_keys": [
            "0abc7cc780daa8ce66694c8bccae6e042dd3e38f893b9b18a6d1783a9f52d213"
          ]
        },
        {
          "cohort_id": 5,
          "sign": -1,
          "start_exit_ms": 1780560000000,
          "end_exit_ms": 1782086400000,
          "exit_groups": 6,
          "origin_keys": [
            "ae6b7b9caaa58babcc9fcc1bc4b2cee66f1adc18cebb57d3811d2fb5463027a7",
            "619e768742c15c76ee70c1212b0b15ffd2c77e18c8237d51ec2c3e1870e27c86",
            "8b66516f43666f0af8ca73955c4ba0ce47c6289413ceb6b2d1b74b4e52acf280",
            "756357e369270b8141b1294beab84ed68db5b2afd5e8a94eaae99d36dd4f532d",
            "9b48ab43e36323daf1b28a7593a1eec3df8e2207f1c82e74b99c679ba2c22323",
            "9a0d851b807312b4cd8e8a2717944d7d4712726ab3cfa08b9a0e1bbaef13af66",
            "2ce471f09edb704478b719eb9fdd6f4d5de1714d1e7dba1b6a56fcb54337c83c"
          ]
        },
        {
          "cohort_id": 6,
          "sign": 1,
          "start_exit_ms": 1782172800000,
          "end_exit_ms": 1782792000000,
          "exit_groups": 2,
          "origin_keys": [
            "8b2cf1ec4a983969bec012213fff13788b44c092e5ba7a2f90b1c5d9c4678d34",
            "962f9283dc72ebb8cde3d9e0c593e37fb697e91eee5c09c8621ad854178a7630"
          ]
        },
        {
          "cohort_id": 7,
          "sign": -1,
          "start_exit_ms": 1782936000000,
          "end_exit_ms": 1783728000000,
          "exit_groups": 5,
          "origin_keys": [
            "f826a228ca45502fa67f3e7a6e6d7ee11336a63e7b5aeddb3e8f297993765312",
            "63d5711bd8e789167e03fc120f8a17294ea157d5724e2fd8f7dad342b093ed3f",
            "15ae8dc0ab4390da0278ef1b62bd74ff1ca4e9740f168e753171672c3ea593f1",
            "aacf3707686f90a2ab2f52fed2b918e3b6c0e38da45c7bf425917f0ca48495e9",
            "71f9c504b36da1bd0767f40a73abe13d2b1773433011d03dfc27642a372df1ad",
            "c845106fe6307ad59e5d7f481d3995fc9a25ffce7720a19b27bb765ec98f78fd"
          ]
        },
        {
          "cohort_id": 8,
          "sign": 1,
          "start_exit_ms": 1783814400000,
          "end_exit_ms": 1783915200000,
          "exit_groups": 4,
          "origin_keys": [
            "06e7d93e8dbc7b0caa092915e4dc54aa6c402b8d13c9255035b9d33e494a6dd9",
            "65605dadb017905b3f7e20717019fade3b6a980661bbf009fbc142950270aa9b",
            "6799663cf96705b99cb17e39b93b93883ed7c06349b33a6f79d53d14f3229c74",
            "2b38504c380f0ce399ecfad56506edeff49119e8d6bec3b139be77a3c3d92006",
            "968e327f0605a840e11db55796bb26798903f1538cbd7a61717a126227e87f62"
          ]
        },
        {
          "cohort_id": 9,
          "sign": -1,
          "start_exit_ms": 1784001600000,
          "end_exit_ms": 1784030400000,
          "exit_groups": 2,
          "origin_keys": [
            "de2fd35bd7d208c609912e7554cbea80e5c8b22c329d552a49e4329a2ddd1ed0",
            "de917e9e79772496d3e24a0cc8351bb306f4a644776903b39ca577854125b8a8"
          ]
        },
        {
          "cohort_id": 10,
          "sign": 1,
          "start_exit_ms": 1784203200000,
          "end_exit_ms": 1784203200000,
          "exit_groups": 1,
          "origin_keys": [
            "42266ad29ddca70b313d0b39e336944ce72dba1f27d9e357b7c80030ecf4b97e",
            "6681a5caea361e92b02a4d9193b908f79dfe91f2776bfa31f1b3b7da1abe0a67"
          ]
        },
        {
          "cohort_id": 11,
          "sign": -1,
          "start_exit_ms": 1784217600000,
          "end_exit_ms": 1784534400000,
          "exit_groups": 3,
          "origin_keys": [
            "013696a18ca39b51a8245b74518f9d2a58dee13996ab9016496c7ad21d58ead5",
            "26c7a35a019f91a6ae5894960175e7db3f8cefbb6758dfbdda245c87379af569",
            "93dfc61c03a8525e14fface007825cb7ff83bfbf1335caa50d94ab17aee30bdc",
            "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782"
          ]
        },
        {
          "cohort_id": 12,
          "sign": 1,
          "start_exit_ms": 1784692800000,
          "end_exit_ms": 1784779200000,
          "exit_groups": 3,
          "origin_keys": [
            "cc82551910becb2ad68371a1b3a10e04d67a710d5de33ae05db11dc9f013f668",
            "b4b54f33da070c5a2b107b71d85233ecb1d9c72ab1fd090b44d7d5b9132e4f58",
            "13c4486cfd2eed83fdb4b21fc1f8f8d68db13cf14b7c9a6b1cb12f7895e15e0f"
          ]
        },
        {
          "cohort_id": 13,
          "sign": -1,
          "start_exit_ms": 1784822400000,
          "end_exit_ms": 1786132800000,
          "exit_groups": 7,
          "origin_keys": [
            "1af94576f2cea51c8aeb8c36c975918cee22ea5bc4ea92e554246be1e6d7a127",
            "7a906d846ccb4308f54f14e0761cf09f7f670c78fdff33aa78dc11ccb770bb0b",
            "43b476ac4ac38af2e843d981583c1cc540442dfef5eb82ab503a6d9368b890b2",
            "3ad115aa9c72b11be73f3f89e82a83a8ab2b991a9c701340de98e7e796740e27",
            "c13b68c9e68bf23173d9fd098c2b34843f61d584a6c06eb9d39c23a7a4a8c32b",
            "97b143bc5b5ed7b17bf78597ae4e633cefc3a42a07c5ed9a169fa4af476a35b4",
            "6320bc05ba8fe5e201115c6a1426cd5e8237575566b79307f4a42ea4874f6f5e",
            "acfca04dd278b6bf61e3ba9a18c2bfe11b7d216dba6de190059b5be8a753a992",
            "a2b05143ce6d7640252b05e5b7cec8092489491c9a5d60ed773715357d5d1270"
          ]
        },
        {
          "cohort_id": 14,
          "sign": 1,
          "start_exit_ms": 1786233600000,
          "end_exit_ms": 1786233600000,
          "exit_groups": 1,
          "origin_keys": [
            "38ba18c10c721df47c7ef7da72cfc453857ef94be5709487ca191dea13b337ce"
          ]
        },
        {
          "cohort_id": 15,
          "sign": -1,
          "start_exit_ms": 1786435200000,
          "end_exit_ms": 1786550400000,
          "exit_groups": 4,
          "origin_keys": [
            "cc4bcf0271d48c707a7f20905e89386e7809e7a8e6656c49172474682459e6cc",
            "04f043c401d6de0a723172f94ce77f53f216b41a2c7764a07fbfafe7d25c1b90",
            "2f440a0c3fa704ef7d28c95044dd753eb0b733c4bbb9917fd2662aafec8fdf45",
            "9f8e2e26ed410b93656c69f6043e97778577d2fa5c0169e089ca36c0a137de7e"
          ]
        },
        {
          "cohort_id": 16,
          "sign": 1,
          "start_exit_ms": 1786579200000,
          "end_exit_ms": 1786579200000,
          "exit_groups": 1,
          "origin_keys": [
            "356b3f003fd56d9d6ad5a5e5c3d7973dd84b86d0aa002131811fa409e9817aa8"
          ]
        },
        {
          "cohort_id": 17,
          "sign": -1,
          "start_exit_ms": 1786737600000,
          "end_exit_ms": 1786924800000,
          "exit_groups": 2,
          "origin_keys": [
            "9ecd714cc633db0047602f722ab967fbfc72c42feb26833f383a3bedb343f2bb",
            "e61dc3626e169b8820e5825f4c028311607ad156e07490946412f789df74e5ba",
            "ebf7543c7ec608f421e7fba452d6da10de0a36a2e77d1ff5b8842c606aab58ea"
          ]
        },
        {
          "cohort_id": 18,
          "sign": 1,
          "start_exit_ms": 1787385600000,
          "end_exit_ms": 1787889600000,
          "exit_groups": 3,
          "origin_keys": [
            "c9052be83a5788a6ba745823a4bf0147dde04deeb2d8b391feb7a0eabaad5ac1",
            "fbeada1abd3295ce40c13a3b978128232e4a1a4c741e75bb0a5cbbeb90832a02",
            "66b48055595e32540059dd7581a1c98154cbd3e8cb9bc0f7c7eded4d36b06634"
          ]
        },
        {
          "cohort_id": 19,
          "sign": -1,
          "start_exit_ms": 1787932800000,
          "end_exit_ms": 1787932800000,
          "exit_groups": 1,
          "origin_keys": [
            "1bd838219fe26f37a91250f207fd090e9991c6f479038fe1e8fa708d2ede810e"
          ]
        },
        {
          "cohort_id": 20,
          "sign": 1,
          "start_exit_ms": 1787947200000,
          "end_exit_ms": 1787947200000,
          "exit_groups": 1,
          "origin_keys": [
            "789d5e159a5a23a24ab065114446b96d4eeb6796049b97b9fc327573dca75002",
            "ff0ff86e7ecfe93c02186f61edd57f38d259e17c8d249038e9c77397a47d88db"
          ]
        },
        {
          "cohort_id": 21,
          "sign": -1,
          "start_exit_ms": 1787961600000,
          "end_exit_ms": 1788408000000,
          "exit_groups": 6,
          "origin_keys": [
            "644115547aee472e42b7bf88ea31bffe83df59e6869a826ab5be5022cd22435a",
            "96c8b29888f69f723c7f604035d0ed3098bd52d26b8eb73cb5fd9e0da79309c1",
            "3a0dd213596625a304559ef7f5ee287e3ca9da6350729310a19ae8cc9609691c",
            "7ad3e943d2db184816904b595059ba414f078a7261744f373b0646995e89df1d",
            "056de4242b3e2706b5e09330a43084fd84bf1eaf43609e14fad35fd8e80c5e25",
            "778b8b9aec9a5244631fd0384759de29d52303397bfe54705eb09db48a8aa788",
            "ec364875f0ba137c532fe352a6bd74a254e375843d76806feb62beedd4109d19"
          ]
        }
      ]
    },
    "FULL": {
      "profit": {
        "by_symbol_closed_net_bps": {
          "1000PEPE-USDT": -2309.0525484387676,
          "BCH-USDT": -805.8648708039566,
          "BTC-USDT": -975.0019930838284,
          "ETH-USDT": 203.79608837448546,
          "HYPE-USDT": 7959.474822399606,
          "LINK-USDT": -638.6564380469331,
          "SOL-USDT": 905.3663353064285
        },
        "by_symbol_positive_trade_profit_bps": {
          "1000PEPE-USDT": 233.06915578042924,
          "BCH-USDT": 318.57218783636296,
          "BTC-USDT": 212.07540276494393,
          "ETH-USDT": 878.1111065619533,
          "HYPE-USDT": 10170.105700660792,
          "LINK-USDT": 1577.0019719632558,
          "SOL-USDT": 3531.520552098785
        },
        "total_positive_trade_profit_bps": 16920.456077666524,
        "top_one_symbol_by_positive_trade_profit": "HYPE-USDT",
        "top_one_symbol_profit_share": 0.6010538754971513,
        "winner_T": 24,
        "top_decile_winner_T": 3,
        "top_decile_winners_share": 0.5574946146207964,
        "basis": "POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN",
        "by_exit_month_net_bps": {
          "2026-05": 2046.7601041045448,
          "2026-06": -106.99593195827781,
          "2026-07": -900.3800711473742,
          "2026-08": 3757.4192355175355,
          "2026-09": -456.74194080939526
        },
        "top_positive_month_share": 0.6473644275371732
      },
      "market_event_weekly_clusters": [
        {
          "utc_monday_ms": 1777852800000,
          "T": 1,
          "net_trade_sum_bps": 50.85453311490776
        },
        {
          "utc_monday_ms": 1778457600000,
          "T": 7,
          "net_trade_sum_bps": -1573.633359848381
        },
        {
          "utc_monday_ms": 1779062400000,
          "T": 1,
          "net_trade_sum_bps": 3352.6202065745424
        },
        {
          "utc_monday_ms": 1779667200000,
          "T": 2,
          "net_trade_sum_bps": 216.91872426347538
        },
        {
          "utc_monday_ms": 1780272000000,
          "T": 2,
          "net_trade_sum_bps": 1666.344243089497
        },
        {
          "utc_monday_ms": 1781481600000,
          "T": 5,
          "net_trade_sum_bps": -2096.5953147548585
        },
        {
          "utc_monday_ms": 1782086400000,
          "T": 2,
          "net_trade_sum_bps": -126.95765629398899
        },
        {
          "utc_monday_ms": 1782691200000,
          "T": 2,
          "net_trade_sum_bps": 176.61539541311112
        },
        {
          "utc_monday_ms": 1783296000000,
          "T": 9,
          "net_trade_sum_bps": -487.7435615672177
        },
        {
          "utc_monday_ms": 1783900800000,
          "T": 8,
          "net_trade_sum_bps": 274.5262275204239
        },
        {
          "utc_monday_ms": 1784505600000,
          "T": 7,
          "net_trade_sum_bps": -13.099401831986452
        },
        {
          "utc_monday_ms": 1785110400000,
          "T": 4,
          "net_trade_sum_bps": -400.46593468063253
        },
        {
          "utc_monday_ms": 1785715200000,
          "T": 3,
          "net_trade_sum_bps": -111.91650363981675
        },
        {
          "utc_monday_ms": 1786320000000,
          "T": 6,
          "net_trade_sum_bps": -267.3580516394132
        },
        {
          "utc_monday_ms": 1786924800000,
          "T": 4,
          "net_trade_sum_bps": 6027.864749915629
        },
        {
          "utc_monday_ms": 1787529600000,
          "T": 6,
          "net_trade_sum_bps": -1110.7285665946447
        },
        {
          "utc_monday_ms": 1788134400000,
          "T": 5,
          "net_trade_sum_bps": -1237.184333333613
        }
      ],
      "same_time_close_cohorts": [
        {
          "cohort_id": 0,
          "sign": 1,
          "start_exit_ms": 1778400000000,
          "end_exit_ms": 1778400000000,
          "exit_groups": 1,
          "origin_keys": [
            "dafa358fd6d72b028ca32eccaf37b64cf0f8d606e43cd843215c695ddf4ce30d"
          ]
        },
        {
          "cohort_id": 1,
          "sign": -1,
          "start_exit_ms": 1778472000000,
          "end_exit_ms": 1778688000000,
          "exit_groups": 4,
          "origin_keys": [
            "54b968ba74f3b0748fe9b476247a26378ecd85a99f05bbd4e4de5e244c091cc0",
            "a68d8edf1a29c59f68fd3f5bcba84c940c821c4a58d01ee3402032015f4c9ff4",
            "54aa08a8e20cfff2787cc4b6b325e4cdd3a7fa69c21b505ee70fbee8aac49ce8",
            "a4feadb736502e81f108b5f7e93522f1fc442c5d91d6b5c216872fc68c116acd",
            "f3d1045f6c8a7a24de19e7d6d1827fe28c79578abfe3271af872406f2a9aeca8",
            "2232a44395250d67899755c9220e8f6f064dbf18967d68c222be3919851f2f13",
            "b139c8184981e16baba8d89e998d6b021c6a20bc6cffebb1d14d6adcf8aa97c6"
          ]
        },
        {
          "cohort_id": 2,
          "sign": 1,
          "start_exit_ms": 1779336000000,
          "end_exit_ms": 1779753600000,
          "exit_groups": 2,
          "origin_keys": [
            "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
            "2787c0350c5cf492e78a44da8ffdfe8b932312bd3576f427d9981014ff178768"
          ]
        },
        {
          "cohort_id": 3,
          "sign": -1,
          "start_exit_ms": 1779969600000,
          "end_exit_ms": 1779969600000,
          "exit_groups": 1,
          "origin_keys": [
            "50b807bef744a52955bcca34b4f5801627a78a04bccb1bfb201cfda6d3d4a777"
          ]
        },
        {
          "cohort_id": 4,
          "sign": 1,
          "start_exit_ms": 1780344000000,
          "end_exit_ms": 1780344000000,
          "exit_groups": 1,
          "origin_keys": [
            "0abc7cc780daa8ce66694c8bccae6e042dd3e38f893b9b18a6d1783a9f52d213"
          ]
        },
        {
          "cohort_id": 5,
          "sign": -1,
          "start_exit_ms": 1780560000000,
          "end_exit_ms": 1782086400000,
          "exit_groups": 6,
          "origin_keys": [
            "ae6b7b9caaa58babcc9fcc1bc4b2cee66f1adc18cebb57d3811d2fb5463027a7",
            "619e768742c15c76ee70c1212b0b15ffd2c77e18c8237d51ec2c3e1870e27c86",
            "8b66516f43666f0af8ca73955c4ba0ce47c6289413ceb6b2d1b74b4e52acf280",
            "756357e369270b8141b1294beab84ed68db5b2afd5e8a94eaae99d36dd4f532d",
            "9b48ab43e36323daf1b28a7593a1eec3df8e2207f1c82e74b99c679ba2c22323",
            "9a0d851b807312b4cd8e8a2717944d7d4712726ab3cfa08b9a0e1bbaef13af66",
            "2ce471f09edb704478b719eb9fdd6f4d5de1714d1e7dba1b6a56fcb54337c83c"
          ]
        },
        {
          "cohort_id": 6,
          "sign": 1,
          "start_exit_ms": 1782172800000,
          "end_exit_ms": 1782792000000,
          "exit_groups": 2,
          "origin_keys": [
            "8b2cf1ec4a983969bec012213fff13788b44c092e5ba7a2f90b1c5d9c4678d34",
            "962f9283dc72ebb8cde3d9e0c593e37fb697e91eee5c09c8621ad854178a7630"
          ]
        },
        {
          "cohort_id": 7,
          "sign": -1,
          "start_exit_ms": 1782936000000,
          "end_exit_ms": 1783728000000,
          "exit_groups": 5,
          "origin_keys": [
            "f826a228ca45502fa67f3e7a6e6d7ee11336a63e7b5aeddb3e8f297993765312",
            "63d5711bd8e789167e03fc120f8a17294ea157d5724e2fd8f7dad342b093ed3f",
            "15ae8dc0ab4390da0278ef1b62bd74ff1ca4e9740f168e753171672c3ea593f1",
            "aacf3707686f90a2ab2f52fed2b918e3b6c0e38da45c7bf425917f0ca48495e9",
            "71f9c504b36da1bd0767f40a73abe13d2b1773433011d03dfc27642a372df1ad",
            "c845106fe6307ad59e5d7f481d3995fc9a25ffce7720a19b27bb765ec98f78fd"
          ]
        },
        {
          "cohort_id": 8,
          "sign": 1,
          "start_exit_ms": 1783814400000,
          "end_exit_ms": 1783915200000,
          "exit_groups": 4,
          "origin_keys": [
            "06e7d93e8dbc7b0caa092915e4dc54aa6c402b8d13c9255035b9d33e494a6dd9",
            "65605dadb017905b3f7e20717019fade3b6a980661bbf009fbc142950270aa9b",
            "6799663cf96705b99cb17e39b93b93883ed7c06349b33a6f79d53d14f3229c74",
            "2b38504c380f0ce399ecfad56506edeff49119e8d6bec3b139be77a3c3d92006",
            "968e327f0605a840e11db55796bb26798903f1538cbd7a61717a126227e87f62"
          ]
        },
        {
          "cohort_id": 9,
          "sign": -1,
          "start_exit_ms": 1784001600000,
          "end_exit_ms": 1784030400000,
          "exit_groups": 2,
          "origin_keys": [
            "de2fd35bd7d208c609912e7554cbea80e5c8b22c329d552a49e4329a2ddd1ed0",
            "de917e9e79772496d3e24a0cc8351bb306f4a644776903b39ca577854125b8a8"
          ]
        },
        {
          "cohort_id": 10,
          "sign": 1,
          "start_exit_ms": 1784203200000,
          "end_exit_ms": 1784203200000,
          "exit_groups": 1,
          "origin_keys": [
            "42266ad29ddca70b313d0b39e336944ce72dba1f27d9e357b7c80030ecf4b97e",
            "6681a5caea361e92b02a4d9193b908f79dfe91f2776bfa31f1b3b7da1abe0a67"
          ]
        },
        {
          "cohort_id": 11,
          "sign": -1,
          "start_exit_ms": 1784217600000,
          "end_exit_ms": 1784534400000,
          "exit_groups": 3,
          "origin_keys": [
            "013696a18ca39b51a8245b74518f9d2a58dee13996ab9016496c7ad21d58ead5",
            "26c7a35a019f91a6ae5894960175e7db3f8cefbb6758dfbdda245c87379af569",
            "93dfc61c03a8525e14fface007825cb7ff83bfbf1335caa50d94ab17aee30bdc",
            "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782"
          ]
        },
        {
          "cohort_id": 12,
          "sign": 1,
          "start_exit_ms": 1784692800000,
          "end_exit_ms": 1784779200000,
          "exit_groups": 3,
          "origin_keys": [
            "cc82551910becb2ad68371a1b3a10e04d67a710d5de33ae05db11dc9f013f668",
            "b4b54f33da070c5a2b107b71d85233ecb1d9c72ab1fd090b44d7d5b9132e4f58",
            "13c4486cfd2eed83fdb4b21fc1f8f8d68db13cf14b7c9a6b1cb12f7895e15e0f"
          ]
        },
        {
          "cohort_id": 13,
          "sign": -1,
          "start_exit_ms": 1784822400000,
          "end_exit_ms": 1786132800000,
          "exit_groups": 7,
          "origin_keys": [
            "1af94576f2cea51c8aeb8c36c975918cee22ea5bc4ea92e554246be1e6d7a127",
            "7a906d846ccb4308f54f14e0761cf09f7f670c78fdff33aa78dc11ccb770bb0b",
            "43b476ac4ac38af2e843d981583c1cc540442dfef5eb82ab503a6d9368b890b2",
            "3ad115aa9c72b11be73f3f89e82a83a8ab2b991a9c701340de98e7e796740e27",
            "c13b68c9e68bf23173d9fd098c2b34843f61d584a6c06eb9d39c23a7a4a8c32b",
            "97b143bc5b5ed7b17bf78597ae4e633cefc3a42a07c5ed9a169fa4af476a35b4",
            "6320bc05ba8fe5e201115c6a1426cd5e8237575566b79307f4a42ea4874f6f5e",
            "acfca04dd278b6bf61e3ba9a18c2bfe11b7d216dba6de190059b5be8a753a992",
            "a2b05143ce6d7640252b05e5b7cec8092489491c9a5d60ed773715357d5d1270"
          ]
        },
        {
          "cohort_id": 14,
          "sign": 1,
          "start_exit_ms": 1786233600000,
          "end_exit_ms": 1786233600000,
          "exit_groups": 1,
          "origin_keys": [
            "38ba18c10c721df47c7ef7da72cfc453857ef94be5709487ca191dea13b337ce"
          ]
        },
        {
          "cohort_id": 15,
          "sign": -1,
          "start_exit_ms": 1786435200000,
          "end_exit_ms": 1786550400000,
          "exit_groups": 4,
          "origin_keys": [
            "cc4bcf0271d48c707a7f20905e89386e7809e7a8e6656c49172474682459e6cc",
            "04f043c401d6de0a723172f94ce77f53f216b41a2c7764a07fbfafe7d25c1b90",
            "2f440a0c3fa704ef7d28c95044dd753eb0b733c4bbb9917fd2662aafec8fdf45",
            "9f8e2e26ed410b93656c69f6043e97778577d2fa5c0169e089ca36c0a137de7e"
          ]
        },
        {
          "cohort_id": 16,
          "sign": 1,
          "start_exit_ms": 1786579200000,
          "end_exit_ms": 1786579200000,
          "exit_groups": 1,
          "origin_keys": [
            "356b3f003fd56d9d6ad5a5e5c3d7973dd84b86d0aa002131811fa409e9817aa8"
          ]
        },
        {
          "cohort_id": 17,
          "sign": -1,
          "start_exit_ms": 1786737600000,
          "end_exit_ms": 1786924800000,
          "exit_groups": 2,
          "origin_keys": [
            "9ecd714cc633db0047602f722ab967fbfc72c42feb26833f383a3bedb343f2bb",
            "e61dc3626e169b8820e5825f4c028311607ad156e07490946412f789df74e5ba",
            "ebf7543c7ec608f421e7fba452d6da10de0a36a2e77d1ff5b8842c606aab58ea"
          ]
        },
        {
          "cohort_id": 18,
          "sign": 1,
          "start_exit_ms": 1787385600000,
          "end_exit_ms": 1787889600000,
          "exit_groups": 3,
          "origin_keys": [
            "c9052be83a5788a6ba745823a4bf0147dde04deeb2d8b391feb7a0eabaad5ac1",
            "fbeada1abd3295ce40c13a3b978128232e4a1a4c741e75bb0a5cbbeb90832a02",
            "66b48055595e32540059dd7581a1c98154cbd3e8cb9bc0f7c7eded4d36b06634"
          ]
        },
        {
          "cohort_id": 19,
          "sign": -1,
          "start_exit_ms": 1787932800000,
          "end_exit_ms": 1787932800000,
          "exit_groups": 1,
          "origin_keys": [
            "1bd838219fe26f37a91250f207fd090e9991c6f479038fe1e8fa708d2ede810e"
          ]
        },
        {
          "cohort_id": 20,
          "sign": 1,
          "start_exit_ms": 1787947200000,
          "end_exit_ms": 1787947200000,
          "exit_groups": 1,
          "origin_keys": [
            "789d5e159a5a23a24ab065114446b96d4eeb6796049b97b9fc327573dca75002",
            "ff0ff86e7ecfe93c02186f61edd57f38d259e17c8d249038e9c77397a47d88db"
          ]
        },
        {
          "cohort_id": 21,
          "sign": -1,
          "start_exit_ms": 1787961600000,
          "end_exit_ms": 1788408000000,
          "exit_groups": 6,
          "origin_keys": [
            "644115547aee472e42b7bf88ea31bffe83df59e6869a826ab5be5022cd22435a",
            "96c8b29888f69f723c7f604035d0ed3098bd52d26b8eb73cb5fd9e0da79309c1",
            "3a0dd213596625a304559ef7f5ee287e3ca9da6350729310a19ae8cc9609691c",
            "7ad3e943d2db184816904b595059ba414f078a7261744f373b0646995e89df1d",
            "056de4242b3e2706b5e09330a43084fd84bf1eaf43609e14fad35fd8e80c5e25",
            "778b8b9aec9a5244631fd0384759de29d52303397bfe54705eb09db48a8aa788",
            "ec364875f0ba137c532fe352a6bd74a254e375843d76806feb62beedd4109d19"
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
