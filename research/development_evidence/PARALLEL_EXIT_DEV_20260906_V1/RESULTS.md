# Q0 / Keltner exit comparison

Both calendars are reused development evidence; independent=false. Equal nominal trade-bps, not account returns. Code PASS does not establish economic adoption.

| Candidate / period | View | Closed/open | Net E | PF | Win% | Payoff | Cost2 E | Closed net | Marked DD | Max grouped loss | Exposure days |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Q0_DEV2025 | P | 86/0 | 47.3970 | 1.2407 | 33.7209 | 2.4386 | 21.2418 | 4,076.1430 | 6,801.4788 | 5,224.6878 | 276.6667 |
| Q0_DEV2025 | FIXED | 86/0 | 47.2319 | 1.2397 | 33.7209 | 2.4366 | 21.1353 | 4,061.9464 | 6,858.0601 | 5,181.6110 | 274.3333 |
| Q0_DEV2025 | FULL | 86/0 | 47.2319 | 1.2397 | 33.7209 | 2.4366 | 21.1353 | 4,061.9464 | 6,858.0601 | 5,181.6110 | 274.3333 |

Q0_DEV2025 decision: `{"decision": "REJECT", "fixed_entry_decision": "REJECT", "full_replay_decision": "REJECT", "research_child_reference_supported": false, "existing_Q0_or_operating_baseline_changed": false, "formal_pass": false, "independent": false}`

| Q0_SEEN2026 | P | 34/0 | 215.1423 | 2.2360 | 32.3529 | 4.6752 | 189.6582 | 7,314.8393 | 5,619.0811 | 2,779.7110 | 97.0000 |
| Q0_SEEN2026 | FIXED | 34/0 | 219.8942 | 2.2987 | 32.3529 | 4.8064 | 194.4995 | 7,476.4040 | 5,457.5163 | 2,695.3691 | 95.3333 |
| Q0_SEEN2026 | FULL | 34/0 | 219.8942 | 2.2987 | 32.3529 | 4.8064 | 194.4995 | 7,476.4040 | 5,457.5163 | 2,695.3691 | 95.3333 |

Q0_SEEN2026 decision: `{"decision": "TRADEOFF", "fixed_entry_decision": "TRADEOFF", "full_replay_decision": "TRADEOFF", "research_child_reference_supported": false, "existing_Q0_or_operating_baseline_changed": false, "formal_pass": false, "independent": false}`

| KELTNER_DEV2025 | P | 217/1 | -2.9223 | 0.9866 | 47.4654 | 1.0919 | -24.2163 | -634.1339 | 16,609.7673 | 7,709.3138 | 434.1667 |
| KELTNER_DEV2025 | FIXED | 217/1 | 18.0208 | 1.0927 | 47.0046 | 1.2320 | -3.0756 | 3,910.5089 | 12,265.1987 | 5,219.6360 | 399.3333 |
| KELTNER_DEV2025 | FULL | 217/1 | 18.0208 | 1.0927 | 47.0046 | 1.2320 | -3.0756 | 3,910.5089 | 12,265.1987 | 5,219.6360 | 399.3333 |

KELTNER_DEV2025 decision: `{"decision": "REJECT", "fixed_entry_decision": "REJECT", "full_replay_decision": "REJECT", "research_child_reference_supported": false, "existing_Q0_or_operating_baseline_changed": false, "formal_pass": false, "independent": false}`

| KELTNER_SEEN2026 | P | 78/4 | -21.5282 | 0.8869 | 35.8974 | 1.5837 | -43.1126 | -1,679.1979 | 5,023.0786 | 3,547.7544 | 160.3333 |
| KELTNER_SEEN2026 | FIXED | 78/4 | -35.4621 | 0.8148 | 33.3333 | 1.6295 | -56.8942 | -2,766.0406 | 6,059.7626 | 3,758.3091 | 145.1667 |
| KELTNER_SEEN2026 | FULL | 79/4 | -18.4939 | 0.9022 | 34.1772 | 1.7375 | -39.9079 | -1,461.0166 | 6,059.7626 | 3,758.3091 | 147.1667 |

KELTNER_SEEN2026 decision: `{"decision": "REJECT", "fixed_entry_decision": "REJECT", "full_replay_decision": "REJECT", "research_child_reference_supported": false, "existing_Q0_or_operating_baseline_changed": false, "formal_pass": false, "independent": false}`

## Signals, costs and unfinished positions

