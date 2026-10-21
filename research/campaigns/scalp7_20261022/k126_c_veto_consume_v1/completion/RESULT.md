# Work C actually consumed — state-lifetime comparison

Classification: ACTUAL_FIXED_SINGLE_CANDIDATE_USED_DEV. No account NAV, historical actual funding, independent OOS or promotion claim.

C source commit: 77ce5616ed6e29c421592f319e7253b81dd79bdc. Incumbent:81a12c422ee9329996d2f6b983267d2def490d4b. Original K126 also retained.

|Metric|Incumbent|Candidate|
|---|---:|---:|
|cost1x T|126|114|
|cost1x Net_bps|7942.268973684915|6788.356135984457|
|cost1x PF|2.0064847071126635|2.1064890609837423|
|cost1x MaxLossStreak|8|5|
|cost1x worst_loss_run_bps|-1128.2251166863311|-892.532161239613|
|cost1x DD_bps|1838.6420049280318|1587.880662214915|
|cost2x T|126|114|
|cost2x Net_bps|6049.2458247083|5075.946442314331|
|cost2x PF|1.6674843985707057|1.7072792645212982|
|cost2x MaxLossStreak|13|11|
|cost2x worst_loss_run_bps|-1946.766452879958|-1465.0298586461777|
|cost2x DD_bps|2059.6075941499575|1993.7531144345073|

Unit: equal-notional summed trade-bps, not account return.
Disposition: REJECT_OR_TRADEOFF_KEEP_INCUMBENT

Origin attribution is before-entry evidence, not proof that a reset is profitable. Full chronology includes changed signals, occupancy, extra/missed trades, recovery winners and inherited reference 1x/2x costs with the same extra carry scenario.

Attribution:
```json
{
  "cost1x": {
    "added_net": 193.76861340535075,
    "common_delta": -292.18630140128187,
    "net_delta": -1153.912837700458,
    "reconciled": true,
    "removed_net": 1055.4951497045258
  },
  "cost2x": {
    "added_net": 106.7571862907555,
    "common_delta": -292.1863014012818,
    "net_delta": -973.2993823939687,
    "reconciled": true,
    "removed_net": 787.8702672834429
  }
}
```
Cohorts:
```json
{
  "large_winners": {
    "baseline_T": 34,
    "baseline_net1x": 14525.496873573524,
    "removed_T": 3,
    "removed_net1x": 2794.657985277592,
    "retained_T": 31,
    "retained_net1x": 11300.606965018178
  },
  "losses": {
    "baseline_T": 57,
    "baseline_net1x": -7891.097517486551,
    "removed_T": 13,
    "removed_net1x": -1987.199234648002,
    "retained_T": 44,
    "retained_net1x": -5765.852660962078
  },
  "ordinary_winners": {
    "baseline_T": 35,
    "baseline_net1x": 1307.8696175979392,
    "removed_T": 2,
    "removed_net1x": 248.03639907493573,
    "retained_T": 33,
    "retained_net1x": 1059.8332185230033
  }
}
```

Current Shadow changes0; orders0; D risk allocation not applied; reserved S comparison untouched.
