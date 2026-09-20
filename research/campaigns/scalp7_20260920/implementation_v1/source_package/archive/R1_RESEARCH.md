# G4 원래 25개 — 벤치마킹 대상·직접 비교 항목·수익 근거 조사

기준일: 2026-09-20
저장소 검토 기준: `leegkssk2000-commits/vultr-z` / `58964a346a733d1a45e919c7c8d4087f05c8da3c`

**범위:** 원래25개 식별자를 유지한다. 이 문서는 인터넷 원자료와 기존 구현 감사의 비교 결과이며, Work에 다시 “알아서 벤치마킹하라”고 맡기는 일반 지시문이 아니다.
**완료 상태:** 비교 대상·이유·성과 증거·공백을 특정했다. 신규 백테스트·채택·배포·새 Work 실행은 하지 않았다.

## 1. 조사 결론

수익이 공표된 계좌와 공개된 매매 규칙을 별도로 확인해야 한다. 계좌 수익률이 큰 사람을 골랐다는 것만으로 그 지표를 검증한 것이 되지 않는다. 반대로 개인 계좌 공개가 없더라도, 원 논문·명시적 규칙·실제 비교표·저자 구현이 함께 있는 자료는 검증용 기준을 만드는 데 유용하다.

이번에 구체적으로 확보한 중심 비교군은 Concretum의 시간대별 Noise-Area와 Stocks-in-Play ORB, Connors의 R2, 원 Turtle 규칙집, Carter의 실제 공개 거래계획, Gajjala의 intraday 사례다. GMMA·AVWAP·Bollinger·RSI/MFI/OBV·Supertrend는 정의/역할 자료와 수익형 독립모델을 구분한다.

## 2. 트레이더·연구별 성과와 증거 범위

| ID / 대상 | 근거 종류·기간 | 확인된 성과 | 귀속·재현의 한계 |
|---|---|---|---|
| D01 **Carlo Zarattini·Andrew Aziz·Andrea Barbon — SPY Intraday Momentum** | 저자 백테스트 + 원 구현 / 2007-05~2024-04 | 표3: 현재 band+VWAP 고정명목 연9.7%·MDD12%; 변동성 조절 연19.6%·누적1985%·MDD25%. 표4: 후자 7668T, 거래승률37%. | 일별 Hit Ratio43%를 거래WR로 사용하지 않는다. 주당 수수료0.0035달러와 슬리피지0.001달러, vol목표/최대4배 등 원 조건 포함. 한국어 투자 권유가 아니라 원 연구 조건 기록. 근거: R01, R02, R03 |
| D02 **Carlo Zarattini·Andrea Barbon·Andrew Aziz — Stocks in Play ORB** | 저자 백테스트 / 2016~2023 | 표2 ORB+상대거래량: 누적1637%, 연41.6%, MDD12%, Sharpe2.81. 표3 15분형 연17.4%·MDD11%, 30분형 연2.3%·MDD35%. | 실계좌 성과 아님. 0.0035달러/주 비용, 종목선정·규모가 포함. 공개 QQQ ORB 노트북은 이 전체 연구와 다른 universe이다. 근거: R04, R05 |
| D03 **Goverdhan Gajjala — Intraday VCP / Bull Flag** | 주최자 확인을 인용한 원 인터뷰 + 공개 거래 사례 / 2023 | 대회 계좌 +805%. 특정 VCP 한 가지의 수익률이 아니다. 상세 실계좌 DD 및 패턴별 비용 후 성과 미확인. | 원 인터뷰의 브로커 명세 사례와 계좌 전체 결과를 구분. 15m/30m 코인으로 이식 시 종목선정과 거래량 의미가 달라진다. 근거: P03, P04 |
| D04 **Mark Minervini — SEPA/VCP** | 대회 주최자 계좌 결과 / 2021 | +334.8%. 해당 연도 계좌 전체; VCP·OBV·GMMA 하나의 기여 수치 아님. | 기업실적·주도주·여러날 구조를 코인30m에 그대로 존재한다고 가정하지 않는다. 이 조사에서 완전한 원저자 수치 규칙집 확보와는 구분. 근거: P01 |
| D05 **Oliver Kell — Cycle of Price Action** | 대회 주최자 계좌 결과 + 본인 공개 framework / 2020 | +941.1% 계좌 결과. EMA crossback 단독 WR/DD 미확인. | 공개 사이트는6단계 구조를 설명하지만 모든 stop/포지션 관리가 기계적으로 완결된 원문은 아니다. 근거: P02, R13 |
| D06 **John Carter — Squeeze 및 공식 Trading Plan** | 본인 회사 계좌 회고·성과 주장 / 독립 감사 미확인 / 2020 | 회사 주장 +1270% 또는 약$18.2m. 공개회고의 2020년10월 TOS 월수익률 -32.83%도 함께 기록. | 단일 Squeeze 성과로 귀속 불가. 주간2.5~5%는 목표이며 실제 매주 수익 아님. 옵션 수익률을 perp 방향신호에 복사하지 않는다. 근거: P05, P06, P07, R11, R12 |
| D07 **Larry Connors — Improved R2** | 저자 공개 모의실험 + 완결된 신호/청산 규칙 / 1995-01-01~2006-12-31 | 102T, WR84.31%, 총1013.90 S&P포인트, 평균보유5.76일. | 비용·연환산계좌수익·MDD는 원문에 없음. stop 없는 신호모델을 그대로 레버리지 운영하지 않는다. RSI14 failure-swing의 수선본이 아닌 별도 비교 모델. 근거: R06 |
| D08 **Richard Dennis·William Eckhardt / Curtis Faith 공개 Turtle Rules** | 원 참가자의 완전한 기계적 규칙집 / 역사적 Turtle 시스템 | 이번 확인 자료에는 공통 기간의 독립 검산 가능한 계좌 원장·정확한 WR/DD 시계열 없음. 인터넷의 연80% 등을 확정값으로 사용하지 않음. | 20/55일, intraday trigger, N·위험정규화·피라미딩·상관 한도·10/20일 청산을 함께 읽어야 한다. 20일을20개15m봉으로 바꾸면 원형이 아니다. 근거: R07, R08 |
| D09 **Linda Raschke — Holy Grail / range-versus-trend reading** | 원저자 인터뷰·차트 사례 / 1997·2013 공개자료 | 해당 Holy Grail 규칙만의 검증된 연간 PnL/WR/DD 미확보. | 저자의 명성은 성과표가 아니다. 정성적인 실패·trail을 임의 bar 만료로 치환했다면 별도 설계로 표시. 근거: R09, R10 |
| D10 **Daryl Guppy — GMMA** | 저자 공식 정의·전술 / 공개 설명 | 검증된 GMMA 단독 계좌 수익/WR/DD 미확보. | 2묶음 정의를 읽은 것은 완성된 수익전략 재현과 다름. PR1341의 실제2묶음 구현을 이미 수행한 사실 보존. 근거: R14 |
| D11 **Brian Shannon — Anchored VWAP** | 원저자 CMT 발표 위치·내용 범위 확인 / 2023-04-27 발표 | AVWAP만의 독립 검증 수익률 미확보. | 전체 영상/슬라이드 미확보. 원형 재현준비 완료로 세지 않는다. 같은 실패 AVWAPv10 변형 반복 금지. 근거: R15 |
| D12 **John Bollinger — Band rules** | 저자 공식 규칙 / 공개 설명 | 이번 자료는 지표 사용 원칙이며 검증 계좌 수익표가 아님. | 밴드 접촉을 자동 반전 신호로 해석하지 않는다. 근거: R16 |
| D13 **RSI/MFI/OBV 공식 산식 및 Supertrend** | 공식 기술 정의 / 공개 문서 | 그 지표로 특정 트레이더가 벌었다는 수익 귀속 근거 없음. | 정확 계산과 경제적 기여 검증을 분리. 근거: R17, R18, R19, R20 |
| D14 **Kai-Yuan Chen·Kai-Hsin Chen·Jyh-Shing Roger Jang — DGT** | 원 논문 + 저자 코드 저장소 / 2021-01~2024-07 | 원문: 유리한 설정 IRR 약60~70%, ETH MDD 약50%. 거래 fee0.0008(0.08%) 사용. | 파라미터 조합 탐색·상승기 효과가 포함. 하단 이탈 시 재고 보유, 익절금 재투입; perpetual청산·funding 없음. 당장 사용자 레버리지 전략으로 복사 불가. 근거: R21, R22 |
| D15 **Cont·Kukanov·Stoikov — OFI** | 원 논문의 미시구조 연구 / 논문 2010/후속출판 | 초록의 가격충격 설명력은 15m/30m 순손익 성과가 아니다. | 체결가격만으로 호가잔량/취소사건을 합성하지 않는다. Paul Rotter의 비공개 매매법 재현으로 표시 금지. 근거: R23 |
| D16 **ICT — FVG/MSS** | 원 영상 위치 확인, 전체 규칙 검수 미완료 / 2022-02-03 | 독립검증된 해당 모델의 비용 후 계좌 수익 미확보. | 목차 Account History가 존재한다는 것만으로 인증하지 않는다. 수익이 검증된 원형으로 자동선정 금지. 근거: R24 |
| D17 **R-Breaker 공개 구현 참고** | FMZ 게시자 구현; 원저자 성과 미검증 / 2020 공개, 2025 수정 표기 | Futures Truth 순위 주장은 원 자료 미확보. 게시자도 stop이 빠진 demo라고 명시. | 원문r3 식에 /2가 있지만 코드에는 없다. 이 모호성을 해결하지 않고 그대로 원형으로 복제하지 않는다. 근거: R25 |
| D18 **Larry Williams — 변동성 돌파·pivot 연구** | 대회 주최자 결과 + 저자 개념 설명 / 1987 대회 | World Cup 공식 기록 +11,376%. 특정 Oops/pivot 하나의 성과가 아니다. | 성과 크기만으로 선택하지 않는다. 공개 소개만으로 완전한 거래 규칙을 확보한 상태는 아님. 근거: R26, R27 |

