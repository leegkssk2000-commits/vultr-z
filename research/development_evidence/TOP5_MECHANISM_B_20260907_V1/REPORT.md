# Top5 메커니즘 이식 — 최종 경제 비교

동일 명목 trade-bps, 계좌 수익률 아님. 종료값은 비용과 미완결의 가상 전체 비용 평가를 포함한다. cost2는 fee뿐 아니라 spread·impact·slippage·funding·floor 전체 2배다. 모든 자료는 기사용 DEV이며 독립 OOS가 아니다.

## 전후 경제표

표의 화살표는 정확한 부모 → FULL 후보다. KR2 부모는 KR1_FULL, SR1/BR1 부모는 각각 highvol V2 H12/breakout50 V2 H6, TPR1/TBR1 부모는 개별 native1h policy다.

| 후보/기간 | 진입 건수 | 승률% | 손익비 | PF | 종료 순손익 bps | 종료 전체cost2 bps |
|---|---:|---:|---:|---:|---:|---:|
| KR2/DEV2025 | 203→203 | 40.10→40.10 | 1.86→1.80 | 1.25→1.21 | 9,367.47→7,808.01 | 4,831.29→3,360.89 |
| KR2/SEEN2026 | 79→79 | 32.43→32.43 | 2.89→2.80 | 1.39→1.34 | 4,414.41→3,895.93 | 2,660.13→2,171.11 |
| SR1/DEV2025 | 246→228 | 43.62→34.82 | 1.17→1.66 | 0.91→0.89 | -5,897.47→-6,424.29 | -11,142.84→-11,639.92 |
| SR1/SEEN2026 | 89→79 | 46.43→40.54 | 1.64→2.68 | 1.43→1.83 | 5,838.40→10,583.89 | 3,941.69→8,729.67 |
| BR1/DEV2025 | 157→140 | 50.97→41.30 | 1.19→1.86 | 1.23→1.31 | 4,792.19→6,654.83 | 1,623.06→3,767.41 |
| BR1/SEEN2026 | 52→46 | 69.23→50.00 | 1.69→2.98 | 3.81→2.98 | 11,508.79→11,155.62 | 10,459.08→10,202.78 |
| TPR1/DEV2025 | 412→382 | 23.54→22.25 | 2.42→2.82 | 0.74→0.81 | -11,678.36→-8,206.03 | -19,918.36→-15,968.03 |
| TBR1/DEV2025 | 459→421 | 22.32→22.20 | 2.51→2.72 | 0.72→0.78 | -14,081.64→-10,139.40 | -23,261.64→-18,689.40 |

| 후보/기간 | marked DD bps | 최대 묶음 연패 횟수 | 일반/큰 승리 보존% | 노출 symbol-days | 미완결 건수 |
|---|---:|---:|---:|---:|---:|
| KR2/DEV2025 | 12,640.26→11,427.29 | 10→10 | 92.89/86.21 | 406.00→380.67 | 1→1 |
| KR2/SEEN2026 | 4,409.68→4,576.35 | 7→7 | 83.76/100.00 | 151.17→140.67 | 5→5 |
| SR1/DEV2025 | 13,409.63→18,096.17 | 8→10 | 58.93/85.73 | 486.50→562.17 | 3→4 |
| SR1/SEEN2026 | 5,347.55→4,890.46 | 5→9 | 62.06/99.30 | 174.67→206.33 | 5→5 |
| BR1/DEV2025 | 4,289.90→7,593.30 | 6→9 | 61.34/82.78 | 155.83→205.67 | 2→2 |
| BR1/SEEN2026 | 1,167.64→2,152.30 | 3→4 | 57.48/69.35 | 52.00→75.17 | 0→0 |
| TPR1/DEV2025 | 12,263.05→12,459.86 | 14→15 | 69.88/93.46 | 387.04→410.92 | 0→0 |
| TBR1/DEV2025 | 14,603.90→12,942.69 | 17→17 | 68.04/85.77 | 419.46→445.42 | 2→2 |

TPR1/TBR1 2026: **NOT_RUN — 적격 기사용 native1h 원천 미확보.** 4h 변환·새 수집 없음. 이는2025 비교를 차단하지 않았다.

