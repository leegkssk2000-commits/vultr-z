# TrendRider unified S4 recovery — sequential failure decomposition (2026-10-25)

**Economic verdict: HOLD_ROBUSTNESS_FAIL, no production promotion.** A single frozen unified model from PR #1469 was already tested historically. This incremental step separates technical short-confirmation failure, pre-entry risk economics, and authenticated **public** funding/tick metadata. Research only; no new Work, global-heavy job, exchange account call, live/paper order, or mutation of baseline trade ledgers.

## Source/identity/reproducibility

- Parent fixed S4: [PR #1469](https://github.com/leegkssk2000-commits/vultr-z/pull/1469), commit d256807c58a41d77606df1a844a2d13c2cfff945, `RESULT.json` SHA256 e99bbd783908628572a64875f7d019676fa5d686fdc7e7b29fd24cee2d4fab13, 12 original 1h OHLC symbols × 1000 bars (only previously approved saved source; no new klines).
- Original 267 distinct *candidate intents* = 119 Liquid6 + 148 Delayed unique; 97 duplicate shared signals removed and 4 invalid delayed stops quarantined. S4 originally 121 admitted trade opportunities / 192 long+short legs.
- `FREEZE.json` SHA256 afd689a36644a40bb62bca976680b3b15d1ffb76e002a7e1b31d089ff2fa4c28 written **before** evaluating the two indicator/cost gate hypotheses. Never tune ADX14 period/25 threshold or initial-stop 10bp threshold on this used window.
- BingX official market source: [public perpetual funding/contract API guide](https://github.com/BingX-API/api-ai-skills/blob/main/skills/swap-market/api-reference.md) & [fee schedule](https://bingxservice.zendesk.com/hc/en-001/articles/11257219036175-Fee-Schedule). Exactly 24 public REST successful responses (12 contracts and 12 funding histories), source identity/time/raw SHA pinned, no authentication used, 0 failures, not a new data collector. API responses obtained Oct25 2026 after the entire historical trade window; historical quote *received-at* cannot be invented.

## Stage1 — independent bearish trend quality, exact PREDEFINED ADX14 (FAIL)

Source: [Fidelity ADX(14) & DI interpretation](https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX), where 25 is a conventional strength signal, not a guaranteed win predictor.

Existing source SHORT reversal requires bearish EMA20. New test permits the short ONLY when **last completed** hourly signal bar Wilder ADX14 >=25, rising vs previous completed ADX14, and -DI14>+DI14. Original LONG entry, exit, extended winner, risk circuit and fee model unchanged.

| Variant | Admitted original opportunities | Reverse shorts | Native modeled Net2 sum trade-bps | PF2 | Realized leg DD2 | Max loss run |
|---|---:|---:|---:|---:|---:|---:|
| S4 baseline | 121 | 71 | +1752.48 | 1.294 | 2225.86 | 14 |
| S4+ADX14 bearish strength | 123 | 7 | **+211.53** | 1.036 | **3651.91** | 27 |

Additional 40 instrument bps per realized leg: S4+ADX Net2 **-1521.80**. Leave out 1000PEPE & replay whole ownership -> **-104.59**. Strong ADX mostly eliminates profitable short reversals; REJECT this fixed hypothesis. Do NOT loosen 25 or search ADX variants on the same labeled cohort.

## Stage2 — published taker fee / sealed stop suitability (FAIL)

Standard BingX taker 0.05% open + 0.05% close -> **10 instrument bps roundtrip** (actual user VIP status, rebate and spreads unknown). At the scheduled LONG entry **before any future result exists**, only accept originally sealed stop-price distance >=10 instrument bp. Fee baseline is an external market specification, NOT a threshold fitted to profitable symbols or trade labels.

| Variant | T | Short legs | Net2 | PF2 | DD2 | Max loss run |
|---|---:|---:|---:|---:|---:|---:|
| S4 original | 121 | 71 | +1752.48 | 1.294 | 2225.86 | 14 |
| Fee-floor 10bp native entry | 118 | 68 | **+1414.01** | 1.234 | **2430.74** | 14 |

Extra 40bps/leg gives **-1065.99**, full leave-one-1000PEPE **-792.68**. This gate is necessary engineering feasibility to investigate before orders, but **not an economic improvement** on this population. Reject as alpha enhancement; do not weaken standard cost to game Net.

Because neither independent hypothesis passes Net and DD/PF, their combination was **NOT attempted**. No combinatorial parameter search.

## Stage3 — historical signed funding and per-symbol contract metadata; actual exchange DATA collected

BingX contract metadata returned advertised standard taker 0.0005, maker 0.0002, pricePrecision and quantityPrecision for all 12 exact symbols. BTC/BCH/ETH, etc. settle funding every 8h in the observed window; **ETHFI and HYPE funding settle every 4h**, confirmed by full timestamp step on 256 observations each (others 128). Overall **1792 observed historical funding-rate records**.

Original saved reference cost code `backend/research/rebuild/a1_exact25_generic_evaluator_v1.py` computes `funding_cost` as `abs(rate)` sum for native LONG model. This is a conservative charge without direction-aware financing, and the original budget queried the latest 100 funding rows by symbol, which can omit earlier history. We have now pinned each original actual signed `fundingRate` by `fundingTime`, retaining native original snapshots' fee, spread, impact. Long funding cost sign = positive rate, SHORT sign = negative rate. Replayed S4 including its 3-loss risk circuit with funding recognized *only after completed simulated leg* (no future-funding entry filter). Ambiguous exact entry/final hourly STOP settlement boundaries are tagged and charged conservatively in both scenarios. Signed venue funding records are genuine public history, **not proven individual account debits/credits**, and source snapshot depth/spread/impact were not historical per-trade quotes.

- **C1**: native fee+spread+impact x2, definitely settled signed funding once, ambiguous positive payable included, credits at ambiguous points excluded, already-frozen model extension carry buffer preserved.
- **C2**: native fee+spread+impact x2, definitely settled positive funding debit x2, any funding credit ignored, possible boundary liabilities x2, extension carry uncertainty buffer preserved.

| Attribution (C1/C2) | T | Net2 trade-bps | PF2 | Realized leg DD2 | Max loss run |
|---|---:|---:|---:|---:|---:|
| S4 original abs funding modeled | 121 | +1752.48 | 1.294 | 2225.86 | 14 |
| C1 signed settled rates/uncertain boundary | 121 | +2236.59 | 1.396 | 1987.43 | 14 |
| **C2 extra-conservative paid-only model** | 121 | **+2103.77** | **1.368** | **2050.12** | **14** |
| C2 +20bp extra per Long AND Short leg | 121 | +823.77 | 1.125 | 2727.29 | 14 |
| **C2 +40bp extra per Long AND Short leg** | 121 | **-456.23** | **0.939** | 3408.52 | 14 |
| C2 SHORT next execution delayed +1 full 1h | 118 | +538.60 | 1.086 | 3375.10 | 9 |
| C2 WITHOUT 1000PEPE, full owner/circuit replay | 115 | **-396.84** | 0.936 | 3341.20 | 15 |

C2 121 accepted LONG leg source includes 45 ambiguous historical funding settlement boundaries; 71 SHORTS include 34 such boundaries. C2 robust source-proxy funds are not audited broker fills; missing actual historic bid/ask slippage and private signed account settlement mean formal 40bp robust PASS still impossible.

## Native executable-price defect: stop geometry must be quantified before Shadow

Published BingX contract `pricePrecision` constraints do **not** prove a full quote-tickSize mapping. Price-precision check flagged **121/121 S4 LONG initial stop values and 71/71 SHORT initial stop values as nonaligned with the advertised decimal precision grid** (continuous ATR/indicator price from saved source). They are floats from old simulators, not proven executable exchange stop prices. Moving LONG stops down and SHORT stops up to valid price precision (more conservative) has an *indicative* same-fill penalty of about 17.54 trade-bps summed across longs plus 7.53bps across shorts, but **exact trade timing could change** once stops are truly requantized. We have not relabeled existing saved fills as executable or overwritten any source PnL. The stop-as-of quote/tick/fee lineage needs first-class replay with authoritative 1m/quote data.

## End disposition

- New tests ADX14 DMI short quality **FAILED** and minimum stop-price 10bp fee floor as economic improvement **FAILED**. No same-data threshold tweak. Signed fund data corrected an *economics approximation*, NOT the negative stressed result.
- Original integrated S4 preserved as `USED_DEV_RESEARCH_HOLD`, not a fresh qualified strategy; cost40 and loss of one source symbol still ECON_FAIL, max 14 consecutive losses, no broker book fills/funding account settlement, no G5 or formal K117/B Shadow credit.
- The only separate useful current Work B task is **read-only verified 1m/tick & actual fill-time source adjudication** on existing 12 symbols; stop when source absent and do not retry disallowed BingX historic 4-min downloads. See `WORK_B_SOURCE_ONLY_HANDOFF.md` in this folder.
- A economics sole global-heavy owner untouched; do not start duplicate full, create new A–F lanes or run this source collection again unless explicit new source/version authorizes.

## Content SHA

This exact packet contains `FREEZE.json` (H1,H2), `RESULT.json`, `FUNDING_RECONCILIATION_FREEZE.json`, `FUNDING_REPRICE_RESULT.json`, every signed funding history/contract RAW response, one public source receipt containing per-request SHA and response UTC, source-reconstruction and 12 anti-lookahead/side-cost regression tests. Canonical sha line output generated at publication, none overwritten.
