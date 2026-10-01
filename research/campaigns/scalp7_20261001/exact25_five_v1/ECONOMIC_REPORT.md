# 동결 5개 identity: 저장된 경제검증 결과

- 결과 상태: 저장 결과 독립 검산 완료 (경제 JSON 원본 보존). 독립 검산: PASS.
- 독립 감사: research/campaigns/scalp7_20261001/exact25_five_v1/audits/INDEPENDENT_ECONOMIC_AUDIT.json; 경제 JSON SHA256=b827d1eb818ee94c185af9d1c93eb06b758c31ade08a2b182c166a61081dfcaa; 감사 SHA256=0ca9f661c6d84bd49b52028d9515ba6ba161f178f783f553a74a93e788b40fc0.
- 경제 JSON의 PENDING 표시는 검산 전 생성단계를 보존한 값이다. 동일 JSON 해시에 결속된 별도 독립 감사 PASS를 확인한 뒤 이 문서만 갱신했다. 미확보 결과는 계속 미완료다.
- 저장 결과 확보: 5/5; 미확보: none.
- 펀딩 제외 연구 손익이며 단위는 USDT다. 펀딩은 미확인이고 0으로 간주하지 않는다. 과거 OHLC 체결모형과 기준 비용을 적용한 결과로, 실제 계좌 실현손익이 아니다.
- 비용 2x는 동일 체결·수량의 비용 재평가이며 추가 FULL 실행이 아니다. Gross·Net·Net/T의 단위는 USDT이므로 이전 일부 캠페인의 bps 값과 직접 혼용하지 않는다.
- T·WR·Gross·Net·Net/T·PF·MaxLS는 결과가 확인된 종료 거래만 집계한다. 완결=no이면 일부 확인 거래의 성과이고 전체 성과는 확정하지 않는다. null은 미확인·산출 불가 상태를 보존한다.
- DD는 저장된 last-price 계좌 평가곡선의 표본에서 산출한다. 거래 손익 누적합으로 대체하지 않는다. 초반 일부 곡선만 있으면 전체 DD는 null이고 해당 구간 DD를 따로 표시한다.
- 이미 검토된 개발용 과거자료이며 fresh T=0이다. 원래 25개와 미완료 19개를 보존한다. 이번 배치 완료는 원래 25개 또는 G4 전체 완료가 아니다.
- NOISE_BASELINE은 독립 대조군이다. GMMA/TrendRider 부모 대비 개선으로 해석하지 않는다. 주문·LIVE·공식 승격은 계속 차단한다.

## Validation 30일

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 217 | 7.233 | 33.641 | -2018.595 | -2441.844 | -11.253 | 0.430 | null | 14 | 6 | 0 | no |
| NOISE_BASELINE | 2x | 217 | 7.233 | 29.032 | -2018.595 | -2865.094 | -13.203 | 0.374 | null | 18 | 6 | 0 | no |
| SR_CONTROL | 1x | 110 | 3.667 | 20.000 | -152.245 | -243.393 | -2.213 | 0.406 | 2.965 | 24 | 0 | 0 | yes |
| SR_CONTROL | 2x | 110 | 3.667 | 19.091 | -152.245 | -334.542 | -3.041 | 0.308 | 3.783 | 24 | 0 | 0 | yes |
| SR_RETEST | 1x | 49 | 1.633 | 10.204 | -96.634 | -142.003 | -2.898 | 0.296 | 1.537 | 21 | 0 | 0 | yes |
| SR_RETEST | 2x | 49 | 1.633 | 10.204 | -96.634 | -187.373 | -3.824 | 0.229 | 1.949 | 21 | 0 | 0 | yes |
| ST_CONTROL | 1x | 81 | 2.700 | 25.926 | -260.951 | -466.683 | -5.762 | 0.397 | 4.809 | 24 | 0 | 0 | yes |
| ST_CONTROL | 2x | 81 | 2.700 | 23.457 | -260.951 | -672.415 | -8.301 | 0.277 | 6.840 | 24 | 0 | 0 | yes |
| ST_TRAIL | 1x | 81 | 2.700 | 25.926 | -237.390 | -443.596 | -5.476 | 0.400 | 4.578 | 24 | 0 | 0 | yes |
| ST_TRAIL | 2x | 81 | 2.700 | 22.222 | -237.390 | -649.802 | -8.022 | 0.277 | 6.615 | 24 | 0 | 0 | yes |

## Rolling 245일: 종료 결과를 사후 확인한 진입 거래 집합