A의 M/M2/KR1/KR2 및 모든 FIXED 상세는 ../TOP5_MECHANISM_A_20260907_V1/REPORT.md. B의 P/FIXED/FULL 상세는 아래에 있다.

## 보존 이득

- KR1: 기존 두 기간 cost2 흑자와 TRADEOFF/TRADEOFF 부분 개선분 보존. KR2가 이를 자동 교체하지 않는다.
- SR1: 2026 FULL 순증분 +4,745.49 bps, 최대 양의기여1거래 제외 +2,804.97 bps. 2025 악화도 함께 남긴다.
- BR1: 2025 FULL +1,862.64 bps, 최대1거래 제외 +539.72 bps. 직접 FIXED 효과는 −282.12 bps라 점유효과와 분리한다.
- TPR1: 2025 FULL 손실 +3,472.33 bps 감소. FIXED +3,010.52와 점유효과 +461.81 bps. 최대1거래 제외 후 +1,404.12 bps.
- TBR1: 2025 FULL 손실 +3,942.25 bps 감소. FIXED +3,719.42와 점유효과 +222.83 bps. 최대1거래 제외 후 +1,874.03 bps.

TPR1과 TBR1은 독립 성과가 아니다. 부모 309건, FULL 264건이 동일 경제 경로이며, 최대 개선 기여 +2,068.22 bps도 같은 ETH long 거래(진입 1746572400000, 1810.32)다. 두 lane의 개선분을 합산하지 않는다.

## 발생한 피해

- KR2: 두 기간 수익 반납 −1,559.46/−518.49 bps. 2025 큰 승리보존86.21%, 2026 DD+166.67 bps. KR1 수익 보존 수선 성공으로 판정하지 않는다.
- SR1: 2025 적자·DD 악화. 2026 DD 감소에도 최대 묶음 연패5→9, 일반 승리보존62.06%.
- BR1: 2025 DD+3,303.41 bps. 2026 고정진입 이득+2,429.01을 점유효과−2,782.18이 상쇄, FULL 순손익−353.17 bps. Q0와 다른 진입/달력이므로 bps로 Q0 교체 순위를 만들지 않는다.
- TPR1: 손실은 줄었지만 종료−8,206.03/cost2−15,968.03 bps. 일반 승리보존69.88%, DD+196.81 bps·연패14→15, 노출+23.875 symbol-days.
- TBR1: 종료−10,139.40/cost2−18,689.40 bps. 일반/큰 승리보존68.04%/85.77%, 노출+25.958 symbol-days. DD는−1,661.21 bps 개선, 연패17→17.
- Native 시간연장은 기존 SL 손실을 바꾸지 않는다. FIXED에서 SL 건수는 TPR1 307→307, TBR1 343→343. FULL의 SL 감소는 점유로 진입구성이 바뀐 결과를 포함한다.

## 남길 개발 분기

| lane | 실측 상태 | 남길 분기/기존 판정 |
|---|---|---|
| KR2 | 35번, 2025/2026 FIXED·FULL REJECT | KR1 기존 부분 개선분 유지, KR2 실패 증거 |
| SR1 | 36번, 2025 REJECT /2026 TRADEOFF | 2026 부분 개선과 2025 실패를 한 연구분기에 보존 |
| BR1 | 37번, 2025 FIXED REJECT·FULL TRADEOFF /2026 FULL REJECT | V2 별도 연구분기; Q0 원형·관측 보존 |
| TPR1 | 38번, 2025 FIXED·FULL REJECT;2026 NOT_RUN | 시간연장의 손실 감소 연구분기; 기존 Primary 판정 보존 |
| TBR1 | 39번, 2025 FIXED·FULL REJECT;2026 NOT_RUN | 시간연장의 손실 감소 연구분기; 기존 Broad 판정 보존 |

새 Survivor·공식 채택·운영 교체 없음. 유효한 일부 이득을 수익형 완성 또는 미래 우위로 주장하지 않는다. 기존 34건과 모든 판정, Q0/QF1 및 연구 관측, G5B·실주문 권한은 보존한다.

