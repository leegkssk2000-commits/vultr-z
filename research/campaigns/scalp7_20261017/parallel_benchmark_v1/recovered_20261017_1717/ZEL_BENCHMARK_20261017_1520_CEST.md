# ZEL 독립 병렬 벤치마킹 — 2026-10-17 15:20 CEST

**상태:** 공개 공식문서 조사만 수행. 경제실험·시장 API·유료 모델 API·주문·배포 0회. 기존 경제 OWNER `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`, 기존 전략, 소비원장, master 불변. 비용후 순손익 개선 `NOT_MEASURED`.

## 재개·중복검사
연구 브랜치 `research/parallel-benchmark-20261017`의 `RESEARCH.md` (blob `4453106d4dee89e0eb2a9e3808d459b51df6665d`), `BENCHMARK_20261017_1222_CEST.md` (blob `77a2afcd6beb0b1d9a52e4ce5ebf824370235e35`), `BENCHMARK_20261017_1320_CEST.md` (blob `4bd96ffea919aadee64a66f53bc12bb1b7208a08`)를 먼저 읽음. 이전 로컬 14:18 조사에서 확인한 BingX 일반 손절의 Mark/Last/Index·Guaranteed SL 수정 불가·8h 펀딩 결손은 신규 발견으로 재등록하지 않음.

원형 정적 코드 재조회: `scalp7_positive_lanes_v2.py` Git blob `79b9934b471cbe0f4342b265c90b2c9c8884f52c`, `scalp7_execution_v2.py` blob `11f7d9e632741dedb536035966f6c7a68befa38f`, 비용스냅샷 blob `87ca53109d19d4ad354f16706d9eecd54da5f556`.

## B04 — BingX Perpetual Futures Trailing TP/SL
**SOURCE_FACT:** BingX 공식 공개 HTML 전문, 2024-12-26 갱신. https://bingxservice.zendesk.com/hc/en-001/articles/11263240647567-Perpetual-Futures-Trailing-TP-SL-App

활성화 기준은 Mark/Last/Index 선택 가능하지만 활성화 이후 **long 청산 트리거는 Last Price가 trailing threshold 이하로 떨어지는 것**. Long trailing threshold는 `highest_price - trailing_distance` 또는 `highest_price * (1 - callback_rate)`로 설명. 트리거 후 시장가 주문도 거래 불가·시장상태 등으로 미체결될 수 있음. 원시계열 경제성적·PF/DD·거래수 미보고.

**CODE_OBSERVATION:** ZEL HG는 `MFE >= 3R`일 때 `peak - 1.25R`를 제시하되 **30분봉 현재 stop 검사를 마친 뒤** 다음봉에 유효하도록 갱신. 거래소 native trailing은 활성화 후 실시간 극값 기준이라 같은 30분봉 안의 고점→하락 선후가 달라질 수 있음. 이전 조사에서 별도 Guaranteed SL의 수정 제한을 확인했지만, 그것이 모든 BingX trailing 상품의 부재를 뜻하지 않음. Native 주문과 ZEL 3R runner의 API 호출 가능성/계정 적용/체결동등성은 미검증.

**반증:** 같은 고점 후 급락에서도 거래소 native의 실시간 트리거와 연구 엔진의 지연갱신 순서가 달라 비용후 결과가 나빠질 수 있음. 정상 눌림에서 조기 청산된 큰 승리도 기록해야 함.

## B05 — BingX Auto Breakeven
**SOURCE_FACT:** BingX 공식 공개 HTML 전문, 2026-06-18 갱신. https://bingxservice.zendesk.com/hc/en-001/articles/16351526106255-Auto-Breakeven-Lock-In-Your-Principal-Once-Profit-Targets-Are-Reached-No-Manual-Stop-Loss-Adjustments-Needed

USDⓢ-M Perp Futures Pro 앱/웹에서 목표가격 활성화 뒤 손절을 **거래수수료+펀딩을 포함한 동적 BE 추정가**로 옮김. 수량·펀딩 변화 시 다시 계산. 시장가 주문이므로 실제 0손실 또는 가격 보장 아님. API 동등 기능의 존재는 이 문서로 증명하지 못함.

**CODE_OBSERVATION:** ZEL `exit_update`는 `entry * [1 + side * (frozen_cost_bps + HG_lock_2bps)/10000]`라는 비용 시나리오를 사용하고, stop은 확정봉 이후 갱신됨. native는 비용 실현/수량변화를 반영하는 별도 의미이므로 현 비용 1회분 펀딩 reserve와 동일한 것으로 보고 전략 수익을 인증하면 안 됨.

