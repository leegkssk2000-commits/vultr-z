# ZEL 공개자료 병렬 벤치마킹 — 2026-10-17 12:22 CEST

상태: RESEARCH_ONLY / NO_ECONOMIC_RUN / NO_RULE_OR_BUDGET_CHANGE / NO_PAID_API.
기존 자료: 동일 연구 브랜치 RESEARCH.md (Git blob 4453106d4dee89e0eb2a9e3808d459b51df6665d). 이전 13개 자료·H01/H02/H03 및 이미 확인된 Raschke 2004/StockCharts Squeeze 논점을 재등록하지 않는다.
경제 owner=CLOUD_WORK_COORDINATOR_ISSUE1358_V1. 이 연구에 별도 경제 claim이 없고, OWNER/CHECKPOINT/원형·비용·실험소비 원장/경제 workflow·주문 권한은 건드리지 않는다.

## 이번 검토의 핵심 변화
**(1) 학술 수익률의 거래비용 단위가 현행 ZEL과 호환되지 않을 수 있음**: 아래 P01의 비용 10bps는 **position turnover 1 unit 당**이고, 현행 ZEL 시나리오 BTC/ETH 14bps는 **전체 왕복 거래당**이다. 이 논문의 long/cash 0→1→0은 비용 20bps라는 단위 계산이 필요하며, 논문 숫자를 ZEL 비용1x/2x·Net과 직접 비교하면 안 된다.
**(2) P01의 결측시간 처리 자체가 ZEL 기존 fail-closed 조건과 상충**: 논문은 미존재 hourly candle을 직전 종가·거래량0의 합성 평탄봉으로 채운다. 이 처리법은 해당 논문 재현 조건이지, ZEL의 결측 1m/30m 봉을 채워도 된다는 승인이 아니다.
**(3) 원저자형 HolyGrail과 다른 'Keltner Channel'의 성과를 동일 전략으로 오인해서는 안 됨**. P02는 주로 비교 방식/종목/시간봉 차이에 관한 간접증거다.
**(4) 기존 next-open/stop-first 엔진의 gap 처리는 공개 모델 원칙과 일부 일치하나**, 현재 비용은 역사적 실제 spread/impact/funding/채결기록이 아닌 2026-09-15 스냅샷 기반 시나리오다. gap 체결의 추가 미끄러짐·시장가 partial fill까지 확인한 것은 아니다.

## P01 — Bysik & Ślepaczuk (2026), BTC 시간당 예측을 매매로 바꾸는 비용 게이트
분류: SOURCE_FACT + AUTHOR_PERFORMANCE_CLAIM (HTML 전문 공개) / ZEL 적용: NOT_A_CANDIDATE.
원문: https://arxiv.org/abs/2606.00060
읽음: 데이터 §3.1–3.2, 규칙 §4.1, walk-forward §4.2, 제한/결론.
원시장·빈도: Binance USD-M BTC/USDT, 1h, 2017-12–2026-01 원천(예측/평가 2018–2025), 27-fold rolling walk-forward.
정확한 공개 방법: 12개월 학습→3개월 검증→3개월 시험; 다음 시간 수익률 예측 후 보유비중 변동량 |pos_t-pos_(t-1)|에 c=0.001 비용을 부과. 진입/청산 승인 가설은 |예측수익률| > λ*c*|포지션 변경량|; 실험의 예시 λ=2.0. 단순 부호 기반 모델은 10bps 비용 적용 시 경제성이 악화했고 비용 인지 필터의 성과가 더 좋았다고 저자 보고. 하지만 모델 우열은 bootstrap에서 유의하게 입증하지 못했고 시황별 편차가 존재한다.
중요한 소스 한계: 결측시간은 직전 종가·거래량0으로 메운 합성봉. L2/partial fill/time-varying spread/observed funding은 재현하지 않음. 논문 결과 자체를 ZEL 계좌수익·2026 현재 암호화폐 예상수익으로 보지 않는다.
현행 코드 비교: ZEL `entry_admission`의 ATR/cost 4.5x 또는 4.0x는 미래 1h 리턴 예측 |forecast|와 차원이 다르다. 시나리오 COST_PATH: `research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json`, Git blob 87ca53109d19d4ad354f16706d9eecd54da5f556. BTC/ETH 14bps = 1회 **round trip** 당, paper c=10bps = 1 unit **position change** 당. 횟수 환산 없이 14>10·14<20으로 전략 유불리를 논하지 않는다.
검증 질문: 추가 거래의 단순 수가 아닌 turnover 및 비용 후 Net/day가 개선됐는가? 이미 실패한 ATR/cost 재튜닝과 중복되는 '단순 비용필터 강화'를 신규 전략축으로 제출하지 않는다. 실제 기존 두 후속 경제실험에 대한 보고 표준만 강화한다.
반증: 복제 데이터/계산에서 청산·점유·결측·왕복 단위가 다르면 저자 수익률과 일치해도 ZEL 실현 가능성을 증명하지 못함.