이 합산에는 진입한 창의 종료 시점에는 열려 있었고 이후 창에서 종료된 거래도 포함된다. 각 창 종료 시점에 알 수 있던 OOS 성과나 9개 창의 단순 합계로 해석하지 않는다. 경계 통과·미종료 거래와 미해결 실행은 별도 보존하고 결측 결과를 0으로 바꾸지 않는다.

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 230 | 0.939 | 46.957 | 1747.198 | 1305.419 | 5.676 | 1.290 | null | 23 | 6 | 6 | no |
| NOISE_BASELINE | 2x | 230 | 0.939 | 45.217 | 1747.198 | 863.640 | 3.755 | 1.182 | null | 23 | 6 | 6 | no |
| SR_CONTROL | 1x | 123 | 0.502 | 27.642 | 408.966 | 335.629 | 2.729 | 2.026 | null | 18 | 6 | 0 | no |
| SR_CONTROL | 2x | 123 | 0.502 | 27.642 | 408.966 | 262.291 | 2.132 | 1.695 | null | 18 | 6 | 0 | no |
| SR_RETEST | 1x | 287 | 1.171 | 21.951 | 391.706 | 200.211 | 0.698 | 1.276 | null | 16 | 2 | 0 | no |
| SR_RETEST | 2x | 287 | 1.171 | 21.603 | 391.706 | 8.716 | 0.030 | 1.010 | null | 16 | 2 | 0 | no |
| ST_CONTROL | 1x | 549 | 2.241 | 27.687 | 356.721 | -743.486 | -1.354 | 0.803 | null | 19 | 1 | 0 | no |
| ST_CONTROL | 2x | 549 | 2.241 | 22.587 | 356.721 | -1843.692 | -3.358 | 0.599 | null | 27 | 1 | 0 | no |
| ST_TRAIL | 1x | 549 | 2.241 | 28.415 | 378.656 | -731.149 | -1.332 | 0.803 | null | 19 | 1 | 0 | no |
| ST_TRAIL | 2x | 549 | 2.241 | 22.769 | 378.656 | -1840.954 | -3.353 | 0.594 | null | 27 | 1 | 0 | no |

| Identity | 비용 | 이후 창 종료 포함 | 9개 창 T 합계 | 사후 합산 T | 미해결 실행 |
|---|---|---:|---:|---:|---:|
| NOISE_BASELINE | 1x | 6 | 224 | 230 | 6 |
| NOISE_BASELINE | 2x | 6 | 224 | 230 | 6 |
| SR_CONTROL | 1x | 0 | 123 | 123 | 6 |
| SR_CONTROL | 2x | 0 | 123 | 123 | 6 |
| SR_RETEST | 1x | 0 | 287 | 287 | 2 |
| SR_RETEST | 2x | 0 | 287 | 287 | 2 |
| ST_CONTROL | 1x | 0 | 549 | 549 | 1 |
| ST_CONTROL | 2x | 0 | 549 | 549 | 1 |
| ST_TRAIL | 1x | 0 | 549 | 549 | 1 |
| ST_TRAIL | 2x | 0 | 549 | 549 | 1 |

## 원래 동결된 Rolling 9개 창


### rolling_1: 2026-01-13T00:00:00+00:00 to 2026-02-12T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 215 | 7.167 | 46.977 | 1900.681 | 1489.849 | 6.930 | 1.357 | null | 23 | 6 | 6 | no |
| NOISE_BASELINE | 2x | 215 | 7.167 | 45.581 | 1900.681 | 1079.017 | 5.019 | 1.245 | null | 23 | 6 | 6 | no |
| SR_CONTROL | 1x | 120 | 4.000 | 28.333 | 413.963 | 342.140 | 2.851 | 2.067 | 0.964 | 18 | 0 | 0 | yes |
| SR_CONTROL | 2x | 120 | 4.000 | 28.333 | 413.963 | 270.317 | 2.253 | 1.732 | 1.047 | 18 | 0 | 0 | yes |
| SR_RETEST | 1x | 51 | 1.700 | 39.216 | 346.842 | 312.477 | 6.127 | 3.957 | 0.669 | 8 | 0 | 0 | yes |
| SR_RETEST | 2x | 51 | 1.700 | 39.216 | 346.842 | 278.112 | 5.453 | 3.204 | 0.732 | 8 | 0 | 0 | yes |
| ST_CONTROL | 1x | 68 | 2.267 | 19.118 | -64.335 | -220.121 | -3.237 | 0.651 | 3.380 | 17 | 0 | 0 | yes |
| ST_CONTROL | 2x | 68 | 2.267 | 17.647 | -64.335 | -375.907 | -5.528 | 0.503 | 4.568 | 17 | 0 | 0 | yes |
| ST_TRAIL | 1x | 68 | 2.267 | 20.588 | -51.079 | -207.320 | -3.049 | 0.665 | 3.380 | 17 | 0 | 0 | yes |
| ST_TRAIL | 2x | 68 | 2.267 | 17.647 | -51.079 | -363.562 | -5.346 | 0.512 | 4.427 | 17 | 0 | 0 | yes |

