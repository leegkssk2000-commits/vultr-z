# Existing portfolio integration audit

Read-only inspection at repository ref `3f4a798f15fbb3a21f3f6063db1b063b95d182e0`.
No strategy, ledger, runtime, workflow or portfolio engine was changed or run.

## Reuse decision

The inspected existing portfolio-related modules do not implement the requested
UTC/Berlin complete-calendar coverage, same-signal alias deduplication,
strategy-day-symbol matrix, holding-overlap detail and saved-ledger candidate
contribution report as a single reusable function. A small Work-D-local reporter
is appropriate. Existing semantics can be retained, but using the old allocation
engine as if it were a two-strategy shared-account simulator would be incorrect.

### Existing causal allocation entry point

`backend/research/rebuild/scalp7_portfolio_v2.py`
Git blob: `8a4613dca047c95dd42645a33f47c8c8d7fffe7f`.

```python
route(
    trades: Sequence[Mapping[str, Any]],
    primary_ids: Mapping[str, str],  # lane -> frozen identity
    start: int,                     # UTC epoch milliseconds, inclusive
    end: int,                       # UTC epoch milliseconds, exclusive
    *,
    mode: str = "adaptive",          # only equal7 or adaptive
    source_gap_events: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]
```

The function enforces exactly seven unique lane/identity pairs. Do not fill
five absent identities with placeholders to force the current K/S report through
this engine. The old preregistered seven identities include the original
Keltner parent, not the later K126 holding-extension control. Rebinding to new
identities/policies is an economic-owner decision, outside Work D.

Required candidate row:
- `identity` must match `signal.identity`, and must be in `primary_ids`.
- `signal` (or `position.signal`) includes `identity, symbol, signal_ts_ms,
  side, timeframe_min`. Only 15/30 minute signals are accepted.
- Optional `signal.meta.feature_available_ts_ms` cannot exceed signal time.
- `entry_ts_ms` (or `position.entry_ts_ms`) cannot precede signal time.
- Closed rows require `exit_ts_ms, outcome_available_ts_ms, gross_bps,
  cost_bps, net_bps`; available >= exit >= entry; finite cost > 0; net = gross - cost.
- Open/unresolved rows omit `net_bps`, preserve entry and signal, and hold
  allocated capacity through the end of the window.
- Source blocks need `{identity or lane, observed_ts_ms}`, or a row's
  `source_block_ts_ms`; an unresolved future outcome label is not an
  earlier blocking event.

The dedup key in this existing engine includes identity, symbol, signal timestamp,
side and legs. Therefore it catches repeated candidate positions within one
identity but does NOT treat identical signals under renamed strategy identities
as one independent opportunity. Work D must explicitly distinguish this.

Causal behavior worth retaining:
- Allocation occurs by signal timestamp, not future PnL.
- Same-time current valid signals share lane allocation.
- Outstanding positions reserve capital until outcome availability.
- Health updates use outcomes available strictly before the decision.
- Release is allowed at the same timestamp as availability, before next allocation.
- Same-time realized outcomes are aggregated before realized DD/loss-batch streak.
- Window starts flat and excludes carry-ins. Signals in a window whose outcomes
  occur later remain open HOLD. Original independent rolling windows must not be
  silently turned into a continuous 245-day capital simulation.

Limitations relevant to D:
- `SLEEVE_COUNT=7`, `SLEEVE_WEIGHT=1/7`, gross research capacity 1.0;
  leverage is explicitly NOT_APPLIED.
- This is allocation over frozen candidate positions, not full price-path
  generation/admission replay.
- It does not enforce same-symbol one-position or opposite-side netting
  constraints across strategies.
- It has no shared exchange account equity, actual position margin, liquidation,
  intrabar MTM, counterfactual new entries or execution venue fills.
- Its returned realized weighted trade-bps are not current account NAV.
- Its adaptive health logic is an old preregistered policy, not permission to
  introduce a new ranking score in Work D.

