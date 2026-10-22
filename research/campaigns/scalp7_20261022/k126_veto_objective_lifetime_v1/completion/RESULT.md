# K126 conditional veto expiry: actual single-comparison result

Unit: equal-notional summed trade-bps, NOT account return. Used development data, NOT untouched OOS.

|Metric|Retained K126|C114 immediate reset|Conditional objective expiry|
|---|---:|---:|---:|
|cost1x T|126|114|117|
|cost1x Net_bps|7942.268973684915|6788.356135984457|10159.281145923826|
|cost1x PF|2.0064847071126635|2.1064890609837423|2.636027419753336|
|cost1x MaxLossStreak|8|5|5|
|cost1x worst_loss_run_bps|-1128.2251166863311|-892.532161239613|-892.532161239613|
|cost1x DD_bps|1838.6420049280318|1587.880662214915|1400.1718363206815|
|cost2x T|126|114|117|
|cost2x Net_bps|6049.2458247083|5075.946442314331|8399.99437120003|
|cost2x PF|1.6674843985707057|1.7072792645212982|2.161761069436464|
|cost2x MaxLossStreak|13|11|11|
|cost2x worst_loss_run_bps|-1946.766452879958|-1465.0298586461777|-1465.0298586461777|
|cost2x DD_bps|2059.6075941499575|1993.7531144345073|1577.8709999161774|

## What changed
Only untraded setup lifetime after a known regime veto: preserve the setup until its touch-time prior20 objective has already been reached, then expire and require a new native EMA touch. Existing entries without a veto and accepted positions are not subjected to the new expiry. Original stop/exit/cost formulas remain fixed. The 20-bar reference is already in native code; it is a mechanical proxy, not a source-exact author rule.

## Actual economics and falsification
Complete chronology includes changed initial geometry, lost/replaced entries, occupancy and inherited carry cost. No loser deletion or winner whitelist. Both prior controls remain immutable.
Disposition versus retained126: PRESERVE_DEV_CANDIDATE_PENDING_INDEPENDENT_VALIDATION

Against saved114:
```json
{
  "cost1x": {
    "added_net": 2626.989205230606,
    "common_delta": 648.0310966309755,
    "net_delta": 3370.9250099393685,
    "reconciled": true,
    "removed_net": -95.90470807778647
  },
  "cost2x": {
    "added_net": 2524.052148656743,
    "common_delta": 648.0310966309755,
    "net_delta": 3324.0479288856986,
    "reconciled": true,
    "removed_net": -151.96468359798388
  }
}
```

Formerly missed five winners:
```json
[
  {
    "child": null,
    "old": {
      "entry_ts_ms": 1769371200000,
      "exit_ts_ms": 1769380200000,
      "key": [
        "ETH-USDT",
        -1,
        1769371200000
      ],
      "net1x": 38.97141535779648,
      "net2x": 24.97141535779648,
      "reason": "HG_FROZEN_5BAR_MFE_SCRATCH"
    },
    "restored": false
  },
  {
    "child": {
      "entry_ts_ms": 1770159600000,
      "exit_ts_ms": 1770204600000,
      "key": [
        "SOL-USDT",
        -1,
        1770159600000
      ],
      "net1x": 209.06498371713926,
      "net2x": 195.04499187707347,
      "reason": "MAX_HOLD_NEXT_OPEN"
    },
    "old": {
      "entry_ts_ms": 1770159600000,
      "exit_ts_ms": 1770204600000,
      "key": [
        "SOL-USDT",
        -1,
        1770159600000
      ],
      "net1x": 209.06498371713926,
      "net2x": 195.04499187707347,
      "reason": "MAX_HOLD_NEXT_OPEN"
    },
    "restored": true
  },
  {
    "child": {
      "entry_ts_ms": 1770242400000,
      "exit_ts_ms": 1770312600000,
      "key": [
        "XRP-USDT",
        -1,
        1770242400000
      ],
      "net1x": 1453.3719072868907,
      "net2x": 1437.2254735005267,
      "reason": "OPEN_GAP_STOP"
    },
    "old": {
      "entry_ts_ms": 1770242400000,
      "exit_ts_ms": 1770312600000,
      "key": [
        "XRP-USDT",
        -1,
        1770242400000
      ],
      "net1x": 1453.3719072868907,
      "net2x": 1437.2254735005267,
      "reason": "OPEN_GAP_STOP"
    },
    "restored": true
  },
  {
    "child": {
      "entry_ts_ms": 1770289200000,
      "exit_ts_ms": 1770327000000,
      "key": [
        "SOL-USDT",
        -1,
        1770289200000
      ],
      "net1x": 1007.4796418545358,
      "net2x": 993.45965001447,
      "reason": "STOP_FIRST"
    },
    "old": {
      "entry_ts_ms": 1770289200000,
      "exit_ts_ms": 1770327000000,
      "key": [
        "SOL-USDT",
        -1,
        1770289200000
      ],
      "net1x": 1007.4796418545358,
      "net2x": 993.45965001447,
      "reason": "STOP_FIRST"
    },
    "restored": true
  },
  {
    "child": {
      "entry_ts_ms": 1772251200000,
      "exit_ts_ms": 1772263800000,
      "key": [
        "ETH-USDT",
        -1,
        1772251200000
      ],
      "net1x": 333.8064361361656,
      "net2x": 319.8064361361656,
      "reason": "STOP_FIRST"
    },
    "old": {
      "entry_ts_ms": 1772251200000,
      "exit_ts_ms": 1772263800000,
      "key": [
        "ETH-USDT",
        -1,
        1772251200000
      ],
      "net1x": 333.8064361361656,
      "net2x": 319.8064361361656,
      "reason": "STOP_FIRST"
    },
    "restored": true
  }
]
```

