# ZEL 병렬 벤치마킹 — 2026-10-17 최초 수집

## 실제 범위와 경계

사용자 최신 지시: 경제실행이 막혀 있더라도 정보수집·벤치마킹을 별도로 병렬 수행한다. 이 문서는 그 지시에 따른 **정보수집 결과**이며 새 경제실험 승인, 자동 후보 승격, 실행 연결 복구 또는 수익 개선이 아니다.

- 경제 담당자는 기존 CLOUD_WORK_COORDINATOR_ISSUE1358_V1 그대로다. OWNER/CHECKPOINT/실험 소비원장은 수정하지 않았다.
- 대조한 저장소 기준: c9ad2bdee6c607660a05494fad9acdf4e2351ad2.
- 원형 코드: backend/research/rebuild/scalp7_positive_lanes_v2.py, Git blob 79b9934b471cbe0f4342b265c90b2c9c8884f52c.
- 현재 실패 구성 근거: research/campaigns/scalp7_20261013/dual_streak_v1/RESULT_AND_NEXT.json, Git blob 1e6a357351fae427a36731167b2d4be4aedac3d4. 이 파일의 옛 CI-pending 탐색 지시는 현행 승인/병합 상태로 사용하지 않는다.
- 현재 두 승인 후속안: fresh-touch-after-reject / trend-signal-low-invalidation. 아래 자료는 해당 실험을 대체하거나 예산을 늘리지 않는다.
- 시장 API·유료 모델 API·새 경제 replay·Paper/Live/주문·배포: 이번 수집에서 0회.
- 외부 수익률/승률 광고는 검증한 거래원장 없이 실적으로 인용하지 않는다. 외부 수치·시간봉·손절 비중은 ZEL 임계치로 복사하지 않는다.

## 네 수집 축

| 축 | 수집 질문 | 실제 초기 산출물 |
|---|---|---|
| Keltner/HG | 추세 형성, 눌림, 반전, 실패 후 재시도가 어떻게 구분되는가? | S01/S02와 현재 상태기계 비교, H02 |
| Squeeze | 압축 해제 이후 모멘텀 약화·반전·정상 되돌림을 어떻게 구분하는가? | S03/S04/S05와 청산 조건 비교, H01 |
| 청산·큰 승리 보존 | 조기청산이 줄인 손실보다 놓친 승리를 키우는가? | S06/S07/S13 반대 증거, H03 |
| 차트·다중시간봉·공개 구현 | 상위봉 맥락, 캔들/피보나치 확정 시각, 점유·거절 기록은 어떻게 연결되는가? | S08–S12, 영상 접수 V01–V04 |

주제별 분리 조사와 묶음 웹 검색을 수행했다. 네 개의 별도 실행 에이전트나 경제 Job을 시작했다는 뜻은 아니다.

## 읽은 1차 자료 13건 — 관련 본문/도표 확인 범위

### S01 — Raschke, AIQ Opening Bell, August 1997
URL: https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf
확인: 인쇄 p.2 규칙 상자, p.4 실패 사례; 웹 PDF 원문과 해당 페이지 이미지 대조.
원문 사실: 먼저 ADX가 높고 상승한 상태를 찾고, 이어지는 EMA20 눌림에서는 ADX 하락이 동반될 수 있다고 설명한다. 접촉 이후 이전 봉 고점 위 buy-stop, 체결 후 새 swing low 보호손절을 구분한다. 시장은 강한데 해당 종목의 후속 움직임이 없는 실패 사례도 제시한다.
한계: 1997년 주식/선물 교육 인터뷰. 현재 BingX 수익성이나 정식 자동화 성과 원장 아님. 현재 ZEL의 종가 반전/다음시가 체결과 원문 buy-stop은 서로 다른 체결 의미다.
사용: H02의 단계 구분, H03의 상대적 후속 움직임 질문. ADX 임계값 변경이나 새 stop-order 모델을 이 문서만으로 도입하지 않는다.

### S02 — Raschke, The rituals of trading, Active Trader, August 2000
URL: https://lindaraschke.net/wp-content/uploads/2026/01/rituals.pdf
확인: 인쇄 p.58–60의 실패한 HG, 시장상태, 보유관리 문단; p.58 이미지 대조.
원문 사실: HG 매수 전제가 깨진 뒤 같은 시장의 눌림 매수를 계속 찾지 않는 접근을 설명한다. 자동 stop-and-reverse를 한다고 말하지 않는다. 추세와 횡보에서 진입 위치·체결 방식의 중요성이 다르며, 보유 중 이어지는 가격 구조를 관찰한다.
한계: 재량 설명에 정확한 모든 재무장 조건/시간 임계치가 있지는 않다. 실패 뒤 즉시 숏으로 전환하는 규칙으로 번역하지 않는다.
사용: 새 접촉이 생겨도 추세 전제가 회복되지 않은 경우의 반례 수집. 현재 fresh-touch와 기전상 중복 가능성이 있어 별도 신규 후보로 세지 않는다.

