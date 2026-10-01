# 원래25개 구현·측정 후속 상태

scope_key=G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1.
PR1345 merge 7bb11442454053c011082fd6034d965631e719ef를 보존하고 현재 증거만 새 표에 추가했다. 과거 MODEL_CLOSURE/COVERAGE는 덮어쓰지 않았다.

실제 새 코드 연결은 HG·Kell·Gajjala 3개 bounded 연구 caller가 원래4행을 덮는다. Gajjala 두 행은 한 계보다.
거래량5행의 원 필드 입장 adapter와 상품4종 경계 코드를 구현·시험했으며, 경계 검사를 원형 body caller 완성으로 집계하지 않는다.
원래25 ID와 기존 미완료19 ID를 그대로 승계한다. 이번 caller/입장 계약의 부분 구현 완료를 원형 전체·G4 완료로 표시하지 않는다.

PR1345 ST_CONTROL/ST_TRAIL/SR_CONTROL/SR_RETEST/NOISE_BASELINE은 이미 각1회 COMPLETED, 누적5/5·잔여0이다.
trend_rider/session_bias는 같은 NOISE_BASELINE 1회다. 이전 문서의 미실행 문구는 역사 기록이며 새 예약의 근거가 아니다.
신규 FULL·genuine-history 전략 probe·탐색·주문/LIVE·승격은 모두0이다. 신규 전략 실행에서 산출한 T/WR/PnL/DD는 없다. 기존 Noise 초기 두 구간의 저장 NAV·DD 회수는 측정 결손 수선이며 신규 전략 개선으로 집계하지 않는다.

가격자료 물리 단절은 2026-02-13 20:32~20:35 UTC 6심볼 각4분이며 raw 응답에도 없다. 한정 회수로24분 중0분 복구했다.
미확정 소유권과 기존 결과는 보존한다. episode cohort·sampled NAV 경로와 원천 결측을 구분하는 실제 진단·admission·prefix valuation 코드를 연결했다.
연속 독립 segment의 신규 경제결과는 아직 없다. 기존 Noise validation·rolling_1의 sampled reference NAV·DD는 저장 원장에서 회수했고, cohort 경계와 펀딩 제외 한계를 유지한다. 이를 신규 전략 실행·수익 개선으로 세거나 독립 구간을 연속 전체 계좌 성과로 합산하지 않는다. funding은 UNKNOWN_NOT_ZERO다.

