# Frozen Q0/B — 2026 seen-period replication

**evidence_type=SEEN_DATA_REPLICATION; independent=false; formal_credit=0; operating_adoption=false.**

Entries: 2026-05-08 00:00 UTC inclusive to 2026-09-05 00:00 exclusive. Final mark at September5 00UTC uses the last completed4h close. Both start flat. Channel state uses the original full historical prefix, without warmup PnL or carried orders/positions.

The whole original raw candidate pool (May7 16UTC–September5 12UTC) was used by prior related research. Different generations/file hashes do not establish unused data. Prior independent comparison stays NOT_RUN, used0/1.

All monetary values are weighted fixed-reference-notional amounts in bps units, not account returns or account MDD. C is an ex-post same-average-notional-holding control, not an executable input. Research price-taker cost model only; signed funding/fills and nonlinear impact are unbound.

## A/B/C economics and risk

| Metric | Q0 A | Entry allocation B | Fixed exposure C |
|---|---:|---:|---:|
| Signals | 40 | 40 | 40 |
| Closed / open | 34 / 0 | 34 / 0 | 34 / 0 |
| Unit win rate % | 32.3529 | 32.3529 | 32.3529 |
| Closed gross / T | 240.6265 | 238.9844 | 239.5648 |
| Closed net / T | 215.1423 | 213.5727 | 214.1931 |
| Amount PF | 2.2360 | 2.2270 | 2.2360 |
| Mean win / loss | 1,203.0127 / -257.3174 | 1,198.1290 / -257.3021 | 1,197.7050 / -256.1821 |
| Realized amount payoff | 4.6752 | 4.6565 | 4.6752 |
| Closed cost2 net / T | 189.6582 | 188.1610 | 188.8214 |
| Closed net amount | 7,314.8393 | 7,261.4710 | 7,282.5658 |
| Open hypothetical net mark | 0.0000 | 0.0000 | 0.0000 |
| Terminal net amount | 7,314.8393 | 7,261.4710 | 7,282.5658 |
| Terminal cost2 net amount | 6,448.3789 | 6,397.4732 | 6,419.9283 |
| Daily marked drawdown | 5,619.0811 | 5,618.7276 | 5,594.2893 |
| Max completed marked recovery days | 102.0000 | 102.0000 | 102.0000 |
| Unrecovered at end / underwater days | True / 8.0000 | True / 8.0000 | True / 8.0000 |
| Maximum simultaneous-close-group losing run | 2,779.7110 | 2,779.7110 | 2,767.4468 |
| Notional-weighted position-days | 97.0000 | 96.5720 | 96.5720 |
| Max simultaneous notional slots | 5.0000 | 5.0000 | 4.9779 |
| Original all-winner amount retained | 13,233.1402 | 13,179.4186 | 13,174.7548 |
| Current-period A top3 amount retained / % | 9,130.1062 / 100.0000 | 9,130.1062 / 100.0000 | 9,089.8236 / 99.5588 |
| Original top-decile winner amount retained / % | 6,387.6943 / 100.0000 | 6,387.6943 / 100.0000 | 6,359.5115 / 99.5588 |
| Closed fees / funding / total cost | 340.0000 / 348.5400 / 866.4604 | 339.1202 / 347.2312 / 863.9979 | 338.4999 / 347.0022 / 862.6375 |

Frozen reference: {'N': 38, 'first_available_at': 1734825600000, 'last_available_at': 1738022400000, 'ddof': 1, 'available_at_rule': 'STRICTLY_BEFORE_EVALUATION_START', 'return_definition': 'ARITHMETIC_MEAN_OF_SEVEN_SIMPLE_CLOSE_RETURNS', 'sigma_ref': 0.03290943045427639}.
Entry weights: {'T': 34, 'minimum': 0.9159989915559242, 'maximum': 1.0, 'mean_per_entry': 0.9974122548347865, 'reduced_entries': 2}.
C normalization: {'k': 0.9955879412725077, 'normalization': 'SUM_B_WEIGHT_TIMES_HOLD_MS_DIVIDED_BY_SUM_A_HOLD_MS', 'ex_post_analysis_only': True, 'executable_strategy': False, 'fed_back_to_candidate_weights_or_reference_volatility': False}.

## Same-trade amount attribution

