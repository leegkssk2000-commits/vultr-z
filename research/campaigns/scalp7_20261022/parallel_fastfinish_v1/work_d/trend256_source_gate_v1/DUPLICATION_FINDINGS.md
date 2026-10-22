# D TrendRider source / duplication review

Read-only review, 2026-10-22. Read `upload/WORK_D_EXISTING(1).txt` in full, D `WORK_NEXT_TRENDRIDER.txt` at `2f26c8dab8085c2406c5fb6f51462361e0355292` (blob `d1254788ad42363a0c821fbfa28d3ee9a6aeaff4`), and relevant latest saved #566/#1388/#1358 receipts. No source edits, economic replay, market fetch, Actions, owner/consumption writes, or new agents.

## Decision

The proposed BTC/ETH categorical trend confirmation and entry-chase cooling mechanisms are **already implemented and evaluated in distinct earlier TrendRider lineages**. They cannot be presented as untried axes. The exact D256 lineage is historical and remains independently identifiable; earlier WR81.25/frozen22 results must not be relabelled as D256 economics. None of the reviewed existing mechanisms establishes a new source-backed, untried D256 child.

The actual D256 archive supplies trade identities, initial geometry and hashes, but not the underlying OHLCV prefixes or the feature values needed to decide a BTC/ETH prior-state rule. This is a concrete `SOURCE_FEATURE_BLOCKED` condition for a new source-exact filter, not evidence that the original policy source is missing. The specific missing inputs are the original 12-symbol 1h bar snapshots, complete prefix/warmup used by both native evaluation and delayed transform, exact clock/closed-bar status, and corresponding funding/fill lineage. A later rolling fetch cannot substitute for these historical inputs.

## Keep the cohorts separate

| Receipt | Identity / observation | Meaning |
|---|---|---|
| run37989679810 / artifact11646670634 / `long_only_prospective.json` | D frozen256; signed receipt `4515dfa653d0ebf25029ee6b1eb0a9a54f81c8c4f65d3fbaecc30f9efc334c70`; parent301 receipt `a657c271f2ebf209569738647c4d4c40064c8952a39e123929254029d5861b7a` | Historical diagnostic cohort. Net1/T +24.0114 and cost2 sum +1461.103 are this cohort only. |
| run37995747426 / artifact11647389180 | Liquid6 T123; signed `a98f502f1b161bff5309a22bba320fd3f8725874e9303991ac8bb5f960ac0a43` | Separate scaled stream. Existing 50:50 bundle rejected. The earlier report says106/123 same-direction interval overlap and+0.92372474 on37 days. Exact reproduction now identifies106 as the legacy interval predicate including zero-span rows; strict half-open occupancy has104/123, and the37 correlation dates are the union of exit-bar UTC dates with zero fill, not37 shared nonempty dates. See the new overlap receipt; no prior record is edited. |
| #566 comment6341787161, 2026-10-22T13:20:34Z | run39783505611; repair receipt `52031787b72c2015dc35ec42abdd5675818cc727cc8410ce8620d2b4ea51be75`; parent299, long-only260 | Later rolling repair result. Parent Net/T −8.404606; long-only +7.323552. All five child axes ready=false; next=None. |
| #566 comment6346281757, 2026-10-22T16:52:23Z | run39802697122; summary `73ebd5390565cb1280bfd37d6b2c6723f05422c32e53f95eaefef11a765f81b2`; T265 | Later long-only receipt. Fresh-labelled Net/T +0.1015319445, net sum +26.9059653, PF1.000768; H4 NO_PROVEN_EDGE/H5 HOLD, survivor_ready=false. Not a refresh of frozen256. |

#1388 comment6090838180 requested a source-backed completed prior BTC/ETH trend/volatility mechanism; it did not specify a frozen untried rule. Comment6111203884 already rejected the correlated bundle and preserved account-NAV/capital unbinding. Later actual receipts supersede stale positive-anchor status, while the D task deliberately keeps old256 as its fixed diagnostic cohort. Existing owner remains `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`; these receipts do not grant D economic execution.

## Exact frozen source and native features

Run37989679810 event head is `758fde9213032ef0211e5d8d3ffc914f6dad5ca2`. At that ref:

