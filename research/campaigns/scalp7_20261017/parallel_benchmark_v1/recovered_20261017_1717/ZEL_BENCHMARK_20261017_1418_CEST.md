# ZEL 독립 벤치마킹 5회차 — 2026-10-17 14:18 CEST

**상태:** 연구전용 / 경제실험 실행 0회 / 유료 AI·시장 API 호출 0회 / 원형 전략 및 경제 OWNER 불변. GitHub 전용 연구 브랜치에 새 파일을 저장하려 했으나 쓰기 안전검사에서 거부되어 **이 파일만 로컬에 보존**했다. GitHub 반영·커밋 성공을 주장하지 않는다.

## 재개·중복 경계
기존 브랜치 `research/parallel-benchmark-20261017`의 `RESEARCH.md` (blob `4453106d4dee89e0eb2a9e3808d459b51df6665d`), `BENCHMARK_20261017_1222_CEST.md` (blob `77a2afcd6beb0b1d9a52e4ce5ebf824370235e35`), `BENCHMARK_20261017_1320_CEST.md` (blob `4bd96ffea919aadee64a66f53bc12bb1b7208a08`)를 먼저 읽었다. 이전 HG/ADX/Squeeze·상대강도·VectorBT gap 연구는 신규 발견으로 재등록하지 않는다.

## B01 — BingX 조건부 손절의 가격 기준과 실제 체결은 분리
**SOURCE_FACT**: BingX 공식 `Perpetual Futures | Introducing Position TP/SL` (2023-12-14), https://bingx.com/en/support/articles/26392412034713 . Position TP/SL은 **Mark/Last/Index** 중 선택된 가격을 트리거 기준으로 삼을 수 있지만 트리거가 충족되면 *시장가* 청산하여 실제 체결가격은 보장하지 않는다. 이 문서는 해당 상품이 Hedge Mode에서 사용되며 One-Way Mode는 지원되지 않는다고 적는다. 이를 모든 손절 주문 유형으로 일반화하지 않는다.

**CODE_OBSERVATION**: `backend/research/rebuild/scalp7_execution_v2.py` (Git blob `11f7d9e632741dedb536035966f6c7a68befa38f`)는 한 OHLC 프레임에 `bar.low<=stop`/`bar.high>=stop`을 적용하고, stop-first·불리한 갭 시가 체결·완성봉 뒤 다음시가 청산을 모델링한다. `scalp7_source_data_v2.py` (blob `9e793d943a079e477772565f05b8fa456b97ef6e`)는 `/openApi/swap/v3/quote/klines`를 원천으로 사용하지만 이 자료만으로 해당 candle이 Last/Mark/Index 중 어떤 가격인지 증명하지 못했다.

**HYPOTHESIS / 리스크:** Squeeze의 확정봉 `signal-low` 구조 청산과 거래소의 Mark 기반 조건부 SL은 동일 트리거·체결이 아니다. 실행 정확도 검증에 `order_family`, `candle_price_basis`, `trigger_price_type`, `trigger_available_ts`, `trigger_witness_ts`, `actual_fill_ts`, `actual_fill_price`를 구분해야 한다. 단일 OHLC 연구 엔진의 확정 버그 판정은 아니다. 현재 매매 연결과 주문형태는 검증되지 않았다.

## B02 — 일반 손절과 별도 Guaranteed SL은 동적 수정 제한
**SOURCE_FACT**: BingX 공식 `Perpetual Futures | Exclusive Guaranteed Price Launched...` (2023-08-01), https://bingx.com/en/support/articles/21313115553945-perpetualfuturesexclusiveguaranteedpricelaunchedtopreventslippagelosses . 일반 stop-market은 급변 시 불리하게 체결될 수 있고, stop-limit은 미체결 위험이 있다. 별도 요금의 *Guaranteed SL*은 상품 지원 시 지정 손절가를 보장할 수 있지만 공식 설명상 **한 번 설정한 SL 파라미터를 수정할 수 없다**. 종목 지원 및 수수료는 거래소가 변경할 수 있다. 문서의 BTC 26,500 진입/25,840 손절/25,472.7 실제 급락 예시는 **교육 사례이지 ZEL 가격자료가 아니다**.

**CODE_OBSERVATION**: `scalp7_positive_lanes_v2.py` (blob `79b9934b471cbe0f4342b265c90b2c9c8884f52c`)는 Keltner의 관측 MFE≥1R에서 BE/비용 보전 수준으로 stop을 끌어올리고 MFE≥3R에서 runner trailing stop을 추가 갱신한다. `scalp7_execution_v2.py` 역시 콜백 `next_stop`을 매봉 갱신한다. **수정 불가능한 Guaranteed SL 하나를 현재 동적 stop과 동일한 주문 상품으로 가정하는 것은 부적절**하다. 재발주·취소 시 보호 공백/비용 문제는 검증되지 않았다. 이 근거로 새로운 손절 후보를 만들거나 기존 손익표에 보장체결을 넣지 않는다.