### rolling_2: 2026-02-12T00:00:00+00:00 to 2026-03-14T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 9 | 0.300 | 22.222 | -273.515 | -292.141 | -32.460 | 0.055 | null | 5 | 6 | 6 | no |
| NOISE_BASELINE | 2x | 9 | 0.300 | 22.222 | -273.515 | -310.767 | -34.530 | 0.040 | null | 5 | 6 | 6 | no |
| SR_CONTROL | 1x | 3 | 0.100 | 0.000 | -4.996 | -6.511 | -2.170 | 0.000 | null | 3 | 6 | 0 | no |
| SR_CONTROL | 2x | 3 | 0.100 | 0.000 | -4.996 | -8.026 | -2.675 | 0.000 | null | 3 | 6 | 0 | no |
| SR_RETEST | 1x | 34 | 1.133 | 20.588 | 1.621 | -15.964 | -0.470 | 0.782 | null | 6 | 2 | 0 | no |
| SR_RETEST | 2x | 34 | 1.133 | 20.588 | 1.621 | -33.549 | -0.987 | 0.613 | null | 6 | 2 | 0 | no |
| ST_CONTROL | 1x | 71 | 2.367 | 30.986 | 53.736 | -85.747 | -1.208 | 0.854 | null | 7 | 1 | 0 | no |
| ST_CONTROL | 2x | 71 | 2.367 | 21.127 | 53.736 | -225.230 | -3.172 | 0.676 | null | 12 | 1 | 0 | no |
| ST_TRAIL | 1x | 71 | 2.367 | 30.986 | 63.659 | -76.419 | -1.076 | 0.870 | null | 7 | 1 | 0 | no |
| ST_TRAIL | 2x | 71 | 2.367 | 22.535 | 63.659 | -216.498 | -3.049 | 0.688 | null | 8 | 1 | 0 | no |

### rolling_3: 2026-03-14T00:00:00+00:00 to 2026-04-13T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| NOISE_BASELINE | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_RETEST | 1x | 31 | 1.033 | 25.806 | 26.989 | 7.358 | 0.237 | 1.107 | null | 7 | 0 | 2 | no |
| SR_RETEST | 2x | 31 | 1.033 | 25.806 | 26.989 | -12.272 | -0.396 | 0.852 | null | 7 | 0 | 2 | no |
| ST_CONTROL | 1x | 56 | 1.867 | 23.214 | 56.680 | -61.397 | -1.096 | 0.841 | null | 13 | 0 | 1 | no |
| ST_CONTROL | 2x | 56 | 1.867 | 21.429 | 56.680 | -179.474 | -3.205 | 0.626 | null | 13 | 0 | 1 | no |
| ST_TRAIL | 1x | 56 | 1.867 | 25.000 | 70.130 | -48.672 | -0.869 | 0.873 | null | 9 | 0 | 1 | no |
| ST_TRAIL | 2x | 56 | 1.867 | 21.429 | 70.130 | -167.475 | -2.991 | 0.646 | null | 13 | 0 | 1 | no |

### rolling_4: 2026-04-13T00:00:00+00:00 to 2026-05-13T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| NOISE_BASELINE | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_RETEST | 1x | 39 | 1.300 | 10.256 | -87.762 | -116.662 | -2.991 | 0.165 | null | 14 | 0 | 2 | no |
| SR_RETEST | 2x | 39 | 1.300 | 10.256 | -87.762 | -145.561 | -3.732 | 0.122 | null | 14 | 0 | 2 | no |
| ST_CONTROL | 1x | 69 | 2.300 | 27.536 | 0.582 | -133.692 | -1.938 | 0.674 | null | 13 | 0 | 1 | no |
| ST_CONTROL | 2x | 69 | 2.300 | 24.638 | 0.582 | -267.966 | -3.884 | 0.469 | null | 13 | 0 | 1 | no |
| ST_TRAIL | 1x | 69 | 2.300 | 27.536 | 24.105 | -111.215 | -1.612 | 0.725 | null | 13 | 0 | 1 | no |
| ST_TRAIL | 2x | 69 | 2.300 | 24.638 | 24.105 | -246.535 | -3.573 | 0.507 | null | 13 | 0 | 1 | no |