## 3. 가장 먼저 차이를 검증할 구체적인 기준

### 3.1 Carter: 지표 설명보다 실제 매매계획이 더 많은 조건을 제공한다
공식 계획에는 EMA21 부근 압축중 접근과 상위시간봉 문맥, ATR로 판단한 정상 변동, 매매 전제가 깨졌는지에 따른 관리가 있다. 표준 TTM fire 규칙과 이 계획은 동일한 모드로 합치지 않는다. 기존 PANIC-only/High2 대체는 저자 계획의 보편 필수조건이 아니다. 이미 실패한 PR1341 High2를 재튜닝하는 대신, 원 사례에 대응하는 기준과 기존 구현의 차이를 먼저 확정할 대상으로 선정한다. [R11][R12][G03]

### 3.2 Gajjala/Kell: 이동평균 하나가 아니라 선정된 종목의 매매 구조다
Gajjala의 실적은 계좌 수준으로 확인되고 intraday 사례도 공개되어 있다. 그러나 종목선정·시장 참여·추세의 형성과 눌림이 포함된 계좌 결과다. Kell도 phase별 가격행동을 설명한다. 따라서 모든 6개 코인의 EMA정렬이나 4봉돌파를 이 방법의 재현이라고 하지 않는다. 현재 데이터에서 동일한 선행 조건을 관측할 수 있는지, 관측할 수 없는 주식 고유 조건은 무엇인지가 비교 항목이다. [P03][P04][P02][R13]

### 3.3 Concretum: 원형 알고리즘과 성과표를 연결할 수 있는 비교 기준
Noise-Area에는 시계별 과거 변동 추정, 의사결정 시각, VWAP/밴드 청산과 자본가정이 함께 있다. 저자 MATLAB 페이지의 계산 코드까지 확인했다. 원형 결과를 얻을 때와 기존crypto모델과 비교할 때의 시장/비용을 분리한다. Python 확장본의 NightGapReversal을 원 논문 baseline으로 섞지 않는다. [R01][R02][R03]
Stocks-in-Play ORB의 전일/당일 정보 경계와 종목선정은 진입만큼 중요하다. 이 논문의 5m·15m·30m 결과는 동일하지 않다. QQQ 전용 공개 ORB 코드가 존재해도 약7000종목+상대거래량 top20 전체 데이터 연구를 이미 복제한 것은 아니다. [R04][R05]

### 3.4 R2/Turtle: 숫자·시간·거래 생애를 그대로 읽고, 이식은 별도로 선언한다
R2의 200일 추세조건과 연속3일 RSI2 순서, 종가 신호/청산을 15분봉 몇 개로 조용히 바꾸지 않는다. Turtle의 System1/2, 변동성 N, 직전breakout 승패 처리, 실제체결 기준 추가unit, 승리포지션 청산도 하나의 비교 구조다. 사용자의 현재 스캘핑 범위를 늘리는 작업 승인이 생기는 것은 아니며, 일봉 원형은 원자료 일치 검사와 독립 번역의 기준이다. [R06][R08]

### 3.5 공개 코드도 무조건 복사하면 안 되는 사례
FMZ R-Breaker는 설명식과 코드의 r3가 다르고, stop이 빠진 예제라고 스스로 명시한다. DGT는 진짜 spot 재고를 보유하는 모델이라 선물의 청산·funding·유한 위험과 직접 호환되지 않는다. 성공 수치를 보았다는 이유만으로 이 둘을 운영에 넣지 않는다. [R25][R21][R22]

## 4. 원래 25개 전부의 선정 결과

**아래 비교 항목은 직접 조사한 자료와 저장소 차이를 바탕으로 내가 정한 연구 질문이다. 아직 계산하지 않은 개선효과나 신규 SSOT 등급을 뜻하지 않는다.**

