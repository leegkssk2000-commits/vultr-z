# G4 원래 25개 벤치마크 자료 재검증 V2
기준일: 2026-09-20 | 연구자료 보완·정적 검토 | 새 전략 경제실행 0회

## 1. 판정
**V1은 비교 대상·출처 목록으로 유용했지만, 25개 전체를 바로 구현·선별할 수 있는 완결된 원형 패키지는 아니었다. V2는 실제 장중 사례·공식 매매법 매뉴얼·코드 내부·성과 부록을 추가 확인하고, 그대로 사용하면 안 되는 부분을 명시한다. 인터넷의 모든 자료를 수집했다거나 모든 미래 누락이 없다는 주장은 하지 않는다.**
이번에는 25개 전부의 자료 준비상태를 표시했다. 이 상태는 source 연구의 분류이지 검증 성공·전략 등급·경제성 PASS가 아니다. 원자료에서 확인한 사실, 그에 따른 분석, 앞으로 필요한 검증을 구별한다.

## 2. V1에서 실제로 달라진 점
### SOURCE_RAS_INTRADAY — 원 사례 추가
**확인:** 1997 일봉 예제 외 2004 원 인터뷰의 15m euro futures 사례와 30m SPX Holy Grail 차트를 확보했다. 3–10 oscillator는 SMA3−SMA10 및 차이의 SMA16이다.
**우리 작업에서의 의미:** 일봉 전략을 분봉으로 임의 압축하는 대신 실제 원저자 intraday 사례의 상태 순서와 계산을 대조할 수 있다.
**한계:** 원저자 장기간 계좌/전략별 WR·DD는 이 자료로 인증되지 않는다. 1min Short Skirt와30m Grail을 합치지 않는다.
근거: [V2_RAS_FEB04], [V2_RAS_MAR04], [V2_RAS_FAQ]

### SOURCE_BB_METHODS — 정의에서 매매법 매뉴얼로 확장
**확인:** 저자의 TradeStation Methods I–IV 매뉴얼을 읽었다. III은 밴드접촉+Intraday Intensity로 alert를 만들고 별도 가격 확인을 요구한다. II는 가격 강도와 MFI 확인을 다룬다.
**우리 작업에서의 의미:** indicator-only 정의보다 역할·사용 상황·진입 전제에 더 구체적인 근거가 생겼다.
**한계:** 매뉴얼에 없는 수치 entry·stop·exit를 만들어 완성 전략이라 하지 않는다. 플랫폼별 같은 Method명도 고정 버전으로 관리한다.
근거: [V2_BB_I], [V2_BB_II], [V2_BB_III], [V2_BB_IV], [V2_BB_ESIGNAL]

### SOURCE_AVWAP_CASE — 원 사례 추가
**확인:** Shannon의 공개 essay와 사이트의 10:38 peak→11:04 재접촉·정체→lower-high 위 stop 사례 설명을 확보했다.
**우리 작업에서의 의미:** CMT 발표 위치 확인에 그치던 상태를 넘어 anchor 사건·anchor를 알게 된 때·재접촉·위험 위치를 비교할 수 있다.
**한계:** 페이지 사례 설명을 읽었다. MP4 전체/모든 차트를 재생 검산하지 않았고 정확 entry/size/exit 및 성과 원장은 미확인.
근거: [V2_SHANNON_ESSAY], [V2_SHANNON_CASE]

### PERF_GAJJALA — 성과 출처 강화
**확인:** 대회 주최자 최종 표에서2023 Gajjala +805.1%를 직접 확인했다.
**우리 작업에서의 의미:** 기사에서 주최자를 재인용한 +805%보다 직접적인 계좌수준 출처를 추가했다.
**한계:** VCP/flag 한가지의 수익·인터뷰 WR·개별 거래크기·최대DD를 주최자가 검증한 것처럼 표시하지 않는다.
근거: [V2_GAJJALA_ORGANIZER], [P04]

### PERF_SPY_APPENDIX — 약한 기간까지 보완
**확인:** 후반 Q24 저자 업데이트는2025 Jan–Aug누적+1.0%, 과거2016−12.8%,2017−6.9%도 제시한다. 본문의19.6%는 장기연환산·변동성조절형이다.
**우리 작업에서의 의미:** 성공한 장기 평균만 보고 꾸준한 연20% 매매법으로 기대하지 않도록 성과 기간을 확장했다.
**한계:** 2025 전체/2026 현재 실계좌 수익이 아니다. 원 계좌 투자조언이나 독립모델 검증으로 쓰지 않는다.
근거: [R01]

### CODE_SPY_SNIPPET — 공식 코드 예제 불일치
**확인:** Step3 통합 코드는 lagged exposure×change_1m이고 Step3.8 설명 조각은 signal×change_1m이다.
**우리 작업에서의 의미:** 후자의 조각을 쓰면 같은 봉의 종가에서 만든 signal을 그 봉의 가격변화에 곱하고30분 의사결정 필터도 반영하지 않아 본문과 다른 계산이 된다.
**한계:** 페이지 조각의 불일치를 확인한 것이며, 올바른 lagged exposure를 쓰는 본문이나 논문 전체가 잘못됐다고 단정하지 않는다. 실행은 하지 않았다.
근거: [R02]

### CODE_DGT_SIGNATURE — 정적 인터페이스 결함
**확인:** handle_down_break 호출13개 위치인자 대 정의12개. settle_last_grid_segment 호출에max_price 키워드가 있지만 정의에는 없다.
**우리 작업에서의 의미:** 선택한 고정 modular code는 해당 경로에서 그대로 실행 가능한 원본 기준으로 취급할 수 없다.
**한계:** 해당 파일의 호출/정의 비교다. 다른 미검토 버전이나 논문 결과 전체를 무효라고 하지 않는다. 실제 시장 backtest 재현 없음.
근거: [V2_DGT_RUNNER], [V2_DGT_LOGIC]