### rolling_5: 2026-05-13T00:00:00+00:00 to 2026-06-12T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| NOISE_BASELINE | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_RETEST | 1x | 33 | 1.100 | 18.182 | -13.632 | -33.167 | -1.005 | 0.587 | null | 11 | 0 | 2 | no |
| SR_RETEST | 2x | 33 | 1.100 | 18.182 | -13.632 | -52.702 | -1.597 | 0.455 | null | 11 | 0 | 2 | no |
| ST_CONTROL | 1x | 64 | 2.133 | 35.938 | 167.270 | 41.402 | 0.647 | 1.096 | null | 11 | 0 | 1 | no |
| ST_CONTROL | 2x | 64 | 2.133 | 29.688 | 167.270 | -84.465 | -1.320 | 0.837 | null | 12 | 0 | 1 | no |
| ST_TRAIL | 1x | 64 | 2.133 | 37.500 | 176.741 | 49.195 | 0.769 | 1.119 | null | 11 | 0 | 1 | no |
| ST_TRAIL | 2x | 64 | 2.133 | 29.688 | 176.741 | -78.352 | -1.224 | 0.843 | null | 12 | 0 | 1 | no |

### rolling_6: 2026-06-12T00:00:00+00:00 to 2026-07-12T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| NOISE_BASELINE | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_RETEST | 1x | 39 | 1.300 | 12.821 | -59.963 | -84.792 | -2.174 | 0.197 | null | 11 | 0 | 2 | no |
| SR_RETEST | 2x | 39 | 1.300 | 12.821 | -59.963 | -109.622 | -2.811 | 0.138 | null | 11 | 0 | 2 | no |
| ST_CONTROL | 1x | 65 | 2.167 | 30.769 | -67.223 | -190.109 | -2.925 | 0.548 | null | 8 | 0 | 1 | no |
| ST_CONTROL | 2x | 65 | 2.167 | 23.077 | -67.223 | -312.995 | -4.815 | 0.385 | null | 14 | 0 | 1 | no |
| ST_TRAIL | 1x | 65 | 2.167 | 32.308 | -74.979 | -200.288 | -3.081 | 0.500 | null | 8 | 0 | 1 | no |
| ST_TRAIL | 2x | 65 | 2.167 | 24.615 | -74.979 | -325.597 | -5.009 | 0.333 | null | 14 | 0 | 1 | no |

### rolling_7: 2026-07-12T00:00:00+00:00 to 2026-08-11T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| NOISE_BASELINE | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_RETEST | 1x | 29 | 0.967 | 10.345 | -45.688 | -70.006 | -2.414 | 0.101 | null | 12 | 0 | 2 | no |
| SR_RETEST | 2x | 29 | 0.967 | 6.897 | -45.688 | -94.325 | -3.253 | 0.060 | null | 12 | 0 | 2 | no |
| ST_CONTROL | 1x | 66 | 2.200 | 21.212 | -65.594 | -196.788 | -2.982 | 0.465 | null | 18 | 0 | 1 | no |
| ST_CONTROL | 2x | 66 | 2.200 | 13.636 | -65.594 | -327.983 | -4.969 | 0.313 | null | 23 | 0 | 1 | no |
| ST_TRAIL | 1x | 66 | 2.200 | 22.727 | -60.475 | -193.061 | -2.925 | 0.476 | null | 18 | 0 | 1 | no |
| ST_TRAIL | 2x | 66 | 2.200 | 13.636 | -60.475 | -325.647 | -4.934 | 0.317 | null | 23 | 0 | 1 | no |

### rolling_8: 2026-08-11T00:00:00+00:00 to 2026-09-10T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| NOISE_BASELINE | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_RETEST | 1x | 25 | 0.833 | 40.000 | 248.276 | 231.295 | 9.252 | 6.203 | null | 5 | 0 | 2 | no |
| SR_RETEST | 2x | 25 | 0.833 | 40.000 | 248.276 | 214.314 | 8.573 | 5.007 | null | 5 | 0 | 2 | no |
| ST_CONTROL | 1x | 78 | 2.600 | 33.333 | 328.091 | 176.739 | 2.266 | 1.397 | null | 8 | 0 | 1 | no |
| ST_CONTROL | 2x | 78 | 2.600 | 29.487 | 328.091 | 25.386 | 0.325 | 1.046 | null | 15 | 0 | 1 | no |
| ST_TRAIL | 1x | 78 | 2.600 | 32.051 | 281.869 | 129.318 | 1.658 | 1.288 | null | 8 | 0 | 1 | no |
| ST_TRAIL | 2x | 78 | 2.600 | 28.205 | 281.869 | -23.233 | -0.298 | 0.958 | null | 15 | 0 | 1 | no |

