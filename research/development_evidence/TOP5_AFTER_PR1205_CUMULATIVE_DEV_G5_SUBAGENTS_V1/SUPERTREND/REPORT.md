# Supertrend H12: stored causal timeline diagnosis

Status: DIAGNOSTIC_COMPLETE; next strategy NOT_RUN / DISTINCT_EXECUTABLE_DISCRIMINATOR_UNRESOLVED. New strategy replays 0, new candidates 0, paid API calls 0, formal credit 0.

The new evidence separates persistent absence of favorable completed closes from favorable progress later lost. Neither is by itself a safe exit discriminator: eventual winners also start below entry and cross back below entry. These are observational timing decompositions, not causal treatment effects or counterfactual profits.

Only stored SR1 `views.P` original long H12 origins were used. The native H12 convention is twelve held 4h bars, with the original close exit on held bar 12. States k1–11 use completed closes strictly before that exit; the exit bar high/low/close is excluded from state features. Final stored exit price is used only for source parity and postoutcome labels. No final MFE/MAE feeds a state. At close k, an action could first occur at the next observed open; no such action was simulated.

SPEC.json was frozen at 2026-09-07T13:26:07.282026+00:00 before the first bounded timeline scan. All k1–11 are reported; no preferred cutoff was selected.

## Disjoint final cohorts

Values are equal nominal trade-bps, not account percentages. Cost-flipped means positive stored gross but negative stored net and takes priority over giveback. Giveback means a positive pre-exit completed close occurred, followed by nonpositive terminal gross. No-favorable means every pre-exit completed close was at or below actual entry; intrabar favorable highs remain unknown to this label. Ordinary winners exclude the top ceil(10% of positive net outcomes), following the existing large-winner convention.

| Period | Cohort | T | Stored gross | Stored cost | Stored net | First close at/below entry T |
|---|---|---:|---:|---:|---:|---:|
| DEV2025 | COST_FLIPPED | 5 | 39.4248 | 107.7384 | -68.3136 | 1 |
| DEV2025 | GIVEBACK | 75 | -25641.2562 | 1612.2255 | -27253.4817 | 25 |
| DEV2025 | LARGE_WINNER | 11 | 18939.3599 | 251.7364 | 18687.6235 | 4 |
| DEV2025 | NO_FAVORABLE_CLOSE | 57 | -30755.1992 | 1227.3910 | -31982.5903 | 57 |
| DEV2025 | ORDINARY_WINNER | 95 | 37050.2598 | 1986.2754 | 35063.9844 | 47 |
| SEEN2026 | GIVEBACK | 29 | -8130.9279 | 620.4167 | -8751.3446 | 14 |
| SEEN2026 | LARGE_WINNER | 4 | 9622.5050 | 89.1984 | 9533.3066 | 2 |
| SEEN2026 | NO_FAVORABLE_CLOSE | 16 | -6988.4314 | 351.7364 | -7340.1677 | 16 |
| SEEN2026 | ORDINARY_WINNER | 35 | 14134.3973 | 735.3595 | 13399.0378 | 19 |

The 2025 partition sums to the stored 137 losses / −59304.3856 trade-bps; 2026 to 45 / −16091.5123. Gross-positive cost flips account for only 5 losses / −68.3136 in 2025 and none in 2026. Costs still worsen every loss; this specific sign-flip classification does not imply costs are otherwise irrelevant.

2025 has 243 completed P trades and 3 open observations; seen2026 has 84 completed and 5 open. Open origin keys are preserved in the artifacts and excluded from winner/loss labels.

## Full pre-exit timeline: no favorable completed close yet

Each cell counts trades whose maximum completed close through k remains at/below entry. It is a causal state cross-tabulated by a final label. Row choices are exhaustive k1–11, not tested exit rules.

### DEV2025