| # | 기존 식별자 | 선정 donor / 연결 방식 | 우선 판단 |
|---|---|---|---|
| 1 | `alpha_combo` | D01, D02, D07 — 독립 원형 없는 자체 합성: 구성 모델을 명시한 새 비교 | 완성 비교 모델의 개별 검증 이후 제한된 연구 조합. 정식 B×B 승격 우회 금지. |
| 2 | `anchor_vwap_trend` | D11 — 원래 AVWAP 방법의 역할 대응 | 문맥/진입 참조 부품 후보. 기존 실패 reset/crossover를 그대로 재실행하지 않음. |
| 3 | `bb_revert` | D12, D07 — Bollinger 원칙 검수 + R2 명시적 대체 비교 | 기존 BB 모델 그대로 보존; 반전 문맥 부품 또는 별도 R2 비교. |
| 4 | `break_and_continue` | D03, D02, D04 — Gajjala intraday VCP 원 사례 우선; ORB는 별도 대체 비교 | 현재 실패 계보와 별개 기준 구현. 현재 원장이 원 VCP를 반증한다고 하지 않음. |
| 5 | `ema_ribbon_scalp` | D05, D10 — Kell 가격주기 역할 + Guppy 묶음 문맥 | 사례 기반 역할 부품부터 검수. 원 계좌941.1%를 EMA 결과로 귀속하지 않음. |
| 6 | `fvg_revert` | D16 — ICT 원형 정의를 확인할 대상; 성공 모델로 확정하지 않음 | 정의·사례 확보가 먼저. 계좌 수익이 검증된 완성 donor로 표시하지 않음. |
| 7 | `grid_rebalance` | D14 — 현물 inventory grid 원 연구와 기존 bounded-reversion 분리 | 원형 학습/현물 대조만 우선. 무손절 장기재고를 사용자 레버리지 선물에 이식하지 않음. |
| 8 | `keltner_trend` | D09 — Raschke Holy Grail 원형 대응 | 기존 parent 보존, 완료ADX변경 재시험 금지. 원형 전체 대응의 미확인 부분만 보완. |
| 9 | `liquidity_sweep` | D15 — Rotter 수익 시스템 대신 관측 가능한 order-flow 부품 검증 | 실제 BBO size/순서가 없으면 자료 보류. 기술 부품 결과를 Rotter 계좌 재현으로 표시하지 않음. |
| 10 | `mfi_rsi_div` | D13 — 공식 지표와 동일 가격 pivot의 divergence 검증 | 논리 결함과 재료 기여를 따로 검증; 독립 전략으로 수익 보장하지 않음. |
| 11 | `obv_trend` | D13, D03, D04 — OBV 산식 기준 + 성공사례의 거래량 문맥과 분리 비교 | 문맥 부품 우선; Minervini/Gajjala 계좌 수익을 OBV 수익이라고 하지 않음. |
| 12 | `pivot_reversal` | D09, D18 — Raschke swing 문맥 / Williams pivot 정의 검토 | 역할 기준 명료화 후 경제검증. 유명 trader 계좌성과로 미공개 pivot 규칙을 정당화하지 않음. |
| 13 | `range_fade` | D09, D07 — Raschke range 문맥 + Connors 별도 반전 대조 | 기존 역할과 반전 독립 모델 비교를 분리. 동일 실패 0.7ATR 변형 반복 금지. |
| 14 | `rbreaker_like` | D17, D02 — R-Breaker demo 산식/상태 검수; 검증성과 ORB는 다른 비교 | 정통 원규칙·위험정의 확보는 보류. Stocks-in-Play ORB를 대체 시험하면 별도identity. |
| 15 | `rsi_swing_fail` | D13, D07 — RSI14 failure-swing 원 정의 + R2 별도 비교 | 완료 RSI14 재실행 금지; 대체 모델 또는 청산재료 질문은 별도연구. |
| 16 | `scalp_snap` | D03 — Gajjala Bull Flag intraday 사례를 가격·참여 모델로 사용 | 미시구조 전략을 가장하지 않는 별도 가격행동 비교. |
| 17 | `session_bias` | D01, D02 — 시계별 noise/participation 원 연구 | 완성 원연구의 clock모듈 재사용. 코인에서 같은 효과는 미검증. |
| 18 | `squeeze_break` | D06 — Carter 실제 Trading Plan vs 현재 TTM fire 변형 | 원형 양수 대조군 보존; 이미 실패한 High2 replacement/4bar/BE축 반복 금지. |
| 19 | `sr_levels` | D06, D11 — Carter Box Trades의 수준/실패/목표 관계 + AVWAP 역할 | 출처 사례로 box형성 공백 보완 후 역할 또는 별도구조 비교. 기존참조수선 재실행 금지. |
| 20 | `supertrend_pullback` | D13 — Olivier Seban 계열 공식 구현 및 stop/context 역할 | 정의·부품 벤치마크. 수익형독립전략 승격은 별도증거 필요. |
| 21 | `trend_ma_macd` | D10, D13 — GMMA 문맥과 MACD모멘텀의 서로 다른 역할 | 문맥/trigger 부품 비교 우선. 자체3EMA라벨오류를 고쳤다는 이유로수익PASS 금지. |
| 22 | `trend_rider` | D10, D01, D05 — GMMA 원역할 확인; Noise-Area는 명시적 대체 기준 | Noise-Area 원구현 검수의 우선순위 높음. 기존Rider명칭과원형을바꾸지않음. |
| 23 | `turtle_trend` | D08 — 원 Turtle System1/2 전체 의미 대응 | 원형논리 및 source시장fixture검증. 일봉성과를30m로상속하지않고 실제선물위험한도는SSOT유지. |
| 24 | `vol_spike_fade` | D05, D09, D15 — Kell exhaustion / Raschke swings / 실제flow의 역할 분리 | 청산/문맥부품선정. 근거없는spike만의신규entry반복금지. |
| 25 | `vwap_revert` | D11, D01, D09 — anchor/VWAP의 문맥과 trend/reversion을 분리 | anchor문맥부품및명시적추세대조. VWAP-trend논문을VWAP-reversion성과로부르지않음. |

### 01. `alpha_combo`
**선정:** D01, D02, D07 / 독립 원형 없는 자체 합성: 구성 모델을 명시한 새 비교
**현재 차이:** 기존 점수투표/정성 regime 전환은 유명 트레이더의 공개 완성 규칙과 대응되지 않는다. [G01–G03]
**이유:** 지표 수를 늘리는 것이 아니라 수익 발생 방식이 다른 검증 모델을 재사용할 수 있다.
**비교할 항목:**
1. 구성별 원형 단독 결과와 겹치는 진입·손실 시점을 분리한다.
2. Noise-Area 추세와 R2 반전 등을 동일 전략이라고 합치지 않고 별도 계보로 둔다.
3. 선택 조건이 사전 관측 가능한지와 cash 선택을 명세화한다.
4. 조건부 배분의 증분손익·공통손실·추가 비용을 독립 성과와 나눠 본다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 현재 alpha_combo 자체를 성공한 저자의 원형이라고 할 근거 없음; 각 구성의 crypto 성과 필요.
**처리:** 완성 비교 모델의 개별 검증 이후 제한된 연구 조합. 정식 B×B 승격 우회 금지.

### 02. `anchor_vwap_trend`
**선정:** D11 / 원래 AVWAP 방법의 역할 대응
**현재 차이:** rolling swing/fetch-window anchor와 의미 있는 사건의 고정 anchor가 혼재. 기존30m AVWAPv10 실패도 있다. [G01–G03]
**이유:** AVWAP는 임의 rolling 평균과 다른 참여자 평균 원가 문맥을 제공하므로 정의를 먼저 맞춰야 한다.
**비교할 항목:**
1. anchor 사건과 그 사건을 알게 된 시각을 고정한다.
2. pivot을 나중에 확인한 뒤 과거 저점부터 즉시 알고 있었다고 하지 않는다.
3. 가격의 anchor 재접촉·이탈·회복을 서로 다른 조건으로 비교한다.
4. 동일 방향 진입에 참조선으로 넣었을 때 손실·승리 훼손과 점유를 측정한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Shannon 전체 공개 사례/실행 세부와 전략별 계좌 성과 미확보; 발표 위치는 확인.
**처리:** 문맥/진입 참조 부품 후보. 기존 실패 reset/crossover를 그대로 재실행하지 않음.