| Repository path | Git blob | Content SHA256 where locally established |
|---|---|---|
| `backend/research/rebuild/trend_policy_batch_v1.py` | `5212f92a0b181e523c235dc546b64ea2852045e7` | Trade receipts directly bind this policy blob. |
| `backend/research/rebuild/a1_trend_rider_delayed_fill_evaluator_v1.py` | `82821e69159b685944f41ab43231cb98b92e8ed3` | `44a682e474ca73eb2b2fa5bb1860f40a2c332c36d42eb9590aba617848df62f8` |
| `backend/research/rebuild/a1_trend_rider_long_only_exact_parent_evaluator_v1.py` | `f776611535c99a6abadc9de616f5ffdd0d06a6e4` | `eed4e08d951d8a5c0720fe2a69a5edefa6bd0b270f9614f45e75f4b3e3327648` |
| `backend/research/rebuild/a1_trend_rider_exact_parent_repair_batch_v1.py` | `7e33b17e97dcc68d636bda48e0ad808232973ddb` | `b878606b67ed1153cbb95b8a357055b2a1824e64e2652a22e7d830552957d45d` |
| `backend/research/contracts/a1_trend_rider_delayed_fill_v1.json` | `476e5f36abb6456c459f4b9ea87ee49968f3a830` | `fcc0baed713eaf24504cf30e04aa5005a9ae2bfee0433e2c3d87955b514a65c7` |
| `backend/research/contracts/a1_trend_rider_long_only_exact_parent_v1.json` | `d44b7fd17aa3298b6112f7a0217ffd23748fec5f` | `6cd82c326a57071fe5ec42b8f454d9f0ac1ddac9c18b8a9b90db9f0fc78db948` |

Checkout pin resolved: workflow `.github/workflows/a1-trend-rider-long-only-exact-parent-v1.yml` blob `dfb090f5f75a0487113bf4492e3ad9153a22a966` checks out `ref: master`, so run.head_sha alone would not establish executed bytes. The primary-source reviewer recovered existing job114020351819 `git log -1` output confirming actual checkout `758fde9213032ef0211e5d8d3ffc914f6dad5ca2`. The source table is therefore bound to executed checkout as well as the receipt's directly recorded policy blob; this potential provenance blocker is closed.

Native API is `compute_trend_rider_feature(bars, *, symbol, now_ts_ms, config=None)` followed by `build_trend_rider_intent(feature, policy_source_sha=..., verified_round_trip_cost_bps=..., config=...)`. Native one-hour config: ATR14, EMA50, Supertrend10×3, minimum64 bars, maximum stale2 intervals,48-bar timeout. Long confirmation: direction+1, close>Supertrend, close>EMA50, EMA50 rising, prior candle close>=open. Entry additionally requires ST gap/ATR>=0.10 and abs(close−EMA50)/ATR<=2.0. Native emitted values are `supertrend`, `direction`, `ema50`, `long_confirm`, `short_confirm`, `st_gap_atr`, `chase_atr`; snapshot includes close,ATR,signal_ts and feature_sha. BTC/ETH cross-symbol state is absent from this parent.

Original intent fixes SL=signal close−1.5ATR for long, no TP, partial disabled, pyramiding disabled, cooldown2 bars, one entry per transition. It declares trailing/runner metadata, but delayed-fill transform actually evaluates a fixed SL then timeout; do not infer a realized trailing or partial path from intent declarations. Native config risk fractions are not proof of an account NAV implementation.

The delayed transform fetches rolling1000 one-hour bars a second time, enters at original entry index+1 (signal timestamp+2h), preserves signal-based SL, scans from delayed entry through `min(last_bar, entry_index+48)` inclusive, fills SL at the stop without a gap-open adjustment, otherwise last scanned close. It copies `realized_cost_bps` from original parent. Full chronology admission happens on computed delayed trades; long-only child then takes the exact long subset. This code cannot be replaced by filtering stored256 and treated as new opportunity/occupancy economics.

## Already attempted mechanisms, exact current pinned evidence

The following paths were read at pinned master `8efbce6238e54e39bd9a59c5f5bfc723174f08f9`; paths are under `backend/research/rebuild/`. These are prior mechanisms, not D256 result substitutions.