| Contribution | B minus A | B minus C |
|---|---:|---:|
| Saved original loss amount | 0.3534 | -25.7585 |
| Foregone original winner amount | 53.7217 | -4.6637 |
| Cost saving already included in net | 2.4625 | -1.3604 |

No removed/new trades. Cost saving is already included in net. Different stages' maximum losing-run or DD extrema are not same-trade causal contributions.

## Monthly marked net amounts

| Month | A | B | C | B−C |
|---|---:|---:|---:|---:|
| 2026-05 | -975.2869 | -975.2869 | -970.9838 | -4.3030 |
| 2026-06 | -2,256.5646 | -2,256.5646 | -2,246.6085 | -9.9561 |
| 2026-07 | -1,232.0455 | -1,231.6921 | -1,226.6097 | -5.0825 |
| 2026-08 | 11,778.7363 | 11,725.0146 | 11,726.7678 | -1.7532 |
| 2026-09 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Symbol terminal net amounts

| Symbol | A | B | C | B−C |
|---|---:|---:|---:|---:|
| 1000PEPE-USDT | 1,419.4830 | 1,419.8364 | 1,413.2201 | 6.6162 |
| BCH-USDT | -113.7311 | -113.7311 | -113.2293 | -0.5018 |
| BTC-USDT | 1,338.1192 | 1,338.1192 | 1,332.2154 | 5.9039 |
| ETH-USDT | 2,724.4391 | 2,724.4391 | 2,712.4188 | 12.0204 |
| HYPE-USDT | 2,710.5121 | 2,710.5121 | 2,698.5532 | 11.9589 |
| LINK-USDT | -1,185.6203 | -1,185.6203 | -1,180.3893 | -5.2310 |
| SOL-USDT | 421.6372 | 367.9156 | 419.7769 | -51.8614 |

## Frozen technical decision and dependence

