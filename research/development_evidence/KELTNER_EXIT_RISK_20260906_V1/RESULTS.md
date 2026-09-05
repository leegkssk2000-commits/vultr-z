# Keltner: average economics and loss-sequence risk

Existing PR1184 trades and exit traces only. No rerun of the breakeven exit, new trading simulation or holdout access. All amounts are modelled entry-notional trade bps, not account returns.

| Population | T | Net E | PF | WR % | Payoff | Cost2 E | Exposure days | Max grouped streak loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 217 | -2.9223 | 0.9866 | 47.47 | 1.0919 | -24.2163 | 434.0000 | 7709.3138 |
| fixed | 217 | 16.7913 | 1.1072 | 30.88 | 2.4788 | -3.9069 | 315.6667 | 8327.0067 |
| full | 254 | 23.7171 | 1.1567 | 29.92 | 2.7090 | 3.0420 | 364.1667 | 11808.4402 |

Maxima occur over different windows and are not an additive causal loss decomposition. Same-calendar-window accounting separates exit amount, exit timing, excluded entries and new entries. Simultaneous exits are netted before a streak resets.

```json
{
  "same_window_comparisons": [
    {
      "bridges": {
        "fixed_minus_parent": {
          "child_closed_T": 10,
          "child_net_bps": -6400.490269176419,
          "common_child_inside_T": 10,
          "common_exit_amount_change_at_child_close_bps": 271.87101785033747,
          "common_parent_inside_T": 12,
          "common_parent_net_timing_shift_bps": 1036.952533562725,
          "end_ms": 1762243200000,
          "excluded_inside_T": 0,
          "excluded_parent_net_effect_bps": -0.0,
          "net_delta_bps": 1308.823551413063,
          "new_inside_T": 0,
          "new_trade_net_bps": 0.0,
          "parent_closed_T": 12,
          "parent_net_bps": -7709.313820589482,
          "parity": "PASS",
          "parity_residual_bps": 4.547473508864641e-13,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1760011200000
        },
        "full_minus_fixed": {
          "child_closed_T": 11,
          "child_net_bps": -6320.034060810276,
          "common_child_inside_T": 8,
          "common_exit_amount_change_at_child_close_bps": 0.0,
          "common_parent_inside_T": 8,
          "common_parent_net_timing_shift_bps": 0.0,
          "end_ms": 1762243200000,
          "excluded_inside_T": 2,
          "excluded_parent_net_effect_bps": 1916.4197427720583,
          "net_delta_bps": 80.45620836614307,
          "new_inside_T": 3,
          "new_trade_net_bps": -1835.9635344059145,
          "parent_closed_T": 10,
          "parent_net_bps": -6400.490269176419,
          "parity": "PASS",
          "parity_residual_bps": -6.821210263296962e-13,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1760011200000
        },
        "full_minus_parent": {
          "child_closed_T": 11,
          "child_net_bps": -6320.034060810276,
          "common_child_inside_T": 8,
          "common_exit_amount_change_at_child_close_bps": 271.87101785033747,
          "common_parent_inside_T": 10,
          "common_parent_net_timing_shift_bps": 1036.952533562725,
          "end_ms": 1762243200000,
          "excluded_inside_T": 2,
          "excluded_parent_net_effect_bps": 1916.4197427720583,
          "net_delta_bps": 1389.279759779206,
          "new_inside_T": 3,
          "new_trade_net_bps": -1835.9635344059145,
          "parent_closed_T": 12,
          "parent_net_bps": -7709.313820589482,
          "parity": "PASS",
          "parity_residual_bps": -2.2737367544323206e-13,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1760011200000
        }
      },
      "end_utc": "2025-11-04T08:00:00+00:00",
      "nonnegative_reset_observations": {
        "fixed_minus_parent": [],
        "full_minus_fixed": [],
        "full_minus_parent": []
      },
      "sources": [
        "parent"
      ],
      "start_utc": "2025-10-09T12:00:00+00:00"
    },
    {
      "bridges": {
        "fixed_minus_parent": {
          "child_closed_T": 22,
          "child_net_bps": -8327.006677833524,
          "common_child_inside_T": 22,
          "common_exit_amount_change_at_child_close_bps": 3368.0075794804075,
          "common_parent_inside_T": 21,
          "common_parent_net_timing_shift_bps": -148.97553262136927,
          "end_ms": 1765108800000,
          "excluded_inside_T": 0,
          "excluded_parent_net_effect_bps": -0.0,
          "net_delta_bps": 3219.032046859038,
          "new_inside_T": 0,
          "new_trade_net_bps": 0.0,
          "parent_closed_T": 21,
          "parent_net_bps": -11546.038724692562,
          "parity": "PASS",
          "parity_residual_bps": 0.0,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1759982400000
        },
        "full_minus_fixed": {
          "child_closed_T": 25,
          "child_net_bps": -8559.98673558281,
          "common_child_inside_T": 19,
          "common_exit_amount_change_at_child_close_bps": 0.0,
          "common_parent_inside_T": 19,
          "common_parent_net_timing_shift_bps": 0.0,
          "end_ms": 1765108800000,
          "excluded_inside_T": 3,
          "excluded_parent_net_effect_bps": 2081.8045142707388,
          "net_delta_bps": -232.98005774928606,
          "new_inside_T": 6,
          "new_trade_net_bps": -2314.7845720200244,
          "parent_closed_T": 22,
          "parent_net_bps": -8327.006677833524,
          "parity": "PASS",
          "parity_residual_bps": -4.547473508864641e-13,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1759982400000
        },
        "full_minus_parent": {
          "child_closed_T": 25,
          "child_net_bps": -8559.98673558281,
          "common_child_inside_T": 19,
          "common_exit_amount_change_at_child_close_bps": 3727.779539407346,
          "common_parent_inside_T": 18,
          "common_parent_net_timing_shift_bps": -148.97553262136927,
          "end_ms": 1765108800000,
          "excluded_inside_T": 3,
          "excluded_parent_net_effect_bps": 1722.0325543438005,
          "net_delta_bps": 2986.051989109752,
          "new_inside_T": 6,
          "new_trade_net_bps": -2314.7845720200244,
          "parent_closed_T": 21,
          "parent_net_bps": -11546.038724692562,
          "parity": "PASS",
          "parity_residual_bps": -9.094947017729282e-13,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1759982400000
        }
      },
      "end_utc": "2025-12-07T12:00:00+00:00",
      "nonnegative_reset_observations": {
        "fixed_minus_parent": [
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 14.949245057036563,
              "trades": [
                {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 14.949245057036563
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1762977600000,
                  "identity": "cfba327a8dbc63404a800b325ca5e7992c97eff2a2e34b4883e1f6c5c13938cb",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -139.7698847460294,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 6.7905652247235615,
              "trades": [
                {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 6.7905652247235615
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764273600000,
                  "identity": "c904f6f955e39ec103294664f7babca785675e84fb39a43f32036db62f1e78c6",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -19.812653390037077,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 194.38718842825776,
              "trades": [
                {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 194.38718842825776
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764388800000,
                  "identity": "02cbfba7dd55230f8a2935ebc3c39fddbd72e1da166c42298250c07a1e53a36f",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -165.38477149868075,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          }
        ],
        "full_minus_fixed": [],
        "full_minus_parent": [
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 14.949245057036563,
              "trades": [
                {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 14.949245057036563
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1762977600000,
                  "identity": "cfba327a8dbc63404a800b325ca5e7992c97eff2a2e34b4883e1f6c5c13938cb",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -139.7698847460294,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 6.7905652247235615,
              "trades": [
                {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 6.7905652247235615
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764273600000,
                  "identity": "c904f6f955e39ec103294664f7babca785675e84fb39a43f32036db62f1e78c6",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -19.812653390037077,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 194.38718842825776,
              "trades": [
                {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 194.38718842825776
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": null,
                "reference": {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          }
        ]
      },
      "sources": [
        "fixed"
      ],
      "start_utc": "2025-10-09T04:00:00+00:00"
    },
    {
      "bridges": {
        "fixed_minus_parent": {
          "child_closed_T": 32,
          "child_net_bps": -11200.820060240814,
          "common_child_inside_T": 32,
          "common_exit_amount_change_at_child_close_bps": 2381.3014325192134,
          "common_parent_inside_T": 31,
          "common_parent_net_timing_shift_bps": -148.97553262136927,
          "end_ms": 1765108800000,
          "excluded_inside_T": 0,
          "excluded_parent_net_effect_bps": -0.0,
          "net_delta_bps": 2232.3258998978436,
          "new_inside_T": 0,
          "new_trade_net_bps": 0.0,
          "parent_closed_T": 31,
          "parent_net_bps": -13433.145960138658,
          "parity": "PASS",
          "parity_residual_bps": -4.547473508864641e-13,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1758254400000
        },
        "full_minus_fixed": {
          "child_closed_T": 37,
          "child_net_bps": -11808.44023572217,
          "common_child_inside_T": 28,
          "common_exit_amount_change_at_child_close_bps": 0.0,
          "common_parent_inside_T": 28,
          "common_parent_net_timing_shift_bps": 0.0,
          "end_ms": 1765108800000,
          "excluded_inside_T": 4,
          "excluded_parent_net_effect_bps": 2079.2947600439074,
          "net_delta_bps": -607.6201754813555,
          "new_inside_T": 9,
          "new_trade_net_bps": -2686.9149355252625,
          "parent_closed_T": 32,
          "parent_net_bps": -11200.820060240814,
          "parity": "PASS",
          "parity_residual_bps": -4.547473508864641e-13,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1758254400000
        },
        "full_minus_parent": {
          "child_closed_T": 37,
          "child_net_bps": -11808.44023572217,
          "common_child_inside_T": 28,
          "common_exit_amount_change_at_child_close_bps": 2741.073392446152,
          "common_parent_inside_T": 27,
          "common_parent_net_timing_shift_bps": -148.97553262136927,
          "end_ms": 1765108800000,
          "excluded_inside_T": 4,
          "excluded_parent_net_effect_bps": 1719.522800116969,
          "net_delta_bps": 1624.705724416488,
          "new_inside_T": 9,
          "new_trade_net_bps": -2686.9149355252625,
          "parent_closed_T": 31,
          "parent_net_bps": -13433.145960138658,
          "parity": "PASS",
          "parity_residual_bps": -1.1368683772161603e-12,
          "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
          "start_ms": 1758254400000
        }
      },
      "end_utc": "2025-12-07T12:00:00+00:00",
      "nonnegative_reset_observations": {
        "fixed_minus_parent": [
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1759780800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-10-06T20:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1759780800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 352.0081296870248,
              "trades": [
                {
                  "entry_ts": 1759608000000,
                  "exit_ts": 1759780800000,
                  "identity": "e977568395134b58228f46c2d02df2e0d6787a67ba9f0ff151e40dbee3cf61b2",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 352.0081296870248,
                  "side": "long",
                  "signal_ts": 1759608000000,
                  "symbol": "SOL-USDT"
                }
              ],
              "utc": "2025-10-06T20:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 352.0081296870248
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1759608000000,
                  "exit_ts": 1759694400000,
                  "identity": "239656c4f01d34000a6922682b7e2f467667d4461237a9db3b5a756e1e4b1aa8",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -13.25465230598345,
                  "side": "long",
                  "signal_ts": 1759608000000,
                  "symbol": "SOL-USDT"
                },
                "reference": {
                  "entry_ts": 1759608000000,
                  "exit_ts": 1759780800000,
                  "identity": "e977568395134b58228f46c2d02df2e0d6787a67ba9f0ff151e40dbee3cf61b2",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 352.0081296870248,
                  "side": "long",
                  "signal_ts": 1759608000000,
                  "symbol": "SOL-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1759809600000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-10-07T04:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 2,
              "exit_ts": 1759809600000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 647.1416082145504,
              "trades": [
                {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "20270f9710dd5c24aa580a66accd263524fbba214de3a317b3a9672243cf85c1",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 218.309409606327,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "1000PEPE-USDT"
                },
                {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "d666281426f64917d228f665756ee7d7caa92777771ba308a1432d7305d87bed",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 428.8321986082234,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "LINK-USDT"
                }
              ],
              "utc": "2025-10-07T04:00:00+00:00",
              "win_T": 2,
              "winner_offset_bps": 647.1416082145504
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759694400000,
                  "identity": "84caa62717323a17b81f7cfe9129c14aae05609a42365750820b5bd1c2d220e9",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -227.45800965249038,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "1000PEPE-USDT"
                },
                "reference": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "20270f9710dd5c24aa580a66accd263524fbba214de3a317b3a9672243cf85c1",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 218.309409606327,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "1000PEPE-USDT"
                }
              },
              {
                "child": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759694400000,
                  "identity": "35b2c5f4f7922f1beda9f3a705f7d07b057f1b118ca0eed4a1a67d71f4ce6d96",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -203.0387111210557,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "LINK-USDT"
                },
                "reference": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "d666281426f64917d228f665756ee7d7caa92777771ba308a1432d7305d87bed",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 428.8321986082234,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "LINK-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 14.949245057036563,
              "trades": [
                {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 14.949245057036563
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1762977600000,
                  "identity": "cfba327a8dbc63404a800b325ca5e7992c97eff2a2e34b4883e1f6c5c13938cb",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -139.7698847460294,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 6.7905652247235615,
              "trades": [
                {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 6.7905652247235615
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764273600000,
                  "identity": "c904f6f955e39ec103294664f7babca785675e84fb39a43f32036db62f1e78c6",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -19.812653390037077,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 194.38718842825776,
              "trades": [
                {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 194.38718842825776
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764388800000,
                  "identity": "02cbfba7dd55230f8a2935ebc3c39fddbd72e1da166c42298250c07a1e53a36f",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -165.38477149868075,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          }
        ],
        "full_minus_fixed": [
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1758312000000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-09-19T20:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1758312000000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 2.5097542268315465,
              "trades": [
                {
                  "entry_ts": 1758139200000,
                  "exit_ts": 1758312000000,
                  "identity": "b264a71caf03cc7896d6bbc32789db10fa2829b473f4ebc832a2c5b0de113d12",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 2.5097542268315465,
                  "side": "long",
                  "signal_ts": 1758139200000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-09-19T20:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 2.5097542268315465
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": null,
                "reference": {
                  "entry_ts": 1758139200000,
                  "exit_ts": 1758312000000,
                  "identity": "b264a71caf03cc7896d6bbc32789db10fa2829b473f4ebc832a2c5b0de113d12",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 2.5097542268315465,
                  "side": "long",
                  "signal_ts": 1758139200000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 2,
              "exit_ts": 1759795200000,
              "loss_T": 1,
              "negative_trade_loss_bps": 344.0086074392874,
              "net_trade_sum_bps": -212.91483094276484,
              "trades": [
                {
                  "entry_ts": 1759622400000,
                  "exit_ts": 1759795200000,
                  "identity": "003fb27ecb7d07fb9c34f6acfbb600ff0d277ae55fb3fe2d26c3368f86ffefba",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 131.09377649652257,
                  "side": "long",
                  "signal_ts": 1759622400000,
                  "symbol": "BCH-USDT"
                },
                {
                  "entry_ts": 1759766400000,
                  "exit_ts": 1759795200000,
                  "identity": "ac0f9ec51a83fb4c367c2ee150edda36cd40fa36bb54e869570f57f65449d46d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -344.0086074392874,
                  "side": "long",
                  "signal_ts": 1759766400000,
                  "symbol": "HYPE-USDT"
                }
              ],
              "utc": "2025-10-07T00:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 131.09377649652257
            },
            "new_same_timestamp_trades": [
              {
                "entry_ts": 1759766400000,
                "exit_ts": 1759795200000,
                "identity": "ac0f9ec51a83fb4c367c2ee150edda36cd40fa36bb54e869570f57f65449d46d",
                "lane_id": "keltner_trend_main",
                "net_bps": -344.0086074392874,
                "side": "long",
                "signal_ts": 1759766400000,
                "symbol": "HYPE-USDT"
              }
            ],
            "observation": "NONNEGATIVE_RESET_ABSENT_AFTER_ACTUAL_SIMULTANEOUS_NETTING",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1759795200000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 131.09377649652257,
              "trades": [
                {
                  "entry_ts": 1759622400000,
                  "exit_ts": 1759795200000,
                  "identity": "003fb27ecb7d07fb9c34f6acfbb600ff0d277ae55fb3fe2d26c3368f86ffefba",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 131.09377649652257,
                  "side": "long",
                  "signal_ts": 1759622400000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-10-07T00:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 131.09377649652257
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1759622400000,
                  "exit_ts": 1759795200000,
                  "identity": "003fb27ecb7d07fb9c34f6acfbb600ff0d277ae55fb3fe2d26c3368f86ffefba",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 131.09377649652257,
                  "side": "long",
                  "signal_ts": 1759622400000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1759622400000,
                  "exit_ts": 1759795200000,
                  "identity": "003fb27ecb7d07fb9c34f6acfbb600ff0d277ae55fb3fe2d26c3368f86ffefba",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 131.09377649652257,
                  "side": "long",
                  "signal_ts": 1759622400000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          }
        ],
        "full_minus_parent": [
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1758312000000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-09-19T20:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1758312000000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 2.5097542268315465,
              "trades": [
                {
                  "entry_ts": 1758139200000,
                  "exit_ts": 1758312000000,
                  "identity": "b264a71caf03cc7896d6bbc32789db10fa2829b473f4ebc832a2c5b0de113d12",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 2.5097542268315465,
                  "side": "long",
                  "signal_ts": 1758139200000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-09-19T20:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 2.5097542268315465
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": null,
                "reference": {
                  "entry_ts": 1758139200000,
                  "exit_ts": 1758312000000,
                  "identity": "b264a71caf03cc7896d6bbc32789db10fa2829b473f4ebc832a2c5b0de113d12",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 2.5097542268315465,
                  "side": "long",
                  "signal_ts": 1758139200000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1759780800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-10-06T20:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1759780800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 352.0081296870248,
              "trades": [
                {
                  "entry_ts": 1759608000000,
                  "exit_ts": 1759780800000,
                  "identity": "e977568395134b58228f46c2d02df2e0d6787a67ba9f0ff151e40dbee3cf61b2",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 352.0081296870248,
                  "side": "long",
                  "signal_ts": 1759608000000,
                  "symbol": "SOL-USDT"
                }
              ],
              "utc": "2025-10-06T20:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 352.0081296870248
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1759608000000,
                  "exit_ts": 1759694400000,
                  "identity": "239656c4f01d34000a6922682b7e2f467667d4461237a9db3b5a756e1e4b1aa8",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -13.25465230598345,
                  "side": "long",
                  "signal_ts": 1759608000000,
                  "symbol": "SOL-USDT"
                },
                "reference": {
                  "entry_ts": 1759608000000,
                  "exit_ts": 1759780800000,
                  "identity": "e977568395134b58228f46c2d02df2e0d6787a67ba9f0ff151e40dbee3cf61b2",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 352.0081296870248,
                  "side": "long",
                  "signal_ts": 1759608000000,
                  "symbol": "SOL-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1759809600000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-10-07T04:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 2,
              "exit_ts": 1759809600000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 647.1416082145504,
              "trades": [
                {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "20270f9710dd5c24aa580a66accd263524fbba214de3a317b3a9672243cf85c1",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 218.309409606327,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "1000PEPE-USDT"
                },
                {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "d666281426f64917d228f665756ee7d7caa92777771ba308a1432d7305d87bed",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 428.8321986082234,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "LINK-USDT"
                }
              ],
              "utc": "2025-10-07T04:00:00+00:00",
              "win_T": 2,
              "winner_offset_bps": 647.1416082145504
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759694400000,
                  "identity": "84caa62717323a17b81f7cfe9129c14aae05609a42365750820b5bd1c2d220e9",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -227.45800965249038,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "1000PEPE-USDT"
                },
                "reference": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "20270f9710dd5c24aa580a66accd263524fbba214de3a317b3a9672243cf85c1",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 218.309409606327,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "1000PEPE-USDT"
                }
              },
              {
                "child": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759694400000,
                  "identity": "35b2c5f4f7922f1beda9f3a705f7d07b057f1b118ca0eed4a1a67d71f4ce6d96",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -203.0387111210557,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "LINK-USDT"
                },
                "reference": {
                  "entry_ts": 1759636800000,
                  "exit_ts": 1759809600000,
                  "identity": "d666281426f64917d228f665756ee7d7caa92777771ba308a1432d7305d87bed",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 428.8321986082234,
                  "side": "long",
                  "signal_ts": 1759636800000,
                  "symbol": "LINK-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1763092800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 14.949245057036563,
              "trades": [
                {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-14T04:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 14.949245057036563
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1762977600000,
                  "identity": "cfba327a8dbc63404a800b325ca5e7992c97eff2a2e34b4883e1f6c5c13938cb",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -139.7698847460294,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1762920000000,
                  "exit_ts": 1763092800000,
                  "identity": "fe7be8d09f510d8e1b710275631d3e67e87e92b160028ad0046e236e63b8274d",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 14.949245057036563,
                  "side": "long",
                  "signal_ts": 1762920000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764316800000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 6.7905652247235615,
              "trades": [
                {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-28T08:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 6.7905652247235615
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764273600000,
                  "identity": "c904f6f955e39ec103294664f7babca785675e84fb39a43f32036db62f1e78c6",
                  "lane_id": "keltner_trend_main",
                  "net_bps": -19.812653390037077,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                },
                "reference": {
                  "entry_ts": 1764144000000,
                  "exit_ts": 1764316800000,
                  "identity": "d43a7e8eecc04ee5a85fb6f9d3a6d065b3992d558e55449cdd207bc7f6b34f08",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 6.7905652247235615,
                  "side": "long",
                  "signal_ts": 1764144000000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          },
          {
            "child_same_timestamp_group": {
              "T": 0,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 0,
              "trades": [],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 0,
              "winner_offset_bps": 0.0
            },
            "new_same_timestamp_trades": [],
            "observation": "NO_CLOSE_GROUP_AT_ORIGINAL_RESET_TIME",
            "original_reset_group": {
              "T": 1,
              "exit_ts": 1764518400000,
              "loss_T": 0,
              "negative_trade_loss_bps": -0.0,
              "net_trade_sum_bps": 194.38718842825776,
              "trades": [
                {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              ],
              "utc": "2025-11-30T16:00:00+00:00",
              "win_T": 1,
              "winner_offset_bps": 194.38718842825776
            },
            "reference_entry_actual_child_outcomes": [
              {
                "child": null,
                "reference": {
                  "entry_ts": 1764345600000,
                  "exit_ts": 1764518400000,
                  "identity": "269d70e72d1a2dd3d6ceef1af97c35fe41762edbc4ff978b915a84adf6c46f66",
                  "lane_id": "keltner_trend_main",
                  "net_bps": 194.38718842825776,
                  "side": "long",
                  "signal_ts": 1764345600000,
                  "symbol": "BCH-USDT"
                }
              }
            ],
            "reference_reset_kind": "POSITIVE_NET_RESET",
            "same_timestamp_accounting_only": true
          }
        ]
      },
      "sources": [
        "full"
      ],
      "start_utc": "2025-09-19T04:00:00+00:00"
    }
  ],
  "whole_development_bridges": {
    "fixed_minus_parent": {
      "child_closed_T": 217,
      "child_net_bps": 3643.7024337918347,
      "common_child_inside_T": 217,
      "common_exit_amount_change_at_child_close_bps": 4277.836357672556,
      "common_parent_inside_T": 217,
      "common_parent_net_timing_shift_bps": 0.0,
      "end_ms": null,
      "excluded_inside_T": 0,
      "excluded_parent_net_effect_bps": -0.0,
      "net_delta_bps": 4277.836357672555,
      "new_inside_T": 0,
      "new_trade_net_bps": 0.0,
      "parent_closed_T": 217,
      "parent_net_bps": -634.1339238807209,
      "parity": "PASS",
      "parity_residual_bps": -9.094947017729282e-13,
      "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
      "start_ms": null
    },
    "full_minus_fixed": {
      "child_closed_T": 254,
      "child_net_bps": 6024.152156845897,
      "common_child_inside_T": 200,
      "common_exit_amount_change_at_child_close_bps": 0.0,
      "common_parent_inside_T": 200,
      "common_parent_net_timing_shift_bps": 0.0,
      "end_ms": null,
      "excluded_inside_T": 17,
      "excluded_parent_net_effect_bps": 4073.46206615017,
      "net_delta_bps": 2380.449723054062,
      "new_inside_T": 54,
      "new_trade_net_bps": -1693.0123430961078,
      "parent_closed_T": 217,
      "parent_net_bps": 3643.7024337918347,
      "parity": "PASS",
      "parity_residual_bps": 0.0,
      "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
      "start_ms": null
    },
    "full_minus_parent": {
      "child_closed_T": 254,
      "child_net_bps": 6024.152156845897,
      "common_child_inside_T": 200,
      "common_exit_amount_change_at_child_close_bps": 5585.943690283758,
      "common_parent_inside_T": 200,
      "common_parent_net_timing_shift_bps": 0.0,
      "end_ms": null,
      "excluded_inside_T": 17,
      "excluded_parent_net_effect_bps": 2765.354733538968,
      "net_delta_bps": 6658.286080726617,
      "new_inside_T": 54,
      "new_trade_net_bps": -1693.0123430961078,
      "parent_closed_T": 217,
      "parent_net_bps": -634.1339238807209,
      "parity": "PASS",
      "parity_residual_bps": -9.094947017729282e-13,
      "scope": "DESCRIPTIVE_ACCOUNTING_BRIDGE_NOT_REPLAYED_POLICY",
      "start_ms": null
    }
  },
  "worst_runs": {
    "fixed": {
      "T": 22,
      "end_ms": 1765108800000,
      "end_utc": "2025-12-07T12:00:00+00:00",
      "group_exit_timestamps": [
        1759982400000,
        1760011200000,
        1760083200000,
        1760126400000,
        1760140800000,
        1761681600000,
        1761825600000,
        1761897600000,
        1761912000000,
        1761940800000,
        1762243200000,
        1762977600000,
        1764273600000,
        1764360000000,
        1764388800000,
        1764547200000,
        1764691200000,
        1765094400000,
        1765108800000
      ],
      "length_groups": 19,
      "loss_trade_sum_bps": 8327.006677833524,
      "negative_trade_loss_bps": 8327.006677833524,
      "simultaneous_groups": 2,
      "start_ms": 1759982400000,
      "start_utc": "2025-10-09T04:00:00+00:00",
      "winner_offset_bps": 0.0
    },
    "full": {
      "T": 37,
      "end_ms": 1765108800000,
      "end_utc": "2025-12-07T12:00:00+00:00",
      "group_exit_timestamps": [
        1758254400000,
        1758283200000,
        1758528000000,
        1758600000000,
        1759680000000,
        1759694400000,
        1759795200000,
        1759824000000,
        1759982400000,
        1760083200000,
        1760126400000,
        1760140800000,
        1760184000000,
        1761681600000,
        1761825600000,
        1761897600000,
        1761912000000,
        1761940800000,
        1762171200000,
        1762977600000,
        1763049600000,
        1764273600000,
        1764360000000,
        1764388800000,
        1764547200000,
        1764561600000,
        1764691200000,
        1765094400000,
        1765108800000
      ],
      "length_groups": 29,
      "loss_trade_sum_bps": 11808.44023572217,
      "negative_trade_loss_bps": 11939.534012218692,
      "simultaneous_groups": 6,
      "start_ms": 1758254400000,
      "start_utc": "2025-09-19T04:00:00+00:00",
      "winner_offset_bps": 131.09377649652257
    },
    "parent": {
      "T": 12,
      "end_ms": 1762243200000,
      "end_utc": "2025-11-04T08:00:00+00:00",
      "group_exit_timestamps": [
        1760011200000,
        1760097600000,
        1760126400000,
        1760140800000,
        1761796800000,
        1761825600000,
        1761897600000,
        1761912000000,
        1762056000000,
        1762243200000
      ],
      "length_groups": 10,
      "loss_trade_sum_bps": 7709.313820589482,
      "negative_trade_loss_bps": 7709.313820589482,
      "simultaneous_groups": 1,
      "start_ms": 1760011200000,
      "start_utc": "2025-10-09T12:00:00+00:00",
      "winner_offset_bps": 0.0
    }
  }
}
```

