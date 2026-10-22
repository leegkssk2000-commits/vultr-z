# Frozen K117: saved-ledger sensitivity review

Classification: SAVED_LEDGER_SENSITIVITY_NOT_NEW_POLICY_OR_INDEPENDENT_VALIDATION.
All values below use the completed 245-day development ledger. No new price replay, orders, Shadow changes or parameter/symbol selection.
Source economic result: 8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8; K126 and C114 are preserved.
Unit: equal-notional summed trade-bps, not account return. Realized DD nets simultaneous outcomes; no account MTM drawdown claim.

|Metric|K126|C114|Frozen K117|
|---|---:|---:|---:|
|cost1x T|126|114|117|
|cost1x Net_bps|7942.268973684913|6788.356135984457|10159.281145923826|
|cost1x PF|2.006484707112663|2.106489060983743|2.6360274197533355|
|cost1x WR_pct|54.76190476190476|60.526315789473685|60.68376068376068|
|cost1x MaxLossStreak|8|5|5|
|cost1x worst_loss_run_bps|-1128.2251166863311|-892.532161239613|-892.532161239613|
|cost1x DD_bps|1838.6420049280318|1587.880662214915|1400.1718363206815|
|cost2x T|126|114|117|
|cost2x Net_bps|6049.2458247083|5075.94644231433|8399.994371200033|
|cost2x PF|1.6674843985707066|1.7072792645212982|2.1617610694364644|
|cost2x WR_pct|33.333333333333336|33.333333333333336|36.75213675213675|
|cost2x MaxLossStreak|13|11|11|
|cost2x worst_loss_run_bps|-1946.766452879958|-1465.0298586461777|-1465.0298586461777|
|cost2x DD_bps|2059.6075941499575|1993.7531144345073|1577.8709999161774|

## Concentration sensitivity; subtraction only, not independent replays
|Diagnostic|K126 net2x|C114 net2x|K117 net2x|
|---|---:|---:|---:|
|Exclude largest winner|4612.020351207772|3738.5546433649824|6962.768897699506|
|Exclude best original rolling window|1560.5586784149693|276.92994469686244|3600.9778735825653|

K117 positive/negative cost2x windows: 4/5 of9. The number of profitable windows has NOT improved.
Every leave-one-window and leave-one-symbol cost2x remainder is positive. This does not show every window or every symbol is individually profitable.
Compared with K126, five windows improve and four are unchanged at both costs. This is used-data attribution, not an unseen-period test.
Remaining cost2x loss windows: rolling2, rolling4, rolling6, rolling7, rolling9. BTC component is also negative at cost2x. No losing period or symbol is removed from the strategy.
Completed-trade rate: 117/245 = 0.477551 per day, below the eventual combined3-4/day objective. This comparison does not validate a common-account portfolio.

## Winner preservation
{"large_same_entry_and_net": 34, "large_winners": 34, "original_winners": 69, "removed_losses": 10, "removed_winners": 1, "retained_same_entry_and_net": 68}
All34 original large winners retain their entry and net. Of69 original winners,68 are unchanged; one38.9714153578 trade-bps ordinary winner remains excluded.
## Next execution boundary
{
  "preserve": "Freeze K117 as a development challenger; retain immutable K126/C114. No current strategy, Shadow, risk budget or promotion change.",
  "do_not": "Do not retune or manufacture a numeric filter for the remaining loss windows. Do not relabel used historical windows as untouched OOS.",
  "next_unfinished": "Identify an existing authorized untouched/prospective validation contract and inputs for this exact frozen identity. Reuse existing engine; no new platform, paid API, live orders, or unapproved replacement of B.",
  "parallel_independent": "Existing reserved Squeeze comparison can proceed separately under the same single economic owner after checking its current receipt and authority; no budget transfer from S to K."
}
## Integrity
Three source-ledger hashes and all frozen code hashes checked; independent arithmetic agrees with stored metrics. Event-time checks cover215 objective-expiry records.
No new experiment, no account NAV or historical funding claim, no fresh/OOS PASS.