### 03. `bb_revert`
**선정:** D12, D07 / Bollinger 원칙 검수 + R2 명시적 대체 비교
**현재 차이:** 단순 밴드 복귀를 자체 stop/timeout과 연결한 변형을 Bollinger 전체 방법처럼 읽으면 안 된다. [G01–G03]
**이유:** 반전의 문맥을 설명한 저자 규칙과 명확한 통계 모델을 각각 활용할 수 있다.
**비교할 항목:**
1. band tag와 실제 반전 조건을 구분한다.
2. 추세가 밴드를 따라 진행하는 경우를 무조건 역매매하지 않는다.
3. 밴드 산식/중심선과 실제 청산의 의미를 분리한다.
4. R2를 비교할 경우 RSI2 일봉 원형과 BB 모델을 다른 identity로 유지한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Bollinger 원칙만으로 완결된 수익전략의 stop/target이 정해지지 않음.
**처리:** 기존 BB 모델 그대로 보존; 반전 문맥 부품 또는 별도 R2 비교.

### 04. `break_and_continue`
**선정:** D03, D02, D04 / Gajjala intraday VCP 원 사례 우선; ORB는 별도 대체 비교
**현재 차이:** 이동20봉 채널과 literal/shallow retest는 종목선정·반복 수축을 갖춘 intraday VCP 또는 session ORB가 아니다. [G01–G03]
**이유:** Gajjala는 실제 intraday 성과/사례가 있어 일봉VCP를 이름만30m로 바꾸는 것보다 시간축 비교가 명료하다.
**비교할 항목:**
1. 진입 전에 이미 강한 참여·유동성이 있었는지와 가격수축의 순서를 확인한다.
2. 거래량 감소가 최초 상승의 감소인지 눌림에서의 매도 감소인지 구분한다.
3. 실제 돌파 순간과 종가 후 next-open 진입 지연을 비교한다.
4. 원 사례의 무효화 지점과 보유 전제를 기존 pivotstop/timeout과 대조한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 750건 전체 거래 및 패턴별 독립 WR/DD 미확보; 사례로부터 무근거 임계치 생성 금지.
**처리:** 현재 실패 계보와 별개 기준 구현. 현재 원장이 원 VCP를 반증한다고 하지 않음.

### 05. `ema_ribbon_scalp`
**선정:** D05, D10 / Kell 가격주기 역할 + Guppy 묶음 문맥
**현재 차이:** EMA3개 정렬을 두 GMMA 묶음이나 완전한 trend continuation setup으로 부르면 안 된다. [G01–G03]
**이유:** 수익 계좌가 확인되는 Kell의 phase-based 방법은 EMA 정렬만으로 매매하는 기존 문제와 직접 비교할 수 있다.
**비교할 항목:**
1. Wedge Pop/EMA Crossback/Base-n-Break을 동일 cross 신호로 합치지 않는다.
2. 진입 전 impulsive leg와 후속 눌림의 구분을 사례에 결속한다.
3. 추세 유지 상태와 exhaustion/실패 상태를 나눠 본다.
4. Guppy 부품 사용 시 실제 두 묶음인지 확인하고 Rider와 중복 경제실행을 제거한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Kell 유료/이메일 framework의 세부가 아직 모두 확보된 것은 아니다.
**처리:** 사례 기반 역할 부품부터 검수. 원 계좌941.1%를 EMA 결과로 귀속하지 않음.

### 06. `fvg_revert`
**선정:** D16 / ICT 원형 정의를 확인할 대상; 성공 모델로 확정하지 않음
**현재 차이:** 기존 failed-displacement analogue는 canonical FVG 기하를 재현했다는 근거가 없다. [G01–G03]
**이유:** 원형을 확인할 직접 자료의 위치가 있으며 다른 저자를 인용한 가짜 FVG 재현을 피할 수 있다.
**비교할 항목:**
1. 공식영상 11:31 FVG·18:29 MSS·37:59 FVG 구간에 각 코드 조건의 원문 근거를 연결한다.
2. 3개 봉 가격영역과 일반 갭/장대봉 되돌림을 구분한다.
3. 구조전환·선행 유동성 사건·유효기간이 원 영상에서 실제 요구되는지 확인한다.
4. 미체결/invalidated gap을 사후 회복한 gap과 함께 기록한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 공식영상 자막 전문/차트 전체·독립 성과 미확보; 이 행은 구현준비 완료가 아님.
**처리:** 정의·사례 확보가 먼저. 계좌 수익이 검증된 완성 donor로 표시하지 않음.

### 07. `grid_rebalance`
**선정:** D14 / 현물 inventory grid 원 연구와 기존 bounded-reversion 분리
**현재 차이:** 기존은 제한된 반전 매매로 실제 grid 재고·리셋·현금 재투자를 재현하지 않는다. [G01–G03]
**이유:** 코인 원 데이터와 알고리즘·저자 코드가 있어 무에서 새 grid를 만들 필요가 없다.
**비교할 항목:**
1. 재고·현금·미실현손익을 함께 계산한다.
2. 상단/하단 이탈 후 재투입 자본의 출처를 구분한다.
3. 유한 자본·체결 순서·격자별 비용을 검사한다.
4. spot 원형과 perp funding/청산/손절을 포함한 변형을 다른 모델로 둔다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 독립 forward·parameter-selection 편향 및 실제 체결 효과 미검증; 약50%DD를 저위험으로 부르지 않음.
**처리:** 원형 학습/현물 대조만 우선. 무손절 장기재고를 사용자 레버리지 선물에 이식하지 않음.

### 08. `keltner_trend`
**선정:** D09 / Raschke Holy Grail 원형 대응
**현재 차이:** 원형의 초기 강도→눌림→조건부 진입과 현재 GMMA/시장상태/종가확인/runner가 섞여 있다. PR1340 초기ADX변경은 이미 실패. [G01–G03]
**이유:** 현재 양수 대조군을 보존하면서 원래 의도했던 추세 눌림 매매의 누락/추가를 검증할 수 있다.
**비교할 항목:**
1. 강한 추진을 확인한 시점과 후속 눌림을 분리한다.
2. 원문의 이전 봉 고가 조건부 주문과 종가확인/next-open 차이를 기록한다.
3. 무효화 swing과 정상 눌림 허용 범위를 원 성공·실패 사례로 확인한다.
4. 원문에 없는 무제한 자격·일괄scratch·BE는 원형과 별도 이식 선택으로 둔다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 원저자의 공통기간 PnL/WR/DD 원장 없음; 원 resting-order를 지원하는 실제 재현 엔진 필요.
**처리:** 기존 parent 보존, 완료ADX변경 재시험 금지. 원형 전체 대응의 미확인 부분만 보완.

