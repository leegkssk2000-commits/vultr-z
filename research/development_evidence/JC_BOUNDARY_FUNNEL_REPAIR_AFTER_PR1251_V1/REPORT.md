# JC boundary and funnel repair — Issue1252

**NO_SETUP_AFTER_BOUNDED_REPAIR.** Boundary context repaired; extra wait unchanged because wait-only witness count is zero. Both first FULLs are NOT_RUN; no candidate/evaluation numbers or reservations assigned. Historical 79/142 retained. This is a signal preflight result, not a new zero-trade economic backtest.

## History eligibility and daily decisions

Calendar days with sufficient history differ from days after the first eligible fresh daily decision. Six symbols retain sufficient pre-start history, but the boundary candle is first available only at 2024-12-20 00:00 UTC. No claim of fully validated 375-day trading. HYPE has no verified listing origin or invented warmup. The SEEN2026 504-day pre-start prefix is unchanged. Decision counts include a signal exactly at the terminal boundary (pending, no next open).

|Period|Symbol|Old history days|New history days|First eligible daily decision UTC|Days after first decision|
|---|---|---:|---:|---|---:|
|DEV2025|1000PEPE-USDT|9.3333|375.0000|2024-12-20 00:00|374.3333|
|DEV2025|BCH-USDT|9.3333|375.0000|2024-12-20 00:00|374.3333|
|DEV2025|BTC-USDT|9.3333|375.0000|2024-12-20 00:00|374.3333|
|DEV2025|ETH-USDT|9.3333|375.0000|2024-12-20 00:00|374.3333|
|DEV2025|HYPE-USDT|9.3333|10.3333|2025-12-19 00:00|10.3333|
|DEV2025|LINK-USDT|9.3333|375.0000|2024-12-20 00:00|374.3333|
|DEV2025|SOL-USDT|9.3333|375.0000|2024-12-20 00:00|374.3333|
|SEEN2026|1000PEPE-USDT|120.0000|120.0000|2026-05-08 00:00|120.0000|
|SEEN2026|BCH-USDT|120.0000|120.0000|2026-05-08 00:00|120.0000|
|SEEN2026|BTC-USDT|120.0000|120.0000|2026-05-08 00:00|120.0000|
|SEEN2026|ETH-USDT|120.0000|120.0000|2026-05-08 00:00|120.0000|
|SEEN2026|HYPE-USDT|120.0000|120.0000|2026-05-08 00:00|120.0000|
|SEEN2026|LINK-USDT|120.0000|120.0000|2026-05-08 00:00|120.0000|
|SEEN2026|SOL-USDT|120.0000|120.0000|2026-05-08 00:00|120.0000|

## Cumulative gate passes

Order-dependent cumulative counts; independent evaluability/pass counts and first-failure counts are saved separately. A later zero does not establish that condition as an independent cause.

|Condition|DEV original|DEV repaired context|SEEN original|SEEN repaired context|
|---|---:|---:|---:|---:|
|history365|70|2261|847|847|
|recent_high20|0|219|61|61|
|squeeze3|0|5|0|0|
|EMA21|0|0|0|0|
|ATR21|0|0|0|0|
|HLHL_pivots|0|0|0|0|
|cup_geometry|0|0|0|0|
|extra_confirmation_wait|0|0|0|0|
|target_geometry|0|0|0|0|
|below_first_target|0|0|0|0|

DEV connected context: 364 first fail history; 2,042 recent high; 214 squeeze; 5 EMA21. SEEN: 786 recent high; 61 squeeze. No complete setup in either context and no wait-only witness.

|DEV blocker|Available UTC|Close|EMA21|
|---|---|---:|---:|
|BCH-USDT|2025-09-23 00:00|566.68000000|590.66882035|
|BCH-USDT|2025-09-24 00:00|556.38000000|587.55165487|
|BTC-USDT|2025-02-04 00:00|101315.40000000|101318.01594494|
|BTC-USDT|2025-02-05 00:00|97725.30000000|100991.40540449|
|BTC-USDT|2025-08-01 00:00|115694.50000000|116680.67862255|

The source does not mandate two additional days after the handle becomes confirmed. The approval requires a wait-only witness to remove that delay; none exists. Radius2, squeeze3, high365/recent20, geometry, EMA/ATR, no-chase, allocations, stops, targets, 72-hour management and runner are unchanged.

## Economic reference — saved results only

Fixed reference-notional trade-bps; terminal values include hypothetical open liquidation costs. These are not account returns or live performance. No repaired-result PnL, avoided losses, missed wins or drawdown is imputed from signal zero.

|Period|Rule|Closed/open|WR %|Avg win|Avg loss|Payoff|PF|Terminal net|Cost2|Daily DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|C63_SAVED|98/4|37.76|784.35|-395.24|1.98|1.20|4638.62|2301.59|7864.04|
|DEV2025|JC79_SAVED|0/0|—|—|—|—|—|0.00|0.00|0.00|
|DEV2025|JC_REPAIRED NOT_RUN|—|—|—|—|—|—|—|—|—|
|SEEN2026|C63_SAVED|24/5|50.00|1473.26|-273.53|5.39|5.39|12283.75|11581.93|3642.33|
|SEEN2026|JC79_SAVED|0/0|—|—|—|—|—|0.00|0.00|0.00|
|SEEN2026|JC_REPAIRED NOT_RUN|—|—|—|—|—|—|—|—|—|

Repaired risk/attribution (loss tail, streak, exposure, winner coverage, new/excluded/open transitions, partial exits and trailing): NOT_RUN, not zero. JC79 REJECT_KEEP_C63 is preserved. The original source is an options workflow; this remains a disclosed crypto adaptation.

## Evidence and closure

All seven raw boundary rows pass exact decimal close and high/low/volume containment. Missing initial 4-hour bars, original day open and prefix quantities remain unverified. No new market GET, OOS, paid AI, baseline replay, FIXED, sweep, order or deployment. Native setup boolean parity was checked for every saved diagnostic observation; final verification recounts saved flags only.

Source mapping: SOURCE_MAPPING.md. Independent gate counts: DIAGNOSTIC_SUMMARY.json. Full observations: DEV2025/ and SEEN2026/GATE_OBSERVATIONS.json.gz. Original history hashes: PRESERVATION.json. Closure CI/review/merge identifiers are recorded on the PR and Issue1252.
