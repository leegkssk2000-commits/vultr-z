# Baseline comparability and finite component experiment

Scope: retained Scalp7, 15m/30m only. This first source-based comparison stays at the existing 30m Squeeze timeframe to avoid adding a timeframe/execution confound. No legacy 1h result is admitted.

| Field | Earlier Chat receipt | PR1338 current parent |
|---|---|---|
| Signal source | `a1_strategy_regime_alpha_matrix_v1.py` selects Squeeze `NATIVE` | `scalp7_positive_lanes_v2.py` SQUEEZE_PARENT uses cost4 |
| Entry cost filter | NATIVE has no ATR/cost threshold | ATR20 / next-open price / reference cost >=4 |
| Candle clock | old offset aggregation | complete UTC buckets |
| Entry price access | old source checks next open | signal first; next-open admission owns price/cost check |
| Close-driven exit | old close-price diagnostic | next open after completed decision |
| Occupancy | legacy standalone replay/selection | common causal per-symbol owner |
| Regime fit and period | inspected short history | prior90-day fit, validation30 + rolling245 days |

These simultaneous differences are not an isolated estimate of overfitting or the cost-filter effect. No numerical share of the old/new change is attributed without a matched bridge. Current-parent economics are evidence for their disclosed identity, not retrospectively identical to NATIVE.

Current cached control: `scalp7_squeeze_panic_cost4_parent_utc30m_v2`, PR1338. Reuse immutable raw trades, costs, window boundaries, source loader, context and execution hashes. Do not rerun completed parent economics.

New comparisons: P+A, P+B, P+A+B. A is a disclosed Brooks-inspired second-signal supplement after an existing squeeze fire. B is a disclosed Carter initial-thrust failure exit. All use 30m complete bars and the same existing execution engine. No new data source, relaxed threshold, symbol filtering, or live authority.

A leaves original signal generation intact but cannot promise original fills when a supplementary position occupies the same symbol. Lost original opportunities and winner-profit retention are explicitly reported. B can free occupancy; later setups must already be causally valid.

Work's five observed source/forward/paper processes are not altered. This Chat owns only the three finite new identities. All results are historical diagnostics, not genuine fresh or a new B/material/Core grade. No fixed profit threshold is invented.