| Held close k | No-favorable losses | Giveback losses | Cost-flipped losses | Ordinary winners | Large winners |
|---:|---:|---:|---:|---:|---:|
| 1 | 57 | 25 | 1 | 47 | 4 |
| 2 | 57 | 14 | 1 | 29 | 2 |
| 3 | 57 | 12 | 0 | 18 | 2 |
| 4 | 57 | 8 | 0 | 15 | 1 |
| 5 | 57 | 5 | 0 | 14 | 1 |
| 6 | 57 | 3 | 0 | 11 | 1 |
| 7 | 57 | 2 | 0 | 11 | 1 |
| 8 | 57 | 0 | 0 | 9 | 1 |
| 9 | 57 | 0 | 0 | 7 | 1 |
| 10 | 57 | 0 | 0 | 6 | 0 |
| 11 | 57 | 0 | 0 | 4 | 0 |

### SEEN2026

| Held close k | No-favorable losses | Giveback losses | Cost-flipped losses | Ordinary winners | Large winners |
|---:|---:|---:|---:|---:|---:|
| 1 | 16 | 14 | 0 | 19 | 2 |
| 2 | 16 | 9 | 0 | 10 | 0 |
| 3 | 16 | 6 | 0 | 7 | 0 |
| 4 | 16 | 4 | 0 | 6 | 0 |
| 5 | 16 | 3 | 0 | 4 | 0 |
| 6 | 16 | 2 | 0 | 3 | 0 |
| 7 | 16 | 2 | 0 | 2 | 0 |
| 8 | 16 | 1 | 0 | 2 | 0 |
| 9 | 16 | 1 | 0 | 2 | 0 |
| 10 | 16 | 1 | 0 | 1 | 0 |
| 11 | 16 | 0 | 0 | 0 | 0 |

## Adverse recurrence after favorable progress

| Period | Cohort | T | Ever returned to entry or below by k11 | No observed return before exit |
|---|---|---:|---:|---:|
| DEV2025 | GIVEBACK | 75 | 70 | 5 |
| DEV2025 | ORDINARY_WINNER | 95 | 38 | 57 |
| DEV2025 | LARGE_WINNER | 11 | 1 | 10 |
| SEEN2026 | GIVEBACK | 29 | 27 | 2 |
| SEEN2026 | ORDINARY_WINNER | 35 | 9 | 26 |
| SEEN2026 | LARGE_WINNER | 4 | 2 | 2 |

2025: 47/95 ordinary winners and 4/11 large winners had a nonpositive first held close. One large winner first showed a favorable close only at k10, and four ordinary winners never did so before the original exit. 2026: 19/35 ordinary and 2/4 large winners began nonpositive. Two of four large 2026 winners crossed back to entry or below after already favorable progress. Thus an unconditional early adverse-close exit or favorable-then-return exit directly shares states with winners.

Five 2025 and two 2026 giveback losses never returned to entry or below at any pre-exit completed close. Their loss was first observable at the original exit close; using that final close to trigger an earlier exit would be lookahead. The complete first-favorable/first-return timing distributions and the cost-adjusted state counts remain in RESULT.json; full per-origin states remain in DEV2025.json and SEEN2026.json.

## Stored failed rules, without replay