### S03 — John Carter, Trading Plan
URL: https://www.simplertrading.com/trading-plan
확인: Entry Rules, risk/exit 문단, Execution Methods의 Box Trades 및 진입 전 거래유형 고정 문단.
원문 사실: 상위 일봉 이동평균 정렬과 Squeeze를 함께 본다. 정상 변동과 진입 전제 붕괴를 구별한다. 별도의 Box Trades 사례에서는 박스 안으로 종가가 돌아오는 것을 청산 신호로 설명한다.
한계: 이 Box 규칙은 현재 Squeeze 신호봉 저가 규칙의 원문 증명이 아니다. 박스 경계 산출법도 완전히 정식화돼 있지 않다. 공개 수익 목표·계좌위험 비중을 ZEL에 이식하지 않는다.
사용: 상위봉 맥락과 하위봉 진입/청산을 구분하는 벤치마크. 기존에 읽은 Carter 자료는 재사용으로 표시하며 신규 수익기전으로 중복 계산하지 않는다.

### S04 — Simpler Trading, How to Trade the TTM Squeeze Indicator
URL: https://www.simplertrading.com/trading-education/tutorials/squeeze-indicator
확인: indicator overview, momentum, first release, time-frame 설명 본문. 연결 영상 자체의 전편 시청은 아님.
원문 사실: 압축 점은 방향 자체를 결정하지 않는다. 모멘텀의 부호와 기울기를 별도로 설명하며, 0선으로 돌아오는 움직임은 정지/반전 가능성으로 취급한다.
한계: 8–10봉 지속 등 제작자 일반 설명은 통계 표본/원장 없는 주장이다. 현재 11봉 보유를 해당 설명에 맞춰 조정하지 않는다.
사용: H01의 부호 전환 진단. 음수 전환 즉시 청산의 수익성은 원문에서 입증하지 않는다.

### S05 — Schwab thinkorswim, TTM_Squeeze
URL: https://toslc.thinkorswim.com/center/reference/Tech-Indicators/studies-library/T-U/TTM-Squeeze
확인: Description / oscillator color / input parameters.
원문 사실: 압축 표시와 모멘텀 표시를 나눠 설명하고, 색상 변화에 따른 신호 유효성 설명을 제공한다.
한계: 플랫폼 표시 설명이며 ZEL의 수치 모멘텀·음수 전환·청산 규칙과 일대일 동일성을 입증하지 않는다.
사용: 기존 RESULT_AND_NEXT에 이미 있던 출처 재확인. 신규 발견 수에 포함해 성과를 부풀리지 않는다.

### S06 — Andrea Unger, Trailing stop, sì o no? 제작자 영상 대본
URL: https://ungeracademy.com/it/blog/trailing-stop-si-o-no
확인: 제작자가 공개한 Trascrizione 전체 핵심 문단. 정확한 초단위 timecode는 미확보.
원문 사실: 본인의 단기 시스템 시험에서는 trailing stop이 성과를 개선하지 않았다고 보고하고, 장기 추세추종과 구별한다. 일부 플랫폼의 봉 내부 처리 때문에 실현 불가능한 양수 backtest가 나올 위험도 설명한다.
한계: 모든 시장에 적용되는 정리나 독립 감사 성과가 아니다. ZEL 기존 trailing을 삭제할 근거로 쓰지 않는다.
사용: 조기청산의 회복 승리 훼손과 봉 내부 선후관계 반례. 손실 사례뿐 아니라 개선이 실패한 사례도 보존한다.

### S07 — John Bollinger, Bollinger Bands Rules
URL: https://www.bollingerbands.com/bollinger-band-rules
확인: rules 4, 6–8, 14, 19–22.
원문 사실: 밴드 접촉만을 매매신호로 삼지 않고, 추세 중 밴드를 따라가는 움직임과 반전을 구분한다. 같은 계열 모멘텀 지표를 여러 개 더하는 것을 독립 정보로 취급하지 않는다.
한계: 공개 교육 규칙이지 암호화폐 표본에서의 비용 후 우위가 아니다.
사용: Squeeze의 정상 확장/실패 구분과 중복 지표 필터 추가의 반증 자료.

