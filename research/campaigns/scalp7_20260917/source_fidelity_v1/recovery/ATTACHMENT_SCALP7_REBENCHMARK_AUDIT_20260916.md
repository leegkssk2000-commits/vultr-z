# Scalp7 재벤치마킹 대조 보고서

검토일: 2026-09-16
저장소: leegkssk2000-commits/vultr-z
검토 기준: 2f7ad51aadb6faa12430596e515d2117cfe096ff (PR #1339 병합본)
범위: Keltner/Holy-Grail, Trend Rider, Break, Supertrend, Squeeze의 5개 주력 계열 + MR, Micro = 7개 연구 대상. 의사결정 TF는 15m/30m. 승격된 Core 7개라는 뜻이 아니다.

## 검토의 성격
이번 작업은 원자료와 현재 구현의 대조다. 신규 경제 실행, 파라미터 튜닝, 등급 변경, 서비스 재시작, 주문, live 활성화는 하지 않았다. 아래 개선 방향은 검증할 가설이며 신규 성과가 아니다. PR #1338/#1339의 기존 원장과 부정 결과를 유지한다. 과거 결과의 동일성은 이름이 아니라 code/rule/data/cost/window/execution identity로 확인한다.

## 1. Keltner/Holy-Grail 30m
- 원자료: Linda Bradford Raschke 인터뷰, AIQ Opening Bell, August 1997, 인쇄 2쪽의 Holy Grail 규칙. 저자 사이트에 보존된 원문과 사례 차트를 확인했다.
- 출처: https://lindaraschke.net/wp-content/uploads/2026/01/august1997.pdf
- 코드: backend/research/rebuild/scalp7_positive_lanes_v2.py / _hg_event, generate_signals, entry_admission, exit_update.
- 확인된 차이: 초기 ADX 상승은 검사하지 않으며, 되돌림/재개 관찰에도 매번 ADX>=30을 요구한다. ADX 25~30이면 관찰 진행을 건너뛰고 25 미만이면 상태를 지운다. 원문의 초기 추세 확인과 이후 되돌림을 하나의 동시 조건으로 취급하지 않아야 한다.
- 별도 차이: 현재 진입은 이전 고가와 EMA20 위 종가 확인 후 다음 시가다. 원문의 조건부 stop 진입과 다르다. GMMA 정렬, PANIC/TREND_DISPERSED, ATR/cost4.5 및 고정 BE/partial/runner는 현재 자체 설계 요소다.
- 첫 검증축: 기존 incumbent의 나머지 조건을 유지하고, 초기 impulse 자격과 후속 pullback 상태의 시간적 연결만 별도 child로 비교한다. 무효화/만료 해석은 별도 명세로 고정한다.
- 다음 검증축: 조건부 stop과 종가확인 진입의 차이는 따로 비교한다. 1분 원천에서 실제 선후관계를 확인하며 미관측 체결을 만들지 않는다.
- 필요한 기여분해: ADX 상태 때문에 누락된 touch/reclaim, 추가/제외 거래, 진입 지연, 기존 winner 보존, 비용 후 성과. 이를 산출하기 전에는 차이의 경제 효과를 확정하지 않는다.

## 2. Trend Rider 15m
- 원자료: Daryl Guppy 공식 GMMA 설명.
- 출처: https://www.guppytraders.com/gmma-info
- 코드: backend/research/rebuild/scalp7_rider_architecture_v2.py / generate_signals, exit_update.
- 확인된 차이: 현재 신호는 직전 4봉 범위 돌파 → 반대 방향 눌림 → 종가 재돌파다. 신호 생성부에 GMMA 두 묶음, 장기 묶음 안정성, 묶음 간 확산/압축 상태가 없다. 현재 구현을 GMMA 재현이라고 부를 수 없다.
- 첫 검증축: 고정된 15m trigger/exit를 보존하고, 완료된 30m GMMA 문맥을 독립적인 상태 부품으로 연결한다. 단순 이동평균 교차나 이미 기각한 ADX 필터 반복으로 대체하지 않는다.
- 가설: 장기 추세가 유지되는 단기 눌림과 양쪽 묶음이 함께 붕괴하는 상태를 분리하면 불필요한 재진입 비용을 줄일 수 있다. 유효 거래 빈도까지 늘어난다는 보장은 없다.
- 필요한 기여분해: 신호부터 체결까지 조건별 누락 수, 동일 trend episode 재진입 수, gross/T와 cost/T, 손상 winner, raw loss cluster. 문맥 수선과 반복진입 소유권 수선을 한 실험에서 섞지 않는다.

## 3. Break 15m
- 원자료: Brooks의 breakout pullback/test 정의; Crabel의 공개 ORB 연구는 별도 비교 기준이다.
- 출처: https://www.brookstradingcourse.com/price-action-trading-terms-glossary/
- 출처: https://tobycrabel.substack.com/p/opening-range-breakout-a-century
- 코드: backend/research/rebuild/scalp7_break_architecture_v2.py / BreakArchitecture._step.
- 확인된 차이: 20봉 채널 돌파 뒤 원래 경계에 실제 touch를 요구한다. 이후 retest 고가를 종가로 넘겨야 하며, 그 전에 채널 안 종가 또는 retest 저가 이탈이면 setup을 지운다. 따라서 기준선 위에서 얕게 멈춘 되돌림은 이 경로로 거래할 수 없다.
- 분류 정정: 이것은 20봉 채널/재시험 모델이며 session open/stretch 기반 ORB가 아니다. Crabel의 연구 초안은 일봉·다음 시가 청산·비용 전 비교이므로 15m crypto net 성과로 전용하지 않는다.
- 첫 검증축: 기존 literal-retest는 보존하고, 원자료의 얕은 breakout pullback에 대응하는 독립 경로를 정의한다. sweep 후 회복은 또 다른 경로이므로 동시에 섞지 않는다.
- 필요한 기여분해: breakout → shallow/literal/overshoot → reclaim → fill의 조건별 집계, 기다리다 놓친 기회와 false-break 증가를 함께 측정한다. 허용 오차 숫자를 결과에 맞춰 완화하지 않는다.

## 4. Supertrend 30m
- 기준 자료: TradingView 공식 Supertrend 계산 및 용도. 이 문서는 지표 명세이며 원저자의 완전한 수익형 playbook이 아니다.
- 출처: https://www.tradingview.com/support/solutions/43000634738-supertrend/
- 코드: backend/research/rebuild/scalp7_supertrend_architecture_v2.py / _step, _advance_setup, exit_update.
- 확인된 내용: ATR10*3 밴드와 native line trailing이 이미 있다. 여기에 '트레일링을 처음 추가한다'는 제안은 중복이다.
- 확인된 차이: ATR 첫 값에서 현재 코드는 종가/중간값으로 방향을 초기화한다. 공식 예시의 초기 방향 처리와 동일하지 않다. 이 차이의 경제적 크기는 아직 산출하지 않았다.
- 우선 검증: 초기값·갭 reset·방향 전환의 산식 정합성을 PnL과 무관하게 확인한다. native band 수정이 필요하다면 별도 identity로 남긴다.
- 개선 가설: 방향/위험관리 부품으로서의 기여와 현재 독립 impulse/pullback 진입의 기여를 분리한다. 같은 추세에서 반복해서 local reclaim을 사는 부분이 비용을 키우는지는 별도 계수해야 한다. Top7 지위를 임의로 삭제하지 않는다.

## 5. Squeeze 30m
- 원자료: Simpler Trading 공식 tutorial 및 thinkorswim TTM Squeeze 문서.
- 출처: https://www.simplertrading.com/trading-education/tutorials/squeeze-indicator
- 출처: https://toslc.thinkorswim.com/center/reference/Tech-Indicators/studies-library/T-U/TTM-Squeeze
- 코드: scalp7_positive_lanes_v2.py; scalp7_source_components_v1.py.
- 일치하는 부분: BB/KC 압축 해제와 모멘텀, 두 번 약해지는 모멘텀의 청산 방향은 공식 설명에 대응한다. 지표 전체 계산이 플랫폼과 수치적으로 동일하다는 별도 증명은 아니다.
- 자체 추가: PANIC-only, LONG-only, EMA8/21/34 정렬, ATR/cost4.0. 원문의 필수 조건이라고 표시하지 않는다. 각 조건이 제거한 기회의 경제성은 아직 분리하지 않았다.
- PR1339 보존: '4봉 후 미수익' 청산과 늦은 30m 보완 진입 조합은 재튜닝하지 않는다. Brooks의 high2 정의와 우리의 두 번 종가 reclaim은 동일하지 않다.
- 첫 검증축: 같은 완료 30m fire/방향 문맥 아래 첫 15m 되돌림 진입을 별도 대조군/child로 결속한다. 30m 신호가 실제 공개되기 전의 15m 봉을 사용하지 않는다.
- 중요 실행 계약: 15m 진입으로 바꿔도 30m expansion 유효시간과 30m 모멘텀 청산을 임의로 절반으로 줄이지 않는다. 신호 발생 시각, entry 시각, lifecycle 기준 TF를 별도 기록한다.
- 필요한 기여분해: 같은 origin별 진입지연, 초기 위험거리, 비중복 기회, 기존 포지션 점유로 거절된 기회, winner 보존. 직후 손실 및 매매 횟수 증가는 함께 보고한다.

## 6. Cross-sectional MR V1 30m
- 원자료: Gatev/Goetzmann/Rouwenhorst의 pairs trading 연구; Avellaneda/Lee의 residual mean reversion; Yeo/Papanicolaou의 회귀시간 위험 연구.
- 출처: https://www.nber.org/papers/w7032
- 출처: https://cims.nyu.edu/ams/abstracts/avellaneda.html
- 출처: https://journals.sagepub.com/doi/10.3233/RDA-170132
- 코드: scalp7_mr_formation_v2.py / _control_signals, exit_update, _fit_prepared, exit_reason.
- 확인된 내용: V1은 6h 수익률 최상/최하 종목의 3% 이상 격차 및 수축을 사용하며 0.5 long/0.5 short다. 이는 동적 cross-sectional reversal이며 고정 pairs trading이나 beta-neutral residual 모델과 같지 않다.
- 표현상 핵심: trailing 6h 수익률의 분모는 매봉 바뀐다. 그 격차의 재확대를 entry-anchored 포지션 손익의 악화와 동일시할 수 없다. 이는 산식의 차이이며 원래 지표가 무조건 잘못됐다는 판정은 아니다.
- 첫 검증축: 원래 V1 진입/종목선택/비용을 유지하고, 청산 판단을 위한 고정 pair의 entry-anchored spread 관측을 별도 추가한다. 재확대 판정과 실제 양 leg 경제성이 언제 불일치하는지 먼저 계수한다.
- 별도 연구: factor hedge/잔차 모델은 V1의 단순 튜닝이 아닌 별도 donor다. 1주 formation/4h max hold 모델에서는 추정 회귀시간과 4h 보유의 정합성을 먼저 검토한다. 약한 fit을 통과시키거나 z threshold를 완화해 거래를 만들지 않는다.

## 7. Micro EDGE 15m
- 원자료: Cont/Kukanov/Stoikov, The Price Impact of Order Book Events.
- 출처: https://arxiv.org/abs/1011.6402
- 코드: scalp7_micro_decision_v2.py / MicroDecision; scalp7_micro_decision_v3.py / ClockMicroDecision.
- 확인된 내용: 현재는 실제 체결가격의 break/retest/reclaim이다. 코드가 L2/수량/aggressor-side/full-tape 사용을 주장하지 않는다고 명시한다. V3는 시각 검증 보강이지 OFI 추가가 아니다.
- 개선 전제: 실제 best bid/ask 가격과 잔량 및 변화 이벤트를 출처/단위/시퀀스와 결속해야 한다. aggressive flow를 더하려면 별도로 체결방향 의미를 확인한다. OHLC나 단순 가격상승/하락을 주문흐름으로 위장하지 않는다.
- 첫 검증: 동일 시간대 가격변화 설명과 다음 15m/30m 구간의 비용 후 예측력을 분리한다. 원 논문의 짧은 구간 price impact를 15m 선물 수익 증명으로 취급하지 않는다.
- price-only 원형은 대조군으로 유지한다. 호가 자료가 미결속이면 진짜 OFI 경제평가는 NOT_RUN으로 표시한다.

## 우선순위와 다음 비교의 완료 조건
1. Keltner ADX 시간순서 대조 및 Squeeze 30m 문맥/15m 진입 계약: 기존 양수 원형의 기회를 덜 놓치고 승리를 보존하는 방향.
2. Rider GMMA 문맥 결속: 현재 일반 4봉 impulse 모델과 donor 상태 모델을 구분.
3. Break shallow-pullback, MR anchor/horizon 진단: 단일 경로/단일 측정축부터.
4. Supertrend 역할/초기값 검산; Micro는 실제 quote/flow 자료 결속과 병렬.

계획된 비교는 실행 전 후보 ID, 원문 규칙, 자체 해석, 원형, 변경축, 비용, TF, 데이터 해시, 구간, 금지 반복, 예산을 고정해야 한다. 이 보고서는 새 실행 예산이나 미시작 Work의 실행 증거를 대신하지 않는다.

공통 보고: T/Tday, WR, gross/T, cost/T, net/T, 총 net, PF, DD/연패/손실 tail, 미완료 포지션, winner 보존, 원형누락/추가거래, 월/심볼 집중, exposure·점유. 계좌곡선이 없으면 연구 명목 bps와 계좌수익률/MTM DD를 구분한다. 동일 조건 대조가 없으면 기존성과와 새성과를 전후 개선으로 계산하지 않는다.

Chat 담당: 원자료→코드 대조, 원문 사례와 상태전이/trigger 정합, 독립 변경축 설계 및 짧은 검산.
Work 담당: 고정 후보의 15m/30m source/fill 결속, 공통원천 전체 시간순 재생, rolling/fresh, 독립 경제검산·CI/PR. 실제 실행/예약 영수증 없이 진행 중이라고 보고하지 않는다.

원자료에 가까운 것이 자동으로 더 수익성 높다는 결론은 아니다. 일치성 검사는 무엇을 시험했는지 분명하게 만들며, 채택은 비용 후 경제성·위험·표본과 독립 검증으로 판단한다.