## 실제 검증 기록

- A 동결6818273 → 최초 실행35/36/37 → PR1202 결과-head CI34102262199 PASS → merge0df014a → master run34102599510 exact reproduction PASS. A 완료 후 추가 감사·경제 재실행 없음.
- B 동결67c7d09, SPEC acdb9a25d06cdeb1c2e3a0111ba4b814d9455fbf244e260bc6dd0b891a21bf5d → 최초 TPR1 2026-09-07T08:58:44.551324Z → TBR1. 원형 완결412/457건과 native raw intents1555/3386건 exact parity PASS.
- B 결과 전26개 합성/native 의존 테스트 PASS. pre-registration CI34103468331 및 함께 실행된7개 workflow PASS. 경계 SL/TP 가격 proxy는 비용과 함께 보존하며 timeout 경계는 미체결 마지막종가 평가다. trailing 미구현·실제 체결시각 상한 한계 유지.
- A/B 경제 담당1명, 읽기 전용 검토1명. 동일 후보 시세 중복 병렬 실행0. 결과 후규칙·코드·기간·판정수정0. 이미 완료한 경제를 감사 명목으로 반복하지 않음.
- B 최종CI·병합·master exact reproduction은 PR1203 완료 gate이며 최종 작업 receipt로 추적한다.

## B P/FIXED/FULL 상세

### TPR1

| 지표 | P | FIXED | FULL |
|---|---:|---:|---:|
| PF | 0.74 | 0.81 | 0.81 |
| closed_T | 412.00 | 412.00 | 382.00 |
| closed_cost2x_net_bps | -19,918.36 | -17,039.84 | -15,968.03 |
| closed_cost_bps | 8,240.00 | 8,372.00 | 7,762.00 |
| closed_fee_bps | 4,120.00 | 4,120.00 | 3,820.00 |
| closed_funding_bps | 1,147.00 | 1,330.00 | 1,212.00 |
| closed_gross_bps | -3,438.36 | -295.84 | -444.03 |
| closed_net_bps | -11,678.36 | -8,667.84 | -8,206.03 |
| entries_T | 412.00 | 412.00 | 382.00 |
| entries_per_30_days | 32.96 | 32.96 | 30.56 |
| exposure_symbol_days | 387.04 | 448.08 | 410.92 |
| grouped_max_loss_trade_sum_bps | 3,242.32 | 2,954.48 | 2,954.48 |
| marked_DD_trade_sum_bps | 12,263.05 | 13,602.86 | 12,459.86 |
| max_completed_recovery_days | 12.00 | 12.00 | 12.00 |
| max_simultaneous_symbols | 2.00 | 2.00 | 2.00 |
| mean_loss_bps | -144.93 | -144.93 | -142.81 |
| mean_win_bps | 350.24 | 381.27 | 402.44 |
| net_expectancy_bps_per_closed_trade | -28.35 | -21.04 | -21.48 |
| open_T | 0.00 | 0.00 | 0.00 |
| open_net_mark_bps_hypothetical | 0.00 | 0.00 | 0.00 |
| open_underwater_days | 356.33 | 356.33 | 356.33 |
| realized_payoff | 2.42 | 2.63 | 2.82 |
| terminal_cost2x_net_bps_hypothetical | -19,918.36 | -17,039.84 | -15,968.03 |
| terminal_net_bps_hypothetical | -11,678.36 | -8,667.84 | -8,206.03 |
| win_rate | 0.24 | 0.24 | 0.22 |