### CODE_DGT_MODEL — 원 논문/자본/체결 모델 불일치
**확인:** modular grid는 같은 가격간격의 산술 grid다. runner는O-L-H-C 경로와여러 grid crossing을 가정한다. 부족현금은money_input에외부납입으로 추가하고IRR명칭에고정43개월 연환산식을 쓴다.
**우리 작업에서의 의미:** 원 논문 기하 grid, 유한 계좌, 현물재고, 실제 체결 순서와 다른 지점을 먼저 식별해야 한다. 외부납입시점을 반영한 현금흐름 IRR로도 해석할 수 없다.
**한계:** 상수 기간 설정이나 산술 grid 자체가 항상 오류라는 뜻은 아니다. 원 결과 동일성·고정자본 선물 적합성을 입증하지 못했다는 의미다.
근거: [R21], [V2_DGT_RUNNER], [V2_DGT_LOGIC], [V2_DGT_STATIC]

### SOURCE_MODE_SPLIT — 버전/매매 모드 분리
**확인:** 동일 저자도 서로 다른 scalp/trend/setup/플랫폼 문서에서 다른 관리 방식을 설명한다.
**우리 작업에서의 의미:** 원형 하나의 선택/진입/위험/청산을 같은 모드·문서로 결속해야 하며 유리한 문장만 여러 문서에서 합치지 않는다.
**한계:** 어느 버전이 더 수익적인지는 아직 검증하지 않았다.
근거: [V2_RAS_FEB04], [V2_RAS_FAQ], [V2_BB_IV], [V2_BB_ESIGNAL], [R11]

## 3. 성과 숫자의 의미를 수정·보강한 부분
| 대상 | V2에서 사용할 사실 | 과장하면 안 되는 부분 |
|---|---|---|
| Gajjala | 주최자 2023 최종 계좌 +805.1% [V2_GAJJALA_ORGANIZER] | 패턴 한 가지의 수익, 인터뷰의 WR·평균손익을 별도 검증한 것이 아님 |
| SPY Noise-Area | V1의 장기 성과 외 Q24의 2025 Jan–Aug +1.0%, 2016 −12.8%, 2017 −6.9% 병기 [R01] | 특정 부분연도와 장기연환산을 같은 기간처럼 비교하지 않음. 저자보고이지 실계좌감사 아님 |
| DGT | 원 논문의 저자실험값은 보존하되 선택 공개코드에 직접재현 차단요인 존재 [R21, V2_DGT_RUNNER, V2_DGT_LOGIC] | 코드문제를 이유로 논문수치를 무효라고 단정하지도, 그대로 재현됐다고 하지도 않음 |
| Raschke / Bollinger / Shannon | 원 규칙·공식 매뉴얼·사례의 근거 강화 | 해당 개별 모드의 검증된 장기간 PnL·WR·DD가 새로 확보된 것은 아님 |
| Carter / Minervini / Kell / Williams | V1의 기간·자기보고/주최자 구분 유지 | 유명인의 계좌수익을 지표 하나 또는 우리코인모델에 귀속하지 않음 |

## 4. 사례를 실제로 어떻게 비교할 것인지
| 원자료 | 확인된 사례/규칙의 위치 | 대조할 실제 항목 | 아직 시험하지 않은 것 |
|---|---|---|---|
| Raschke March2004 [V2_RAS_MAR04] | printed78 Figure1, 30m SPX / Indicator checklist | 2003-12-18/19 이전 횡보→momentum 고점·ADX→EMA눌림; SMA3/10/16 계산 | 같은 시장 원 가격 전체와 exact fill 재생·원계좌 수익 |
| Raschke February2004 [V2_RAS_FEB04] | printed73 Figure3, 15m euro-futures | 하락 문맥의 higher-low 반등 scalp와 이후 추세복귀의 구분 | 단일 차트로 장기간 기대수익·청산 최적화 |
| Raschke FAQ [V2_RAS_FAQ] | Short Skirt / Anti / Oops / Z-day | 서로 다른 setup의 조건·시간수명·실패논리를 섞지 않음 | 1min ShortSkirt를15m/30m 동일전략으로 확대; stop없는 BB실험의선물적용 |
| Bollinger 2021 TS III [V2_BB_III] | 첫 페이지 About MethodIII | band touch + II alert와 실제 가격확인을 구분 | strong bar의 미공개수치·완전한stop/exit·검증계좌성과 |
| Shannon [V2_SHANNON_CASE] | 페이지 MP4 아래 예시 설명 | 10:38 peak 인식→11:04 AVWAP 재접촉·정체→lower-high 위stop | MP4 전체시청·정확size/exit·fulltradeledger |
| Concretum [R02] | Step3와Step3.8 | 30분 시각 signal→1분 lagged exposure→해당가격변화; 코드조각불일치 | 저자 전체연도 performance reproduction / coin translation |