### rolling_9: 2026-09-10T00:00:00+00:00 to 2026-09-15T00:00:00+00:00 (종료 시각 제외)

| Identity | 비용 | T | T/day | WR % | Gross USDT | Net USDT | Net/T USDT | PF | DD % | MaxLS 연패 | 경계통과·미종료 | 이전 창 이월 | 완결 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NOISE_BASELINE | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| NOISE_BASELINE | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 1x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_CONTROL | 2x | 0 | 0.000 | null | 0 | 0 | null | null | null | null | 0 | 6 | no |
| SR_RETEST | 1x | 6 | 1.200 | 0.000 | -24.977 | -30.328 | -5.055 | 0.000 | null | 6 | 0 | 2 | no |
| SR_RETEST | 2x | 6 | 1.200 | 0.000 | -24.977 | -35.678 | -5.946 | 0.000 | null | 6 | 0 | 2 | no |
| ST_CONTROL | 1x | 12 | 2.400 | 16.667 | -52.486 | -73.772 | -6.148 | 0.123 | null | 10 | 0 | 1 | no |
| ST_CONTROL | 2x | 12 | 2.400 | 16.667 | -52.486 | -95.058 | -7.922 | 0.082 | null | 10 | 0 | 1 | no |
| ST_TRAIL | 1x | 12 | 2.400 | 16.667 | -51.316 | -72.686 | -6.057 | 0.139 | null | 10 | 0 | 1 | no |
| ST_TRAIL | 2x | 12 | 2.400 | 16.667 | -51.316 | -94.056 | -7.838 | 0.095 | null | 10 | 0 | 1 | no |

## 확인된 종료 거래의 tail·hold·집중도

각 값은 해당 비용 시나리오의 결과 확인 종료 거래만 사용한다. 미해결·미종료 거래는 포함하지 않으므로 불완결 구간의 전체 위험으로 해석하지 않는다. 1x/2x는 체결·보유시간이 같고 비용 차이에 따라 손실·승리 분류와 이익 기여도가 달라진다.
정의: 최악 거래=min(Net). 손실 tail=음수 거래 중 가장 나쁜 ceil(5%) 평균. ES5=모든 거래 중 가장 나쁜 ceil(5%) 평균. hold는 (실제 종료시각−진입시각)/분이며 p95는 (n−1)×0.95 위치의 선형보간이다. T/day는 달력 일수 기준이다. 통계 정의는 기존 scalp7_metrics_v2를 따르되 이번 단위는 USDT이며 이번 동결 진입시각 코호트를 사용한다.
집중도는 개별 양수 Net의 합을 분모로 사용하며 음수 집단도 JSON에 보존한다. 월은 결과 확인 시각 UTC, 세션은 진입 UTC의 00–08/08–16/16–24시 구분이다. 아래는 validation과 rolling 사후 합산이며 9개 원래 창의 세부 통계·모든 그룹은 ECONOMIC_COMPARISON.json의 descriptive_risk에 있다.