### 09. `liquidity_sweep`
**선정:** D15 / Rotter 수익 시스템 대신 관측 가능한 order-flow 부품 검증
**현재 차이:** OHLC sweep는 실제 잔량·취소·aggressor flow·queue 변화를 알 수 없다. [G01–G03]
**이유:** OFI 원 연구는 필요한 데이터가 무엇인지 명확해 가격패턴에 order-flow라는 이름만 붙이는 것을 막는다.
**비교할 항목:**
1. 직전 유동성 수준·호가잔량·거래 방향의 실제 공급 필드를 확인한다.
2. 동시 가격충격 설명과 다음15m/30m 예측을 분리한다.
3. 가격 수준 침범 후 반응을 관측된 order-flow와 대조한다.
4. 부품을 넣은 경우 피한 손실·놓친 winner·시간지연을 측정한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Rotter 원 매매법/독립 검증 소득 원장 및 사용자 데이터의 완전한 OFI 결속 미확보.
**처리:** 실제 BBO size/순서가 없으면 자료 보류. 기술 부품 결과를 Rotter 계좌 재현으로 표시하지 않음.

### 10. `mfi_rsi_div`
**선정:** D13 / 공식 지표와 동일 가격 pivot의 divergence 검증
**현재 차이:** canonical 포함-current extreme 조건의 도달불가와 이전5m one-bar turn이 별개 문제다. [G01–G03]
**이유:** 단순 oscillator 방향변화 대신 divergence를 시험해야 해당 재료를 공정하게 평가할 수 있다.
**비교할 항목:**
1. 가격의 두 pivot에 해당하는 MFI/RSI 값을 같은 시각으로 연결한다.
2. pivot 확인 시각 이전에는 미래 오른쪽 봉을 사용하지 않는다.
3. MFI 입력이 실제 가격×거래량 단위인지 확인한다.
4. 청산/위험 부품으로 사용할 때 정상 승리를 잘라내는 정도를 대조한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 이 복합 지표로 특정 성공 트레이더가 번 순손익의 직접 증거 없음.
**처리:** 논리 결함과 재료 기여를 따로 검증; 독립 전략으로 수익 보장하지 않음.

### 11. `obv_trend`
**선정:** D13, D03, D04 / OBV 산식 기준 + 성공사례의 거래량 문맥과 분리 비교
**현재 차이:** OBV 산식은 기존에도 맞았다. 문제는 신호/청산을 임의 결합한 경제모델이다. [G01–G03]
**이유:** 원 계산을 다시 고치는 낭비 대신 참여 확인 부품으로서의 질문을 직접 시험할 수 있다.
**비교할 항목:**
1. 동일 close에서 누적변화 처리 등 원 산식을 유지한다.
2. OBV trend와 당일 비정상 참여/눌림 거래량을 다른 feature로 구분한다.
3. 현재 비용·시장문맥을 고정하고 해당 feature의 기여를 분리한다.
4. 유사 volume filter의 중복 여부를 확인한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** OBV-only 검증수익 미확보. 실제 역할 시험은 아직 별도 필요.
**처리:** 문맥 부품 우선; Minervini/Gajjala 계좌 수익을 OBV 수익이라고 하지 않음.

### 12. `pivot_reversal`
**선정:** D09, D18 / Raschke swing 문맥 / Williams pivot 정의 검토
**현재 차이:** rolling extrema·꼬리와 이전 session의 산술 pivot이 혼용됐다. [G01–G03]
**이유:** pivot 수식을 바꾸는 것보다 실제 거래 상황을 원 인터뷰의 가격구조와 일치시키는 것이 우선이다.
**비교할 항목:**
1. 어떤 종류 pivot인지 먼저 고정한다: 확인된 swing 또는 이전session HLC 기준.
2. reference가 현재 판단 이전에 확정됐는지 확인한다.
3. range 내부 반전과 강한 추세의 정상눌림을 분리한다.
4. 재돌파/무효화/목표가 같은 reference 의미를 사용하는지 대조한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Oops 등 이름만 언급된 패턴의 완전 원규칙과 별도 수익은 미확보.
**처리:** 역할 기준 명료화 후 경제검증. 유명 trader 계좌성과로 미공개 pivot 규칙을 정당화하지 않음.

### 13. `range_fade`
**선정:** D09, D07 / Raschke range 문맥 + Connors 별도 반전 대조
**현재 차이:** 현재20봉box/ATR거리/목표는 자체 번역이며 range 문맥과 시간축의 원 대응이 부족하다. [G01–G03]
**이유:** 모든 약세를 같은 반전으로 처리하지 않고 원자료가 구별하는 시장문맥을 비교할 수 있다.
**비교할 항목:**
1. 여러 봉 중첩과 방향성 swing을 구분한다.
2. range 경계 반전과 range중앙 추격 진입을 분리한다.
3. 진입을 발생시킨 같은 range reference로 무효화와 목표를 표현한다.
4. R2 대조는 일봉 추세 속 반전이며 횡보range 원형과 다른 모델임을 유지한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 원문 정성 range조건을 계량화한 후보의 별도 경제성과 필요.
**처리:** 기존 역할과 반전 독립 모델 비교를 분리. 동일 실패 0.7ATR 변형 반복 금지.

### 14. `rbreaker_like`
**선정:** D17, D02 / R-Breaker demo 산식/상태 검수; 검증성과 ORB는 다른 비교
**현재 차이:** 현재 rolling20 돌파·반전은 전일 HLC 기반 daily levels/상태와 다르다. [G01–G03]
**이유:** 직접 공개코드를 확인하면 이름뿐인 R-Breaker와 실제 reference/상태 차이를 검출할 수 있다.
**비교할 항목:**
1. 이전session HLC로 만들어 당일 고정하는 기준선과 이동채널을 분리한다.
2. flat의 breakout과 보유 후 관찰선→반전선 재진입을 다른 상태로 둔다.
3. 공개FMZ 설명 r3의 /2와 실제코드 불일치를 그대로 받아쓰지 않는다.
4. 원 demo의 stop 누락을 자체숫자로 메우고 원형완료라고 하지 않는다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Futures Truth 원 순위표/검증 PnL/WR/DD 미확보. 인기 서술은 성공데이터로 계산하지 않음.
**처리:** 정통 원규칙·위험정의 확보는 보류. Stocks-in-Play ORB를 대체 시험하면 별도identity.

### 15. `rsi_swing_fail`
**선정:** D13, D07 / RSI14 failure-swing 원 정의 + R2 별도 비교
**현재 차이:** price sweep parent와 oscillator child는 다르며 PR1340 oscillator 단독 실험 실패가 있다. [G01–G03]
**이유:** R2에는 거래수·승률·보유기간과 구체적 규칙이 같이 있어 검증 가능한 대체 반전 모델이다.
**비교할 항목:**
1. 이미 완료된 RSI14 순서복원/경제실험은 재사용한다.
2. 거래량·가격조건을 혼합한 parent와 oscillator pattern을 구분한다.
3. R2 원형은 RSI2·200일시장조건·3일순서·RSI2청산으로 별도기준을 둔다.
4. 과거 높은 WR를 15m/30m에 그대로 목표치로 이식하지 않는다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** R2 거래비용/MDD 미공개·레버리지용 stop 미정. RSI14 원형을 반증했다고 말할 수 없음.
**처리:** 완료 RSI14 재실행 금지; 대체 모델 또는 청산재료 질문은 별도연구.

