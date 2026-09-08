# PR1212 continuation — saved-origin attribution, not another experiment

Source head: b50eea7f685a7162b1743d5862d315fc92fecf9e. Downloaded saved DEV artifact10037006426 from run34175207506; ZIP SHA256 8e75dbd88d33d347488fb7cf52faceedd89f6ea75932a9a7b281bc5f0d54f6e8.

No native replay, raw market collection, new candidate, paid provider request or sealed/OOS access. The original twelve attempts45–56 and their fixed results are unchanged. KR3 remains TRADEOFF and G5A HOLD. This is post-measurement accounting on already-used DEV2025, not a preregistered significance result.

## Origin mapping and accounting

Use REGIMES.json.gz annotated_closed/open for original KR3 amounts. Use direction_flip RESULT events only for the original signal/eligibility clock, NOT its reflected PnL. The203 original position origins match that result's entry/exit/mark indices, timestamps, prices and cost hash. There are379 original events. Each shifted origin is matched by `(symbol, shifted_signal_index - offset)`; no fuzzy timestamp or PnL-based match. Each control contains378 events because one end event is outside the shifted input cutoff. All child positions are contained in that original signal population.

`parent absent = 0` in the accounting identity means no position, NOT a zero-return trade or win. Costs are already in net. Open marks are hypothetical full-roundtrip liquidation values, not completed losses avoided. These disjoint partitions reconcile to full terminal differences; float residual is zero in the calculation below.

| Partition | +6 observations: origins | +6 net contribution, trade-bps | +1 observation: origins | +1 net contribution, trade-bps |
|---|---:|---:|---:|---:|
| Common closed original opportunities |106|−1,020.467974|102|−6,612.441564|
| Removed original CLOSED opportunities |96|+6,764.357848|100|−1,507.189771|
| Removed original OPEN end mark |1|+76.731064|1|+76.731064|
| Newly admitted CLOSED opportunities |12|−576.088719|7|−2,308.320087|
| Newly admitted OPEN mark |0|0|1|+368.798513|
| Total increment | |+5,244.532219| |−9,982.421845|

Original terminal net10,264.995799; +6 terminal15,509.528018; +1 terminal282.573954. Original all-cost2 terminal5,744.227514; +6 all-cost2 terminal12,855.944787; +1 all-cost2 terminal−2,146.539961. Equal-notional trade-bps only, not account return/DD.

## What removed +6 opportunities?

94 original closed opportunities were rejected by `SIGNAL_CLOSE_BELOW_DIRECTIONAL_HALF` at the SHIFTED bar. Their original net total was −7,434.063687; the accounting contribution of absence is +7,434.063687. Another2 original closed opportunities were blocked by `RUNNER_OCCUPIED`, losing +669.705839 of original gains. The remaining1 is the original unfinished position beyond the shifted cutoff, accounted separately above.

The96 removed closed originals contain34 winners and62 losers. The12 new closed trades contain4 winners and8 losers. Of those12,9 were originally blocked by directional-half (new net−943.829036),2 by reference reservation (new net+221.191771) and1 by reference-exit-bar ownership (new net+146.548547).

Therefore the observed +6 increase is dominated by a DIFFERENT admitted opportunity set. The aggregate common-origin change is negative. It does not establish that delaying the same trades by six bars improves their execution. Shifting also relatches exit anchors, rechecks signal-bar geometry and regenerates actual/reference occupancy.

The +1 control removes100 closed originals, all due to shifted directional-half, but those originals had positive aggregate net. Its common and new closed contributions also deteriorate. This counterexample rules out a simple interpretation that more delay is monotonically better.

## Preserved damage and concentration

Capped original-winner profit retention at identical original signal origins is45.72% for +6 and45.29% for +1. This is a diagnostic accounting definition, NOT an approved formal G5 retention gate. It includes omitted original winners and changed exits; higher total profit does not mean old winners were all preserved.

+6 net increments by symbol: 1000PEPE+2,114.70; BCH−581.86; BTC+125.83; ETH−247.57; HYPE+4,577.58; LINK−2,762.10; SOL+2,017.96 trade-bps. Largest positive single-origin increment: HYPE signal_index1015, +2,881.951040 (original−366.531825 → shifted+2,515.419215). Excluding that contribution only as a sensitivity calculation leaves +2,362.581179; this is not a proposed trade filter.

## Next justified question, not automatic KR4

Preserve KR3's trend/reclaim/directional-half and its fixed management modules. Testable follow-up must distinguish waiting from requalification and occupancy, starting with the saved original-signal trace. A later-bar condition cannot be applied retroactively to the original entry. No six-bar optimum, full-DEV volatility cutoff, profitable cohort deletion or new threshold is adopted here. Any candidate requires its own exact rule, budget, pre-outcome freeze and complete replay including new/displaced trades, and later independent validation.

## AI review defect addressed in the accompanying patch

The provider dossier now embeds every12 fixed results with exact metrics, current gate failures, report states and limitations. SPEC/G5A_RESULT/INDEX are added to the source allowlist. Before any reservation the route recomputes the bounded summary from those fixed files and rejects omitted/edited/stale outcomes. Both Gemini and OpenAI serialized request paths are covered by mock-transport tests. The template remains unsigned/non-authorizing; quote/keys/manual dispatch/shared USD5/provider1 guards are not relaxed. Actual provider calls remain0.

This MD is a new interpretation record, not a modification of original results. No frontend deployment required. CI/merge status is recorded separately in the PR to avoid result/receipt self-reference and economic replay loops.