| Identity | 구간 | 비용 | 완결 | T/day | 최악 Net USDT | 손실 tail5 USDT | ES5 USDT | 평균 hold 분 | 중앙 hold 분 | p95 hold 분 | 최대승리 이익기여 % |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NOISE_BASELINE | validation30d | 1x | no | 7.233 | -136.749 | -97.083 | -90.800 | 823.903 | 870.000 | 1410.000 | 8.489 |
| NOISE_BASELINE | rolling245d 사후합산 | 1x | no | 0.939 | -198.702 | -122.164 | -108.175 | 888.787 | 930.000 | 1410.000 | 4.795 |
| NOISE_BASELINE | validation30d | 2x | no | 7.233 | -139.119 | -99.366 | -93.027 | 823.903 | 870.000 | 1410.000 | 9.016 |
| NOISE_BASELINE | rolling245d 사후합산 | 2x | no | 0.939 | -200.992 | -124.546 | -110.438 | 888.787 | 930.000 | 1410.000 | 4.923 |
| SR_CONTROL | validation30d | 1x | yes | 3.667 | -16.450 | -15.304 | -14.438 | 280.218 | 120.000 | 966.000 | 15.108 |
| SR_CONTROL | rolling245d 사후합산 | 1x | no | 0.502 | -12.498 | -10.048 | -9.392 | 403.171 | 90.000 | 1347.000 | 7.624 |
| SR_CONTROL | validation30d | 2x | yes | 3.667 | -17.645 | -16.025 | -15.229 | 280.218 | 120.000 | 966.000 | 16.023 |
| SR_CONTROL | rolling245d 사후합산 | 2x | no | 0.502 | -13.667 | -10.838 | -10.103 | 403.171 | 90.000 | 1347.000 | 7.838 |
| SR_RETEST | validation30d | 1x | yes | 1.633 | -22.445 | -17.258 | -17.258 | 235.388 | 90.000 | 708.000 | 59.875 |
| SR_RETEST | rolling245d 사후합산 | 1x | no | 1.171 | -13.810 | -10.570 | -9.890 | 304.599 | 150.000 | 1200.000 | 7.303 |
| SR_RETEST | validation30d | 2x | yes | 1.633 | -23.831 | -18.387 | -18.387 | 235.388 | 90.000 | 708.000 | 63.191 |
| SR_RETEST | rolling245d 사후합산 | 2x | no | 1.171 | -14.844 | -11.411 | -10.697 | 304.599 | 150.000 | 1200.000 | 7.546 |
| ST_CONTROL | validation30d | 1x | yes | 2.700 | -27.568 | -27.071 | -25.510 | 240.691 | 162.000 | 900.000 | 28.673 |
| ST_CONTROL | rolling245d 사후합산 | 1x | no | 2.241 | -26.364 | -22.213 | -21.466 | 270.089 | 180.000 | 900.000 | 5.534 |
| ST_CONTROL | validation30d | 2x | yes | 2.700 | -30.770 | -29.181 | -28.506 | 240.691 | 162.000 | 900.000 | 32.812 |
| ST_CONTROL | rolling245d 사후합산 | 2x | no | 2.241 | -29.357 | -24.533 | -23.994 | 270.089 | 180.000 | 900.000 | 5.984 |
| ST_TRAIL | validation30d | 1x | yes | 2.700 | -27.571 | -27.112 | -25.535 | 235.617 | 162.000 | 900.000 | 29.689 |
| ST_TRAIL | rolling245d 사후합산 | 1x | no | 2.241 | -26.447 | -22.289 | -21.560 | 265.342 | 180.000 | 860.400 | 5.642 |
| ST_TRAIL | validation30d | 2x | yes | 2.700 | -30.773 | -29.215 | -28.533 | 235.617 | 162.000 | 900.000 | 33.856 |
| ST_TRAIL | rolling245d 사후합산 | 2x | no | 2.241 | -29.470 | -24.665 | -24.085 | 265.342 | 180.000 | 860.400 | 6.131 |

