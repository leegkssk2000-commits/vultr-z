**실행 결과: 수익형 7-lane 시스템은 아직 성립하지 않았다.** 고정 21 identity의 12개월 실제 원천 기반 실행을 완료했다. T·WR·Net·DD 동시 개선 0개, C→B 0개, B×B 시작 불가. order/live authority는 BLOCKED다.

Fresh 원장 확인 시각: 2026-09-15T20:08:17.963184+00:00. 아래 경제 표는 rolling 245 calendar days만 사용한다. 초기 90일 문맥 학습, 30일 validation, 이후 9개 rolling window(8×30일+5일)를 분리했다. 과거를 본 뒤 설계한 구조이므로 chronological parameter-OOS이며 genuine fresh로 부르지 않는다.

원천: 2025-09-15 00:00–2026-09-15 00:00 UTC. 6심볼 실제 1분봉 3,153,576개. 심볼별 4분(2026-02-13 20:32–20:35 UTC) 누락을 보존했다. 합성 봉·합성 L2·합성 체결은 없다. 24개월 자료는 확보되지 않았다.

Gross/Net/DD는 동일 명목 거래 bps 합산이며 계좌 수익률이 아니다. DD는 완료 결과의 동시 시각 묶음 기준이며 MTM DD는 미산출이다. 1x/2x는 동일 고정 거래·배분에 비용만 1배/2배 적용한다. 현재 관측한 reference cost를 사용하며 역사 실제 수수료·펀딩·체결비용을 재현했다고 주장하지 않는다.

집중도는 해당 축의 최대 그룹이 양수 net 거래 이익 총합에서 차지한 비중이다. 최대 winner도 같은 분모다. 손실 월·심볼·session별 net은 JSON에 모두 보존했다. ES5는 모든 거래 중 하위 5% 평균 net이다. 빈 rolling window도 양수 비율 분모 9에 포함한다.

**표 1 — CURRENT TOP7.** 첫 7행은 사전 고정 primary set이다. 아래 비교본은 별도 frozen identity이며 결과에 맞춰 primary를 교체하지 않았다.

