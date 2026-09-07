# PR1203 이후 집중 수선 — 실제 경제 결과

동일 명목 trade-bps. 계좌 수익률 아님. 종료 net와 전체cost2는 미완결 가상 전체 비용 평가를 포함한다. 모든 자료는 기사용 DEV, 독립 OOS 아님.

## 실제 수선 전후 경제표

부모→FULL: KR3 부모 KR1_FULL; BR2 부모 BR1_FULL. M/M2/KR2/V2 및 FIXED 상세는 뒤 표에 모두 병기한다.

| 후보/기간 | signal | entry | closed/open | 승률% | 손익비 | PF | 종료 net | 전체cost2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| KR3/DEV2025 | 379→379 | 203→203 | 202/1→202/1 | 40.10→41.09 | 1.86→1.82 | 1.25→1.27 | 9,367.47→10,265.00 | 4,831.29→5,744.23 |
| KR3/SEEN2026 | 126→126 | 79→79 | 74/5→75/4 | 32.43→33.33 | 2.89→2.85 | 1.39→1.43 | 4,414.41→4,746.58 | 2,660.13→3,002.13 |
| BR2/DEV2025 | 283→283 | 140→142 | 138/2→140/2 | 41.30→41.43 | 1.86→1.79 | 1.31→1.26 | 6,654.83→5,923.84 | 3,767.41→2,995.04 |
| BR2/SEEN2026 | 90→90 | 46→47 | 46/0→47/0 | 50.00→51.06 | 2.98→3.14 | 2.98→3.28 | 11,155.62→11,923.29 | 10,202.78→10,948.99 |

| 후보/기간 | marked DD | 최대 묶음 연패 | 연패 손실금액 | 일반/큰 승리 보존% | 노출symbol-days | 최대1거래 제외 순증분 |
|---|---:|---:|---:|---:|---:|---:|
| KR3/DEV2025 | 12,640.26→11,727.79 | 10→10 | 3,835.25→3,835.25 | 97.13/100.00 | 406.00→399.00 | 421.01 |
| KR3/SEEN2026 | 4,409.68→4,093.69 | 7→7 | 2,665.35→2,665.35 | 99.47/100.00 | 151.17→148.17 | -42.68 |
| BR2/DEV2025 | 7,593.30→7,593.30 | 9→9 | 3,296.71→3,296.71 | 100.00/100.00 | 205.67→208.67 | -885.44 |
| BR2/SEEN2026 | 2,152.30→1,620.24 | 4→4 | 975.02→886.38 | 100.00/100.00 | 75.17→78.17 | 372.29 |

## TrendRider 역사→현재 연결

| 최초 차이/영향 | Primary | Broad |
|---|---|---|
| 역사 완결/승리/순손익 |16/13/+23,297.77 |30/21/+34,960.58 |
| 현재 native 부모 완결/승리 |412/97 |457/102 (+미완결2) |
| 역사 동일종목 보유중 추가행 / 최대중첩 |13/16 · 최대8 |25/30 · 최대12 |
| 역사 저장행에만 현점유 적용 |5건/4승/+4,732.61 |6건/4승/+4,812.37 |
| 전체 같은입력 시장재현 |UNRESOLVED |UNRESOLVED |

Primary는 선별 모집단부터 다르고, 최초 입증된 실행 의미 차이는 과거 evaluator의 점유·cooldown 미적용이다. 현재는 이미 적용돼 같은 수선 반복0. 역사2026과 현DEV2025는 달력도 다르며 당시 raw/warmup/전체신호/funding 원천 부재로 전체 차이 귀속은 미확정이다. 위5/6건은 저장행 부분집합 산술일 뿐 수정 baseline이나 실현가능 전체 수익이 아니다. 원래16/30 계산 자체는 일치하며 현재 부모 승률 저하를 TPR1/TBR1 청산 변경 탓으로 돌리지 않는다. 상세 원문 SHA·SL421개 합집합·분류 한계는 TRENDRIDER_AND_SUPERTREND.md 및 TRENDRIDER_STORED_ROWS.json에 있다.

## 보존 이득

- KR3: KR1의 양기간 비용후 흑자를 유지하며 종료 +897.52/+332.17, cost2 +912.93/+342.00, DD −912.47/−315.99 bps. 큰 승리100% 보존. FIXED/FULL 동일, 진입집합변화0. 기존 KR1/M/M2/KR2는 덮어쓰지 않는다.
- BR2: 2026 종료 +767.67 / 전체cost2 +746.21 / DD −532.06 bps. BR1 일반·큰 승리100% 보존. 2026 수익 증가 대부분은 후속 손실 두 거래가 새 점유로 빠진 효과이며 새로운 3거래의 합계는 +21.69뿐이다.
- BR2의2025도 BR1보다악화했지만 V2보다 종료 +1,131.65/cost2 +1,371.98 bps인 부분이 남는다. 2026 V2보다 종료+414.50이나 DD는+452.60 악화다. 서로다른부모대비결과를혼동하지않는다.

## 발생 피해와 불확실성

- KR3: 평균 손익비1.862→1.825/2.888→2.853으로 소폭하락. 2025 일반승리 이익756.00bps 삭감, 승리→손실1건(추가손실6.25). 일반승리보존97.13%/99.47%. 2026 최대기여HYPE 한거래(+374.85)를빼면순증분−42.68, O→C전환과마지막평가시점에의존한다. 두기간미완결1/4 및 일별차이95%하한미충족으로FIXED/FULL 모두TRADEOFF, formal PASS아님.
- BR2: 2025 종료−730.99/cost2−772.37, 새3거래−885.44를기존손실1거래제외+154.45가일부완화. DD는동일수준, 노출양기간+3symbol-days. 2025 REJECT,2026 FULL TRADEOFF. FIXED는원래BR1와완전히동일하여increment gate미충족 REJECT. 점유수선에대한기준을사후완화하지않는다.
- BR2는이미완료된실제상한close뒤에서만새nextopen진입. 종가→다음시가 가격차·새보유구간·이후signal차단·추가비용이실제로달라진다. 같은포지션을이름만바꾸어성과로세지않는다. 부모의동일시가가정으로동일수량이라고주장하지않으며고정명목연구노출이다.
- 모든집단분석은기존개발자료의설계단서. 후보선택2개,숫자스윕0,결과후규칙변경0. 독립검증·공식채택·운영승격0.

## 남길 분기와 다음 판단

| 번호 | 분기 | 실제판정 | 보존/다음판단 |
|---|---|---|---|
|40|KR3|2025/2026 FIXED·FULL TRADEOFF|KR1 위의누적부분개선으로보존.2026단일거래·미완결의존을명시 |
|41|BR2|2025REJECT /2026FULL TRADEOFF;FIXED양기간REJECT|V2·BR1와별도보존.2025피해를감춘자동교체없음 |
|—|TrendRider bridge|저장행/코드차이검산완료;같은자료전체재현UNRESOLVED|현재입증된추가구현결함0.정확관리상태/체결계약은미정,새TR실측0 |
|—|Supertrend|저장분해완료;새실측0|SR12026개선보존.원형진입및기존H12보유손실구조진단이우선,실행가능새판별축미확정 |
|—|Q0/G5B|보존|자격심사·관측리셋·formal경계추가0 |

## 실제 검증 기록

- 동결762b4e8d8a49f1a0949138040dd40f15296bcc64 → 최초KR3/BR2순서. ATTEMPT/receipt에실행시각·PID·후보40/41·sourceSHA저장. 12개관련합성시험PASS,사전CI34110641617및함께실행된7개workflowPASS.
- 첫KR3프로세스요청이transport disconnected로실행되지않았고ATTEMPT와로그부재를확인한뒤최초실행. 경제오류실행0. 최초진단출력디렉터리누락은파일쓰기전오류로수선;시장replay없음.
- 이전39개후보재실행0,신규baseline시장재현0,신규후보2×2기간×2모드=8경로묶음. 실제기존helper내참조예약계산은후보에필요한인과예약이며원장에기록된다.
- 역사연결은읽기전용검산1묶음,SL봉이후HLC로손절전MFE생성0,공통Primary/Broad거래중복합산0.
- 경제실행자1명/읽기전용검토1명. 실제확인된결과전BR2cap시가오인수정과회귀시험을포함. 결과후코드/기간/종목/판정변경0.
- PR1204최종head CI·병합·master exact reproduction을완료 gate로사용. 그실행ID와완료시각은PR completion receipt에추가한다. 여기의기존경제결과를별도감사명목으로다시실행하지않는다.

## 부모 / 보존 작업본 / FIXED / FULL 전체 지표

### KR3 DEV2025

| 지표 | FIXED | FULL | KR1_FULL | KR2_FULL | M | M2 |
|---|---:|---:|---:|---:|---:|---:|
| PF | 1.27 | 1.27 | 1.25 | 1.21 | 1.15 | 1.16 |
| closed_T | 202.00 | 202.00 | 202.00 | 202.00 | 202.00 | 202.00 |
| closed_cost2x_net_bps | 5,840.96 | 5,840.96 | 4,928.02 | 3,457.62 | 1,749.89 | 1,945.92 |
| closed_cost_bps | 4,500.77 | 4,500.77 | 4,516.18 | 4,427.12 | 4,272.32 | 4,227.90 |
| closed_fee_bps | 2,020.00 | 2,020.00 | 2,020.00 | 2,020.00 | 2,020.00 | 2,020.00 |
| closed_funding_bps | 1,422.86 | 1,422.86 | 1,442.27 | 1,343.82 | 1,324.82 | 1,121.43 |
| closed_gross_bps | 14,842.50 | 14,842.50 | 13,960.38 | 12,311.87 | 10,294.53 | 10,401.72 |
| closed_net_bps | 10,341.73 | 10,341.73 | 9,444.20 | 7,884.74 | 6,022.21 | 6,173.82 |
| entries_T | 203.00 | 203.00 | 203.00 | 203.00 | 203.00 | 203.00 |
| entries_per_30_days | 16.24 | 16.24 | 16.24 | 16.24 | 16.24 | 16.24 |
| exposure_symbol_days | 399.00 | 399.00 | 406.00 | 380.67 | 372.67 | 315.83 |
| grouped_max_loss_trade_sum_bps | 3,835.25 | 3,835.25 | 3,835.25 | 3,835.25 | 4,782.53 | 3,981.70 |
| marked_DD_trade_sum_bps | 11,727.79 | 11,727.79 | 12,640.26 | 11,427.29 | 11,605.83 | 9,599.81 |
| max_completed_recovery_days | 63.00 | 63.00 | 63.00 | 58.00 | 64.00 | 64.00 |
| max_simultaneous_symbols | 6.00 | 6.00 | 6.00 | 6.00 | 7.00 | 6.00 |
| mean_loss_bps | -318.58 | -318.58 | -316.59 | -316.40 | -375.58 | -326.33 |
| mean_win_bps | 581.35 | 581.35 | 589.52 | 569.98 | 460.02 | 502.32 |
| net_expectancy_bps_per_closed_trade | 51.20 | 51.20 | 46.75 | 39.03 | 29.81 | 30.56 |
| open_T | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| open_net_mark_bps_hypothetical | -76.73 | -76.73 | -76.73 | -76.73 | -76.73 | -76.73 |
| open_underwater_days | 101.33 | 101.33 | 137.33 | 101.33 | 101.33 | 101.33 |
| realized_payoff | 1.82 | 1.82 | 1.86 | 1.80 | 1.22 | 1.54 |
| terminal_cost2x_net_bps_hypothetical | 5,744.23 | 5,744.23 | 4,831.29 | 3,360.89 | 1,653.16 | 1,849.19 |
| terminal_net_bps_hypothetical | 10,265.00 | 10,265.00 | 9,367.47 | 7,808.01 | 5,945.48 | 6,097.09 |
| win_rate | 0.41 | 0.41 | 0.40 | 0.40 | 0.49 | 0.43 |