## B03 — 공식 펀딩 정산 시각 × 현행 ZEL 1회 reserve의 범위
**SOURCE_FACT**: BingX 공식 `Perpetual Futures | Fee Schedule` (원문 2020-04-08), https://bingx.com/en/support/articles/360046487573-Perpetual%2520Futures%2520%257C%2520Fee%2520Schedule/ . 기본 정산은 00:00/08:00/16:00 (UTC+8)로 설명되며 실제 정산 완료에 약 1분 지연이 생길 수 있어 명목 정산 시각 직전·직후 보유 여부와 수수료 부담이 정확히 일치하지 않을 수 있다. 당시 정책 문서이며 모든 2026 종목/시각의 보증은 아니다.

**STORED_DATA_ARITHMETIC**: `SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json` (blob `87ca53109d19d4ad354f16706d9eecd54da5f556`)을 읽어 저장된 2026-09-15 BingX 관측의 BTC, ETH, SOL, XRP, LINK, DOGE **각 100개 펀딩 시각**을 검사했다. 각 종목에 99개 인접 간격이 모두 **8시간**으로 나타났다. 스냅샷은 `p95(abs(fundingRate))=1bps`를 거래당 **단 1회** reserve로 포함하며, 실제 기간별 부호·정산 수·계좌 펀딩원장 복원이 아니라고 스스로 제한한다. 비용 1x는 BTC/ETH **14bps/왕복**, 다른 4종 약 **14.02~16.73bps/왕복**이다.

Keltner 동결 `max_hold_bars=25` × 30분은 최대 약 **12.5시간** 보유해 당시 8시간 정산 체계상 **최대 2회** 정산을 가로지를 수 있다. Squeeze `max_hold_bars=11` × 30분은 최대 약 **5.5시간**이므로 같은 주기에서 최대 1회다. 실제 포지션은 조기종료될 수 있으며 정산 부호가 +/−로 변하므로 비용 보수적/낙관적 방향을 결과 없이 단정하지 않는다.

**검증 항목:** `position_side, entry_ts, exit_ts, settlement_actual_ts, signed_funding_rate, notional_at_settlement, held_at_settlement, source_clock`, 그리고 정산증거 결손. 전략 연구의 기존 1x/2x 비용 스트레스는 유지하되 실제 체결/펀딩 계좌손익으로 재명명하지 않는다.

## 네 축 연결·반증
- **Keltner/HG:** B02는 기존 BE/trailing을 Guaranteed SL 한 주문으로 이식할 수 없다는 주문의미 반례, B03은 최대 보유시간이 펀딩 1회 reserve 범위를 넘어설 수 있다는 비용 검증 결손이다. 기존 fresh-touch/ADX 가설·원형은 불변.
- **Squeeze:** B01은 `signal-low`가 완성봉 관찰값일 뿐 Mark/Last/Index 조건부 주문 트리거와 자동 동일하지 않다는 결속 문제. 음수 모멘텀 H01의 손실인과는 여전히 미입증.
- **청산·큰 승리:** 일반 시장가·미체결 위험 있는 stop-limit·유료 보장 SL을 같은 체결모델로 합쳐 계산하면 손실 회피와 회복 승리 훼손이 왜곡될 수 있다. 기존 경제 평가를 반복 실행하지 않았다.
- **차트/다중시간봉/봇:** 가격 봉의 `price_basis`, `event_ts`, `available_at`, 주문 `trigger_reference`는 서로 분리해야 한다. 새로운 피보나치/HTF 필터나 거래 후보는 만들지 않았다.

## 인계·최종 상태
비경제 필드만 제안: `stop_trigger_reference=MODEL_OHLC`, `native_order_family=UNVERIFIED`, `native_trigger_series=UNVERIFIED`, `observed_signed_funding=NOT_RECONSTRUCTED`; 이는 향후 연구 경제영수증에 현존하는 불확실성 라벨을 붙이기 위한 것이다. 새 후보/매개변수/상한/경제 OWNER/원형/경쟁 claim/워크플로/master/Paper/Live/주문/배포 변경 **0건**. 연구 브랜치 GitHub 쓰기는 차단되었으므로 이 로컬 파일만 남겼다. 새로운 successor 경제실행 **0회**, 성과 **NOT_MEASURED**. CF·GS 실거래 최소자료는 검증하지 않았으므로 거래결정 [UNSURE]+HOLD.