| Study | View | Signals | Gross E | Avg win/loss | Fee/funding | Total cost | Open gross/net/cost2 | Max simultaneous | Recovery days/open underwater days |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Q0_DEV2025 | P | 102 | 73.5522 | 724.5046/-297.0963 | 860.0000/934.6400 | 2,249.3472 | 0.0000/0.0000/0.0000 | 6 | 85.0000/159.0000 |
| Q0_DEV2025 | FIXED | 86 | 73.3285 | 724.5046/-297.3454 | 860.0000/925.6000 | 2,244.3072 | 0.0000/0.0000/0.0000 | 6 | 85.0000/159.0000 |
| Q0_DEV2025 | FULL | 102 | 73.3285 | 724.5046/-297.3454 | 860.0000/925.6000 | 2,244.3072 | 0.0000/0.0000/0.0000 | 6 | 85.0000/159.0000 |
| Q0_SEEN2026 | P | 40 | 240.6265 | 1,203.0127/-257.3174 | 340.0000/348.5400 | 866.4604 | 0.0000/0.0000/0.0000 | 5 | 102.0000/8.0000 |
| Q0_SEEN2026 | FIXED | 34 | 245.2890 | 1,203.0127/-250.2929 | 340.0000/342.5000 | 863.4204 | 0.0000/0.0000/0.0000 | 5 | 102.0000/8.0000 |
| Q0_SEEN2026 | FULL | 40 | 245.2890 | 1,203.0127/-250.2929 | 340.0000/342.5000 | 863.4204 | 0.0000/0.0000/0.0000 | 5 | 102.0000/8.0000 |
| KELTNER_DEV2025 | P | 379 | 18.3718 | 451.7071/-413.6839 | 2,170.0000/1,535.5800 | 4,620.8088 | -56.7311/-76.7311/-96.7311 | 7 | 64.0000/101.3333 |
| KELTNER_DEV2025 | FIXED | 218 | 39.1172 | 451.9685/-366.8720 | 2,170.0000/1,412.4400 | 4,577.9225 | -56.7311/-76.7311/-96.7311 | 7 | 64.0000/137.3333 |
| KELTNER_DEV2025 | FULL | 379 | 39.1172 | 451.9685/-366.8720 | 2,170.0000/1,412.4400 | 4,577.9225 | -56.7311/-76.7311/-96.7311 | 7 | 64.0000/137.3333 |
| KELTNER_SEEN2026 | P | 126 | 0.0563 | 470.1711/-296.8798 | 780.0000/573.5400 | 1,683.5870 | -536.9856/-616.9856/-696.9856 | 7 | 14.0000/93.0000 |
| KELTNER_SEEN2026 | FIXED | 82 | -14.0299 | 467.9307/-287.1584 | 780.0000/519.9100 | 1,671.7067 | -536.9856/-616.9856/-696.9856 | 7 | 13.0000/93.0000 |
| KELTNER_SEEN2026 | FULL | 126 | 2.9201 | 498.9341/-287.1584 | 790.0000/525.9100 | 1,691.7067 | -536.9856/-616.9856/-696.9856 | 7 | 13.0000/93.0000 |

## Exit effects and preservation

| Study | View | Common CC/CO/OC/OO | Removed/new closed/open | Closed net delta | Original win retained | Large win amount retained/parent | Daily delta95 |
|---|---|---|---|---:|---:|---:|---|
| Q0_DEV2025 | FIXED | 86/0/0/0 | 0/0/0/0 | -14.1966 | 1.0000 | 10,154.1931/10,154.1931 | [-0.610605503957239, 0.5416363115750028] |
| Q0_DEV2025 | FULL | 86/0/0/0 | 0/0/0/0 | -14.1966 | 1.0000 | 10,154.1931/10,154.1931 | [-0.610605503957239, 0.5416363115750028] |
| Q0_SEEN2026 | FIXED | 34/0/0/0 | 0/0/0/0 | 161.5647 | 1.0000 | 6,387.6943/6,387.6943 | [-0.000782253939952543, 3.3078813229395396] |
| Q0_SEEN2026 | FULL | 34/0/0/0 | 0/0/0/0 | 161.5647 | 1.0000 | 6,387.6943/6,387.6943 | [-0.000782253939952543, 3.3078813229395396] |
| KELTNER_DEV2025 | FIXED | 217/0/0/1 | 0/0/0/0 | 4,544.6428 | 0.9909 | 16,803.7818/16,803.7818 | [-1.937453800687487, 31.671720220651736] |
| KELTNER_DEV2025 | FULL | 217/0/0/1 | 0/0/0/0 | 4,544.6428 | 0.9909 | 16,803.7818/16,803.7818 | [-1.937453800687487, 31.671720220651736] |
| KELTNER_SEEN2026 | FIXED | 78/0/0/4 | 0/0/0/0 | -1,086.8426 | 0.9241 | 4,973.4681/4,973.4681 | [-30.1615031306647, 2.238835293119354] |
| KELTNER_SEEN2026 | FULL | 78/0/0/4 | 0/0/1/0 | 218.1813 | 0.9241 | 4,973.4681/4,973.4681 | [-29.26517418010398, 22.76292274918875] |