| 원래 ID | 이번 실제 연결/회수 | 자료 부재·증거 미확보 | 명세 미결정 | 구현 미완료 | 이번 경제 |
|---|---|---|---|---|---|
| alpha_combo | 기존 부품·결과 보존; 신규 코드 수선 없음 | 새 자료 부재로 일괄 차단한 항목 아님 | 유효 SSOT의 B×B·grade·구성/상관·행동 중복 기준 충족 필요. | 고정 배정 부품 이후 실제 composition/portfolio caller 미완료. | 미측정; 기존 실패/parent 보존 |
| anchor_vwap_trend | adapt_volume_frame / evaluate_volume_component / admit_observed_base_frame | canonical volume 단위 UNKNOWN; 저장 객체 schema의 역사적 단위 권위 미확보. / 실측 quote volume ABSENT; price×unknown volume 합성 금지. | 자동 causal anchor 사건 선정과 독립 전략/host 적용 역할. | 자동 anchor·수량·주문 수명·전체 위험/청산 caller. | 미측정; 기존 실패/parent 보존 |
| bb_revert | adapt_volume_frame / evaluate_volume_component / admit_observed_base_frame | canonical volume 단위 UNKNOWN; 저장 객체 schema의 역사적 단위 권위 미확보. | BBIII 확인/만료 해석과 독립 전략/host 적용 역할. | 실제 관리 정책 동결과 주문·수량·전체 청산 caller. | 미측정; 기존 실패/parent 보존 |
| break_and_continue | compile_model / create_order / management_update / run_fixture / admit_observed_base_frame; GAJJALA_FLAG15_CRYPTO_PARTIAL_PIVOT_V1 | canonical volume 단위 UNKNOWN이므로 실제 자료 admission 차단. / 상품 가격격자 원천·native 주식 scanner/universe 자료 미확보. | 원 Gajjala 재량 전체 방법이 아니다. 15m 완료 확인 후 시장가·crypto HTF selection·관리 비율은 선언한 가설. / native ORB/Short Skirt 경로는 이번 Gajjala 모델과 다르며 시간축을 몰래 교체하지 않았다. | genuine 경제 입력/비용/기간 freeze·허가된 partial gateway 미완료; 동일 alias를 독립 모델로 중복 실행하지 않는다. | 미측정; 기존 실패/parent 보존 |
| ema_ribbon_scalp | compile_model / create_order / management_update / run_fixture; KELL_BASE_BREAK_HTF15_PARTIAL_PIVOT_V1 | 당시 상품 가격격자 원천과 전체 계좌 비용/funding 자료 결속 필요. / 원 native 주식 PIT scanner/universe·실계좌 자료는 확보되지 않았다. | 원 Kell 전체 6단계·재량 관리 복제가 아니다. 1h 4봉 selection·pivot1L1R·30%·3봉 등은 선언한 수치화 가설. | genuine 경제용 입력 검수·코드/자료/비용/기간 동결 및 승인 원장 gateway는 준비 미완료; bounded 인공 caller만 제공. | 미측정; 기존 실패/parent 보존 |
| fvg_revert | fvg_receipt_adapter | 실제 resting order/fill 원장·queue/size 원자료 없음. | 원 모든 차트 사례·정성 displacement·유효기간/목표·부분 관리 의미 미완결. | 목표·부분청산·전체 위험관리 source caller 미완료. 이번 adapter는 FVG body caller 완성이 아니다. | 미측정; 기존 실패/parent 보존 |
| grid_rebalance | value_native_spot_ledger | native spot 체결·재고·원 시장 자료 없음. / native DGT 직접 Python callable bytes는 관련 repo 저장 범위에 없고 URL/진단 기록만 있음. | 명시된 native DGT 버전/함수 호출·capital/reset/외부 cash flow 정책 및 경로 민감도 계약 필요. | DGT runner/callee 서명 정합 수선·grid order/reset·외부 cash flow-aware 회계 caller 미완료. | 미측정; 기존 실패/parent 보존 |
| keltner_trend | compile_model / create_order / create_adapter / entry_update / exit_update / run_synthetic_fixture; HG1997_FIRST_PULLBACK_STOP_V1 | 당시 상품 가격격자와 자료/비용/기간·funding 결속 필요. | 30m crypto·20봉 자격수명·ADX25 재무장·1tick swing proxy·1L1R trailing은 선언 가설이며 원 전체 재량법 인증 아님. | 경제용 FULL gateway/새 identity freeze·공통 계좌/실자료 integration 경로 미완료; fixture caller는 FULL을 제공하지 않는다. | 미측정; 기존 실패/parent 보존 |
| liquidity_sweep | bind_price_grid | 역사적 instrument PRICE_GRID 원천/유효기간 변경 이력의 독립 인증 미확보. / 실제 BBO/sequence/queue 원자료 미확보; 가격 패턴으로 합성하지 않음. | Anti impulse continuation과 Soup false-break를 섞지 않는다; 가격격자의 tick을 체결 tape로 해석하지 않는다. / OFI/BBO/absorption은 가격 Soup와 별도 역할·원 단위를 유지한다. | 기존 연구 model caller의 가격격자 실제 원천 binding과 genuine freeze/admission 미완료; 전체 원형 방법 인증 없음. | 미측정; 기존 실패/parent 보존 |
| mfi_rsi_div | adapt_volume_frame / evaluate_volume_component / admit_observed_base_frame | canonical volume 단위 UNKNOWN; 저장 객체 schema의 역사적 단위 권위 미확보. | RSI/MFI divergence 이후의 가격 확인과 구체적인 host 조치. | 진입/관리 대조군 및 주문·위험/청산 caller. | 미측정; 기존 실패/parent 보존 |
| obv_trend | adapt_volume_frame / evaluate_volume_component / admit_observed_base_frame | canonical volume 단위 UNKNOWN; 저장 객체 schema의 역사적 단위 권위 미확보. | 진입·보유·위험 중 변경할 host 조치와 동일 조건 대조군. | 검수된 거래량 부품을 선정 host 행동·대조군에 연결. | 미측정; 기존 실패/parent 보존 |
| pivot_reversal | 기존 부품·결과 보존; 신규 코드 수선 없음 | 새 자료 부재로 일괄 차단한 항목 아님 | 거래할 Kell reversal phase·재량 지지 수치화·원 관리 선택 미결정. | Reversal phase 주문 수명·구조 stop·규모/전체관리 caller 미완료; 새 Kell base-break와 같다고 집계하지 않는다. | 미측정; 기존 실패/parent 보존 |
| range_fade | bind_price_grid | 역사적 instrument PRICE_GRID 원천/유효기간 변경 이력의 독립 인증 미확보. | Anti impulse continuation과 Soup false-break를 섞지 않는다; 가격격자의 tick을 체결 tape로 해석하지 않는다. | 기존 연구 model caller의 가격격자 실제 원천 binding과 genuine freeze/admission 미완료; 전체 원형 방법 인증 없음. | 미측정; 기존 실패/parent 보존 |
| rbreaker_like | 기존 부품·결과 보존; 신규 코드 수선 없음 | 새 자료 부재로 일괄 차단한 항목 아님 | native1m와15m/30m 결정층 관계·native position/OCO 뜻 미결정. | 실제 position/OCO·trailing·수량·EOD caller 미완료; genuine1m가 없어서 막혔다고 표시하지 않는다. | 미측정; 기존 실패/parent 보존 |
| rsi_swing_fail | 기존 부품·결과 보존; 신규 코드 수선 없음 | 새 자료 부재로 일괄 차단한 항목 아님 | 기존 실패를 넘는 근거 있는 단일 인과 축 또는 host 역할 미선정. | 선정 host 행동/대조군에 맞춘 주문·위험·전체관리 caller 미완료. | 미측정; 기존 실패/parent 보존 |
| scalp_snap | compile_model / create_order / management_update / run_fixture / admit_observed_base_frame; GAJJALA_FLAG15_CRYPTO_PARTIAL_PIVOT_V1 | canonical volume 단위 UNKNOWN이므로 실제 자료 admission 차단. / 상품 가격격자 원천·native 주식 scanner/universe 자료 미확보. | 원 Gajjala 재량 전체 방법이 아니다. 15m 완료 확인 후 시장가·crypto HTF selection·관리 비율은 선언한 가설. / native ORB/Short Skirt 경로는 이번 Gajjala 모델과 다르며 시간축을 몰래 교체하지 않았다. | genuine 경제 입력/비용/기간 freeze·허가된 partial gateway 미완료; 동일 alias를 독립 모델로 중복 실행하지 않는다. | 미측정; 기존 실패/parent 보존 |
| session_bias | followup_admission / window_measurement_status / value_trusted_prefix | 동일 거래소/상품 2026-02-13 20:32~20:35 UTC 6심볼 각4분이 raw에도 빠짐; 한정 회수에서 24분 중0분 복구. / funding UNKNOWN_NOT_ZERO; 미확정 소유권 삭제/0손익 처리 금지. | 공통 평가 계약 확정; 이번 미결정 없음 | 기존 caller 완료·보존; 신규 구현 공백 없음 | 신규 전략 경제 미실행; PR1345 완료 승계; 저장 초기 NAV·DD 회수 |
| squeeze_break | 기존 부품·결과 보존; 신규 코드 수선 없음 | 새 genuine fresh/rolling 검증 자료 근거 미확보. | 새 인과 축 또는 native options/day-weekly 관리 adaptation 미결정. | 기존 frozen BE1R 이후 추가개선 후보 caller 미구현. 완료된 High2/실패 반복하지 않는다. | 미측정; 기존 실패/parent 보존 |
| sr_levels | followup_admission / window_measurement_status / value_trusted_prefix / segment_inputs / run_synthetic_comparison / freeze_comparison / run_authorized_comparison | 동일 거래소/상품 2026-02-13 20:32~20:35 UTC 6심볼 각4분이 raw에도 빠짐; 한정 회수에서 24분 중0분 복구. / funding UNKNOWN_NOT_ZERO; 미확정 소유권 삭제/0손익 처리 금지. | 공통 평가 계약 확정; 이번 미결정 없음 | 기존 caller 완료·보존; SR 신규 결속/승인 gateway 구현됨 | 신규 전략 경제 미실행; PR1345 완료 승계 |
| supertrend_pullback | followup_admission / window_measurement_status / value_trusted_prefix | 동일 거래소/상품 2026-02-13 20:32~20:35 UTC 6심볼 각4분이 raw에도 빠짐; 한정 회수에서 24분 중0분 복구. / funding UNKNOWN_NOT_ZERO; 미확정 소유권 삭제/0손익 처리 금지. | 공통 평가 계약 확정; 이번 미결정 없음 | 기존 caller 완료·보존; 신규 구현 공백 없음 | 신규 전략 경제 미실행; PR1345 완료 승계 |
| trend_ma_macd | 기존 부품·결과 보존; 신규 코드 수선 없음 | 새 자료 부재로 일괄 차단한 항목 아님 | 선택 계산과 어느 host의 어떤 조치를 바꿀지 단일축 역할 미선정. | host action·위험/전체 관리·대조군 caller 미완료. | 미측정; 기존 실패/parent 보존 |
| trend_rider | followup_admission / window_measurement_status / value_trusted_prefix | 동일 거래소/상품 2026-02-13 20:32~20:35 UTC 6심볼 각4분이 raw에도 빠짐; 한정 회수에서 24분 중0분 복구. / funding UNKNOWN_NOT_ZERO; 미확정 소유권 삭제/0손익 처리 금지. | 공통 평가 계약 확정; 이번 미결정 없음 | 기존 caller 완료·보존; 신규 구현 공백 없음 | 신규 전략 경제 미실행; PR1345 완료 승계; 저장 초기 NAV·DD 회수 |
| turtle_trend | turtle_daily_filled_units | 원 trading-day 다시장·PIT 상품/위험·실계좌 자료 미확보. 기존 minute를 UTC daily로 집계할 수 있다는 사실은 구현 장애와 구분한다. | System2 reference를 선택한 input boundary만 닫았다. 전체 Scalp7 실행 adaptation·상관/방향 위험 정책은 명세 미완결. | 실제 pyramiding·entry/exit·portfolio order caller와 System1 virtual 마지막 돌파 승패 ledger 미완료. | 미측정; 기존 실패/parent 보존 |
| vol_spike_fade | 기존 부품·결과 보존; 신규 코드 수선 없음 | native stock/borrow/원 시장 자료 미확보; VWAP을 쓰면 volume 원 단위도 미확보. | native stock 또는 crypto price-only 역할 및 short 위험/선정 명세 미결정. | 실제 선정·분할청산·규모·전체lifecycle caller 미완료. | 미측정; 기존 실패/parent 보존 |
| vwap_revert | adapt_volume_frame / evaluate_volume_component / admit_observed_base_frame | canonical volume 단위 UNKNOWN; 저장 객체 schema의 역사적 단위 권위 미확보. / 실측 quote volume ABSENT; price×unknown volume 합성 금지. | 원 parabolic 선정·crack 문맥과 causal anchor 및 독립/host 역할. | 원 선정 문맥과 전체 주문·수량·위험/청산 caller. | 미측정; 기존 실패/parent 보존 |

실제 함수·증거 파일·각 범주의 상세 이유는 COVERAGE.json에 저장했다. HG 검증은 implementation/hg/HG_CLOSURE.json, KG 검증은 implementation/kell_gajjala/SYNTHETIC_EVIDENCE.json, volume은 implementation/volume/synthetic_tests.txt, 상품은 implementation/products/SYNTHETIC_PRODUCT_REGRESSION.xml을 참조한다.

원래 미완료19(원형 전체 기준) 보존: alpha_combo, anchor_vwap_trend, bb_revert, break_and_continue, ema_ribbon_scalp, fvg_revert, grid_rebalance, keltner_trend, mfi_rsi_div, obv_trend, pivot_reversal, rbreaker_like, rsi_swing_fail, scalp_snap, squeeze_break, trend_ma_macd, turtle_trend, vol_spike_fade, vwap_revert.

추가 경제배치의 정확 identity·변경축·자료/비용/기간 해시·대조군 재사용 및 최소 횟수는 단일 담당의 신규 배치 보고에 결속한다. 이 표는 새 실행을 예약하거나 허가하지 않는다.
