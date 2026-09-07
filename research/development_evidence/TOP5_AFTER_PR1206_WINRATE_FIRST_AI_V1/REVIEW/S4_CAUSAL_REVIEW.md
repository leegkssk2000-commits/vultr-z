# S4 bounded causal and overblocking review

Scope: `TOP5_AFTER_PR1206_WINRATE_FIRST_AI_V1`. Base: `2646f818775caff88a97f81fe255b393eb9c141d`. Writable paths: this scope's `REVIEW/` only. Root selects the candidate. No market replay, native price reads, market feature pass, cutoff scan, paid API call, recursive delegation, 406-row reaudit, or historical 16/30 audit was performed. User authorization explicitly permits this research outside the default frontend scope in `AGENTS.md`.

## Decision before freeze

The S1 pre-scan hypothesis is technically eligible for one bounded entry experiment: veto an original Primary signal iff `side_sign * (signal_close - signal_open) < 0`. Keep doji eligible. This is a causal, non-vacuous eligibility change at the original signal close, with no delay. It is **not established economically superior**, and it overlaps the rationale of a prior failed local price confirmation filter. Its actual held-trade winner loss is substantial enough to require the prescribed protection metrics.

The accompanying executable synthetic review passes. An exact native Primary long signal with current open 102.72 and close 102.70 remains eligible in the parent; native initial SL is 101.75699526239069, chase is 1.382660527336268 ATR, the previous candle aligns, previous parent confirmation is false, and the US cooling condition passes. The proposed rule rejects this signal. The check also covers fixed-index future independence, the disabled veto, long/short symmetry, doji equality, and distinction from the failed prior-extreme predicate. This validates the specified predicate; root's integration still needs its own minimal adapter verification.

## Existing mandatory conditions and availability

The native parent already requires matching Supertrend direction, close beyond its Supertrend line and EMA50, matching EMA50 slope, and the **previous** candle's aligned or flat body. The intent adds `st_gap_atr >= 0.10`, `chase_atr <= 2.0`, freshness and the structural cost budget. Primary further requires the raw parent confirmation false-to-true transition and, during US hours, current chase no larger than previous chase. These are not new explanatory filters. S1 reports all 406 held origins already satisfy native maintained state.

Current signal OHLC is fully completed when the original next-open order is decided. The signal candle's body is available then; next candle HLC, first-SL-bar HLC, final MFE and final outcome are not. A filter must use the explicit original `signal_index`, never the last row of a full future-containing array. Do not replace this rule with signed close-to-previous-close: gaps make those definitions differ.

Initial-stop count alone does not prove the SL is too narrow or that immediate adverse motion caused all losses. S1's completed-bar diagnosis reports 159 of 288 SL outcomes had a pre-SL completed close beyond the contemporaneous modeled cost, 65 never had a positive pre-exit completed close, 49 were positive but never beyond cost, and 15 first-entry-bar stops are intrabar-unknown. These are outcome diagnosis categories, not entry features or an authorization to change stops/exits.

## Bounded failure-list comparison

| Existing source | Exact meaning | Relationship to this hypothesis |
| --- | --- | --- |
| `top5_development_repair_v1.json` fixed diagnostic list; `top5_development_repair_v1.py.geometry/diagnose` | `directional_body_positive = sign*(signal close-open)>0`; stored False/True diagnostic groups | Already observed diagnostic, not an unseen feature. Proposed doji allowance uses `>=0`, so False is not exactly the proposed veto group. |
| `top5_development_children_v1.json`, Primary `precision_prior_extreme_v1` | Long close at/above prior high; short close at/below prior low | Actual prior entry candidate. Same broad local-countermove rationale, but not identical: a favorable current body inside the preceding range passes the proposed rule and fails this prior filter. Neither should be claimed a new source of independent evidence. |
| `top5_external_children_v1.json`, Primary `dmi_direction_fade_veto_v1` | Veto prior side-aligned DMI with non-rising ADX | Different inputs/state, shared weakening-direction interpretation; the new predicate is not a rename of its code. |
| `top5_state_children_v1.json`, Primary `setup_first_signal_v1` | One raw signal per side/EMA50 setup; reset on closed opposite-side EMA50 crossing, blocked signals consume setup | Different stateful rule; adding episode/reattempt suppression would be another axis and repeat a failed mechanism. |
| `top5_no_credit_exit_v1.json`, Primary `cost_cover_lost_exit_v1` | Exit after previously achieved completed-close cost coverage is lost | Exit mechanism, not this entry axis; preserved as negative evidence rather than retuned. |

