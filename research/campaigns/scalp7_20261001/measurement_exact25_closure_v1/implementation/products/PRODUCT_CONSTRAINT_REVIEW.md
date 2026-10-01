# 상품·체결·원 시간축 경계 검수

scope_key=G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1.
기존 동결 파일은 보존했다. 이번 신규 FULL·역사 전략 probe·파라미터 탐색은 각각 0이다.
상품 경계 어댑터와 인공 회귀시험을 실제 작성·실행했다. 새 수익 측정과 원형 전체 caller 완료는 주장하지 않는다.

| 원래 ID | 이번 실제 수정 | 보존한 의미 | 남은 공백 |
|---|---|---|---|
| range_fade / liquidity_sweep | bind_price_grid: 원 receipt bytes SHA, symbol/venue/product, 유효기간·가용시각·증거등급 결속 | Anti/Soup의 tick은 주문 가격 증가폭 PRICE_GRID다. 체결 tick/tape·BBO·queue 자료의 확보를 뜻하지 않는다. | 당시 상품 가격격자의 실제 원천·변경 이력 인증. 기존 Anti/Soup caller에 대한 원형 전체 인증 없음. |
| fvg_revert | fvg_receipt_adapter: 기존 DetailExecutionAdapter의 RECEIPT_ONLY 경로 재사용 | 완료한 세 번째 봉 뒤 zone 활성화·선행 sweep/MSS와 주문/체결은 별도. limit touch는 fill이 아니며 잔량 취소도 보유분을 닫지 않는다. | 실제 resting order/fill 원장·queue/size·원 사례 전체 대응. 전체 FVG 전략 caller 신규 완성 아님. |
| turtle_trend | turtle_daily_filled_units: DAILY System2 55/20/N 참조와 실제/선언모형 fill 증거·시각 검사, 기존 unit-state 함수 재사용 | 55/20은 TRADING_DAY, 0.5N 추가는 직전 fill 기준, 2N stop과 실제 완료 unit 최대 4개. pending unit은 fill unit이 아니다. | System1 가상 직전돌파 승패 원장, pyramiding/exit/portfolio 주문 caller, native daily·다시장·실계좌 자료. |
| grid_rebalance | value_native_spot_ledger: 계약/fill/평가가격의 동일 venue/product=SPOT/symbol 결속, 기존 유한 현금·재고 원장 재사용 | 현물 SELL은 실제 보유량 이하, BUY는 비용 포함 가용 현금 이하. USDT 비용·실제 수량·평가 가격을 분리하며 외부 입금 지원을 암묵 추가하지 않는다. | native DGT reset/order caller와 원 코드 서명 불일치 수선, native spot 자료·경로민감도·외부 현금흐름 검산. |

원 자료를 다시 전수조사하지 않고 저장된 최종 정정과 기존 구현을 대조했다.
source_package 최종 검수의 S314/S402는 Anti를 작은 flag 이후 선행 impulse 방향 재개로 구분한다.
S309는 Soup의 20일·옛 극값 나이·tick offset과 당일/Plus One 익일 주문을 구분한다.
S304/G02는 FVG 3봉 기하와 사건 순서를 설명하며, paper 시연과 실계좌 수익 인증을 구분한다.
R07/R08은 Turtle의 일봉 System1/2·N·fill 기반 unit 구조다.
R21/V2_DGT_RUNNER/V2_DGT_LOGIC는 현물 DGT 자료이며 perp bounded-reversion 성과를 상속하지 않는다.

이번 어댑터의 입력 검사는 선언한 기계화 계약이다. SHA 일치는 공급자가 제공한 bytes의 결속이며 역사적 상품정보의 독립 진위 인증이 아니다.
SYNTHETIC_FIXTURE는 실제 과거 metadata로 승격하지 않는다. DECLARED_MODEL_FILL과 OBSERVED_FILL은 섞지 않는다.
원래 source rule, 기존 동결 구현, 새 계약의 구분과 hash는 SOURCE_CONTRACT_REVIEW.json에 기록했다.

인공 회귀시험 tests/test_scalp7_product_contracts_v1.py는 50개 PASS다.
가격격자의 과거 시각·상품·SHA 오류, FVG touch/partial/cancel/gap, Turtle DAILY/N/실제 fill 간격/기록 시각, 현물 유한 현금·재고·상품 격리를 검사했다.
PR #1346 P2 검수에서 발견한 실제 receipt→caller 계약 불일치도 수정했다.
bind_price_grid 출력에 QUOTE_PRICE_INCREMENT 단위와 canonical valid_from_ts_ms/valid_to_ts_ms를 추가하고 Anti/Soup의 기존 valid_from_ms/valid_to_ms 별칭은 동일한 값으로 보존했다.
HG/Kell/Gajjala가 요구하는 양의 유한 float tick_size를 전달하며 원 price_increment의 정확한 Decimal 표기는 price_increment_decimal에 남긴다. float overflow/underflow와 원 receipt의 단위·시간 별칭 충돌은 차단한다.
실제 Kell·Gajjala compile_model에 어댑터 receipt를 그대로 공급한 두 인공 시험에서 주문 계획 각 1개와 원 SHA 결속을 확인했고, 이후 setup에서 유효기간이 지난 receipt는 계획이 생성되지 않았다.
HG의 숫자형 tick_sizes 입력에는 어댑터의 tick_size를 직접 전달해 계획 1개를 확인했다. HG는 metadata receipt 자체를 독립 검증하는 API가 아니며 genuine_tick_receipt_verified=False를 유지한다.
현물 계산은 손으로 검산한 BUY 1@100+fee1, BUY 1@120+fee1, SELL 1@150-fee2, 잔량1@130 사례다:
cash=926, qty=1, 평균원가110, 실현gross40, 미실현20, fee4, equity1056, net56. 이는 인공 원장 산술이며 경제 T/PnL 성과가 아니다.
Black/Ruff/Mypy/immutable-source 정상 hook은 PASS다.

독립 검수에서 발견한 실제 공백 두 개를 root가 수정했다.
1. SPOT 계약 아래 PERPETUAL fill 또는 다른 venue의 가격이 들어올 수 있던 제품 경계를 차단했다.
2. Turtle의 후속 fill timestamp int 강제변환과 누락된 가용시각/증거 검사를 strict 입력 검증으로 바꿨다.
출력에서도 fill 증거등급과 최종 state 가용시각을 보존한다.

DGT 함수 불일치의 직접 원 Python bytes는 이 repo의 관련 저장 범위에 없고 기존 source_package에는 URL·검수 요약이 있다.
이를 수정한 native DGT caller가 있다고 보고하지 않는다. 관련 원 코드 version과 실제 native spot 입력이 확보되기 전까지 그 역할은 미완료다.
이번 경계 개선을 원래25개 또는 G4 전체 완료로 집계하지 않는다.