Original126 winner retention:
```json
{
  "original_winners": 69,
  "same_entry_retained": 68,
  "same_entry_and_same_net": 68,
  "missing": [
    {
      "key": [
        "ETH-USDT",
        -1,
        1769371200000
      ],
      "old_net1x": 38.97141535779648
    }
  ]
}
```

All126 attribution:
```json
{
  "cost1x": {
    "added_net": 289.6733214831372,
    "common_delta": 355.84479522969366,
    "net_delta": 2217.0121722389104,
    "reconciled": true,
    "removed_net": -1571.49405552608
  },
  "cost2x": {
    "added_net": 258.7218698887393,
    "common_delta": 355.84479522969366,
    "net_delta": 2350.74854649173,
    "reconciled": true,
    "removed_net": -1736.1818813733007
  }
}
```

Original worst8 entries:
```json
[
  {
    "new": {
      "entry_ts_ms": 1770429600000,
      "exit_ts_ms": 1770447600000,
      "key": [
        "XRP-USDT",
        1,
        1770429600000
      ],
      "net1x": -192.28643278646092,
      "net2x": -207.53286657282482,
      "reason": "STOP_FIRST"
    },
    "old": {
      "entry_ts_ms": 1770429600000,
      "exit_ts_ms": 1770447600000,
      "key": [
        "XRP-USDT",
        1,
        1770429600000
      ],
      "net1x": -192.28643278646092,
      "net2x": -207.53286657282482,
      "reason": "STOP_FIRST"
    },
    "same_original_entry_retained": true
  },
  {
    "new": {
      "entry_ts_ms": 1771241400000,
      "exit_ts_ms": 1771248600000,
      "key": [
        "DOGE-USDT",
        -1,
        1771241400000
      ],
      "net1x": -164.58304389948103,
      "net2x": -181.31369116678218,
      "reason": "STOP_FIRST"
    },
    "old": {
      "entry_ts_ms": 1771241400000,
      "exit_ts_ms": 1771248600000,
      "key": [
        "DOGE-USDT",
        -1,
        1771241400000
      ],
      "net1x": -164.58304389948103,
      "net2x": -181.31369116678218,
      "reason": "STOP_FIRST"
    },
    "same_original_entry_retained": true
  },
  {
    "new": {
      "entry_ts_ms": 1771268400000,
      "exit_ts_ms": 1771279200000,
      "key": [
        "DOGE-USDT",
        -1,
        1771268400000
      ],
      "net1x": -99.08215333126796,
      "net2x": -115.81280059856911,
      "reason": "STOP_FIRST"
    },
    "old": {
      "entry_ts_ms": 1771268400000,
      "exit_ts_ms": 1771279200000,
      "key": [
        "DOGE-USDT",
        -1,
        1771268400000
      ],
      "net1x": -99.08215333126796,
      "net2x": -115.81280059856911,
      "reason": "STOP_FIRST"
    },
    "same_original_entry_retained": true
  },
  {
    "new": null,
    "old": {
      "entry_ts_ms": 1771817400000,
      "exit_ts_ms": 1771826400000,
      "key": [
        "ETH-USDT",
        -1,
        1771817400000
      ],
      "net1x": -51.522543134773656,
      "net2x": -65.52254313477366,
      "reason": "HG_FROZEN_5BAR_MFE_SCRATCH"
    },
    "same_original_entry_retained": false
  },
  {
    "new": null,
    "old": {
      "entry_ts_ms": 1771817400000,
      "exit_ts_ms": 1771826400000,
      "key": [
        "SOL-USDT",
        -1,
        1771817400000
      ],
      "net1x": -56.64683900344197,
      "net2x": -70.66683084350777,
      "reason": "HG_FROZEN_5BAR_MFE_SCRATCH"
    },
    "same_original_entry_retained": false
  },
  {
    "new": null,
    "old": {
      "entry_ts_ms": 1771821000000,
      "exit_ts_ms": 1771830000000,
      "key": [
        "LINK-USDT",
        -1,
        1771821000000
      ],
      "net1x": -197.5453888112064,
      "net2x": -213.2504066192404,
      "reason": "HG_FROZEN_5BAR_MFE_SCRATCH"
    },
    "same_original_entry_retained": false
  },
  {
    "new": null,
    "old": {
      "entry_ts_ms": 1771821000000,
      "exit_ts_ms": 1771830000000,
      "key": [
        "XRP-USDT",
        -1,
        1771821000000
      ],
      "net1x": -229.68158022987848,
      "net2x": -244.92801401624237,
      "reason": "HG_FROZEN_5BAR_MFE_SCRATCH"
    },
    "same_original_entry_retained": false
  },
  {
    "new": {
      "entry_ts_ms": 1771835400000,
      "exit_ts_ms": 1771840800000,
      "key": [
        "SOL-USDT",
        -1,
        1771835400000
      ],
      "net1x": -136.87713548982077,
      "net2x": -150.8971273298866,
      "reason": "STOP_FIRST"
    },
    "old": {
      "entry_ts_ms": 1771835400000,
      "exit_ts_ms": 1771840800000,
      "key": [
        "SOL-USDT",
        -1,
        1771835400000
      ],
      "net1x": -136.87713548982077,
      "net2x": -150.8971273298866,
      "reason": "STOP_FIRST"
    },
    "same_original_entry_retained": true
  }
]
```

## Limitations
Repeated use of the same development sample can overfit. Independent untouched evaluation, account NAV/MTM and actual historical funding are not verified. No Shadow/Live replacement, no order or paid API. D risk allocation and the reserved Squeeze comparison remain untouched.