### S08 — CME, Fibonacci Retracements and Extensions
URL: https://www.cmegroup.com/education/courses/technical-analysis/fibonacci-retracements-and-extensions
확인: prior-high/low 기준과 retracement/extension 설명.
원문 사실: 이전 움직임의 고저점과 거리에서 되돌림·확장 구간을 계산한다. 구간은 관찰 대상이지 확정적인 지지/저항이 아니다.
한계: 어떤 과거 swing을 언제 확정할지에 대한 완전한 기계식 규칙과 비용 후 수익 원장은 없다. 영문 본문에는 61.8과 62.8 표기가 혼재한다. 이를 임의 수정해 원문의 확정 임계치라고 만들지 않는다.
사용: fib_anchor_ts / anchor_confirmed_at / subsequent_repainting을 추적하는 벤치마크. 미래 pivot을 과거 시점에 제공하는 구현은 제외.

### S09 — Steve Nison Candlecharts, Candlestick Patterns
URL: https://candlecharts.com/candlestick-patterns/
확인: Hammer / Hanging Man 본문.
원문 사실: 유사한 캔들 모양도 선행 추세에 따라 이름과 해석이 달라지고, Hanging Man에는 뒤따르는 확인을 설명한다.
한계: 패턴 사전 자체에 ZEL용 자동 추세정의·진입/청산 lifecycle·비용 검증이 있는 것은 아니다.
사용: 캔들 모양 단독 필터 대신 관측 당시 추세·위치·확인시각을 함께 접수. 이미 실패한 Inverted Hammer나 1봉 지연 확인을 이름만 바꿔 재등록하지 않는다.

### S10 — Freqtrade, Advanced Backtesting Analysis
URL: https://www.freqtrade.io/en/stable/advanced-backtesting/
확인: 신호 시점 지표, enter/exit tags, rejected-signals, CSV export.
원문 사실: 신호·체결 및 진입/청산 이유를 분해한 분석을 지원한다.
한계: 이 도구가 전략의 수익을 만들어주는 것은 아니며 stable 페이지의 CLI 예시가 모든 과거 설치 버전과 같다고 가정하지 않는다. 코드 사용 시 고정 버전 재확인.
사용: 기존 엔진의 같은 질문을 위한 출력 설계 참고. 새로운 플랫폼 이주/설치 없음. 이미 연구한 기능은 재사용.

### S11 — Freqtrade, Backtesting
URL: https://www.freqtrade.io/en/stable/backtesting/
확인: Improved backtest accuracy / timeframe-detail / occupancy 설명.
원문 사실: 하위 시간봉은 봉 내부 체결 가정을 더 세밀하게 만들고, 조기 해제된 포지션 슬롯 때문에 후속 거래도 달라질 수 있다. 원천 세부봉이 필요하다.
한계: 세부봉 검증이 실제 bid/ask·체결큐를 복구하는 것은 아니다. 콜백 평가 주기 변경은 전략 의미도 바꿀 수 있어 무단 적용하지 않는다.
사용: 조기청산 효과를 기존 거래들의 exit 가격만 바꾸는 방식으로 계산하지 않는 벤치마크.

### S12 — Freqtrade, Strategy Customization
URL: https://www.freqtrade.io/en/stable/strategy-customization/
확인: informative pairs / merge_informative_pair / colliding signals.
원문 사실: 상위 시간봉 정보를 미래 누출 없이 결합하는 helper와 충돌 신호 처리를 설명한다.
한계: 공개 예제 전략은 수익 인증이 아니다. 현재 완료되지 않은 상위봉 값을 lower-TF에 미리 쓰면 안 된다.
사용: 다중시간봉 자료원의 closed/available 시각 명시. 새 거래 시간봉이나 1d 전략 승인을 의미하지 않는다.

### S13 — Kaminski & Lo, When do stop-loss rules stop losses?
URL: https://dspace.mit.edu/entities/publication/bb69ca4b-0cdc-487f-831d-63b2e84fafee
DOI: 10.1016/j.finmar.2013.07.001
확인 범위: MIT 원저자 저장소의 초록과 서지 정보만. 논문 전체 정리·표 수치를 검토했다고 주장하지 않는다.
초록 사실: 누적손실 뒤 노출을 줄이는 정책이 기대수익과 변동성에 주는 영향을 분석하며, 특정 조건/표본에서는 유용할 수 있다고 보고한다.
한계: 일별 지수선물 포트폴리오 stop 정책과 30분봉 개별 거래 청산은 다른 문제다.
사용: 다음 원문 회차의 반대증거/적용한계 조사. 현재 전략의 손절 확대·축소나 레버리지 변경 없음.