```json
{
  "parent_parity": {
    "closed_exact_parity_T": 412,
    "original_closed_ledger_unchanged": true,
    "raw_intent_exact_parity_T": 1555,
    "restored_censored_T": 0,
    "tail_not_multiple_live_positions": true
  },
  "terminal_cost_components": {
    "FIXED": {
      "cost2x_net_bps": -17039.83912172748,
      "cost_bps": 8372.0,
      "fee_bps": 4120.0,
      "frozen_floor_reserve_bps": 1686.0,
      "funding_bps": 1330.0,
      "gross_bps": -295.83912172748177,
      "impact_bps": 824.0,
      "net_bps": -8667.839121727482,
      "slippage_bps": 0.0,
      "spread_bps": 412.0
    },
    "FULL": {
      "cost2x_net_bps": -15968.025438737674,
      "cost_bps": 7762.0,
      "fee_bps": 3820.0,
      "frozen_floor_reserve_bps": 1584.0,
      "funding_bps": 1212.0,
      "gross_bps": -444.0254387376732,
      "impact_bps": 764.0,
      "net_bps": -8206.025438737674,
      "slippage_bps": 0.0,
      "spread_bps": 382.0
    },
    "P": {
      "cost2x_net_bps": -19918.359577413252,
      "cost_bps": 8240.0,
      "fee_bps": 4120.0,
      "frozen_floor_reserve_bps": 1737.0,
      "funding_bps": 1147.0,
      "gross_bps": -3438.3595774132505,
      "impact_bps": 824.0,
      "net_bps": -11678.35957741325,
      "slippage_bps": 0.0,
      "spread_bps": 412.0
    }
  },
  "origin_transitions": {
    "ABSENT_C": {
      "T": 40,
      "delta_bps": {
        "cost2x_net_bps": -4193.969770192937,
        "cost_bps": 802.0,
        "fee_bps": 400.0,
        "frozen_floor_reserve_bps": 195.0,
        "funding_bps": 87.0,
        "gross_bps": -2589.969770192937,
        "impact_bps": 80.0,
        "net_bps": -3391.969770192937,
        "slippage_bps": 0.0,
        "spread_bps": 40.0
      }
    },
    "C_ABSENT": {
      "T": 70,
      "delta_bps": {
        "cost2x_net_bps": 5635.445215467299,
        "cost_bps": -1400.0,
        "fee_bps": -700.0,
        "frozen_floor_reserve_bps": -307.0,
        "funding_bps": -183.0,
        "gross_bps": 2835.4452154672995,
        "impact_bps": -140.0,
        "net_bps": 4235.445215467299,
        "slippage_bps": 0.0,
        "spread_bps": -70.0
      }
    },
    "C_C": {
      "T": 342,
      "delta_bps": {
        "cost2x_net_bps": 2508.858693401215,
        "cost_bps": 120.0,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": -41.0,
        "funding_bps": 161.0,
        "gross_bps": 2748.858693401215,
        "impact_bps": 0.0,
        "net_bps": 2628.858693401215,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      }
    }
  },
  "ordinary_winners": {
    "T": 87,
    "additional_loss_after_winner_bps": 0.0,
    "capped_terminal_preserved_bps_hypothetical": 16190.95552694621,
    "capped_terminal_retention_hypothetical": 0.6988217157865757,
    "child_signed_terminal_bps": 20336.606515974494,
    "parent_positive_bps": 23168.93588334199,
    "profit_cut_bps": 6977.98035639578,
    "realized_capped_retention_lower": 0.6988217157865757,
    "realized_capped_retention_upper": 0.6988217157865757,
    "signed_winner_deterioration_bps": 6977.98035639578,
    "winner_removed_T": 15,
    "winner_to_loss_T": 0,
    "winner_to_loss_origins": []
  },
  "large_winners": {
    "T": 10,
    "additional_loss_after_winner_bps": 0.0,
    "capped_terminal_preserved_bps_hypothetical": 10097.26061401309,
    "capped_terminal_retention_hypothetical": 0.9345719626088341,
    "child_signed_terminal_bps": 12731.00785538119,
    "parent_positive_bps": 10804.155290328677,
    "profit_cut_bps": 706.8946763155868,
    "realized_capped_retention_lower": 0.9345719626088341,
    "realized_capped_retention_upper": 0.9345719626088341,
    "signed_winner_deterioration_bps": 706.8946763155868,
    "winner_removed_T": 0,
    "winner_to_loss_T": 0,
    "winner_to_loss_origins": []
  },
  "increment_by_symbol": {
    "BTC-USDT": 705.9211022446505,
    "ETH-USDT": 2766.4130364309276
  },
  "increment_by_month": {
    "2024-12": 94.97678425759705,
    "2025-01": -408.5733705383154,
    "2025-02": -292.5079073981359,
    "2025-03": 156.38118710792318,
    "2025-04": -60.52731929943249,
    "2025-05": 1779.2273834484404,
    "2025-06": -561.92449984567,
    "2025-07": 1070.9364438502148,
    "2025-08": 604.0359617037664,
    "2025-09": 829.7953119736101,
    "2025-10": -36.08999980404231,
    "2025-11": 455.42478771617294,
    "2025-12": -158.82062449655098
  },
  "largest_positive_origin": {
    "child": {
      "cost2x_net_bps": 4210.671792832207,
      "cost_bps": 26.0,
      "fee_bps": 10.0,
      "frozen_floor_reserve_bps": 0.0,
      "funding_bps": 13.0,
      "gross_bps": 4262.671792832207,
      "impact_bps": 2.0,
      "net_bps": 4236.671792832207,
      "slippage_bps": 0.0,
      "spread_bps": 1.0
    },
    "child_hold_ms": 349200000,
    "delta": {
      "cost2x_net_bps": 2062.218922621415,
      "cost_bps": 6.0,
      "fee_bps": 0.0,
      "frozen_floor_reserve_bps": 0.0,
      "funding_bps": 6.0,
      "gross_bps": 2074.218922621415,
      "impact_bps": 0.0,
      "net_bps": 2068.218922621415,
      "slippage_bps": 0.0,
      "spread_bps": 0.0
    },
    "entry_month": "2025-05",
    "origin_key": "ee0ccaf4b4b699c6bb70368dced72933ceb6f130b4f538c8a23d644afb9b02b0",
    "parent": {
      "cost2x_net_bps": 2148.452870210792,
      "cost_bps": 20.0,
      "fee_bps": 10.0,
      "frozen_floor_reserve_bps": 0.0,
      "funding_bps": 7.0,
      "gross_bps": 2188.452870210792,
      "impact_bps": 2.0,
      "net_bps": 2168.452870210792,
      "slippage_bps": 0.0,
      "spread_bps": 1.0
    },
    "parent_hold_ms": 176400000,
    "parent_large_winner": true,
    "parent_winner": true,
    "signal_ts": 1746572400000,
    "symbol": "ETH-USDT",
    "transition": "C_C",
    "winner_removed": false,
    "winner_to_loss": false
  },
  "net_increment_without_largest_positive": 1404.1152160541624,
  "fixed_full_bridge": {
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 2878.5204556857716,
      "full_occupancy_remainder": 1071.8136829898067,
      "full_total_effect": 3950.3341386755783
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 132.0,
      "full_occupancy_remainder": -610.0,
      "full_total_effect": -478.0
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -300.0,
      "full_total_effect": -300.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -51.0,
      "full_occupancy_remainder": -102.0,
      "full_total_effect": -153.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 183.0,
      "full_occupancy_remainder": -118.0,
      "full_total_effect": 65.0
    },
    "gross_bps": {
      "fixed_path_or_filter_effect": 3142.520455685769,
      "full_occupancy_remainder": -148.18631701019143,
      "full_total_effect": 2994.3341386755774
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -60.0,
      "full_total_effect": -60.0
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 3010.520455685768,
      "full_occupancy_remainder": 461.8136829898085,
      "full_total_effect": 3472.3341386755765
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -30.0,
      "full_total_effect": -30.0
    }
  },
  "uncertainty": {
    "FIXED": {
      "N_effective": null,
      "approximate_calendar_blocks": 12.533333333333333,
      "block_days": 30,
      "calendar_days": 376,
      "calendar_last_day": "2025-12-29",
      "calendar_start": "2024-12-19",
      "child_marked_delta_sum_bps": -8667.839121727482,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -7.103580067523046,
        24.03045649655965
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -2670.9461053886653,
        9035.451642706428
      ],
      "child_minus_parent_marked_delta_sum_bps": 3010.520455685768,
      "child_minus_parent_mean_daily_bps": 8.006703339589809,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": -11678.35957741325,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    },
    "FULL": {
      "N_effective": null,
      "approximate_calendar_blocks": 12.533333333333333,
      "block_days": 30,
      "calendar_days": 376,
      "calendar_last_day": "2025-12-29",
      "calendar_start": "2024-12-19",
      "child_marked_delta_sum_bps": -8206.025438737674,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -4.629192299529682,
        24.612382439482698
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1740.5763046231602,
        9254.255797245494
      ],
      "child_minus_parent_marked_delta_sum_bps": 3472.3341386755765,
      "child_minus_parent_mean_daily_bps": 9.234931219881853,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": -11678.35957741325,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    }
  }
}
```

