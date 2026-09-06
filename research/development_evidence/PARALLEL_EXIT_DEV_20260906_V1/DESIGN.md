# Two bounded exit development hypotheses after PR1195

Q0 keeps the original prepared daily breakout signal and initial channel protective stop. The entry UP channel upper is immutable; loss of that upper at a held completed4h close queues nextopen exit. Original gap SL and original confirmed bearish exit take precedence; an intrabar protective fill prevents later close trigger. No B allocation, Q1 stop raise, common breakeven condition, extra entry filter or changing channel is added.

Keltner uses the original V2 EMA20 reclaim + EMA20>EMA50 parent and its original DSL calculation (truncated4N EMA history seed), index239 minimum and12bar horizon. A held close with EMA20<=EMA50 queues nextopen exit before the existing maxhold. Existing timeout has priority. There is no separately specified SL in this original research model. Strict original end-completion exclusion remains an explicitly marked, unfinished tail; it is not silently dropped or forced closed.

Both hypotheses apply to all eligible gains/losses using only observations available then. Future path, MFE/MAE and final winner labels are reporting targets only. Original signal pools are preserved. Fixed admitted-entry comparison and full chronological ownership are separate; Q0 allows signal on the exit bar after open exit, while Keltner preserves its original signal_index<=exit_index exclusion. Tail orders cannot access a bar opening at or after the end.

## Input and provenance

All seven original frozen symbols. Q0 original2025 interval2025-01-29T00Z to2025-12-29T00Z; Keltner native interval2024-12-19T08Z to2025-12-29T08Z. Both seen2026 intervals2026-05-08T00Z to2026-09-05T00Z, freshflat with earlier prefix for causal features only. Original lane calendars are not asserted identical. Canonical input identity and cost binding use PR1194 bounded reader:3748decoded4h rows per symbol, none afterSep5T00Z. Original2025 calculations receive only2250row prefix (Q0 trims to UTCdaily end). Existing original validation/purged_OOS partition labels in this alreadyseen prefix are explicitly reported, not disguised as new independent evidence.

Original fee/spread/impact/slippage/funding with20bpsfloor unchanged; elapsed funding recalculated at actual modeled exit/mark, cost2 doubles wholecost. No actual signedfunding or production execution lineage. Equal nominal trade-bps, not accountreturn, accountMDD or equal account risk. Open valuations hypothetically reserve full roundtrip modeled cost, with entry-side cost not separately bound. UTCdaily marks include exact native partial edges. All samecalendar loss/DD windows have position contributions, overlappingwindows cannot be added. Block30days1000seed1178 uncertainty is descriptive reuseddata, not independent sample proof.

## Preregistered development decision

Minimum6completed trades; positive closed net/E,PF>1,payoff>=1,cost2positive. Direct and full closed plus marked increments must both bepositive. IMPROVED additionally needs nonworse groupedlossrun and daily markedDD,90% capped parent topdecile winner amount (inherited Q1 development comparison prior), positive paired daily95lower and no unresolved positions. Positive economics/increment with risk,retention or uncertainty miss is TRADEOFF; failed absolute/increment is REJECT; insufficient/undefined sample is INSUFFICIENT. Relative lossreduction is separately disclosed even if REJECT. These are frozen research comparison criteria; formal SSOT remains unchanged. No numerical retuning after results.

## Narrow duplicate check and allocation

Latest master afterPR1195 contained telemetry updates only; latest ten PRs ended1195. ExactnewIDs absent. Prior1184 commoncost-coverlost BE,1185 EMA-at-BE group attribution,1187 entryEMA removal and1191 Q1 protective stop raise are different rules and remain immutable. No old economic run is repeated by the new-only CI route; opaque byte checks and synthetic guards preserve them.

Previous26candidate history retained. Ordinal27=Q0 entrychannel exit,28=Keltner trendinvalidation exit. Each has2explicitlyapproved periodapplications and fixed/full reporting views. Total2candidates,4candidate-period evaluations,8comparison views; noextra control strategy or budgetreset. Priorseen1/1 and independent0/1 NOT_RUN preserved. Reproduction is not newallocation. Newchildresult had not been calculated when this code/spec was frozen.

## Protected operation

PR1195 observer remains separate. Its code/spec/design/schedule hashes are checked; no bootstrap/warmup/archive/cursor or future price is loaded as development input. Collector telemetry can advance independently. Q0/B olddecisions, Top5,MA001/STAPC001, BreakvalidationREJECT and G5B remain preserved. No automatic research-parent or operating replacement, G6formalcredit, liveorders/account sizing, externalpaidAI or deployment. A later childvalidation requires ownfrozenrule/boundary and authorization; currentQ0futureobservations cannot be retroactively assigned independent childcredit.