### 16. `scalp_snap`
**선정:** D03 / Gajjala Bull Flag intraday 사례를 가격·참여 모델로 사용
**현재 차이:** 체결가격 snap을 미시구조 피로로 해석하는 근거가 없다. [G01–G03]
**이유:** 실제 intraday trader의 가격/volume 사례를 써서 OHLC만으로 관측 가능한 부분부터 정직하게 비교할 수 있다.
**비교할 항목:**
1. 기존 impulse의 종목선정·거래량 참여를 확인한다.
2. 강한 추진과 조용한 눌림, 재개 trigger를 구분한다.
3. 원 사례의 빠른 발생 시간과15m/30m관측 지연을 측정한다.
4. 두세봉짜리 기회가 30m에서는 사라지면 TF부적합으로 남긴다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 전략별 거래원장·정확 stop/exit 전체 미확보; 계좌805% 상속 불가.
**처리:** 미시구조 전략을 가장하지 않는 별도 가격행동 비교.

### 17. `session_bias`
**선정:** D01, D02 / 시계별 noise/participation 원 연구
**현재 차이:** 임의 UTC 금지시간과 거래소 session의 공급수요 변화를 혼동했다. canonical current-extreme 버그도 별도다. [G01–G03]
**이유:** 단순히 몇 시에는 거래금지가 아니라 원자료가 계량화한 장중 참여·변동의 차이를 이식할 수 있다.
**비교할 항목:**
1. 같은 시각의 과거 변화/거래량 기준을 당일정보와 구분한다.
2. 미국 개장·마감과 DST를 원형재현에 보존한다.
3. 24/7 코인의 기준시각 선택은 별도 시장이식 가설로 둔다.
4. 세션 입력이 없는 대조와 signal/cost/자본 동일하게 비교한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 새 equity원천과 사용자 crypto데이터의 양쪽 비교 및 실행관측 차이 필요.
**처리:** 완성 원연구의 clock모듈 재사용. 코인에서 같은 효과는 미검증.

### 18. `squeeze_break`
**선정:** D06 / Carter 실제 Trading Plan vs 현재 TTM fire 변형
**현재 차이:** 현재PANIC-only fire 이후 High2대체는 Carter 전체계획과 다르며 PR1341지연대체는 실패. [G01–G03]
**이유:** 기존 지표개요보다 구체적 저자 진입·관리 계획이 공개돼 있어 High2를 발명할 필요가 줄어든다.
**비교할 항목:**
1. 공식계획의 EMA21부근 압축중 접근과 fire 후 진입을 서로 다른 mode로 구분한다.
2. 일봉방향/상대적고점·상위TF 문맥이 현재PANIC상태와 같은지 대조한다.
3. 원 위험기준의 ATR시간범위와 기존trigger-low/330분deadline을 비교한다.
4. 일반계획과 TTM 플랫폼규칙, 옵션표현과 선물표현을 섞어 새 원형을 발명하지 않는다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Carter 전체계좌 자기보고를 30m BTC Squeeze 수익으로 사용할 수 없음; 세부모드 완결검수 필요.
**처리:** 원형 양수 대조군 보존; 이미 실패한 High2 replacement/4bar/BE축 반복 금지.

### 19. `sr_levels`
**선정:** D06, D11 / Carter Box Trades의 수준/실패/목표 관계 + AVWAP 역할
**현재 차이:** reference 오류 수선은 실행됐지만 임의 prior50과25분scratch가 경제적 정합성을 증명하지 않는다. [G01–G03]
**이유:** 단순한 선 하나가 아니라 진입·실패·목표를 연결하는 공개 규칙을 가져올 수 있다.
**비교할 항목:**
1. Carter 공개 box폭 목표와 box내종가복귀 실패를 같은 reference로 묶는다.
2. box 형성의 시작/끝을 미래정보 없이 지정한다.
3. 기존 stop/첫30분scratch와 source-based 무효화가 다른 사건을 만드는지 확인한다.
4. reference를 진입기 아닌 위험/문맥 재료로 쓸 때 marginal기여를 분리한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Carter가 이 box모드 하나로 얻은 검증손익 미확보; box검출 임의값을 원문으로 표시 금지.
**처리:** 출처 사례로 box형성 공백 보완 후 역할 또는 별도구조 비교. 기존참조수선 재실행 금지.

### 20. `supertrend_pullback`
**선정:** D13 / Olivier Seban 계열 공식 구현 및 stop/context 역할
**현재 차이:** native ATR/trailing은 이미 구현돼 있으며 자체 entrypattern의 실패와 지표 역할이 혼동됐다. [G01–G03]
**이유:** 최소기술원형을 공식산식으로 고정한 뒤 경제역할을 정확히 시험할 수 있다.
**비교할 항목:**
1. 공식밴드 recurrence/초기화·gap후reset을 대조한다.
2. 기존추적stop과 중복되는 새모듈을 만들지 않는다.
3. 같은 원형진입에서 방향문맥 또는 stop 역할 한 가지의 기여를 본다.
4. 단순방향flip을 완성된수익전략으로 취급하지 않는다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 공개 검증된 Supertrend-only 수익률/WR/DD 미확보.
**처리:** 정의·부품 벤치마크. 수익형독립전략 승격은 별도증거 필요.

### 21. `trend_ma_macd`
**선정:** D10, D13 / GMMA 문맥과 MACD모멘텀의 서로 다른 역할
**현재 차이:** EMA3개 정렬을 GMMA로 부른 표기와 독립MACD효과가 섞여 있다. [G01–G03]
**이유:** 비슷한 지표를 더하는 대신 각 부품이 독립적 정보를 추가하는지 볼 수 있다.
**비교할 항목:**
1. 원형평균묶음의 상대관계와 MACD 산식을 각각 고정한다.
2. 둘이 사실상 같은 모멘텀정보를 반복투표하는지 측정한다.
3. 진입재개 확인과 추세상태 정의를 한 조건으로 합치지 않는다.
4. PR1341 Rider의 실제 GMMA 구현/실패를 회수해 중복재현하지 않는다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** Guppy/Appel 이름만으로 복합전략 계좌수익을 뒷받침하지 못함.
**처리:** 문맥/trigger 부품 비교 우선. 자체3EMA라벨오류를 고쳤다는 이유로수익PASS 금지.

### 22. `trend_rider`
**선정:** D10, D01, D05 / GMMA 원역할 확인; Noise-Area는 명시적 대체 기준
**현재 차이:** PR1341은 진짜2묶음GMMA를 구현했지만 자체entry/stop조합이 음수. 다시 GMMA추가를 제안하면 중복이다. [G01–G03]
**이유:** 기존지표조합을 재발명하는 대신 명확한 시간·청산·성과·원코드가 함께 있는 intraday 비교기준을 확보한다.
**비교할 항목:**
1. 기존V2와PR1341둘다회수하고 source전략과 자체조합의경계를 고정한다.
2. Noise-Area원연구의 동시간기대변동·진입시각·VWAP청산을 완성모델로 비교한다.
3. paper기본형과NightGapReversal확장코드를 구분한다.
4. 기존Rider의 직접개선이 아니라 대체benchmark인 경우 그렇게보고한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** SPY시장구조·실제주당비용을 crypto에복사할수없고 새시장성과는미실행.
**처리:** Noise-Area 원구현 검수의 우선순위 높음. 기존Rider명칭과원형을바꾸지않음.