## 5. 원래 25개 준비상태 — 누락 없이, 과장 없이
| # | 식별자 | 자료 준비상태 | 이번에 사용할 구체 근거 |
|---|---|---|---|
| 1 | `alpha_combo` | 구성요소 검증 선행 | R01, R02, R06 |
| 2 | `anchor_vwap_trend` | 사례·역할 검수 가능 | V2_SHANNON_ESSAY, V2_SHANNON_CASE |
| 3 | `bb_revert` | 사례·역할 검수 가능 | V2_BB_III, V2_RAS_FAQ |
| 4 | `break_and_continue` | 사례·역할 검수 가능 | P04, V2_GAJJALA_ORGANIZER, V2_RAS_FAQ, R04 |
| 5 | `ema_ribbon_scalp` | 사례·역할 검수 가능 | R13, V2_RAS_MAR04, P04 |
| 6 | `fvg_revert` | 핵심 출처 검수 보류 | R24 |
| 7 | `grid_rebalance` | 원 코드 직접사용 보류 | R21, V2_DGT_COMMIT, V2_DGT_RUNNER, V2_DGT_LOGIC |
| 8 | `keltner_trend` | 사례·역할 검수 가능 | R09, V2_RAS_MAR04, V2_RAS_FAQ |
| 9 | `liquidity_sweep` | 정의·데이터 부품 한정 | R23, V2_SHANNON_CASE |
| 10 | `mfi_rsi_div` | 정의·데이터 부품 한정 | R17, R18, V2_BB_II, V2_BB_III |
| 11 | `obv_trend` | 정의·데이터 부품 한정 | R19, P04, V2_BB_II |
| 12 | `pivot_reversal` | 사례·역할 검수 가능 | V2_RAS_FAQ, R13 |
| 13 | `range_fade` | 사례·역할 검수 가능 | V2_RAS_FAQ, V2_BB_III, R11 |
| 14 | `rbreaker_like` | 핵심 출처 검수 보류 | R25, R04 |
| 15 | `rsi_swing_fail` | 정의·데이터 부품 한정 | R17, R06 |
| 16 | `scalp_snap` | 시간축 제약 사례 자료 | V2_RAS_FAQ, V2_RAS_FEB04, P04 |
| 17 | `session_bias` | 알고리즘 대조 자료 | R01, R02, R04 |
| 18 | `squeeze_break` | 사례·역할 검수 가능 | R11, R12, V2_BB_I, V2_BB_IV, V2_RAS_FAQ |
| 19 | `sr_levels` | 사례·역할 검수 가능 | V2_SHANNON_CASE, V2_SHANNON_ESSAY, R11 |
| 20 | `supertrend_pullback` | 정의·데이터 부품 한정 | R20 |
| 21 | `trend_ma_macd` | 사례·역할 검수 가능 | R14, V2_RAS_MAR04, V2_RAS_FAQ |
| 22 | `trend_rider` | 알고리즘 대조 자료 | R01, R02, R14, V2_RAS_MAR04 |
| 23 | `turtle_trend` | 원 규칙 대조 자료 | R07, R08 |
| 24 | `vol_spike_fade` | 사례·역할 검수 가능 | R13, V2_RAS_FEB04, V2_SHANNON_CASE |
| 25 | `vwap_revert` | 사례·역할 검수 가능 | V2_SHANNON_ESSAY, V2_SHANNON_CASE, R01 |

