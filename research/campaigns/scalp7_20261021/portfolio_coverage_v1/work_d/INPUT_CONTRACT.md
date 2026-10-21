# Owner-generated saved-ledger input

`INPUT_MANIFEST.json` is the executable K126/S25 example. Do not edit those source ledgers.
For a candidate, create a new manifest with `baseline_labels: ["K", "S"]` and append
its source to `sources`. No candidate placeholder produces forecast profit or entries.

Required source bindings: unique `label`; exact `identity` and `identity_field`;
immutable 40-hex `ref`; local repository-relative `path`; raw file `sha256`;
JSON `array`; `partition`; `row_semantics: one_position_lifecycle`; `cost` metadata
as in the example. Supply `evaluated_window_utc` equal to the comparison window;
do not present a shorter candidate evaluation as full-window coverage. Supply the
full symbol universe in manifest `symbols`, including symbols with zero entries.

The JSON/gzip file contains lifecycle rows in the named array plus optional
`unresolved` rows. Unresolved data must use the same normalized schema; nested
engine-native unresolved positions require an explicit owner export. The reporter
fails on missing partitions instead of silently dropping positions. Validation
rows are excluded from a rolling comparison, with counts disclosed.

Each lifecycle row provides `identity`, `partition`, `symbol`, `side` (+1/-1),
`signal_ts_ms`, `entry_ts_ms`, `exit_ts_ms`, `outcome_available_ts_ms`,
`gross_bps`, `cost_bps`, optional parity-checked `net_bps`, optional `regime`.
Times are integer epoch milliseconds (timezone-aware ISO values are also accepted
for normalized top-level timestamps). The current native nested signal remains
integer milliseconds. `signal <= entry <= exit <= outcome_available` must hold.
Open positions have null exit/outcome; pending signals have null entry/exit/outcome.
Missing economic values yield UNKNOWN totals, never invented zeros for entered positions.

Nested signal fields, when present, must match symbol/side/signal time/timeframe
and identity; feature availability cannot be after the signal. For K126 only,
`management_comparison_identity` identifies the child while `lineage_identity`
pins the inherited raw and nested signal identity. A pinned execution profile
must match the row exactly.

Export one authoritative whole-position lifecycle including all its realized
cashflows. Partial fills/exits, DCA and handoff rows must use `event_type`
(`partial_fill`, `partial_exit`, `dca`, `handoff`) and `parent_position_id` linking
to a lifecycle `position_id`; they add neither entries nor additional PnL.
Orphan events and conflicting duplicate lifecycle rows fail. Do not provide
successive lifecycle snapshots or aggregated plus per-leg profit as separate positions.

`opportunity_id` is optional, but only a nonempty stable source ID shared across
renamed strategies/legs can certify the number of independent observed opportunities.
Absent IDs leave independent counts UNKNOWN; symbol/side/time clusters are proxies.
Even complete IDs in an admitted-trade export do not establish the complete raw
intended/rejected opportunity stream. Supply that limitation honestly.

The reporter reads and SHA-checks each ledger, frozen cost source and optional
`cost.additional_reserve_source`. Fetch the exact pinned source files into the
local repository layout before calling it. This code has no download/API path.
Cost unit is `equal_notional_trade_bps`; formula is
`gross_bps - multiplier * cost_bps`. Already included funding reserves must not
be charged twice. 1x/2x are scenarios over unchanged rows, not actual funding history.

Output includes standalone coverage/economics, `candidate_contribution` against
all baseline labels, and every pairwise contribution. `raw_additive_economics`
is separate from `nonoverlap_saved_entries_economics`; both are descriptive.
`shared_incremental_net1x_trade_bps`, account NAV and MTM DD stay null.
No priority allocation, future-PnL selection, ranking weights or portfolio PASS is run.