| Axis / source | Rule and saved result |
|---|---|
| `trend_rider_wr8125_peer_consensus_child_policy_v1.py`, blob `c02239cd895adcc8d2565717a0923eef3bd83d73` | Fixed BTC↔ETH peer categorical ST direction, price-vs-ST, price-vs-EMA50, EMA50 slope sign; only re-enables otherwise blocked US transitions of WR81.25 chase-cooling parent. Result `a1_trend_rider_wr8125_peer_consensus_latest.json`, blob `94327d5ba58261f21d8967d6cb0070a6d3042b77`: `NO_STRICT_PEER_CONSENSUS_FUSION`; additional7=1winner+6losers; formal_credit0; next different causal architecture. Signed receipt `ca47713e33884258e31abc213f530477e2bb0635d3b3d092ba06ee8546e9bf33`. |
| `trend_rider_wr80_us_chase_cooling_child_policy_v1.py`, blob `7d6917cc59fe581a67668d8c389b36832802ea64` | Current completed-bar chase_atr<=prior completed-bar chase_atr, applied to US re-enable, non-US preserved. Latest forward blob `3a9820cf3c6dd8ce8050478e911e2990c580308e`:46T, Net/T−30.8909423, net−1420.98335, PF0.622064; H4 NO_PROVEN_EDGE/H5 HOLD; signed `dcaa357ea5cda04c2352d465ae1c9bfae41fb832dbbf2d10c8a25c92e6abad23`. |
| `trend_rider_wr8125_structural_consensus_child_policy_v1.py` (prior tree blob `82771f959c587fffc6c2bdbd28bbdbf4bef0f654`); result read | Structural US re-enable result blob `5b85b3fc0c84d557a28e4e6d9e5f9850385ce0f1`: `NO_STRICT_STRUCTURAL_CONSENSUS_FUSION`, extra2 both losers; formal_credit0. Do not use result as proof of D256 behavior. |
| `trend_rider_momentum_child_policy_v1.py`, blob `734c76df53157c87fbe1e5fa4a83f691e58e7602` | MACD12/26/9 histogram first-difference sign. Result blob `53d9b76ca9dee3aa0b160d9957962b3b3bbd6e36`: `FAIL_MOMENTUM_FROZEN_W123_RETENTION_BELOW_60PCT`, retention45.4545%. |
| `trend_rider_multiscale_alignment_child_policy_v1.py`, blob `1333e712ab5b49dbee5c1953f1760536890e07c6` | close/EMA21/EMA55 ordering plus both slopes. Result blob `461e9889d45b70ed8d539b269b34af72db147649`: `FAIL_MULTISCALE_ALIGNMENT_FROZEN_W123_DEVELOPMENT_SCREEN`, retention68.1818%. |
| `trend_rider_transition_freshness_child_policy_v1.py`, blob `94e945d67b397913735ebbe85771ec54078c2e24` | Current parent confirmation true/prior closed confirmation false. Router result blob `829a78b62e5e8bd6086ad9f3594fe2b2dfde9462`:47T,H4 NO_PROVEN_EDGE,H5 HOLD; next distinct axis. Parent delayed transform already has transition/cooldown enforcement, so rebranding that enforcement is particularly inappropriate. |
| `trend_rider_atr_expansion_child_policy_v1.py`, blob `e5a7053305339fe7516dfd2beef8c6caa007359a` | Existing ATR14 current>prior completed-bar ATR14 admission. Runner blob `df79232a7f79303603e13a6d172fd58941e96fec` exists for frozen22. **No completed ATR result was established in this review**; classify implemented/registered, not economically rejected by inference. |
| EMA50 slope reversal exit result `a1_trend_rider_ema_slope_exit_frozen_w123_ab_latest.json`, blob `dc5f5c915da45c9b80a581af22e54c8fc5346290` | `FAIL_EMA_SLOPE_EXIT_DEVELOPMENT_SCREEN`; changed4,unchanged18,retention100%; signed `d652816d4d9c6261ece3db9b15dda4bb103add1980c474ce3bb64206fd9c7df8`. |
| `a1_trend_rider_volatility_risk_scaling_g1_latest.json`, blob `486140913e87a697ca522bd5754e73e4a2efeb38` | Existing delayed-fill-long-only distinct34T parent, ATR50/ATR14 position scaling; `HOLD_TREND_RIDER_VOLATILITY_RISK_SCALING_G1`, concentration blocker count not improved; development_candidate_ready=false. Explicitly risk management, not signal alpha. |

