# PR1357: one Squeeze failure-exit comparison completed

## Result first: loss reduction, not a profitable strategy

Exactly ONE new child was executed: `scalp7_squeeze_panic_cost4_momentum_nonpositive_utc30m_v1`. It added observed native momentum<=0 failure exit to the ORIGINAL parent, not BE1R. Parent results and15 position-independent potential signals were reused, while all child occupancy and later opportunities were replayed. No original parent, BE1R or Keltner replay occurred; no signal generator was called.

| Metric | Saved parent1x | New child1x | Saved parent2x | New child2x |
|---|---:|---:|---:|---:|
| Complete T |9|9|9|9|
| WR pct |22.222222|22.222222|22.222222|22.222222|
| Gross trade-bps |-572.422830|-464.330514|-572.422830|-464.330514|
| Cost trade-bps |139.877057|139.877057|279.754114|279.754114|
| Net trade-bps |-712.299887|-604.207571|-852.176945|-744.084628|
| Net bps/T |-79.144432|-67.134175|-94.686327|-82.676070|
| PF |0.254166|0.286604|0.199400|0.221937|
| Realized trade-sum DD bps |869.533824|761.441508|994.164448|886.072131|
| Maximum loss streak |5|5|5|5|

All15 potential signals were accounted for:5 frozen ATR/cost rejects,1 occupied-position reject,9 completed trades,0 unresolved. These are the SAME9 opportunities, not18 independent observations. Cost2x reprices the same fills; it is not leverage. Summed trade-bps and realized trade-sum DD are not account returns/drawdown.

**Decision:** preserve one-case loss-reduction evidence only. Both gross and net remain negative. This does NOT qualify as a profitable strategy or generalized exit improvement, and receives no material grade promotion. The fixed comparison is closed. Do not keep adjusting the exit threshold on this window; no follow-up variant or other-lane execution was activated.

## Where all improvement came from

Exactly1 DOGE trade changed. Original max-hold Net1x -523.109068 became -415.016751 at the first eligible received nonpositive-momentum observation, a +108.092317trade-bps change. Total net loss fell15.175114% and trade-sum DD fell108.092317bps. The child had already lost substantially by this observation; the zero-cross failure exit did not rescue its entry.

All other8 outcomes are identical. Improved1, harmed0, parent winners harmed0, added opportunities0, missing opportunities0. The two positive trades retain the same prices/times/net. Therefore observed winner preservation is real for this tiny sample, but its generalization is unestablished. This design was motivated by the already inspected DOGE loss; one affected trade is especially weak evidence for adoption. No DOGE deletion, favorable substituted fill, monthly filter, alternative threshold or counterfactual parent replay was used.

Child42 management observations include exactly1 new failure-exit event. It uses the already frozen receipt-aware simulator and existing full-post-entry30m callback clock. Resting stops retain priority whenever hit earlier. The numerical native entry, initial stop, positive-weakening exit, max-hold, fit and reference cost rules remain unchanged.

## Actual execution and immutable evidence

Reviewed source472aef593d73dc5123ddbd191f2543603e9e956f passed32 generated tests and22 returned PR workflows before activation. Automated review summary5992087961 completed at2026-10-05T09:57:44Z with no inline findings and bot approval reaction545446646. This is automated review plus maintainer publication, not independent human approval.

Separate approval commit5a657c334e7bd4d430ef58bb80de6f2b672750e4 binds source and contract0717e695a33abed5ec3c362bc4e266b3ff9475766e8eab3186a30544ed61e088. Activation175b056bf3897f6af3a4dfe120ecacd23c7681ec added only RUN_GITHUB.json. Actual Actions run37293808916/attempt1, economic job111710360092, completed successfully. Permanent atomic claim212fad80d3886b0622fb4e3feed871333dac1966 was created before model execution. Child STARTED2026-10-05T10:02:00.956723Z. Original parent input/result and new runner source are hash-pinned. One allowance consumed; remaining0.