위 분류별 집계: 구성요소 검증 선행 1개 / 사례·역할 검수 가능 12개 / 핵심 출처 검수 보류 2개 / 원 코드 직접사용 보류 1개 / 정의·데이터 부품 한정 5개 / 시간축 제약 사례 자료 1개 / 알고리즘 대조 자료 2개 / 원 규칙 대조 자료 1개.
**분류된 25행 = 검증을 완료한 25개가 아니다.** 원 source 시장/규칙을 확인하는 것, 실제 code/fill 재현, 우리 crypto15m/30m 경제성, 재료 결합 기여는 서로 다른 완료 상태다. MR·Micro 추가 lane을 원래25 처리수에 넣지 않는다.
### 01. `alpha_combo`
**자료 상태:** 구성요소 검증 선행
**직접 대조할 내용:** 원형 한 명이 존재하는 전략이 아니라 자체 합성이다. Noise-Area/R2 등의 원형을 별도 검증한 뒤 구성·상관·합성 기여를 비교한다.
**먼저 공개해야 할 한계:** 구성 전략의 같은 시장·비용 경제성; 조합 권한; 원형이 없는 것을 유명인 조합으로 인증 금지.
**왜 이 자료인가:** 지표 수를 늘리는 것이 아니라 수익 발생 방식이 다른 검증 모델을 재사용할 수 있다.
**원형과 대체 기준 구분:** 독립 원형 없는 자체 합성: 구성 모델을 명시한 새 비교
**근거:** [R01], [R02], [R06]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 02. `anchor_vwap_trend`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** anchor 사건과 실제 인식 시각, 고정 기준선, 재접촉 후 가격반응, 무효화 swing을 사례와 대조한다.
**먼저 공개해야 할 한계:** 완전한 anchor 선정 알고리즘·연속 거래원장·종료 규칙은 여전히 별도 확정 필요. 사례숫자를 보편 threshold로 쓰지 않음.
**왜 이 자료인가:** AVWAP는 임의 rolling 평균과 다른 참여자 평균 원가 문맥을 제공하므로 정의를 먼저 맞춰야 한다.
**원형과 대체 기준 구분:** 원래 AVWAP 방법의 역할 대응
**근거:** [V2_SHANNON_ESSAY], [V2_SHANNON_CASE]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 03. `bb_revert`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** 단순 하단접촉매수를 BB MethodIII alert+price confirmation과 비교. Raschke Z-day Bollinger 모드는 별도 원형으로 구분한다.
**먼저 공개해야 할 한계:** III의 stop/exit와 strong bar의 계량기준 미공개. FAQ의 stop 없는 테스트를 선물에 그대로 넣을 수 없음.
**왜 이 자료인가:** 반전의 문맥을 설명한 저자 규칙과 명확한 통계 모델을 각각 활용할 수 있다.
**원형과 대체 기준 구분:** Bollinger 원칙 검수 + R2 명시적 대체 비교
**근거:** [V2_BB_III], [V2_RAS_FAQ]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 04. `break_and_continue`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** intraday VCP의 종목선정→추진→수축을 case로 검사. Breakout Mode는 반응을 기다리는 방식과 구분. ORB는 별도 알고리즘 대체 비교.
**먼저 공개해야 할 한계:** Gajjala 전체setup별 원장/모든관리규칙 미확보. 미국 stocks-in-play 선정이6코인에서 재현되는지 별도 문제.
**왜 이 자료인가:** Gajjala는 실제 intraday 성과/사례가 있어 일봉VCP를 이름만30m로 바꾸는 것보다 시간축 비교가 명료하다.
**원형과 대체 기준 구분:** Gajjala intraday VCP 원 사례 우선; ORB는 별도 대체 비교
**근거:** [P04], [V2_GAJJALA_ORGANIZER], [V2_RAS_FAQ], [R04]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 05. `ema_ribbon_scalp`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** EMA 정렬만이 아니라 추진/눌림/재개 단계의 원 사례에 연결. Kell Cycle과Raschke Grail은 별개계보.
**먼저 공개해야 할 한계:** Kell 일부 framework 이상의 기계적 전체관리 명세는 미확보. 서로 다른저자 조건을 한 원형이라 하지 않음.
**왜 이 자료인가:** 수익 계좌가 확인되는 Kell의 phase-based 방법은 EMA 정렬만으로 매매하는 기존 문제와 직접 비교할 수 있다.
**원형과 대체 기준 구분:** Kell 가격주기 역할 + Guppy 묶음 문맥
**근거:** [R13], [V2_RAS_MAR04], [P04]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 06. `fvg_revert`
**자료 상태:** 핵심 출처 검수 보류
**직접 대조할 내용:** 정확 FVG/MSS 원 영상은 기존 확보 metadata/목차까지만 확인된 상태다. failed-displacement 대신원형기하·무효화·사례를 확인할 대상으로 남긴다.
**먼저 공개해야 할 한계:** 전체 자막/차트 사례·독립 성과 원장이 미확보. 다른 저자 근거로 FVG 재현완료 또는 수익실패 판정 금지.
**왜 이 자료인가:** 원형을 확인할 직접 자료의 위치가 있으며 다른 저자를 인용한 가짜 FVG 재현을 피할 수 있다.
**원형과 대체 기준 구분:** ICT 원형 정의를 확인할 대상; 성공 모델로 확정하지 않음
**근거:** [R24]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 07. `grid_rebalance`
**자료 상태:** 원 코드 직접사용 보류
**직접 대조할 내용:** 원 논문·실제 modular code 차이와 호출 불일치를 먼저 해결할 검증자료가 확보됐다. spotinventory와boundedreversion을 혼동하지 않는다.
**먼저 공개해야 할 한계:** 공개코드 수선·유한자본/외부납입·OHLC경로·수익률 정의 검증 선행. 15m/30m perp 원형적합성 없음.
**왜 이 자료인가:** 코인 원 데이터와 알고리즘·저자 코드가 있어 무에서 새 grid를 만들 필요가 없다.
**원형과 대체 기준 구분:** 현물 inventory grid 원 연구와 기존 bounded-reversion 분리
**근거:** [R21], [V2_DGT_COMMIT], [V2_DGT_RUNNER], [V2_DGT_LOGIC]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 08. `keltner_trend`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** 일봉뿐 아니라 실제30m SPX Grail: prior consolidation, newmomentum, priorADXqualification, EMApullback을 동일 순서로대조한다.
**먼저 공개해야 할 한계:** 동일저자의 scalp와trend관리혼합금지. 원문 restingentry와현재nextopen의지연, swingrisk, trailing계량화는별도 명세 필요.
**왜 이 자료인가:** 현재 양수 대조군을 보존하면서 원래 의도했던 추세 눌림 매매의 누락/추가를 검증할 수 있다.
**원형과 대체 기준 구분:** Raschke Holy Grail 원형 대응
**근거:** [R09], [V2_RAS_MAR04], [V2_RAS_FAQ]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 09. `liquidity_sweep`
**자료 상태:** 정의·데이터 부품 한정
**직접 대조할 내용:** 가격sweep/retest 사례와 실제OFI를 별도분리. 호가/취소/체결 의미가결속된원자료를 쓰는지 검사한다.
**먼저 공개해야 할 한계:** BBO잔량·순서·공격체결단위/지연·수동호가체결근거 미확인. OFI논문은Rotter매매법/미래15m수익인증 아님.
**왜 이 자료인가:** OFI 원 연구는 필요한 데이터가 무엇인지 명확해 가격패턴에 order-flow라는 이름만 붙이는 것을 막는다.
**원형과 대체 기준 구분:** Rotter 수익 시스템 대신 관측 가능한 order-flow 부품 검증
**근거:** [R23], [V2_SHANNON_CASE]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 10. `mfi_rsi_div`
**자료 상태:** 정의·데이터 부품 한정
**직접 대조할 내용:** 가격pivot과동시점oscillator의실제 divergence를확인하고 MFI확인과IntradayIntensity확인을구분한다.
**먼저 공개해야 할 한계:** MFI trendconfirmation은RSI divergence완성전략이아니다. 복합부품의경제기여/원저자전체매매법 미검증.
**왜 이 자료인가:** 단순 oscillator 방향변화 대신 divergence를 시험해야 해당 재료를 공정하게 평가할 수 있다.
**원형과 대체 기준 구분:** 공식 지표와 동일 가격 pivot의 divergence 검증
**근거:** [R17], [R18], [V2_BB_II], [V2_BB_III]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 11. `obv_trend`
**자료 상태:** 정의·데이터 부품 한정
**직접 대조할 내용:** OBV누적산식과비정상거래량/눌림volume/MFI를별도비교한다. volume이있는것을모든flow지표동등성으로보지않음.
**먼저 공개해야 할 한계:** 계좌실적의OBV단독귀속없음. 추세 확인부품기여검증필요.
**왜 이 자료인가:** 원 계산을 다시 고치는 낭비 대신 참여 확인 부품으로서의 질문을 직접 시험할 수 있다.
**원형과 대체 기준 구분:** OBV 산식 기준 + 성공사례의 거래량 문맥과 분리 비교
**근거:** [R19], [P04], [V2_BB_II]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 12. `pivot_reversal`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** Anti의선행impulse와range/reversal문맥, Oops의전일range안회복을구분한다. 실제swingpivot과session산술pivot혼동금지.
**먼저 공개해야 할 한계:** Oops은Raschke가Williams를설명한출처이지Williams원책의완전위험명세가아님.24/7coin의gap/session차이남음.
**왜 이 자료인가:** pivot 수식을 바꾸는 것보다 실제 거래 상황을 원 인터뷰의 가격구조와 일치시키는 것이 우선이다.
**원형과 대체 기준 구분:** Raschke swing 문맥 / Williams pivot 정의 검토
**근거:** [V2_RAS_FAQ], [R13]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 13. `range_fade`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** Raschke Z-day/아침meanreversion 문맥과 BBIII가격확인을읽고 범위경계·중앙·실패돌파를구분한다.
**먼저 공개해야 할 한계:** 정성적trendday/Z-day판별과cost후전체성과미확보. stop없는원테스트그대로승격금지.
**왜 이 자료인가:** 모든 약세를 같은 반전으로 처리하지 않고 원자료가 구별하는 시장문맥을 비교할 수 있다.
**원형과 대체 기준 구분:** Raschke range 문맥 + Connors 별도 반전 대조
**근거:** [V2_RAS_FAQ], [V2_BB_III], [R11]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 14. `rbreaker_like`
**자료 상태:** 핵심 출처 검수 보류
**직접 대조할 내용:** 공개demo의전일고정level과rollingchannel차이, 수식/코드불일치를확인한상태. ORB는완전별도대체대조다.
**먼저 공개해야 할 한계:** 원R-Breaker권위있는완전규칙/손절/검증성과미확보. 잘못된demo를원형으로확정하지않음.
**왜 이 자료인가:** 직접 공개코드를 확인하면 이름뿐인 R-Breaker와 실제 reference/상태 차이를 검출할 수 있다.
**원형과 대체 기준 구분:** R-Breaker demo 산식/상태 검수; 검증성과 ORB는 다른 비교
**근거:** [R25], [R04]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 15. `rsi_swing_fail`
**자료 상태:** 정의·데이터 부품 한정
**직접 대조할 내용:** RSI14failure-swing과R2를구별. R2는완결된다른규칙의대조군이지현재RSI14원형을완료한증거가아님.
**먼저 공개해야 할 한계:** RSI14정의만으로모든stop/exit가정해지지않음. R2의일봉/stop없음/비용미공개를15mperp에복사금지.
**왜 이 자료인가:** R2에는 거래수·승률·보유기간과 구체적 규칙이 같이 있어 검증 가능한 대체 반전 모델이다.
**원형과 대체 기준 구분:** RSI14 failure-swing 원 정의 + R2 별도 비교
**근거:** [R17], [R06]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 16. `scalp_snap`
**자료 상태:** 시간축 제약 사례 자료
**직접 대조할 내용:** ShortSkirt의impulse→shallowpause→재개이전접근과짧은거래수명을원자료로확인한다.
**먼저 공개해야 할 한계:** 원1minchart/2–10min거래가현재15m/30m결정주기와직접호환되지않음.점수/봉수만확대해같은전략이라하지않음.
**왜 이 자료인가:** 실제 intraday trader의 가격/volume 사례를 써서 OHLC만으로 관측 가능한 부분부터 정직하게 비교할 수 있다.
**원형과 대체 기준 구분:** Gajjala Bull Flag intraday 사례를 가격·참여 모델로 사용
**근거:** [V2_RAS_FAQ], [V2_RAS_FEB04], [P04]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 17. `session_bias`
**자료 상태:** 알고리즘 대조 자료
**직접 대조할 내용:** 시간대별정상변동·상대참여를원algorithm으로비교가능. corrected laggedexposure경로만기준으로읽는다.
**먼저 공개해야 할 한계:** 원NYSE개장/마감/DST·주식universe와coinclock다름. sourceeconomic정답복제/코인성능은미실행.
**왜 이 자료인가:** 단순히 몇 시에는 거래금지가 아니라 원자료가 계량화한 장중 참여·변동의 차이를 이식할 수 있다.
**원형과 대체 기준 구분:** 시계별 noise/participation 원 연구
**근거:** [R01], [R02], [R04]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 18. `squeeze_break`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** Cartercompression중접근/fire이후진입과 BB squeezebreakout은별도모드. 원형즉시진입을보존/대체하는지명확히비교한다.
**먼저 공개해야 할 한계:** Carter모드별체계화/전체계좌실적귀속미확인. BBmanual연속close를또무근거지연child로추가금지.
**왜 이 자료인가:** 기존 지표개요보다 구체적 저자 진입·관리 계획이 공개돼 있어 High2를 발명할 필요가 줄어든다.
**원형과 대체 기준 구분:** Carter 실제 Trading Plan vs 현재 TTM fire 변형
**근거:** [R11], [R12], [V2_BB_I], [V2_BB_IV], [V2_RAS_FAQ]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 19. `sr_levels`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** anchor인식시각/재접촉stall/위험level, box형성/되돌림실패를서로다른원사례로묶어reference검수한다.
**먼저 공개해야 할 한계:** 사례하나로모든수평level생성/stop/exit가정해지지않음.원pricelevel을기존scratch와무조건합치지않음.
**왜 이 자료인가:** 단순한 선 하나가 아니라 진입·실패·목표를 연결하는 공개 규칙을 가져올 수 있다.
**원형과 대체 기준 구분:** Carter Box Trades의 수준/실패/목표 관계 + AVWAP 역할
**근거:** [V2_SHANNON_CASE], [V2_SHANNON_ESSAY], [R11]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 20. `supertrend_pullback`
**자료 상태:** 정의·데이터 부품 한정
**직접 대조할 내용:** 공식ATR밴드·방향·초기화·stop역할을확인한수준. 이미구현된trailing중복개발금지.
**먼저 공개해야 할 한계:** 완성된성공트레이더Supertrend-only규칙과전략별계좌성과미확보. 공개지표정의는부품검수근거.
**왜 이 자료인가:** 최소기술원형을 공식산식으로 고정한 뒤 경제역할을 정확히 시험할 수 있다.
**원형과 대체 기준 구분:** Olivier Seban 계열 공식 구현 및 stop/context 역할
**근거:** [R20]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 21. `trend_ma_macd`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** GMMA문맥과3–10momentum의서로다른역할. Raschkeoscillator는SMA3/10/16이며표준EMA-MACD로대체하면다른계산이다.
**먼저 공개해야 할 한계:** 3–10을추가하면수익개선이라는뜻아님. 실제기존MACD와의중복/기여미측정.
**왜 이 자료인가:** 비슷한 지표를 더하는 대신 각 부품이 독립적 정보를 추가하는지 볼 수 있다.
**원형과 대체 기준 구분:** GMMA 문맥과 MACD모멘텀의 서로 다른 역할
**근거:** [R14], [V2_RAS_MAR04], [V2_RAS_FAQ]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 22. `trend_rider`
**자료 상태:** 알고리즘 대조 자료
**직접 대조할 내용:** 기존GMMA실패보존. NoiseArea는명시적인별도대체benchmark; 입력시각/30min판단/laggedexposure/비용/약한연도까지비교한다.
**먼저 공개해야 할 한계:** 원SPY데이터와모든코드경로재현미실행.1997/2004Grail이나NoiseArea를GMMA원형으로바꾸지않음.
**왜 이 자료인가:** 기존지표조합을 재발명하는 대신 명확한 시간·청산·성과·원코드가 함께 있는 intraday 비교기준을 확보한다.
**원형과 대체 기준 구분:** GMMA 원역할 확인; Noise-Area는 명시적 대체 기준
**근거:** [R01], [R02], [R14], [V2_RAS_MAR04]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 23. `turtle_trend`
**자료 상태:** 원 규칙 대조 자료
**직접 대조할 내용:** 원System1/2·N·가상직전돌파승패·failsafe·추가unit·반대channel청산을통째로대조가능.
**먼저 공개해야 할 한계:** 원다시장일봉성과원장미확보.15m/30m압축은시장/시간변형.현재G4범위의피라미딩권한자동추가없음.
**왜 이 자료인가:** 공개27페이지가 진입부터 크기·청산까지 제공해 단순Donchian조합보다 원형재현공백이작다.
**원형과 대체 기준 구분:** 원 Turtle System1/2 전체 의미 대응
**근거:** [R07], [R08]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 24. `vol_spike_fade`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** 추진의시작과소진/재접촉실패를원사례에서구별하고volspike만으로역매매하지않는다.
**먼저 공개해야 할 한계:** Kell공개framework전체기계명세/개별패턴성과미확보.신규trade수명/exit정의필요.
**왜 이 자료인가:** 강한상승을역매매하는실수를피하려면매매주기상위치와가격반응이필요하다.
**원형과 대체 기준 구분:** Kell exhaustion / Raschke swings / 실제flow의 역할 분리
**근거:** [R13], [V2_RAS_FEB04], [V2_SHANNON_CASE]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

