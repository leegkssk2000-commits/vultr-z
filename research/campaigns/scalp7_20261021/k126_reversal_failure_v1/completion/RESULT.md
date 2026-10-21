# K126 post-entry reversal-bar failure: actual paired and chronological comparison

Completed UTC: 2026-10-21T21:10:46.928222+00:00
Disposition: REJECT_OR_TRADEOFF_REQUIRES_EXPLICIT_REVIEW_KEEP_K126
Baseline retained: 308bd2deb7acaaacf1adb582206e78262d72c9d1.
Classification: ACTUAL_USED_DEV_EXIT_ONLY_COMPARISON. Equal-notional trade-bps, not account returns.

## Predeclared rule
For a long, a completed close below the original reversal-signal low (short: above high) schedules an exit at the actual next open. Wicks alone do not qualify. Existing protective stops, gap fills and already-due exits take precedence. Entry, original risk, fee-BE, partial, scratch and positive25/50bar winner extension remain fixed. This is a source-motivated internal translation, not an author-exact certified rule. No fitted cutoff or sweep.

|Metric|Incumbent K126|New exit rule|
|---|---:|---:|
|T cost1x|126.00000000|130.00000000|
|Net_bps cost1x|7925.82228888|4297.85486455|
|PF cost1x|2.00231147|1.50115249|
|WR_pct cost1x|54.76190476|46.92307692|
|MaxLossStreak cost1x|8.00000000|9.00000000|
|worst_loss_run_bps cost1x|-1128.22511669|-856.90474713|
|DD_bps cost1x|1838.64200493|1520.26041157|
|T cost2x|126.00000000|130.00000000|
|Net_bps cost2x|6032.79913990|2348.10168812|
|PF cost2x|1.66446380|1.23729685|
|WR_pct cost2x|33.33333333|28.46153846|
|MaxLossStreak cost2x|13.00000000|13.00000000|
|worst_loss_run_bps cost2x|-1946.76645288|-1366.01175772|
|DD_bps cost2x|2059.60759415|2022.58638702|

## Failure onset versus later loss: ALL126 paired entries (not final chronology)
{
  "baseline_loser_T": 28,
  "baseline_winner_T": 9,
  "changed_earlier_T": 37,
  "earlier_minutes_total": 10830.0,
  "loser_delta1x": 1096.262745348253,
  "negative_delta_T": 20,
  "net_delta1x": -2123.594340390116,
  "net_delta2x": -2120.8943403901153,
  "positive_delta_T": 17,
  "same_entries": 126,
  "unresolved": 0,
  "winner_delta1x": -3219.85708573837
}
Original worst8 paired sum delta1x: 290.80607514897713
Original worst8 changed entries: 3

