# Trend Rider 256 saved-ledger findings

Read-only scope: the original 256 long-only closed rows, run `37989679810`, artifact `11646670634`, member `long_only_prospective.json`. No replay, price/feature calculation, altered stops/costs, policy sweep or new economic run. K117 and older D files are unchanged.

## Binding and clocks

- Raw file SHA256: `686c5574c2554867b8cdb38fcb23f2de50fa9c3837dd9406d0be4a168b976fb9`.
- Native semantic receipt SHA256: `4515dfa653d0ebf25029ee6b1eb0a9a54f81c8c4f65d3fbaecc30f9efc334c70`.
- Verified by extracting only the native `stable` function from `a1_trend_rider_exact_parent_repair_batch_v1.py`, SHA256 `b878606b67ed1153cbb95b8a357055b2a1824e64e2652a22e7d830552957d45d`. It hashes sorted compact UTF-8 JSON excluding `receipt_sha256`. This is integrity verification, not a digital signer or proof of actual fills.
- Schema: `zel.a1.trend_rider.long_only_exact_parent_economics.v1`; challenger `trend_rider_delayed_fill_long_only_v1`. All 256 are long, 12 symbols, frozen 1h source.
- All 256 signal-bar → parent-entry-bar → delayed-entry-bar differences are exactly 1h each. Native rows are entry-time/symbol ordered, not close ordered.
- Native `exit_ts` is the exit bar's opening label: SL uses that bar's low/high; TIMEOUT uses its closing price. The field does not give actual intrabar fill or outcome-availability time. Same-bar ordering is unknown.

## Actual rows and cost fragility

Values below are sums of per-trade bps, with equal row weights. They have no quantity, quote-money, NAV or mark-to-market interpretation. Decimal arithmetic uses saved numeric spellings; the source float metrics are retained separately. The sum of saved net minus Decimal(gross − cost) is only `-1.029e-13` bps.

| Report | Trades | Wins | Gross sum | Cost sum | Net sum | Net/trade | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| Saved cost 1x | 256 | 64 | 10832.718773 | 4685.807815 | 6146.910959 | 24.011371 | 1.195871 |
| Posthoc cost 2x | 256 | 63 | 10832.718773 | 9371.615630 | 1461.103144 | 5.707434 | 1.042101 |

Cost 2x is gross minus twice realized cost; it is not net minus twice cost, an execution input, or a candidate result. Only one positive-gross row becomes nonpositive at 1x; one 1x winner becomes nonpositive at 2x. Thus this sample's principal loss mass is not a large population of tiny positive-gross trades crossed solely by fees.

SL: 189 rows, 3 net winners, Net1 `-30868.035425`, Net2 `-34110.882233`. TIMEOUT: 67 rows, 61 net winners, Net1 `37014.946383`, Net2 `35571.985377`; all timeout exit/entry bar-label spans equal 48h. These are retrospective outcome categories, not lawful runtime selectors.

Four original entries are below their frozen long stop (PEPE Sep11; APE and HYPE Sep20; APE Sep23). The native evaluator books the stop price when touched; those four have positive gross, and three have positive Net1. The code preserves and flags all four. It does not reprice, repair, remove them or assume realistic gap fills.

## Concentration and October clock correction

| Largest winners removed descriptively | Net1 remaining | Net2 remaining |
|---|---:|---:|
| 1 | 2807.415145 | -1861.272415 |
| 3 | -1050.100575 | -5688.754042 |
| 5 | -4165.497548 | -8773.248304 |
| 10 | -10505.847279 | -14987.603665 |

The largest cost2 winner is BCH, saved entry `256.27`, TIMEOUT exit `342.29`, gross `3356.616069`, cost `17.120255`, Net2 `3322.375559`. It contributes 227.388% of signed total Net2, but only 9.186% of positive Net2 profit. Those denominators must not be confused. Top10 contribute 45.481% of positive Net2 profit. These leave-outs measure concentration and are not filtered strategy results. All 64 Net1 winners and all 63 Net2 winners remain in the report.

| UTC month basis | September rows / Net1 | October rows / Net1 |
|---|---:|---:|
| Entry bar | 203 / 10391.117630 | 53 / -4244.206671 |
| Exit bar | 197 / 10146.710856 | 59 / -3999.799897 |

The previously quoted October 59 trades is an **exit-bar month** statistic. Both clocks are reported separately; neither calendar labels nor loss labels become execution features.

## Drawdown and consecutive losses

| Ordering / observation unit | 1x diagnostic DD | 2x diagnostic DD | Maximum consecutive negative observations |
|---|---:|---:|---:|
| Original entry-ordered individual trades | 10783.896244 | 13018.070873 | 33 trades |
| Exit-bar ordered individual trades; arbitrary same-bar ties | 10503.594917 | 12722.752499 | 40 trades |
| All same-exit-bar outcomes netted once | 10503.594917 | 12722.752499 | 24 cohorts |

There are 156 exit-bar cohorts, including 61 with multiple trades. Grouped drawdown does not observe intrabar drawdown; individual tie ordering does not establish actual order. All curves finish at the same net sum.

## Missing causal evidence and inherited scope

Every closed row has the same 20 fields: config/cost/feature/policy identity hashes; entry/exit prices and bar timestamps; signal and parent-entry timestamps; parent/delayed intent hashes; side/symbol/reason; gross/net/cost; entry-delay bars; sealed intent geometry (SL, null TP, timeout 48 bars). There are no feature values, feature `available_ts`, source OHLC paths, MFE/MAE, recovery traces, intrabar fill times, or partial/stop-update traces.

Consequently, prior-completed BTC/ETH trend, volatility and entry-chase context cannot be certified from these rows. A final winner or 48h TIMEOUT does not prove a recovery winner, nor that an earlier exit would preserve it. Recovery/MFE/MAE remain UNKNOWN for every row. Changed entry/exit opportunities require A's full chronology, not these final labels.

`native_policy_ownership` and the lists of 1 open / 1889 rejected intents are inherited from the 301-closed parent. Their native list hashes verify, but they are not the admission ledger of the filtered 256-long child. No PnL is assigned to them. The open record remains separately visible.

Liquid6 T123 has separate raw SHA `ddeadab19a915bf43cee8534f44369cd7ff5805aacf10331a308e4201dc17028` and receipt SHA `a98f502f1b161bff5309a22bba320fd3f8725874e9303991ac8bb5f960ac0a43`. Its saved bps are scaled by 1/3; unscaled `instrument_*` fields are separate. This attribution module does not merge it with long256 or rebuild the prior mixture.

**Result: SOURCE_FEATURE_BLOCKED / NO_CAUSAL_CHILD, candidate count 0.** The attribution is complete and reviewable; it creates no economic improvement claim.
