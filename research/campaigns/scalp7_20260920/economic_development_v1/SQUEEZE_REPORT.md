# G4 selected-batch saved economic comparison

All PnL and DD values below are summed equal-original-notional trade bps, not account returns. Validation and rolling are separate already-inspected development history. Fresh T=0; formal promotion, fusion, orders and LIVE remain BLOCKED. This batch does not complete G4.

## SQUEEZE

Matched completed30m Squeeze context with first-fire versus second-upward-attempt 15m entry.

Parent: scalp7_squeeze_30m_context_15m_exec_control_v1 (freeze 4484fea34f14c15577c59c71b228afb6158a1332d1a89ffd8dd6492e48a005e6). Child: scalp7_squeeze_30m_context_15m_high2_replacement_v1 (freeze 83812c0fc507cde6cb8eb8d56d64dba0a229261c484297ef83a3b105e2480fd9).

### rolling

| Side | T | T/day | WR % | Gross | Net 1x | Net/T | PF | DD | MaxLS | Net 2x |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 25 | 0.10 | 48.00 | 1892.29 | 1520.49 | 60.82 | 1.912 | 576.67 | 3 | 1148.69 |
| child | 13 | 0.05 | 46.15 | 423.31 | 230.43 | 17.73 | 1.465 | 171.06 | 3 | 37.56 |

| Side | ES5 all trades | Hold median/p95 min | Positive/all windows | Month/symbol/session positive-profit concentration | Largest winner share | Unresolved |
|---|---:|---:|---:|---|---:|---:|
| parent | -288.34 | 300.00/330.00 | 3/9 | 0.5856/0.2574/0.5531 | 0.1951 | 0 |
| child | -131.03 | 120.00/231.00 | 3/9 | 0.3911/0.4824/0.8425 | 0.3762 | 0 |

Exact-event common/missed/added: 0/25/13; total Net delta -1290.06 = common 0.00 + removed-parent contribution -1520.49 + added-child 230.43.
Exact-event capped parent-winner profit retained 0.0000; winner-group delta -3187.21; parent-loser observed loss saved 1666.72.
Explicit same-opportunity matches 13, signal-time shifts 13, entry-time shifts 13; unmatched completed known origins P/C 12/0; ambiguous groups 0; missing origins {"child": 0, "parent": 0}.
Full-stream causal-origin signal classifications touching this partition: {"PARENT_ONLY_SAVED_SIGNAL_ORIGIN": 17, "SAME_ORIGIN_SIGNAL_TIME_SHIFT": 18}. Unmatched completed-fill evidence P: {"NO_OPPOSITE_SAVED_SIGNAL_ORIGIN": 12}; C: {}.
Same-opportunity capped parent-winner profit retained 0.2106; winner-group delta -2713.39; parent-loser observed loss saved 1423.33.
Net delta excluding largest child winner -1563.14. Strict descriptive improvements T/WR/Net/DD: {"DD": true, "Net": false, "T": false, "WR": false}; this is not a promotion gate.
Saved opportunity status P: {"COMPLETED_INCLUDED": 25, "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER": 10}; C: {"COMPLETED_INCLUDED": 13, "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER": 5}.

### validation

| Side | T | T/day | WR % | Gross | Net 1x | Net/T | PF | DD | MaxLS | Net 2x |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 1 | 0.03 | 0.00 | 2.62 | -12.62 | -12.62 | 0.000 | 12.62 | 1 | -27.87 |
| child | 0 | 0.00 | N/A | 0.00 | 0.00 | N/A | N/A | 0.00 | 0 | 0.00 |

| Side | ES5 all trades | Hold median/p95 min | Positive/all windows | Month/symbol/session positive-profit concentration | Largest winner share | Unresolved |
|---|---:|---:|---:|---|---:|---:|
| parent | -12.62 | 270.00/270.00 | 0/1 | N/A/N/A/N/A | N/A | 0 |
| child | N/A | N/A/N/A | 0/1 | N/A/N/A/N/A | N/A | 0 |

Exact-event common/missed/added: 0/1/0; total Net delta 12.62 = common 0.00 + removed-parent contribution 12.62 + added-child 0.00.
Exact-event capped parent-winner profit retained N/A; winner-group delta 0.00; parent-loser observed loss saved 12.62.
Explicit same-opportunity matches 0, signal-time shifts 0, entry-time shifts 0; unmatched completed known origins P/C 1/0; ambiguous groups 0; missing origins {"child": 0, "parent": 0}.
Full-stream causal-origin signal classifications touching this partition: {"PARENT_ONLY_SAVED_SIGNAL_ORIGIN": 2}. Unmatched completed-fill evidence P: {"NO_OPPOSITE_SAVED_SIGNAL_ORIGIN": 1}; C: {}.
Same-opportunity capped parent-winner profit retained N/A; winner-group delta 0.00; parent-loser observed loss saved 12.62.
Net delta excluding largest child winner 12.62. Strict descriptive improvements T/WR/Net/DD: {"DD": true, "Net": true, "T": false, "WR": false}; this is not a promotion gate.
Saved opportunity status P: {"COMPLETED_INCLUDED": 1, "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER": 1}; C: {}.

## Evidence limits

The JSON includes cost1x/cost2x full metrics, window outcomes, month/symbol/session distributions, exact event attribution, causal-origin time shifts, occupancy blockers, observed successor entries and unresolved positions. Cost2x uses the identical saved fills with twice the frozen cost; it is not a new replay.
An exact-time event match need not mean the same setup. A missing exact event may be a time shift of the same causal origin. Origins match only when the metadata provides one unique completed trade on both sides; missing/ambiguous origins stay unpaired. Unmatched contributions reconcile observed ledgers and do not impute hypothetical fills or profits. Capped winner retention treats unpaired observed contribution as zero, not proof that an unresolved opportunity finally loses.
Successor timing and occupancy witnesses are descriptive. No MFE, recovery, rejected signal or unfilled opportunity is converted into realizable profit. Closed outcomes at/after a window end are excluded, and unresolved ownership remains explicit. No fresh boundary, service, live authority or promotion changed.
