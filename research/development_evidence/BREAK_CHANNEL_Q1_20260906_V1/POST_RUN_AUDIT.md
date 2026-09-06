# Independent Q1 ledger and execution audit

This is a post-outcome verification note, not a change to the preregistered rule, goal, result or trial allocation. Preregistration commit: `69be0aef86e04ddfa10d325cd4990954c6c5d8f4`. Result seal: `3ef91131a4f248475d7db5da0813df46ef0c23da1cf43641cda706196eb65e6b`.

Two independent read-only audits passed. Accounting checked 413 completed rows across P/Q0/Q1 fixed/Q1 full, P's one unfinished position, and all 118 preserved-file hashes. Price returns, elapsed 8h funding boundaries, the 20bps floor, costs, PF/payoff, exposure, daily marked drawdown, simultaneous-close losing runs and symmetric origin/terminal bridges reconcile.

Execution checked 102 original UP formulas/two-close confirmations, 625 original DOWN confirmations, 172 candidate ledger rows and 502 trace rows against the approved DEV data. Each candidate view has 86 completed positions and no unfinished position. All 16 protection increases across 13 positions activate at the next 4h open and strictly increase the stop. Entry times, prices and initial protective levels remain identical for all 86 Q0 origins. Each view has 32 original intrabar stop exits, 47 original bearish next-open exits and seven new ratchet intrabar exits. Observed gap fills are zero; gap priority is covered by synthetic tests only.

Exactly seven exits move earlier, by 248 hours in total (10.3333 symbol-days). Full replay still has 86 fills and 16 occupied exclusions from 102 opportunities. Freed intervals admit no additional eligible UP signal. Fixed and full fills/economics coincide; common origins 86, new 0, removed 0.

## Complete additive net bridge

| Q0 to Q1 contribution | Trade-bps |
|---|---:|
| Reduced existing losses | +64.999421 |
| Worsened existing losses | -22.403748 |
| Cut positive winner profit | -468.220756 |
| Additional loss after a winner becomes a loser | -40.342346 |
| Increased winners / new trades / removed trades | 0 |
| Total net change | -465.967428 |

This is a net bridge: do not add cost savings again. The alternative gross/cost bridge is -499.047428 gross plus 33.08 saved costs. Funding savings are 34.08; the floor reserve increases by 1, leaving 33.08 total savings. Fees remain 860 trade-bps. Original winner profit retention is 97.771506%; all three top-decile winners retain 100% of their 10,154.193075 trade-bps profit. Failure is not caused by losing those three large winners.

## Calendar and concentration limits

Q0's pinned 2025-05-11 to 2025-07-08 marked-loss window changes from -6,801.478761 to -6,802.9502 trade-bps, approximately -1.47144 incremental net. The global maximum marked drawdown rises from 6,801.478761 to 6,886.8051 because Q1's peak moves to February 15. The difference between maxima, 85.3263, is not the causal contribution within Q0's pinned window. Both maximum completed losing runs remain 5,224.687753 trade-bps in the February 1 to April 20 interval.

LINK alone contributes 4,687.2909 closed net trade-bps, exceeding Q1's total 3,610.1755; July contributes 10,122.5096. Dependence on profitable symbols/periods remains. April versus May closed-profit changes partly reflect earlier realization and are not standalone causal gains. The paired 30-day block interval for Q1 minus Q0 daily marked PnL is [-3.873274, -0.240944] trade-bps/day. It describes repeatedly used DEV data, not independent validation.

Q1 meets exposure reduction, large-profit preservation and the existing absolute closed-economics checks, but fails aggregate terminal PnL preservation in both views and full marked-DD non-deterioration. Therefore Q1 remains DEV_REJECT and Q0 remains the research reference with its original DEV_INCONCLUSIVE. Code correctness does not imply economic adoption.

One new hypothesis consumed, cumulative 25, remaining approved slots 0. Fixed/full views and verification are not additional hypotheses. No Q2, outcome-driven rule changes, paid external AI, validation/OOS decoding, G5B changes or operating authority changes occurred. execution=NONE / order=BLOCKED / live=BLOCKED.