```json
{
  "terminal_all_cost_components": {
    "FIXED": {
      "cost2x_net_bps": 5744.2275135445,
      "cost_bps": 4520.768285289946,
      "fee_bps": 2030.0,
      "frozen_floor_reserve_bps": 316.8597986694352,
      "funding_bps": 1424.27,
      "gross_bps": 14785.764084124392,
      "impact_bps": 422.8421035575453,
      "net_bps": 10264.995798834447,
      "slippage_bps": 0.0,
      "spread_bps": 326.79638306296556
    },
    "FULL": {
      "cost2x_net_bps": 5744.2275135445,
      "cost_bps": 4520.768285289946,
      "fee_bps": 2030.0,
      "frozen_floor_reserve_bps": 316.8597986694352,
      "funding_bps": 1424.27,
      "gross_bps": 14785.764084124392,
      "impact_bps": 422.8421035575453,
      "net_bps": 10264.995798834447,
      "slippage_bps": 0.0,
      "spread_bps": 326.79638306296556
    },
    "KR1_FULL": {
      "cost2x_net_bps": 4831.29313093191,
      "cost_bps": 4536.178285289946,
      "fee_bps": 2030.0,
      "frozen_floor_reserve_bps": 312.8597986694352,
      "funding_bps": 1443.68,
      "gross_bps": 13903.649701511802,
      "impact_bps": 422.8421035575453,
      "net_bps": 9367.471416221857,
      "slippage_bps": 0.0,
      "spread_bps": 326.79638306296556
    },
    "KR2_FULL": {
      "cost2x_net_bps": 3360.8868772278884,
      "cost_bps": 4447.124500357505,
      "fee_bps": 2030.0,
      "frozen_floor_reserve_bps": 322.2560137369938,
      "funding_bps": 1345.23,
      "gross_bps": 12255.135877942897,
      "impact_bps": 422.8421035575453,
      "net_bps": 7808.011377585393,
      "slippage_bps": 0.0,
      "spread_bps": 326.79638306296556
    },
    "M": {
      "cost2x_net_bps": 1653.1552960356034,
      "cost_bps": 4292.321334003939,
      "fee_bps": 2030.0,
      "frozen_floor_reserve_bps": 186.45284738342855,
      "funding_bps": 1326.23,
      "gross_bps": 10237.797964043482,
      "impact_bps": 422.8421035575453,
      "net_bps": 5945.476630039542,
      "slippage_bps": 0.0,
      "spread_bps": 326.79638306296556
    },
    "M2": {
      "cost2x_net_bps": 1849.1854772820639,
      "cost_bps": 4247.904220897974,
      "fee_bps": 2030.0,
      "frozen_floor_reserve_bps": 345.42573427746277,
      "funding_bps": 1122.84,
      "gross_bps": 10344.993919078011,
      "impact_bps": 422.8421035575453,
      "net_bps": 6097.089698180037,
      "slippage_bps": 0.0,
      "spread_bps": 326.79638306296556
    }
  },
  "effects": {
    "KR1_FULL": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 912.9343826125898,
        "cost_bps": -15.41,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": 4.0,
        "funding_bps": -19.41,
        "gross_bps": 882.1143826125898,
        "impact_bps": 0.0,
        "net_bps": 897.5243826125899,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2025-01": 0.0,
        "2025-02": 0.0,
        "2025-03": 0.0,
        "2025-04": 0.05543698201161362,
        "2025-05": -112.79381034728692,
        "2025-06": 184.43523939555283,
        "2025-07": -186.0904864925711,
        "2025-08": 735.7482553123276,
        "2025-09": 276.1697477625558,
        "2025-10": 0.0,
        "2025-11": 0.0,
        "2025-12": 0.0
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 276.1697477625558,
        "BCH-USDT": 184.43523939555283,
        "BTC-USDT": -491.7843381632663,
        "ETH-USDT": -186.03504951055947,
        "HYPE-USDT": 205.5766666666653,
        "LINK-USDT": 649.1301997958999,
        "SOL-USDT": 260.03191666574185
      },
      "independent": false,
      "large_winners": {
        "T": 9,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 21433.16693932385,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 21433.16693932385,
        "parent_positive_bps": 21433.16693932385,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 526.318593253592,
          "cost_bps": 21.38037691202682,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 6.0,
          "gross_bps": 569.0793470776456,
          "impact_bps": 2.0,
          "net_bps": 547.6989701656188,
          "slippage_bps": 0.0,
          "spread_bps": 3.3803769120268194
        },
        "child_hold_ms": 172800000,
        "delta": {
          "cost2x_net_bps": 477.5154117218185,
          "cost_bps": -1.0,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": -1.0,
          "gross_bps": 475.5154117218185,
          "impact_bps": 0.0,
          "net_bps": 476.5154117218185,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2025-08",
        "origin_key": "23bdd736b6f855d35443df00de3082fc216d437a3f7b5535adb2b3a3965c802a",
        "parent": {
          "cost2x_net_bps": 48.80318153177345,
          "cost_bps": 22.38037691202682,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 7.0,
          "gross_bps": 93.56393535582708,
          "impact_bps": 2.0,
          "net_bps": 71.18355844380027,
          "slippage_bps": 0.0,
          "spread_bps": 3.3803769120268194
        },
        "parent_hold_ms": 201600000,
        "parent_large_winner": false,
        "parent_winner": true,
        "signal_ts": 1755604800000,
        "symbol": "LINK-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.5309219681973844,
      "net_increment_without_largest_positive": 421.00897089077137,
      "ordinary_winners": {
        "T": 72,
        "additional_loss_after_winner_bps": 6.247275593336248,
        "capped_terminal_preserved_bps_hypothetical": 25562.168264703727,
        "capped_terminal_retention_hypothetical": 0.9712744988179536,
        "child_signed_terminal_bps": 26568.638065260508,
        "parent_positive_bps": 26318.170914415055,
        "profit_cut_bps": 756.0026497113281,
        "realized_capped_retention_lower": 0.9712744988179536,
        "realized_capped_retention_upper": 0.9712744988179536,
        "signed_winner_deterioration_bps": 762.2499253046644,
        "winner_removed_T": 0,
        "winner_to_loss_T": 1,
        "winner_to_loss_origins": [
          "63792578bc411889e22ef91262a5824732a8d1ae57a0ded1ca745836604b9ca0"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 202,
          "delta_bps": {
            "cost2x_net_bps": 912.9343826125898,
            "cost_bps": -15.41,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": 4.0,
            "funding_bps": -19.41,
            "gross_bps": 882.1143826125898,
            "impact_bps": 0.0,
            "net_bps": 897.5243826125899,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 1,
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
      }
    },
    "KR2_FULL": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 2383.3406363166114,
        "cost_bps": 73.64378493244138,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": -5.396215067558622,
        "funding_bps": 79.03999999999999,
        "gross_bps": 2530.628206181494,
        "impact_bps": 0.0,
        "net_bps": 2456.9844212490534,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2025-01": -245.00816157168163,
        "2025-02": 0.0,
        "2025-03": 1840.720551439497,
        "2025-04": 2281.474854629749,
        "2025-05": -186.15236579846606,
        "2025-06": -88.55060478479143,
        "2025-07": -621.6308567354213,
        "2025-08": -223.9161992643293,
        "2025-09": -9.064429734929035,
        "2025-10": -290.88836693057425,
        "2025-11": 0.0,
        "2025-12": 0.0
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 2412.3824636461236,
        "BCH-USDT": 414.21355513258163,
        "BTC-USDT": -84.83945950622405,
        "ETH-USDT": -3.6107139914159347,
        "HYPE-USDT": 124.96752005127996,
        "LINK-USDT": -157.81009503152814,
        "SOL-USDT": -248.31884905176378
      },
      "independent": false,
      "large_winners": {
        "T": 9,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 19511.173902574756,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 19885.867755515,
        "parent_positive_bps": 19511.173902574756,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 2017.8420906714568,
          "cost_bps": 39.97840951527722,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 24.48,
          "gross_bps": 2097.7989097020113,
          "impact_bps": 2.7017543148977197,
          "net_bps": 2057.820500186734,
          "slippage_bps": 0.0,
          "spread_bps": 2.796655200379503
        },
        "child_hold_ms": 345600000,
        "delta": {
          "cost2x_net_bps": 1501.9183178259616,
          "cost_bps": 10.199999999999996,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 10.2,
          "gross_bps": 1522.3183178259615,
          "impact_bps": 0.0,
          "net_bps": 1512.1183178259616,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2025-04",
        "origin_key": "54e6c4939b93069ee71a073f9a5a7b9ee5f32e6eb14fbf1ef64e5b05c56eab0f",
        "parent": {
          "cost2x_net_bps": 515.9237728454953,
          "cost_bps": 29.778409515277225,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 14.280000000000001,
          "gross_bps": 575.4805918760497,
          "impact_bps": 2.7017543148977197,
          "net_bps": 545.7021823607726,
          "slippage_bps": 0.0,
          "spread_bps": 2.796655200379503
        },
        "parent_hold_ms": 201600000,
        "parent_large_winner": false,
        "parent_winner": true,
        "signal_ts": 1745078400000,
        "symbol": "1000PEPE-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.6154366729998427,
      "net_increment_without_largest_positive": 944.8661034230918,
      "ordinary_winners": {
        "T": 72,
        "additional_loss_after_winner_bps": 6.247275593336248,
        "capped_terminal_preserved_bps_hypothetical": 23553.844579402125,
        "capped_terminal_retention_hypothetical": 0.8835742632813967,
        "child_signed_terminal_bps": 28115.93724906936,
        "parent_positive_bps": 26657.458867043533,
        "profit_cut_bps": 3103.6142876414115,
        "realized_capped_retention_lower": 0.8835742632813967,
        "realized_capped_retention_upper": 0.8835742632813967,
        "signed_winner_deterioration_bps": 3109.861563234748,
        "winner_removed_T": 0,
        "winner_to_loss_T": 1,
        "winner_to_loss_origins": [
          "63792578bc411889e22ef91262a5824732a8d1ae57a0ded1ca745836604b9ca0"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 202,
          "delta_bps": {
            "cost2x_net_bps": 2383.3406363166114,
            "cost_bps": 73.64378493244138,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": -5.396215067558622,
            "funding_bps": 79.03999999999999,
            "gross_bps": 2530.628206181494,
            "impact_bps": 0.0,
            "net_bps": 2456.9844212490534,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 1,
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
      }
    },
    "M": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 4091.0722175088963,
        "cost_bps": 228.44695128600665,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": 130.40695128600663,
        "funding_bps": 98.04,
        "gross_bps": 4547.9661200809105,
        "impact_bps": 0.0,
        "net_bps": 4319.519168794904,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2025-01": -492.98016428148014,
        "2025-02": 119.12093337511374,
        "2025-03": 2600.5514472157847,
        "2025-04": 1263.3521905128912,
        "2025-05": 819.9984541052197,
        "2025-06": -473.0177466232125,
        "2025-07": 1408.7322433804816,
        "2025-08": -2255.8564611519487,
        "2025-09": 710.1238291801114,
        "2025-10": 491.9553843173815,
        "2025-11": 1040.5833104569974,
        "2025-12": -913.0442516924364
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 3872.7938336213456,
        "BCH-USDT": -1846.2540422863156,
        "BTC-USDT": 394.00541408100764,
        "ETH-USDT": 2040.474679932461,
        "HYPE-USDT": -425.391234047426,
        "LINK-USDT": -527.2829014235388,
        "SOL-USDT": 811.1734189173701
      },
      "independent": false,
      "large_winners": {
        "T": 10,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 13470.451827412096,
        "capped_terminal_retention_hypothetical": 0.8517301514653098,
        "child_signed_terminal_bps": 17911.051048936333,
        "parent_positive_bps": 15815.398579277295,
        "profit_cut_bps": 2344.9467518651986,
        "realized_capped_retention_lower": 0.8517301514653098,
        "realized_capped_retention_upper": 0.8517301514653098,
        "signed_winner_deterioration_bps": 2344.9467518651986,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 4166.574257098651,
          "cost_bps": 25.0,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 12.0,
          "gross_bps": 4216.574257098651,
          "impact_bps": 2.0,
          "net_bps": 4191.574257098651,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "child_hold_ms": 345600000,
        "delta": {
          "cost2x_net_bps": 2057.514962641575,
          "cost_bps": 5.0,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": -1.0,
          "funding_bps": 6.0,
          "gross_bps": 2067.514962641575,
          "impact_bps": 0.0,
          "net_bps": 2062.514962641575,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2025-05",
        "origin_key": "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
        "parent": {
          "cost2x_net_bps": 2109.0592944570762,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 1.0,
          "funding_bps": 6.0,
          "gross_bps": 2149.0592944570762,
          "impact_bps": 2.0,
          "net_bps": 2129.0592944570762,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "parent_hold_ms": 172800000,
        "parent_large_winner": true,
        "parent_winner": true,
        "signal_ts": 1746576000000,
        "symbol": "ETH-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.47748716513208417,
      "net_increment_without_largest_positive": 2257.0042061533286,
      "ordinary_winners": {
        "T": 88,
        "additional_loss_after_winner_bps": 3023.7225455766006,
        "capped_terminal_preserved_bps_hypothetical": 20868.865449023586,
        "capped_terminal_retention_hypothetical": 0.7130570974575262,
        "child_signed_terminal_bps": 27317.515906658788,
        "parent_positive_bps": 29266.752302772857,
        "profit_cut_bps": 8397.886853749269,
        "realized_capped_retention_lower": 0.7130570974575262,
        "realized_capped_retention_upper": 0.7130570974575262,
        "signed_winner_deterioration_bps": 11421.60939932587,
        "winner_removed_T": 0,
        "winner_to_loss_T": 15,
        "winner_to_loss_origins": [
          "136c2d685362c73f9c8faac1906b1f0f6b39c96937143c502f1dafa8a17f4635",
          "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530",
          "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77",
          "426aaff0097e98b6f0e7cc599671e126621e79f81c2d9456d7d68d4dc6ce0e50",
          "437f79a339b9767f600ec378cd215060196d2354fc2a82b194def883ac5e5e94",
          "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1",
          "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569",
          "6183540eaf7ee3778e78b8f4d8f8cbc7736977c475a71761e053c24a7e44e283",
          "8f8515e6532e5db846128d34e0acd9af583552e0154ecac8c07839a96cfa430b",
          "96a7eaa94ec10a0dc4fed1a17b04fca7a0d6ce97a652a93ce32f852597731eca",
          "b79a83562bbb1fcf661f5da109bec9523bc2fbe18a6cc2ee2b9045b078870920",
          "cfede36f952bb1cbafdc54a70967713c8d8900f29aebfedaa2683dac8a33a86e",
          "d88d6da82807ed73485910acdb84b99de13e8b250836cce7b9e4604a05804a5e",
          "dba9bbf39a23532d0a92a6380648a5a82bb86abaaa2a1533200bea613985c5f9",
          "f04b345b13db9aef69e08301403563cd13bee3941d6c62e05f591694a5764ad7"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 202,
          "delta_bps": {
            "cost2x_net_bps": 4091.0722175088963,
            "cost_bps": 228.44695128600665,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": 130.40695128600663,
            "funding_bps": 98.04,
            "gross_bps": 4547.9661200809105,
            "impact_bps": 0.0,
            "net_bps": 4319.519168794904,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 1,
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
      }
    },
    "M2": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 3895.042036262436,
        "cost_bps": 272.8640643919724,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": -28.565935608027594,
        "funding_bps": 301.43,
        "gross_bps": 4440.770165046381,
        "impact_bps": 0.0,
        "net_bps": 4167.906100654409,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2025-01": -492.98016428148014,
        "2025-02": 0.0,
        "2025-03": 2409.8519195253284,
        "2025-04": 2232.860882428055,
        "2025-05": 1699.6263490706417,
        "2025-06": -271.4616862775851,
        "2025-07": 1590.5410558249844,
        "2025-08": -2383.0628620624493,
        "2025-09": 812.2472665986245,
        "2025-10": -480.66038624273864,
        "2025-11": 0.5620398298877838,
        "2025-12": -949.6183137588591
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 2727.725810475015,
        "BCH-USDT": -1628.4922768268757,
        "BTC-USDT": 397.9167807265093,
        "ETH-USDT": 2579.544876623607,
        "HYPE-USDT": 12.854493432621439,
        "LINK-USDT": -197.64393208639012,
        "SOL-USDT": 276.00034830992286
      },
      "independent": false,
      "large_winners": {
        "T": 9,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 12376.626191440322,
        "capped_terminal_retention_hypothetical": 0.8407135731422275,
        "child_signed_terminal_bps": 15392.433151001042,
        "parent_positive_bps": 14721.57294330552,
        "profit_cut_bps": 2344.9467518651986,
        "realized_capped_retention_lower": 0.8407135731422275,
        "realized_capped_retention_upper": 0.8407135731422275,
        "signed_winner_deterioration_bps": 2344.9467518651986,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 4166.574257098651,
          "cost_bps": 25.0,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 12.0,
          "gross_bps": 4216.574257098651,
          "impact_bps": 2.0,
          "net_bps": 4191.574257098651,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "child_hold_ms": 345600000,
        "delta": {
          "cost2x_net_bps": 2057.514962641575,
          "cost_bps": 5.0,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": -1.0,
          "funding_bps": 6.0,
          "gross_bps": 2067.514962641575,
          "impact_bps": 0.0,
          "net_bps": 2062.514962641575,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2025-05",
        "origin_key": "ca21eb9706c97e0f0aa521cc4dae10365923beace25ee2cac6b7879ee422f6e9",
        "parent": {
          "cost2x_net_bps": 2109.0592944570762,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 1.0,
          "funding_bps": 6.0,
          "gross_bps": 2149.0592944570762,
          "impact_bps": 2.0,
          "net_bps": 2129.0592944570762,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "parent_hold_ms": 172800000,
        "parent_large_winner": true,
        "parent_winner": true,
        "signal_ts": 1746576000000,
        "symbol": "ETH-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.49485638899536066,
      "net_increment_without_largest_positive": 2105.391138012834,
      "ordinary_winners": {
        "T": 78,
        "additional_loss_after_winner_bps": 213.7265550347581,
        "capped_terminal_preserved_bps_hypothetical": 21962.69108499536,
        "capped_terminal_retention_hypothetical": 0.7578495767189677,
        "child_signed_terminal_bps": 32646.129795135923,
        "parent_positive_bps": 28980.277563894128,
        "profit_cut_bps": 7017.586478898766,
        "realized_capped_retention_lower": 0.7578495767189677,
        "realized_capped_retention_upper": 0.7578495767189677,
        "signed_winner_deterioration_bps": 7231.313033933523,
        "winner_removed_T": 0,
        "winner_to_loss_T": 4,
        "winner_to_loss_origins": [
          "1dd6aee04904bcf7f8130a45985ae5a21f674a59006753af688612022c652530",
          "2440bd6d1fe7ea94275b486cb5b6c9ec63144905130ff084d8f3a8a0aa53be77",
          "4ff02a7f4dd174372c172c23c1e4be91df462c2c8fe89fffe7780ea1abc251b1",
          "50fcf172703af4e13424cf8d60dcfd66ed18a64ae825688ceb284e5ed3a73569"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 202,
          "delta_bps": {
            "cost2x_net_bps": 3895.042036262436,
            "cost_bps": 272.8640643919724,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": -28.565935608027594,
            "funding_bps": 301.43,
            "gross_bps": 4440.770165046381,
            "impact_bps": 0.0,
            "net_bps": 4167.906100654409,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 1,
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
      }
    }
  },
  "occupancy_bridge": {
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 912.9343826125896,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 912.9343826125896
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": -15.409999999999854,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -15.409999999999854
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": 4.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 4.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": -19.410000000000082,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -19.410000000000082
    },
    "gross_bps": {
      "fixed_path_or_filter_effect": 882.1143826125899,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 882.1143826125899
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 897.5243826125898,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 897.5243826125898
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    }
  },
  "decision": {
    "FIXED": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": 897.5243826125898,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "TRADEOFF",
      "exposure_delta_symbol_days": -7.0,
      "failed_checks": [
        "positive_daily_delta95_lower",
        "no_unresolved_positions"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": 0.0,
      "increment_checks": {
        "closed_net_increased": true,
        "terminal_net_increased": true
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": true,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": false,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": 897.5243826125898
    },
    "FULL": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": 897.5243826125898,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "TRADEOFF",
      "exposure_delta_symbol_days": -7.0,
      "failed_checks": [
        "positive_daily_delta95_lower",
        "no_unresolved_positions"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": 0.0,
      "increment_checks": {
        "closed_net_increased": true,
        "terminal_net_increased": true
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": true,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": false,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": 897.5243826125898
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
      "child_marked_delta_sum_bps": 10264.995798834447,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -0.9361392141359743,
        6.808527615688786
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -351.98834451512636,
        2560.0063834989837
      ],
      "child_minus_parent_marked_delta_sum_bps": 897.5243826125898,
      "child_minus_parent_mean_daily_bps": 2.387032932480292,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 9367.471416221857,
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
      "child_marked_delta_sum_bps": 10264.995798834447,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -0.9361392141359743,
        6.808527615688786
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -351.98834451512636,
        2560.0063834989837
      ],
      "child_minus_parent_marked_delta_sum_bps": 897.5243826125898,
      "child_minus_parent_mean_daily_bps": 2.387032932480292,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 9367.471416221857,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    }
  }
}
```

