# K126 native pullback-structure failure: actual paired and chronological comparison

Completed UTC: 2026-10-21T21:36:58.806340+00:00
Disposition: PRESERVE_DEV_CANDIDATE_FOR_INDEPENDENT_VALIDATION
Baseline retained: 308bd2deb7acaaacf1adb582206e78262d72c9d1.
Classification: ACTUAL_USED_DEV_EXIT_ONLY_COMPARISON. Equal-notional trade-bps, not account returns.

## Predeclared rule
For a long, a completed close below the frozen native whole-pullback invalidation_price (short: mirrored) schedules an exit at the actual next open. Wicks alone do not qualify. Existing protective stops, gap fills and already-due exits take precedence. Entry, original risk, fee-BE, partial, scratch and positive25/50bar winner extension remain fixed. This is a source-motivated internal translation, not an author-exact certified rule. No fitted cutoff or sweep.

|Metric|Incumbent K126|New exit rule|
|---|---:|---:|
|T cost1x|126.00000000|126.00000000|
|Net_bps cost1x|7925.82228888|7942.26897368|
|PF cost1x|2.00231147|2.00648471|
|WR_pct cost1x|54.76190476|54.76190476|
|MaxLossStreak cost1x|8.00000000|8.00000000|
|worst_loss_run_bps cost1x|-1128.22511669|-1128.22511669|
|DD_bps cost1x|1838.64200493|1838.64200493|
|T cost2x|126.00000000|126.00000000|
|Net_bps cost2x|6032.79913990|6049.24582471|
|PF cost2x|1.66446380|1.66748440|
|WR_pct cost2x|33.33333333|33.33333333|
|MaxLossStreak cost2x|13.00000000|13.00000000|
|worst_loss_run_bps cost2x|-1946.76645288|-1946.76645288|
|DD_bps cost2x|2059.60759415|2059.60759415|

## Failure onset versus later loss: ALL126 paired entries (not final chronology)
{
  "baseline_loser_T": 1,
  "baseline_winner_T": 0,
  "changed_earlier_T": 1,
  "earlier_minutes_total": 30.0,
  "loser_delta1x": 16.446684809341434,
  "negative_delta_T": 0,
  "net_delta1x": 16.446684809341434,
  "net_delta2x": 16.446684809341434,
  "positive_delta_T": 1,
  "same_entries": 126,
  "unresolved": 0,
  "winner_delta1x": 0
}
Original worst8 paired sum delta1x: 0.0
Original worst8 changed entries: 0

## Full chronological opportunity and winner effects
{
  "attribution": {
    "cost1x": {
      "added_net": 0,
      "common_delta": 16.446684809341434,
      "net_delta": 16.446684809343424,
      "reconciled": true,
      "removed_net": 0
    },
    "cost2x": {
      "added_net": 0,
      "common_delta": 16.446684809341434,
      "net_delta": 16.446684809341605,
      "reconciled": true,
      "removed_net": 0
    }
  },
  "cohorts": {
    "large_winners": {
      "baseline_T": 34,
      "baseline_net1x": 14525.496873573524,
      "missing_keys": [],
      "retained_T": 34,
      "retained_net1x": 14525.496873573524
    },
    "losses": {
      "baseline_T": 57,
      "baseline_net1x": -7907.5442022958905,
      "missing_keys": [],
      "retained_T": 57,
      "retained_net1x": -7891.09751748655
    },
    "ordinary_winners": {
      "baseline_T": 35,
      "baseline_net1x": 1307.8696175979392,
      "missing_keys": [],
      "retained_T": 35,
      "retained_net1x": 1307.869617597939
    }
  },
  "removed": [],
  "added": [],
  "child_unresolved": 0,
  "child_boundary_excluded": 0
}

## Limits
The whole-pullback close marker is a hypothesis, not proof that a full trend is invalid. Recovery winners are included. Paired improvements are not added to overlapping new opportunities; final results come from the native state/admission/occupancy chronology.
Same245-day usedDEV and original365-day context. No independentOOS, live fills, NAV/MTM drawdown, or verified historical funding. Reference1x/2x costs plus previously disclosed extra-holding reserve. No currentShadow/order/production change; reserved S/C comparisons unspent.
Sources and scope in SOURCE_APPLICATION.md; prepared before the real run in this stage FREEZE and preparation commit. Original module hashes, six prices and context, and disabled126 rows exactly checked.
Artifacts: SUMMARY.json, ROWS.json.gz, PAIRED_ALL126.json.gz, ARITHMETIC_AUDIT.json, CONTROL_PARITY.json, FREEZE.json, EXECUTION.log.