### 25. `vwap_revert`
**자료 상태:** 사례·역할 검수 가능
**직접 대조할 내용:** risingAVWAPtrend와meanreversion기회를분리하고 기준anchor인지rolling평균인지검사한다.
**먼저 공개해야 할 한계:** NoiseAreaVWAPtrend의수익을reversion근거로상속금지.제안역할의경제기여별도필요.
**왜 이 자료인가:** VWAP를쓴다는것보다어떤가격행동에서지속/회귀로해석하는지가현재실패와직접연결된다.
**원형과 대체 기준 구분:** anchor/VWAP의 문맥과 trend/reversion을 분리
**근거:** [V2_SHANNON_ESSAY], [V2_SHANNON_CASE], [R01]
**이번 신규 경제결과:** 미실행. 기존 실패·양수원형·동결상태는 변경하지 않음.

## 6. 충분한 부분 / 충분하지 않은 부분
**충분한 부분:** 위 source 위치와 실제 규칙을 사용해 논리·사례·산식의 대조를 시작하고, 명시적인 공개 알고리즘의 기준 구현을 검수할 자료가 있다. 유효한 기존 증거를 재사용하므로 모든 조사를 처음부터 다시 할 필요가 없다.
**충분하지 않은 부분:** 이 자료만으로25개 모두가 “수익을 낸 원형과 사실상 같은 구현”이라고 인증하거나, 실제 비용 후 독립전략/합성재료로 최종선별할 수는 없다. 특히 핵심 source/실행코드가 막힌 항목은 source readiness부터 구분한다.
**전수 수집과 실무 충분성은 다르다:** 저자 문서가 수십개 더 있다고 무조건 모두 읽는 것을 완료조건으로 삼지 않는다. 기준 모드의 선정/문맥/setup/trigger/위험/무효화/청산/시각/비용/성과 범위가 채워졌는지로 진행한다. 확인 못한 내용은 알고 있는 공백으로 남기고 연구대상 전체에 실패를 일반화하지 않는다.