Trigger-time evidence uses the original EMA20/EMA50 structure. Outcome labels are stored separately and are never feature inputs. Large winners use an outcome-only top-decile label.

```json
{
  "classes": {
    "cut_large_parent_winner": {
      "T": 1,
      "cost2_delta_bps": -2146.416399165284,
      "cut_winner_profit_bps": 2129.0592944570762,
      "intact_T": 1,
      "intact_fraction": 1.0,
      "net_delta_bps": -2146.416399165284,
      "observables": {
        "close_to_ema50_bps": {
          "median": 47.00368349861872,
          "q25": 47.00368349861872,
          "q75": 47.00368349861872
        },
        "closed_bars_since_arm": {
          "median": 3.0,
          "q25": 3.0,
          "q75": 3.0
        },
        "current_net_mark_bps": {
          "median": -17.246984071049834,
          "q25": -17.246984071049834,
          "q75": -17.246984071049834
        },
        "ema20_to_ema50_bps": {
          "median": 32.04337806970159,
          "q25": 32.04337806970159,
          "q75": 32.04337806970159
        },
        "held_closed_bars": {
          "median": 4.0,
          "q25": 4.0,
          "q75": 4.0
        }
      },
      "saved_loss_bps": 0.0
    },
    "cut_parent_winner": {
      "T": 36,
      "cost2_delta_bps": -11458.064822402614,
      "cut_winner_profit_bps": 8888.043764819837,
      "intact_T": 30,
      "intact_fraction": 0.8333333333333334,
      "net_delta_bps": -11507.72193550858,
      "observables": {
        "close_to_ema50_bps": {
          "median": 105.0874080825992,
          "q25": 36.971409102377066,
          "q75": 158.0562644493577
        },
        "closed_bars_since_arm": {
          "median": 2.5,
          "q25": 1.0,
          "q75": 4.0
        },
        "current_net_mark_bps": {
          "median": -38.825129108473526,
          "q25": -93.56730685051156,
          "q75": -20.47186245015935
        },
        "ema20_to_ema50_bps": {
          "median": 113.61902962157333,
          "q25": 67.24768036363903,
          "q75": 170.27570916164746
        },
        "held_closed_bars": {
          "median": 4.0,
          "q25": 4.0,
          "q75": 5.25
        }
      },
      "saved_loss_bps": 0.0
    },
    "saved_parent_loss": {
      "T": 55,
      "cost2_delta_bps": 16997.253899615826,
      "cut_winner_profit_bps": 0.0,
      "intact_T": 46,
      "intact_fraction": 0.8363636363636363,
      "net_delta_bps": 16930.56921365525,
      "observables": {
        "close_to_ema50_bps": {
          "median": 99.65404815500678,
          "q25": 37.25984391063752,
          "q75": 173.72580573648213
        },
        "closed_bars_since_arm": {
          "median": 2.0,
          "q25": 1.0,
          "q75": 3.0
        },
        "current_net_mark_bps": {
          "median": -73.11325529259742,
          "q25": -115.72825048164655,
          "q75": -30.875112551154785
        },
        "ema20_to_ema50_bps": {
          "median": 139.5192080821417,
          "q25": 82.73889406716029,
          "q75": 195.2947979861508
        },
        "held_closed_bars": {
          "median": 4.0,
          "q25": 3.0,
          "q75": 7.0
        }
      },
      "saved_loss_bps": 16930.56921365525
    }
  },
  "primary_screen": {
    "auxiliary_features_used_for_policy_selection": false,
    "checks": {
      "all_leave_one_symbol_out_positive": false,
      "both_reused_DEV_halves_positive": false,
      "positive_lower_week_bound": false,
      "two_occupied_weeks_per_label": true
    },
    "formal_statistical_pass": false,
    "leave_one_symbol_out": {
      "1000PEPE-USDT": 0.016801075268817245,
      "BCH-USDT": 0.012698412698412653,
      "BTC-USDT": -0.0020590253946465298,
      "ETH-USDT": -0.01577060931899643,
      "HYPE-USDT": 0.005376344086021501,
      "LINK-USDT": -0.015456989247311759,
      "SOL-USDT": -0.01855287569573283
    },
    "method": "JOINT_SYMBOL_TRIGGER_WEEK_BLOCK_BOOTSTRAP; REUSED_DEV_SENSITIVITY_NOT_INDEPENDENT_VALIDATION",
    "nonempty_resamples": 1000,
    "occupied_weeks": {
      "cut_parent_winner": 17,
      "saved_parent_loss": 24
    },
    "passed": false,
    "point_separation": -0.003030303030302939,
    "primary_tests": 1,
    "reused_DEV_halves": {
      "early_DEV": 0.033333333333333326,
      "late_DEV": -0.028314028314028294
    },
    "separation_95pct_interval": [
      -0.17009947447447446,
      0.14533437038733643
    ],
    "thresholds_swept": 0
  }
}
```