| Identity | 구간 | 비용 | 최대 심볼 이익기여 | 최대 월 이익기여 | 최대 세션 이익기여 | 최대 심볼 거래비중 |
|---|---|---|---|---|---|---|
| NOISE_BASELINE | validation30d | 1x | XRP-USDT 24.872% | 2026-01 69.888% | UTC_00_08 78.990% | DOGE-USDT 20.276% |
| NOISE_BASELINE | rolling245d 사후합산 | 1x | ETH-USDT 23.396% | 2026-02 65.923% | UTC_00_08 80.736% | BTC-USDT,ETH-USDT 18.261% |
| NOISE_BASELINE | validation30d | 2x | XRP-USDT 25.384% | 2026-01 70.986% | UTC_00_08 79.556% | DOGE-USDT 20.276% |
| NOISE_BASELINE | rolling245d 사후합산 | 2x | ETH-USDT 23.470% | 2026-02 66.391% | UTC_00_08 81.013% | BTC-USDT,ETH-USDT 18.261% |
| SR_CONTROL | validation30d | 1x | DOGE-USDT 46.731% | 2026-01 53.582% | UTC_08_16 49.316% | DOGE-USDT 18.182% |
| SR_CONTROL | rolling245d 사후합산 | 1x | XRP-USDT 22.851% | 2026-01 82.239% | UTC_00_08 78.428% | ETH-USDT 18.699% |
| SR_CONTROL | validation30d | 2x | DOGE-USDT 48.944% | 2026-01 54.618% | UTC_08_16 48.491% | DOGE-USDT 18.182% |
| SR_CONTROL | rolling245d 사후합산 | 2x | XRP-USDT 22.944% | 2026-01 82.048% | UTC_00_08 78.682% | ETH-USDT 18.699% |
| SR_RETEST | validation30d | 1x | DOGE-USDT 69.926% | 2026-01 84.347% | UTC_00_08 74.297% | DOGE-USDT,XRP-USDT 20.408% |
| SR_RETEST | rolling245d 사후합산 | 1x | SOL-USDT 24.369% | 2026-01 32.627% | UTC_00_08 56.873% | LINK-USDT 24.042% |
| SR_RETEST | validation30d | 2x | DOGE-USDT 72.948% | 2026-01 86.608% | UTC_00_08 76.851% | DOGE-USDT,XRP-USDT 20.408% |
| SR_RETEST | rolling245d 사후합산 | 2x | SOL-USDT 24.418% | 2026-01 32.950% | UTC_00_08 57.419% | LINK-USDT 24.042% |
| ST_CONTROL | validation30d | 1x | XRP-USDT 57.219% | 2025-12 60.106% | UTC_00_08 49.272% | BTC-USDT 22.222% |
| ST_CONTROL | rolling245d 사후합산 | 1x | DOGE-USDT 27.245% | 2026-02 20.164% | UTC_08_16 46.285% | LINK-USDT 20.583% |
| ST_CONTROL | validation30d | 2x | XRP-USDT 63.625% | 2025-12 59.770% | UTC_00_08 54.543% | BTC-USDT 22.222% |
| ST_CONTROL | rolling245d 사후합산 | 2x | DOGE-USDT 27.497% | 2026-02 21.164% | UTC_08_16 47.560% | LINK-USDT 20.583% |
| ST_TRAIL | validation30d | 1x | XRP-USDT 59.420% | 2025-12 67.734% | UTC_00_08 53.761% | BTC-USDT 22.222% |
| ST_TRAIL | rolling245d 사후합산 | 1x | DOGE-USDT 26.541% | 2026-02 20.574% | UTC_08_16 47.928% | LINK-USDT 20.583% |
| ST_TRAIL | validation30d | 2x | XRP-USDT 65.841% | 2025-12 66.574% | UTC_00_08 59.359% | BTC-USDT 22.222% |
| ST_TRAIL | rolling245d 사후합산 | 2x | DOGE-USDT 26.872% | 2026-02 21.684% | UTC_08_16 49.431% | LINK-USDT 20.583% |

## 저장된 계좌 평가곡선의 DD

| Identity | 비용 | 전체 DD % | 확인된 초반 구간 DD % | 마지막 평가 시각 UTC | 평가 표본 수 |
|---|---|---:|---:|---|---:|
| NOISE_BASELINE | 1x | null | 26.529 | 2026-02-13T20:30:00+00:00 | 7290 |
| NOISE_BASELINE | 2x | null | 32.028 | 2026-02-13T20:30:00+00:00 | 7290 |
| SR_CONTROL | 1x | null | 3.035 | 2026-02-13T20:30:00+00:00 | 7290 |
| SR_CONTROL | 2x | null | 3.876 | 2026-02-13T20:30:00+00:00 | 7290 |
| SR_RETEST | 1x | null | 1.546 | 2026-02-13T20:30:00+00:00 | 7290 |
| SR_RETEST | 2x | null | 1.965 | 2026-02-13T20:30:00+00:00 | 7290 |
| ST_CONTROL | 1x | null | 7.751 | 2026-02-13T20:30:00+00:00 | 7290 |
| ST_CONTROL | 2x | null | 11.450 | 2026-02-13T20:30:00+00:00 | 7290 |
| ST_TRAIL | 1x | null | 7.396 | 2026-02-13T20:30:00+00:00 | 7290 |
| ST_TRAIL | 2x | null | 11.104 | 2026-02-13T20:30:00+00:00 | 7290 |

## 동결된 대조군 비교와 승리 훼손

승리 훼손은 부모·자식이 모두 완결된 원래 창에서만 계산한다. 이익 보존율에는 자식의 양수 이익만 들어가므로 손실 전환·진입 부재도 함께 표시한다. SR은 고정 일별 기준을 공유하는 셋업으로 대응하며 진입 시각이 같다는 뜻은 아니다. 불완결 창의 합산 승리 훼손은 산출하지 않는다.