## 우선 검증 질문 3개 — 모두 가설 / [UNSURE] / 경제판정 미실행

### H01 — Squeeze 음수 모멘텀 전환의 청산 공백 여부
분류: CODE_OBSERVATION_PLUS_SOURCE_MOTIVATED_HYPOTHESIS.
코드 사실: exit_update는 `momenta[2] > 0`, `momenta[1] > 0`, `momenta[2] < momenta[1] < momenta[0]`를 요구한다. 따라서 급격한 음수 전환은 이 특정 청산 가지에서 발동하지 않는다. 별도 stop/max-hold/승인된 signal-low exit는 여전히 적용될 수 있다.
논리 확인: 인공 값 [3,2,1]에서는 참, [3,1,-1]과 [1,-1,-2]에서는 거짓. 단순 조건식 계산이며 전체 엔진 시험·실제 가격 결과가 아니다.
가설: 추가 추세 거래 일부가 '양수 모멘텀 약화' 단계를 건너뛰어 방향 전환 후에도 늦게 청산될 수 있다.
필요자료: 저장 추가 32거래 및 PANIC 대조군의 진입~원청산 확정봉 OHLC, 동일 함수로 계산한 momentum, entry/asof clock, stop 및 max-hold trace.
먼저 할 분석: 원청산보다 앞선 최초 음수 전환을 전체 거래에서 집계하고, 원래 손실과 이후 회복 승리로 나눠 관측한다. 손실 거래만 선택하지 않는다. pending signal-low 후속안과 실제 발동 겹침도 비교한다.
반증: 이전에 stop/원청산이 이미 발동하거나, 해당 전환이 손실을 구분하지 못하거나, 회복 승리 훼손이 절감손실을 넘으면 이 가설의 개선 근거 부족.
후속 변경: 기존 두 승인 경제비교 결과를 받은 뒤 기존 owner가 신규 축/예산/중복 여부를 판정한다. 이 자료수집으로 새 FULL을 승인하지 않는다.

### H02 — Keltner의 추세 형성·눌림·반전 단계 의미 비교
분류: SOURCE_TRANSLATION_DIAGNOSTIC_NOT_A_BUG_VERDICT.
원문 S01은 최초 높은 상승 ADX와 이후 눌림 중 ADX 하락을 구분한다. 현재 _hg_event의 strong 검사에는 매 봉 ADX>=30 및 EMA20 기울기 방향이 들어가고, ADX 상승 여부는 직접 검사하지 않는다.
가설: 최초의 강한 추세 증거와 눌림 중 정상적인 둔화를 같은 시점 조건으로 취급해 정상 기회를 놓치거나, 오래된 추세의 늦은 시도를 받아들일 수 있다.
필요자료: 현재 HG episode별 first-strong/touch/turn/accepted/rejected 시각, 각 시점 ADX 값·차분·EMA20 기울기, native reset 원인. 숫자 25/30은 원형 그대로 관측만 한다.
먼저 할 분석: 원형, 기각된 accepted-episode, pending fresh-touch의 해당 시점 trace를 비교한다. 원저자의 stop-entry와 ZEL 종가확인 차이는 별도 축으로 분리한다.
반증: 단계 차이가 실제 허용기회/손실과 연결되지 않거나, 놓친 기회를 열 때 비용 후 추가손실이 늘면 신규 수정 근거 부족.
중복: 기존 fresh-touch 재무장과 부분 중복 가능. 지금 새 후보로 만들거나 ADX 수치를 조정하지 않는다.

