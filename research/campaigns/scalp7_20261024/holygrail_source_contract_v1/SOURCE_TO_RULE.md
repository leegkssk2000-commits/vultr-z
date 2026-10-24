# HGL1: source-to-rule contract for existing Work D

Status: SOURCE_RULE_READY; one candidate; market DATA_BINDING_BLOCKED. This packet contains no market economic result. It does not establish a new profitable strategy.

## Primary evidence and interpretation boundary

Read first: Issue1358 latest comment6382002269; source matrix commit bfd137feb68474a1a4d9abe26ae79254e975a7a4. Existing D head ab71035013e226bdc9409a5f36f2f22c7cde3320 is preserved. Freeze e1d0036f9807b231133eb2f012b603d0ff3049bb precedes any HGL1 market outcome.

S1: [original author-hosted August1997 interview](https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf), printed p2 boxed rules, p3 rationale, p4 failure example. Initially ADX14 exceeds30 and rises; then price returns to EMA20. ADX may decline during that return. The trigger is above the preceding bar high. Initial protection uses the new swing low; subsequent trailing is discretionary. Recent-high retest is the proposed tendency, not a guarantee. The Eaton example demonstrates stalled/failed follow-through. The old /2013/11 URL is 404; the same author domain hosts the replacement.

S2: [original author-hosted March2004 interview](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf), printed pp78-79. It describes the first EMA20 retracement following strong ADX and an exit toward new highs; the setup applies on its own bar interval. Printed p77 explicitly distinguishes tested tendencies from complete mechanical trading systems.

The primary setup is reconstructible. A complete reproduction of the author's discretionary management is not: exact swing/trailing/rearm algorithms are unspecified. HGL1 therefore freezes one transparent ZEL translation of the documented setup and recent-high objective. It is not labelled the author's complete algorithm. No Guppy filter is added; a second candidate is not proposed merely to fill the allowance. If exact discretionary replication is required, that claim is REJECTED, not repaired with invented author rules.

| Component | Primary rule | Frozen HGL1 ZEL choice |
|---|---|---|
| Strength | ADX14>30 and initially rising | Wilder seed in FROZEN_SPEC; strict comparisons |
| Long direction | Uptrend context | EMA20 rising, close and whole bar above EMA at arming |
| Pullback | First EMA20 retracement; ADX can fall | Evaluate completed bar low<=EMA<=high; fully below invalidates |
| Trigger | Above previous-bar high | Touching bar=t, previous=t-1; buy-stop high[t-1]+one recorded tick |
| Stop | Newly formed swing low | Lowest low from most recent armed peak through touch, minus tick; fixed |
| Profit objective | Recent/new-high move; discretionary trailing elsewhere | Full exit at highest pre-touch high since arm; no invented trailing formula |
| Availability | Not specified as data protocol | Activate only at future hourly open >= observed touch availability |
| Pending order | No numeric expiry verified | One eligible execution bar; unfilled setup consumed |
| Reset | No numeric reset verified | After consumption, later ADX<=30 then new qualifying arm |
| End of sample | Not specified | Open trade censored, marked separately; never a zero-profit closed trade |

Every right-column convention is pre-outcome, not fitted to the prohibited donor ledger. ADX/EMA use only prefix data. No outcome label, future swing confirmation, right-side pivot or winning-symbol filter is allowed.

## Exact chronology and conservative fills

At touch close t, freeze levels from the then-known prefix. Never fill within t. A few seconds of observed receipt delay normally pushes eligibility beyond the immediately adjacent hourly open. Pending levels stay fixed while waiting. Only the first eligible bar may trigger; no fill expires it.

For entry: open<=stop invalidates, open>=target skips a gap beyond the objective, otherwise high>=trigger fills max(open,trigger). Any entry-bar stop touch takes precedence. If entry occurs intrabar and that bar also touches target without the stop, target is deferred and the restricted-fill bar counted. Crossing a higher target implies crossing the lower buy trigger under a continuous path; this deliberate deferral is a pessimistic ZEL approximation, not a claimed uncertainty in that level ordering. This is a declared conservative model, not proof of an actual exchange fill.

For an existing position: adverse stop gap fills at open; a favorable target gap receives only target. Inside-bar stop/target collision uses stop first. No stop widening, pyramiding, shorts or time exit. After exit there is no same-bar rearm. Real intrabar chronology and slippage remain unproved.

## Input binding and missing evidence

The consumed 2026-02-14..2026-08-30 hourly corpus has manifest SHA256 bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7. It is EXCLUDED from HGL1 DEV, not re-labelled fresh. The old 57-trade donor ledger was neither opened nor reaggregated. Its performance supplies no candidate score or acceptance threshold.

Existing B minute receipt format is technically compatible with a separate read-only hourly normalizer. The shared 15m/30m aggregate API is not modified or called with60. No B active path was opened, no writer or collector started. Work D must receive an owner-authorized immutable snapshot, then verify CURSOR -> receipt -> raw and normalized bytes. A stated hash alone does not prove market receipt authenticity or independent prior consumption.

INPUT_TEMPLATE deliberately holds unknown fields as null: new input SHA, immutable snapshot root/CURSOR/IDENTITY, independent-data attestation, pre-result input freeze, DEV bounds, actual tick metadata. No eligible raw snapshot is present in this Work. Code/selftests are executable now; market DEV is blocked until those existing-source metadata and bytes are supplied. No additional strategy research is required to implement the frozen interpretation.

Exactly60 consecutive UTC minute opens make one hour. The hour open is first, high=max, low=min, close=last; available_at=max(hour close, minute receipt times). No interpolation, sorting away disorder or dropping bad bars. Exactly240 preceding hourly bars are indicator-only. DEV starts after rule freeze; <=31 days is a cheap-screen resource bound, not a statistical significance threshold. The six-symbol universe is fixed before results.

## Costs, stop criteria and report meaning

Same completed-trade ledger yields Net1=gross−20bp and Net2=gross−40bp; these are fixed all-in scenario debits per round trip. They are neither observed fees nor complete historical funding. Funding is null, never observed zero. No actual after-cost, live, G5 or portfolio-NAV PASS follows from these scenarios.

Report completed T, distinct entry epochs/day, gross/Net1/Net2/PF/WR, exit-order trade-bps DD, loss streak, simultaneous symbol positions, largest wins/top2 dependence and censored positions. No account NAV without notionals. Zero trades or cost2<=0 closes this fixed HGL1 screen without parameter repair. Positive cost2 is only REVIEW_REQUIRED; funding, receipt integrity, concentration and independent formal admission remain outstanding. There is no parent/child winner-preservation claim because this packet supplies one independent candidate, not a modification of K117.

## Selection freeze versus final byte manifest

`input_freeze` records the chosen source, universe and calendar window BEFORE its DEV decisions. The final manifest hashes actual archived bytes AFTER capture; no claim is made that future market bytes could be hashed in advance. Rule/selection freeze and final input sealing are separate receipts. `--input-sha256` means the final manifest-file SHA256; preflight additionally returns a combined bound-input SHA256 over that manifest and its verified file inventory.
