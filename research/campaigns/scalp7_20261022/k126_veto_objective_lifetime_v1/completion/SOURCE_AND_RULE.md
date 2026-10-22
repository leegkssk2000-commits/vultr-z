# Conditional expiry after a missed pullback objective

## Scope and preserved controls

Latest explicit user authorization: proceed after the C114 result. One new fixed lifetime mechanism; no numeric sweep. Preserve K126 at 81a12c422ee9329996d2f6b983267d2def490d4b and C114 at 441fa935d1a7d6711ef8287ef0a6bf34054c6796. The same economic owner executes at most one new policy chronology, under the existing global-heavy restriction. No order, Shadow, Live, paid API, new market API, workflow or master changes.

## SOURCE_FACT — what was actually read

1. Linda Bradford Raschke / David Vomund, AIQ Opening Bell Monthly, August 1997, printed pages 2 and 3. Author-hosted original: https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf . Parsed text and both rendered pages inspected. The Grail box gives the EMA pullback/trigger/protective-swing sequence. The explanation describes a momentum move, retracement, and a test of the recent extreme. Its examples are daily US equities, not BingX crypto30m. No source-exact regime-veto expiry policy or audited crypto costs/performance is given. The publication expressly does not maintain track records. Favorable probability statements remain AUTHOR_PERFORMANCE_CLAIM, not ZEL evidence.
2. Adam H. Grimes, The nested pullback, November 7, 2014: https://www.adamhgrimes.com/nested-pullback/ . Complete article text read; its diagrams were not analyzed for quantitative rules. A smaller pause during continuation can offer another entry after the original pullback was missed. This warns against treating every missed setup as permanently untradeable. The article does not prescribe our 20-bar reference, regime gating, exact entry, or costs. No audited performance is imported; no video viewing is claimed.

## CODE_OBSERVATION

The unchanged native module already computes hi20 = high.shift(1).rolling(20).max() and lo20 = low.shift(1).rolling(20).min(), and uses these prior-bar extremes in episode re-arming. The reference at the actual native EMA20 touch is available then and can be frozen without looking for a future pivot. Original C observation has 126/126 actual origins. DIAGNOSTIC.json examines all126 saved paths; labels of the missed winners and avoided losses are analysis-only. A retained setup may already have completed its original retest while regime eligibility was absent. That differs from a still-uncompleted setup temporarily rejected by the regime classifier.

## INTERNAL_HYPOTHESIS — sole rule frozen before candidate economics

At each ORIGINAL native EMA20 touch, freeze its existing prior20 high for a long or prior20 low for a short. This is an INTERNAL mechanical proxy for the recent swing, not a claim that every 20-bar extreme is Raschke's discretionary swing.

Track whether that frozen price has been touched by a completed candle since the touch, and whether a completed native turn has received a KNOWN regime veto. Until both facts exist, retain the incumbent's untraded state; known veto alone no longer discards it. Once both facts are available, expire the untraded state and require the original native fresh EMA20 touch plus turn. A wick reaching the objective is sufficient because the question is whether the proposed price objective was already traded; cancellation occurs only after the candle is complete. Same-bar objective completion precedes close-time admission, not a fictional intrabar fill.

No prior known veto => no new objective filter. UNKNOWN regime alone => no expiry. Native weak/side/segment reset clears the tracked objective. Already accepted positions are not affected. A new touch freezes a new reference, never a rolling replacement of the old objective. Initial stop geometry, entry formula, fill/gap priority, partial profit, runner, five-bar scratch, conditional holding extension, latest structural exit, fees and carry model remain unchanged.

This is one qualitative change from immediate-veto C114: condition the lifetime reset on objective completion. It does not restore winners by key/symbol/date, use final PnL/MFE, add an arbitrary age/risk-ATR cutoff, or change the 20-bar lookback. It is developmental reasoning on already-used observations, not out-of-sample discovery.

## Falsification and measurement

A strong continuation may remain profitable after its initial objective, so expiry can still discard large wins. Conversely, an unfinished objective does not prove future profitability. Full chronology must include every changed/replaced opportunity, stop-reference changes, occupancy, unresolved positions, costs1x/2x and recovery winners. Compare the new candidate against BOTH saved126 (profit control) and saved114 (risk-reduction control), including retained/restored former winners, original worst8, global longest streak, worst streak monetary sum, and cohort-net realized DD. Never compute candidate profit by deleting historical losers. No blanket promotion from a used245-day result; account NAV/MTM, historical actual funding and untouched OOS remain unverified.

Prepared code and diagnostics are not ACTUAL_ECONOMIC_RESULT. Only a completed hashed SUMMARY/ROWS and independent saved-row audit establish the new comparison result.