### H03 — 실패 후속 움직임과 정상 되돌림의 상대적 차이
분류: OBSERVATIONAL_QUESTION_RULE_NOT_YET_COMPLETE.
원문 S01의 실패 예시는 전체 시장이 강한데 해당 종목의 반응이 약한 상황이다. S03/S06/S07은 정상 변동까지 잘라내는 청산을 경계할 비교 근거다.
가설: 같은 시점 BTC/시장과 비교한 종목의 후속 움직임이 Keltner 저MFE 청산 및 Squeeze 추가 거래의 실패/회복 승리를 구분할 정보를 줄 수 있다.
필요자료: 진입 이후 현재까지의 종목·BTC 수익률, 같은 timestamp/segment, 기존 의사결정 시점의 가격구조. BTC 자체는 자기 자신과 비교하지 않고 별도 분리한다.
먼저 할 분석: 이미 고정된 기존 판단 시점에서만 상대진행도를 관측하고, 동일시각 동시손실과 진입 전 수익기회 부족을 분리한다. 사후에 잘 된 종목/월을 선택하지 않는다.
반증: 정상 큰 승리에서도 같은 상대약세가 나타나거나, 절대모멘텀의 중복 정보이면 탈락.
현재 결손: benchmark 정의·정식 실행 규칙·재무장 조건 미동결. 즉시 실행 READY 아님.

## 영상 접수 — 시청/자막/조회수 수준을 분리

| ID | 자료 | 확인 수준 | 남은 것 |
|---|---|---|---|
| V01 | Andrea Unger, Trailing stop, sì o no? / S06 | 제작자 공개 대본 확보·검토 | 현재 조회수/초단위 타임코드 미확인 |
| V02 | Linda Raschke, Short Term Scalping Patterns with Candlesticks / https://www.youtube.com/watch?v=kv2H152ISdM | 본인 사이트 https://lindaraschke.net/linda-videos/ 에서 제목 확인 | 직접 영상 페이지 읽기 실패, 대본·현재 조회수 미확인 |
| V03 | TraderLion, The Reality of Relative Strength Based Trading with Linda Raschke / https://www.youtube.com/watch?v=jD4nynuWfEU | 본인 사이트와 YouTube 제목 확인 | 페이지 본문이 일반 footer만 반환, 대본·현재 조회수 미확인 |
| V04 | Simpler Trading, How to Trade the TTM Squeeze Setup / https://www.youtube.com/watch?v=3NeBgVbdQtI | S04 제작자 페이지의 연결 확인 | 영상 본문 읽기 실패, 대본·현재 조회수 미확인 |

3차 요약 사이트의 조회수는 현재 YouTube 검증값으로 채택하지 않았다. 로그인·유료 API·차단 우회 없이 제작자 공개 대본을 우선 사용한다. 영상 한 건의 자막 결손이 문서·논문 수집을 막지 않는다.

## 중복과 실패 보존

- 기존 자료에서 확인한 실패축: ATR/비용 필터 재튜닝, 1봉 지속확인, 이미 기각된 regime-overlay 단독, accepted-episode 단독, 반복된 같은 손실 청산 수선. 신규 source라는 이유만으로 실패축을 재시험하지 않는다.
- 기존 RESULT_AND_NEXT의 Freqtrade callbacks / Schwab TTM / Raschke 124 인터뷰와 신규 자료의 동일 내용은 재사용으로 취급한다.
- 이번 중복검사는 제공 프로젝트 기록과 위 고정 파일 기준이다. 저장소 전체 semantic embedding cosine 검사를 수행했다고 주장하지 않는다. 신규 후보 동결 전에는 기존 총괄 원장과 추가 중복검사가 필요하다.
- 원문 주장, 현재 코드 관측, 새 가설, 실제 경제판정을 서로 다른 열/상태로 유지한다.

## 다음 회차: 수집이 경제개발을 막지 않게 한다

1. 기존 #1414 자료와 이 문서를 먼저 읽고 같은 내용의 재요약을 피한다.
2. 네 축을 나눠 부족한 원문·반대 사례·완전한 체결/청산 규칙만 보충한다. 매회 무조건 소스 수를 늘리지 않는다.
3. 경제실행 연결과 무관하게 공개 웹/제작자 대본/논문/공식 구현 수집은 계속한다. 정보수집자는 경제 claim을 취득하지 않는다.
4. 단일 경제 owner에는 URL 나열 대신 '원인 질문 → 당시 관측값 → 변경 한 축 → 회복 승리 반례 → 필요한 비교'만 넘긴다.
5. 인증 실행이 복구되면 준비된 두 후속안의 기존 승인 비교가 우선이다. 신규 수집 가설 때문에 이를 다시 대기시키지 않는다.
6. 새로운 유료 모델/API, 구독, 서버, 연구 플랫폼 설치는 하지 않는다. 정보수집 완료를 매매 수익 개선으로 보고하지 않는다.

이번 경제 상태: 새로운 실데이터 평가 0회, 수익 개선 미측정, 실주문 hold. 이 연구 브랜치에는 원문 요약과 인계 자료만 저장한다.