### KR3 SEEN2026

| 지표 | FIXED | FULL | KR1_FULL | KR2_FULL | M | M2 |
|---|---:|---:|---:|---:|---:|---:|
| PF | 1.43 | 1.43 | 1.39 | 1.34 | 0.97 | 1.04 |
| closed_T | 75.00 | 75.00 | 74.00 | 74.00 | 75.00 | 75.00 |
| closed_cost2x_net_bps | 3,699.12 | 3,699.12 | 3,209.96 | 2,720.93 | -1,998.21 | -1,097.14 |
| closed_cost_bps | 1,664.44 | 1,664.44 | 1,648.59 | 1,619.13 | 1,600.31 | 1,579.77 |
| closed_fee_bps | 750.00 | 750.00 | 740.00 | 740.00 | 750.00 | 750.00 |
| closed_funding_bps | 521.98 | 521.98 | 519.52 | 486.06 | 497.51 | 424.91 |
| closed_gross_bps | 7,028.01 | 7,028.01 | 6,507.13 | 5,959.19 | 1,202.41 | 2,062.40 |
| closed_net_bps | 5,363.56 | 5,363.56 | 4,858.55 | 4,340.06 | -397.90 | 482.63 |
| entries_T | 79.00 | 79.00 | 79.00 | 79.00 | 79.00 | 79.00 |
| entries_per_30_days | 19.75 | 19.75 | 19.75 | 19.75 | 19.75 | 19.75 |
| exposure_symbol_days | 148.17 | 148.17 | 151.17 | 140.67 | 141.17 | 119.83 |
| grouped_max_loss_trade_sum_bps | 2,665.35 | 2,665.35 | 2,665.35 | 2,665.35 | 3,758.31 | 2,665.35 |
| marked_DD_trade_sum_bps | 4,093.69 | 4,093.69 | 4,409.68 | 4,576.35 | 5,643.86 | 4,260.36 |
| max_completed_recovery_days | 78.00 | 78.00 | 78.00 | 79.00 | 85.00 | 78.00 |
| max_simultaneous_symbols | 7.00 | 7.00 | 7.00 | 7.00 | 7.00 | 7.00 |
| mean_loss_bps | -251.61 | -251.61 | -251.61 | -251.61 | -288.94 | -255.61 |
| mean_win_bps | 717.76 | 717.76 | 726.62 | 705.02 | 498.93 | 500.30 |
| net_expectancy_bps_per_closed_trade | 71.51 | 71.51 | 65.66 | 58.65 | -5.31 | 6.44 |
| open_T | 4.00 | 4.00 | 5.00 | 5.00 | 4.00 | 4.00 |
| open_net_mark_bps_hypothetical | -616.99 | -616.99 | -444.14 | -444.14 | -616.99 | -616.99 |
| open_underwater_days | 8.00 | 8.00 | 8.00 | 8.00 | 8.00 | 8.00 |
| realized_payoff | 2.85 | 2.85 | 2.89 | 2.80 | 1.73 | 1.96 |
| terminal_cost2x_net_bps_hypothetical | 3,002.13 | 3,002.13 | 2,660.13 | 2,171.11 | -2,695.19 | -1,794.12 |
| terminal_net_bps_hypothetical | 4,746.58 | 4,746.58 | 4,414.41 | 3,895.93 | -1,014.88 | -134.35 |
| win_rate | 0.33 | 0.33 | 0.32 | 0.32 | 0.36 | 0.35 |