| Prior mechanism | Existing stored result | What the new timing diagnosis does and does not add |
|---|---|---|
| Frozen signal-low close invalidation | SUPERTREND_INVALIDATION_20260906_V1: DEV_REJECT; FIXED delta −4809.5879; 17 winner-to-loss; FULL net E −46.3531 | Our reference is actual entry and history of completed progress, not frozen signal-low. Winner overlap prevents assuming a new reference solves the failure. |
| Cost-covered close reversal / common BE | TOP5_EXIT_20260906_V1: DEV_REJECT; FIXED +2167.3778 but cut parent winners14753.5738; 38 winner-to-loss; FULL E −15.6245 | Favorable-then-return is close to this failed economic mechanism; these diagnostics explicitly do not rebrand it as a new candidate. Cost-adjusted timeline uses the same research cost owner. |
| Confirmed Supertrend flips | SUPERTREND_FLIP_AB_20260906_V1: A net −13526.7473; B net −6207.4030 with3open; P −5552.7777. A REJECT, B overall INCONCLUSIVE/closed REJECT | This diagnosis keeps all original high-volume momentum P origins. Replacing entries with actual ATR flips changes population and has already failed. |
| Rising ADX14 at signal | TOP5_EXTERNAL_20260905_V1: DEV_REJECT; net E −22.85→−12.49; lost37winners and increased closed drawdown | The new state concerns post-entry progress history, not signal strength; no additional indicator or ADX gate was computed. |
| One native4h delayed entry | TOP5_DIVERSE_EXECUTION_20260906_V1: DEV_REJECT; FIXED E −9.5651; FULL E −11.4846; FULL winner amount retention0.7687 / large0.8374 | Keeping entry fixed and diagnosing later states is distinct from delaying every entry. Choosing a delay or time cutoff from the table would be a new forbidden sweep. |

## Exact unresolved question and required evidence

The distinct structural question is whether an already-entered high-volume momentum position can distinguish an uninterrupted adverse completed-close sequence from delayed recovery while preserving the observed late winners. This is a path-history/transition question, not a signal-low level, signal-strength filter, ATR-flip replacement, blanket delay, or cost-cover reversal. No executable discriminator or action threshold is established here.

The present frozen fields show overlap at every early stage. In 2025 even no favorable close through k11 coexists with four final winners; the large 2025 winner first favorable at k10 rules out treating long initial nonprogress as automatically failed. The missing item is an ex ante justified observable discriminator and frozen action/next-open fill semantics that separate these histories; it cannot be supplied by final labels, final MFE, or selecting the best k. A future diagnostic may predefine a transition descriptor using only earlier native completed closes, but neither its definition, approval, economic test nor promotion exists in this scope. If a proposed mechanism instead depends on intrabar first-touch order, the native4h bars cannot resolve it; an approved timestamped finer-grained source would be required and is not acquired here.

## Provenance, uncertainty, and checks

Both calendars remain DEV_USED, independent=false. The original SEEN2026 partition names (including earlier validation/purged_OOS labels) are retained in source_access as prior usage history; this is the already authorized bounded seen-data reuse, not fresh holdout access. The established reader verifies source file bytes opaquely and decodes only the 3748-row prefix through 2026-09-05T00Z; no later economic row, observer, or raw archive is decoded. Its internal empty-event data-integrity validation does not generate trades. The 2025 slice ends at 2025-12-29T08Z. No online source lookup or paid service was used.

Costs are the frozen research fee/spread/impact/funding proxy and20bps minimum. At each state the displayed cost is a hypothetical full-roundtrip liquidation cost through that timestamp; it is not already-accrued entry cost, observed signed funding, or an actual fill. Neither market impact nor intrabar order can be inferred from these diagnostics.

N_effective UNKNOWN; overlapping symbols and calendar exposure, adaptive reuse, and no independent validation. No significance test or economic PASS is claimed. Three synthetic tests pass: prefix/exit-HLC/final-outcome invariance; disjoint no-favorable/giveback/cost-flip labels; exit-row rejection and independence from stored future funding. Source H12 entry/exit/index/time parity and original gross−cost=net checks passed for every closed trade.

Reproduce stored diagnosis (zero new strategy replay):

```sh
python -m unittest backend.research.rebuild.test_supertrend_h12_timeline_diagnostic_v1 -v
python -m backend.research.rebuild.supertrend_h12_timeline_diagnostic_v1 --data-dir <approved-g5a_stage_v1>
```

Scope owner S4; isolated detached worktree; shared evaluator, ledgers, workflows, and budgets unchanged. No recursive agents or push. Deliverable complete; stop after integration handoff.