**Decision: CLOSE_CURRENT_FAMILY_NO_SUPPORT_IN_PREREGISTERED_SCREEN**

No child has been run by this analysis. A positive screen would require its own frozen parent/code/config/budget before any new child result. A negative screen closes this tested family; it does not discard Keltner or other Top5 lanes.

Reused DEV evidence is adaptive, not independent validation. PR1183 state-child decisions and Break validation REJECT remain unchanged. G5B/G6/order/live authority and collection are unchanged; paid calls = 0.

Data reuse and prior trials:

```json
{
  "Break_validation": "ALREADY_SEEN_REJECT; NO_ACCESS_HERE",
  "Keltner_trials": [
    {
      "PR": 1180,
      "contract": "backend/research/contracts/top5_development_children_v1.json",
      "contract_file_sha256": "5e86b0876052d25d38de466deff50e8966b54f2c6be46bfefc57ee6f4e575a03",
      "lane": {
        "causal_ablation": "Remove this predicate = frozen parent",
        "changed_axes": [
          "ENTRY_ADMISSION"
        ],
        "child_id": "keltner_replacement_trend_pull_long_4h_h12_v2__keltner_prior_extreme_v1",
        "cost_unchanged": true,
        "evidence": {
          "False": {
            "T": 80,
            "mean_net_bps": -43.913243983690776,
            "net_bps": -3513.059518695262,
            "wins": 37
          },
          "True": {
            "T": 137,
            "mean_net_bps": 21.01405543660249,
            "net_bps": 2878.925594814541,
            "wins": 66
          }
        },
        "experiment_id": "TOP5_DEV_20260905_KELTNER_PRIOR_EXTREME_V1",
        "exposure_control": "Fixed-hash parent subset matched to completed child count; not an independent strategy",
        "loss_signature": "EMA_RECLAIM_WITHOUT_PRIOR_HIGH_CLEARANCE",
        "mechanism_and_failure": "EMA reclaim below prior high remains within local resistance; requiring clearance may avoid weak rebounds but can chase price.",
        "native_exit_unchanged": true,
        "native_risk_unchanged": true,
        "no_retune_after_results": true,
        "parameter_provenance": "Ordinal OHLC relationships: previous high/low, signed prior candle body, two-bar containment. No fitted numeric threshold.",
        "parent_id": "keltner_replacement_trend_pull_long_4h_h12_v2",
        "parent_sha256": "ff5cf1f6d3b3ebabc9dca81457c1ffdd26af6e68871cad40bdc85332d4262859",
        "predicate": "close_retains_prior_extreme",
        "runtime_observable": "Closed signal bar and previous two closed bars only",
        "trial_budget_remaining_after_run": 0,
        "trial_ordinal_this_batch": 1
      },
      "same_development_calendar": true
    },
    {
      "PR": 1181,
      "contract": "backend/research/contracts/top5_external_children_v1.json",
      "contract_file_sha256": "4a3864f7e3c4837dfe4becd580360a19e40f49f29b539caade9863ab15c3bc36",
      "lane": {
        "P0": "UNCONFIRMED",
        "changed_axes": [
          "ENTRY_ADMISSION"
        ],
        "child_id": "keltner_replacement_trend_pull_long_4h_h12_v2__prior_atr_bull_context_v1",
        "cost_unchanged": true,
        "experiment_id": "TOP5_EXTERNAL_20260905_KELTNER_TREND_MAIN_V1",
        "failure_signature": "EMA_RECLAIM_DURING_PRIOR_ATR_BEAR_STATE",
        "feature_availability": "Signal bar fully closed, prior DI and ATR state closed earlier; no outcome labels.",
        "formal_PASS": false,
        "mechanism": "Admit EMA reclaim only in previous closed ATR10x3 bull state; reversal winners may be lost.",
        "native_exit_unchanged": true,
        "parameter_provenance": "ADX length14 Wilder convention, only ordinal slope; ATR10x3 from existing native family convention, no threshold fit; published formulas. Not optimized for current data.",
        "parent_id": "keltner_replacement_trend_pull_long_4h_h12_v2",
        "parent_sha256": "ff5cf1f6d3b3ebabc9dca81457c1ffdd26af6e68871cad40bdc85332d4262859",
        "predicate": "prior_Supertrend10x3_bull_state",
        "prior_failed_child": "keltner_replacement_trend_pull_long_4h_h12_v2__keltner_prior_extreme_v1",
        "prior_trials_not_reset": true,
        "risk_unchanged": true,
        "source_ids": [
          "TV_ST",
          "TV_KC",
          "DARWINEX_VIDEO"
        ],
        "trial_budget_remaining_after_run": 0,
        "trial_ordinal_this_batch": 1
      },
      "same_development_calendar": true
    },
    {
      "PR": 1183,
      "contract": "backend/research/contracts/top5_state_children_v1.json",
      "contract_file_sha256": "8afcaa24f81ad3a87072f979ff0ddf15ad5ec5b9593c642ee840d0b99ddfdb82",
      "lane": {
        "child_id": null,
        "exit_risk_cost_unchanged": true,
        "no_post_outcome_retune": true,
        "parent_id": "keltner_replacement_trend_pull_long_4h_h12_v2",
        "prior_pr1180_child": "keltner_replacement_trend_pull_long_4h_h12_v2__keltner_prior_extreme_v1",
        "prior_pr1181_child": "keltner_replacement_trend_pull_long_4h_h12_v2__prior_atr_bull_context_v1",
        "reason": "DIAGNOSIS_CONTRADICTS_LOSS_VETO; DO_NOT_SACRIFICE_PROFITABLE_PARENT_REGION",
        "rule": "DIAGNOSIS ONLY: rising EMA50 / EMA20>EMA50, pullback stays above EMA50 then reclaims EMA20. Not authorized because excluded deep/recovery group carries positive parent profit.",
        "run_authorized": false,
        "state_consumed_on": "RAW_ELIGIBLE_SIGNAL_NOT_FILL",
        "trial_ordinal": null
      },
      "same_development_calendar": true
    },
    {
      "PR": 1184,
      "contract": "backend/research/contracts/top5_no_credit_exit_v1.json",
      "contract_file_sha256": "9d4ad7f51723bec646a35f56c8e858fe2c67f936d350c8db03b1df9f2472e8f0",
      "lane": {
        "child_id": "keltner_replacement_trend_pull_long_4h_h12_v2__cost_cover_lost_exit_v1",
        "exit_trial_ordinal": 1,
        "parent_id": "keltner_replacement_trend_pull_long_4h_h12_v2",
        "parent_sha256": "ff5cf1f6d3b3ebabc9dca81457c1ffdd26af6e68871cad40bdc85332d4262859",
        "reason": "PRIOR_CLOSED_MARK_GIVEBACK_LOSSES; APPLY_TO_ALL_WINNERS_AND_LOSERS"
      },
      "same_development_calendar": true
    }
  ],
  "calendar_first_use": "PR1179 diagnostic development; same frozen data subsequently reused",
  "current_work": "Outcome attribution and one predeclared trigger-state association; no child economics unless separately preregistered",
  "prior_terminal_and_original_records": "PRESERVED_BY_FILE_SHA"
}
```