```json
{
  "terminal_all_cost_components": {
    "FIXED": {
      "cost2x_net_bps": 3002.132202471482,
      "cost_bps": 1744.4444532629004,
      "fee_bps": 790.0,
      "frozen_floor_reserve_bps": 126.18775015399405,
      "funding_bps": 535.98,
      "gross_bps": 6491.021108997284,
      "impact_bps": 164.31578883407948,
      "net_bps": 4746.576655734382,
      "slippage_bps": 0.0,
      "spread_bps": 127.96091427482702
    },
    "FULL": {
      "cost2x_net_bps": 3002.132202471482,
      "cost_bps": 1744.4444532629004,
      "fee_bps": 790.0,
      "frozen_floor_reserve_bps": 126.18775015399405,
      "funding_bps": 535.98,
      "gross_bps": 6491.021108997284,
      "impact_bps": 164.31578883407948,
      "net_bps": 4746.576655734382,
      "slippage_bps": 0.0,
      "spread_bps": 127.96091427482702
    },
    "KR1_FULL": {
      "cost2x_net_bps": 2660.132945077918,
      "cost_bps": 1754.2782381953418,
      "fee_bps": 790.0,
      "frozen_floor_reserve_bps": 125.79153508643543,
      "funding_bps": 546.21,
      "gross_bps": 6168.689421468603,
      "impact_bps": 164.31578883407948,
      "net_bps": 4414.411183273261,
      "slippage_bps": 0.0,
      "spread_bps": 127.96091427482702
    },
    "KR2_FULL": {
      "cost2x_net_bps": 2171.107812355751,
      "cost_bps": 1724.818238195342,
      "fee_bps": 790.0,
      "frozen_floor_reserve_bps": 129.79153508643543,
      "funding_bps": 512.75,
      "gross_bps": 5620.744288746435,
      "impact_bps": 164.31578883407948,
      "net_bps": 3895.926050551093,
      "slippage_bps": 0.0,
      "spread_bps": 127.96091427482702
    },
    "M": {
      "cost2x_net_bps": -2695.193322599963,
      "cost_bps": 1680.3098316697901,
      "fee_bps": 790.0,
      "frozen_floor_reserve_bps": 86.52312856088352,
      "funding_bps": 511.51,
      "gross_bps": 665.4263407396173,
      "impact_bps": 164.31578883407948,
      "net_bps": -1014.8834909301728,
      "slippage_bps": 0.0,
      "spread_bps": 127.96091427482702
    },
    "M2": {
      "cost2x_net_bps": -1794.1235323297237,
      "cost_bps": 1659.770668330459,
      "fee_bps": 790.0,
      "frozen_floor_reserve_bps": 138.58396522155266,
      "funding_bps": 438.91,
      "gross_bps": 1525.4178043311947,
      "impact_bps": 164.31578883407948,
      "net_bps": -134.3528639992646,
      "slippage_bps": 0.0,
      "spread_bps": 127.96091427482702
    }
  },
  "effects": {
    "KR1_FULL": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 341.9992573935636,
        "cost_bps": -9.833784932441379,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": 0.39621506755862157,
        "funding_bps": -10.23,
        "gross_bps": 322.3316875286808,
        "impact_bps": 0.0,
        "net_bps": 332.16547246112214,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2026-05": 0.0,
        "2026-06": 0.0,
        "2026-07": -42.68105362824906,
        "2026-08": 0.0,
        "2026-09": 374.8465260893712
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 0.0,
        "BCH-USDT": -42.68105362824906,
        "BTC-USDT": 0.0,
        "ETH-USDT": 0.0,
        "HYPE-USDT": 374.8465260893712,
        "LINK-USDT": 0.0,
        "SOL-USDT": 0.0
      },
      "independent": false,
      "large_winners": {
        "T": 3,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 9433.063140226812,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 9433.063140226812,
        "parent_positive_bps": 9433.063140226812,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 526.236777920099,
          "cost_bps": 21.46,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 8.46,
          "gross_bps": 569.156777920099,
          "impact_bps": 2.0,
          "net_bps": 547.696777920099,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "child_hold_ms": 172800000,
        "delta": {
          "cost2x_net_bps": 379.07652608937127,
          "cost_bps": -4.23,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": -4.23,
          "gross_bps": 370.61652608937123,
          "impact_bps": 0.0,
          "net_bps": 374.8465260893712,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2026-09",
        "origin_key": "e8c589146cdb1cbe7e03cb2cc50877f46166fadee59afb758fa1d3ab2c47861c",
        "parent": {
          "cost2x_net_bps": 147.16025183072776,
          "cost_bps": 25.69,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 12.690000000000001,
          "gross_bps": 198.54025183072775,
          "impact_bps": 2.0,
          "net_bps": 172.85025183072776,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "parent_hold_ms": 259200000,
        "parent_large_winner": false,
        "parent_winner": false,
        "signal_ts": 1788307200000,
        "symbol": "HYPE-USDT",
        "transition": "O_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 1.1284933479449601,
      "net_increment_without_largest_positive": -42.68105362824906,
      "ordinary_winners": {
        "T": 21,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 7963.197016533631,
        "capped_terminal_retention_hypothetical": 0.9946687854531132,
        "child_signed_terminal_bps": 7963.197016533631,
        "parent_positive_bps": 8005.87807016188,
        "profit_cut_bps": 42.68105362824906,
        "realized_capped_retention_lower": 0.9946687854531132,
        "realized_capped_retention_upper": 0.9946687854531132,
        "signed_winner_deterioration_bps": 42.68105362824906,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 74,
          "delta_bps": {
            "cost2x_net_bps": -37.077268695807675,
            "cost_bps": -5.603784932441378,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": 0.39621506755862157,
            "funding_bps": -6.0,
            "gross_bps": -48.284838560690446,
            "impact_bps": 0.0,
            "net_bps": -42.68105362824906,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_C": {
          "T": 1,
          "delta_bps": {
            "cost2x_net_bps": 379.07652608937127,
            "cost_bps": -4.23,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": 0.0,
            "funding_bps": -4.23,
            "gross_bps": 370.61652608937123,
            "impact_bps": 0.0,
            "net_bps": 374.8465260893712,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 4,
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
      }
    },
    "KR2_FULL": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 831.024390115731,
        "cost_bps": 19.626215067558622,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": -3.6037849324413784,
        "funding_bps": 23.23,
        "gross_bps": 870.2768202508482,
        "impact_bps": 0.0,
        "net_bps": 850.6506051832895,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2026-05": -321.2083296094371,
        "2026-06": 635.7884889648252,
        "2026-07": -372.43898046651293,
        "2026-08": 533.6629002050431,
        "2026-09": 374.8465260893712
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 0.0,
        "BCH-USDT": -97.88056712406072,
        "BTC-USDT": -8.780154063337307,
        "ETH-USDT": -190.0137699401518,
        "HYPE-USDT": 287.1722130141268,
        "LINK-USDT": -17.477721812083075,
        "SOL-USDT": 877.6306051087956
      },
      "independent": false,
      "large_winners": {
        "T": 3,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 9433.063140226812,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 9433.063140226812,
        "parent_positive_bps": 9433.063140226812,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 1061.0012849658979,
          "cost_bps": 25.0,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 12.0,
          "gross_bps": 1111.0012849658979,
          "impact_bps": 2.0,
          "net_bps": 1086.0012849658979,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "child_hold_ms": 345600000,
        "delta": {
          "cost2x_net_bps": 630.7884889648252,
          "cost_bps": 5.0,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": -1.0,
          "funding_bps": 6.0,
          "gross_bps": 640.7884889648252,
          "impact_bps": 0.0,
          "net_bps": 635.7884889648252,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2026-06",
        "origin_key": "962f9283dc72ebb8cde3d9e0c593e37fb697e91eee5c09c8621ad854178a7630",
        "parent": {
          "cost2x_net_bps": 430.21279600107266,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 1.0,
          "funding_bps": 6.0,
          "gross_bps": 470.21279600107266,
          "impact_bps": 2.0,
          "net_bps": 450.21279600107266,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "parent_hold_ms": 172800000,
        "parent_large_winner": false,
        "parent_winner": true,
        "signal_ts": 1782619200000,
        "symbol": "SOL-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.747414373293524,
      "net_increment_without_largest_positive": 214.86211621846428,
      "ordinary_winners": {
        "T": 21,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 6663.37736779853,
        "capped_terminal_retention_hypothetical": 0.8899462634689838,
        "child_signed_terminal_bps": 7963.197016533631,
        "parent_positive_bps": 7487.392937439712,
        "profit_cut_bps": 824.0155696411824,
        "realized_capped_retention_lower": 0.8899462634689838,
        "realized_capped_retention_upper": 0.8899462634689838,
        "signed_winner_deterioration_bps": 824.0155696411824,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 74,
          "delta_bps": {
            "cost2x_net_bps": 451.9478640263597,
            "cost_bps": 23.856215067558622,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": -3.6037849324413784,
            "funding_bps": 27.46,
            "gross_bps": 499.660294161477,
            "impact_bps": 0.0,
            "net_bps": 475.80407909391835,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_C": {
          "T": 1,
          "delta_bps": {
            "cost2x_net_bps": 379.07652608937127,
            "cost_bps": -4.23,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": 0.0,
            "funding_bps": -4.23,
            "gross_bps": 370.61652608937123,
            "impact_bps": 0.0,
            "net_bps": 374.8465260893712,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 4,
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
      }
    },
    "M": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 5697.325525071445,
        "cost_bps": 64.13462159311052,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": 39.66462159311052,
        "funding_bps": 24.470000000000002,
        "gross_bps": 5825.594768257666,
        "impact_bps": 0.0,
        "net_bps": 5761.460146664555,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2026-05": 2467.096334051116,
        "2026-06": 1850.7464234900758,
        "2026-07": -410.6640594205058,
        "2026-08": 1854.2814485438694,
        "2026-09": 0.0
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": -287.5887223216232,
        "BCH-USDT": -67.8876881651025,
        "BTC-USDT": 30.18602234757074,
        "ETH-USDT": -49.95534411152951,
        "HYPE-USDT": 5121.996691362553,
        "LINK-USDT": -500.7078248550294,
        "SOL-USDT": 1515.4170124077164
      },
      "independent": false,
      "large_winners": {
        "T": 3,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 5169.644276112545,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 9433.063140226812,
        "parent_positive_bps": 5169.644276112545,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 3322.7002065745423,
          "cost_bps": 29.92,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 16.92,
          "gross_bps": 3382.5402065745425,
          "impact_bps": 2.0,
          "net_bps": 3352.6202065745424,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "child_hold_ms": 345600000,
        "delta": {
          "cost2x_net_bps": 2107.071887940386,
          "cost_bps": 8.46,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 8.46,
          "gross_bps": 2123.9918879403863,
          "impact_bps": 0.0,
          "net_bps": 2115.5318879403862,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2026-05",
        "origin_key": "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
        "parent": {
          "cost2x_net_bps": 1215.6283186341561,
          "cost_bps": 21.46,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 8.46,
          "gross_bps": 1258.5483186341562,
          "impact_bps": 2.0,
          "net_bps": 1237.0883186341562,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "parent_hold_ms": 172800000,
        "parent_large_winner": true,
        "parent_winner": true,
        "signal_ts": 1778990400000,
        "symbol": "HYPE-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.36718676066259304,
      "net_increment_without_largest_positive": 3645.928258724169,
      "ordinary_winners": {
        "T": 24,
        "additional_loss_after_winner_bps": 113.88534219641485,
        "capped_terminal_preserved_bps_hypothetical": 6023.367052362323,
        "capped_terminal_retention_hypothetical": 0.7255689724535037,
        "child_signed_terminal_bps": 8397.008452257314,
        "parent_positive_bps": 8301.577494410176,
        "profit_cut_bps": 2278.2104420478518,
        "realized_capped_retention_lower": 0.7255689724535037,
        "realized_capped_retention_upper": 0.7255689724535037,
        "signed_winner_deterioration_bps": 2392.0957842442667,
        "winner_removed_T": 0,
        "winner_to_loss_T": 2,
        "winner_to_loss_origins": [
          "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782",
          "93dfc61c03a8525e14fface007825cb7ff83bfbf1335caa50d94ab17aee30bdc"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 75,
          "delta_bps": {
            "cost2x_net_bps": 5697.325525071445,
            "cost_bps": 64.13462159311052,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": 39.66462159311052,
            "funding_bps": 24.470000000000002,
            "gross_bps": 5825.594768257666,
            "impact_bps": 0.0,
            "net_bps": 5761.460146664555,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 4,
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
      }
    },
    "M2": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 4796.255734801206,
        "cost_bps": 84.67378493244138,
        "fee_bps": 0.0,
        "frozen_floor_reserve_bps": -12.396215067558622,
        "funding_bps": 97.07000000000001,
        "gross_bps": 4965.603304666089,
        "impact_bps": 0.0,
        "net_bps": 4880.929519733647,
        "slippage_bps": 0.0,
        "spread_bps": 0.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2026-05": 2694.988682560425,
        "2026-06": 333.5962989971113,
        "2026-07": -515.2069365677316,
        "2026-08": 2367.551474743843,
        "2026-09": 0.0
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 0.0,
        "BCH-USDT": -120.358661669121,
        "BTC-USDT": -152.7196220144462,
        "ETH-USDT": -282.3003004782452,
        "HYPE-USDT": 3992.123726202642,
        "LINK-USDT": -215.5399865141187,
        "SOL-USDT": 1659.7243642069361
      },
      "independent": false,
      "large_winners": {
        "T": 3,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 5169.644276112545,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 9433.063140226812,
        "parent_positive_bps": 5169.644276112545,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 3322.7002065745423,
          "cost_bps": 29.92,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 16.92,
          "gross_bps": 3382.5402065745425,
          "impact_bps": 2.0,
          "net_bps": 3352.6202065745424,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "child_hold_ms": 345600000,
        "delta": {
          "cost2x_net_bps": 2107.071887940386,
          "cost_bps": 8.46,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 8.46,
          "gross_bps": 2123.9918879403863,
          "impact_bps": 0.0,
          "net_bps": 2115.5318879403862,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2026-05",
        "origin_key": "6142f0b565cc34d315c433597a8c95c271149c4051dcdf8c86a4662231012f02",
        "parent": {
          "cost2x_net_bps": 1215.6283186341561,
          "cost_bps": 21.46,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 8.46,
          "gross_bps": 1258.5483186341562,
          "impact_bps": 2.0,
          "net_bps": 1237.0883186341562,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "parent_hold_ms": 172800000,
        "parent_large_winner": true,
        "parent_winner": true,
        "signal_ts": 1778990400000,
        "symbol": "HYPE-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.43342807540802825,
      "net_increment_without_largest_positive": 2765.3976317932606,
      "ordinary_winners": {
        "T": 23,
        "additional_loss_after_winner_bps": 1.8183844089337633,
        "capped_terminal_preserved_bps_hypothetical": 6023.367052362323,
        "capped_terminal_retention_hypothetical": 0.7684777992985665,
        "child_signed_terminal_bps": 8509.075410044796,
        "parent_positive_bps": 7838.049528379601,
        "profit_cut_bps": 1814.6824760172778,
        "realized_capped_retention_lower": 0.7684777992985665,
        "realized_capped_retention_upper": 0.7684777992985665,
        "signed_winner_deterioration_bps": 1816.5008604262116,
        "winner_removed_T": 0,
        "winner_to_loss_T": 1,
        "winner_to_loss_origins": [
          "61f902db7837b6eb773c958f6e4be6c4d124fca479535bd0636df815d53f0782"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "C_C": {
          "T": 75,
          "delta_bps": {
            "cost2x_net_bps": 4796.255734801206,
            "cost_bps": 84.67378493244138,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": -12.396215067558622,
            "funding_bps": 97.07000000000001,
            "gross_bps": 4965.603304666089,
            "impact_bps": 0.0,
            "net_bps": 4880.929519733647,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        },
        "O_O": {
          "T": 4,
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
      }
    }
  },
  "occupancy_bridge": {
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 341.99925739356377,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 341.99925739356377
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": -9.833784932441404,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -9.833784932441404
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": 0.39621506755861446,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.39621506755861446
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": -10.230000000000018,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": -10.230000000000018
    },
    "gross_bps": {
      "fixed_path_or_filter_effect": 322.33168752868096,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 322.33168752868096
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 332.1654724611217,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 332.1654724611217
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    }
  },
  "decision": {
    "FIXED": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": 505.01572429184944,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "TRADEOFF",
      "exposure_delta_symbol_days": -3.0,
      "failed_checks": [
        "positive_daily_delta95_lower",
        "no_unresolved_positions"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": 0.0,
      "increment_checks": {
        "closed_net_increased": true,
        "terminal_net_increased": true
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": true,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": false,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": 332.1654724611217
    },
    "FULL": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": 505.01572429184944,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "TRADEOFF",
      "exposure_delta_symbol_days": -3.0,
      "failed_checks": [
        "positive_daily_delta95_lower",
        "no_unresolved_positions"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": 0.0,
      "increment_checks": {
        "closed_net_increased": true,
        "terminal_net_increased": true
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": true,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": false,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": 332.1654724611217
    }
  },
  "uncertainty": {
    "FIXED": {
      "N_effective": null,
      "approximate_calendar_blocks": 4.0,
      "block_days": 30,
      "calendar_days": 120,
      "calendar_last_day": "2026-09-04",
      "calendar_start": "2026-05-08",
      "child_marked_delta_sum_bps": 4746.576655734382,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -1.3522805708779562,
        2.768045603842674
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -162.27366850535475,
        332.1654724611209
      ],
      "child_minus_parent_marked_delta_sum_bps": 332.16547246112134,
      "child_minus_parent_mean_daily_bps": 2.768045603842678,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 4414.411183273261,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    },
    "FULL": {
      "N_effective": null,
      "approximate_calendar_blocks": 4.0,
      "block_days": 30,
      "calendar_days": 120,
      "calendar_last_day": "2026-09-04",
      "calendar_start": "2026-05-08",
      "child_marked_delta_sum_bps": 4746.576655734382,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -1.3522805708779562,
        2.768045603842674
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -162.27366850535475,
        332.1654724611209
      ],
      "child_minus_parent_marked_delta_sum_bps": 332.16547246112134,
      "child_minus_parent_mean_daily_bps": 2.768045603842678,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 4414.411183273261,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    }
  }
}
```