Exact policy and verification references:
- `research/campaigns/scalp7_20260915/SCALP7_PORTFOLIO_V2_PREREG.json`,
  blob `357c0a249ac3eefb0a38eabe86f9b08392cb99b4`.
- `tests/test_scalp7_portfolio_v2.py`,
  blob `17781d59cd3108083783200400296a733a1ccd2e`.
  Read 15 existing synthetic cases, including no future-PnL influence,
  same-time outcome health exclusion, unresolved capacity and exact window bounds.
  These tests were inspected, not newly run in D.
- `research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json`,
  blob `a2dea5c7ab50721e56d2b055a3c16424e9527f79`.
  Provides original primary identities, independent flat rolling windows,
  retained source gaps and frozen cost reference SHA
  `cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73`.
  Cost2x means the same frozen fills/admission with doubled debits, not new replay.

## Risk/account bindings

`config/zel_production_risk_sizing_v1.json`,
blob `f766aaca1df2165ad06ba601d2968b3fc0918b65`, is FROZEN_PAPER_ONLY.
It defines margin-based sizing formula
`equity_usdt * position_pct / 100 * leverage_x` and quantity as
`notional_usdt / fresh_reference_price`. Its allowed instrument set is only
BTCUSDT/ETHUSDT, not the six-symbol DEV set; this cannot be transplanted as
authorization for a six-symbol account experiment.

This risk file leaves market/account staleness and maximum daily/total DD null.
`config/zel_production_ssot_binding_v1.json`,
blob `414b7abfa7cc82c159d4d08a173c909a0f5ea264`, is HOLD_UNBOUND.
All 15 binding values/source refs/source SHAs are null, including:
- initial account equity in USDT;
- market/account/signal freshness milliseconds;
- daily and total DD percentage limits;
- risk-day timezone;
- improvement criteria and error budget.

D must not invent values, read environment secrets or activate these PAPER
bindings. Saved K/S trade-bps alone do not bind:
initial equity, per-position margin/notional/quantity/leverage, account mode,
cash updates, shared symbol admission/netting policy, mark-price path, actual
funding settlements, liquidation parameters or source-observation timestamps.
Consequently account NAV, MTM DD and actual joint incremental Net remain UNKNOWN.

`backend/portfolio_binding.py`,
blob `9fc1580a2c7fe1f9f8f0cd7dcb812b302866a386`,
is a read-only artifact binding layer for virtual asset readiness, not an
economics simulator. It expects MinData and account artifacts; importing or
calling its refresh/build functions is unnecessary for D.

Other inspected modules:
- `backend/research/zel_component_contribution_logger_v1.json` defines a
  component-event schema requiring a counterfactual for a delta claim; it is
  not daily portfolio coverage code.
- `backend/research/strategy11_portfolio_governor_v1.py` and
  `backend/research/zel_portfolio_role_engine_v1_1.py` compute research
  target weights from pre-bound material/policy/risk inputs; they are not
  entry/occupancy chronological replay. They should not be used to add an
  arbitrary score to this report.
- `backend/research/rebuild/orthogonal_portfolio_status_v13.json` is an
  older diagnostic over an approximately 172-day signal span, not the pinned
  245-day K126/S25 comparison. Its metrics cannot replace this report.

## Owner handoff boundary

Work D can emit exact pinned ledger descriptors, normalized timestamps,
deduplicated entry/opportunity lineage, all-day coverage, conflict pairs,
outcome-available realized batches and unconstrained saved-ledger sums.

The economic owner needs to bind a prospective joint policy, complete intended
signals and open positions, original reset/source-gap boundaries, all cost
components and actual capital/MTM inputs before computing accepted joint
frequency or joint incremental Net. Rejected/blocked trades may change future
opportunity state; deleting overlapping completed rows cannot recover that
counterfactual. No owner run is started by this audit.

