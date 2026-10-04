# Keltner actual recorded-price input and execution closeout — PR1355

## Result first

The requested input connection reached a COMPLETE actual recorded-price model run. It did not stop at metadata or generated-price tests. The run produced20 complete trades from32 in-window signals on164,490 verified original minute rows across the original six BingX symbols. Eleven signals were rejected by the frozen entry ATR/cost condition and one by position ownership. Unresolved positions0. The original K.P parent and engine hashes/rules remain unchanged.

| Metric | Reference cost1x | Reference cost2x |
|---|---:|---:|
| Completed T |20|20|
| WR |30.00%|20.00%|
| Gross trade-bps |185.275695|185.275695|
| Cost trade-bps |310.356308|620.712617|
| Net trade-bps |-125.080613|-435.436921|
| Net bps/T |-6.254031|-21.771846|
| PF |0.916741|0.750718|
| Realized trade-sum DD bps |1017.080055|1158.441325|
| Maximum loss streak |4|9|

Fixed contract epoch window1789502400000–1791075300000 =2026-09-15 20:00Z through2026-10-04 00:55Z exclusive,18.204861 days. Correction to earlier comment prose: the pinned numeric start is20:00Z, not21:00Z; no timestamp or evaluated interval was changed. T/day1.098608 is six-symbol aggregate. Neither this DD nor summed bps is account drawdown or account percentage return. Cost2x means the same trades with twice the frozen reference charge, NOT twice the leverage.

The sampled model economics are NEGATIVE. Gross9.263785bps/T does not cover frozen reference cost15.517815bps/T. This is not a profitability PASS and does not support G5 advancement. It is also not a formal G5 FAIL: this is a historical diagnostic with20 trades, not certified unused OOS/fresh evidence.

## What actually ran and what was recovered

Execution head994d6c5aa20fc9aeb6f8f446254483ced26dcd04; Actions run37208749237/job111455394132. STARTED2026-10-04T14:18:28.056199Z, COMPLETED14:18:29.874639Z, economic_replays1. Execution had already completed when this continuation recovered its artifact; it was NOT rerun to obtain the same result.

Artifact11305329406 ZIP SHA256f5811b647afcf3f6d352aed5b875a43c23a754be8845dc9bfb44a5af1598cef7. Original RESULT.json SHA25642091eced2860b8d301df92d51c0a6e4693d409cdcc617422ccda788afb9f087. It includes full20-trade execution,32 signals,146 lifecycle trace rows, frame manifest, started/completed records, and an amount audit. Downloaded archive hash and completion/result link were checked locally. A separate stdlib saved-result audit recomputed every trade's partial/final gross, net costs, WR, PF, simultaneous-outcome-netted realized DD and loss streak. All20 agree;3 partial trades reconcile; largest residual0bps. No strategy or price-history replay is invoked by that audit.

Initial activation run37208507591 failed in shell parsing BEFORE artifact download or model invocation. PREEXEC_RESUME.json preserves that failed attempt and its exact artifact; it does not replenish an already consumed economic run. The successful resume consumed the original single allowance. The closeout workflow now has NO market execution or SSH stage and only audits the completed result. Its tests do not consume economic credits.

## Provenance and remaining timing problem

The main acquisition run37207227809/artifact11305242034 verified75,842 receipt-bound raw/normalized pairs. Its fixed common cut retained157,722 rows. Original configuration also referenced a second adjacent source: run37207878006/artifact11305382754 verified12 receipts/6,768 rows. Combined input164,490 rows; ZIP SHA256a656836ac36ab2dd8b90344513f567b296c6f092213a84e4d195e9b5bbabe299, expanded PRICE_INPUT SHA2563da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3. Config pin d75239c6282c1baa88648ccd594d32beb719de0bdf3fd1d2123f6361593fff9b is checked independently of hashes supplied by that config. P1 review4177966600 was fixed before execution; originally acquired bytes already matched that prior pin.

The old observer had already processed part of this history through2026-09-18. This full interval is now explicitly consumed research input, never untouched after inspecting these results. A campaign claim was recovered; that is not a complete global use-history or reservation census.

All32 signal bars have actual recorded receipt availability AFTER the hypothetical next-open instant. Observed lateness: minimum0.237s, median115.856s, maximum308.788s. The run intentionally used the precommitted historical bar-boundary availability model and retained the original receipt clocks separately. It does NOT prove these fills could have been taken by the actual delayed collector. It never rewrote source timestamps, changed the old late-observation guard or counted missed signals as genuine fresh trades.

Thus input integration and historical economic output are complete; the existing running live/fresh consumers are still NOT repaired/activated. Actual funding settlements, position sizing, margin/liquidation and continuous account NAV/DD remain unbound. G5A shortlist, G5B terminal, G6, Core and LIVE remain off. PR1350's limited frozen-baseline admission is preserved, not expanded.

## Failure attribution, not a post-outcome filter

Six frozen5bar no-progress exits contributed -587.915509/-681.007644trade-bps (cost1x/2x). Twelve STOP_FIRST exits contributed +148.234346/-39.324810; this group includes profitable protective stops, so STOP_FIRST is not equivalent to initial-stop loss. Two max-hold exits contributed +314.600550/+284.895533. These sum to the reported total. Deleting those six failed trades or moving the scratch threshold after viewing this sample is NOT a proven improvement. Preserve this loss evidence and the large-winner pathways; no child or tuning is implemented here.

## Next bounded engineering point and other strategies

1. Do not repeat input acquisition, old119 amount reconciliation, baseline admission, or this20-trade replay merely to reproduce totals.
2. Before a new genuine validation, bind a timing-aware execution convention using observable availability, or an authorized timely feed, with a new prospective/unseen window and complete usage/owner record. Fix that specification BEFORE viewing outcomes. The present historical run cannot be relabeled to satisfy it.
3. Reuse the committed snapshot and raw/normalized input schema for the next eligible lane; no per-strategy transport rebuild. Squeeze stays next frozen candidate. Other strategy economics, material ranks and budgets are not changed or automatically activated by this PR.
4. This negative short sample warrants retention and diagnosis, not automatic promotion, universal Keltner failure, or unbounded new tuning.

This task remains explicitly authorized non-frontend research/input work. No old backend, source loader, frozen strategy, budget, guard/allowlist, service or collector was modified. No user SSH or separate Work handoff is required. No deployment should be run. Rollback only this PR's added input/diagnostic files; retain completed execution and usage evidence. Exact final-head CI/review/merge status belongs in the final receipt and is not presumed by this report. Full source/price artifacts have14-day Actions retention; the hashes, contract, summary and usage receipt are permanent, not a claim that all original price bytes are committed to Git.