### BR2 DEV2025

| 지표 | BR1_FULL | FIXED | FULL | V2 |
|---|---:|---:|---:|---:|
| PF | 1.31 | 1.31 | 1.26 | 1.23 |
| closed_T | 138.00 | 138.00 | 140.00 | 155.00 |
| closed_cost2x_net_bps | 4,245.68 | 4,245.68 | 3,473.31 | 2,101.33 |
| closed_cost_bps | 2,847.42 | 2,847.42 | 2,888.80 | 3,129.13 |
| closed_fee_bps | 1,380.00 | 1,380.00 | 1,400.00 | 1,550.00 |
| closed_funding_bps | 725.71 | 725.71 | 735.94 | 553.14 |
| closed_gross_bps | 9,940.51 | 9,940.51 | 9,250.90 | 8,359.59 |
| closed_net_bps | 7,093.10 | 7,093.10 | 6,362.11 | 5,230.46 |
| entries_T | 140.00 | 140.00 | 142.00 | 157.00 |
| entries_per_30_days | 11.20 | 11.20 | 11.36 | 12.56 |
| exposure_symbol_days | 205.67 | 205.67 | 208.67 | 155.83 |
| grouped_max_loss_trade_sum_bps | 3,296.71 | 3,296.71 | 3,296.71 | 2,735.50 |
| marked_DD_trade_sum_bps | 7,593.30 | 7,593.30 | 7,593.30 | 4,289.90 |
| max_completed_recovery_days | 83.00 | 83.00 | 83.00 | 98.00 |
| max_simultaneous_symbols | 7.00 | 7.00 | 7.00 | 7.00 |
| mean_loss_bps | -286.38 | -286.38 | -292.80 | -294.94 |
| mean_win_bps | 531.40 | 531.40 | 523.65 | 349.95 |
| net_expectancy_bps_per_closed_trade | 51.40 | 51.40 | 45.44 | 33.74 |
| open_T | 2.00 | 2.00 | 2.00 | 2.00 |
| open_net_mark_bps_hypothetical | -438.27 | -438.27 | -438.27 | -438.27 |
| open_underwater_days | 137.33 | 137.33 | 137.33 | 87.33 |
| realized_payoff | 1.86 | 1.86 | 1.79 | 1.19 |
| terminal_cost2x_net_bps_hypothetical | 3,767.41 | 3,767.41 | 2,995.04 | 1,623.06 |
| terminal_net_bps_hypothetical | 6,654.83 | 6,654.83 | 5,923.84 | 4,792.19 |
| win_rate | 0.41 | 0.41 | 0.41 | 0.51 |

