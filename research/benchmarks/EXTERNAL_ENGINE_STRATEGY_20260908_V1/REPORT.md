# Actual external engine / strategy benchmark

All monetary values are equal-notional trade-bps, not account returns. USED_DEV only.
Costs: original20bps floor/absolute funding proxy; same price paths repriced at2x, not ROI re-optimized at2x.
External ROI/SL are stock4h-candle assumptions. Intrabar time is unobserved; conservative bar-close funding debit applied. Forced engine terminal exits are OPEN marks, not wins.
Heracles rule and published loaded parameters unchanged; point-in-time100day verified-source-history age filter is an explicit adaptation of the source recommendation.
Offline SPOT matching applied to existing BingX futures price data is an analytical experiment, NOT certified futures support or a live strategy.
4h DD uses the same new4h-close valuation for native/external; never compare it as identical to old dailyDD.

|Period|Strategy|Closed/open|WR%|Payoff|PF|Terminal net|Allcost2|4h marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|ZEL_Break_V2_SAVED|155/2|50.968|1.187|1.233|4792.194|1623.063|4404.814|
|DEV2025|BREAK|155/1|50.968|1.187|1.234|5002.277|1853.145|4400.337|

## DEV2025 actual engine differences
```json
{
  "common_entries": 156,
  "declared_convention_deltas": [
    "ZEL_H6_CLOSE_VS_FT_NEXT_OPEN",
    "FT_NO_LAST_BAR_ENTRY",
    "FT_FORCE_EXIT_REPORTED_AS_OPEN_FINAL_CLOSE_MARK",
    "UNCONSTRAINED_ANALYTICAL_PRECISION_NOT_FUTURES_EXECUTION"
  ],
  "external_only_entries": [],
  "first_mismatches": [
    {
      "changes": {
        "exit_price": [
          0.0069044,
          0.006905
        ]
      },
      "origin": "1000PEPE-USDT:1742241600000"
    },
    {
      "changes": {
        "exit_price": [
          0.0079919,
          0.0079923
        ]
      },
      "origin": "1000PEPE-USDT:1742832000000"
    },
    {
      "changes": {
        "exit_price": [
          0.0083392,
          0.0083362
        ]
      },
      "origin": "1000PEPE-USDT:1742990400000"
    },
    {
      "changes": {
        "exit_price": [
          0.0079948,
          0.0079946
        ]
      },
      "origin": "1000PEPE-USDT:1745208000000"
    },
    {
      "changes": {
        "exit_price": [
          0.0091621,
          0.0091627
        ]
      },
      "origin": "1000PEPE-USDT:1745323200000"
    },
    {
      "changes": {
        "exit_price": [
          0.0125276,
          0.0125282
        ]
      },
      "origin": "1000PEPE-USDT:1746720000000"
    },
    {
      "changes": {
        "exit_price": [
          0.0126933,
          0.0126979
        ]
      },
      "origin": "1000PEPE-USDT:1749556800000"
    },
    {
      "changes": {
        "exit_price": [
          0.009712,
          0.0097123
        ]
      },
      "origin": "1000PEPE-USDT:1751529600000"
    },
    {
      "changes": {
        "exit_price": [
          0.0130203,
          0.0130196
        ]
      },
      "origin": "1000PEPE-USDT:1752696000000"
    },
    {
      "changes": {
        "exit_price": [
          0.0138145,
          0.0138157
        ]
      },
      "origin": "1000PEPE-USDT:1753041600000"
    }
  ],
  "mismatched_common_entries": 98,
  "native_only_entries": [
    "1000PEPE-USDT:1766980800000"
  ],
  "raw_signal_symmetric_difference": [],
  "raw_signals_external": 283,
  "raw_signals_native": 283
}
```

No D/D2/KR3 promotion or removal. No parameter sweep, new market collection, paid AI, unused OOS or live orders.
Remote closure/CI/merge status is separate. A failed or incompatible benchmark is not proof all external systems fail.