Downloaded artifact11337563059 ZIP SHA2567fbfeed38a94f9ddf491fd3ab7106f50da30cbbd755a640637849cd60dd1ca78 verified. Nine archived source files match local reviewed bytes, all source pins and expanded price input3da2f940... match. Full8 original result JSON files are permanently preserved as lossless RESULT_BUNDLE.json.xz SHA256c8cfdcb32fdc6db8efffd9ce535b98e75a1b84a19499ad23dad5e72a92ad97e4. SUMMARY1f6897a6..., child RESULTecfe8a28...; exact hashes appear in COMPLETION.json.

Independent stdlib saved-only audit reconciles gross/net/cost1x2x/WR/PF/expectancy/grouped realized DD/losing streak, signal accounting, simple receipt-order chronology and occupancy, and paired common/unique attribution. Audit SHA256294a92b2411f3503a0d07a7fd629eff2d47e73cab0abe27c961f141b3c5ae6ea. It does not regenerate a signal or replay an economic path; it is NOT an independent exchange-fill simulation. Local44 generated tests passed:32 preexecution plus5 arithmetic and7 event/fill evidence regressions. Final publication CI/review/merge must be observed separately.

## Saved-audit review correction

P2 review4182966238 on publication a02f355 was accepted: arithmetic agreement alone did not independently establish unchanged fills or link the failure callback to the changed exit. The saved-only auditor now cross-indexes signal keys and trade records, requires exactly one matching failure event for each failure exit, and verifies its effective timestamp/reason against the trade. It compares11 entry/exit/clock/reason/amount fields on every common trade, separately flagging equal-net but changed-fill cases. Seven generated regressions reject mismatched times/reasons/signals, missing/duplicate events and events without a completed trade.

The stronger audit confirms8 identical trade records and1 changed DOGE record. The sole failure event and trade share exit1790055180000ms at price0.0986; observed momentum -0.0000738428571428599 was received at1790055176175ms, before the effective exit. No new economic path was evaluated. Original bundle/result/source/contract hashes are unchanged. Prior arithmetic-only audit f6b4ff4e94534e85e022e6ffe047c1a45fad8fb6abc22a0ec96702d4e40e428c and its37-test CI remain historical evidence; the new audit digest above supersedes only that verifier output, not the market result. Final exact-head CI/review is recorded separately.

## Preserved failure and normal integration

Push measurement guard37293808930/job111710205453 failed because published master39b02985 contained newer unrelated `a1_top5_evolutionary_synthesis_latest.json` than activation. This is preserved as an integration failure, not a strategy failure. Publication normally integrates that master without editing any verifier or allowlist. No economic retry is required or permitted. Old backend, strategy files, telemetry, guards, PR1356 results and permanent old claim remain intact.

## Limits and next boundary

Fixed six-symbol input2026-09-15T20:00Z–2026-10-04T00:55Z,18.204861days, was already consumed development data. Neither this comparison nor its parent is certified untouched OOS/fresh. Historical seed/config readiness and minute-open fill/stop/ACK are model assumptions. Account NAV/DD, actual funding, sizing/margin/liquidation and running consumers are not certified. No G5A shortlist/G5B/G6/Core/LIVE authority changes.

This output answers the authorized exit question: it reduces ONE known failure but leaves entry economics negative. Preserve the failure exit as unvalidated research material only. The next profit-development question must address entry-mechanism evidence/possible replacement or separately justified broader frozen-rule validation, NOT repeat this same exit tuning or call loss reduction a successful income system. That next scope is not automatically started here.

Current workflow is saved-only contents:read; economic job is removed. COMPLETION prevents the consumed driver from executing. Contract, approval, claim and actual RUN remain preserved; never reset them. No deployment, SSH/service change, source collection or orders occurred. Rollback only this PR's additive files, preserving original and derived evidence. No user Work handoff or file upload is required.