```json
{
  "terminal_all_cost_components": {
    "BR1_FULL": {
      "cost2x_net_bps": 3767.4137356659935,
      "cost_bps": 2887.415977055927,
      "fee_bps": 1400.0,
      "frozen_floor_reserve_bps": 243.10189865438335,
      "funding_bps": 729.75,
      "gross_bps": 9542.245689777848,
      "impact_bps": 292.63157766815897,
      "net_bps": 6654.829712721921,
      "slippage_bps": 0.0,
      "spread_bps": 221.9325007333851
    },
    "FIXED": {
      "cost2x_net_bps": 3767.4137356659935,
      "cost_bps": 2887.415977055927,
      "fee_bps": 1400.0,
      "frozen_floor_reserve_bps": 243.10189865438335,
      "funding_bps": 729.75,
      "gross_bps": 9542.245689777848,
      "impact_bps": 292.63157766815897,
      "net_bps": 6654.829712721921,
      "slippage_bps": 0.0,
      "spread_bps": 221.9325007333851
    },
    "FULL": {
      "cost2x_net_bps": 2995.0428499914865,
      "cost_bps": 2928.796353967954,
      "fee_bps": 1420.0,
      "frozen_floor_reserve_bps": 245.87189865438333,
      "funding_bps": 739.98,
      "gross_bps": 8852.635557927395,
      "impact_bps": 296.63157766815897,
      "net_bps": 5923.839203959441,
      "slippage_bps": 0.0,
      "spread_bps": 226.3128776454119
    },
    "V2": {
      "cost2x_net_bps": 1623.0627246957692,
      "cost_bps": 3169.1313712749898,
      "fee_bps": 1570.0,
      "frozen_floor_reserve_bps": 469.12812953411515,
      "funding_bps": 557.1800000000001,
      "gross_bps": 7961.32546724575,
      "impact_bps": 327.33333198305667,
      "net_bps": 4792.19409597076,
      "slippage_bps": 0.0,
      "spread_bps": 245.48990975781822
    }
  },
  "effects": {
    "BR1_FULL": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": -772.370885674507,
        "cost_bps": 41.38037691202682,
        "fee_bps": 20.0,
        "frozen_floor_reserve_bps": 2.7699999999999996,
        "funding_bps": 10.23,
        "gross_bps": -689.6101318504534,
        "impact_bps": 4.0,
        "net_bps": -730.9905087624802,
        "slippage_bps": 0.0,
        "spread_bps": 4.3803769120268194
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2025-01": 0.0,
        "2025-02": 0.0,
        "2025-03": 0.0,
        "2025-04": 0.0,
        "2025-05": -310.321194341906,
        "2025-06": 0.0,
        "2025-07": 0.0,
        "2025-08": -420.66931442057415,
        "2025-09": 0.0,
        "2025-10": 0.0,
        "2025-11": 0.0,
        "2025-12": 0.0
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 0.0,
        "BCH-USDT": 0.0,
        "BTC-USDT": 0.0,
        "ETH-USDT": 0.0,
        "HYPE-USDT": -546.7561708439506,
        "LINK-USDT": -184.23433791852955,
        "SOL-USDT": 0.0
      },
      "independent": false,
      "large_winners": {
        "T": 6,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 11392.42901768919,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 11392.42901768919,
        "parent_positive_bps": 11392.42901768919,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
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
        },
        "child_hold_ms": 0,
        "delta": {
          "cost2x_net_bps": 174.44893248701462,
          "cost_bps": -20.0,
          "fee_bps": -10.0,
          "frozen_floor_reserve_bps": -1.6196230879731814,
          "funding_bps": -3.0,
          "gross_bps": 134.44893248701462,
          "impact_bps": -2.0,
          "net_bps": 154.44893248701462,
          "slippage_bps": 0.0,
          "spread_bps": -3.3803769120268194
        },
        "entry_month": "2025-05",
        "origin_key": "5a79a5dd3e1a9eb432025d9a04f4dadcc13b17269e3b8cf1459b09085d2bbfee",
        "parent": {
          "cost2x_net_bps": -174.44893248701462,
          "cost_bps": 20.0,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 1.6196230879731814,
          "funding_bps": 3.0,
          "gross_bps": -134.44893248701462,
          "impact_bps": 2.0,
          "net_bps": -154.44893248701462,
          "slippage_bps": 0.0,
          "spread_bps": 3.3803769120268194
        },
        "parent_hold_ms": 86400000,
        "parent_large_winner": false,
        "parent_winner": false,
        "signal_ts": 1746921600000,
        "symbol": "LINK-USDT",
        "transition": "C_ABSENT",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": -0.21128719270033575,
      "net_increment_without_largest_positive": -885.4394412494948,
      "ordinary_winners": {
        "T": 51,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 18897.43324238867,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 18897.43324238867,
        "parent_positive_bps": 18897.43324238867,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "ABSENT_C": {
          "T": 3,
          "delta_bps": {
            "cost2x_net_bps": -946.8198181615217,
            "cost_bps": 61.38037691202682,
            "fee_bps": 30.0,
            "frozen_floor_reserve_bps": 4.389623087973181,
            "funding_bps": 13.23,
            "gross_bps": -824.0590643374679,
            "impact_bps": 6.0,
            "net_bps": -885.4394412494947,
            "slippage_bps": 0.0,
            "spread_bps": 7.760753824053639
          }
        },
        "C_ABSENT": {
          "T": 1,
          "delta_bps": {
            "cost2x_net_bps": 174.44893248701462,
            "cost_bps": -20.0,
            "fee_bps": -10.0,
            "frozen_floor_reserve_bps": -1.6196230879731814,
            "funding_bps": -3.0,
            "gross_bps": 134.44893248701462,
            "impact_bps": -2.0,
            "net_bps": 154.44893248701462,
            "slippage_bps": 0.0,
            "spread_bps": -3.3803769120268194
          }
        },
        "C_C": {
          "T": 137,
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
      }
    },
    "V2": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 1371.9801252957172,
        "cost_bps": -240.33501730703586,
        "fee_bps": -150.0,
        "frozen_floor_reserve_bps": -223.25623087973182,
        "funding_bps": 182.8,
        "gross_bps": 891.3100906816453,
        "impact_bps": -30.70175431489772,
        "net_bps": 1131.6451079886808,
        "slippage_bps": 0.0,
        "spread_bps": -19.177032112406323
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2025-01": 0.0,
        "2025-02": 0.0,
        "2025-03": 576.8706516259081,
        "2025-04": -808.1320193812653,
        "2025-05": 291.75655882371905,
        "2025-06": 726.2452149737662,
        "2025-07": 2499.847753792093,
        "2025-08": 434.6298278458683,
        "2025-09": -992.6557311194877,
        "2025-10": -672.0636264568125,
        "2025-11": 0.0,
        "2025-12": -924.853522115109
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": -252.11483768322614,
        "BCH-USDT": -2741.038484700936,
        "BTC-USDT": -223.8932414951455,
        "ETH-USDT": 962.2630448101675,
        "HYPE-USDT": 1662.7448461541428,
        "LINK-USDT": 1431.956117628484,
        "SOL-USDT": 291.72766327519406
      },
      "independent": false,
      "large_winners": {
        "T": 8,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 8878.295802308296,
        "capped_terminal_retention_hypothetical": 0.8278354687960143,
        "child_signed_terminal_bps": 11004.770613434805,
        "parent_positive_bps": 10724.71056986806,
        "profit_cut_bps": 1846.4147675597653,
        "realized_capped_retention_lower": 0.8278354687960143,
        "realized_capped_retention_upper": 0.8278354687960143,
        "signed_winner_deterioration_bps": 1846.4147675597653,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 1918.8052685722355,
          "cost_bps": 27.738409515277223,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 12.24,
          "gross_bps": 1974.28208760279,
          "impact_bps": 2.7017543148977197,
          "net_bps": 1946.5436780875127,
          "slippage_bps": 0.0,
          "spread_bps": 2.796655200379503
        },
        "child_hold_ms": 172800000,
        "delta": {
          "cost2x_net_bps": 1316.7947504553067,
          "cost_bps": 6.120000000000001,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 6.12,
          "gross_bps": 1329.0347504553067,
          "impact_bps": 0.0,
          "net_bps": 1322.9147504553066,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2025-07",
        "origin_key": "f8bbac66a79fa36955476264d2d7eb5f355b551a626f8dcc7d489aaa222417bc",
        "parent": {
          "cost2x_net_bps": 602.0105181169288,
          "cost_bps": 21.61840951527722,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 6.12,
          "gross_bps": 645.2473371474832,
          "impact_bps": 2.7017543148977197,
          "net_bps": 623.628927632206,
          "slippage_bps": 0.0,
          "spread_bps": 2.796655200379503
        },
        "parent_hold_ms": 86400000,
        "parent_large_winner": false,
        "parent_winner": true,
        "signal_ts": 1752091200000,
        "symbol": "1000PEPE-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 1.1690191042371731,
      "net_increment_without_largest_positive": -191.26964246662578,
      "ordinary_winners": {
        "T": 71,
        "additional_loss_after_winner_bps": 2848.7728977036013,
        "capped_terminal_preserved_bps_hypothetical": 10462.377647502082,
        "capped_terminal_retention_hypothetical": 0.6182937517848746,
        "child_signed_terminal_bps": 15270.070297311808,
        "parent_positive_bps": 16921.370493069935,
        "profit_cut_bps": 6458.992845567852,
        "realized_capped_retention_lower": 0.6182937517848746,
        "realized_capped_retention_upper": 0.6182937517848746,
        "signed_winner_deterioration_bps": 9307.765743271453,
        "winner_removed_T": 10,
        "winner_to_loss_T": 16,
        "winner_to_loss_origins": [
          "19f257381a58217a5939d7cd4c1c2c64d7cc5d907b7cd4abd9305f6b8f5a6231",
          "1ff9ecf8923813e16032eb997cf21c0a433aa549336677e36f6014fa56a77eb8",
          "225f2c0c74dec674d14dd2542a98b87735badb7593e5ebf32d4b6af32309c910",
          "3c5a14e98e97cdcc4ab2ccf38c7721973355239db90f0b8cf0fb15c355155599",
          "3f51205dc1796ad1adfeadc494bbd4c5863874e0c53ce7fcb48aea973063220e",
          "486f3c379524c1142a45fd11d3bcdb20f1bc53d8cdb01e7fb4e537126a14e582",
          "62f365c2e2f8d3aaa16b0b80129fcf63647dfbf23f6f92a3b2e8a751fd7efae3",
          "65096e09475306adc4c891c76c29c02fa99fab9a2e47244d727d0b96f00ca052",
          "651217e8d7efd041657b1e7a9c5bc7e59fb672d38ba02d4bac6014c41cf0fd35",
          "65ea9e92c1f61c7e9ffb6969d5d84c537ab2fc15a03ebbe9c0d0a732c731b284",
          "822d8ddf2416c697673994ade0628e3cc865edc859393fa9331567774a642bed",
          "9c81225d6f110ff12a13a07bcae870e54d6a1849e93a0b305fff7577a8eec6f3",
          "a0c5f502cb345b714fc91e81e9486695f0c1f236cb6348d8948d65c27b24a0f1",
          "b9bdb4c2b4b149a2d8e6a8832b0991c8121ea44e8054055c1744eb5651743083",
          "bea8aae7dd2b88f3b8fb0ac87118bf5e97847dbbebd228e32a400dd469eb5a56",
          "d8a4f2a22a84a15e76cf58b338e484119ccadf383e7993fa025f42b80aa20ab4"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "ABSENT_C": {
          "T": 3,
          "delta_bps": {
            "cost2x_net_bps": 160.72347978368882,
            "cost_bps": 61.38037691202682,
            "fee_bps": 30.0,
            "frozen_floor_reserve_bps": 5.0,
            "funding_bps": 15.0,
            "gross_bps": 283.4842336077425,
            "impact_bps": 6.0,
            "net_bps": 222.10385669571568,
            "slippage_bps": 0.0,
            "spread_bps": 5.3803769120268194
          }
        },
        "C_ABSENT": {
          "T": 18,
          "delta_bps": {
            "cost2x_net_bps": 2302.0535725554023,
            "cost_bps": -361.6184095152772,
            "fee_bps": -180.0,
            "frozen_floor_reserve_bps": -59.549246175946365,
            "funding_bps": -60.81,
            "gross_bps": 1578.8167535248476,
            "impact_bps": -36.70175431489772,
            "net_bps": 1940.435163040125,
            "slippage_bps": 0.0,
            "spread_bps": -24.55740902443314
          }
        },
        "C_C": {
          "T": 137,
          "delta_bps": {
            "cost2x_net_bps": -1090.7969270433737,
            "cost_bps": 59.90301529621456,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": -168.70698470378545,
            "funding_bps": 228.61,
            "gross_bps": -970.9908964509449,
            "impact_bps": 0.0,
            "net_bps": -1030.8939117471598,
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
      }
    }
  },
  "occupancy_bridge": {
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -772.370885674507,
      "full_total_effect": -772.370885674507
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 41.380376912026804,
      "full_total_effect": 41.380376912026804
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 20.0,
      "full_total_effect": 20.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 2.769999999999982,
      "full_total_effect": 2.769999999999982
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 10.230000000000018,
      "full_total_effect": 10.230000000000018
    },
    "gross_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -689.6101318504534,
      "full_total_effect": -689.6101318504534
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 4.0,
      "full_total_effect": 4.0
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -730.9905087624802,
      "full_total_effect": -730.9905087624802
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 4.380376912026804,
      "full_total_effect": 4.380376912026804
    }
  },
  "decision": {
    "FIXED": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": 0.0,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "REJECT",
      "exposure_delta_symbol_days": 0.0,
      "failed_checks": [
        "closed_net_increased",
        "terminal_net_increased",
        "positive_daily_delta95_lower",
        "no_unresolved_positions"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": 0.0,
      "increment_checks": {
        "closed_net_increased": false,
        "terminal_net_increased": false
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": true,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": false,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": 0.0
    },
    "FULL": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": -730.9905087624802,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "REJECT",
      "exposure_delta_symbol_days": 3.0,
      "failed_checks": [
        "closed_net_increased",
        "terminal_net_increased",
        "positive_daily_delta95_lower",
        "no_unresolved_positions"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": 0.0,
      "increment_checks": {
        "closed_net_increased": false,
        "terminal_net_increased": false
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": true,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": false,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": -730.9905087624802
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
      "child_marked_delta_sum_bps": 6654.829712721921,
      "child_minus_parent_95pct_interval_bps_per_day": [
        0.0,
        0.0
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        0.0,
        0.0
      ],
      "child_minus_parent_marked_delta_sum_bps": 0.0,
      "child_minus_parent_mean_daily_bps": 0.0,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 6654.829712721921,
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
      "child_marked_delta_sum_bps": 5923.83920395944,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -5.023598213988068,
        9.675475550775832e-15
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -1888.8729284595136,
        3.637978807091713e-12
      ],
      "child_minus_parent_marked_delta_sum_bps": -730.9905087624802,
      "child_minus_parent_mean_daily_bps": -1.9441236935172346,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 6654.829712721921,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    }
  }
}
```

