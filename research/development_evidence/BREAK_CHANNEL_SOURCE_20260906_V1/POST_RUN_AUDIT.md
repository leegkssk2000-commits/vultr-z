# Post-run interpretation and ledger audit

This note interprets the already sealed result; it does not change the specification, code, trades, costs, thresholds or decisions. Preregistration was published at `650153aca254916f584114c73029fab4e0a49250` before the single economic run. Result seal: `a5509c187f94b163f8e0428be876f9ba0f64540142d2be45ff883238d5d32018`. Reproduction is not another hypothesis allocation. Previous 22 applications remain preserved; Q and Q-minus consume ordinals 23 and 24, with zero remaining slots.

## Closed attribution versus complete terminal valuation

The reused origin-attribution helper accepts parent **completed trades** and child completed/open observations. Its `marked_delta_bps_not_realized` field includes child open marks but excludes parent open marks. It is a bridge relative to parent closed PnL, not a complete marked portfolio comparison. The receipt's `comparisons.*.uncertainty.child_minus_parent_marked_delta_sum_bps` and daily valuation ledger include **both sides' open positions**, and are the appropriate complete terminal comparison. Neither is a realized account return.

| Comparison | Closed net difference, trade-bps | Complete terminal marked difference, trade-bps |
|---|---:|---:|
| P → Q | -1,154.3181 | -986.0268 |
| P → Q-minus | -27,886.6268 | -27,328.9880 |
| Q-minus → Q | +26,732.3087 | +26,342.9612 |

P has one unfinished position with hypothetical net mark -168.2913; Q has none; Q-minus has three with combined hypothetical net mark +389.3475. Full modeled roundtrip liquidation costs are charged for this valuation convention; entry-side costs are not separately bound. No unfinished position was forced into a completed trade. P's 155 matching completed trades preserve the original full-parent economics exactly. The common calendar changes the signal boundary and explicitly records unfinished ownership, not completed parent PnL.

## What the preparation condition changed

Q-minus → Q has 60 common completed origins with **zero** PnL, fee or funding change. Removing 225 Q-minus completed origins excludes losses of 63,245.0418 and winner profit of 35,661.7830, for a net contribution of +27,583.2589. The 26 additional completed Q trades after changed ownership contribute -850.9502. These sum to the closed improvement +26,732.3087. The three Q-minus terminal open observations are accounted for separately above.

Q preserves 32.34% of Q-minus's original positive completed profit and 55.16% of its original large-winner profit under the existing capped origin-match measure. Q and P have no identical signal origins; zero original-origin profit retention is descriptive of this mechanism replacement, not a rejection criterion. Q generates 86 completed trades and 21,010.6326 positive winner trade-bps versus P's 155 and 27,646.0811. The identical-calendar aggregate comparison, not origin coincidence, determines the economic interpretation.

## Trade-off and uncertainty

Q has positive closed expectancy +47.3970 bps and cost×2 expectancy +21.2418, but its closed total +4,076.1430 is below P's +5,230.4611. Maximum grouped losing-run loss increases from 2,735.5014 to 5,224.6878; marked drawdown increases from 4,289.8967 to 6,801.4788. Exposure rises from 155.3333 to 276.6667 symbol-days. These are equal-notional trade-bps and exposure measures, not account MDD or equal-risk returns. Q is `DEV_INCONCLUSIVE`, with no adoption.

Q-minus's completed-trade screen is `DEV_REJECT`: -79.4953 bps expectancy, PF 0.6994, cost×2 expectancy -104.2712. Its overall terminal status remains `DEV_INCONCLUSIVE` because three positions are unfinished; this does not erase the negative completed-trade finding.

For Q minus P, the paired 30-day moving-block 95% interval is [-72.0428, +77.6872] trade-bps/day. For Q minus Q-minus it is [-32.2235, +147.0263]. Neither establishes a positive lower bound. There are 334 calendar days, including zero-trade days; approximately 11.13 block lengths are not claimed as independent samples. Maximum Q holding is 17 days; cross-symbol dependence and repeated DEV use remain limitations. Preparation evidence is `NOT_ESTABLISHED`.

Q's July net contribution is +10,400.3227, exceeding its full-period net profit; LINK contributes +4,687.2909 while total Q net is +4,076.1430. Both reveal concentration rather than broad stability. The three largest Q winners account for 48.33% of positive winner profit. No alternate period, symbol subset, threshold or parameter result was executed from these observations.

There are 32 intrabar Q stops and 144 Q-minus stops. Stop timestamps use the preregistered 4h close upper bound; respectively 12 and 70 stop bars meet the modeled funding-boundary count. These are fill/timing limitations, not finer execution lineage. Public source attribution was independently checked against the paper; unresolved menu/count discrepancies and all DESIGN_PRIOR adaptations remain explicit.

Independent read-only audits checked all 2,618 daily bars against their six original 4h bars, 1,977 confirmations against prior-close formulas and latched thresholds, and 625 identical bearish confirmations per candidate. All 526 completed trades, four open observations, 817 opportunity events and 1,336 daily valuation rows passed independent price, cost, funding, exposure, attribution and marked-path checks. Q has 102 opportunities = 86 completed + 16 excluded while occupied; Q-minus has 433 = 285 completed + 3 open + 145 occupied exclusions. There were no observed gap-stop, gap-cancel or conflicting-fill cases; those branches have synthetic test coverage only. The parent-open attribution scope above is the reported accounting limitation.

The frozen runner passed local byte-identical reproduction with a changed Python hash seed. Code tests and CI verify implementation and reproduction; they do not grant economic adoption. Formal validation remains blocked pending separate authority, unused eligible data and required cost/execution lineage. Break's seen validation reject, all other Top5 lanes, G5B collection/open intent/boundary and execution/order/live authority remain preserved. No new paid external AI call or video analysis was performed.