### TBR1

| 지표 | P | FIXED | FULL |
|---|---:|---:|---:|
| PF | 0.72 | 0.79 | 0.78 |
| closed_T | 457.00 | 457.00 | 419.00 |
| closed_cost2x_net_bps | -23,611.76 | -20,045.34 | -19,039.52 |
| closed_cost_bps | 9,140.00 | 9,293.00 | 8,510.00 |
| closed_fee_bps | 4,570.00 | 4,570.00 | 4,190.00 |
| closed_funding_bps | 1,244.00 | 1,454.00 | 1,318.00 |
| closed_gross_bps | -5,331.76 | -1,459.34 | -2,019.52 |
| closed_net_bps | -14,471.76 | -10,752.34 | -10,529.52 |
| entries_T | 459.00 | 459.00 | 421.00 |
| entries_per_30_days | 36.72 | 36.72 | 33.68 |
| exposure_symbol_days | 419.46 | 488.92 | 445.42 |
| grouped_max_loss_trade_sum_bps | 3,657.90 | 3,366.05 | 3,366.05 |
| marked_DD_trade_sum_bps | 14,603.90 | 14,352.85 | 12,942.69 |
| max_completed_recovery_days | 15.00 | 12.00 | 12.00 |
| max_simultaneous_symbols | 2.00 | 2.00 | 2.00 |
| mean_loss_bps | -145.54 | -145.83 | -144.88 |
| mean_win_bps | 364.64 | 402.13 | 394.65 |
| net_expectancy_bps_per_closed_trade | -31.67 | -23.53 | -25.13 |
| open_T | 2.00 | 2.00 | 2.00 |
| open_net_mark_bps_hypothetical | 390.12 | 390.12 | 390.12 |
| open_underwater_days | 356.33 | 356.33 | 356.33 |
| realized_payoff | 2.51 | 2.76 | 2.72 |
| terminal_cost2x_net_bps_hypothetical | -23,261.64 | -19,695.23 | -18,689.40 |
| terminal_net_bps_hypothetical | -14,081.64 | -10,362.23 | -10,139.40 |
| win_rate | 0.22 | 0.22 | 0.22 |