### BR2 SEEN2026

| 지표 | BR1_FULL | FIXED | FULL | V2 |
|---|---:|---:|---:|---:|
| PF | 2.98 | 2.98 | 3.28 | 3.81 |
| closed_T | 46.00 | 46.00 | 47.00 | 52.00 |
| closed_cost2x_net_bps | 10,202.78 | 10,202.78 | 10,948.99 | 10,459.08 |
| closed_cost_bps | 952.84 | 952.84 | 974.30 | 1,049.71 |
| closed_fee_bps | 460.00 | 460.00 | 470.00 | 520.00 |
| closed_funding_bps | 267.68 | 267.68 | 279.14 | 188.25 |
| closed_gross_bps | 12,108.46 | 12,108.46 | 12,897.60 | 12,558.50 |
| closed_net_bps | 11,155.62 | 11,155.62 | 11,923.29 | 11,508.79 |
| entries_T | 46.00 | 46.00 | 47.00 | 52.00 |
| entries_per_30_days | 11.50 | 11.50 | 11.75 | 13.00 |
| exposure_symbol_days | 75.17 | 75.17 | 78.17 | 52.00 |
| grouped_max_loss_trade_sum_bps | 975.02 | 975.02 | 886.38 | 1,055.86 |
| marked_DD_trade_sum_bps | 2,152.30 | 2,152.30 | 1,620.24 | 1,167.64 |
| max_completed_recovery_days | 90.00 | 90.00 | 90.00 | 29.00 |
| max_simultaneous_symbols | 6.00 | 6.00 | 6.00 | 6.00 |
| mean_loss_bps | -245.14 | -245.14 | -227.77 | -256.33 |
| mean_win_bps | 730.16 | 730.16 | 715.09 | 433.61 |
| net_expectancy_bps_per_closed_trade | 242.51 | 242.51 | 253.69 | 221.32 |
| open_T | 0.00 | 0.00 | 0.00 | 0.00 |
| open_net_mark_bps_hypothetical | 0.00 | 0.00 | 0.00 | 0.00 |
| open_underwater_days | 14.00 | 14.00 | 14.00 | 14.00 |
| realized_payoff | 2.98 | 2.98 | 3.14 | 1.69 |
| terminal_cost2x_net_bps_hypothetical | 10,202.78 | 10,202.78 | 10,948.99 | 10,459.08 |
| terminal_net_bps_hypothetical | 11,155.62 | 11,155.62 | 11,923.29 | 11,508.79 |
| win_rate | 0.50 | 0.50 | 0.51 | 0.69 |