Same-parent five-axis repair was also already run repeatedly. Exact frozen repair implementation computes: EMA21>EMA50>EMA55 plus slopes; current volume>=prior20 mean; current dollar-volume>=prior20 median; long-only; short-only. Latest run39783505611 has no ready axis. These are not unexplored D alternatives.

## Concrete lifecycle/data limits visible in256

- All256 rows retain `feature_sha`, but no complete feature snapshots or OHLCV arrays. `execution_snapshots` are cost inputs, not feature/bar history. `source` records interval/endpoints/ranges/counts, not original bar byte hashes.
- Cost snapshots supply fee/spread/impact/pretrade funding reserve; delayed transform keeps original realized cost despite changed holding interval. Exact delayed-period funding settlement rows are absent. This is a known cost-lineage limitation, not a new after-cost improvement.
- Four actual256 long trades entered below their preserved initial SL. The transform then prices an SL at that higher stop. No reprice or deletion was done here. #1388 comment6066988322 already documented this same defect class on separate264; neither that earlier diagnosis nor these256 rows constitute a new untried alpha axis.
- Archived `native_policy_ownership` counters are inherited301-parent counts (raw2191,admitted301,open1,rejected1889), not child256 counts. Use proper subset/integrity metadata and preserve inherited fields without interpreting them as256 admission totals.
- No per-bar MFE/MAE/recovery/target path is archived. Terminal winners and holding duration can be diagnosed; recovering winners cannot be causally classified from terminal outcomes alone. Reconstructing from newly fetched prices or ordinary K117 six-symbol30m cached bars would not bind this12-symbol1h lineage.

The four exact stored long-entry/stop geometry cases are below. All have `reason=SL` and `exit_ts=entry_ts`; stop equals recorded exit price. Values are read from the preserved receipt, and cost2 is solely `gross_bps−2×realized_cost_bps`. This is retrospective execution diagnosis, with no invented alternative fill, row removal, revised strategy return or new alpha claim.

| Symbol | signal_ts | entry_ts=exit_ts | Entry | SL=exit | Net1 bps | Net2 bps |
|---|---:|---:|---:|---:|---:|---:|
|1000PEPE-USDT|1789135200000|1789142400000|0.0033572|0.0033585576765489305|−8.955925923594165|−21.955925923594165|
|APE-USDT|1789866000000|1789873200000|0.1378|0.1383217735062538|9.255978113479653|−19.3525942994415|
|HYPE-USDT|1789866000000|1789873200000|90.054|90.41057755885379|26.59597117882518|13.595971178825181|
|APE-USDT|1790168400000|1790175600000|0.1537|0.15471175856961425|37.21827011240386|8.609697699482702|

Exact delayed `intent_sha` identities, in table order:

1. `9a6f7f8909c8327a87d48765ab338b083145fdae7a26b087b9db4999721d12b9` (parent `0c9d3c0d7b004fba41e82a43375bdc4971fa327ce464b257146af9c9aed719c8`).
2. `2e14982a64a8285cc14c090f2f6d62a479dbe06fde314960d6a23084c6ffa1d8` (parent `75cb5cae9eb8c765b03b630f8b9edb6f7a77f00acbbe44014ae64619d00ec99c`).
3. `591d9e24231875a51e02558d39ae5249091b89d1e26baa6b84e56fea3903cd9b` (parent `b65f5dc90183f37a622b9ab5b034539e38da9838cd8f3ebf8bb3110d86f81e76`).
4. `2afc6625afda157a381fbdb5ca1cba077f90267cc633a4143223b059ee153272` (parent `9f0dec96e7347cc973dcd8045b07f5eccb0dd4c7693ad5d4a89cf3ff1a4aab7a`).

## Bounded disposition

Deliver the saved256 full ledger diagnostic and source-map/missing-input proof. Mark new child count0 and economics unmeasured. Do not implement a renamed BTC/ETH peer, chase-cooling, multiscale, transition, momentum or sizing child to satisfy a count. If the complete original archived feature/bar/funding inputs are recovered later, they can support one properly frozen new mechanism in A's existing authority; this audit neither creates that authority nor asserts an economic candidate is ready.