## P02 — Gil Cohen (2023), 'Intraday algorithmic trading strategies for cryptocurrencies'
분류: ABSTRACT_ONLY / AUTHOR_PERFORMANCE_CLAIM. 전체 규칙·거래원장·비용/슬리피지·검증 분할 미확보.
원문 출판사 https://link.springer.com/article/10.1007/s11156-023-01139-2
DOI 10.1007/s11156-023-01139-2, 2023-05-19 발표. 출판사 초록 읽음, 본문 구독 제한 확인.
대상: BTC, ETH, BNB, ADA, XRP; 5–180분 여러 봉, RSI/MACD/Keltner Channels 비교. 논문 초록상 60·120분 봉이 5·15분보다 성과가 좋았고 Keltner/MACD는 BTC·BNB·XRP에서 buy/hold를 이겼지만 ETH·ADA에서는 뒤졌다고 저자 보고. **30분 결과·정확한 거래 수·net/PF/DD·거래비용·OOS 세부는 공개 초록에 없음.**
현행 코드 비교: ZEL `scalp7_positive_lanes_v2.py` Git blob 79b9934b471cbe0f4342b265c90b2c9c8884f52c는 GMMA 배열·ADX·EMA20 눌림·native turn·다음 시가 모델을 쓰는 HG이며, 일반적인 단순 Keltner 채널 교차 규칙과 동일하지 않다. 바로 60/120분 봉으로 바꾸거나 RSI 삽입할 이유가 없다.
진짜 정보 이득: 30분 현재 전략의 저수익/연패를 기계적으로 더 많은 신호로 해결하려 하지 말고, 낮은 시간봉의 잡음과 보유기회 차이를 **관측 질문**으로만 남긴다. 현행 두 승인 후속안에 60/120분 전략 새로 섞지 않는다.
반증: 같은 HTF 가격맥락도 실수익 개선을 예측하지 못하거나 30분 HG 대조군에서 큰 승리 훼손이 발생하면 불필요함.

## P03 — StockCharts ChartSchool, ADX 원자료 설명
분류: SOURCE_FACT + CODE_OBSERVATION / 새 필터 NOT_READY.
https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx
검토: Applying ADX, trend strength/direction, ADX smoothing lag 설명. 기술 문서이지 검증된 수익 연구가 아니다.
출처 명제: ADX는 **추세 강도**이지 방향 자체가 아니다. +DI/-DI가 방향 정보이며 ADX는 후행성이 있다. Wilder의 ADX>25 강추세 설명은 ZEL의 30/25 state reset을 최적값으로 인증하지 않는다.
코드 대조: `_hg_event`는 side를 GMMA 정렬과 g60의 직전 차이에서 판단하고, strong에 adx14>=30과 g20 방향경사를 요구한다. strong false여도 adx>=25 및 side≠0이면 stage/pull_low/pull_high를 명시적으로 삭제하지 않은 채 return한다. 이것은 기존 최신 로컬 후속 조사에서 이미 알려진 관측이므로 NEW_DISCOVERY로 다시 세지 않는다.
정확한 H02 후속진단 자료: 직전 첫 strong 시각, touch 시각, ADX와 그 이전 차이, weak-but-held 봉 수, 실제 turn·accepted/rejected 시각, 포지션 보유/원래 exit 이후 원인. 새 신호·ADX 임계치 최적화 없이 원형과 승인 fresh-touch의 trace에 한정한다.
반증: ADX weakness-memory가 체결로 이어지지 않거나 고수익 정상 재진입을 유지하는 경우는 임의 reset 추가에 반대하는 증거.