```json
{
  "terminal_all_cost_components": {
    "BR1_FULL": {
      "cost2x_net_bps": 10202.775126754566,
      "cost_bps": 952.8439321365202,
      "fee_bps": 460.0,
      "frozen_floor_reserve_bps": 54.42129939903678,
      "funding_bps": 267.68,
      "gross_bps": 12108.462991027607,
      "impact_bps": 95.5087715744886,
      "net_bps": 11155.619058891087,
      "slippage_bps": 0.0,
      "spread_bps": 75.23386116299483
    },
    "FIXED": {
      "cost2x_net_bps": 10202.775126754566,
      "cost_bps": 952.8439321365202,
      "fee_bps": 460.0,
      "frozen_floor_reserve_bps": 54.42129939903678,
      "funding_bps": 267.68,
      "gross_bps": 12108.462991027607,
      "impact_bps": 95.5087715744886,
      "net_bps": 11155.619058891087,
      "slippage_bps": 0.0,
      "spread_bps": 75.23386116299483
    },
    "FULL": {
      "cost2x_net_bps": 10948.988269883177,
      "cost_bps": 974.3039321365202,
      "fee_bps": 470.0,
      "frozen_floor_reserve_bps": 51.42129939903678,
      "funding_bps": 279.14,
      "gross_bps": 12897.596134156218,
      "impact_bps": 97.5087715744886,
      "net_bps": 11923.292202019698,
      "slippage_bps": 0.0,
      "spread_bps": 76.23386116299483
    },
    "V2": {
      "cost2x_net_bps": 10459.078593902392,
      "cost_bps": 1049.7104570916633,
      "fee_bps": 520.0,
      "frozen_floor_reserve_bps": 147.83903792687587,
      "funding_bps": 188.25,
      "gross_bps": 12558.499508085717,
      "impact_bps": 108.21052588938632,
      "net_bps": 11508.789050994055,
      "slippage_bps": 0.0,
      "spread_bps": 85.41089327540115
    }
  },
  "effects": {
    "BR1_FULL": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 746.2131431286109,
        "cost_bps": 21.46,
        "fee_bps": 10.0,
        "frozen_floor_reserve_bps": -3.0,
        "funding_bps": 11.46,
        "gross_bps": 789.1331431286109,
        "impact_bps": 2.0,
        "net_bps": 767.6731431286108,
        "slippage_bps": 0.0,
        "spread_bps": 1.0
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2026-05": 399.29246931703636,
        "2026-06": 0.0,
        "2026-07": 0.0,
        "2026-08": 368.3806738115745,
        "2026-09": 0.0
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 0.0,
        "BCH-USDT": 0.0,
        "BTC-USDT": 0.0,
        "ETH-USDT": 0.0,
        "HYPE-USDT": 709.6413169864344,
        "LINK-USDT": 0.0,
        "SOL-USDT": 58.03182614217644
      },
      "independent": false,
      "large_winners": {
        "T": 3,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 6682.813993770693,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 6682.813993770693,
        "parent_positive_bps": 6682.813993770693,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
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
        },
        "child_hold_ms": 0,
        "delta": {
          "cost2x_net_bps": 416.84070484581486,
          "cost_bps": -21.46,
          "fee_bps": -10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": -8.46,
          "gross_bps": 373.92070484581484,
          "impact_bps": -2.0,
          "net_bps": 395.3807048458148,
          "slippage_bps": 0.0,
          "spread_bps": -1.0
        },
        "entry_month": "2026-05",
        "origin_key": "6fcd9cabd94f7c0b3c97000580ba8c8b4288834a67e002bde524cdb187b95c13",
        "parent": {
          "cost2x_net_bps": -416.84070484581486,
          "cost_bps": 21.46,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 8.46,
          "gross_bps": -373.92070484581484,
          "impact_bps": 2.0,
          "net_bps": -395.3807048458148,
          "slippage_bps": 0.0,
          "spread_bps": 1.0
        },
        "parent_hold_ms": 158400000,
        "parent_large_winner": false,
        "parent_winner": false,
        "signal_ts": 1779336000000,
        "symbol": "HYPE-USDT",
        "transition": "C_ABSENT",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 0.5150378235644169,
      "net_increment_without_largest_positive": 372.292438282796,
      "ordinary_winners": {
        "T": 20,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 10110.916104554404,
        "capped_terminal_retention_hypothetical": 1.0,
        "child_signed_terminal_bps": 10110.916104554404,
        "parent_positive_bps": 10110.916104554404,
        "profit_cut_bps": 0.0,
        "realized_capped_retention_lower": 1.0,
        "realized_capped_retention_upper": 1.0,
        "signed_winner_deterioration_bps": 0.0,
        "winner_removed_T": 0,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "ABSENT_C": {
          "T": 3,
          "delta_bps": {
            "cost2x_net_bps": -41.23302628718254,
            "cost_bps": 62.92,
            "fee_bps": 30.0,
            "frozen_floor_reserve_bps": 1.0,
            "funding_bps": 22.92,
            "gross_bps": 84.60697371281748,
            "impact_bps": 6.0,
            "net_bps": 21.686973712817498,
            "slippage_bps": 0.0,
            "spread_bps": 3.0
          }
        },
        "C_ABSENT": {
          "T": 2,
          "delta_bps": {
            "cost2x_net_bps": 787.4461694157934,
            "cost_bps": -41.46,
            "fee_bps": -20.0,
            "frozen_floor_reserve_bps": -4.0,
            "funding_bps": -11.46,
            "gross_bps": 704.5261694157934,
            "impact_bps": -4.0,
            "net_bps": 745.9861694157934,
            "slippage_bps": 0.0,
            "spread_bps": -2.0
          }
        },
        "C_C": {
          "T": 44,
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
      }
    },
    "V2": {
      "absence_is_only_zero_contribution_not_zero_return_trade": true,
      "all_origin_terminal_delta_bps": {
        "cost2x_net_bps": 489.9096759807859,
        "cost_bps": -75.40652495514311,
        "fee_bps": -50.0,
        "frozen_floor_reserve_bps": -96.41773852783908,
        "funding_bps": 90.89,
        "gross_bps": 339.09662607049984,
        "impact_bps": -10.70175431489772,
        "net_bps": 414.5031510256432,
        "slippage_bps": 0.0,
        "spread_bps": -9.177032112406323
      },
      "cost_saving_already_in_net": true,
      "increment_by_entry_month": {
        "2026-05": -1052.0993928687863,
        "2026-06": -1361.1754441911987,
        "2026-07": -547.0201267156361,
        "2026-08": 3374.7981148012636,
        "2026-09": 0.0
      },
      "increment_by_symbol": {
        "1000PEPE-USDT": 627.7329983930866,
        "BCH-USDT": 40.31235684247798,
        "BTC-USDT": -243.56825045562584,
        "ETH-USDT": 183.54012121140636,
        "HYPE-USDT": -1688.1353784007715,
        "LINK-USDT": 1169.0799077820036,
        "SOL-USDT": 325.54139565306593
      },
      "independent": false,
      "large_winners": {
        "T": 4,
        "additional_loss_after_winner_bps": 0.0,
        "capped_terminal_preserved_bps_hypothetical": 4224.9122809846995,
        "capped_terminal_retention_hypothetical": 0.6934882181489441,
        "child_signed_terminal_bps": 6682.813993770693,
        "parent_positive_bps": 6092.262522154764,
        "profit_cut_bps": 1867.350241170065,
        "realized_capped_retention_lower": 0.6934882181489441,
        "realized_capped_retention_upper": 0.6934882181489441,
        "signed_winner_deterioration_bps": 1867.350241170065,
        "winner_removed_T": 1,
        "winner_to_loss_T": 0,
        "winner_to_loss_origins": []
      },
      "largest_positive_origin": {
        "child": {
          "cost2x_net_bps": 2647.860320926302,
          "cost_bps": 27.738409515277223,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 12.24,
          "gross_bps": 2703.3371399568564,
          "impact_bps": 2.7017543148977197,
          "net_bps": 2675.5987304415794,
          "slippage_bps": 0.0,
          "spread_bps": 2.796655200379503
        },
        "child_hold_ms": 172800000,
        "delta": {
          "cost2x_net_bps": 1493.9140413653065,
          "cost_bps": 6.120000000000001,
          "fee_bps": 0.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 6.12,
          "gross_bps": 1506.1540413653065,
          "impact_bps": 0.0,
          "net_bps": 1500.0340413653066,
          "slippage_bps": 0.0,
          "spread_bps": 0.0
        },
        "entry_month": "2026-08",
        "origin_key": "17d4a27cebb8baa5995fdc65905a280f56bed1873794b81c83f634ef94f3fabd",
        "parent": {
          "cost2x_net_bps": 1153.9462795609954,
          "cost_bps": 21.61840951527722,
          "fee_bps": 10.0,
          "frozen_floor_reserve_bps": 0.0,
          "funding_bps": 6.12,
          "gross_bps": 1197.1830985915499,
          "impact_bps": 2.7017543148977197,
          "net_bps": 1175.5646890762728,
          "slippage_bps": 0.0,
          "spread_bps": 2.796655200379503
        },
        "parent_hold_ms": 86400000,
        "parent_large_winner": true,
        "parent_winner": true,
        "signal_ts": 1787227200000,
        "symbol": "1000PEPE-USDT",
        "transition": "C_C",
        "winner_removed": false,
        "winner_to_loss": false
      },
      "largest_positive_share_of_net_increment": 3.618872468529213,
      "net_increment_without_largest_positive": -1085.5308903396635,
      "ordinary_winners": {
        "T": 32,
        "additional_loss_after_winner_bps": 1587.6946010380145,
        "capped_terminal_preserved_bps_hypothetical": 5548.343605378012,
        "capped_terminal_retention_hypothetical": 0.5829469321134326,
        "child_signed_terminal_bps": 8891.602177327964,
        "parent_positive_bps": 9517.75075865463,
        "profit_cut_bps": 3969.4071532766175,
        "realized_capped_retention_lower": 0.5829469321134326,
        "realized_capped_retention_upper": 0.5829469321134326,
        "signed_winner_deterioration_bps": 5557.101754314632,
        "winner_removed_T": 2,
        "winner_to_loss_T": 9,
        "winner_to_loss_origins": [
          "05f931d53335082784f715ab2aa3088c871c04a24ca1ed31708388aa34b61be7",
          "41b49e1212e6b7a059b6c722caf908846d3db6f7d912286f99f504f0ed638739",
          "5dc1f5cd16538e0bbd500c80985accfaef13c0d505283efc1c18902318637461",
          "5deda87e4f6bcedbe0ea537daa43aa3f1ddbb0c0baae482bb42dfe6e248bfe05",
          "7a46cbe9a3bd2b9f4c19702ebab06d13de1bb8d3ebac4861be8fe23783a16db0",
          "c178719029ba5f1afb830a8a38f760e70dabd79096684c440b48e83bc88e4828",
          "c4f4ac82b590d77483debb043cd0953c41e1ec3a4f47961a4b130135ae9074cb",
          "d75c5263f533b3220c2a50304972f05e7f0b194c15756101b21940e356c645c2",
          "f8e77d579fd3b97ab5104462ef77d5229516558eef7aa0fb8c0ced932d5bedf5"
        ]
      },
      "parity": "PASS",
      "post_outcome_diagnostic_only": true,
      "transition_groups": {
        "ABSENT_C": {
          "T": 1,
          "delta_bps": {
            "cost2x_net_bps": -75.58006167095492,
            "cost_bps": 21.46,
            "fee_bps": 10.0,
            "frozen_floor_reserve_bps": 0.0,
            "funding_bps": 8.46,
            "gross_bps": -32.66006167095492,
            "impact_bps": 2.0,
            "net_bps": -54.12006167095492,
            "slippage_bps": 0.0,
            "spread_bps": 1.0
          }
        },
        "C_ABSENT": {
          "T": 6,
          "delta_bps": {
            "cost2x_net_bps": -2793.9737795073797,
            "cost_bps": -121.61840951527722,
            "fee_bps": -60.0,
            "frozen_floor_reserve_bps": -16.38962308797318,
            "funding_bps": -22.35,
            "gross_bps": -3037.210598537934,
            "impact_bps": -12.70175431489772,
            "net_bps": -2915.592189022657,
            "slippage_bps": 0.0,
            "spread_bps": -10.177032112406323
          }
        },
        "C_C": {
          "T": 46,
          "delta_bps": {
            "cost2x_net_bps": 3359.4635171591203,
            "cost_bps": 24.7518845601341,
            "fee_bps": 0.0,
            "frozen_floor_reserve_bps": -80.0281154398659,
            "funding_bps": 104.78,
            "gross_bps": 3408.9672862793886,
            "impact_bps": 0.0,
            "net_bps": 3384.2154017192547,
            "slippage_bps": 0.0,
            "spread_bps": 0.0
          }
        }
      }
    }
  },
  "occupancy_bridge": {
    "cost2x_net_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 746.2131431286107,
      "full_total_effect": 746.2131431286107
    },
    "cost_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 21.460000000000036,
      "full_total_effect": 21.460000000000036
    },
    "fee_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 10.0,
      "full_total_effect": 10.0
    },
    "frozen_floor_reserve_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": -3.0,
      "full_total_effect": -3.0
    },
    "funding_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 11.45999999999998,
      "full_total_effect": 11.45999999999998
    },
    "gross_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 789.1331431286108,
      "full_total_effect": 789.1331431286108
    },
    "impact_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 2.0,
      "full_total_effect": 2.0
    },
    "net_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 767.6731431286116,
      "full_total_effect": 767.6731431286116
    },
    "slippage_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 0.0,
      "full_total_effect": 0.0
    },
    "spread_bps": {
      "fixed_path_or_filter_effect": 0.0,
      "full_occupancy_remainder": 1.0,
      "full_total_effect": 1.0
    }
  },
  "decision": {
    "FIXED": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": 0.0,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "REJECT",
      "exposure_delta_symbol_days": 0.0,
      "failed_checks": [
        "closed_net_increased",
        "terminal_net_increased",
        "positive_daily_delta95_lower"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": 0.0,
      "increment_checks": {
        "closed_net_increased": false,
        "terminal_net_increased": false
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": false,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": true,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": 0.0
    },
    "FULL": {
      "absolute_economic_checks": {
        "PF_above_one": true,
        "payoff_at_least_one": true,
        "positive_closed_cost2x_net": true,
        "positive_closed_net": true,
        "positive_expectancy": true
      },
      "closed_net_delta_bps": 767.6731431286116,
      "code_PASS_is_economic_PASS": false,
      "comparison_type": "EXIT_CHANGE",
      "decision": "TRADEOFF",
      "exposure_delta_symbol_days": 3.0,
      "failed_checks": [
        "positive_daily_delta95_lower"
      ],
      "formal_pass": false,
      "grouped_loss_run_delta_bps_descriptive": -88.63151373090341,
      "increment_checks": {
        "closed_net_increased": true,
        "terminal_net_increased": true
      },
      "independent": false,
      "loss_reduction": false,
      "open_censoring_blocks_strong_verdict": false,
      "operating_adoption": false,
      "risk_and_evidence_checks": {
        "grouped_loss_run_not_worse": true,
        "large_winner_amount_preserved": true,
        "marked_DD_not_worse": true,
        "no_unresolved_positions": true,
        "positive_daily_delta95_lower": false
      },
      "source_overlap_is_economic_gate": false,
      "terminal_net_delta_bps": 767.6731431286116
    }
  },
  "uncertainty": {
    "FIXED": {
      "N_effective": null,
      "approximate_calendar_blocks": 4.0,
      "block_days": 30,
      "calendar_days": 120,
      "calendar_last_day": "2026-09-04",
      "calendar_start": "2026-05-08",
      "child_marked_delta_sum_bps": 11155.619058891087,
      "child_minus_parent_95pct_interval_bps_per_day": [
        0.0,
        0.0
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        0.0,
        0.0
      ],
      "child_minus_parent_marked_delta_sum_bps": 0.0,
      "child_minus_parent_mean_daily_bps": 0.0,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 11155.619058891087,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    },
    "FULL": {
      "N_effective": null,
      "approximate_calendar_blocks": 4.0,
      "block_days": 30,
      "calendar_days": 120,
      "calendar_last_day": "2026-09-04",
      "calendar_start": "2026-05-08",
      "child_marked_delta_sum_bps": 11923.292202019698,
      "child_minus_parent_95pct_interval_bps_per_day": [
        -0.2058383648058225,
        9.467115141168215
      ],
      "child_minus_parent_95pct_interval_calendar_sum_bps": [
        -24.7006037766987,
        1136.0538169401857
      ],
      "child_minus_parent_marked_delta_sum_bps": 767.6731431286117,
      "child_minus_parent_mean_daily_bps": 6.397276192738431,
      "daily_unit": "UTC_DATE_BUCKET; FIRST_OR_LAST_MAY_BE_PARTIAL; NO_ANNUALIZATION",
      "independent": false,
      "limitations": "30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING",
      "method": "PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS",
      "parent_marked_delta_sum_bps": 11155.619058891087,
      "partial_native_edge_buckets_included": true,
      "resamples": 1000,
      "seed": 1178,
      "status": "COMPUTED"
    }
  }
}
```