| CURRENT TOP7 / 고정 비교본 | TF | Identity/SHA | T | T/day | WR% | Gross bps | Net 1x bps | Net 2x bps | Net/T bps | PF 1x/2x | DD 1x/2x bps | MaxLS | loss tail ES5 bps | hold median/p95 분 | rolling +window | fresh T | 월/심볼/session 집중 | 최대 winner 기여 | parent 대비 | 최종 상태 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Keltner parent | 30m | K.P@b0919c9e | 109 | 0.445 | 59.63 | 7,586.95 | 5,947.63 | 4,308.32 | 54.57 | 2.003/1.624 | 1,609.47/2,019.03 | 5 | -289.17 | 180/750 | 6/9 | 0 | 44.4%/31.4%/49.4% | 11.4% | frozen parent/control | parent 보존 · 2x 양수 · fresh 미확증 |
| Trend Rider rebuild | 15m | R.C@9cdd3b80 | 4358 | 17.788 | 22.28 | 7,685.01 | -57,549.68 | -122,784.37 | -13.21 | 0.682/0.472 | 58,693.85/123,691.43 | 39 | -142.22 | 135/540 | 1/9 | 0 | 16.2%/23.3%/39.3% | 1.0% | T -2,610, WR -4.81pp, Net 36,690.63, DD -37,009.11 | 순손실 · Core 불가 |
| Break rebuild | 15m | B.C@df1831fb | 871 | 3.555 | 25.95 | -2,007.60 | -15,017.98 | -28,028.36 | -17.24 | 0.683/0.509 | 17,139.63/28,707.07 | 23 | -198.97 | 180/360 | 1/9 | 0 | 22.4%/18.7%/55.4% | 3.8% | T -1,498, WR 0.37pp, Net 20,216.12, DD -18,798.38 | 순손실 · Core 불가 |
| Supertrend rebuild | 30m | ST.C@aaf91c3e | 1886 | 7.698 | 36.80 | 10,651.50 | -17,466.56 | -45,584.61 | -9.26 | 0.850/0.662 | 26,233.22/48,356.11 | 21 | -266.18 | 480/480 | 3/9 | 0 | 16.2%/18.8%/42.9% | 1.4% | T -2,065, WR 6.60pp, Net 29,350.30, DD -26,131.20 | 순손실 · Core 불가 |
| Squeeze parent | 30m | S.P@b0919c9e | 25 | 0.102 | 48.00 | 1,892.29 | 1,520.49 | 1,148.69 | 60.82 | 1.912/1.617 | 576.67/609.11 | 3 | -288.34 | 300/330 | 3/9 | 0 | 58.6%/25.7%/55.3% | 19.5% | frozen parent/control | parent 보존 · 2x 양수 · fresh 미확증 |
| MR V1 parent | 30m | MR.P@1674f245 | 75 | 0.306 | 56.00 | 1,305.00 | 188.81 | -927.37 | 2.52 | 1.083/0.670 | 797.47/958.51 | 6 | -237.07 | 240/240 | 6/9 | 0 | 46.7%/11.2%/46.5% | 9.7% | frozen parent/control | 1x 소폭 양수 · 2x 음수 · 보류 |
| Micro EDGE | 15m | Micro@5132e69d | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 0 | N/A | N/A | N/A | 실제 tape fresh; 역사 L2 N/A |
| Keltner TD0.75 child | 30m | K.TD075@b0919c9e | 110 | 0.449 | 57.27 | 6,611.74 | 4,958.41 | 3,305.07 | 45.08 | 1.830/1.472 | 1,635.52/2,059.10 | 5 | -289.17 | 150/750 | 6/9 | 0 | 48.2%/29.8%/53.6% | 12.4% | T 1, WR -2.36pp, Net -989.22, DD 26.05 | parent 대비 악화 · 미채택 |
| Squeeze BE1R child | 30m | S.BE1R@b0919c9e | 25 | 0.102 | 48.00 | 1,892.29 | 1,520.49 | 1,148.69 | 60.82 | 1.912/1.617 | 576.67/609.11 | 3 | -288.34 | 300/330 | 3/9 | 0 | 58.6%/25.7%/55.3% | 19.5% | T 0, WR 0.00pp, Net 0.00, DD 0.00 | rolling 동일 · 별도 fresh |
| MR re-expansion child | 30m | MR.BAR4@1674f245 | 82 | 0.335 | 48.78 | 1,226.90 | 10.07 | -1,206.76 | 0.12 | 1.004/0.628 | 634.46/1,245.67 | 6 | -205.77 | 240/240 | 6/9 | 0 | 39.6%/10.4%/58.2% | 10.2% | T 7, WR -7.22pp, Net -178.74, DD -163.02 | DD 개선/Net 악화 · 미채택 |
| MR weekly formation child | 30m | MR.FORM@1674f245 | 41 | 0.167 | 7.32 | -132.26 | -706.26 | -1,280.26 | -17.23 | 0.061/0.014 | 706.26/1,280.26 | 13 | -37.71 | 30/240 | 0/9 | 0 | 70.7%/100.0%/70.7% | 70.7% | T -34, WR -48.68pp, Net -895.07, DD -91.21 | formation 실패 · 미채택 |
| Rider causal control | 15m | R.P@5d7b4b6e | 6968 | 28.441 | 27.10 | 9,673.39 | -94,240.31 | -198,154.01 | -13.52 | 0.634/0.410 | 95,702.96/198,859.97 | 54 | -126.93 | 75/345 | 0/9 | 0 | 19.1%/19.9%/39.0% | 0.6% | frozen parent/control | 순손실 · Core 불가 |
| Break causal control | 15m | B.P@5d7b4b6e | 2369 | 9.669 | 25.58 | 119.05 | -35,234.11 | -70,587.27 | -14.87 | 0.442/0.222 | 35,938.01/71,133.46 | 44 | -100.51 | 30/195 | 0/9 | 0 | 18.8%/20.7%/36.5% | 2.2% | frozen parent/control | 순손실 · Core 불가 |
| Supertrend causal control | 30m | ST.P@5d7b4b6e | 3951 | 16.127 | 30.19 | 12,233.43 | -46,816.86 | -105,867.14 | -11.85 | 0.740/0.524 | 52,364.42/106,795.65 | 36 | -149.66 | 150/600 | 2/9 | 0 | 18.5%/19.6%/35.2% | 1.2% | frozen parent/control | 순손실 · Core 불가 |

**표 2 — MATERIAL/FUSION.** 각각 한 causal axis의 round1을 실행했다. 최대 3회라는 상한을 반복 튜닝의 목표로 사용하지 않았다. Round2/3는 동결·실행하지 않았다.