## P04 — QuantConnect, stop-market 실행 의미와 gap 위험
분류: SOURCE_FACT + CODE_OBSERVATION / 연구용 실행모델 반대점.
https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/order-types/stop-market-orders
https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts
공식 설명: 가격이 stop을 관통하는 순간 시장가 주문으로 전환되며 gap이 stop 가격을 뛰어넘으면 실제 체결가격이 stop보다 불리할 수 있다. 수량 일부만 채워질 수 있어 stop 금액은 보장손실 상한이 아니다.
ZEL `scalp7_execution_v2.py` Git blob 11f7d9e632741dedb536035966f6c7a68befa38f: long stop에서 bar.low<=stop일 때 open<stop이면 open으로, 아니면 stop으로 종료. stop·target 동시 발생은 stop-first. 이는 불리한 gap을 stop-price 그대로 채우는 낙관 오류를 일부 피한다. 그러나 gap open 이후 추가 market impact, 부분 체결, bid/ask, observed signed funding은 이 OHLC 단일 fill 엔진만으로 실증되지 않는다.
Squeeze H01 및 승인 signal-low 후속안의 구체 비교: ① 기존 stop이 먼저 발동한 경우 ② 음수 전환 또는 신호봉 저가 이탈 완료봉 뒤 next-open exit ③ 그 사이 gap ④ 포지션 조기 해제 뒤 후속 진입 ⑤ 회복한 큰 승리. 실시간 주문가격 없이 '완성봉 종가에서 손실제한 청산'으로 적지 않는다.
반증: 일찍 signal-low/모멘텀 조건이 발동해도 기존 stop과 실제 먼저 발동한 이벤트가 동일하거나 next-open adverse gap으로 손실감소가 상쇄되면 개선 근거 부재.

## 네 독립 축 점검 / 이번 회차 실제 차이
- Keltner/HG: P02는 같은 이름의 보조지표가 같은 체결전략이 아님을 입증한 **비동등 벤치마크**. P03은 ADX 강도/방향 의미와 weak-state trace 요구의 근거. 추가 코드수정 없음.
- Squeeze: 기존 H01의 '음수 momentum 청산 공백'은 같은 원형 코드 관찰로 유지. 새 원인 확정 아님. stop과 gap 우선으로 상대적 시간 순서를 검토하는 P04 제공. 새로운 breakout 규칙 없음.
- 청산·큰 승리 보존: P04에서는 stop gap과 partial fill의 불확실성을 분리. P01은 비용 단위 및 27-fold 경제검증 설계의 반대자료. 큰 승리 보존 실측 없음.
- 차트/HTF/공개 봇: P02는 다른 60/120m 결과를 맥락 비교로만 제시. P01의 합성 결측봉은 ZEL fail-closed 1m→30m 연쇄와 불일치하며 채택하지 않음. 새로운 피보나치·캔들·영상 조회수 근거를 억지로 만들지 않음.
- 영상: 이번 회차 신규로 완전 시청/대본·현행 조회수를 검증한 영상 0건; 이전 등록 V01–V04 상태 유지.

## 금지 및 판정
SOURCE_FACT와 AUTHOR_PERFORMANCE_CLAIM, CODE_OBSERVATION, INTERNAL_HYPOTHESIS를 분리했다. ACTUAL_ECONOMIC_RESULT for successor 없음. ZEL 245일 개발 경제비교·fresh/OOS·계좌 NAV 실측 모두 이번 정보 수집에서 수행하지 않았다. src=cf: 또는 src=sheets: 계좌 실시간 값 없음 — 실주문·자금결정 [UNSURE]+HOLD.
현행 승인 Keltner fresh-touch와 Squeeze signal-low 두 비교를 최우선으로 두고, 신규 경제 후보·시간봉 변경·파라미터 변경·실행예산 변경·owner claim 변경 없음. 자료수집은 경제실행 연결과 독립적으로 계속될 수 있다.

검증 수준: HTML 전문 P01/P03/P04, 출판사 초록 P02; PDF 전문 분석한 것 아님. 이번 정보수집에서 새로운 시장데이터·결제·비용발생·경제재생 0회.
