# PR1264 saved group → lot diagnostic

PR1262 CAPREUSE is the development parent. This saved-only diagnostic does not gate the authorized LOTLOCK candidate.

| Window | Group triggers | Actual risk exits | Own breached exits | Other-lot collateral exits | Collateral normalized qty | Collateral net change vs saved continuation (bps) | Full-size root qty changes |
|---|---:|---:|---:|---:|---:|---:|---:|
| DEV2025 | 26 | 24 | 22 | 2 | 1.000000000 | 365.492026 | 9 |
| SEEN2026 | 6 | 5 | 5 | 0 | 0.000000000 | 0.000000 | 1 |

Own thresholds use only each lot’s positive actual partial net, its own completed-close marked net and its own peak since actual partial. Equal-time next-open fills are excluded. Source exits already due at the next open keep priority.

The source-continuation intermediate values immutable saved unit source legs at the group run’s actual allocations. It does not rerun admissions and is not an executable counterfactual. Positive collateral net change means the forced cut happened to improve saved terminal PnL; it remains a collateral intervention.

| Window | Own-threshold exit DD effect | Collateral exit DD effect | Quantity/reentry DD effect | New/excluded DD effect | Peak-window relocation | Own max DD change | Residual |
|---|---:|---:|---:|---:|---:|---:|---:|
| DEV2025 | -1456.566870 | -0.000000 | 666.089208 | -0.000000 | 0.000000 | -790.477662 | 0.000000000 |
| SEEN2026 | -40.540851 | -0.000000 | 262.622733 | -0.000000 | -392.305066 | -170.223184 | 0.000000000 |

DD effects above use the same group peak→trough calendar on both ledgers. Negative means a lower loss in that matched window. The parent window relocation term separately reconciles the difference between each run’s own maximum DD. These are observed saved-accounting allocations; they do not establish isolated causal portfolio returns.

Full trigger details, source-priority cases, lot cash/peak witnesses, collateral PnL, quantity/reentry changes, terminal money bridges and DD residuals are in PRE_DIAGNOSTIC.json. Parent strategy replays and economic evaluations: 0.