## 7. 지금 명시적으로 남겨둔 공백
- **FVG/ICT:** 원영상 전문/차트와완전한위험/청산,독립전략성과미확보 → 성공한재현기준으로지정불가;기존자체실험FAIL과분리
- **원R-Breaker:** 권위있는원규칙/위험관리/원성과표미확보 → 서로불일치하는demo직접복사금지
- **Rotter식flow와미시구조:** 개인원거래법/계좌원장,사용자호가단위·순서·실행증거 → 가격기하case와OFI기술부품만분리검수
- **DGT:** 검토한공개코드의호출불일치및paper/자본/체결차이 → 원코드그대로원형재현및perp적용금지
- **정성setup:** Carter/Kell/Gajjala/Shannon등은일부기계조건과연속거래원장미확보 → 원case검수는가능;불명확조건을원형인것처럼발명금지
- **Source market -> crypto15m/30m:** 시장선정·session·체결·risk·holding변경후성과 → 원성과를이식본성과로상속불가
- **전체25경제/재료선별:** 신규원형/이식재생및허용된역할별기여검증 → 이번문서는source연구이며G4완료가아님
Gajjala/Kell/Carter 같은 재량적 원형에서 연속 거래원장이 미공개라는 이유로 모든 유용한 부품연구를 막지 않는다. 다만 그 원장 없이 특정 패턴의 검증된 수익이라고 부르지도 않는다. 원형 충실도 검사와 테스트할 가설을 구분한다.

## 8. Work가 이번 보완을 잘못 해석하지 않도록
- 원 source의 모델/버전/market/timeframe/성과종류를 특정하고 same-method reference를 정한다. 다른모델이비교대상이면 replacement라고 표시한다.
- 선행문맥·선정·setup·trigger·초기위험·무효화·청산/재진입·자본/비용·가용시각 중 빠진 칸을 실행 전에 공개한다. 정성규칙의 기계화는 source-case와 함께 한정한다.
- 핵심미확인이있는항목은known-gap으로남기고가능한원사례/부품검수만진행한다. 모든자료가없다는이유로전체25를멈추거나모든돈버는트레이더의원장확보를필수로발명하지않음.
- 코드가있다는표시대신 실제파일/commit/함수호출/수익산식의간단한검수를통과해야기준구현으로사용한다.
- 원형대응확인과15m/30mtranslation및경제/재료효과는독립상태.이미완료한실험을중복하거나새FULL예산을자동발급하지않음.
이 문서 발급은 새 Work 세션·신규 FULL 예산·유료 구매·서비스 조작·G 승격·주문 권한의 승인이 아니다. 단순 LLM 매매/ML-Light/다른 단계 작업은 끼워 넣지 않는다. 현재 승인 범위 안에서만 조사 결과를 반영한다.

