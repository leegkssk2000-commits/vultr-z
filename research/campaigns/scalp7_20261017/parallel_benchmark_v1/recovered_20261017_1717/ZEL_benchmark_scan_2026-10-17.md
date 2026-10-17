# ZEL 정보수집 후속 스캔 — 2026-10-17, 독일 10:19

## 권한 및 상태
- 정보수집 전용. 기존 경제 owner `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` 및 승인된 Keltner/Squeeze 경제비교는 변경하지 않았다.
- 기존 GitHub 연구 브랜치 `research/parallel-benchmark-20261017`의 `RESEARCH.md` blob `4453106d4dee89e0eb2a9e3808d459b51df6665d`와 현행 전략코드 blob `79b9934b471cbe0f4342b265c90b2c9c8884f52c`를 읽었다.
- **이번 GitHub 연구 브랜치 새 파일 쓰기는 연결 도구의 안전검사에서 거절되어 반영되지 않았다.** 이 파일은 로컬 보조 산출물일 뿐 저장소 반영본이 아니다.

## N14 StockCharts ChartSchool — TTM Squeeze
- 원문 https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/ttm-squeeze
- 확인: 계산·해석 본문. 공개 구현은 원형 Chester Keltner 채널 공식을 쓴다고 명시하고 Raschke 채널과 구분한다.
- 코드 대조: ZEL `squeeze_on`은 SMA20 ± 2σ를 `EMA20(g20) ± 1.5×ATR20`과 비교한다. 외부 TTM의 값이나 첫 발화 시각이 ZEL과 같다고 주장할 수 없다. 별도 소스 계산식/씨딩/발화 시각 parity 없이는 벤치마킹에 `TRANSLATION_NOT_SOURCE_REPRODUCTION` 표시가 필요하다.
- 모멘텀 감소 두 봉 매도 예시는 양수 히스토그램의 감속 사례다. ZEL의 최근 음수 모멘텀에서 해당 청산 가지가 실행되지 않는 정적 코드 관측을 새 수익가설로 입증하지 않는다.

## N15 StockCharts ChartSchool — Bollinger Band Squeeze / Head Fake
- 원문 https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze
- 확인: 가짜 상향 돌파 후 빠른 방향반전과 지지/저항 확인 설명. 원저자 투자 실적 영수증은 없다.
- 코드 대조: ZEL 신호는 squeeze_on→off, 양수 가속 모멘텀 및 이동평균 정렬을 보지만 가격 자체가 상단 BB를 이탈했다는 별도 조건은 없다. 문서의 헤드페이크와 ZEL 신호를 동일한 이벤트로 취급하지 않는다.
- 후속: 신호 저가 이탈 정책이 기존 stop/최대보유보다 먼저 발생했는지, 가짜 돌파 손실뿐 아니라 이후 회복 승리를 얼마나 훼손하는지 시간순 전체 거래로 확인 필요. 기사용 손실만 사후 선택 금지.

## N16 QuantConnect LEAN — Future Fill Model
- 원문 https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models/future-model
- 확인: Stop Market Orders, 선물 TradeBar 기본 체결 모델: sell stop 충족 시 `min(stop, close - slippage)`; 틱/호가 기반 모델은 별도. 과거/스테일 봉 체결 방지.
- ZEL 연구 엔진은 매봉 저가가 stop 아래이면 갭 시 시가를, 그 외 stop 가격을 사용한다. 이 차이가 tail loss를 바꿀 수 있으므로 비용 2배 스트레스와 stop-fill 불확실성을 분리해야 한다. LEAN의 전통 선물 모델을 BingX 무기한 선물 실체결이라고 주장하지 않는다.

## N17 Moskowitz, Ooi, Pedersen (2012) — Time Series Momentum
- 원저자 공개 요약 https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum
- 확인 수준: `ABSTRACT_ONLY`. 전통 선물·선도 58종, 12개월 내외 추세 효과는 30m 코인 무기한이나 BTC 상대강도 가설 H03의 검증이 아니다. 크로스섹션 상대강도와 자신의 시계열 모멘텀은 다른 신호.

## 코드 기반 새 H02 분기: Keltner의 약한 구간 상태 유지
- `_hg_event`에서 `strong = side!=0 and ADX>=30 and 방향과 일치하는 EMA20 경사>0`.
- `strong=False`일 때 `ADX<25` 또는 `side==0`인 경우에만 전체 reset. 즉 side가 유지되고 ADX>=25인 경우 `ADX<30` 또는 EMA20 경사 반대만으로는 기존 `stage/pull_low/pull_high`가 초기화되지 않는다.
- 이후 strong이 재성립하면 이전 접촉 상태가 재사용될 수 있다. 이것은 **정적 코드경로 확인**이며 어느 거래의 손실 원인이었는지는 미측정.
- 이미 승인된 `fresh-touch-after-reject`는 **생성된 진입의 확정 거절 후** 상태 초기화이다. 본 진단은 **거절 이전 약세 구간** 상태 유지에 관한 것이므로 인과질문은 다르지만 신규 후보 승인은 아니다.
- 필요한 관측: 원형·기각본·새 후속안에서 episode stage_before/after, ADX, EMA20 경사, 첫 touch_ts, weak_hold_bars, return_to_strong_ts, 후속 turn, acceptance, 이후 winner 훼손.

## 결론
- 신규 실측 수익 `NOT_RUN/UNVERIFIED`. 외부 소스의 홍보 수익률·임계치 이식 불가.
- 이번의 강한 발견은 Keltner 약세구간 상태유지의 별도 경로, TTM 공개 구현과 ZEL 압축 공식의 parity 위험.
- 경제 원장의 기사용 원형과 기존 두 후속 비교 우선순위는 유지. 브랜치 쓰기 실패 상태를 다음 회차에서 반복 도배하지 말고 read-only 연구나 정상 쓰기경로 확인 시에만 재시도.