### 23. `turtle_trend`
**선정:** D08 / 원 Turtle System1/2 전체 의미 대응
**현재 차이:** 20봉돌파/ATRrunner/Donchian10청산 일부는 전체시스템을 대표하지 않는다. [G01–G03]
**이유:** 공개27페이지가 진입부터 크기·청산까지 제공해 단순Donchian조합보다 원형재현공백이작다.
**비교할 항목:**
1. 20/55일System을 구분하고1의직전break가상승패·failsafe를포함한다.
2. N의초기값/재귀·변동성정규화·추가입력 actualfill을검증한다.
3. 진입과10/20일반대채널청산의 결합을유지한다.
4. 원다시장상관한도·승리집중과15m/30m이식차이를분리한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 원계좌전체검증시계열 및사용자시간범위에서의새경제증거미확보.
**처리:** 원형논리 및 source시장fixture검증. 일봉성과를30m로상속하지않고 실제선물위험한도는SSOT유지.

### 24. `vol_spike_fade`
**선정:** D05, D09, D15 / Kell exhaustion / Raschke swings / 실제flow의 역할 분리
**현재 차이:** 거래량급증이나 장대봉을 곧바로 소진·반전으로 처리하는 근거가 부족하다. [G01–G03]
**이유:** 강한상승을역매매하는실수를피하려면매매주기상위치와가격반응이필요하다.
**비교할 항목:**
1. 추세초기 수요확장과 후반exhaustion을 source사례로구분한다.
2. 높은거래량 이후가격이 계속진전하는지 막히는지 따로관측한다.
3. 실제flow버전은 BBO/aggressor시간과단위가있어야한다.
4. 청산부품으로사용할때fatwinner를너무일찍자르는지비교한다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 구체적원exhaustion기계명세·부품별수익미확보; 계좌Kell성과로대신하지않음.
**처리:** 청산/문맥부품선정. 근거없는spike만의신규entry반복금지.

### 25. `vwap_revert`
**선정:** D11, D01, D09 / anchor/VWAP의 문맥과 trend/reversion을 분리
**현재 차이:** fetch-window누적·rolling20VWAP를원session/anchorVWAP와동일시했다. [G01–G03]
**이유:** VWAP를쓴다는것보다어떤가격행동에서지속/회귀로해석하는지가현재실패와직접연결된다.
**비교할 항목:**
1. 누적시작과reset을명확히하고입력창변경으로reference가바뀌지않게한다.
2. VWAP위추세지속과VWAP회귀를서로다른가설로둔다.
3. 단순이격크기가아닌시장문맥을원자료사례에결속한다.
4. 같은기회에반전보조를넣었을때추세winner훼손과손실회피를함께본다.
**수익 근거:** §2의 해당 donor에만 귀속한다. 우리 전략 수익은 미실행이다.
**남은 근거:** 원숫자없는정성문맥의계량화와독립crypto경제비교가필요.
**처리:** anchor문맥부품및명시적추세대조. VWAP-trend논문을VWAP-reversion성과로부르지않음.

## 5. 판단이 실제로 바뀐 점
1. 원래25개 전체의 식별자와 비교항목을 유지했다. 몇 개새실험이 끝나도나머지25개의확인상태를대신하지않는다.
2. 새 비교모델과 기존 방법의 원형재현을 분리했다. 예컨대 Noise-Area는 Rider의 경제적 대체비교이지 GMMA원형이 아니다.
3. 트레이더 계좌의 성공과 특정규칙의 성공, 저자백테스트와실계좌수익을구분했다.
4. 지표원리만확인한 항목은그상태그대로남겼다. 이 자료들에근거하지않는임의성과/원형규칙을덧붙이지않았다.
5. 완결된수치규칙이있는원자료·저자코드를확보했지만, 원시장실제데이터/원실행조건복제와crypto변형검증은별도로남아있다.

## 6. 자료별 실제 확인 범위와 링크

Sourcing은 아래 원자료와 저장된 코드감사에 한정된다. 링크가 존재하는 것, 본문을 읽은 것, 코드가 실행된 것은 서로 다른 상태다. 공개 저자수익은 명시한 과거 기간이며 현재매월소득이 아니다.

### G01. 원래 25개 donor-native 명세
https://github.com/leegkssk2000-commits/vultr-z/blob/58964a346a733d1a45e919c7c8d4087f05c8da3c/backend/research/rebuild/benchmark25_donor_native_spec_v1.json
기존 회수 명세와 이번 원래25 계약으로 식별자 대조. donor_native라는 이름은 원형 재현 인증이 아니다.

### G02. 기존 27개 원자료·계보 감사
https://github.com/leegkssk2000-commits/vultr-z/blob/58964a346a733d1a45e919c7c8d4087f05c8da3c/research/campaigns/scalp7_20260917/source_fidelity_v1/audits/AUDIT_27.md
전체 관련 행과 후반 재료 행을 읽음. 선행 감사 snapshot이므로 이후 PR1340/1341 실행 상태와 구분.

### G03. PR1341 고정 최종 보고
https://github.com/leegkssk2000-commits/vultr-z/blob/58964a346a733d1a45e919c7c8d4087f05c8da3c/research/campaigns/scalp7_20260920/economic_development_v1/FINAL_REPORT.md
대화에서 원문·코드·원장 진단 회수. Squeeze High2/Rider 두 구조 실패는 보존.

### P01. 2021 US Investing Championship — Minervini
https://financial-competitions.com/previousstandings/2022/1/18/december-31-standings
주최자 표 직접 확인: 2021, $1m+ STOCK DIVISION, +334.8%. 특정 VCP 하나의 성과가 아니다.

### P02. 2020 US Investing Championship — Kell
https://financial-competitions.com/previousstandings/2021/1/13/december-2020-standings
주최자 표 직접 확인: 2020 STOCK DIVISION +941.1%. 전략별 WR/DD를 제공하지 않는다.

### P03. Gajjala — Business Insider 원 인터뷰
https://www.businessinsider.com/stock-trader-shares-easy-chart-pattern-he-trades-2024-8
원 인터뷰 본문 확인. 기자가 주최자 Norman Zadeh를 인용해 2023 +805% 확인. 특정 패턴 수익으로 귀속 금지.

### P04. Gajjala — TraderLion 인터뷰 정리
https://traderlion.com/investing-champions/2023-us-investing-champion/
5m/15m, 종목선정·거래량·bull flag 설명 확인. 세부 WR 등은 인터뷰 공개치이며 주최자 별도 검증치와 구분.

### P05. Carter 2020 계좌 회고
https://www.simplertrading.com/news/part-1-the-road-to-an-18-2-million-year
저자 회사의 연말 회고. 자기 보고 자료이며 외부 회계검증 원본 아님.

### P06. Carter 2020 손실 월 회고
https://www.simplertrading.com/news/part-5-the-road-to-an-18-2-million-year
검색 반환 원문에서 2020년10월 TOS -32.83% 확인. 전체 페이지 재접근은 오류. 수익 홍보만 보지 않고 손실도 병기.

### P07. Carter 회사의 성과 주장
https://www.simplertrading.com/10x
2020 +1270%/$18.2m라는 회사 자체 주장. 외부 검증과 단일 Squeeze 성과로 승격하지 않음.

### R01. SPY Intraday Momentum — 원 논문
https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf
2025-09-22 개정본의 규칙·비용 본문과 표3/4 페이지 이미지 확인. 저자 백테스트; 계좌 실거래 인증 아님.

### R02. SPY 원 저자 MATLAB 구현
https://concretumgroup.com/backtesting-riding-intraday-trends-in-us-markets-using-matlab/
페이지의 변수 산식, 전략 backtest, 성과 계산 코드와 전체 코드 다운로드 링크 확인. 실행하지 않음.