## Closed-net decomposition

| Study | View | Common loss improved/worsened | Winner profit cut/flipped loss/added | New net | Removed loss/profit | Cost/funding delta (already in net) |
|---|---|---:|---:|---:|---:|---:|
| Q0_DEV2025 | FIXED | 120.4656/134.6621 | 0.0000/0.0000/0.0000 | 0.0000 | 0.0000/0.0000 | -5.0400/-9.0400 |
| Q0_DEV2025 | FULL | 120.4656/134.6621 | 0.0000/0.0000/0.0000 | 0.0000 | 0.0000/0.0000 | -5.0400/-9.0400 |
| Q0_SEEN2026 | FIXED | 181.4237/19.8590 | 0.0000/0.0000/0.0000 | 0.0000 | 0.0000/0.0000 | -3.0400/-6.0400 |
| Q0_SEEN2026 | FULL | 181.4237/19.8590 | 0.0000/0.0000/0.0000 | 0.0000 | 0.0000/0.0000 | -3.0400/-6.0400 |
| KELTNER_DEV2025 | FIXED | 7,769.9940/2,606.2768 | 425.0409/194.0335/0.0000 | 0.0000 | 0.0000/0.0000 | -42.8864/-123.1400 |
| KELTNER_DEV2025 | FULL | 7,769.9940/2,606.2768 | 425.0409/194.0335/0.0000 | 0.0000 | 0.0000/0.0000 | -42.8864/-123.1400 |
| KELTNER_SEEN2026 | FIXED | 856.3860/525.3847 | 998.5928/419.2512/0.0000 | 0.0000 | 0.0000/0.0000 | -11.8804/-53.6300 |
| KELTNER_SEEN2026 | FULL | 856.3860/525.3847 | 998.5928/419.2512/0.0000 | 1,305.0240 | 0.0000/0.0000 | 8.1196/-47.6300 |
## Complete accounting

Per-period compressed ledgers include every fill, trigger, event, open mark, UTC marked path, monthly/symbol concentration, paired block uncertainty, same-calendar loss/DD attribution and common/new/removed origin bridge. receipt.json retains all summary metrics.

Q0 freezes the original entry channel upper. Keltner preserves original EMA20/50 seed, entry,12-bar maximum and absence of a separate SL. Full replay includes newly available opportunities; FIXED isolates original admitted entries and is a counterfactual accounting view.

Native Keltner exact-end excluded horizon remains an explicit open mark. Open marks use the unchanged hypothetical full roundtrip research cost; no terminal forced fill. Original closed ledgers remain unchanged.

2025 calendars: Q0 2025-01-29T00Z–2025-12-29T00Z; Keltner 2024-12-19T08Z–2025-12-29T08Z. 2026 both 2026-05-08T00Z–2026-09-05T00Z. Native calendar differences are preserved. No rows after2026-09-05T00Z decoded. Existing split labels in the authorized seen prefix do not confer independent validation.

| Top5 | This batch |
|---|---|
| Primary | Preserved, no new candidate |
| Broad | Preserved, no new candidate |
| Break / Q0 lineage | Entry-channel-loss exit research child only; Q0 baseline unchanged |
| Keltner V2 | Trend-invalidation exit research child only; parent unchanged |
| Supertrend | Preserved, no new candidate |

Candidate count26→28;2new candidates,4candidate-period applications,8fixed/full comparison views;0remaining. Previous26history, seen1/1 and independent0/1 NOT_RUN preserved. No retuning or further candidate.

PR1195 observer code/calendar/source/cursor/schedule unchanged and never used as development input. No G5B replacement, G6 formal credit, account sizing, orders/live execution or paid externalAI. New child future validation would need its own prospective freeze/boundary and separate authorization; existing Q0 future data cannot be retroactively unused child evidence.