```json
{
  "decision": {
    "B_minus_C_increment_lower95_positive": false,
    "automatic_next_candidate": false,
    "checks": {
      "DD_not_worse_than_C": false,
      "at_least_one_improvement": false,
      "loss_run_not_worse_than_C": false,
      "net_not_worse_than_C": false,
      "positive_cost2_terminal_net": true,
      "positive_terminal_net": true
    },
    "code_test_PASS_is_economic_PASS": false,
    "comparison_type": "ENTRY_NOTIONAL_ALLOCATION",
    "decision": "SEEN_PERIOD_VULNERABILITY",
    "economic_status": "MEASURED",
    "evidence_type": "SEEN_DATA_REPLICATION",
    "failed_checks": [
      "net_not_worse_than_C",
      "DD_not_worse_than_C",
      "loss_run_not_worse_than_C",
      "at_least_one_improvement"
    ],
    "formal_credit": 0,
    "formal_pass": false,
    "independent": false,
    "independent_comparison": "NOT_RUN",
    "independent_comparison_uses": 0,
    "new_candidate_trials": 0,
    "operating_adoption": false,
    "original_26_candidate_trials_unchanged": true,
    "original_technical_decision": "DEV_REJECT",
    "relative_advantages": {
      "loss_run": false,
      "marked_DD": false,
      "terminal_net": false
    },
    "research_reference": "Q0",
    "sample_sufficiency": {
      "N_effective": null,
      "block_days": 30,
      "calendar_days": 120,
      "closed_PF_payoff_and_expectancy_defined": true,
      "completed_T": 34,
      "holding_exceeds_bootstrap_block": false,
      "inherited_minimum_closed_T": 6,
      "maximum_holding_days": 8.0,
      "minimum_closed_T_met": true,
      "minimum_source": "break_channel_metrics_v1.decide.minimum_closed_T",
      "model_selection_and_data_reuse_corrected": false,
      "no_new_cluster_count_pass_threshold": true,
      "nominal_blocks_are_independent_samples": false,
      "nominal_calendar_blocks": 4.0,
      "status": "DESCRIPTIVE_SEEN_SAMPLE_ONLY",
      "terminal_mark_is_hypothetical_not_realized": false,
      "unresolved_open_T": 0
    },
    "signal_prediction_improvement_claimed": false,
    "study_goal_met": false,
    "technical_decision_scope": "UNCHANGED_GOAL_ARITHMETIC_ON_NEW_SEEN_PERIOD_ONLY; ORIGINAL_DEV_STATES_PRESERVED"
  },
  "dependence": {
    "N_effective": null,
    "basis": "SHARED_ENTRY_MARKET_WEIGHT_AND_CROSS_SYMBOL_LOSS_DEPENDENCE; NOT_INDEPENDENT_SAMPLE_COUNTS",
    "entry_cluster_count": 24,
    "entry_clusters": [
      {
        "T": 1,
        "entry_ms": 1778371200000,
        "origin_keys": [
          "d6754eb08aa2efdcbdca0a71a1f64cdbd3ffdd0d573da28b90fd4a028b93783f"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1778457600000,
        "origin_keys": [
          "51694dbf44269443137e55f6d0930bed96a9a973d316548eefc83aa046896729"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1778544000000,
        "origin_keys": [
          "c4cf3282179efb7fb426139875146fcadc35eaa73910c5a527140174c53c3f65"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1779408000000,
        "origin_keys": [
          "fbb58ca3453bbf81df4b4e82debd3cc07875c5666c6841a5cca57fea900705b4"
        ]
      },
      {
        "T": 2,
        "entry_ms": 1780272000000,
        "origin_keys": [
          "2f92e5c776980667af76c0657717ea176a11148c42eb75199cd794eadd593250",
          "578c32fa7bb629c2cc136354741556c944f16d029a5a671b423715f1fbf3e379"
        ]
      },
      {
        "T": 3,
        "entry_ms": 1780963200000,
        "origin_keys": [
          "1978e6145de1a23ed120177583f891cfeff854068ec1aa90d9e1473df533c8c4",
          "564e1bd0da2b14b7ad470365d10d552756f22ba83acf9b39794a60743395cda2",
          "9190a651256b0b77e800f2c67116fb3b1701de716ddcf13e266d3344e2f014d5"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1781308800000,
        "origin_keys": [
          "31715d9f91e846da37de1e8f01413cee2d4253495818dbfcfac99cec390c27e6"
        ]
      },
      {
        "T": 3,
        "entry_ms": 1781481600000,
        "origin_keys": [
          "18a8d76917adc06bc592b54eb4b9211697ff94fae98c588e3e850d704cd4e1d0",
          "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568",
          "64b673229efe7ebff6a88851395741b66b20cea69751309f0393f4715ae73b19"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1782086400000,
        "origin_keys": [
          "efa60e623906f0d7806aa1865503f7fbd5e88e5086c317dbbe48e10143780573"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1782864000000,
        "origin_keys": [
          "7cf9020701be02c957a508ce6c551b757539204eb16ac730c4d9973e7b4a30f3"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1783123200000,
        "origin_keys": [
          "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1783382400000,
        "origin_keys": [
          "e2445ff43ebdd66214ef673c57f11985307e96452e8bbb5646c0b0910c9760fd"
        ]
      },
      {
        "T": 2,
        "entry_ms": 1783814400000,
        "origin_keys": [
          "cf3d93688918f848d38e6c44f971f7808ca47e5ae32c4a5ef6eb84e353814272",
          "e31955635438f244d0376a365c0362f67dd0cb5850f49389ef0d3be90cffe84e"
        ]
      },
      {
        "T": 2,
        "entry_ms": 1784505600000,
        "origin_keys": [
          "ab2a2b1541e2af29c7ebd20a9a64c6e7348ca43ef05eb7855304fe34d2515a65",
          "b005e4d1d431dfabd2c4d12d0205b33f3fa3cfd3a01ef62299888eaf438b4245"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1784678400000,
        "origin_keys": [
          "fe5abbc5dd9ef292ad6a800292338342013096ae76e0cdda1294205ca0a16330"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1785110400000,
        "origin_keys": [
          "84b9483292abbf26e56f2460135f9f76d6a9e95821073d80c342cb2d3fc55d3a"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1785196800000,
        "origin_keys": [
          "d6af7453485b4ffec7745f4b952aa50d376b3e08e1c9dd450f69d87342bef175"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1785715200000,
        "origin_keys": [
          "e2ee772a775c57ef6f6b059f00d842055e54bba3605202bd51555f9d3260740a"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1785801600000,
        "origin_keys": [
          "369bc66780e9c80e600445beeb75b248437a03e18ad94379ada3964623cc56d7"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1786060800000,
        "origin_keys": [
          "de18c3d895e5ac61eb712cc3dd5168f660d9d03f94c65336e237d33f0c5408ef"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1786320000000,
        "origin_keys": [
          "7cde4b543006fb8c9d2138a83226b490da703904eab4e4496115462252268705"
        ]
      },
      {
        "T": 3,
        "entry_ms": 1787097600000,
        "origin_keys": [
          "40ebc4356d6f9e0d5c7e7c83ec57b8f7870c55be0ac3b98c4827c6dcc05f5cae",
          "4999f99153ed39cf58046aea603e500de7337a8f914896b6d167d57ff2ddd00b",
          "811b7a73c0c6e4ff61e0143d6fac907c10babe6954b7451207ae435548e7c8e3"
        ]
      },
      {
        "T": 2,
        "entry_ms": 1787270400000,
        "origin_keys": [
          "0885a5740d9d7680986d09077031be501313f4588115afee33c0cd8b28e816d3",
          "254874089657dee5a2f36bb9bd1cf8c9a786cfe709b1f6df29229eccbe214a45"
        ]
      },
      {
        "T": 1,
        "entry_ms": 1787616000000,
        "origin_keys": [
          "9d1db065e5e0eb36d9c8ce8c640427a2b089c80b83c9473c725c5c99c2a10e4f"
        ]
      }
    ],
    "max_holding_days": 8.0,
    "max_simultaneous_entry_T": 3,
    "simultaneous_close_clusters": [
      {
        "T": 1,
        "exit_ms": 1778587200000,
        "origin_keys": [
          "c4cf3282179efb7fb426139875146fcadc35eaa73910c5a527140174c53c3f65"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -295.8037400831126,
            "net_bps": -275.8037400831126
          },
          "B_RISK": {
            "cost2x_net_bps": -295.8037400831126,
            "net_bps": -275.8037400831126
          },
          "C_FIXED": {
            "cost2x_net_bps": -294.498636610054,
            "net_bps": -274.58687778460387
          }
        },
        "symbol_count": 1,
        "symbols": [
          "LINK-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1778601600000,
        "origin_keys": [
          "d6754eb08aa2efdcbdca0a71a1f64cdbd3ffdd0d573da28b90fd4a028b93783f"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -312.16803222254475,
            "net_bps": -280.34962270726754
          },
          "B_RISK": {
            "cost2x_net_bps": -312.16803222254475,
            "net_bps": -280.34962270726754
          },
          "C_FIXED": {
            "cost2x_net_bps": -310.7907285315332,
            "net_bps": -279.11270370765277
          }
        },
        "symbol_count": 1,
        "symbols": [
          "1000PEPE-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1778630400000,
        "origin_keys": [
          "51694dbf44269443137e55f6d0930bed96a9a973d316548eefc83aa046896729"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -249.24951995268782,
            "net_bps": -229.24951995268782
          },
          "B_RISK": {
            "cost2x_net_bps": -249.24951995268782,
            "net_bps": -229.24951995268782
          },
          "C_FIXED": {
            "cost2x_net_bps": -248.1498164328573,
            "net_bps": -228.23805760740714
          }
        },
        "symbol_count": 1,
        "symbols": [
          "BTC-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1779465600000,
        "origin_keys": [
          "fbb58ca3453bbf81df4b4e82debd3cc07875c5666c6841a5cca57fea900705b4"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -169.88398635315423,
            "net_bps": -149.88398635315423
          },
          "B_RISK": {
            "cost2x_net_bps": -169.88398635315423,
            "net_bps": -149.88398635315423
          },
          "C_FIXED": {
            "cost2x_net_bps": -169.1344482285036,
            "net_bps": -149.22268940305347
          }
        },
        "symbol_count": 1,
        "symbols": [
          "BTC-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 2,
        "exit_ms": 1780300800000,
        "origin_keys": [
          "2f92e5c776980667af76c0657717ea176a11148c42eb75199cd794eadd593250",
          "578c32fa7bb629c2cc136354741556c944f16d029a5a671b423715f1fbf3e379"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -424.6484438927344,
            "net_bps": -384.6484438927344
          },
          "B_RISK": {
            "cost2x_net_bps": -424.6484438927344,
            "net_bps": -384.6484438927344
          },
          "C_FIXED": {
            "cost2x_net_bps": -422.77487001974146,
            "net_bps": -382.9513523688411
          }
        },
        "symbol_count": 2,
        "symbols": [
          "1000PEPE-USDT",
          "LINK-USDT"
        ],
        "unit_loss_T": 2,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1781092800000,
        "origin_keys": [
          "564e1bd0da2b14b7ad470365d10d552756f22ba83acf9b39794a60743395cda2"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -411.6380927611873,
            "net_bps": -391.6380927611873
          },
          "B_RISK": {
            "cost2x_net_bps": -411.6380927611873,
            "net_bps": -391.6380927611873
          },
          "C_FIXED": {
            "cost2x_net_bps": -409.821921321452,
            "net_bps": -389.9101624960019
          }
        },
        "symbol_count": 1,
        "symbols": [
          "BTC-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 2,
        "exit_ms": 1781136000000,
        "origin_keys": [
          "1978e6145de1a23ed120177583f891cfeff854068ec1aa90d9e1473df533c8c4",
          "9190a651256b0b77e800f2c67116fb3b1701de716ddcf13e266d3344e2f014d5"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -1117.2563942654765,
            "net_bps": -1068.1376078381727
          },
          "B_RISK": {
            "cost2x_net_bps": -1117.2563942654765,
            "net_bps": -1068.1376078381727
          },
          "C_FIXED": {
            "cost2x_net_bps": -1112.326993440311,
            "net_bps": -1063.4249219833475
          }
        },
        "symbol_count": 2,
        "symbols": [
          "1000PEPE-USDT",
          "LINK-USDT"
        ],
        "unit_loss_T": 2,
        "unit_winner_T": 0
      },
      {
        "T": 2,
        "exit_ms": 1781740800000,
        "origin_keys": [
          "31715d9f91e846da37de1e8f01413cee2d4253495818dbfcfac99cec390c27e6",
          "49368c14663606dcad82af6630e53963cc7a11dff5f74e5a04a6a6b256457568"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": 154.69474230544796,
            "net_bps": 204.69474230544796
          },
          "B_RISK": {
            "cost2x_net_bps": 154.69474230544796,
            "net_bps": 204.69474230544796
          },
          "C_FIXED": {
            "cost2x_net_bps": 154.01222001756207,
            "net_bps": 203.79161708118744
          }
        },
        "symbol_count": 2,
        "symbols": [
          "BTC-USDT",
          "SOL-USDT"
        ],
        "unit_loss_T": 0,
        "unit_winner_T": 2
      },
      {
        "T": 1,
        "exit_ms": 1781798400000,
        "origin_keys": [
          "64b673229efe7ebff6a88851395741b66b20cea69751309f0393f4715ae73b19"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -462.9858027477328,
            "net_bps": -436.605425835706
          },
          "B_RISK": {
            "cost2x_net_bps": -462.9858027477328,
            "net_bps": -436.605425835706
          },
          "C_FIXED": {
            "cost2x_net_bps": -460.94308219601464,
            "net_bps": -434.6790970561771
          }
        },
        "symbol_count": 1,
        "symbols": [
          "LINK-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1781827200000,
        "origin_keys": [
          "18a8d76917adc06bc592b54eb4b9211697ff94fae98c588e3e850d704cd4e1d0"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -134.53595097146717,
            "net_bps": -109.53595097146716
          },
          "B_RISK": {
            "cost2x_net_bps": -134.53595097146717,
            "net_bps": -109.53595097146716
          },
          "C_FIXED": {
            "cost2x_net_bps": -133.94237045482203,
            "net_bps": -109.05267192300933
          }
        },
        "symbol_count": 1,
        "symbols": [
          "ETH-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1782172800000,
        "origin_keys": [
          "efa60e623906f0d7806aa1865503f7fbd5e88e5086c317dbbe48e10143780573"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -110.69382119433865,
            "net_bps": -90.69382119433865
          },
          "B_RISK": {
            "cost2x_net_bps": -110.69382119433865,
            "net_bps": -90.69382119433865
          },
          "C_FIXED": {
            "cost2x_net_bps": -110.20543355445871,
            "net_bps": -90.29367472900854
          }
        },
        "symbol_count": 1,
        "symbols": [
          "SOL-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1782950400000,
        "origin_keys": [
          "7cf9020701be02c957a508ce6c551b757539204eb16ac730c4d9973e7b4a30f3"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -449.7352479936045,
            "net_bps": -429.7352479936045
          },
          "B_RISK": {
            "cost2x_net_bps": -449.7352479936045,
            "net_bps": -429.7352479936045
          },
          "C_FIXED": {
            "cost2x_net_bps": -447.7509896676334,
            "net_bps": -427.83923084218327
          }
        },
        "symbol_count": 1,
        "symbols": [
          "HYPE-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1783296000000,
        "origin_keys": [
          "1aee29b57680f7a81d3e7e052d35d78047193a61676f999daf3a67299619a2e6"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -116.48104239986421,
            "net_bps": -88.742632884587
          },
          "B_RISK": {
            "cost2x_net_bps": -116.01717677955405,
            "net_bps": -88.38923068623052
          },
          "C_FIXED": {
            "cost2x_net_bps": -115.96712120015648,
            "net_bps": -88.35109517666791
          }
        },
        "symbol_count": 1,
        "symbols": [
          "1000PEPE-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1783396800000,
        "origin_keys": [
          "e2445ff43ebdd66214ef673c57f11985307e96452e8bbb5646c0b0910c9760fd"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -107.3777445109769,
            "net_bps": -87.3777445109769
          },
          "B_RISK": {
            "cost2x_net_bps": -107.3777445109769,
            "net_bps": -87.3777445109769
          },
          "C_FIXED": {
            "cost2x_net_bps": -106.9039875961688,
            "net_bps": -86.99222877071865
          }
        },
        "symbol_count": 1,
        "symbols": [
          "LINK-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1783900800000,
        "origin_keys": [
          "e31955635438f244d0376a365c0362f67dd0cb5850f49389ef0d3be90cffe84e"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": 170.99876623890108,
            "net_bps": 192.6171757541783
          },
          "B_RISK": {
            "cost2x_net_bps": 170.99876623890108,
            "net_bps": 192.6171757541783
          },
          "C_FIXED": {
            "cost2x_net_bps": 170.2443096399263,
            "net_bps": 191.76733746282716
          }
        },
        "symbol_count": 1,
        "symbols": [
          "1000PEPE-USDT"
        ],
        "unit_loss_T": 0,
        "unit_winner_T": 1
      },
      {
        "T": 1,
        "exit_ms": 1784332800000,
        "origin_keys": [
          "cf3d93688918f848d38e6c44f971f7808ca47e5ae32c4a5ef6eb84e353814272"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": 241.95459989478235,
            "net_bps": 272.95459989478235
          },
          "B_RISK": {
            "cost2x_net_bps": 241.95459989478235,
            "net_bps": 272.95459989478235
          },
          "C_FIXED": {
            "cost2x_net_bps": 240.88708199065968,
            "net_bps": 271.7503081701074
          }
        },
        "symbol_count": 1,
        "symbols": [
          "ETH-USDT"
        ],
        "unit_loss_T": 0,
        "unit_winner_T": 1
      },
      {
        "T": 1,
        "exit_ms": 1784851200000,
        "origin_keys": [
          "ab2a2b1541e2af29c7ebd20a9a64c6e7348ca43ef05eb7855304fe34d2515a65"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": 6.787268770401852,
            "net_bps": 31.78726877040185
          },
          "B_RISK": {
            "cost2x_net_bps": 6.787268770401852,
            "net_bps": 31.78726877040185
          },
          "C_FIXED": {
            "cost2x_net_bps": 6.757322941987565,
            "net_bps": 31.647021473800258
          }
        },
        "symbol_count": 1,
        "symbols": [
          "BTC-USDT"
        ],
        "unit_loss_T": 0,
        "unit_winner_T": 1
      },
      {
        "T": 2,
        "exit_ms": 1784908800000,
        "origin_keys": [
          "b005e4d1d431dfabd2c4d12d0205b33f3fa3cfd3a01ef62299888eaf438b4245",
          "fe5abbc5dd9ef292ad6a800292338342013096ae76e0cdda1294205ca0a16330"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -650.3585735981028,
            "net_bps": -599.978196686076
          },
          "B_RISK": {
            "cost2x_net_bps": -650.3585735981028,
            "net_bps": -599.978196686076
          },
          "C_FIXED": {
            "cost2x_net_bps": -647.4891533774598,
            "net_bps": -597.3310576470822
          }
        },
        "symbol_count": 2,
        "symbols": [
          "LINK-USDT",
          "SOL-USDT"
        ],
        "unit_loss_T": 2,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1785182400000,
        "origin_keys": [
          "84b9483292abbf26e56f2460135f9f76d6a9e95821073d80c342cb2d3fc55d3a"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -449.8396403650029,
            "net_bps": -429.8396403650029
          },
          "B_RISK": {
            "cost2x_net_bps": -449.8396403650029,
            "net_bps": -429.8396403650029
          },
          "C_FIXED": {
            "cost2x_net_bps": -447.8549214537585,
            "net_bps": -427.9431626283083
          }
        },
        "symbol_count": 1,
        "symbols": [
          "HYPE-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1785254400000,
        "origin_keys": [
          "d6af7453485b4ffec7745f4b952aa50d376b3e08e1c9dd450f69d87342bef175"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -133.73109640831711,
            "net_bps": -113.73109640831711
          },
          "B_RISK": {
            "cost2x_net_bps": -133.73109640831711,
            "net_bps": -113.73109640831711
          },
          "C_FIXED": {
            "cost2x_net_bps": -133.14106695727168,
            "net_bps": -113.22930813182153
          }
        },
        "symbol_count": 1,
        "symbols": [
          "BCH-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1785974400000,
        "origin_keys": [
          "e2ee772a775c57ef6f6b059f00d842055e54bba3605202bd51555f9d3260740a"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -182.60794764670248,
            "net_bps": -148.74953813142525
          },
          "B_RISK": {
            "cost2x_net_bps": -182.60794764670248,
            "net_bps": -148.74953813142525
          },
          "C_FIXED": {
            "cost2x_net_bps": -181.8022706575784,
            "net_bps": -148.09324643350206
          }
        },
        "symbol_count": 1,
        "symbols": [
          "1000PEPE-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 2,
        "exit_ms": 1786464000000,
        "origin_keys": [
          "7cde4b543006fb8c9d2138a83226b490da703904eab4e4496115462252268705",
          "de18c3d895e5ac61eb712cc3dd5168f660d9d03f94c65336e237d33f0c5408ef"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -630.5901770515388,
            "net_bps": -577.8917675362616
          },
          "B_RISK": {
            "cost2x_net_bps": -630.5901770515388,
            "net_bps": -577.8917675362616
          },
          "C_FIXED": {
            "cost2x_net_bps": -627.8079761574077,
            "net_bps": -575.3420751197573
          }
        },
        "symbol_count": 2,
        "symbols": [
          "1000PEPE-USDT",
          "ETH-USDT"
        ],
        "unit_loss_T": 2,
        "unit_winner_T": 0
      },
      {
        "T": 1,
        "exit_ms": 1786492800000,
        "origin_keys": [
          "369bc66780e9c80e600445beeb75b248437a03e18ad94379ada3964623cc56d7"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": -62.708874792917584,
            "net_bps": -25.70887479291758
          },
          "B_RISK": {
            "cost2x_net_bps": -62.708874792917584,
            "net_bps": -25.70887479291758
          },
          "C_FIXED": {
            "cost2x_net_bps": -62.432199554596274,
            "net_bps": -25.595445727513482
          }
        },
        "symbol_count": 1,
        "symbols": [
          "BTC-USDT"
        ],
        "unit_loss_T": 1,
        "unit_winner_T": 0
      },
      {
        "T": 4,
        "exit_ms": 1787529600000,
        "origin_keys": [
          "0885a5740d9d7680986d09077031be501313f4588115afee33c0cd8b28e816d3",
          "254874089657dee5a2f36bb9bd1cf8c9a786cfe709b1f6df29229eccbe214a45",
          "4999f99153ed39cf58046aea603e500de7337a8f914896b6d167d57ff2ddd00b",
          "811b7a73c0c6e4ff61e0143d6fac907c10babe6954b7451207ae435548e7c8e3"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": 8207.224836428624,
            "net_bps": 8321.463622855928
          },
          "B_RISK": {
            "cost2x_net_bps": 8207.224836428624,
            "net_bps": 8321.463622855928
          },
          "C_FIXED": {
            "cost2x_net_bps": 8171.014078460567,
            "net_bps": 8284.748836653196
          }
        },
        "symbol_count": 4,
        "symbols": [
          "1000PEPE-USDT",
          "BTC-USDT",
          "ETH-USDT",
          "LINK-USDT"
        ],
        "unit_loss_T": 0,
        "unit_winner_T": 4
      },
      {
        "T": 1,
        "exit_ms": 1787702400000,
        "origin_keys": [
          "40ebc4356d6f9e0d5c7e7c83ec57b8f7870c55be0ac3b98c4827c6dcc05f5cae"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": 3527.4770018119043,
            "net_bps": 3570.087001811904
          },
          "B_RISK": {
            "cost2x_net_bps": 3527.4770018119043,
            "net_bps": 3570.087001811904
          },
          "C_FIXED": {
            "cost2x_net_bps": 3511.9135661200316,
            "net_bps": 3554.335568297653
          }
        },
        "symbol_count": 1,
        "symbols": [
          "HYPE-USDT"
        ],
        "unit_loss_T": 0,
        "unit_winner_T": 1
      },
      {
        "T": 1,
        "exit_ms": 1788048000000,
        "origin_keys": [
          "9d1db065e5e0eb36d9c8ce8c640427a2b089c80b83c9473c725c5c99c2a10e4f"
        ],
        "stages": {
          "A_Q0": {
            "cost2x_net_bps": 611.5358276231491,
            "net_bps": 639.5358276231491
          },
          "B_RISK": {
            "cost2x_net_bps": 560.166201403122,
            "net_bps": 585.814173166688
          },
          "C_FIXED": {
            "cost2x_net_bps": 608.8376956377101,
            "net_bps": 636.7141579933403
          }
        },
        "symbol_count": 1,
        "symbols": [
          "SOL-USDT"
        ],
        "unit_loss_T": 0,
        "unit_winner_T": 1
      }
    ],
    "thirty_day_blocks_proven_independent": false
  },
  "economic_questions": {
    "A_Q0": {
      "terminal_cost2_positive": true,
      "terminal_net_positive": true
    },
    "B_RISK": {
      "terminal_cost2_positive": true,
      "terminal_net_positive": true
    },
    "B_minus_C_terminal_net_bps": -21.09475173676492,
    "independent_increment_supported": false
  },
  "uncertainty": {
    "N_effective": null,
    "approximate_calendar_blocks": 4.0,
    "block_days": 30,
    "calendar_days": 120,
    "calendar_last_day": "2026-09-04",
    "calendar_start": "2026-05-08",
    "child_marked_delta_sum_bps": 7261.47103585869,
    "child_minus_parent_95pct_interval_bps_per_day": [
      -0.3769037550379577,
      0.5230513863558907
    ],
    "child_minus_parent_95pct_interval_calendar_sum_bps": [
      -45.22845060455492,
      62.766166362706876
    ],
    "child_minus_parent_marked_delta_sum_bps": -21.094751736765584,
    "child_minus_parent_mean_daily_bps": -0.17578959780637987,
    "evidence_type": "SEEN_DATA_REPLICATION",
    "formal_credit": 0,
    "independent": false,
    "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; SEEN_DATA_REUSE_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
    "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
    "operating_adoption": false,
    "parent_marked_delta_sum_bps": 7282.565787595455,
    "resamples": 1000,
    "seed": 1178,
    "status": "COMPUTED"
  }
}
```

The unchanged numerical goal does not grant independent validation or adoption. All original sign cohorts, winner retention, per-stage recoveries, same-calendar marked-DD contributions and full paths are in weighted_accounting.json.gz. Outcome-based groups are diagnostics only.

Paired noncircular30day/1000draw/seed1178 uncertainty conditions on realized C. Long holds and market clusters may exceed30days; prior data reuse and model selection remain uncorrected. Counts are not independent samples.

## Preserved budget and operational boundaries

Candidate cumulative26, candidate remaining0, new candidates0. Separate seen-period economic evaluation1/1. Independent comparison0/1 and priorNOT_RUN preserved. Exact result reproduction is not another evaluation. Q0/Q1/Q2/B original states unchanged. No deploy, G5B replacement, account sizing, formal credit or new paid AI.

Future collection/validation is not activated by this result. See DESIGN.md and receipt.future_readiness for actual source paths and missing minimal prospective connection. It did not block this authorized replication.