| grade | parent | child | T | WR% | Net 1x/2x bps | PF 1x/2x | DD 1x/2x bps | marginal contribution | parent behavior cosine | fresh 상태 | B/A 승격 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C | rbreaker_like control; T=5264, Net=-87,644.62, PF=0.614 | round1 @ebdf060f | 5374 | 30.55 | -90,542.45/-170,901.41 | 0.556/0.346 | 91,014.78/171,079.21 | ΔNet -2,897.83, ΔDD 3,136.40 | 0.856 | T=0; 미확증 | B=0/A=0; 경제조건 실패 |
| C | rsi_swing_fail control; T=2724, Net=-46,463.65, PF=0.585 | round1 @ebdf060f | 2767 | 36.50 | -48,073.74/-89,448.31 | 0.571/0.355 | 48,918.34/89,740.36 | ΔNet -1,610.09, ΔDD 1,200.56 | 0.960 | T=0; 미확증 | B=0/A=0; 경제조건 실패 |
| C | trend_ma_macd control; T=685, Net=-1,292.60, PF=0.958 | round1 @ebdf060f | 1425 | 26.88 | -13,048.15/-34,301.59 | 0.820/0.611 | 20,659.24/39,713.63 | ΔNet -11,755.55, ΔDD 14,036.63 | 0.515 | T=0; 미확증 | B=0/A=0; 경제조건 실패 |
| C | turtle_trend control; T=2346, Net=-30,232.61, PF=0.777 | round1 @ebdf060f | 2287 | 26.28 | -41,557.46/-75,765.04 | 0.715/0.557 | 44,599.56/77,604.59 | ΔNet -11,324.86, ΔDD 10,830.88 | 0.895 | T=0; 미확증 | B=0/A=0; 경제조건 실패 |

4개 child 간 behavior cosine: 0.146, 0.003, 0.164, -0.045, -0.139, 0.253. 중복 기준 0.85 이상은 없지만 독립 B가 0개이므로 fusion 자격이 없다. C×C brute force와 Top7 이식은 수행하지 않았다.

Rebuild 3개는 총손실·실현 DD·MaxLS를 줄였지만 T를 크게 잃었다. Supertrend는 WR과 Net/T도 개선됐으나 비용 후 음수다. 세 구조 모두 ES5 loss tail과 최대 winner 집중도는 악화됐고 Break는 Net/T도 악화됐다. 총손실 감소를 충분한 edge로 해석하지 않는다.

Keltner·Squeeze parent는 rolling 2x에도 양수다. Keltner TD0.75는 부모보다 WR·Net·DD가 악화돼 미채택이다. Squeeze BE1R은 동일 결과다. MR bar4는 T·DD 개선과 Net·WR 저하가 함께 나타났고 proper formation child는 실패했다. 어느 child도 결과를 보고 역사 재튜닝하지 않았다.

포트폴리오 동일 1/7 비중: T 4003, T/day 16.339, WR 26.78%, Net 1x/2x -4325.71/-9464.81bps, PF 0.735/0.530, DD 4669.53/9631.45bps. 수익 시스템 채택 불가.

포트폴리오 과거 완료 shadow health 기반 배분: T 602, T/day 2.457, WR 29.07%, Net 1x/2x -5016.15/-9649.15bps, PF 0.729/0.558, DD 5620.18/10180.07bps. 수익 시스템 채택 불가.

Portfolio는 과거 완료·공개된 shadow 결과만 health에 사용하고, 같은 시각 이미 유효한 저장 opportunity에만 배분한다. 없으면 cash이며 replacement trade를 만들지 않는다. 최대 gross weight 1, 미해결 갭 포지션은 자본 점유. 입력은 독립 sleeve의 체결 및 미해결 opportunity 원장이므로 독립 sleeve 점유 중 빠진 모든 raw valid signal까지 포함한 완전한 opportunity pool은 아니다. 연구 window별 독립 flat 시작이며 연속 계좌 곡선이 아니다.

Fresh는 2026-09-15 20:00 UTC 전에 규칙과 관측 호가 paper 설정을 고정해 7 primary 및 별도 child/material을 동시에 관측하기 시작했다. 실제 공개 trade tape와 1분봉만 수집하며 decision은 15m/30m다. Paper는 실제 decision publication 후 새 요청으로 받은 호가만 사용한다. 신호 수를 fresh T로 세지 않는다. 실제 계좌 체결·주문·capacity 입증은 없다. Genuine fresh 검증에는 앞으로 도착할 자료가 필요하다.

