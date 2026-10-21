# Keltner stage2: fresh-signal handoff during conditional extension

Completed UTC: 2026-10-21T16:32:02.283261+00:00
Classification: ACTUAL_USED_DEV_CHRONOLOGICAL_COMPARISON_NOT_OOS_NOT_ACCOUNT_RETURN
Disposition: REJECT_INCREMENTAL_HANDOFF_KEEP126_WINNER_EXTENSION

One frozen change: after the original25-bar deadline and observed2R qualification, an eligible same-direction native signal can close the old remaining position and start one new ordinary position at the next open. No concurrent pyramiding. Full cost model charged to each trade. Existing25/50 cap and protected lifecycle unchanged.

|Metric|Prior126 extension|New handoff|
|---|---:|---:|
|Trades|126.00000000|128.00000000|
|Net1x trade-bps|7925.82228888|7567.23483215|
|PF1x|2.00231147|1.93901410|
|WR1x pct|54.76190476|54.68750000|
|DD1x trade-bps|1838.64200493|1838.64200493|
|Loss streak1x|8.00000000|8.00000000|
|Net2x trade-bps|6032.79913990|5645.28103590|
|PF2x|1.66446380|1.61067321|
|DD2x trade-bps|2059.60759415|2059.60759415|
|Loss streak2x|13.00000000|13.00000000|

Net delta1x -358.58745673; delta2x -387.51810400 trade-bps.
Handoffs 2; unresolved 0; boundary excluded 0.

## Opportunity accounting
{
  "recovered_vs128_keys": [
    {
      "key": [
        "BTC-USDT",
        -1,
        1769974200000
      ],
      "net1x": 14.449052801677752,
      "net2x": 0.44905280167775175,
      "reason": "STOP_FIRST"
    },
    {
      "key": [
        "BTC-USDT",
        -1,
        1769988600000
      ],
      "net1x": -151.1577899844856,
      "net2x": -165.1577899844856,
      "reason": "STOP_FIRST"
    },
    {
      "key": [
        "DOGE-USDT",
        1,
        1787317200000
      ],
      "net1x": 980.5396339796674,
      "net2x": 963.8089867123663,
      "reason": "STOP_FIRST"
    }
  ],
  "lost_vs126": [
    {
      "key": [
        "BTC-USDT",
        -1,
        1769999400000
      ],
      "net1x": 154.63418123013997,
      "net2x": 140.63418123013997,
      "reason": "STOP_FIRST"
    }
  ],
  "added_vs126": [
    {
      "key": [
        "BTC-USDT",
        -1,
        1769974200000
      ],
      "net1x": 14.449052801677752,
      "net2x": 0.44905280167775175,
      "reason": "STOP_FIRST"
    },
    {
      "key": [
        "BTC-USDT",
        -1,
        1769988600000
      ],
      "net1x": -151.1577899844856,
      "net2x": -165.1577899844856,
      "reason": "STOP_FIRST"
    },
    {
      "key": [
        "DOGE-USDT",
        1,
        1787317200000
      ],
      "net1x": 980.5396339796674,
      "net2x": 963.8089867123663,
      "reason": "STOP_FIRST"
    }
  ],
  "cohorts": {
    "original_large35": {
      "baseline_count": 35,
      "child_net1x": 14318.067206827975,
      "child_net2x": 13785.799005701985,
      "child_retained_count": 35,
      "prior126_net1x": 14370.862692343384,
      "prior126_net2x": 13867.525138484692,
      "prior126_retained_count": 33
    },
    "original_remainder93": {
      "baseline_count": 93,
      "child_net1x": -6750.832374682438,
      "child_net2x": -8140.517969800363,
      "child_retained_count": 93,
      "prior126_net1x": -6599.674584697953,
      "prior126_net2x": -7975.360179815876,
      "prior126_retained_count": 92
    }
  },
  "changed_common_trades": [
    {
      "child_exit": 1769974200000,
      "child_net1x": 111.86906046935954,
      "delta1x": -103.23065880700076,
      "key": [
        "BTC-USDT",
        -1,
        1769925600000
      ],
      "prior_exit": 1769988600000,
      "prior_net1x": 215.0997192763603
    },
    {
      "child_exit": 1787317200000,
      "child_net1x": 348.68293025965085,
      "delta1x": -944.5535134897498,
      "key": [
        "DOGE-USDT",
        1,
        1787272200000
      ],
      "prior_exit": 1787356800000,
      "prior_net1x": 1293.2364437494007
    }
  ]
}

## Limits and preservation
- The old126T positive extension is immutable; an inferior child is rejected rather than replacing it.
- Full original signal/state/rejection chronology, fees, missed/reintroduced trades and extra carry scenario included; not selected-winner recovery.
- Same245-day usedDEV and original365-day indicator/context prefix. Source hashes and context-fit parity confirmed; disabled adapter reproduces126T exactly.
- Historical funding, real execution latency, MTM/account drawdown and independentOOS remain unverified; summed trade-bps are not account percent.
- No activeShadow/root strategy/workflow/OWNER/CHECKPOINT mutation, no tokens, marketAPI, paidAPI, orders or deployment. ReservedS comparison untouched.
- Separately joined all128 entry-time OHLC/EMA20/ADX fields; this is input reconstruction, not a newly successful loss filter.
- No parameter sweep. Current user approved this one additional missed-opportunity mechanism.
- Existing other global-heavy work was allowed to terminate; no cancellation or preemption.

Source result commit308bd2deb7acaaacf1adb582206e78262d72c9d1; new freeze68e4b995419aea62e6362c01f8a54fd3455c556fde444f8877e8cf9547244b1a.