## Full chronological opportunity and winner effects
{
  "attribution": {
    "cost1x": {
      "added_net": -342.25926085163997,
      "common_delta": -2123.594340390116,
      "net_delta": -3627.9674243264326,
      "reconciled": true,
      "removed_net": 1162.1138230846757
    },
    "cost2x": {
      "added_net": -429.70928014783965,
      "common_delta": -2120.8943403901153,
      "net_delta": -3684.6974517825656,
      "reconciled": true,
      "removed_net": 1134.0938312446099
    }
  },
  "cohorts": {
    "large_winners": {
      "baseline_T": 34,
      "baseline_net1x": 14525.496873573524,
      "missing_keys": [
        [
          "BTC-USDT",
          -1,
          1769999400000
        ],
        [
          "SOL-USDT",
          -1,
          1770289200000
        ]
      ],
      "retained_T": 32,
      "retained_net1x": 11184.797635329294
    },
    "losses": {
      "baseline_T": 57,
      "baseline_net1x": -7907.5442022958905,
      "missing_keys": [],
      "retained_T": 57,
      "retained_net1x": -6811.281456947636
    },
    "ordinary_winners": {
      "baseline_T": 35,
      "baseline_net1x": 1307.8696175979392,
      "missing_keys": [],
      "retained_T": 35,
      "retained_net1x": 266.5979470191207
    }
  },
  "removed": [
    {
      "entry_ts_ms": 1769999400000,
      "exit_ts_ms": 1770004800000,
      "key": [
        "BTC-USDT",
        -1,
        1769999400000
      ],
      "mfe_R_analysis_only": 3.4462153823518915,
      "net1x": 154.63418123013997,
      "net2x": 140.63418123013997,
      "reason": "STOP_FIRST"
    },
    {
      "entry_ts_ms": 1770289200000,
      "exit_ts_ms": 1770327000000,
      "key": [
        "SOL-USDT",
        -1,
        1770289200000
      ],
      "mfe_R_analysis_only": 5.432708278453788,
      "net1x": 1007.4796418545358,
      "net2x": 993.45965001447,
      "reason": "STOP_FIRST"
    }
  ],
  "added": [
    {
      "entry_ts_ms": 1769974200000,
      "exit_ts_ms": 1769979600000,
      "key": [
        "BTC-USDT",
        -1,
        1769974200000
      ],
      "mfe_R_analysis_only": 2.016849620282529,
      "net1x": 14.449052801677752,
      "net2x": 0.44905280167775175,
      "reason": "STOP_FIRST"
    },
    {
      "entry_ts_ms": 1769988600000,
      "exit_ts_ms": 1769992200000,
      "key": [
        "BTC-USDT",
        -1,
        1769988600000
      ],
      "mfe_R_analysis_only": 0.08518850356192406,
      "net1x": -151.1577899844856,
      "net2x": -165.1577899844856,
      "reason": "STOP_FIRST"
    },
    {
      "entry_ts_ms": 1780684200000,
      "exit_ts_ms": 1780693200000,
      "key": [
        "LINK-USDT",
        -1,
        1780684200000
      ],
      "mfe_R_analysis_only": 0.870490978981952,
      "net1x": -229.2866169318006,
      "net2x": -244.9916347398346,
      "reason": "K126_REVERSAL_BAR_FAILURE_NEXT_OPEN"
    },
    {
      "entry_ts_ms": 1780702200000,
      "exit_ts_ms": 1780727400000,
      "key": [
        "LINK-USDT",
        -1,
        1780702200000
      ],
      "mfe_R_analysis_only": 2.3710837214888842,
      "net1x": 41.9799197684504,
      "net2x": 26.274901960416397,
      "reason": "STOP_FIRST"
    },
    {
      "entry_ts_ms": 1770273000000,
      "exit_ts_ms": 1770276600000,
      "key": [
        "SOL-USDT",
        -1,
        1770273000000
      ],
      "mfe_R_analysis_only": 0.047165261429367375,
      "net1x": -188.6016190432,
      "net2x": -202.6216108832658,
      "reason": "K126_REVERSAL_BAR_FAILURE_NEXT_OPEN"
    },
    {
      "entry_ts_ms": 1770305400000,
      "exit_ts_ms": 1770314400000,
      "key": [
        "SOL-USDT",
        -1,
        1770305400000
      ],
      "mfe_R_analysis_only": 0.24603952467575319,
      "net1x": 170.35779253771804,
      "net2x": 156.33780069765226,
      "reason": "HG_FROZEN_5BAR_MFE_SCRATCH"
    }
  ],
  "child_unresolved": 0,
  "child_boundary_excluded": 0
}

## Limits
The first bar failure marker is a hypothesis, not proof that a full trend is invalid. Recovery winners are included. Paired improvements are not added to overlapping new opportunities; final results come from the native state/admission/occupancy chronology.
Same245-day usedDEV and original365-day context. No independentOOS, live fills, NAV/MTM drawdown, or verified historical funding. Reference1x/2x costs plus previously disclosed extra-holding reserve. No currentShadow/order/production change; reserved S/C comparisons unspent.
Sources and scope in SOURCE_APPLICATION.md; prepared before the real run at34df33538653d14fea12c56473782eb776068b22. Original module hashes, six prices and context, and disabled126 rows exactly checked.
Artifacts: SUMMARY.json, ROWS.json.gz, PAIRED_ALL126.json.gz, ARITHMETIC_AUDIT.json, CONTROL_PARITY.json, FREEZE.json, EXECUTION.log.