In these inspected frozen sources, exact current-body eligibility is **diagnostic-only, not an actual failed Primary candidate**. That statement is bounded to the recorded hashes. Recent `a1_trend_rider_exact_parent_repair_latest.json`, separate Work, observer/future paths, and economic paths were not inspected. Existing momentum/ATR/multiscale/consensus policy definitions were read only to distinguish inputs; no new outcome audit of those policies was performed.

## Counterexamples and selection effects

S1's delivered summary has SHA256 `8f133d3d239335dc02a04b5e5eb079ab086ed9a4061dd8a0dd38739c5fe0dade`. These counts are received evidence, not a repeated S4 feature pass:

| Existing held-origin state | Trades | Losses | Winners | Large winners | S1 late-recovery winners |
| --- | ---: | ---: | ---: | ---: | ---: |
| Adverse current body; proposed veto | 123 | 96 | 27 | 3 | 5 |
| Aligned or flat current body | 283 | 200 | 83 | 8 | 28 |

Thus the same entry-time state contains stop losses and material winners. Three adverse-body large-winner origins are `2efa61890c25a88bbfd2d8130a8f04f3f7705261b13690496f448a3242256137` (BTC-USDT), `9aef8180503fb75ac9d27bef899da394c0db4d8c90531014f4d2d4721c6881bc` (ETH-USDT), and `d8b97717b1ee3b2a1a30d3608ba28332f10fb2b5fe5c11b3cb87b8f5736730b5` (ETH-USDT). Their completed-close evidence remains in S1's summary; do not treat hypothetical late recovery as the only counterexample.

S1 also reports 83 reattempts after an earlier SL, with 28 winners and two large winners. A prior SL is therefore not sufficient evidence for another first-attempt/episode veto. A state defined using **actual** prior admitted positions changes under candidate occupancy; parent actual states cannot be reused unchanged as if they were candidate-causal states. The chosen stateless current-body rule avoids that dependence.

All 1,555 raw signals contain 743 adverse-body states and 812 aligned/flat states, whereas only 406 existing held positions have known stored outcomes. The other 1,149 outcomes are UNKNOWN. Neither their exclusion nor their body state assigns a loss or zero return. The held-origin comparison is selected by existing occupancy/cooldown; it cannot establish performance on the full raw signal population or a realized portfolio.

## Integration and accounting checks handed to root

`top5_native_finite_runner_v1.replay` overwrites event admission with true. Merely annotating `admission=False` does not execute this filter. Root has acknowledged implementing a real pre-entry tape filter, preserving all raw veto/occupancy events, and passing only eligible events to unchanged TPC1 serial replay.

FIXED must be only the retained subset of stored TPC1 FULL paths. FULL must use original chronological signals with native actual position ownership and cooldown. A veto reserves no position and produces no synthetic zero-profit trade. Root must verify all common origin exit/cost paths remain identical, preserve uncompleted positions, and reconcile avoided losses minus missed winners plus added/removed follow-up contributions to total delta. Root remains the single serial economic owner because the parent replay uses a temporary global path binding.

No conclusion is made about net, cost2, DD, or economic acceptance before that measurement. The minimum meaningful remaining checks are the actual adapter's veto-off parent parity, no decisions changed by future bars, occupancy/veto event handling, common-path identity, and required result-accounting checks. No new numeric cutoff or additional candidate is recommended.

Inputs and synthetic validation are recorded in `s4_counterexample_result.json`. This handoff ends the pre-freeze review; no additional audits will be performed unless root requests the already planned one stored-result accounting pass.