## 9. 자료 인덱스와 확인 범위
URL 수를 품질 점수로 사용하지 않는다. 아래 V2 자료는 이번에 추가 확인한 위치이며, V1 source는 JSON에 보존했다. 전체 copyrighted PDF·페이지 전문·타인 코드 저장소를 재배포하지 않는다.
### [V2_RAS_FEB04] Raschke original interview, Active Trader February 2004
https://lindaraschke.net/wp-content/uploads/2026/01/raschke0204.pdf
확인 범위: 10페이지 본문. PDF index1(printed67)과 index7(printed73)의 원 차트/설명 화면 확인. 15m ECZ03 사례와 scalp/trend 모드 구분.
위치: printed67 scalp management; printed73 Figure3, November3 2003 euro futures15m

### [V2_RAS_MAR04] Raschke original interview part2, Active Trader March 2004
https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf
확인 범위: 4페이지 본문, PDF index2/3 차트·표 화면 확인. 원30m Holy Grail과 지표 산식.
위치: printed78 Figure1 and Indicator checklist; printed79 timeframe progression

### [V2_RAS_FAQ] Raschke official FAQ — strategy-specific modes
https://lindaraschke.net/faq/
확인 범위: Short Skirt, Holy Grail, Anti, Oops, Breakout Mode, timeframes, Bollinger Bands 항목 본문.
위치: FAQ의 각 질문 제목으로 구분. 서로 다른 setup을 단일 원형으로 합치지 않음.

### [V2_SHANNON_ESSAY] Brian Shannon — Anchored VWAP, author essay
https://alphatrends.net/anchored-vwap/
확인 범위: 계산·anchor 인식 시각·상승/하락/중립 문맥 본문. 모든 삽입 차트의 숫자 재현은 하지 않음.
위치: Calculation; Analysis Tool; 11AM low recognition paragraph

### [V2_SHANNON_CASE] Alphatrends — Check out this AVWAP example
https://alphatrends.net/archives/podcast/check-out-this-avwap-example/
확인 범위: 페이지의 10:38 peak→11:04 retest/short/stop 사례 설명 확인. 링크된 MP4 전체를 재생했다고 주장하지 않음.
위치: 영상 바로 아래 두 문단

### [V2_BB_LANDING] Bollinger official TradeStation methods
https://www.bollingerbands.com/tradestation-methods
확인 범위: 저자 매매법 I–IV 소개 및 직접 연결된 매뉴얼.
위치: Methods and support manuals

### [V2_BB_I] Bollinger Method I Breakouts Manual (2021 TradeStation)
https://www.bollingerbands.com/_files/ugd/58be43_f5e967053af44fa083340cacfc5e6226.pdf
확인 범위: 5페이지 텍스트. 매매법 설명·BandWidth·입력 설정 확인. 설치 화면은 수익 근거가 아님.
위치: About Method I; BandWidth; Reversal/Breakout alerts

### [V2_BB_II] Bollinger Method II Trend Following Manual (2021 TradeStation)
https://www.bollingerbands.com/_files/ugd/58be43_b120ddf0184540608baf19e2c0ae2019.pdf
확인 범위: 5페이지 텍스트. 가격 강도와 MFI 확인, 지표 입력. 완전한 수치 entry/exit/stop 원장은 없음.
위치: About Method II; Money Flow Index; %Money Flow

### [V2_BB_III] Bollinger Method III Reversals Manual (2021 TradeStation)
https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf
확인 범위: 5페이지 텍스트. 밴드 tag/Intraday Intensity/추가 price confirmation, alert와 signal 구별.
위치: p1 About Method III; Intraday Intensity

### [V2_BB_IV] Bollinger Method IV Confirmed Breakouts Manual (2021 TradeStation)
https://www.bollingerbands.com/_files/ugd/58be43_d09c50b6e8ea4afd9af0523ef94de876.pdf
확인 범위: 6페이지 텍스트. Squeeze 후 연속 종가와 ADX 문맥. 구체적인 미공개 threshold는 추정하지 않음.
위치: About Method IV; Confirmed Breakouts

### [V2_BB_ESIGNAL] Bollinger official eSignal toolkit — version comparator
https://www.bollingerbands.com/esignal-bbtk
확인 범위: 공식 플랫폼별 Method 설명 비교. eSignal MethodIV와 2021 TradeStation MethodIV를 자동 동일시하지 않음.
위치: Method IV / Confirmed Breakouts description

### [V2_GAJJALA_ORGANIZER] 2023 US Investing Championship final standings
https://financial-competitions.com/previousstandings/2024/1/23/december-standings-2023
확인 범위: 2023-12-31 기준 주최자 최종 순위 직접 확인.
위치: $20,000+ Accounts / Stock Division / Goverdhan Gajjala +805.1%

### [V2_DGT_COMMIT] DGT public repository commit
https://github.com/colachenkc/Dynamic-Grid-Trading/commit/1cbfed11f398e797a6aeebe6cade0f0970f2096c
확인 범위: 선택 파일의 고정 버전: 2025-12-12 commit. 실행 아님.
commit: `1cbfed11f398e797a6aeebe6cade0f0970f2096c`

### [V2_DGT_RUNNER] DGT actual modular runner
https://github.com/colachenkc/Dynamic-Grid-Trading/blob/1cbfed11f398e797a6aeebe6cade0f0970f2096c/src/dgt_backtest.py
확인 범위: 전체 runner 정적 검토. 호출 인자·OHLC 경로·grid crossing·수익률 산식 확인. 시장데이터 실행 없음.
Git blob SHA: `7fd83b9348e0d23b5305a942b473a286e1f3d308` (로컬파일 SHA256과 다름)

### [V2_DGT_LOGIC] DGT grid and cash/inventory functions
https://github.com/colachenkc/Dynamic-Grid-Trading/blob/1cbfed11f398e797a6aeebe6cade0f0970f2096c/src/grid_logic.py
확인 범위: 전체 파일 정적 검토. 함수 정의와 호출의 불일치, 산술 grid, 부족현금 외부보충 확인.
Git blob SHA: `96d3f6761fc8da3f4396a93d2208957810eb4c8c` (로컬파일 SHA256과 다름)