```json
{
  "parent_parity": {
    "closed_exact_parity_T": 457,
    "original_closed_ledger_unchanged": true,
    "raw_intent_exact_parity_T": 3386,
    "restored_censored_T": 2,
    "tail_not_multiple_live_positions": true
  },
  "terminal_cost_components": {
    "FIXED": {
      "cost2x_net_bps": -19695.226124118584,
      "cost_bps": 9333.0,
      "fee_bps": 4590.0,
      "frozen_floor_reserve_bps": 1908.0,
      "funding_bps": 1458.0,
      "gross_bps": -1029.2261241185852,
      "impact_bps": 918.0,
      "net_bps": -10362.226124118584,
      "slippage_bps": 0.0,
      "spread_bps": 459.0
    },
    "FULL": {
      "cost2x_net_bps": -18689.39777170684,
      "cost_bps": 8550.0,
      "fee_bps": 4210.0,
      "frozen_floor_reserve_bps": 1755.0,
      "funding_bps": 1322.0,
      "gross_bps": -1589.3977717068399,
      "impact_bps": 842.0,
      "net_bps": -10139.39777170684,
      "slippage_bps": 0.0,
      "spread_bps": 421.0
    },
    "P": {
      "cost2x_net_bps": -23261.64292891933,
      "cost_bps": 9180.0,
      "fee_bps": 4590.0,
      "frozen_floor_reserve_bps": 1965.0,
      "funding_bps": 1248.0,
      "gross_bps": -4901.64292891933,
      "impact_bps": 918.0,
      "net_bps": -14081.64292891933,
      "slippage_bps": 0.0,
      "spread_bps": 459.0
    }
  },
  "origin_transitions": {
    "ABSENT_C": {
      "T": 55,
      "delta_bps": {
        "cost2x_net_bps": -4868.66622658407,
        "cost_bps": 1104.0,
        "fee_bps": 550.0,
        "frozen_floor_reserve_bps": 238.0,
        "funding_bps": 151.0,
        "gross_bps": -2660.66622658407,
        "impact_bps": 110.0,
        "net_bps": -3764.66622658407,
        "slippage_bps": 0.0,
        "spread_bps": 55.0
      }
    },
    "C_ABSENT": {
      "T": 93,
      "delta_bps": {
        "cost2x_net_bps": 6421.712383988005,
        "cost_bps": -1860.0,
        "fee_bps": -930.0,
        "frozen_floor_reserve_bps": -404.0,
        "funding_bps": -247.0,
        "gross_bps": 2701.7123839880046,
        "impact_bps": -186.0,
        "net_bps": 4561.712383988005,
        "slippage_bps": 0.0,
        "spread_bps": -93.0
      }
    },
    "C_C": {
      "T": 364,
      "delta_bps": {
        "cost2x_net_bps": 3019.1989998085555,
        "cost_bps": 126.0,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": -44.0,
        "funding_bps": 170.0,
        "gross_bps": 3271.1989998085555,
        "impact_bps": 0.0,
        "net_bps": 3145.1989998085555,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      }
    },
    "O_O": {
      "T": 2,
      "delta_bps": {
        "cost2x_net_bps": 0.0,
        "cost_bps": 0.0,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": 0.0,
        "funding_bps": 0.0,
        "gross_bps": 0.0,
        "impact_bps": 0.0,
        "net_bps": 0.0,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      }
    }
  },
  "ordinary_winners": {
    "T": 91,
    "additional_loss_after_winner_bps": 0.0,
    "capped_terminal_preserved_bps_hypothetical": 17079.2315562689,
    "capped_terminal_retention_hypothetical": 0.6803717260780635,
    "child_signed_terminal_bps": 21396.703786445152,
    "parent_positive_bps": 25102.79440140828,
    "profit_cut_bps": 8023.562845139379,
    "realized_capped_retention_lower": 0.6803717260780635,
    "realized_capped_retention_upper": 0.6803717260780635,
    "signed_winner_deterioration_bps": 8023.562845139379,
    "winner_removed_T": 17,
    "winner_to_loss_T": 0,
    "winner_to_loss_origins": []
  },
  "large_winners": {
    "T": 11,
    "additional_loss_after_winner_bps": 0.0,
    "capped_terminal_preserved_bps_hypothetical": 10370.05598738757,
    "capped_terminal_retention_hypothetical": 0.8577027753442614,
    "child_signed_terminal_bps": 13528.149331260447,
    "parent_positive_bps": 12090.50067865908,
    "profit_cut_bps": 1720.4446912715098,
    "realized_capped_retention_lower": 0.8577027753442614,
    "realized_capped_retention_upper": 0.8577027753442614,
    "signed_winner_deterioration_bps": 1720.4446912715098,
    "winner_removed_T": 1,
    "winner_to_loss_T": 0,
    "winner_to_loss_origins": []
  },
  "increment_by_symbol": {
    "BTC-USDT": -229.60036322436173,
    "ETH-USDT": 4171.845520436854
  },
  "increment_by_month": {
    "2024-12": 204.7859011992289,
    "2025-01": -359.4217584587874,
    "2025-02": -383.22085449109727,
    "2025-03": 392.4945017204917,
    "2025-04": 11.175197103264026,
    "2025-05": 1758.5524618046165,
    "2025-06": -538.6449441793478,
    "2025-07": 955.9039890935501,
    "2025-08": 1082.082907908624,
    "2025-09": 334.157489811901,
    "2025-10": 547.9772212811588,
    "2025-11": 41.54011616948548,
    "2025-12": -105.13707175059716
  },
  "largest_positive_origin": {
    "child": {
      "cost2x_net_bps": 4210.671792832207,
      "cost_bps": 26.0,
      "fee_bps": 10.0,
      "frozen_floor_reserve_bps": 0.0,
      "funding_bps": 13.0,
      "gross_bps": 4262.671792832207,
      "impact_bps": 2.0,
      "net_bps": 4236.671792832207,
      "slippage_bps": 0.0,
      "spread_bps": 1.0
    },
    "child_hold_ms": 349200000,
    "delta": {
      "cost2x_net_bps": 2062.218922621415,
      "cost_bps": 6.0,
      "fee_bps": 0.0,
      "frozen_floor_reserve_bps": 0.0,
      "funding_bps": 6.0,
      "gross_bps": 2074.218922621415,
      "impact_bps": 0.0,
      "net_bps": 2068.218922621415,
      "slippage_bps": 0.0,
      "spread_bps": 0.0
    },
    "entry_month": "2025-05",
    "origin_key": "f5990697fab23c4df5aed33cca05e710612c67720ec4a1475b47d6f8c945a7a3",
    "parent": {
      "cost2x_net_bps": 2148.452870210792,
      "cost_bps": 20.0,
      "fee_bps": 10.0,
      "frozen_floor_reserve_bps": 0.0,
      "funding_bps": 7.0,
      "gross_bps": 2188.452870210792,
      "impact_bps": 2.0,
      "net_bps": 2168.452870210792,
      "slippage_bps": 0.0,
      "spread_bps": 1.0
    },
    "parent_hold_ms": 176400000,
    "parent_large_winner": true,
    "parent_winner": true,
    "signal_ts": 1746572400000,
    "symbol": "ETH-USDT",
    "transition": "C_C",
    "winner_removed": false,
    "winner_to_loss": false
  },
  "net_increment_without_largest_positive": 1874.0262345910755,
  "fixed_full_bridge": {
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 3566.416804800745,
      "full_occupancy_remainder": 1005.8283524117433,
      "full_total_effect": 4572.245157212488
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 153.0,
      "full_occupancy_remainder": -783.0,
      "full_total_effect": -630.0
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -380.0,
      "full_total_effect": -380.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": -57.0,
      "full_occupancy_remainder": -153.0,
      "full_total_effect": -210.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 210.0,
      "full_occupancy_remainder": -136.0,
      "full_total_effect": 74.0
    },
    "gross_bps": {
      "fixed_path_or_filter_effect": 3872.416804800745,
      "full_occupancy_remainder": -560.1716475882547,
      "full_total_effect": 3312.24515721249
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -76.0,
      "full_total_effect": -76.0
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 3719.416804800745,
      "full_occupancy_remainder": 222.82835241174507,
      "full_total_effect": 3942.24515721249
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -38.0,
      "full_total_effect": -38.0
    }
  },
  "uncertainty": {
    "FIXED": {
      "N_effective": null,
      "approximate_calendar_blocks": 12.533333333333333,
      "block_days": 30,
      "calendar_days": 376,
      "calendar_last_day": "2025-12-29",
      "calendar_start": "2024-12-19",
      "child_marked_delta_sum_bps": -10362.226124118584,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -6.402132764125569,
        27.48314569258552
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -2407.2019193112137,
        10333.662780412156
      ],
      "child_minus_parent_marked_delta_sum_bps": 3719.416804800745,
      "child_minus_parent_mean_daily_bps": 9.892065970214748,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": -14081.64292891933,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    },
    "FULL": {
      "N_effective": null,
      "approximate_calendar_blocks": 12.533333333333333,
      "block_days": 30,
      "calendar_days": 376,
      "calendar_last_day": "2025-12-29",
      "calendar_start": "2024-12-19",
      "child_marked_delta_sum_bps": -10139.39777170684,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -4.372398653173437,
        26.073472673745464
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1644.021893593212,
        9803.625725328295
      ],
      "child_minus_parent_marked_delta_sum_bps": 3942.24515721249,
      "child_minus_parent_mean_daily_bps": 10.484694567054495,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": -14081.64292891933,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    }
  }
}
```

