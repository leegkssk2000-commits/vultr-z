# A Keltner completed comparison — exact result readback, 2026-10-21

Classification: ACTUAL_ECONOMIC_RESULT plus read-only independent saved-trade recalculation. This readback did not initiate a workflow or replay prices.

## Authoritative execution and artifact

- Economic owner remains CLOUD_WORK_COORDINATOR_ISSUE1358_V1.
- Run 39522258946, number 441, attempt 3; event workflow_dispatch; head d55eeda13a17600e4b49ce7b15d38192d2ec467b.
- Job 119092365604 completed success. Actual run started 2026-10-21T07:19:01Z and completed 2026-10-21T07:23:26Z (09:23:26 Europe/Berlin).
- Exact run: https://github.com/leegkssk2000-commits/vultr-z/actions/runs/39522258946
- Artifact 12327593998, kp-access-diagnosis-39522258946-3, 52070 bytes; expiry 2026-10-28T07:23:22Z.
- Archive SHA256: 2e9e4de8cbe9c42e9c2c206024a66bc34708dcaa08ac6b820397e1e98db9378f.
- Result member: KELTNER_FRESH_TOUCH_SUCCESSOR_RESULT.json.
- Result raw SHA256: d62a9513996c8b2d0e648803ff8e498e31bb029faaa6008c125eee68dc8b85a1.
- Internal result receipt SHA256: 4017a6a30628df0de444bcfd3b65a622e765e595f836976729d6c3d868c03ae4.
- Source inventory SHA256: 53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2.
- Successor identity: scalp7_keltner_hg_fresh_touch_after_reject_utc30m_v1.
- New native candidate comparisons in this source run: 1. Saved rejected child replayed: false.

## Economic comparison

Same 245-day used-DEV window, six symbols, 30-minute bars. Net and DD units below are summed equal-notional trade-bps, NOT account percentage returns. DD is realized equity drawdown with simultaneous outcome cohorts netted together. No account NAV/mark-to-market curve is bound.

| Metric | Original parent | Previously rejected child | Fresh-touch successor |
|---|---:|---:|---:|
| Completed trades | 109 | 146 | 128 |
| Entries per calendar day, reported completed-trade ledger | 0.4448979592 | 0.5959183673 | 0.5224489796 |
| Net, modeled cost 1x, trade-bps | 5947.63112739 | 6660.37156742 | 6362.61741759 |
| Net, modeled cost 2x, trade-bps | 4308.31718760 | 4471.68505712 | 4444.26362135 |
| WR, cost 1x, percent | 59.63302752 | 52.73972603 | 54.6875 |
| PF, cost 1x | 2.00308107 | 1.71319066 | 1.78953378 |
| PF, cost 2x | 1.62373718 | 1.41824434 | 1.48075423 |
| Max consecutive losses, cost 1x | 5 | 8 | 8 |
| Max consecutive losses, cost 2x | 11 | 14 | 13 |
| Realized DD, cost 1x, trade-bps | 1609.46608839 | 2267.56743306 | 1838.64200493 |
| Realized DD, cost 2x, trade-bps | 2019.03343844 | 2729.32563395 | 2059.60759415 |
| Days with no recorded entry out of 245 | 207 | 196 | 198 |
| Max consecutive wins, cost 1x | 10 | 11 | 9 |

## Verified differences and limitations

Successor versus original: Net1x +414.98629020 trade-bps; Net2x +135.94643375 trade-bps. However maximum losing streak and DD remain worse than original at both cost levels. Successor versus rejected child: DD1x is 18.91566363 percent lower and DD2x is 24.53785768 percent lower; total Net1x and Net2x are slightly lower than that rejected child.

Original-to-successor matching in the source receipt: common 105 trades, added 23, removed 4. The 23 added trades sum +273.03495758 trade-bps at cost1x but -66.48054763 trade-bps at cost2x. Largest original winner retained=true; original positive-trade profit retention at cost1x=0.9856564884693838. The low frequency remains below the user's daily opportunity objective.

Readback assessment, NOT a mutation of the formal owner disposition: PARTIAL_RISK_REPAIR_VS_REJECTED_NOT_PARENT_DOMINANCE. This is not a comprehensive original-parent improvement or live profitability qualification. The source receipt states promotion=false, survivor_count_delta=0, fresh_or_oos=false, used_dev_only=true, account_nav_or_mtm=null, order/live/paper/deploy blocked.

## Independent saved-trade audit actually performed

The downloaded ZIP matches GitHub's artifact digest. Its exact result member matches the extracted raw result. Removing receipt_sha256, canonical JSON with sorted keys, compact separators and a final newline reproduces the internal receipt hash.

All 128 successor trade rows were independently re-aggregated at cost1x and cost2x: Gross, Cost, Net, WR, PF, realized cohort-netted DD and maximum losing streak match the result. Streak ordering is outcome_available_ts_ms, exit_ts_ms, symbol, identity, signal_ts_ms; zero net ends a streak. Parent and rejected metrics were read from the same source result, not independently re-simulated here. No new price replay or market-data API was used.

## Continuation / duplicate protection

Do not re-dispatch K or rerun #441 to obtain this result again. Attempts 1/2 cancellation history remains preserved, but is no longer the current execution status. The existing owner must reconcile the actual consumed K comparison with its ledger before any next economic run; this readback does not directly mutate OWNER/CHECKPOINT or consumption.

Next approved target is existing Squeeze signal-low source-trigger scan on the saved 57T source comparison. Only a complete source path with an actual earlier trigger can justify at most its remaining approved FULL; missing source is UNKNOWN, not zero. No new S execution was initiated in this readback. No B observer or original strategy was modified.

The user supplied a TOKEN_SAVED screenshot. Token authentication was NOT verified here: remote command requests were blocked by the platform safety check, including a separate public read-only request. No secret was exported; no workaround was used. The completed attempt 3 is not attributed to this new token or this readback.