### [V2_DGT_STATIC] DGT repository static-grid comparator
https://github.com/colachenkc/Dynamic-Grid-Trading/blob/1cbfed11f398e797a6aeebe6cade0f0970f2096c/grid_trading.py
확인 범위: 전체 파일 정적 검토. 기하 grid를 쓰는 별도의 static 실험이며 modular DGT와 같지 않음.
Git blob SHA: `ae215eb491e5b6a63ce09638c4f03e3faeff33a8` (로컬파일 SHA256과 다름)

### [V2_DAVEY_SCREEN] Kevin Davey official site — screened lead, not acquired rule pack
https://kjtradingsystems.com/
확인 범위: 공개 페이지·성과 주장과 전략 제공 안내 확인. 전체 거래 규칙/코드/계좌 원장 미확보.
위치: 개별 전략 실적을 검증된 계좌수익으로 사용하지 않음

### [V2_UNGER_SCREEN] Andrea Unger original interview — competition risk context
https://bettersystemtrader.com/016-andrea-unger/
확인 범위: 원 인터뷰의 대회/평시 위험 구분. 이 인터뷰만으로 재현 가능한 전체 전략을 확보한 것은 아님.
위치: competition leverage/risk and drawdown discussion

[R01] SPY Intraday Momentum — 원 논문 — https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf
V2: 중심 성과표뿐 아니라 2025-09-22 개정본 FAQ/후반부 재검토. Q24 표의 2025 Jan–Aug +1.0%, 2016−12.8%, 2017−6.9% 확인. 저자 보고 모델 성과이지 계좌인증 아님. Q11 turnkey 전략 아님/자기매매 수정본 구분.
[R02] SPY 원 저자 MATLAB 구현 — https://concretumgroup.com/backtesting-riding-intraday-trends-in-us-markets-using-matlab/
V2: Step3 본문은 lagged exposure로 PnL. Step3.8 설명 예제는 signal로 PnL을 계산해 같은 페이지에서 불일치. 예제를 그대로 이어 붙이지 않음. 원 논문 전체 수익이 거짓이라는 결론은 아님.
[R04] Stocks in Play ORB — 원 논문 — https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf
V2: 종목선정과 5m/15m/30m 성과 차이 유지. 원 연구의 주식 universe·주당비용과 코인15m/30m 이식을 분리.
[P04] Gajjala — TraderLion 인터뷰 정리 — https://traderlion.com/investing-champions/2023-us-investing-champion/
V2: 인터뷰 요약의 750T·WR31%·평균이익8.55%/평균손실4.06%는 주최자 계좌805.1%와 검증 수준이 다름. 포지션 크기/분모/집계 방식 미확인으로 같은 계좌 원장을 복원하지 않음.
[R21] Dynamic Grid Trading 원 논문 — https://arxiv.org/html/2506.11921v1
[R22] Dynamic Grid Trading 저자 코드 — https://github.com/colachenkc/Dynamic-Grid-Trading
V2: README 확인 단계를 넘어 실제 modular runner/grid_logic/static comparator를 읽음. 아래 CODE_DGT_* 문제 발견. src/backtest.py가 아닌 src/dgt_backtest.py 존재.
[R24] ICT 2022 Mentorship Episode6 원 영상 — https://www.youtube.com/watch?v=Bkt8B3kLATQ
[R25] FMZ R-Breaker 공개 구현 — https://www.fmz.com/digest-topic/5707
[R11] John Carter 공식 Trading Plan — https://www.simplertrading.com/trading-plan
[R12] John Carter 공식 프로필·계획 — https://www.simplertrading.com/traders/john-carter/
[R06] Larry Connors Improved R2 원문 — https://tradingmarkets.com/recent/the_improved_r2_strategy_84_correct_with_just_6_rules_-674361
[R07] Original Turtle Rules 안내 — https://www.tradingblox.com/originalturtles/originalturtlerules.htm
[R08] Original Turtle Rules 전문 — https://www.tradingblox.com/originalturtles/originalturtlerules.pdf
[R09] Linda Raschke Holy Grail 원 인터뷰 — https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf
[R13] Oliver Kell 공식 Cycle of Price Action — https://kelltrading.com/
[R14] Daryl Guppy 공식 GMMA — https://www.guppytraders.com/gmma-info
[R17] Fidelity RSI 정의 — https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI
[R18] Fidelity MFI 정의 — https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/mfi
[R19] Fidelity OBV 정의 — https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/obv
[R20] TradingView Supertrend — https://www.tradingview.com/support/solutions/43000634738-supertrend/
[R23] Cont–Kukanov–Stoikov Order Book Events — https://arxiv.org/abs/1011.6402

## 10. 검토 증거의 한계와 실행 기록
이번 결과는 files로 원 조사파일을 읽고, web으로 원문/PDF이미지를 확인하고, GitHub connector로 공개코드를 정적으로 대조한 것이다. 선택 DGT 함수의 불일치는 실제 원코드에 근거하지만 해당 저장소를 데이터와 함께 실행한 결과는 아니다. 외부코드 전체감사/실수익재현을 완료했다는 표시는 없다.
모든 source URL은 조회 시점 자료다. 웹페이지의 raw byte는 로컬보관하지 않았으며 raw source SHA256을 만들지 않았다. GitHub 파일은 위 commit/blob 식별자를 사용한다. 아래 패키지 manifest의 SHA256은 우리의 결과파일을 보호하는 값이지 원문 사실의 진실성을 증명하는 값이 아니다.
신규 경제실행0회 / 사용자저장소변경0건 / 서비스변경0건 / 새Work시작없음 / 유료자료구매없음. 기존 V1의 Firecrawl 사용량은 이전turn 기록으로만 보존한다.

**최종 결론:** V1을 무조건 충분하다고 승인하지 않았다. 실제로 더 직접적인 사례·매뉴얼을 확보했고, 공개 코드·성과 해석의 차단요인을 찾아 수정했다. V2는 일부 기준 구현과 전25 항목의 공백을 확인하는 데 쓰는 자료이며, 모든 전략의 재현·경제성 완료를 대신하지 않는다.