## B06 — BingX Exit within Slippage Limit
**SOURCE_FACT:** BingX 공식 공개 HTML 전문, 2026-06-18 갱신. https://bingxservice.zendesk.com/hc/en-001/articles/16509954637455-Perp-Futures-New-Exit-within-Slippage-Limit-Feature-for-Take-Profit-and-Stop-Loss

USDⓢ-M Perp Futures Pro의 일부 TP/SL에서 최대 불리한 슬리피지를 정하면 트리거 뒤 제한가 주문이 나감. 슬리피지 상한 초과 시 **미체결 제한가가 남고 포지션도 계속 열려 있을 수 있다.** 거래소 문서는 **현재 API 거래에서는 지원되지 않는다**고 명시. Guaranteed TP/SL과 중복 불가. trailing/AutoBE까지 일반화할 근거 없음.

**HYPOTHETICAL COUNTEREXAMPLE:** Long TP/SL 청산 트리거 100, 허용 불리한 슬리피지 1%라면 매도 제한가 99; 매수호가가 97뿐이면 99에 즉시 체결되지 않음. 실제 시장기록이 아닌 인공 반례. 99에 손절 완료한 것으로 백테스트하면 미체결 포지션 손실/재진입 점유를 감춤. **가격보호가 경제적 손실 한도의 보장이 아님.**

## B07 — BingX Close by BTC Price
**SOURCE_FACT:** BingX 공식 공개 HTML 전문, 2026-03-18 갱신. https://bingxservice.zendesk.com/hc/en-001/articles/15481956987279-Perp-Futures-New-Close-by-BTC-Price-Feature-for-TP-and-SL

USDⓢ-M BTC 이외 종목의 **이미 열린 포지션**을 BTC 가격 조건으로 시장가 청산할 수 있다고 설명하며, BTC와 타 종목의 가격경로가 일치하지 않을 수 있음을 명시. 단계적 출시이며 신규 주문 진입에는 적용 안 됨; BTC 자신은 제외. 수익·PF/DD를 보고하지 않음; API 연결 여부 미검증.

**H03 COUNTEREVIDENCE:** BTC 트리거 상품 존재는 BTC가 이후 알트 수익률을 예측한다는 증거가 아님. BTC 이벤트시각·다른 종목의 당시 관측가능 가격·실제 체결시각·그 종목의 회복승리 훼손을 별도로 기록해야 하며 BTC의 미래 움직임이나 해당 종목 선택을 사후 반영하지 않음.

## 검증에 필요한 기존 trace 구분
`order_family`, `model_vs_native`, `activation_price_type`, `activation_ts`, `trailing_peak_observed_ts`, `stop_update_effective_ts`, `trigger_price_reference`, `native_trigger_ts`, `dynamic_BE_price`, `observed_fee_and_signed_funding`, `market_or_limit`, `slippage_limit_bps`, `order_sent_ts`, `fill_qty`, `fill_price`, `unfilled_remaining_qty`, `position_occupancy_until`, `posthoc_recovered_winner`.

이것은 경제 실행 계약·새 코드·새 후보를 작성하라는 승인 아닌 진단용 증거 항목. 사용자의 실제 CF·GS MinData가 없으므로 실주문/자금 결정은 `[UNSURE]+HOLD`.

## 연구축별 판정
- Keltner: native 실시간 trailing vs ZEL 완료봉 갱신, native 동적 원가보전 BE vs ZEL frozen 비용. H02 ADX 정적 경로와 별도 문제. 신규 경제 후보 0.
- Squeeze: H01 음수 momentum 손실 인과 미입증. 제한 슬리피지 주문의 **미체결/열린 포지션 반례**는 승인 signal-low/다음시가 평가의 필수 경계.
- 청산과 승리보존: 손절가격, 트리거가격, 실제 체결·잔존 포지션, 정상 회복 승리와 fat-tail 승리 훼손을 각각 분리.
- 상대강도/차트: BTC 트리거는 BTC 리더십 증명이 아니며 H03를 신규 필터로 승격하지 않음.

**저장상태:** GitHub 전용 연구 브랜치에 새 파일을 생성하려 했으나 쓰기 요청이 안전검사에서 차단됨. 이전 저장본은 변경하지 않았으며 **본 로컬 파일만 작성**. Issue1414/1334 댓글·원형·경제 OWNER·workflow·CLAIM·master 변경 없음. 경제실행 0회·경제 개선 미측정.
