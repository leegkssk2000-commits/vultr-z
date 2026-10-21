# Keltner loss / winner-management attribution — 2026-10-21

Classification: CODE_OBSERVATION + independent saved-trade diagnostic. Not a new strategy, economic replay, adopted exit rule or profitability PASS. Existing economic owner CLOUD_WORK_COORDINATOR_ISSUE1358_V1 and all budgets remain unchanged.

## Exact evidence

Source run 39522258946 / attempt 3 / head d55eeda13a17600e4b49ce7b15d38192d2ec467b / artifact 12327593998. ZIP SHA256 2e9e4de8cbe9c42e9c2c206024a66bc34708dcaa08ac6b820397e1e98db9378f; result raw SHA256 d62a9513996c8b2d0e648803ff8e498e31bb029faaa6008c125eee68dc8b85a1; internal receipt 4017a6a30628df0de444bcfd3b65a622e765e595f836976729d6c3d868c03ae4. All three hashes verified from the existing ZIP. All 128 successor rows used; no new price replay or source API. Same 245-day / six-symbol / 30m used-DEV cohort. All PnL units are equal-notional trade-bps, not account returns.

## What was and was not changed

Read the exact-head ops/scalp7_keltner_fresh_touch_successor_v1.py and backend/research/rebuild/scalp7_positive_lanes_v2.py, blob79b9934b471cbe0f4342b265c90b2c9c8884f52c, including exit_update. The tested successor changes rejected-entry rearming, not the profit-management policy. Existing K lifecycle ALREADY has fee break-even armed at 1R with modeled net lock +2bps; 10% partial at 2R; trailing armed at 3R with 1.25R gap; five-bar scratch when MFE<0.40R; maximum hold25 bars. These are existing frozen parameters, not suggested new values. Do not propose adding an already-existing runner or declare these mechanisms newly implemented.

## Recomputed findings

Parent / rejected / successor maximum wins at cost1x: 10 / 11 / 9. Maximum losses: 5 / 8 / 8. Median win runs: 2 / 2 / 2. Successor and rejected summaries both have worst cost1x losing-run amount -1128.2251166863311 trade-bps. Equality of count/amount is verified; exact rejected-versus-successor trade-identity equality was not checked here. The current successor eight-loss run has four STOP_FIRST and four HG_FROZEN_5BAR_MFE_SCRATCH outcomes; all eight gross returns are negative. Its cost2x longest13-loss run includes only3 base-cost winners turning negative; ten are already gross losers. Costs alone therefore do not account for this loss run.

All128 rows grouped by final exit reason:

| Exit reason | Trades | Wins1x | Wins2x | Net1x trade-bps | Net2x trade-bps |
|---|---:|---:|---:|---:|---:|
| HG_FROZEN_5BAR_MFE_SCRATCH |33|5|3|-3503.9007042002|-3998.170450908181|
| MAX_HOLD_NEXT_OPEN |19|13|12|2934.5089728883904|2652.6091508893287|
| OPEN_GAP_STOP |8|8|8|2303.137960897226|2181.458789141796|
| STOP_FIRST |68|44|20|4628.871188004527|3608.366132223087|

Counts and both Net totals exactly reconcile with the source result within floating tolerance. STOP_FIRST is a fill-order label, NOT synonymous with losing trade; it contains protected profitable exits too. Scratch's negative group does not prove that the scratch caused those losses or that removing it improves results.

23 trades end at approximately +2.0bps net each under base cost (absolute tolerance1e-8), all STOP_FIRST and all with recorded MFE between1.0472089R and1.8297689R. Their combined Net1x is +46.00000000000894; Net2x is -299.57622073167846. This is a persistent cost-fragile small-winner group, not evidence that all23 would later recover after a different exit. Across all128,27 base-cost winners become nonpositive at2x cost; the23 are a subset, not all27.

The recorded-MFE>=2R group contains35 trades and sums +13113.449792272382 Net1x / +12584.781591191126 Net2x. This is ex-post path classification, not an entry filter or claim that the observed maximum was an executable fill. It emphasizes the need to preserve real larger winners when reducing losses.

19 trades exit at the25-bar time limit,13 profitable at base cost. No post-exit price path is exported, so extending these positions has NOT been evaluated and may lose rather than gain. Merely observing a profitable time exit is not proof of premature exit.

## Actionable development questions, not new execution authority

1. Existing approved Squeeze signal-low comparison remains the immediate loss-control execution target. Use the complete source path to locate the first executable failure event BEFORE the original exit and compare lost recovery winners as well as reduced losses. This audit does not gate or delay that comparison.
2. For K winner management, compare the actual fee-BE / partial / trailing / time-exit sequence on ALL trades, including counterexamples. The current entry-only result does not answer this question. Establish whether a causal structure-based profit-protection or continuation rule is supported before freezing one change. Do not change entry, initial risk, costs and several exits together; do not sweep R thresholds or resurrect previously rejected axes under a new name.
3. Compare paired same-entry outcomes first, then full chronological occupancy and missed-opportunity effects only within confirmed scope/budget. Win-run length, win-run median, average winner/loser, Net1x/2x, loss-run amount, DD and large-winner preservation must be shown together. Partial exits are not independent winning trades.

Actual executable bar prefixes, recovery paths and post-exit paths are absent from this artifact. Terminal MFE/MAE and exit labels are retrospective diagnostic labels; do not use them as entry features, infer intrabar order, or invent counterfactual PnL. The original execution engine's stop-first/gap/next-open timing stays intact.

Executed here: saved128-row audit and exact-code reading. NewFULL0, newcandidate0, marketAPI0, runtime/OWNER/CHECKPOINT/consumption edits0, orders0. This evidence note is NOT consumer adoption, code implementation, a new approval or an increase in realized profit.