| 비교 | 비용 | 창 | 완결 | ΔT | ΔWR %p | ΔNet USDT | ΔDD %p | 부모 승리 | 자식 양수·음수·부재 | 승리집합 ΔNet USDT | 양수 이익 보존 % |
|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| SR_CONTROL_vs_SR_RETEST | 1x | validation | yes | -61 | -9.796 | 101.390 | -1.428 | 22 | 5/1/16 | -107.430 | 35.902 |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_1 | yes | -69 | 10.882 | -29.663 | -0.295 | 34 | 20/1/13 | -244.813 | 63.079 |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_2 | no | 31 | 20.588 | -9.453 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_3 | no | 31 | null | 7.358 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_4 | no | 39 | null | -116.662 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_5 | no | 33 | null | -33.167 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_6 | no | 39 | null | -84.792 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_7 | no | 29 | null | -70.006 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_8 | no | 25 | null | 231.295 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 1x | rolling_9 | no | 6 | null | -30.328 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | validation | yes | -61 | -8.887 | 147.169 | -1.833 | 21 | 5/1/15 | -94.758 | 37.405 |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_1 | yes | -69 | 10.882 | 7.795 | -0.315 | 34 | 20/1/13 | -236.393 | 63.208 |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_2 | no | 31 | 20.588 | -25.523 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_3 | no | 31 | null | -12.272 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_4 | no | 39 | null | -145.561 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_5 | no | 33 | null | -52.702 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_6 | no | 39 | null | -109.622 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_7 | no | 29 | null | -94.325 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_8 | no | 25 | null | 214.314 | null | null | null | null | null |
| SR_CONTROL_vs_SR_RETEST | 2x | rolling_9 | no | 6 | null | -35.678 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | validation | yes | 0 | 0.000 | 23.087 | -0.231 | 21 | 19/2/0 | -36.014 | 91.334 |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_1 | yes | 0 | 1.471 | 12.801 | 0.000 | 13 | 13/0/0 | 1.280 | 100.312 |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_2 | no | 0 | 0.000 | 9.327 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_3 | no | 0 | 1.786 | 12.725 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_4 | no | 0 | 0.000 | 22.477 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_5 | no | 0 | 1.562 | 7.792 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_6 | no | 0 | 1.538 | -10.179 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_7 | no | 0 | 1.515 | 3.727 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_8 | no | 0 | -1.282 | -47.421 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 1x | rolling_9 | no | 0 | 0.000 | 1.086 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | validation | yes | 0 | -1.235 | 22.613 | -0.226 | 19 | 17/2/0 | -36.178 | 92.211 |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_1 | yes | 0 | 0.000 | 12.345 | -0.141 | 12 | 12/0/0 | 1.192 | 100.313 |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_2 | no | 0 | 1.408 | 8.731 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_3 | no | 0 | 0.000 | 12.000 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_4 | no | 0 | 0.000 | 21.431 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_5 | no | 0 | 0.000 | 6.113 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_6 | no | 0 | 1.538 | -12.602 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_7 | no | 0 | 0.000 | 2.336 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_8 | no | 0 | -1.282 | -48.619 | null | null | null | null | null |
| ST_CONTROL_vs_ST_TRAIL | 2x | rolling_9 | no | 0 | 0.000 | 1.003 | null | null | null | null | null |

## 저장 근거

| Identity | 원본 JSON SHA256 | 저장 파일 |
|---|---|---|
| NOISE_BASELINE | 391ad9e2bfa2988ef964012cae4aa538ff4c86c5195f330c08c379cc207719d7 | research/campaigns/scalp7_20261001/exact25_five_v1/results/NOISE_BASELINE.json.gz |
| SR_CONTROL | 97a02ed3e57e6c7aa3775b03b854d6e88c65705a4e4ab345ccabdf33b39103a7 | research/campaigns/scalp7_20261001/exact25_five_v1/results/SR_CONTROL.json.gz |
| SR_RETEST | 99283c787869069fcff9e7fc56f949352ea1175be04ae27131ed26529185bd9d | research/campaigns/scalp7_20261001/exact25_five_v1/results/SR_RETEST.json.gz |
| ST_CONTROL | e8b08438b48ea46bd8c80285d07c04ff29ab1a7615644b5a06c4df7d65618afb | research/campaigns/scalp7_20261001/exact25_five_v1/results/ST_CONTROL.json.gz |
| ST_TRAIL | 2c68b320ca03aea9ed4e27326007dedc2b0f505d4527e4d164383ef79f3b06b6 | research/campaigns/scalp7_20261001/exact25_five_v1/results/ST_TRAIL.json.gz |