### R03. SPY Python/Alpaca 확장 구현
https://concretumgroup.com/backtesting-7-years-of-free-data-beat-the-market-an-effective-intraday-momentum-strategy-for-the-sp500-etf-spy/
본문·코드 확인. WithNightGapReversal 확장 표기가 있어 원 논문 그대로인 코드로 취급하지 않음.

### R04. Stocks in Play ORB — 원 논문
https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf
원 논문 정의·데이터·비용·표2/3 이미지 확인. 약7000종목 연구의 종목선정은 전략의 일부.

### R05. QQQ 계열 ORB 공개 코드
https://concretumgroup.com/backtesting-the-opening-range-breakout-orb-strategy-using-polygon-io/
공개 코드 페이지와 Colab 링크 확인. 이것을 7000종목 Stocks-in-Play 전체 구현이라고 하지 않음.

### R06. Larry Connors Improved R2 원문
https://tradingmarkets.com/recent/the_improved_r2_strategy_84_correct_with_just_6_rules_-674361
저자 2007년 원문, 6개 규칙·102회 모의 성과·날짜 명시 사례 확인. 비용과 MDD 누락.

### R07. Original Turtle Rules 안내
https://www.tradingblox.com/originalturtles/originalturtlerules.htm
원 참가자가 공개한 규칙집 안내와 PDF 링크 확인.

### R08. Original Turtle Rules 전문
https://www.tradingblox.com/originalturtles/originalturtlerules.pdf
Firecrawl로 27페이지 전문 추출 성공. 원시 PDF 바이트 보관/해시는 미확보. 규칙을 확인했으나 원 계좌 성과를 독립 검산한 것은 아니다.

### R09. Linda Raschke Holy Grail 원 인터뷰
https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf
1997년 AIQ 원문 규칙·성공/실패 설명, 차트 페이지 이미지 확인. 원저자 연간 PnL/WR/DD 전체 없음.

### R10. Linda Raschke 가격구조 원 인터뷰
https://www.moneyshow.com/articles/videotranstr-30540/
2013년 원 인터뷰: swing/overlap/range/압축·추세 문맥. 기계적 완성전략 또는 수익표 아님.

### R11. John Carter 공식 Trading Plan
https://www.simplertrading.com/trading-plan
진입·시간봉·ATR·불변 매매 전제와 Box Trades 등 공개 계획 본문 확인. 서로 다른 setup과 자본관리 예시를 하나로 합치지 않음.

### R12. John Carter 공식 프로필·계획
https://www.simplertrading.com/traders/john-carter/
주간2.5~5%는 목표. 가격34MA/일봉정렬/고점근접은 일반 계획의 선택 문맥이지 모든 Squeeze의 보편 필수조건이 아님.

### R13. Oliver Kell 공식 Cycle of Price Action
https://kelltrading.com/
공개6단계 설명 확인. 이메일 제출/유료책/수업 미열람. 세밀한 실행규칙은 미확보로 구분.

### R14. Daryl Guppy 공식 GMMA
https://www.guppytraders.com/gmma-info
두 평균집단·압축/확산·관계 해석 확인. 공개 검증 계좌 수익률 없음.

### R15. Brian Shannon CMT 원 발표
https://cmtassociation.org/video/specific-anchored-vwap-strategies-for-all-timeframes/
발표자·주제·IPO/갭/short squeeze/여러 시간범위 설명 확인. 전체 영상/슬라이드 접근은 미완료; 모두 봤다고 표시하지 않음.

### R16. John Bollinger 공식 규칙
https://www.bollingerbands.com/bollinger-band-rules
band tag, band walking, continuation, 지표 중복 관련 원 규칙 확인. 검증 수익표 없음.

### R17. Fidelity RSI 정의
https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI
oscillator failure swing/추세별 구간 설명. Wilder의 전체 매매법이나 Connors R2와 동일하지 않음.

### R18. Fidelity MFI 정의
https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/mfi
산식과 가격 대비 divergence 설명 확인. 독립 수익률 자료 아님.

### R19. Fidelity OBV 정의
https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/obv
가격 변화 방향에 따른 거래량 누적·추세 확인 정의. 독립 수익률 자료 아님.

### R20. TradingView Supertrend
https://www.tradingview.com/support/solutions/43000634738-supertrend/
Olivier Seban 출처·산식·방향/stop 역할 확인. 공개 검증된 Seban 지표별 수익 없음.

### R21. Dynamic Grid Trading 원 논문
https://arxiv.org/html/2506.11921v1
전체 HTML의 알고리즘·비용·결과·한계 확인. 상승기 spot/재고 보유 및 파라미터 탐색 성과; leveraged perp 성과 아님.

### R22. Dynamic Grid Trading 저자 코드
https://github.com/colachenkc/Dynamic-Grid-Trading
논문이 직접 연결한 저장소 README를 GitHub connector로 확인. src/config.py·grid_logic.py·backtest.py 경로 설명; 해당 실행코드는 이번에 실행/전체 감사하지 않음.

### R23. Cont–Kukanov–Stoikov Order Book Events
https://arxiv.org/abs/1011.6402
원 논문 초록과 데이터·OFI 연구 범위 확인. 호가사건 가격충격 설명과 다음15m 수익예측을 구분.

### R24. ICT 2022 Mentorship Episode6 원 영상
https://www.youtube.com/watch?v=Bkt8B3kLATQ
공식 채널 metadata/설명/목차 확보. 11:31 FVG,18:29 MSS,37:59 FVG. 자막 전문·전체 차트 재현 미확보; 계좌영상 목차는 감사 증거 아님.

### R25. FMZ R-Breaker 공개 구현
https://www.fmz.com/digest-topic/5707
게시자의 실제 코드/설명 확인. 원 Saidenberg 규칙집은 아님. 설명r3 수식과 코드가 다르고 저자 스스로 stop 미포함 demo라고 명시.

### R26. Larry Williams 본인 연구 소개
https://ireallytrade.com/innovation/
본인 pivot/OBV 대안/volatility-breakout 논평 확인. Oops 완성 실행규칙은 이 페이지에 없음. 자기 성과 주장과 독립 인증 구분.

### R27. World Cup Trading Championships 공식
https://www.worldcupchampionships.com/
1987 Larry Williams +11,376% 기록 확인. 특정 지표 하나·현재 수익의 증거 아님.

## 7. 작업 경계와 재현성
- 신규경제실행0회, 저장소변경0건, 서비스변경0건. 이 보고서 작성으로 실행예산이나 주문권한이 늘어나지 않았다.
- 동일한실패변형은반복하지않는다. source형태와시장/시간봉/비용이달라지면새모델로기록한다.
- 필요한공개부품을여러파일에서재사용할수있지만성공한트레이더25명을억지로배정하지않는다.
- 원형의성과원장이나모든case를얻지못한항목도있다. 공백은조사한부족근거로표시했으며경제적FAIL로덮지않았다.
- Firecrawl 도구가보고한이번사용량: Turtle PDF27페이지/27크레딧, ICT페이지1크레딧, 검색0크레딧. 그 외출처는웹/연결자료조회. 유료강의·새데이터구매없음.
- 문서의여러수익률은정의가다르므로한표에서우열점수로합산하지않는다. 실제최종비교는SSOT비용·입력시각·방향·위험·자본·미완결처리일치후에만한다.

끝.