Validation 30일은 rolling 표에 합치지 않았다. identity별 validation T/WR/Net/PF/DD·2x는 CAMPAIGN_FINAL_RESULTS_V2.json의 window_receipts에서 partition=validation로 별도 보존한다. 초기 90일은 문맥 학습만 수행하고 train PnL을 만들지 않았다. Window 끝 미완료와 갭 미결 거래는 임의 종가 청산하지 않았다.

최초 Rider/Break 대조군은 segment_id 문자열/정수 불일치로 모든 신호가 거절돼 실제 fill=0이었다. 두 시도는 기술 오류로 보존하며 성과에서 제외했다. 유효한 기존 4개 positive를 재실행하지 않고, 같은 lexical segment ID의 타입만 맞춘 별도 repair를 경제결과 전에 동결해 나머지 17개를 실행했다. 원래 전략·가격·갭·비용·규칙은 바꾸지 않았다.

독립 saved 검증은 21개 identity의 raw fill 49,581개, rolling 완료 43,742개를 검산했다. 경계와 정확히 같은 outcome 8개는 제외한다. 보존된 Keltner parent32개/TD07529개 raw partial 거래는 개별 cashflow event가 빠져 있어 terminal entry/exit만으로 gross 전체를 독립 복원할 수 없다. net/cost 산술은 일치하고 유효 실험은 반복하지 않았다. 나머지 17개는 partial cashflow도 명시적으로 검산했다.

현행 endpoint OPEN timestamp는 실제 전후 표본으로 확인했고 역사 1m→native 1h OHLC도 일치했다. 같은 endpoint의 과거 timestamp 해석은 추론이며 역사 delivery latency는 관측되지 않았다. 역사 available time은 bar close 모델이다. raw volume/quantity unit이 불명확해 방향이나 L2를 가정하지 않았다. Micro raw는 4GiB 용량 한도 내 실제 수집이며 무제한 수집 약속이 아니다.

CI는 저장 원장 해시·산술과 causal fixture만 검증하며 경제 재실행을 하지 않는다. Active5 1h, TrendRider Broad, G4/G5 및 old Top3/Liquid6 성과는 이 표에 포함하지 않았다.

Micro는 최초 역사 계약의 미구현 placeholder scalp7_micro_observed_tick_15m_v2를 경제 결과에 사용하지 않았다. 실제 frozen fresh identity MICRO_OBSERVED_TRADE_RECLAIM_15M_V2는 공통 시작 전 forward config의 external_micro에 결속했다. 이 명시적 연결은 MICRO_IDENTITY_BINDING_V2.json에 보존한다.

표 alias의 exact identity (@는 모듈 SHA256 앞 8자리):

- K.P: `scalp7_keltner_hg_parent_utc30m_v2`
- R.C: `scalp7_rider_15m_impulse_pullback_reclaim_v2`
- B.C: `scalp7_break_15m_anchored_retest_reclaim_v2`
- ST.C: `scalp7_supertrend_native_impulse_pullback_30m_v2`
- S.P: `scalp7_squeeze_panic_cost4_parent_utc30m_v2`
- MR.P: `mr_cross_sectional_v1_30m_causal_control_v2`
- Micro: `MICRO_OBSERVED_TRADE_RECLAIM_15M_V2`
- K.TD075: `scalp7_keltner_hg_td075_utc30m_v2`
- S.BE1R: `scalp7_squeeze_panic_cost4_be1r_utc30m_v2`
- MR.BAR4: `mr_reexpansion_bar4_30m_causal_control_v2`
- MR.FORM: `mr_btceth_weekly_formation_30m_v2`
- R.P: `scalp7_trend_rider_opportunity_control_15m_v2`
- B.P: `scalp7_break_and_continue_opportunity_control_15m_v2`
- ST.P: `scalp7_supertrend_pullback_opportunity_control_30m_v2`

- [전체 경제 원장·2x·모든 월/심볼/session](FINAL_COMPARISON_V2.json)
- [독립 saved 검증](../broad_v2/SAVED_RESULTS_INDEPENDENT_ARITHMETIC_V2.json)
- [실제 candle 비교](anatomy_binding_repair/)
- [공통 fresh 고정](FRESH_FORWARD_FREEZE_V2.json)
- [실제 호가 paper 고정](OBSERVED_PAPER_FREEZE_V2.json)

Core/order/live 승격 없음. 프런트엔드 배포 불필요. Rollback은 해당 Scalp7 연구 service만 중지하고 기존 원장·freeze를 보존한다.
